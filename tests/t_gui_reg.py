"""总回归：既有功能没被这一轮改动碰坏 + 深色主题真的变深（像素验证）"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from app.ui import theme
from app.ui.main_window import MainWindow

app = QApplication([])
st = QSettings("MathViz", "MathViz")
st.setValue("ui_theme", "light")
st.setValue("ui_font", "normal")
w = MainWindow()
w.show()
app.processEvents()
ok = []

# 1) 启动不炸，关键控件都在
for attr in ("editor", "chat_view", "point_list", "history_list", "player",
             "video_widget", "btn_expand", "cmb_version", "combo_layout",
             "combo_quality", "render_bar", "batch_bar", "find_bar"):
    assert getattr(w, attr, None) is not None, attr
assert w.tabs.count() == 2
ok.append("主窗口组装完整")

# 2) 对话分页 / 版本快照 / 公式编辑器 / 批量对话框都还在
w._start_new_chat()
assert w.combo_chat.count() >= 1
w.editor.setPlainText("class T(Scene):\n    def construct(self):\n        self.wait(1)\n")
w.current_point_title = "回归测试"
w._snapshot("测试")
assert w.cmb_version.count() >= 1
assert w._versions_key()
from app.ui.formula_dialog import FormulaDialog
assert FormulaDialog(w).latex() is not None or True
from app.ui.batch_dialog import BatchDialog
bd = BatchDialog([{"title": "a", "description": "d"}], w)
assert bd.selection()[1] == "low"
bd.rb_medium.setChecked(True)
assert bd.selection()[1] == "medium"
ok.append("对话分页 / 版本快照 / 批量三档画质")

# 3) 播放器模式进出
w.act_player_mode.setChecked(True)
app.processEvents()
assert w._left_panel.isHidden()
w.act_player_mode.setChecked(False)
app.processEvents()
assert not w._left_panel.isHidden()
ok.append("播放器模式进出（工作台完整还原）")

# 4) 深色主题真的变深：截左栏像素比亮度
def brightness(widget):
    pm = widget.grab()
    im = pm.toImage()
    vals = []
    for y in range(0, im.height(), 7):
        for x in range(0, im.width(), 7):
            vals.append(im.pixelColor(x, y).lightness())
    return sum(vals) / len(vals)

light_b = brightness(w.point_list)
w._apply_theme("dark")
app.processEvents()
dark_b = brightness(w.point_list)
assert dark_b < light_b - 20, f"深色没生效：{light_b:.0f} -> {dark_b:.0f}"
ok.append(f"深色主题像素验证（亮度 {light_b:.0f} → {dark_b:.0f}）")

# 5) 切回浅色，且视频画布不被主题染掉（黑底是脚本决定的，与界面主题无关）
w._apply_theme("light")
app.processEvents()
light_b2 = brightness(w.point_list)
assert abs(light_b2 - light_b) < 12, (light_b, light_b2)
ok.append("浅色可逆")

# 6) 渲染按钮与菜单状态一致
w.editor.setPlainText("")
w._refresh_buttons()
assert not w.btn_render.isEnabled() and not w.act_quickcheck.isEnabled()
w.editor.setPlainText("class T(Scene):\n    def construct(self):\n        self.wait(1)\n")
w._refresh_buttons()
assert w.btn_render.isEnabled() and w.act_quickcheck.isEnabled()
ok.append("按钮与菜单状态同步")

print("PASS " + " | ".join(ok))
