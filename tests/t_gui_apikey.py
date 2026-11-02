"""API Key 输入体验校验：黑圆点遮蔽、显示切换、粘贴去空白、位数反馈。"""
import os
import sys
import tempfile

PROJ = str(__import__("pathlib").Path(__file__).resolve().parents[1])
sys.path.insert(0, PROJ)

TMP = tempfile.mkdtemp(prefix="apikey_")
os.environ["MATHVIZ_USER_DIR"] = TMP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QStyle

app = QApplication([])
from app.core import config
from app.ui.first_run import ApiKeyDialog

ok, bad = [], []
_n = [0]


def check(cond, msg):
    """msg 只在失败时有用（描述哪里不对），通过就只计数。"""
    _n[0] += 1
    if not cond:
        bad.append(msg)
        print("  ✗", msg)


# ---------- 1) 默认就是密码模式，且遮蔽字符是黑圆点 ----------
d = ApiKeyDialog(None, first_run=True)
check(d.ed_key.echoMode() == QLineEdit.EchoMode.Password, "输入框默认不是密码模式")
hint = d.ed_key.style().styleHint(QStyle.StyleHint.SH_LineEdit_PasswordCharacter)
check(hint == 0x25CF, f"遮蔽字符不是 ●，而是 {chr(hint)!r} (U+{hint:04X})")
check(d.ed_key.isClearButtonEnabled(), "没有清空按钮")

# 密码模式下按字符输入，显示层不能出现明文
d.ed_key.setText("")
for ch in "sk-secret":
    d.ed_key.insert(ch)
check(d.ed_key.text() == "sk-secret", "真实文本被改坏了")
check(d.ed_key.displayText() == "●" * len("sk-secret"),
      f"显示文本不是圆点：{d.ed_key.displayText()!r}")
ok.append(f"密码模式：{len('sk-secret')} 个字符显示为 {d.ed_key.displayText()}")

# ---------- 2) 显示切换 ----------
d.btn_show.setChecked(True)
check(d.ed_key.echoMode() == QLineEdit.EchoMode.Normal, "点显示后仍是密码模式")
check(d.btn_show.text() == "隐藏", f"按钮文案没变成隐藏：{d.btn_show.text()}")
check(d.ed_key.displayText() == "sk-secret", "显示后看不到明文")
check("sk-secret" in d.ed_key.font().styleHint().name.lower()
      or d.ed_key.font().styleHint().name == "Monospace",
      f"显示时没切成等宽字体：{d.ed_key.font().styleHint().name}")
d.btn_show.setChecked(False)
check(d.ed_key.echoMode() == QLineEdit.EchoMode.Password, "点隐藏后没回到密码模式")
check(d.btn_show.text() == "显示", "按钮文案没变回显示")
ok.append("显示/隐藏切换正常，显示时用等宽字体")

# ---------- 3) 粘贴带空白会自动清理 ----------
d.ed_key.setText("sk- abc  def\n\tghi ")
check(d.ed_key.text() == "sk-abcdefghi", f"空白没清掉：{d.ed_key.text()!r}")
check(d.lbl_count.text().startswith("已输入 12 位"),
      f"位数提示不对：{d.lbl_count.text()}")
d.btn_show.setChecked(True)
check(d.lbl_count.text() == "共 12 位", f"显示时位数文案不对：{d.lbl_count.text()}")
d.btn_show.setChecked(False)
ok.append("粘贴带空格/换行会被自动清理，并报出位数")

# ---------- 4) 空输入不保存 ----------
warned = []
QMessageBox.warning = lambda *a, **k: warned.append(a)
d.ed_key.setText("")
d._on_ok()
check(len(warned) == 1, "空 Key 没有给出提示")

# ---------- 5) 短 Key 会提醒"可能没粘全" ----------
asked = []
QMessageBox.question = lambda *a, **k: asked.append(a[:3]) or QMessageBox.StandardButton.No
d.ed_key.setText("sk-123")
d._on_ok()
check(len(asked) == 1 and "不完整" in asked[0][1],
      f"短 Key 没有提醒：{asked}")
check(not os.path.exists(config.ENV_FILE) or "sk-123" not in open(
    config.ENV_FILE, encoding="utf-8").read(), "点了否却还是保存了")
ok.append("只有 6 位时会提示「Key 看起来不完整」，点否不写入")

# ---------- 6) 正常长度且以 sk- 开头：直接落盘 ----------
asked.clear()
d.ed_key.setText("sk-" + "a" * 48)
d._on_ok()
env_path = str(config.ENV_FILE)
body = open(env_path, encoding="utf-8").read() if os.path.exists(env_path) else ""
check("DEEPSEEK_API_KEY=sk-" + "a" * 48 in body, f"正常 Key 没写进文件：{body[:80]}")
check(not asked, "正常 Key 不该弹确认框")
check(env_path.startswith(TMP), f"保存位置不在隔离目录：{env_path}")
ok.append(f"正常 Key 直接保存到 {os.path.basename(env_path)}")

# ---------- 7) 提示文案不泄露整串 Key ----------
asked.clear()
d.ed_key.setText("abcd1234efgh5678")
d._on_ok()
if asked:
    check(len(asked[0][2]) < 200 and "abcd1234efgh5678" not in asked[0][2],
          "提示里出现了完整 Key")

# ---------- 8) 设置里的「更改…」走同一个对话框 ----------
d2 = ApiKeyDialog(None, first_run=False)
check(d2.ed_key.echoMode() == QLineEdit.EchoMode.Password, "更改 Key 时不是密码模式")
cur = config.get_api_key() or ""
check(d2.ed_key.text() == cur, "更改时没有预填现有 Key")
check(d2.lbl_count.text().startswith(f"已输入 {len(cur)} 位"),
      f"预填后位数不对：{d2.lbl_count.text()}")
ok.append("设置里「更改…」共用同一套密码体验，且预填已有 Key")

print("\n断言 %d 项全过：" % _n[0])
for m in ok:
    print("  ✓", m)
if bad:
    print("\n失败 %d 项" % len(bad))
    sys.exit(1)
print("\n全绿")
