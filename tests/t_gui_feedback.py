# -*- coding: utf-8 -*-
"""问题反馈：编码/脱敏/收件箱 + 两个界面的行为校验。

跑法（项目根无关，脚本自带路径）：
    .venv\\Scripts\\python.exe C:\\Users\\ChRis\\mathviz_work\\t_gui_feedback.py
"""
import os
import shutil
import sys
import tempfile

PROJ = str(__import__("pathlib").Path(__file__).resolve().parents[1])
sys.path.insert(0, PROJ)

# 全程用临时数据目录，别把测试反馈写进真实的 %LOCALAPPDATA%\MathViz
TMP = tempfile.mkdtemp(prefix="mathviz_fb_")
os.environ["MATHVIZ_USER_DIR"] = TMP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication          # noqa: E402
from PySide6.QtWidgets import QApplication         # noqa: E402

app = QApplication([])

from app.core import config, feedback              # noqa: E402
from app.ui import feedback_dialog, feedback_inbox  # noqa: E402
from app.ui.main_window import MainWindow          # noqa: E402

ok = []
FAKE_KEY = "sk-abcdef0123456789abcdef0123456789"


def check(cond, msg):
    if not cond:
        print("FAIL", msg)
        shutil.rmtree(TMP, ignore_errors=True)
        sys.exit(1)


# ---------- 1) 脱敏：Key 和用户名都不能外泄 ----------
cfg_key = config.get_api_key
config.get_api_key = lambda: FAKE_KEY
try:
    dirty = (f"调用失败 key={FAKE_KEY}\n"
             r"路径 C:\Users\ChRis\AppData\Local\MathVizWork\media\a.mp4" "\n"
             "另一处 sk-9999999999999999zzzz 也要抹掉")
    clean = feedback.redact(dirty)
finally:
    config.get_api_key = cfg_key

check(FAKE_KEY not in clean, f"API Key 没被抹掉：{clean}")
check("sk-999" not in clean, "第二个 key 没被抹掉")
check("ChRis" not in clean, f"用户名没被抹掉：{clean}")
check("<用户>" in clean, "用户名没有替换成占位符")
ok.append("脱敏：Key 与用户名都已隐去")

# ---------- 2) 反馈码：往返、体积、容忍换行 ----------
packet = feedback.build_packet(
    kind="bug", title="渲染卡住",
    desc="用标准画质渲染 40 秒场景，进度条停在 61% 不动了。" * 3,
    contact="qq 123456", include_env=True, log_lines=60,
    context="当前标题：定积分｜编辑器脚本：42 行")
code = feedback.encode(packet)
back = feedback.decode(code)
check(back["title"] == "渲染卡住", "标题没回来")
check(back["desc"] == packet["desc"], "描述没回来")
check(back["kind"] == "bug", "类型没回来")
check(code.startswith(feedback.CODE_PREFIX), f"前缀不对：{code[:12]}")
check(120 < len(code) < 2600, f"反馈码长度 {len(code)} 不适合粘贴")
ok.append(f"编码往返正常，反馈码 {len(code)} 字符（{len(code) / 1024:.1f} KB）")

# 聊天软件会在长文本里插换行，解码要能吃下去
chopped = "\n".join(code[i:i + 60] for i in range(0, len(code), 60))
check(feedback.decode(chopped)["title"] == "渲染卡住", "带换行的反馈码解不开")
# 一次粘多条
two = feedback.find_codes(f"上面这条：\n{code}\n下面还有一条\n{code}")
check(len(two) == 2, f"一次粘贴多条识别失败：{len(two)}")
ok.append("换行/多条粘贴都能正确解析")

