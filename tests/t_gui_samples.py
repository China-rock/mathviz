"""示例课件入口：菜单项在、示例目录能解析、一次点击就能载入（offscreen）。

为什么值得单测：示例是随包发布的"第一课"，它挂了不会报错，
只会让新用户点开菜单看到一句"没找到"——这种静默失效最难发现。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from app.core import config
from app.ui.main_window import MainWindow

app = QApplication([])
w = MainWindow()
w.show()
app.processEvents()
ok = []

# 1) 示例目录按 APP_DIR 解析（开发态=项目根，打包态=_internal），两边都能命中
assert config.SAMPLES_DIR.is_dir(), f"示例目录不存在：{config.SAMPLES_DIR}"
files = [p for p in config.SAMPLES_DIR.iterdir()
         if p.suffix.lower() in config.COURSE_EXTENSIONS]
assert files, f"示例目录里没有课件文件：{config.SAMPLES_DIR}"
ok.append(f"示例目录可解析（{config.SAMPLES_DIR.name}/，{len(files)} 份课件）")

# 2) 「文件」菜单里有入口
acts = [a for a in w.findChildren(QAction) if a.text() == "打开示例课件"]
assert acts, "「文件」菜单缺少「打开示例课件」"
ok.append("菜单项存在")

# 3) 点下去真的能把内容读进来（只有一个示例时不再多问一层对话框）
w.on_open_sample()
app.processEvents()
assert w.course_text.strip(), "载入后 course_text 仍为空"
assert len(w.course_text) > 200, f"示例内容过短：{len(w.course_text)} 字符"
assert "微分中值定理" in w.course_text or "定理" in w.course_text, "读到的不是示例内容"
ok.append(f"一键载入成功（{len(w.course_text)} 字符）")

# 4) 界面与日志都留了痕迹，用户知道"课件从哪来的"
assert "📄" in w.lbl_file.text(), w.lbl_file.text()
assert "[示例]" in w.log_view.toPlainText()
ok.append("课件标签与运行日志均已标注来源")

print("PASS " + " | ".join(ok))
