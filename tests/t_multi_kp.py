"""多选整合知识点 + 「切回旧对话后生成串台」回归（offscreen）"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJ = str(__import__("pathlib").Path(__file__).resolve().parents[1])
sys.path.insert(0, PROJ)

from PySide6.QtWidgets import QApplication, QListWidgetItem  # noqa: E402

from app.core import config, prompt  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

ok = []
app = QApplication([])
w = MainWindow()
w.show()
app.processEvents()

KP = [
    {"title": "导数的定义", "description": "割线逼近切线", "level": "高中"},
    {"title": "洛必达法则", "description": "0/0 型极限的处理", "level": "大学基础"},
    {"title": "泰勒展开", "description": "用多项式逼近函数", "level": "大学进阶"},
]
w.knowledge_points = list(KP)
w.point_list.clear()
for k in KP:
    QListWidgetItem(k["title"], w.point_list)
w._update_merge_btn()


# ---------- 1) 串台回归：对话主题优先于左栏残留选中 ----------
w._ensure_chat_topic("洛必达法则")
w.chat_plan = "洛必达的清单"
w.point_list.setCurrentRow(0)          # 左栏还停在"导数的定义"（典型串台现场）
title, desc, level = w._generate_subject()
assert title == "洛必达法则", f"应按当前对话主题生成，实际：{title}"
assert desc == "洛必达的清单", desc
ok.append("切回旧对话后生成不再串台（对话主题优先于左栏选中）")

# ---------- 2) 主题与左栏一致时，仍用知识点的描述与难度 ----------
w._ensure_chat_topic("导数的定义")
w.chat_plan = "导数清单"
w.point_list.setCurrentRow(0)
title, desc, level = w._generate_subject()
assert title == "导数的定义", title
assert desc == "割线逼近切线", desc          # 知识点自带描述优先
assert level == "高中", level
ok.append("主题与选中行一致时沿用知识点的描述/难度")

# ---------- 3) 切回会话时左栏自动对齐（对不上就清空） ----------
w._load_chat_session({"title": "洛必达法则", "bubbles": [], "history": [], "plan": ""})
assert w.point_list.currentRow() == 1, w.point_list.currentRow()
assert w._selected_point()["title"] == "洛必达法则"
w._load_chat_session({"title": "自由对话", "bubbles": [], "history": [], "plan": "x"})
assert w.point_list.currentRow() == -1, "对不上知识点时应清空选中"
ok.append("切换会话时左栏选中行自动对齐 / 清空")

# ---------- 4) 多选控制「整合」按钮 ----------
w._ensure_chat_topic("导数的定义")
w.point_list.clearSelection()
w.point_list.setCurrentRow(0)
w._update_merge_btn()
assert not w.btn_merge.isEnabled(), "只选 1 个不该能整合"
assert w.btn_merge.text() == "🧩 整合", w.btn_merge.text()

w.point_list.setCurrentRow(0)
w.point_list.item(1).setSelected(True)
w.point_list.item(2).setSelected(True)
w._update_merge_btn()
assert w.btn_merge.isEnabled(), "选中 3 个应可整合"
assert "3" in w.btn_merge.text(), w.btn_merge.text()
ok.append("整合按钮跟着选中数量启用（0/1 个禁用，2 个以上可用）")

# ---------- 5) 合并主题的命名规则 ----------
assert w._merged_topic(KP[:2]) == "导数的定义 与 洛必达法则", w._merged_topic(KP[:2])
assert w._merged_topic(KP) == "导数的定义 等 3 个知识点", w._merged_topic(KP)
long_topic = w._merged_topic([{"title": "很长的知识点名字" * 5}])
assert len(long_topic) <= 30, len(long_topic)
ok.append("合并主题命名：两个用「与」，更多用「等 N 个」，超长截断")

# ---------- 6) 整合动作：换主题 + 消息带全部知识点 + 走对话页 ----------
sent = []
w._send_message = lambda text, already_shown=False: sent.append(text)
config.get_api_key = lambda: "sk-test"
w._ensure_chat_topic("导数的定义")
w.point_list.clearSelection()
for i in range(3):
    w.point_list.item(i).setSelected(True)
w.on_merge_points()
assert len(sent) == 1, sent
assert w.chat_topic == "导数的定义 等 3 个知识点", w.chat_topic
for k in KP:
    assert k["title"] in sent[0], k["title"]
assert "整合成一支动画" in sent[0] and "逻辑关系" in sent[0], sent[0][:80]
assert w.tabs.currentIndex() == 1, "整合后应切到对话页"
ok.append("整合：换对话主题、消息列出全部知识点、切到对话页")

# ---------- 7) 整合后生成用的是合并主题，不回到某个知识点 ----------
w.chat_plan = "整合后的清单"
title, desc, level = w._generate_subject()
assert title == "导数的定义 等 3 个知识点", title
assert desc == "整合后的清单", desc
ok.append("整合后生成使用合并主题 + 整合后的清单")

# ---------- 8) 选不够两个时给提示、不发消息 ----------
sent.clear()
w.point_list.clearSelection()
w.point_list.setCurrentRow(0)
QMessageBox = __import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox
QMessageBox.information = staticmethod(lambda *a, **k: 0)
w.on_merge_points()
assert not sent, "只选 1 个不该发消息"
ok.append("不够两个知识点时不整合、只提示")

# ---------- 9) 策划提示词含整合规则（两套模板都要有） ----------
assert "整合成一支动画" in prompt.PLAN_SYSTEM
for subj, ex in (("物理", prompt.PLAN_EXAMPLES_PHYSICS),
                 ("数据结构", prompt.PLAN_EXAMPLES_DSA)):
    assert "整合成一支动画" in prompt.plan_system_for(subj, ex), subj
ok.append("策划提示词（数学 / 其他学科模板）都写了整合规则")

print("\n".join("  ✓ " + s for s in ok))
print(f"\n多选整合：{len(ok)} 项通过")
