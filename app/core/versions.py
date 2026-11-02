"""脚本版本管理：自动生成快照，随时对比与退回。

为什么需要它
------------
原来的流程是"AI 生成 → 写进编辑器 → 用户手改"，任何时候新脚本都会直接覆盖编辑器
里的旧内容。一旦 AI 改坏了（自动修复回路也可能越修越偏），就只能重来一遍
——而重来意味着再烧一次 token、且未必复现原来的版本。

设计取舍
--------
- 存**整份脚本**而不是 diff：脚本最长不过几百行，纯文本存盘最省心，
  比对时现算 unified diff，不会出现增量链断裂导致全版本失效。
- 目录形态 `versions/<key>/NNN.py` + `NNN.json`（元信息），
  key 取知识点标题（安全化后的文件名主干），这样每个知识点各自一条时间线。
- 只保留最近 MAX_PER_KEY 版：硬盘便宜，但列表太长反而没人看。
"""
import difflib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR
from .renderer import safe_stem

VERSIONS_DIR = DATA_DIR / "versions"
MAX_PER_KEY = 30          # 每个知识点最多保留的快照数
MAX_KEYS = 60             # 总知识点上限（超了清理最久未用的）

# 版本来源标签（显示在下拉框里）
LBL_GENERATE = "生成"
LBL_REVISE = "代码修改"
LBL_RENDERED = "渲染定稿"
LBL_MANUAL = "手动存档"
LBL_REVERT = "退回"


@dataclass
class Version:
    idx: int
    label: str
    ts: float
    scene_name: str = ""
    chars: int = 0

    @property
    def code(self) -> str:
        try:
            return Path(self.code_path).read_text(encoding="utf-8",
                                                  errors="replace")
        except Exception:
            return ""

    @property
    def code_path(self) -> str:
        return str(VERSIONS_DIR / self.key / f"{self.idx:03d}.py")

    key: str = ""      # dataclass 里放最后只是为了不破坏构造顺序语义，见 make()

    def time_text(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.ts))

    def display(self) -> str:
        return f"v{self.idx} · {self.time_text()} · {self.label}"


def make(idx: int, label: str, ts: float, scene_name: str,
         chars: int, key: str) -> Version:
    """构造 Version：把 key 也带进去（方便 UI 只拿一个对象就能操作）。"""
    v = Version(idx=idx, label=label, ts=ts, scene_name=scene_name,
                chars=chars, key=key)
    return v


def make_key(title: str = "", scene_name: str = "") -> str:
    """版本时间线的 key：优先用知识点标题，退化到 Scene 名。"""
    base = title or scene_name or "未命名"
    key = safe_stem(base, limit=30)
    return key or "未命名"


def key_dir(key: str, create: bool = False) -> Path:
    d = VERSIONS_DIR / key
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def add(key: str, code: str, label: str, scene_name: str = "") -> Version | None:
    """存一版。与上版内容完全相同时不重复落盘（避免刷屏）。"""
    try:
        d = key_dir(key, create=True)
        exist = sorted(d.glob("*.py"))
        if exist:
            last = exist[-1]
            try:
                if last.read_text(encoding="utf-8", errors="replace").strip() \
                        == (code or "").strip():
                    prev = list_versions(key)
                    return prev[0] if prev else None   # 内容没变，沿用最新版
            except Exception:
                pass
        idx = (int(exist[-1].stem) + 1) if exist else 1
        (d / f"{idx:03d}.py").write_text(code or "", encoding="utf-8")
        meta = {"idx": idx, "label": label, "ts": time.time(),
                "scene_name": scene_name, "chars": len(code or "")}
        (d / f"{idx:03d}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        prune(key)
        return make(idx, label, meta["ts"], scene_name, meta["chars"], key)
    except Exception:
        return None   # 版本功能不应拖垮主流程


def list_versions(key: str) -> list[Version]:
    """新版在前。"""
    d = key_dir(key)
    if not d.exists():
        return []
    out = []
    for py in sorted(d.glob("*.py")):
        idx = int(py.stem)
        meta_p = d / f"{py.stem}.json"
        label, ts, scene, chars = LBL_MANUAL, py.stat().st_mtime, "", len(py.read_text(encoding="utf-8", errors="replace"))
        if meta_p.exists():
            try:
                m = json.loads(meta_p.read_text(encoding="utf-8"))
                label = m.get("label", label)
                ts = m.get("ts", ts)
                scene = m.get("scene_name", "")
                chars = m.get("chars", chars)
            except Exception:
                pass
        out.append(make(idx, label, ts, scene, chars, key))
    return sorted(out, key=lambda v: v.idx, reverse=True)


def get_version(key: str, idx: int) -> Version | None:
    for v in list_versions(key):
        if v.idx == idx:
            return v
    return None


def latest(key: str) -> Version | None:
    vs = list_versions(key)
    return vs[0] if vs else None


def delete(key: str, idx: int) -> bool:
    d = key_dir(key)
    ok = False
    for suffix in (f"{idx:03d}.py", f"{idx:03d}.json"):
        p = d / suffix
        if p.exists():
            try:
                p.unlink()
                ok = True
            except Exception:
                pass
    return ok


def clear_key(key: str) -> int:
    """清空某个知识点的全部版本，返回删掉的数量。"""
    d = key_dir(key)
    if not d.exists():
        return 0
    n = len(list(d.glob("*.py")))
    for p in d.iterdir():
        try:
            p.unlink()
        except Exception:
            pass
    try:
        d.rmdir()
    except Exception:
        pass
    return n


def prune(key: str):
    """保留最近 MAX_PER_KEY 版（py 与 json 成对删）。"""
    vs = list_versions(key)
    for v in vs[MAX_PER_KEY:]:
        delete(key, v.idx)
    # 顺带控制知识点总数
    if VERSIONS_DIR.exists():
        dirs = sorted((p for p in VERSIONS_DIR.iterdir() if p.is_dir()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for p in dirs[MAX_KEYS:]:
            try:
                for f in p.iterdir():
                    f.unlink()
                p.rmdir()
            except Exception:
                pass


def all_keys() -> list[str]:
    if not VERSIONS_DIR.exists():
        return []
    dirs = [p for p in VERSIONS_DIR.iterdir() if p.is_dir()]
    return [p.name for p in sorted(dirs, key=lambda p: p.stat().st_mtime,
                                   reverse=True)]


def diff_text(old: str, new: str, old_name: str = "选中的版本",
              new_name: str = "编辑器当前内容") -> str:
    """统一差异格式；两边一致时返回空串外的说明。"""
    a = (old or "").splitlines(keepends=True)
    b = (new or "").splitlines(keepends=True)
    if a == b:
        return "（两个版本内容完全一致）"
    return "".join(difflib.unified_diff(
        a, b, fromfile=old_name, tofile=new_name, lineterm="\n", n=2))


def stat_text(key: str) -> str:
    vs = list_versions(key)
    if not vs:
        return "还没有存过版本"
    newest = vs[0]
    return (f"{len(vs)} 个版本 · 最新 v{newest.idx}"
            f"（{newest.time_text()} · {newest.label}）")


_NUM_PREFIX = re.compile(r"^(\d{3})\.py$")
