# -*- coding: utf-8 -*-
"""把 packaging/launcher.py 打成项目根下的 MathViz.exe（双击即启动）。

和打包主程序（build_all.py）是两件事：
  主程序 exe  = 冻结整个应用（736 MB，含 Python + Qt + manim）
  启动器 exe  = 只负责「找到 venv 里的 pythonw 并把它拉起来」（几 MB）
所以启动器必须和 .venv、app 待在一起，它不能单独发给别人用。
发给别人用请走 build_all.py + installer.iss。

用法：.venv\\Scripts\\python.exe packaging\\build_launcher.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
OUT_NAME = "MathViz.exe"
WORK = ROOT / "build_launcher"
DIST = ROOT / "dist_launcher"

# launcher 只用标准库（os / subprocess / sys / pathlib / ctypes）。
# 这些包一个都不 import，但 PyInstaller 的依赖分析偶尔会顺着 site-packages
# 摸进去（尤其项目 venv 里装着 manim、PySide6 的时候），显式排掉最稳，
# 顺带把体积从几十 MB 压到几 MB。
EXCLUDES = [
    "PySide6", "shiboken6",
    "manim", "manimpango", "moderngl", "moderngl_window", "pyglet", "pyglm",
    "numpy", "scipy", "matplotlib", "PIL", "pandas",
    "openai", "httpx", "requests", "urllib3",
    "imageio", "imageio_ffmpeg", "av", "networkx", "tqdm", "rich", "click",
    "tkinter", "unittest", "pydoc", "doctest", "lib2to3",
    "email", "html", "http", "xml", "xmlrpc", "sqlite3",
    "multiprocessing", "asyncio", "concurrent", "logging.config",
    "setuptools", "pkg_resources", "pip", "pytest",
]


def main() -> int:
    icon = ROOT / "assets" / "mathviz-icon-v2.ico"
    cmd = [
        PY, "-m", "PyInstaller",
        str(ROOT / "packaging" / "launcher.py"),
        "--onefile",
        "--noconsole",          # GUI 子系统：双击不弹黑窗
        "--clean",
        "--noconfirm",
        "--name", "MathViz",
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
    ]
    if icon.is_file():
        cmd += ["--icon", str(icon)]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]

    print("打包启动器...")
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        print("PyInstaller 失败")
        return r.returncode

    built = DIST / OUT_NAME
    if not built.is_file():
        print("没找到产物:", built)
        return 1

    target = ROOT / OUT_NAME
    # 覆盖根目录那份（正在运行时会被占用，改名让位而不是硬删）
    if target.exists():
        try:
            target.unlink()
        except OSError:
            stale = ROOT / (OUT_NAME + ".old")
            if stale.exists():
                stale.unlink()
            target.rename(stale)
    shutil.copy2(built, target)

    size = target.stat().st_size / 1048576
    print(f"\n完成：{target}  ({size:.1f} MB)")
    print("双击它会拉起 .venv 里的 pythonw 跑 app.main —— 全程无黑窗。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
