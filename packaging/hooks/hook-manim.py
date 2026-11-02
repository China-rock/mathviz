"""manim 的 shader 文件（.glsl/.frag/.vert）是运行时读的，不是代码。

PyInstaller 官方 hook 里没有 manim，不收集的话渲染器启动时会在找 shader
的地方炸掉 —— 报的错还是"file not found"，完全看不出是打包漏了文件。
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("manim")
hiddenimports = (
    collect_submodules("manim")
    # manimpango 的 utils.py / register_font.py / _version.py 没有任何静态
    # import 指向它们（符号是从 cmanimpango 这个扩展里再导出的），静态分析
    # 看不见，不显式补齐就会在渲染文本时报 No module named 'manimpango.utils'。
    + collect_submodules("manimpango")
)
