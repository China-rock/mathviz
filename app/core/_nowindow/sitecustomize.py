"""渲染子进程专用：让本进程派生的**所有**控制台程序都不开窗。

背景：主程序用 pythonw.exe 启动，本身没有控制台；我们调用 manim 时也已经带了
CREATE_NO_WINDOW。但 manim 在渲染过程中还会自己去 spawn pdflatex / dvisvgm /
ffmpeg —— 它用的是默认参数，于是每个控制台子进程都各自申请一个新控制台，
表现就是渲染时"黑窗一闪一闪"。

外部管不到孙辈进程，只能在 manim 自己的解释器里改默认行为：
本文件通过 PYTHONPATH 注入，site 模块在解释器启动时会自动 import 它，
于是 manim 里所有 subprocess 调用都会走被 patch 过的 Popen
（run / check_output / check_call 内部都调用 Popen，一并生效）。
"""
import os
import subprocess

if os.name == "nt" and getattr(subprocess, "CREATE_NO_WINDOW", 0):
    _FLAG = subprocess.CREATE_NO_WINDOW
    _Base = subprocess.Popen

    if not getattr(_Base, "_mathviz_nowindow", False):
        class Popen(_Base):
            """默认补上 CREATE_NO_WINDOW；调用方显式传的 flags 按位或保留。"""
            _mathviz_nowindow = True

            def __init__(self, *args, **kwargs):
                kwargs["creationflags"] = kwargs.get("creationflags", 0) | _FLAG
                super().__init__(*args, **kwargs)

        subprocess.Popen = Popen
