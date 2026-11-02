"""D4 冒烟：主题切换 + 字号档位"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from app.ui import theme
from app.ui.main_window import MainWindow

app = QApplication([])
# 上一轮跑测试可能把主题留在深色，先复位，保证本轮从默认态开始
_st = QSettings("MathViz", "MathViz")
_st.setValue("ui_theme", "light")
_st.setValue("ui_font", "normal")
w = MainWindow()
w.show()
ok = []

# 1) 默认浅色
p = theme.palette("light")
assert w._palette["name"] == "light"
assert w._bc["user"] == p["bubble_user"]
ok.append("默认浅色主题")

# 2) 切深色：全局 QSS + 硬编码样式 + 编辑器 + 气泡全部跟着换
w._append_chat("user", "我想理解 $\\epsilon-\\delta$ 定义")
before_html = w.chat_view.toHtml()
w._apply_theme("dark", "large")
assert w._palette["name"] == "dark"
assert "#1e2126" in app.styleSheet(), "全局 QSS 没换成深色"
assert "#1a1d22" in w.editor.styleSheet(), w.editor.styleSheet()
assert w.find_bar.styleSheet().count("#1e2126") >= 1
assert "QListWidget" in w.point_list.styleSheet()
after_html = w.chat_view.toHtml()
assert after_html != before_html, "气泡要按新配色重画"
assert "#2d4a73" in after_html, after_html[:400]
assert any(r == "user" for r, _ in w.chat_bubbles)
ok.append("切深色（全局 QSS / 列表 / 编辑器 / 气泡重绘）")

# 3) 字号档位
assert app.font().pointSize() == theme.FONT_LEVELS["large"]
w._apply_theme("dark", "xlarge")
assert app.font().pointSize() == theme.FONT_LEVELS["xlarge"]
ok.append("字号三档（标准/大/特大）")

# 4) 写进 QSettings，重启读回
st = QSettings("MathViz", "MathViz")
assert st.value("ui_theme", "light", type=str) == "dark"
assert st.value("ui_font", "normal", type=str) == "xlarge"
ok.append("主题与字号持久化")

# 5) 选项弹窗能读回当前值
from app.ui.settings_dialog import SettingsDialog
dlg = SettingsDialog(w)
dlg.load()
assert dlg.combo_theme.currentData() == "dark"
assert dlg.combo_font.currentData() == "xlarge"
dlg.combo_theme.setCurrentIndex(0)
dlg.combo_font.setCurrentIndex(0)
dlg.apply()
assert w._palette["name"] == "light"
assert app.font().pointSize() == theme.FONT_LEVELS["normal"]
ok.append("选项弹窗读写一致")

print("PASS " + " | ".join(ok))
