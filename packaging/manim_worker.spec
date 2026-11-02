# -*- mode: python ; coding: utf-8 -*-
"""manim 渲染子进程（manim_worker.exe）打包配置。

存在理由：冻结后的解释器不再接受 `-m`，主 exe 没法再当 manim 用；而渲染输出
必须走标准输出（主程序靠读它算进度），所以这个入口得是 console=True —— 这也
是它不能并进主 exe 的直接原因（主 exe 是 windowed，stdout 是 None）。

它不需要任何 Qt（省掉一百多 MB），只需要 manim 那一套：shader、ffmpeg、
av、scipy。构建完由 packaging/build_all.py 把它搬进主程序目录。
"""
import os

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH 是 spec 所在目录（= 项目根/packaging），往上一级才是项目根
ROOT = os.path.dirname(os.path.abspath(SPECPATH)) \
    if "SPECPATH" in globals() else os.path.abspath(os.getcwd())

EXCLUDES = [
    "PySide6",                 # 渲染子进程不碰界面，整个 Qt 都不要
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "PySide6.QtMultimedia", "PySide6.QtSvg",
    "typst", "tkinter",                  # 注意：unittest/doctest 不能排
    # （numpy.testing、scipy 的 array_api_compat 在导入链里真的会 import）
    "IPython", "jupyter", "notebook",
    "app",                     # 主程序代码，worker 用不到
    "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_qtcairo",
    "matplotlib.backends.backend_webagg", "matplotlib.backends.backend_nbagg",
    "matplotlib.backends.backend_macosx",
]

a = Analysis(
    [os.path.join(ROOT, "packaging", "manim_worker.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=["manim", "manim.__main__", *collect_submodules("manim")],
    hookspath=[os.path.join(ROOT, "packaging", "hooks")],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz, a.scripts, [],
    name="manim_worker",
    console=True,               # 必须：渲染日志走 stdout，主程序按行读它算进度
    # 依赖目录改名，避免和主程序的 _internal 撞车（两个 exe 要住同一个目录）
    contents_directory="_internal_worker",
    exclude_binaries=True,
)
coll = COLLECT(
    exe, a.binaries, a.datas, [],
    name="MathViz_worker",      # 单独目录，构建完再搬进主程序目录
    upx=False,
)
