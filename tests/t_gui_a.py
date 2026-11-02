"""A 组冒烟：画质档位 / 分段 / 快检 / 进度（offscreen）"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from app.core import renderer
from app.ui.main_window import MainWindow

PROJ = str(__import__("pathlib").Path(__file__).resolve().parents[1])
CODE = open(os.path.join(PROJ, "scenes", "E2E_Derivative.py"), encoding="utf-8").read()

app = QApplication([])
w = MainWindow()
w.show()
app.processEvents()
ok = []

# 1) 画质三档
assert [w.combo_quality.itemData(i) for i in range(3)] == ["low", "medium", "high"], "画质档位"
assert renderer.QUALITY_LABELS["medium"] == "720p"
assert renderer.quality_fps("medium") == 30
w.combo_quality.setCurrentIndex(1)
assert w._current_quality() == "medium"
assert "720p" in w.btn_render.text(), w.btn_render.text()
w.combo_quality.setCurrentIndex(2)
assert "1080p" in w.btn_render.text()
assert not hasattr(w, "btn_render_high"), "旧的高清按钮应已删除（单一渲染入口）"
w.combo_quality.setCurrentIndex(0)
ok.append("画质三档 + 单一渲染入口（按钮文字跟档位走）")

# 2) 分辨率换算（含 720p）
assert renderer.resolution_for("16:9", "low") == (854, 480)
assert renderer.resolution_for("16:9", "medium") == (1280, 720)
assert renderer.resolution_for("9:16", "medium") == (720, 1280)
assert renderer.qc_resolution_for("16:9") == (640, 360)
ok.append("分辨率换算（720p / 快检 640x360）")

# 3) 段数统计与分段控件
w.editor.setPlainText(CODE)
w._refresh_pacing()
n = renderer.count_plays(CODE)
assert n > 0, n
assert f"共 {n} 段" in w.lbl_plays.text(), w.lbl_plays.text()
assert w._current_anim_range() is None
w.chk_range.setChecked(True)
w.spin_from.setValue(2)
w.spin_to.setValue(3)
assert w._current_anim_range() == (2, 3)
w.spin_from.setValue(5)
w.spin_to.setValue(2)
assert w._current_anim_range() == (2, 5), "起止颠倒应自动换回来"
assert w.spin_from.maximum() == n
ok.append(f"分段控件（脚本共 {n} 段）")

# 4) 进度条初始隐藏，信号能点亮
assert w.render_bar.isHidden()
w._on_render_progress(42)
assert w.render_bar.isVisible() and w.render_bar.value() == 42
w.render_bar.hide()
ok.append("渲染进度条")

# 5) 快检真跑一遍（真渲染，耗时长但值得）
w.current_scene_name = "E2E_Derivative"
w.combo_layout.setCurrentIndex(0)
res = {}
import threading

def _run():
    okq, dest, msg = renderer.render_quickcheck(
        CODE, "E2E_Derivative", layout="16:9", frames=4, log_cb=lambda m: res.setdefault("log", []).append(m))
    res["ok"], res["dest"], res["msg"] = okq, dest, msg

t = threading.Thread(target=_run)
t.start()
t.join(300)
assert res.get("ok"), res.get("msg")
pngs = sorted(p for p in __import__("pathlib").Path(res["dest"]).glob("*.png"))
assert len(pngs) == 4, pngs
ok.append(f"版式快检真渲染 -> {len(pngs)} 张定格（{res['msg']}）")

print("PASS " + " | ".join(ok))
