"""B-11：渲染中关窗口要问一句（默认"继续渲染"）。

要点：手滑关窗不该无声丢掉一次十几分钟的渲染；但确认之后必须真的
把 manim 进程杀掉（否则窗口没了它还在后台跑）。
"""
import os
import subprocess
import sys
import tempfile
import time
from unittest import mock

PROJ = str(__import__("pathlib").Path(__file__).resolve().parents[1])
sys.path.insert(0, PROJ)
os.environ["MATHVIZ_USER_DIR"] = tempfile.mkdtemp(prefix="quit_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["MATHVIZ_TEST_DIALOGS"] = "1"     # 允许测确认框本身

from PySide6.QtWidgets import QApplication, QMessageBox        # noqa: E402

app = QApplication([])

from app.core import renderer                                   # noqa: E402
from app.ui.main_window import (BatchWorker, MainWindow,        # noqa: E402
                                RenderWorker)

ok, bad = [], []
_n = [0]


def check(cond, name):
    """name 是中性的"这条在验什么"，通过时不打印，失败时打出来。"""
    _n[0] += 1
    if cond:
        ok.append(name)
    else:
        bad.append(name)
        print("  ✗", name)


def spawn_sleeper():
    """冒充 manim：一个不会自己退出的子进程。"""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    renderer._register(p)
    for _ in range(40):
        if p.poll() is None:
            break
        time.sleep(0.02)
    return p


def dead(p, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if p.poll() is not None:
            return True
        time.sleep(0.05)
    return False


# ---------- 1) 没有渲染时不打扰 ----------
win = MainWindow()
win.show()
app.processEvents()
called = []
win._confirm_abort_render = lambda d: called.append(d) or True
check(win._render_in_progress() == "", "空闲时判为未渲染")
win.close()
app.processEvents()
check(not called, "空闲关窗不弹确认框")
check(not win.isVisible(), "空闲关窗直接放行")

# ---------- 2) 有 manim 进程 → 认得出来 ----------
win2 = MainWindow()
win2.show()
app.processEvents()
p1 = spawn_sleeper()
d = win2._render_in_progress()
check(bool(d), "裸 manim 进程也能判出渲染中")
check("渲染" in d, f"描述说明了在渲染（'{d}'）")
check(renderer.active_count() >= 1, "active_count 统计到存活进程")

# ---------- 3) 单支渲染线程 → 带进度 ----------
fake_rw = mock.Mock(spec=RenderWorker)
fake_rw.isRunning.return_value = True
real_worker = win2._worker
win2._worker = fake_rw
win2.render_bar.setValue(42)
d = win2._render_in_progress()
check("42" in d, f"单支渲染描述带进度（'{d}'）")
win2._worker = real_worker

# ---------- 4) 批量线程 → 报第几个 ----------
fake_bw = mock.Mock(spec=BatchWorker)
fake_bw.isRunning.return_value = True
win2.batch_bar.setRange(0, 7)
win2.batch_bar.setValue(3)
win2._batch_worker = fake_bw
d = win2._render_in_progress()
check("批量" in d and "3" in d and "7" in d, f"批量描述带序号（'{d}'）")
win2._batch_worker = None

# ---------- 5) 确认框本身：默认"继续渲染"，Esc 也是 ----------
seen = []


def fake_exec(self):
    seen.append(self)
    return 0


QMessageBox.exec = fake_exec

result = win2._confirm_abort_render("正在渲染「定积分」，进度 42%")
box = seen[-1]
texts = [b.text() for b in box.buttons()]
check(result is False, "未点击时按'取消关闭'处理（保守）")
check(len(texts) == 2, f"只有两个按钮（{texts}）")
check(any("继续渲染" in t for t in texts), f"有「继续渲染」（{texts}）")
check(any("仍然关闭" in t for t in texts), f"有「仍然关闭」（{texts}）")
check(box.defaultButton() is not None
      and "继续渲染" in box.defaultButton().text(), "回车默认「继续渲染」")
check(box.escapeButton() is not None
      and "继续渲染" in box.escapeButton().text(), "Esc 也是「继续渲染」")
check("42%" in box.text(), f"框里说清在渲染什么（'{box.text()}'）")
check("中断" in box.informativeText(), "框里说明后果（会中断本次渲染）")

# ---------- 6) 选"继续渲染" → 不关窗、进程还活着 ----------
win2._confirm_abort_render = lambda d: False
win2.close()
app.processEvents()
check(win2.isVisible(), "选「继续渲染」窗口不关")
check(p1.poll() is None, "选「继续渲染」进程保住")
log_txt = win2.log_view.toPlainText()
check("取消关闭" in log_txt, "日志留下'已取消关闭'")

# ---------- 7) 选"仍然关闭" → 关窗且真的杀掉 ----------
win2._confirm_abort_render = lambda d: True
win2.close()
app.processEvents()
check(dead(p1), "选「仍然关闭」进程被终止")
check(renderer.active_count() == 0, "登记表清空")

# ---------- 8) 确认关闭时先叫停批量队列 ----------
win3 = MainWindow()
win3.show()
app.processEvents()
p2 = spawn_sleeper()
fake_bw2 = mock.Mock(spec=BatchWorker)
fake_bw2.isRunning.return_value = True
win3._batch_worker = fake_bw2
win3._worker = fake_bw2
win3._confirm_abort_render = lambda d: True
win3.close()
app.processEvents()
check(fake_bw2.cancel.called, "关窗前先 cancel 批量队列")
check(dead(p2), "批量中关窗也杀掉进程")

# ---------- 9) app 级退出钩子仍在（main.py 的 aboutToQuit） ----------
src = open(os.path.join(PROJ, "app/main.py"), encoding="utf-8").read()
check("aboutToQuit.connect(_kill_renderers)" in src, "main.py 的 aboutToQuit 兜底仍在")

print("\n断言 %d 项：" % _n[0])
for m in ok:
    print("  ✓", m)
if bad:
    print("\n失败 %d 项：" % len(bad))
    for m in bad:
        print("  ✗", m)
    sys.exit(1)
print("\n全部通过（%d 项）" % _n[0])
