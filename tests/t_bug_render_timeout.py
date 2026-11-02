"""复现 BUG：渲染超时机制失效。

renderer.render 里先 `for raw in proc.stdout` 读完输出，再 `proc.wait(timeout)`。
若 manim 卡住（LaTeX 等输入、字体缓存被占、宏包弹窗），stdout 不会关闭，
for 循环永远阻塞 —— 后面的 wait(timeout) 根本执行不到，900 秒超时形同虚设，
界面会一直停在"渲染中"，只能强杀程序。
"""
import os
import subprocess
import sys
import tempfile
import time

PROJ = str(__import__("pathlib").Path(__file__).resolve().parents[1])
sys.path.insert(0, PROJ)
TMP = tempfile.mkdtemp(prefix="bug_timeout_")
os.environ["MATHVIZ_USER_DIR"] = TMP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core import renderer  # noqa: E402

HANG_SECONDS = 12          # 假进程卡住多久
renderer.RENDER_TIMEOUT_SECONDS = 3   # 期望 3 秒就被判定超时


class HangProc:
    """模拟 manim：打一行日志后就卡死，既不输出也不退出。"""

    def __init__(self, *a, **k):
        self.returncode = None
        self.stdout = self._lines()

    def _lines(self):
        yield "Manim Community v0.19.0\n"
        time.sleep(HANG_SECONDS)
        yield "[假装跑完了]\n"

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("manim", timeout)

    def kill(self):
        self.returncode = -9


real_popen = subprocess.Popen
renderer.subprocess.Popen = HangProc

t0 = time.time()
try:
    ok, mp4, msg = renderer.render("class Scene1(Scene):\n    pass",
                                   "Scene1", "low", log_cb=lambda s: None)
    elapsed = time.time() - t0
    print(f"render 返回：ok={ok} 耗时 {elapsed:.1f}s")
    print(f"提示：{msg.splitlines()[-1][:90] if msg else ''}")
finally:
    renderer.subprocess.Popen = real_popen

# 期望：3 秒左右就判定超时并返回。实际若接近 12 秒，说明卡在 for 循环里。
if elapsed <= renderer.RENDER_TIMEOUT_SECONDS + 2.5:
    print(f"\nPASS 超时生效（{elapsed:.1f}s ≤ 阈值+2.5s）")
    sys.exit(0)
print(f"\nFAIL 超时失效：等了 {elapsed:.1f}s，阈值只有 {renderer.RENDER_TIMEOUT_SECONDS}s")
sys.exit(1)
