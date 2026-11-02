"""C 组冒烟：倍速 / 逐帧 / 键盘 / A-B 循环 / 全屏（offscreen）"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow

app = QApplication([])
w = MainWindow()
w.show()
ok = []

# 造一支"成片"：offscreen 下不真解码，播放控制逻辑只需要一个真实存在的小视频文件
import tempfile
_fd, MP4 = tempfile.mkstemp(suffix=".mp4", prefix="mathviz_test_")
os.close(_fd)
w.current_video = MP4
# offscreen 环境没有解码后端，真 QMediaPlayer 的 position() 恒为 0，
# 这里换一个只会记位置的替身，把"控制逻辑"和"能不能解码"分开验。
class FakePlayer:
    def __init__(self):
        self._pos, self._dur = 0, 60000
    def position(self): return self._pos
    def duration(self): return self._dur
    def setPosition(self, p): self._pos = max(0, min(self._dur, int(p)))
    def pause(self): pass
    def playbackState(self): return None
w.player = FakePlayer()
w._apply_media_enabled()
assert w.combo_speed.isEnabled() and w.btn_fs.isEnabled()
assert w.act_loop_a.isEnabled() and w.act_step_fwd.isEnabled()
ok.append("播放增强控件随成片启用")

# 1) 倍速
w.combo_speed.setCurrentIndex(0)          # 0.5x
assert abs(w.combo_speed.currentData() - 0.5) < 1e-9
w.combo_speed.setCurrentIndex(w.combo_speed.findData(1.0))
assert "00:00" in w.lbl_time.text() and "0.5x" not in w.lbl_time.text()
w.combo_speed.setCurrentIndex(0)
w._update_time_label(0, 60000)
assert "0.5x" in w.lbl_time.text(), w.lbl_time.text()
ok.append("倍速（0.5x~2x，时间标签显示当前倍率）")

# 2) 逐帧
w.player.setPosition(5000)
w._step_frame(+1)
assert w.player.position() == 5033, w.player.position()
w._step_frame(-2)
assert w.player.position() == 4967, w.player.position()
ok.append("逐帧前进/后退（33ms/帧）")

# 3) A-B 循环
w.player.setPosition(3000)
w._set_loop_point("a")
w.player.setPosition(9000)
w._set_loop_point("b")
assert w._loop_active()
assert "⟲00:03~00:09" in w.lbl_time.text(), w.lbl_time.text()
w.act_loop_clear.setEnabled(True)
# 位置越过 B 时应自动跳回 A
w._seeking = False
w._on_position_changed(9100)
assert w.player.position() == 3000, w.player.position()
w._clear_loop()
assert not w._loop_active() and not w.act_loop_clear.isEnabled()
# 设反了要自动换回来
w.player.setPosition(9000)
w._set_loop_point("a")
w.player.setPosition(2000)
w._set_loop_point("b")
assert w._loop_a == 2000 and w._loop_b == 9000
w._clear_loop()
ok.append("A-B 循环（含端点颠倒自动换回、到 B 跳回 A）")

# 5) 快捷键：焦点在编辑器里时不抢键（空格是打字，方向键是移动光标）
w.player.setPosition(10000)
app.setActiveWindow(w)      # 全屏窗口销毁后活动窗口可能为空，先把主窗口扶正
app.processEvents()
w.editor.setFocus()
app.processEvents()
assert QApplication.focusWidget() is w.editor, QApplication.focusWidget()
w._media_hotkey("-5s")
assert w.player.position() == 10000, "在编辑器里按 ← 不该被播放器抢走"
w.editor.clearFocus()
app.processEvents()
w._media_hotkey("-5s")
assert w.player.position() == 5000, w.player.position()
ok.append("快捷键不抢输入框的按键（焦点在编辑器里自动让行）")

# 4) 全屏：搬出去再插回原位的父控件变化
assert w._fs_window is None
parent_before = w.video_container.parent()
w._toggle_fullscreen()
assert w._fs_window is not None
assert w.video_container.parent() is not parent_before
assert w.btn_expand.isHidden()
w._toggle_fullscreen()
assert w._fs_window is None
assert w.video_container.parent() is parent_before, "退出全屏要插回预览页原位"
assert w.btn_expand.isVisible()
ok.append("全屏进出（画面搬进顶层窗口并归位）")

print("PASS " + " | ".join(ok))