# ---------- 3) 邮件：收件人 + 码都在链接里，且不会被客户端截断 ----------
url = feedback.mailto_url(code, packet)
check(url.startswith("mailto:" + feedback.AUTHOR_EMAIL), f"收件人不对：{url[:60]}")
check(feedback.AUTHOR_EMAIL == "china_rock676@163.com", "作者邮箱不对")
check("%E3%80%90MathViz" in url, "主题没有正确编码")
check(feedback.CODE_PREFIX in url or "%2D" in url, "正文里没有反馈码")
ok.append(f"邮件链接已预填收件人（{feedback.AUTHOR_EMAIL}）")

# 真实日志往往几十行；邮件链接必须控制在客户端能吃的长度内
os.makedirs(os.path.join(TMP, "logs"), exist_ok=True)
with open(os.path.join(TMP, "logs", "console.log"), "w", encoding="utf-8") as f:
    for i in range(300):
        f.write(f"[{i:03d}] 渲染进度 {i % 100}%  scene=PackTest  "
                f"elapsed={i * 0.31:.2f}s  media_dir=C:\\Users\\ChRis\\w\\media\n")
for n_try in (60, 200):
    c2, p2, u2, used = feedback.fit_for_mailto(
        lambda n: feedback.build_packet("bug", "日志很长", "描述" * 30,
                                        "", True, min(n, n_try)))
    check(len(u2) <= feedback.MAILTO_MAX,
          f"邮件链接 {len(u2)} 超过上限 {feedback.MAILTO_MAX}（日志 {used} 行）")
    check(feedback.decode(c2)["title"] == "日志很长", "裁过日志的码解不开")
ok.append(f"邮件链接长度受控（实测 {len(u2)} ≤ {feedback.MAILTO_MAX}）")

# ---------- 4) 存档：zip 可回灌、重复导入去重 ----------
zip_path = feedback.save_zip(packet)
check(zip_path.exists() and zip_path.stat().st_size > 0, "zip 没生成")
check(feedback.INBOX_FILE.parent == zip_path.parent, "收件箱和 zip 不在同一目录")
item, is_new = feedback.add_code(code)
check(is_new, "第一次导入应算新增")
item2, is_new2 = feedback.add_code(code)
check(not is_new2 and item2["id"] == item["id"], "重复导入没有去重")
zitem, znew = feedback.add_zip(zip_path)
check(not znew, "zip 回灌应命中同一条")
ok.append("zip 存档可回灌，重复导入自动去重")

# ---------- 5) 反馈窗口：点「复制反馈码」真能拿到码 ----------
dlg = feedback_dialog.FeedbackDialog(None, context="当前标题：测试")
dlg.combo_kind.setCurrentIndex(0)
dlg.ed_title.setText("按钮点不动")
dlg.ed_desc.setPlainText("点了「开始渲染」没有任何反应，控制台也没输出。")
dlg._on_copy()
clip = QGuiApplication.clipboard().text()
check(dlg._last_code and dlg._last_code.startswith(feedback.CODE_PREFIX),
      "对话框没生成反馈码")
check(feedback.decode(dlg._last_code)["title"] == "按钮点不动", "码里内容不对")
check(dlg.lbl_status.isVisible() or dlg.lbl_status.text(), "复制后没有状态提示")
check(feedback.AUTHOR_EMAIL in dlg.lbl_status.text(),
      f"提示里没告诉发给谁：{dlg.lbl_status.text()}")
ok.append("反馈窗口：复制即得码，提示里带作者邮箱")

# 空描述要被拦住
dlg2 = feedback_dialog.FeedbackDialog(None)
dlg2.ed_title.setText("x")
warned = []
feedback_dialog.QMessageBox.warning = lambda *a, **k: warned.append(a)
dlg2._on_copy()
check(warned, "描述为空时没有拦下来")
check(not dlg2._last_code, "被拦下了却还是生成了码")
ok.append("描述为空时会被拦下（不会发出空反馈）")

# 没装邮件客户端时要给出下一步，而不是报错
opened = []
feedback_dialog.QDesktopServices.openUrl = staticmethod(
    lambda u: opened.append(u.toString()) or False)
