# Win11 风格控件的像素级校验：
# 箭头必须是"细线条 chevron"（不能是实心矩形），滚动条/滑块/进度条要按新配色画出来
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

from app.ui.main_window import MainWindow
from app.ui import theme

app = QApplication([])
w = MainWindow(); w.show()
w._apply_theme("light")
w.resize(1200, 800); app.processEvents()
ok = []


def grab(widget, rect=None):
    if rect is None:
        return widget.grab().toImage()
    return widget.grab(rect).toImage()


def ink_ratio(img, bg="#ffffff"):
    """有多少像素不是背景色（"墨迹占比"）。"""
    bgc = QColor(bg)
    tot = img.width() * img.height()
    n = sum(1 for y in range(img.height()) for x in range(img.width())
            if img.pixelColor(x, y) != bgc)
    return n / max(1, tot)


# ---------- 1) 下拉框的 chevron：细线条，不是实心方块 ----------
cb = w.combo_quality
cb.resize(160, 30)
app.processEvents()
img = grab(cb)
# 下拉按钮区 = 右侧 22px
arrow_img = img.copy(QRect(img.width() - 22, 0, 22, img.height()))
r = ink_ratio(arrow_img)
assert 0.02 < r < 0.45, f"下拉箭头墨迹占比 {r:.1%} —— 实心方块会接近 100%，空则接近 0"
# 箭头该是小巧的：只看深色笔画（排除浅色边框），V 的竖向跨度应明显小于框高一半
BRight = 150
rows_with_ink = [y for y in range(arrow_img.height())
                 if any(arrow_img.pixelColor(x, y).lightness() < BRight
                        for x in range(arrow_img.width()))]
span = max(rows_with_ink) - min(rows_with_ink) + 1 if rows_with_ink else 0
assert 3 <= span <= arrow_img.height() * 0.55, (
    f"箭头竖向跨度 {span}px / 框高 {arrow_img.height()}px —— 该是小小的 chevron")
ok.append(f"下拉箭头是细线条 chevron（墨迹 {r:.1%}、跨度 {span}px）")

# ---------- 2) SpinBox：上下箭头都在右侧，且是细线条 ----------
sp = w.spin_from
sp.setRange(1, 29); sp.setValue(7)
sp.resize(58, 26)
app.processEvents()
img = grab(sp)
box_half = img.height() // 2
up_area = img.copy(QRect(img.width() - 18, 0, 18, box_half))
dn_area = img.copy(QRect(img.width() - 18, box_half, 18, img.height() - box_half))
ru, rd = ink_ratio(up_area), ink_ratio(dn_area)
assert ru > 0.02, f"上箭头没画出来（{ru:.1%}）"
assert rd > 0.02, f"下箭头没画出来（{rd:.1%}）"
assert max(ru, rd) < 0.6, f"箭头被画成实心块（{ru:.1%}/{rd:.1%}）"
# 数字区域（左侧留给文本的地方）不能被按钮占满
text_area = img.copy(QRect(0, 0, img.width() - 20, img.height()))
assert text_area.width() >= 30, "留给数字的横向空间太小"
ok.append(f"SpinBox 上下箭头各占半高、位于右侧（{ru:.1%}/{rd:.1%}）")

# ---------- 3) 滑块的圆点手柄 ----------
sl = w.slider
sl.resize(300, 20)
sl.setRange(0, 100)     # 没载入视频时播放器范围是空的，sub-page 画不出来
sl.setValue(50)
app.processEvents()
img = grab(sl)
accent = QColor(theme.LIGHT["accent"])
track = QColor(theme.LIGHT["track"])
w_ = img.width()
left_col = img.pixelColor(int(w_ * 0.15), img.height() // 2)   # 已播段 -> 主题色
right_col = img.pixelColor(int(w_ * 0.85), img.height() // 2)  # 未播段 -> 灰轨道
assert abs(left_col.red() - accent.red()) < 30 and left_col.blue() > left_col.red(), \
    f"已播段不是主题色：{left_col.name()}"
assert abs(right_col.red() - track.red()) < 25 or right_col.lightness() > 200, \
    f"未播段不是灰轨道：{right_col.name()}"

# 量形状要避开"已播段整条也是主题色"：轨道行会整行都是主题色，
# 手柄独占的行（像素数明显少）才是它的真实形状。圆点在这些行有 6~8px 宽，
# 之前那枚 4px 宽的竖胶囊在这里只会有 4px。
def runs(row):
    xs = [x for x in range(img.width())
          if img.pixelColor(x, row).name() in (accent.name(), theme.LIGHT["hover_dot"])]
    return (max(xs) - min(xs) + 1) if xs else 0

widths = [(y, runs(y)) for y in range(img.height()) if 0 < runs(y) < img.width() * 0.4]
handle_max = max(w for _, w in widths) if widths else 0
heightunique = max(y for y, _ in widths) - min(y for y, _ in widths) + 1 if widths else 0
assert handle_max >= 6, f"手柄在自身行上只有 {handle_max}px 宽 —— 是竖胶囊不是圆点"
assert abs(handle_max - heightunique) <= 6, (
    f"手柄 {handle_max}x{heightunique}px —— 圆点应该接近正方")
ok.append(f"滑块是圆点手柄（独占行 {handle_max}px、跨 {heightunique} 行）")

# ---------- 4) 进度条：无边框圆角轨道 + 主题色块 ----------
pb = w.render_bar
pb.resize(160, 16)
pb.setValue(60)
pb.show()
app.processEvents()
img = grab(pb)
mid = img.height() // 2
c_left = img.pixelColor(20, mid)
c_right = img.pixelColor(140, mid)
assert c_left.blue() > c_left.red(), f"进度块不是主题色：{c_left.name()}"
assert c_right != c_left, f"轨道与进度块同色：{c_right.name()}"
ok.append(f"进度条（块 {c_left.name()} / 轨道 {c_right.name()}）")

# ---------- 5) 深色主题下箭头要重新生成（按配色区分文件） ----------
w._apply_theme("dark")
app.processEvents()
qss_dark = app.styleSheet()
assert "chev_down_" in qss_dark
import re
p_dark = set(re.findall(r'url\("([^"]+)"\)', qss_dark))
p_light = set(re.findall(r'url\("([^"]+)"\)', theme.app_qss(theme.LIGHT)))
assert p_dark and p_dark != p_light, "深色主题没有用自己的箭头颜色"
ok.append("深浅主题各自生成箭头（深色文件不同）")

print("PASS:", "；".join(ok))
