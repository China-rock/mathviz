# -*- coding: utf-8 -*-
"""MathViz 启动器（源码目录用）。

双击就启动 GUI，全程不弹黑窗。它做的事和 MathViz.vbs 一样，但多了两样：

  · 找不到解释器时弹窗说明「怎么办」，而不是静默失败（vbs 出这种错只会
    一闪而过，什么也看不到）；
  · 有正经图标，可以放心丢到桌面/任务栏。

不打单实例：启动器把 GUI 拉起来后自己就退出了，此时互斥量/锁文件都已释放，
下次双击照样判断不出来 —— 真正的单实例得由 GUI 自己拿（那是另一件事）。

打成 exe 用 packaging/build_launcher.py。不打包时也能直接跑：
    .venv\\Scripts\\pythonw.exe packaging\\launcher.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_TITLE = "MathViz 启动器"

# 目标脚本（相对项目根）。用 -m 而不是路径，模块内的相对导入才不会乱。
ENTRY_MODULE = "app.main"


# ---------------------------------------------------------------- 找项目根
def find_root() -> Path | None:
    """从 exe 所在目录往上找带 app/main.py 的目录。

    exe 通常就在项目根，但用户可能把它复制到上一级或桌面再建快捷方式，
    所以往上找三级，找到第一个像项目根的目录。
    """
    if getattr(sys, "frozen", False):
        start = Path(sys.executable).resolve().parent
    else:
        # 未打包时本文件在 packaging/ 下，上一级才是项目根
        start = Path(__file__).resolve().parent
    for base in [start, *start.parents][:4]:
        if (base / "app" / "main.py").is_file():
            return base
    return None


def find_python(root: Path) -> Path | None:
    """优先用项目自己的 venv，退化到系统 pythonw / python。

    pythonw 优先于 python：前者是 GUI 子系统，不会给子进程挂上控制台。
    """
    venv = root / ".venv" / "Scripts"
    for name in ("pythonw.exe", "python.exe"):
        p = venv / name
        if p.is_file():
            return p
    # 没 venv 时找系统里的（有些用户会用全局环境装依赖）
    for name in ("pythonw.exe", "python.exe"):
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if not d:
                continue
            p = Path(d) / name
            if p.is_file():
                return p
    return None


# ---------------------------------------------------------------- 提示框
def message(text: str, title: str = APP_TITLE, icon: int = 0x10) -> None:
    """弹一个系统原生消息框。

    用 ctypes 直接调 user32 而不是 tkinter：打包体积小一个量级，
    也不会因为 tkinter 被排除而崩掉。icon: 0x10 错误 / 0x40 信息。
    """
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, icon)
    except Exception:
        # 实在弹不出来就写日志，至少留个痕迹
        try:
            log = Path(os.environ.get("LOCALAPPDATA", ".")) / "MathViz" / "launcher.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(text, encoding="utf-8")
        except Exception:
            pass


# ---------------------------------------------------------------- 主流程
def main() -> int:
    root = find_root()
    if root is None:
        message(
            "没找到 MathViz 的程序文件。\n\n"
            "这个启动器要和 app、.venv 这些文件夹放在同一个目录里。\n"
            "如果你把它复制到了别处，请放回 MathViz 文件夹，或者重建一个快捷方式。",
        )
        return 1

    python = find_python(root)
    if python is None:
        message(
            "没找到 Python 解释器。\n\n"
            "正常情况下项目里应该有一个 .venv 文件夹（虚拟环境）。\n\n"
            "解决办法：在 MathViz 文件夹里打开命令行，执行\n"
            "    python -m venv .venv\n"
            "    .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n\n"
            "或者直接用打包好的版本 dist\\MathViz\\MathViz.exe（不需要装任何环境）。",
        )
        return 1

    # DETACHED_PROCESS 让子进程彻底脱离启动器；CREATE_NO_WINDOW 保证
    # 就算选到的是 python.exe 也不会闪一个黑窗出来。
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | \
                getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    try:
        subprocess.Popen(
            [str(python), "-m", ENTRY_MODULE],
            cwd=str(root),
            creationflags=flags,
            close_fds=True,
            # stdout/stderr 千万别指到 DEVNULL 去：app/main.py 判断
            # 「sys.stdout is None 就是没控制台」来自动把输出接到 logs\console.log，
            # 一旦塞进一个有效的 NUL 句柄，这个判断就失效了 ——
            # 日志不写、崩溃也没痕迹，排查时两眼一抹黑。
            # 不传这两个参数即可：launcher 本身是 GUI 子系统 + DETACHED_PROCESS，
            # 子进程不会拿到有效控制台句柄，Python 自然把 stdout 设为 None。
        )
    except OSError as exc:
        message(
            f"启动失败：{exc}\n\n"
            f"解释器：{python}\n"
            f"程序目录：{root}\n\n"
            "可以试试 run.bat debug（会保留黑窗，能看到真正的报错）。",
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
