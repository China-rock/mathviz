"""D2 冒烟：查找替换 / 跳转行 / 注释切换 / 语法标红"""
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

SRC = ("from manim import *\n"
       "class Demo(Scene):\n"
       "    def construct(self):\n"
       "        t = Text(\"alpha\")\n"
       "        self.play(Write(t))\n"
       "        self.wait(1)\n")
w.editor.setPlainText(SRC)

# 1) 查找条
assert w.find_bar.isHidden()
w._show_find_bar(True)
assert w.find_bar.isVisible() and w.find_bar.repl_edit.isVisible()
w.find_bar.find_edit.setText("alpha")
w.find_bar._find(True)
sel = w.editor.textCursor().selectedText()
assert sel == "alpha", sel
ok.append("查找条（定位并选中匹配项）")

# 2) 替换 / 全部替换
w.find_bar.repl_edit.setText("beta")
w.find_bar._replace_one()
assert "beta" in w.editor.toPlainText() and "alpha" not in w.editor.toPlainText()
w.editor.setPlainText("x = 1\ny = 1\nz = 1\n")
w.find_bar.find_edit.setText("1")
w.find_bar.repl_edit.setText("2")
w.find_bar._replace_all()
assert w.editor.toPlainText().count("2") == 3, w.editor.toPlainText()
assert "替换了 3 处" in w.find_bar.lbl_info.text()
ok.append("替换 / 全部替换（可撤销）")

# 3) 跳转行
assert w.editor.goto_line(3) is True
assert w.editor.textCursor().blockNumber() == 2
assert w.editor.goto_line(9999) is False     # 越界返回 False，不崩
ok.append("跳转到行（越界安全）")

# 4) 注释切换：加 # 再去掉，文本应回到原样
w.editor.setPlainText("a = 1\nb = 2\n")
cur = w.editor.textCursor()
cur.select(cur.SelectionType.Document)
w.editor.setTextCursor(cur)
w.editor.toggle_comment()
assert w.editor.toPlainText() == "# a = 1\n# b = 2\n", repr(w.editor.toPlainText())
w.editor.toggle_comment()
assert w.editor.toPlainText() == "a = 1\nb = 2\n", repr(w.editor.toPlainText())
ok.append("注释切换（整行加/去 #，来回无损）")

# 5) 语法标红
w.editor.setPlainText("def f(:\n    pass\n")
w._refresh_syntax()
assert w.lbl_syntax.isVisible() and "语法错误" in w.lbl_syntax.text()
assert len(w.editor.extraSelections()) == 1
w.editor.setPlainText("def f():\n    pass\n")
w._refresh_syntax()
assert w.lbl_syntax.isHidden() and not w.editor.extraSelections()
w.editor.setPlainText("")
w._refresh_syntax()
assert w.lbl_syntax.isHidden()
ok.append("语法错误实时标红 + 改好即清除")

print("PASS " + " | ".join(ok))
