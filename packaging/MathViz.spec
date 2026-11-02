# -*- mode: python ; coding: utf-8 -*-
"""MathViz 主程序打包配置（PyInstaller onedir）。

为什么不打成一个 exe、也不走 MERGE：
  · 冻结后的解释器不再接受 `-m`，`MathViz.exe -m manim` 不会去跑 manim，
    渲染必须交给第二个入口 —— 见 manim_worker.spec。
  · MERGE 能让两个 exe 共用依赖，但官方实现注明"连 onedir 都会退化成 onefile
    语义"，即每次启动把几百 MB 解到临时目录。启动慢、杀软还爱误报，所以不用。
  · 于是两次独立构建放进同一个目录，各自带一份 _internal（worker 那份不含 Qt）。
    体积看着翻倍，但交给 Inno Setup 做固态压缩时重复文件几乎不占额外空间。

构建（两条都要跑，顺序无所谓）：
    .venv\\Scripts\\python.exe -m PyInstaller packaging\\MathViz.spec --noconfirm
    .venv\\Scripts\\python.exe -m PyInstaller packaging\\manim_worker.spec --noconfirm

产物：dist\\MathViz\\ 下 MathViz.exe + manim_worker.exe + _internal*。
"""
import os

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH 是 spec 所在目录（= 项目根/packaging），往上一级才是项目根
ROOT = os.path.dirname(os.path.abspath(SPECPATH)) \
    if "SPECPATH" in globals() else os.path.abspath(os.getcwd())

# ── 用不到的 Qt 模块：QtWebEngineCore 一个就 194 MB，Quick/Qml/Designer/3D
#    加起来近百 MB。本项目只用到 Core / Gui / Widgets / Multimedia / Svg。
QT_EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtQuick3D", "PySide6.QtQml",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtHelp", "PySide6.QtSensors",
    "PySide6.QtSpatialAudio", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtRemoteObjects",
    "PySide6.QtNetworkAuth", "PySide6.QtHttpServer",
]

EXCLUDES = QT_EXCLUDES + [
    "typst",            # manim[typst] 带进来的 65 MB，代码里零引用
    "tkinter",                  # 注意：unittest/doctest 不能排
    # （numpy.testing、scipy 的 array_api_compat 在导入链里真的会 import）
    "IPython", "jupyter", "notebook",
    "matplotlib.backends.backend_webagg", "matplotlib.backends.backend_nbagg",
    "matplotlib.backends.backend_macosx",
]

DATAS = [
    (os.path.join(ROOT, "assets"), "assets"),
    (os.path.join(ROOT, "samples"), "samples"),
    (os.path.join(ROOT, "README.md"), "."),
    (os.path.join(ROOT, "LICENSE"), "."),
]

a = Analysis(
    [os.path.join(ROOT, "packaging", "app_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=DATAS,
    hiddenimports=collect_submodules("app"),
    hookspath=[os.path.join(ROOT, "packaging", "hooks")],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz, a.scripts, [],
    name="MathViz",
    icon=os.path.join(ROOT, "assets", "mathviz-icon-v2.ico"),
    console=False,          # 双击不要黑窗（run.bat 用 vbs 就是为了这个）
    exclude_binaries=True,
)
coll = COLLECT(
    exe, a.binaries, a.datas, [],
    name="MathViz",
    upx=False,
)
