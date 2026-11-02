# 本轮四项 UI 修复的冒烟测试：
# 1) 单一渲染入口  2) spinbox 数字可见（按钮钉右侧）  3) 全屏退出后画面对齐  4) 现代控件 QSS
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from app.ui.main_window import MainWindow
from app.ui import theme

app = QApplication([])
w = MainWindow(); w.show(); app.processEvents()
ok = []

# ---------- 1) 单一渲染入口 ----------
assert hasattr(w, "btn_render") and not hasattr(w, "btn_render_high")
w.combo_quality.setCurrentIndex(w.combo_quality.findData("medium"))
assert "720p" in w.btn_render.text()
w.combo_quality.setCurrentIndex(w.combo_quality.findData("high"))
assert "1080p" in w.btn_render.text()
assert w.act_render_hd_once.isEnabled() or not w.editor.toPlainText().strip()
w.combo_quality.setCurrentIndex(w.combo_quality.findData("low"))
ok.append("单一渲染入口（btn_render 跟画质，Ctrl+Shift+R 变临时高清）")

# ---------- 2) QSS：spinbox 按钮钉右侧 / 下拉三角 / 细滚动条 / 滑块 / 进度条 ----------
qss = app.styleSheet()
for must in ("QSpinBox::up-button", "subcontrol-position: top right",
             "QComboBox::down-arrow", "QScrollBar::handle:vertical",
             "QSlider::handle:horizontal", "QProgressBar::chunk"):
    assert must in qss, f"全局 QSS 缺 {must}"
ok.append("主题 QSS 覆盖 spinbox/combo/scrollbar/slider/progressbar")

# ---------- 3) 全屏退出后画面 item 尺寸跟齐 ----------
# offscreen 不真解码，画面同步逻辑只需要一个真实存在的视频文件
import tempfile
_fd, MP4 = tempfile.mkstemp(suffix=".mp4", prefix="mathviz_test_")
os.close(_fd)
w.current_video = MP4
w._apply_media_enabled()
w.resize(1000, 700); app.processEvents()

vw = w.video_widget
def sync_ok():
    vp = vw.view.viewport()
    return (round(vw.item.size().width()), round(vw.item.size().height())) == \
           (vp.width(), vp.height())

assert sync_ok(), "初始就不同步"
w._toggle_fullscreen(); app.processEvents()
assert sync_ok(), "进入全屏后不同步"
w._exit_fullscreen(); app.processEvents()
# 关键：reparent 回来后（布局还没挪完孩子）item 也不该停在全屏尺寸 —— 延迟对齐兜底
final = None
def check():
    global final
    final = sync_ok()
QTimer.singleShot(50, check)
app.exec() if False else None
for _ in range(20):
    app.processEvents()
assert sync_ok(), f"退出全屏后 item {vw.item.size()} != viewport {vw.view.viewport().size()}"
ok.append("全屏进出后视频 item 尺寸跟齐 viewport")

# ---------- 4) 硬要构造"resize 事件时 viewport 还是旧尺寸"的场景也能自愈 ----------
w.video_container.setParent(None)
vw.resize(900, 500)          # 模拟 container 尚未插回、canvas 先被拉大
app.processEvents()
w._preview_v.insertWidget(0, w.video_container, 1)
w.video_container.show()
for _ in range(20):
    app.processEvents()
assert sync_ok(), "reparent 场景未自愈"
ok.append("reparent 后延迟同步自愈")

print("PASS:", "；".join(ok))