shown = []
feedback_dialog.QMessageBox.information = lambda *a, **k: shown.append(a)
dlg3 = feedback_dialog.FeedbackDialog(None)
dlg3.ed_desc.setPlainText("这是个测试反馈，描述长度够。")
dlg3._on_mail()
check(opened and opened[0].startswith("mailto:" + feedback.AUTHOR_EMAIL),
      f"邮件链接没打开或收件人不对：{opened[:1]}")
check(shown, "邮件客户端缺失时没有给出替代说明")
ok.append("邮件按钮：收件人已填，缺客户端时给出替代方案")

# ---------- 6) 反馈台：导入、筛选、标记、导出 ----------
inbox = feedback_inbox.FeedbackInbox()
n0 = inbox.list.count()
inbox.ed_code.setText(f"看看这个\n{dlg._last_code}")
inbox._on_paste_import()
check(inbox.list.count() == n0 + 1, f"导入后列表没增加：{inbox.list.count()} vs {n0}")

items = feedback.load_items()
check(len(items) >= 2, f"库里条目数不对：{len(items)}")
check(items[0]["packet"]["title"] == "按钮点不动",
      f"最新导入的反馈没排在最上面：{items[0]['packet']['title']}")
# 同学的机器不该往作者收件箱里写东西 —— 「复制并打开邮箱」只存档 zip
check(not any(it["packet"]["title"] == "这是个测试反馈" for it in items),
      "发邮件的对话框把反馈写进了作者收件箱（跨机器了）")
# 选中刚导入的那条（列表里还有前面几条别的反馈）
target = next(i for i, it in enumerate(inbox._items)
              if it["packet"]["title"] == "按钮点不动")
inbox.list.setCurrentRow(target)
html = inbox.view.toHtml()
check("按钮点不动" in html, "详情里没渲染出反馈内容")
check("环境" in html, "详情里没有环境信息")
ok.append(f"反馈台：导入成功，当前 {inbox.list.count()} 条，详情含环境与日志")

# 标记已处理 → 待处理筛选里应该看不到
fid = inbox._current()["id"]
inbox._set_status("done")
check(any(it["id"] == fid and it["status"] == "done" for it in feedback.load_items()),
      "标记已处理没落盘")
inbox.combo_filter.setCurrentIndex(1)     # 待处理
check(all(it.get("status") != "done" for it in inbox._items), "待处理筛选没生效")
inbox.combo_filter.setCurrentIndex(0)
ok.append("反馈台：标记已处理生效，筛选正确")

csv_path = os.path.join(TMP, "out.csv")
feedback.export_csv(csv_path, feedback.load_items())
head = open(csv_path, encoding="utf-8-sig").readline()
check("收到时间" in head and "联系方式" in head, f"CSV 表头不对：{head}")
rows = open(csv_path, encoding="utf-8-sig").read().splitlines()
check(len(rows) >= 3, f"CSV 行数太少：{len(rows)}")
md_path = os.path.join(TMP, "out.md")
feedback.export_markdown(md_path, feedback.load_items())
check("MathViz 反馈汇总" in open(md_path, encoding="utf-8").read(), "Markdown 导出异常")
ok.append(f"导出 CSV（{len(rows) - 1} 行）与 Markdown 正常")

# ---------- 7) 「关于」里确实有这个入口、也有邮箱 ----------
win = MainWindow()
win._apply_theme("light")
text = win._about_text()
check(feedback.AUTHOR_EMAIL in text, "关于文本里没有反馈邮箱")
check(hasattr(win, "on_feedback"), "主窗口没有 on_feedback")
ctx = win._feedback_context()
check("编辑器脚本" in ctx, f"现场信息不完整：{ctx}")
ok.append("关于框：有反馈邮箱与入口，现场信息自动带上")

shutil.rmtree(TMP, ignore_errors=True)
print("PASS " + " | ".join(ok))
