# 「跟随系统」主题模式的冒烟测试
#   1) 选项里三项齐全  2) 存进 QSettings 的是 system（不是被解析后的 light/dark）
#   3) 系统切深浅时界面跟着变  4) 明确选了浅/深色时系统变了不动
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.settings_dialog import SettingsDialog
from app.ui import theme

app = QApplication([])
st = QSettings("MathViz", "MathViz")
st.setValue("ui_theme", "light")     # 从干净状态开始
st.setValue("ui_font", "normal")

w = MainWindow(); w.show(); app.processEvents()
ok = []

# ---------- 1) 选项三项齐全 ----------
dlg = SettingsDialog(w)
items = [dlg.combo_theme.itemData(i) for i in range(dlg.combo_theme.count())]
assert items == ["system", "light", "dark"], items
ok.append(f"主题下拉三项（{'/'.join(items)}）")

# ---------- 2) 选「跟随系统」后，存的是 system 而不是解析后的实际配色 ----------
w._apply_theme("system"); app.processEvents()
assert st.value("ui_theme", "", type=str) == "system", st.value("ui_theme")
assert w._theme_mode == "system"
ok.append("存储的是用户选择 system（没被改写）")


def bg_dark():
    im = w._middle_panel.grab().toImage()
    v = [im.pixelColor(x, y).lightness()
         for y in range(0, im.height(), 9) for x in range(0, im.width(), 9)]
    return sum(v) / len(v)


# ---------- 3) 系统切深/浅，界面跟着走 ----------
real = theme.system_prefers_dark
try:
    theme.system_prefers_dark = lambda: True
    w._on_system_theme_changed(); app.processEvents()
    dark1 = bg_dark()
    assert w._palette["name"] == "dark", w._palette["name"]
    theme.system_prefers_dark = lambda: False
    w._on_system_theme_changed(); app.processEvents()
    light1 = bg_dark()
    assert w._palette["name"] == "light", w._palette["name"]
    assert light1 - dark1 > 40, f"浅/深亮度差太小（{light1:.0f} vs {dark1:.0f}）"
    ok.append(f"跟随系统生效（深 {dark1:.0f} → 浅 {light1:.0f} 亮度）")
finally:
    theme.system_prefers_dark = real

# ---------- 4) 明确选了深色，系统变浅不许动 ----------
theme.system_prefers_dark = lambda: False
w._apply_theme("dark"); app.processEvents()
name_before = w._palette["name"]
w._on_system_theme_changed(); app.processEvents()
assert w._palette["name"] == name_before == "dark", w._palette["name"]
assert st.value("ui_theme", "", type=str) == "dark"
ok.append("锁定深色时系统切换不打扰")

# ---------- 5) 重启后从设置恢复到 system ----------
st.setValue("ui_theme", "system")
w2 = MainWindow(); w2.show(); app.processEvents()
assert w2._theme_mode == "system", w2._theme_mode
assert w2._palette["name"] in ("light", "dark"), w2._palette["name"]
ok.append("重启后恢复到跟随系统")

# 还原成默认的浅色，免得影响后续测试
st.setValue("ui_theme", "light")
print("PASS:", "；".join(ok))
