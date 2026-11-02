"""ffmpeg 二进制（约 84 MB）必须跟着走。

本项目不依赖系统 ffmpeg（本机 PATH 里就没有），成片编码全靠 imageio_ffmpeg
自带的这个 exe；漏掉它渲染会在最后一步失败。
"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("imageio_ffmpeg")
