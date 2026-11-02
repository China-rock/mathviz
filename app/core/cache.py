"""生成结果缓存：同一个知识点第二次遇到时，直接复用上次的成果，不再麻烦 AI。

一条缓存 = 目录 `cache/<key>/`：

    meta.json    索引信息（标题、学科、Scene 名、成片路径、时间统计）
    script.py    上次通过检查 / 成功渲染的那版脚本
    plan.md      当时确认的「呈现清单」

【关于 key 的一个刻意取舍】
命中的判定只用「学科 + 标题 + 描述」，**不把「呈现清单」混进来**。
理由是：清单是 AI 写的自然语言，两次请求哪怕语义相同，措辞也常常差一两个字，
把它算进 key 之后缓存几乎永远命不中，等于白做。
取而代之的规矩是 —— **只有当用户没有额外的自定义清单时才走缓存**；
一旦他在对话里另行确认了内容（且和缓存里记的那份不同），就正常调用 AI。

这样既保住了"重复劳动不烧 token"，又不会让用户在自定义内容后被旧稿糊弄。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core import config

CACHE_DIR = config.DATA_DIR / "cache"

_ENABLED = True          # 界面上的「启用缓存」开关
_MAX_PLAN_CHARS = 4000   # 清单太长就不存了，避免缓存目录膨胀


# ---------------------------------------------------------------- 开关

def is_enabled() -> bool:
    return _ENABLED


def set_enabled(value: bool):
    global _ENABLED
    _ENABLED = bool(value)


# ---------------------------------------------------------------- key

def _normalize(text: str) -> str:
    """归一化：全角转半角、压空白、去大小写差异。

    AI 这次写「导数的定义」、下次写「导数的定义 」或「导数的定义。」，
    应当算同一个知识点 —— 否则缓存就成了摆设。
    """
    s = unicodedata.normalize("NFKC", text or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


def entry_key(domain: str, title: str, description: str = "") -> str:
    """缓存主键：**只看学科 + 标题**，描述不参与。

    description 是 AI 写的自然语言，同一知识点两次提取出来措辞常有出入；
    把它算进 key 会让缓存动不动就不命中。而标题重复的情况在同一份课件里极少，
    用它做主键既稳，也让"渲染完成后回写成片路径"这类操作能准确找到同一条。
    """
    raw = "|".join((domain or "", _normalize(title)))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- entry

@dataclass
class CacheEntry:
    key: str
    title: str
    domain: str = "math"
    description: str = ""
    level: str = ""
    scene_name: str = ""
    video: str | None = None
    created_at: float = 0.0
    hits: int = 0
    last_hit: float = 0.0
    source: str = "generate"          # generate / render（后者是渲染修复后的定稿）
    extra: dict = field(default_factory=dict)

    # ---- 路径

    @property
    def dir(self) -> Path:
        return CACHE_DIR / self.key

    @property
    def script_path(self) -> Path:
        return self.dir / "script.py"

    @property
    def plan_path(self) -> Path:
        return self.dir / "plan.md"

    # ---- 内容

    def load_code(self) -> str:
        try:
            return self.script_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def load_plan(self) -> str:
        try:
            return self.plan_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def has_video(self) -> bool:
        return bool(self.video) and Path(self.video).exists()

    # ---- 展示

    @property
    def created_text(self) -> str:
        return _fmt_time(self.created_at)

    @staticmethod
    def _size_text(code: str) -> str:
        return f"{len(code)} 字符"

    def summary(self) -> str:
        """给列表提示 / 日志用的一句话概览。"""
        parts = [self.created_text]
        if self.hits:
            parts.append(f"已复用 {self.hits} 次")
        if self.has_video():
            parts.append("有成片")
        return " · ".join(parts)


def _fmt_time(ts: float) -> str:
    if not ts:
        return "未知时间"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- 读写

def _read_meta(key: str) -> dict:
    try:
        return json.loads((CACHE_DIR / key / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_meta(entry: CacheEntry):
    entry.dir.mkdir(parents=True, exist_ok=True)
    data = {
        "key": entry.key,
        "title": entry.title,
        "domain": entry.domain,
        "description": entry.description,
        "level": entry.level,
        "scene_name": entry.scene_name,
        "video": entry.video,
        "created_at": entry.created_at,
        "hits": entry.hits,
        "last_hit": entry.last_hit,
        "source": entry.source,
    }
    (entry.dir / "meta.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get(domain: str, title: str, description: str = "",
        touch: bool = True) -> CacheEntry | None:
    """按知识点查缓存。开关关闭时永远返回 None。"""
    if not _ENABLED:
        return None
    key = entry_key(domain, title, description)
    meta = _read_meta(key)
    if not meta:
        return None
    if not (CACHE_DIR / key / "script.py").exists():
        return None    # 目录残缺（被人手工删了一半）→ 当作没缓存
    entry = CacheEntry(
        key=key,
        title=meta.get("title", title),
        domain=meta.get("domain", domain),
        description=meta.get("description", description),
        level=meta.get("level", ""),
        scene_name=meta.get("scene_name", ""),
        video=meta.get("video"),
        created_at=meta.get("created_at", 0.0),
        hits=int(meta.get("hits", 0)),
        last_hit=meta.get("last_hit", 0.0),
        source=meta.get("source", "generate"),
    )
    if touch:
        entry.hits += 1
        entry.last_hit = time.time()
        _write_meta(entry)
    return entry


def save(domain: str, title: str, description: str, code: str,
         scene_name: str = "", plan: str = "", level: str = "",
         video: str | None = None, source: str = "generate") -> CacheEntry | None:
    """写入（或覆盖）一条缓存。code 为空时不写 —— 别把空气缓存进去。"""
    if not _ENABLED or not (code or "").strip():
        return None
    key = entry_key(domain, title, description)
    prev = _read_meta(key)
    entry = CacheEntry(
        key=key,
        title=title,
        domain=domain,
        description=description,
        level=level,
        scene_name=scene_name,
        video=video if video is not None else prev.get("video"),
        created_at=prev.get("created_at") or time.time(),
        hits=int(prev.get("hits", 0)),
        last_hit=prev.get("last_hit", 0.0),
        source=source,
    )
    entry.dir.mkdir(parents=True, exist_ok=True)
    entry.script_path.write_text(code, encoding="utf-8")
    try:
        entry.plan_path.write_text((plan or "")[:_MAX_PLAN_CHARS], encoding="utf-8")
    except Exception:
        pass
    _write_meta(entry)
    return entry


def record_video(domain: str, title: str, description: str, video: str,
                 code: str | None = None, scene_name: str = "") -> None:
    """渲染成功后补记成片路径（顺带把能跑的定稿脚本盖上去）。"""
    if not _ENABLED:
        return
    key = entry_key(domain, title, description)
    meta = _read_meta(key)
    if not meta and not code:
        return
    entry = CacheEntry(
        key=key, title=title, domain=domain, description=description,
        level=meta.get("level", ""),
        scene_name=scene_name or meta.get("scene_name", ""),
        video=str(video),
        created_at=meta.get("created_at") or time.time(),
        hits=int(meta.get("hits", 0)),
        last_hit=meta.get("last_hit", 0.0),
        source="render",
    )
    entry.dir.mkdir(parents=True, exist_ok=True)
    if code:
        entry.script_path.write_text(code, encoding="utf-8")
    _write_meta(entry)


# ---------------------------------------------------------------- 管理

def all_entries() -> list[CacheEntry]:
    if not CACHE_DIR.exists():
        return []
    out: list[CacheEntry] = []
    for meta_path in CACHE_DIR.glob("*/meta.json"):
        meta = _read_meta(meta_path.parent.name)
        if not meta:
            continue
        out.append(CacheEntry(
            key=meta.get("key", meta_path.parent.name),
            title=meta.get("title", ""),
            domain=meta.get("domain", "math"),
            description=meta.get("description", ""),
            level=meta.get("level", ""),
            scene_name=meta.get("scene_name", ""),
            video=meta.get("video"),
            created_at=meta.get("created_at", 0.0),
            hits=int(meta.get("hits", 0)),
            last_hit=meta.get("last_hit", 0.0),
            source=meta.get("source", "generate"),
        ))
    return sorted(out, key=lambda e: e.created_at, reverse=True)


def stats() -> dict:
    entries = all_entries()
    total_chars = sum(len(e.load_code()) for e in entries)
    return {
        "count": len(entries),
        "hits": sum(e.hits for e in entries),
        "with_video": sum(1 for e in entries if e.has_video()),
        "chars": total_chars,
    }


def delete(key: str) -> bool:
    """删除单条缓存。已归档在 media/ 里的成片不受影响。"""
    import shutil
    d = CACHE_DIR / key
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return not d.exists()


def clear_all() -> int:
    """清空缓存目录，返回被删掉的条目数。"""
    n = len(all_entries())
    import shutil
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return n


def ensure_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
