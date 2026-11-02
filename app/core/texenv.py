"""LaTeX 环境检测 —— 为「目标机器上没有 TeX」这件事准备可操作的提示。

公式渲染走 manim 的 MathTex，底层是 pdflatex + dvisvgm，两者都不是 pip 包，
打不进安装包。所以对分发版来说，能不能在渲染前**明确地**告诉用户"你缺什么、
去哪下、装完要注意什么"，比事后弹一句 latex error 有用得多。

本模块只负责"查清楚"，不负责界面；弹窗由主窗口决定怎么呈现。
"""

from __future__ import annotations

import glob as _glob
import shutil
import sys
from pathlib import Path

# 常见 MiKTeX bin 目录（安装后启动的进程可能带着旧 PATH，需要兜底探测）
# 注意：USERNAME 环境变量不一定等于用户目录名（某些机器上两者不一致），
# 因此用户目录下的候选一律用 glob 探测，不信任环境变量。
MIKTEX_CANDIDATES = [
    r"C:\Program Files\MiKTeX\miktex\bin\x64",
    r"C:\MiKTeX\miktex\bin\x64",
]
MIKTEX_USER_GLOB = r"C:\Users\*\AppData\Local\Programs\MiKTeX\miktex\bin\x64"

MIKTEX_DOWNLOAD_URL = "https://miktex.org/download"

# 真正会被调用到的三个命令：少任何一个，渲染都会以一种看不懂的方式失败
REQUIRED_CMDS = ("latex", "dvisvgm")


def latex_dir() -> str | None:
    """PATH 里没有 latex 时，返回能补进 PATH 的目录；已有则返回 None。"""
    if shutil.which("latex"):
        return None
    if sys.platform != "win32":  # 这些候选路径只对 Windows 的 MiKTeX 成立
        return None
    for d in MIKTEX_CANDIDATES:
        if Path(d, "latex.exe").exists():
            return d
    for d in _glob.glob(MIKTEX_USER_GLOB):
        if Path(d, "latex.exe").exists():
            return d
    return None


def _which_with_fallback(cmd: str) -> bool:
    """在"补上 MiKTeX 目录之后的 PATH"里找命令，而不是只看当前 PATH。

    刚装完 MiKTeX 就打开本软件的情况下，进程里的 PATH 还是旧的，
    直接 shutil.which 会误判成"没装"。
    """
    if shutil.which(cmd):
        return True
    d = latex_dir()
    if not d:
        return False
    return Path(d, f"{cmd}.exe").exists()


def check() -> tuple[bool, str]:
    """检查 LaTeX 是否可用。

    返回 (可用?, 说明文字)。说明文字直接面向用户：缺什么、去哪装。
    """
    if sys.platform != "win32":
        ok = all(shutil.which(c) for c in REQUIRED_CMDS)
        missing = [c for c in REQUIRED_CMDS if not shutil.which(c)]
        if ok:
            return True, "LaTeX 环境就绪"
        return False, f"缺少命令：{'、'.join(missing)}"

    missing = [c for c in REQUIRED_CMDS if not _which_with_fallback(c)]
    if not missing:
        return True, "LaTeX 环境就绪（pdflatex + dvisvgm 都在）"
    return False, (
        "没检测到 LaTeX（缺 "
        f"{'、'.join(missing)}"
        "）。公式渲染依赖它，不是可有可无的组件。\n\n"
        "安装办法（只需一次）：\n"
        f"1. 打开 {MIKTEX_DOWNLOAD_URL} 下载 MiKTeX 并安装\n"
        "2. 安装时选「Anyone who uses this computer」，允许自动安装缺失宏包\n"
        "3. 装完重启本软件（不重启读不到新的 PATH）\n\n"
        "首次渲染时 MiKTeX 会联网补几个宏包，属正常现象。"
    )
