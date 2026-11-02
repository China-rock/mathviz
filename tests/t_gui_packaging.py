"""打包相关行为的校验（不需要真的打完包就能验）。

三件事，都是"打包后才成立、平时看不见"的行为：
  1. 冻结后 manim 必须改走 manim_worker.exe（否则渲染静默失败）
  2. 数据目录必须落到用户目录（装到 Program Files 时程序目录只读）
  3. 缺 LaTeX 时要给出带下载链接的引导，而不是一句 latex error
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])
sys.path.insert(0, ROOT)

import importlib

from app.core import config, renderer, texenv

ok = []
tmp = Path(tempfile.mkdtemp(prefix="mvz_pack_"))


def frozen(on: bool, meipass: str = ""):
    """切换"假装已被打包"的状态，并让 config 按新状态重算路径。"""
    if on:
        sys.frozen = True
        sys._MEIPASS = meipass
    else:
        sys.frozen = False
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS
    return importlib.reload(config)


# ---------- 1) 冻结后 manim 走 worker ----------
fake_dir = tmp / "dist"
fake_dir.mkdir()
fake_exe = fake_dir / "MathViz.exe"
fake_exe.write_bytes(b"")
worker = fake_dir / "manim_worker.exe"
worker.write_bytes(b"")

old_exe, had_frozen = sys.executable, hasattr(sys, "frozen")
sys.executable = str(fake_exe)
sys.frozen = True
cmd = renderer._manim_base_cmd()
assert cmd == [str(worker)], f"冻结后应调用 manim_worker.exe，实际：{cmd}"

# worker 没打成时退回 -m：宁可失败，也要让日志里能看出是打包漏了文件
worker.unlink()
cmd2 = renderer._manim_base_cmd()
assert cmd2[0] == str(fake_exe) and "-m" in cmd2 and "manim" in cmd2, \
    f"worker 缺失时应退回 -m manim，实际：{cmd2}"

# 开发态不受影响
if not had_frozen:
    del sys.frozen
sys.executable = old_exe
cmd3 = renderer._manim_base_cmd()
assert cmd3 == [sys.executable, "-m", "manim"], f"开发态应仍是 -m manim：{cmd3}"
ok.append("冻结后 manim 走 manim_worker.exe（缺失退 -m），开发态不变")


# ---------- 2) 冻结后数据目录落到用户目录 ----------
internal = tmp / "_internal"
internal.mkdir()
cfg = frozen(True, str(internal))
assert cfg.IS_FROZEN is True
assert cfg.APP_DIR == internal, f"APP_DIR 应指向资源目录：{cfg.APP_DIR}"
if sys.platform == "win32":
    want = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MathViz"
    assert cfg.DATA_DIR == want, f"DATA_DIR 应在用户目录：{cfg.DATA_DIR}"
    assert "Program Files" not in str(cfg.OUTPUT_MEDIA_DIR), "成片不能往程序目录写"
assert cfg.ENV_FILE == cfg.DATA_DIR / ".env", f"Key 应存用户目录：{cfg.ENV_FILE}"
ok.append(f"冻结后数据落用户目录（{cfg.DATA_DIR.name}），资源仍在 APP_DIR")

# Key 写入与读回（不能碰真实 .env：只在临时目录里验）
user_dir = tmp / "userdata"
os.environ["MATHVIZ_USER_DIR"] = str(user_dir)
cfg = importlib.reload(config)
assert cfg.DATA_DIR == user_dir
cfg.save_api_key("sk-test-only")
assert (user_dir / ".env").exists()
assert cfg.load_env_file().get("DEEPSEEK_API_KEY") == "sk-test-only"
cfg.save_api_key("sk-second")      # 覆盖而不是追加
txt = (user_dir / ".env").read_text(encoding="utf-8")
assert txt.count("DEEPSEEK_API_KEY=") == 1, f"覆盖写入应只留一行：{txt!r}"
assert cfg.load_env_file().get("DEEPSEEK_API_KEY") == "sk-second"
del os.environ["MATHVIZ_USER_DIR"]
ok.append("Key 写入用户目录 .env（覆盖不追加），不碰项目里的真实 .env")

cfg = frozen(False)
assert cfg.DATA_DIR == cfg.APP_DIR == Path(ROOT), \
    f"开发态两个目录应同为项目根：{cfg.DATA_DIR} / {cfg.APP_DIR}"


# ---------- 3) 缺 LaTeX 时给出可操作的引导 ----------
import shutil

real_which = shutil.which
real_latex_dir = texenv.latex_dir
texenv.shutil.which = lambda c, *a, **k: None      # 假装系统里什么都没有
texenv.latex_dir = lambda: None
missing_ok, missing_msg = texenv.check()
assert missing_ok is False, "系统无 LaTeX 时应判为不可用"
assert "miktex.org" in missing_msg, f"引导里要有下载链接：{missing_msg[:60]}"
assert "重启" in missing_msg, "要提醒装完重启（进程 PATH 还是旧的）"
texenv.shutil.which = real_which
texenv.latex_dir = real_latex_dir
ok.append("缺 LaTeX 时给出含下载链接与重启提示的引导")

# 装上之后（能探测到目录）就该判为可用 —— 验证"刚装完还没重启"的兜底
texenv.shutil.which = lambda c, *a, **k: None
texenv.latex_dir = lambda: str(tmp / "fake_miktex")
(tmp / "fake_miktex").mkdir(exist_ok=True)
(tmp / "fake_miktex" / "latex.exe").write_bytes(b"")
(tmp / "fake_miktex" / "dvisvgm.exe").write_bytes(b"")
found_ok, found_msg = texenv.check()
texenv.shutil.which = real_which
texenv.latex_dir = real_latex_dir
assert found_ok is True, f"PATH 没有但目录里有，应判为可用：{found_msg}"
ok.append("PATH 未刷新但能探测到 MiKTeX 目录时判为可用（刚装完不重启也认）")

print("PASS " + " | ".join(ok))
