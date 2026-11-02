"""moderngl_window 同样带一批 .glsl 着色器，运行时按需读取。"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("moderngl_window")
