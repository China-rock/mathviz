"""D5 冒烟：对话右键菜单（复制 / 重编辑 / 重生成 / 删除）"""
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

# 造一场对话：user -> assistant -> system
w.chat_bubbles = []
w.chat_view.clear()
w.chat_history = []
w._append_chat("user", "我想理解极限的定义")
w._append_chat("assistant", "呈现清单：1 割线逼近 2 ε-δ")
w._append_chat("system", "可以点确认生成脚本了")
w.chat_history = [{"role": "user", "content": "我想理解极限的定义"},
                  {"role": "assistant", "content": "呈现清单：1 割线逼近 2 ε-δ"}]
w.chat_plan = "呈现清单：1 割线逼近 2 ε-δ"

assert w._last_user_index() == 0
assert w._last_assistant_text().startswith("呈现清单")
ok.append("定位最后一条提问 / 回复")

# 1) 复制最后一条回复
w._copy_last_reply()
assert app.clipboard().text() == "呈现清单：1 割线逼近 2 ε-δ"
# 2) 复制整段
w._copy_all_chat()
clip = app.clipboard().text()
assert "我：我想理解极限的定义" in clip and "AI：呈现清单" in clip and "—：可以点确认" in clip
ok.append("复制最后一条 / 整段对话")

# 3) 重新编辑上一条：原文回输入框，且这一组从气泡与历史里去掉
w._edit_last_message()
assert w.chat_input.toPlainText() == "我想理解极限的定义"
assert w.chat_bubbles == [], w.chat_bubbles
assert w.chat_history == [], w.chat_history
app.processEvents()
assert QApplication.focusWidget() is w.chat_input, QApplication.focusWidget()
ok.append("重新编辑上一条（原文回输入框 + 双向清理）")

# 4) 重新生成：只丢回复，提问保留，历史里 user 也只留一条
w.chat_input.clear()
w.chat_bubbles = []
w.chat_view.clear()
w.chat_history = []
w._append_chat("user", "换个讲法")
w.chat_history.append({"role": "user", "content": "换个讲法"})
w._append_chat("assistant", "旧的一版答案")
w.chat_history.append({"role": "assistant", "content": "旧的一版答案"})
w._regenerate_last.__self__  # noqa
# 不真的调 API（没 Key 时会弹窗），直接验清理逻辑：手动走同一条路径的前半段
saved = w._send_message
calls = []
w._send_message = lambda t, already_shown=False: calls.append((t, already_shown))
import app.ui.main_window as mw
mw.config.get_api_key = lambda: "sk-test"     # 让它走到发请求那一步
w._regenerate_last()
assert calls == [("换个讲法", True)], calls
assert len(w.chat_history) == 1 and w.chat_history[0]["role"] == "user"
assert [r for r, _ in w.chat_bubbles] == ["user"], w.chat_bubbles
w._send_message = saved
ok.append("重新生成（只丢回复、提问不重复入历史）")

# 5) 删除最后一组：清空呈现清单
w._append_chat("assistant", "又一版")
w.chat_plan = "又一版"
w._delete_last_group()
assert w.chat_bubbles == [] and w.chat_plan == ""
ok.append("删除最后一组（含呈现清单复位）")

print("PASS " + " | ".join(ok))
