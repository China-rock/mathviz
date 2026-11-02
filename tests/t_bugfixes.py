"""BUGS-2026-11-02 里各条修复的回归验证。"""
import os
import subprocess
import sys
import tempfile
import time

PROJ = str(__import__("pathlib").Path(__file__).resolve().parents[1])
sys.path.insert(0, PROJ)
TMP = tempfile.mkdtemp(prefix="bugfix_")
os.environ["MATHVIZ_USER_DIR"] = TMP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for k in list(os.environ):
    if "DEEPSEEK" in k.upper():
        os.environ.pop(k)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from app.core import config, feedback, renderer  # noqa: E402
from app.ui.feedback_dialog import FeedbackDialog  # noqa: E402
from app.ui.first_run import ApiKeyDialog  # noqa: E402

ok, bad = [], []
_n = [0]


def check(cond, msg):
    _n[0] += 1
    if not cond:
        bad.append(msg)
        print("  ✗", msg)


# ---------- B-04 .env 行尾注释 ----------
env = os.path.join(TMP, ".env")
cases = [
    ("DEEPSEEK_API_KEY=sk-abc  # 我的 key", "sk-abc", "普通行尾注释"),
    ("DEEPSEEK_API_KEY=\"sk-abc\"  # 注释", "sk-abc", "带引号 + 注释"),
    ("DEEPSEEK_API_KEY=sk-abc#def", "sk-abc#def", "# 前面没空格不算注释"),
    ("DEEPSEEK_API_KEY='sk a # b'", "sk a # b", "引号内的 # 不算注释"),
    ("DEEPSEEK_API_KEY=sk-abc\t# tab 注释", "sk-abc", "tab 分隔的注释"),
]
for line, want, desc in cases:
    with open(env, "w", encoding="utf-8") as f:
        f.write(line + "\n")
    got = config.load_env_file().get("DEEPSEEK_API_KEY")
    check(got == want, f"B-04 {desc}：期望 {want!r}，实际 {got!r}")
ok.append(f".env 行尾注释按规矩剥离（{len(cases)} 种写法）")

# ---------- B-05 码边界 ----------
good = feedback.encode(feedback.build_packet("bug", "标题", "描述", "", False, 0, ""))
for tail in ("thanks", "123", "ok", "看下", "", "!!!", "1."):
    found = feedback.find_codes(good + tail)
    check(bool(found) and found[0] == good,
          f"B-05 码后紧贴 {tail!r}：抠出 {len(found[0]) if found else 0} 字符，"
          f"应等于 {len(good)}")
    if found:
        try:
            feedback.decode(found[0])
        except Exception as e:
            check(False, f"B-05 紧贴 {tail!r} 的码解不开：{e}")
ok.append("码后紧贴英文/数字/标点都能裁回正确边界")

# ---------- B-06 字段长度上限 ----------
pk = feedback.build_packet("bug", "标" * 500, "描" * 20000, "c" * 500, False, 0, "")
check(len(pk["title"]) <= feedback.MAX_TITLE, f"标题未截断：{len(pk['title'])}")
check(len(pk["desc"]) <= feedback.MAX_DESC, f"描述未截断：{len(pk['desc'])}")
check(len(pk["contact"]) <= feedback.MAX_CONTACT, f"联系方式未截断：{len(pk['contact'])}")
check(pk["title"].endswith("…"), "标题截断后没有省略号")
ok.append(f"标题/描述/联系方式分别限 {feedback.MAX_TITLE}/{feedback.MAX_DESC}/"
          f"{feedback.MAX_CONTACT} 字")

d = FeedbackDialog(None)
d.ed_desc.setPlainText("x" * (feedback.MAX_DESC + 100))
app.processEvents()
check("不会发送" in d.lbl_desc_count.text(), f"超限提示缺失：{d.lbl_desc_count.text()}")
check(d.ed_title.maxLength() == feedback.MAX_TITLE, "标题输入框没有长度限制")
ok.append("反馈窗口：描述超限会变红提示，标题/联系方式有输入上限")

# ---------- B-07 坏码给出人话 ----------
for label, broken in (("截掉一半", good[: len(good) // 2]),
                      ("改一个字符", good[:20] + "AAAA" + good[24:])):
    try:
        feedback.decode(broken)
        check(False, f"B-07 {label} 竟然解开了")
    except ValueError as e:
        check("截断" in str(e) or "不完整" in str(e),
              f"B-07 {label} 的提示不像人话：{e}")
    except Exception as e:
        check(False, f"B-07 {label} 抛的不是 ValueError 而是 {type(e).__name__}")
ok.append("损坏/截断的码统一抛 ValueError，提示「被截断，请重新复制」")

# ---------- B-09 清理空白后光标不乱飘 ----------
k = ApiKeyDialog(None, first_run=True)
k.ed_key.setText("")
k.ed_key.insert("sk-ab  cd")
k.ed_key.setCursorPosition(len(k.ed_key.text()))
k.ed_key.setText("sk-ab  cd\t")          # 触发 textChanged
check(k.ed_key.text() == "sk-abcd", f"空白没清干净：{k.ed_key.text()!r}")
check(k.ed_key.cursorPosition() == len("sk-abcd"),
      f"光标落在 {k.ed_key.cursorPosition()}，应在 {len('sk-abcd')}")
ok.append("粘贴带空白时光标停在文本末尾")

# ---------- B-03 退出时杀子进程 ----------
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
renderer._register(child)
time.sleep(0.3)
check(child.poll() is None, "测试进程没起来")
n = renderer.terminate_active()
for _ in range(40):
    if child.poll() is not None:
        break
    time.sleep(0.05)
check(n >= 1, f"terminate_active 返回 {n}，应为 ≥1")
check(child.poll() is not None, "子进程没被终止（会变成孤儿继续跑）")
check(len(renderer._ACTIVE_PROCS) == 0, "登记表没清空")
ok.append("terminate_active() 能杀掉残留渲染进程（含 taskkill /T 杀进程树）")

# ---------- main.py 与主窗口都挂了退出钩子 ----------
src_main = open(os.path.join(PROJ, "app/main.py"), encoding="utf-8").read()
src_win = open(os.path.join(PROJ, "app/ui/main_window.py"), encoding="utf-8").read()
check("aboutToQuit.connect(_kill_renderers)" in src_main, "main.py 没接 aboutToQuit")
check("def closeEvent" in src_win and "terminate_active()" in src_win,
      "主窗口没在 closeEvent 里收进程")
ok.append("退出钩子：main.py 的 aboutToQuit + 主窗口 closeEvent 双保险")

print("\n断言 %d 项全过：" % _n[0])
for m in ok:
    print("  ✓", m)
if bad:
    print("\n失败 %d 项" % len(bad))
    sys.exit(1)
print("\n全绿")
