"""Manim 脚本编辑器：行号 + Python 语法高亮（浅色主题）。

外加三件"改脚本时真的会用"的小工具：查找/替换条、跳转行、注释切换，
以及语法错误行标红。手写脚本的人多半不是程序员，这些是刚需。
"""
import re

from PySide6.QtCore import QRect, QSize, Qt, QRegularExpression
from PySide6.QtGui import (QColor, QFont, QPainter, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor, QTextDocument)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QTextEdit, QWidget)

KEYWORDS = [
    "and", "as", "assert", "async", "await", "break", "class", "continue",
    "def", "del", "elif", "else", "except", "finally", "for", "from",
    "global", "if", "import", "in", "is", "lambda", "nonlocal", "not",
    "or", "pass", "raise", "return", "try", "while", "with", "yield",
    "True", "False", "None",
]


def _fmt(color: str, italic: bool = False, bold: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if italic:
        f.setFontItalic(True)
    if bold:
        f.setFontWeight(QFont.Bold)
    return f


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self._multiline = _fmt("#8c8c8c", italic=True)
        self.set_colors(None)     # None = 用内置的浅色配色

    def set_colors(self, p: dict | None):
        """换主题：配色来自 app/ui/theme.py 的调色板（缺键就回落浅色默认值）。"""
        d = p or {}
        g = lambda k, default: d.get(k, default)
        self.rules = [
            (QRegularExpression(r"\b(?:%s)\b" % "|".join(KEYWORDS)),
             _fmt(g("kw", "#0033b3"), bold=True)),
            (QRegularExpression(r"\b(?:def|class)\s+\w+"),
             _fmt(g("def", "#6f42c1"), bold=True)),
            (QRegularExpression(r"\b(?:self|np|math)\b"), _fmt(g("self", "#7a3e9d"))),
            (QRegularExpression(r"\b[A-Z_][A-Z0-9_]{2,}\b"), _fmt(g("const", "#b01700"))),
            (QRegularExpression(r"\b\d+(?:\.\d+)?\b"), _fmt(g("num", "#1750eb"))),
            (QRegularExpression(r"r?\"[^\"\n]*\"|r?'[^'\n]*'"), _fmt(g("str", "#067d17"))),
            (QRegularExpression(r"#[^\n]*"), _fmt(g("cmt", "#8c8c8c"), italic=True)),
        ]
        self._multiline = _fmt(g("cmt", "#8c8c8c"), italic=True)

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
        # 三引号字符串跨行高亮（状态机：1 = 位于三引号内）
        start = 0
        if self.previousBlockState() != 1:
            m = re.search(r'"""', text)
            if m:
                start = m.start()
                if text.count('"""', m.start()) >= 2:  # 同行闭合
                    self.setFormat(start, text.find('"""', start + 3) + 3 - start, self._multiline)
                    self.setCurrentBlockState(0)
                    return
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self._multiline)
            else:
                self.setCurrentBlockState(0)
        else:
            end = text.find('"""')
            if end == -1:
                self.setCurrentBlockState(1)
                self.setFormat(0, len(text), self._multiline)
            else:
                self.setCurrentBlockState(0)
                self.setFormat(0, end + 3, self._multiline)


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFont("Consolas", 11)
        font.setFixedPitch(True)
        self.setFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.highlighter = PythonHighlighter(self.document())
        self._line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_area_width)
        self.updateRequest.connect(self._update_area)
        self._update_area_width()
        self._gutter_bg = QColor("#f0f0f0")
        self._gutter_fg = QColor("#999999")

    def apply_theme(self, p: dict):
        """跟随界面主题：代码区底色、行号区配色、语法高亮一起换。"""
        self.highlighter.set_colors(p)
        self._gutter_bg = QColor(p.get("gutter_bg", "#f0f0f0"))
        self._gutter_fg = QColor(p.get("gutter_fg", "#999999"))
        self.setStyleSheet(
            f"QPlainTextEdit {{ background:{p.get('code_bg', '#ffffff')};"
            f" color:{p.get('text', '#23272e')};"
            f" border:1px solid {p.get('border', '#d0d4d9')}; border-radius:4px; }}")
        self._line_area.update()
        self.highlighter.rehighlight()

    def line_number_width(self):
        digits = max(2, len(str(self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_area_width(self, *_):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_area(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(),
                                          self.line_number_width(), cr.height()))

    # ------------------------------------------------------------ 编辑小工具

    def goto_line(self, n: int) -> bool:
        """跳到第 n 行（1 起数），并把它滚到视野中央。"""
        doc = self.document()
        block = doc.findBlockByNumber(max(0, n - 1))
        if not block.isValid():
            return False
        cur = QTextCursor(block)
        self.setTextCursor(cur)
        self.centerCursor()
        self.setFocus()
        return True

    def toggle_comment(self):
        """Ctrl+/：把选中的每一行加上/去掉 `# ` 注释。

        按整行处理（而不是光标处插一个 #），因为脚本里最常见的需求是
        "整段先注释掉看看"，而不是在行尾补个井号。
        """
        cur = self.textCursor()
        start, end = cur.selectionStart(), cur.selectionEnd()
        sblock = self.document().findBlock(start)
        eblock = self.document().findBlock(end)
        first, last = sblock.blockNumber(), eblock.blockNumber()
        cur.beginEditBlock()
        for i in range(first, last + 1):
            block = self.document().findBlockByNumber(i)
            if not block.isValid():
                continue
            c = QTextCursor(block)
            text = block.text()
            if not text.strip():
                continue        # 空行不加注释（选区含末尾空行时尤其明显）
            if text.lstrip().startswith("#"):
                idx = text.index("#")
                # 去掉 # 以及紧随其后的一个空格（#  这种多空格只去一个，保留对齐）
                c.setPosition(block.position() + idx)
                strip = 2 if text[idx + 1:idx + 2] == " " else 1
                c.setPosition(block.position() + idx + strip,
                              QTextCursor.MoveMode.KeepAnchor)
                c.removeSelectedText()
            else:
                c.setPosition(block.position())
                c.insertText("# ")
        cur.endEditBlock()

    def mark_error_line(self, lineno: int | None):
        """把某一行标红（语法错误所在行）；传 None 表示清除标记。

        用 ExtraSelection 而不是改文档内容：它是"附加选择"，不参与撤销栈，
        也不会影响脚本本身 —— 标红只是提示，不是编辑。
        """
        if lineno is None:
            self.setExtraSelections([])
            return
        block = self.document().findBlockByNumber(max(0, lineno - 1))
        if not block.isValid():
            self.setExtraSelections([])
            return
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(255, 214, 214))
        sel.format.setForeground(QColor("#8a1f1f"))
        cur = QTextCursor(block)
        sel.cursor = cur
        self.setExtraSelections([sel])

    def paint_line_numbers(self, event):
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), self._gutter_bg)
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(self._gutter_fg)
                painter.drawText(0, top, self._line_area.width() - 6,
                                 self.fontMetrics().height(),
                                 int(Qt.AlignmentFlag.AlignRight), str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1


class FindBar(QWidget):
    """脚本编辑器里的查找 / 替换条（Ctrl+F 唤出，Esc 收起）。

    为什么自己写而不用 Qt 自带的查找对话框：那个对话框是模态的，
    弹出来就没法一边看脚本一边改；这一条贴在编辑器上方，
    查找时脚本仍然可见、可滚动、可继续敲字。
    """

    def __init__(self, editor: CodeEditor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setObjectName("findBar")
        self.setStyleSheet(
            "QWidget#findBar { background:#f4f6f8; border:1px solid #dfe3e8;"
            " border-radius:6px; }")

        h = QHBoxLayout(self)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(4)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("查找（Enter 找下一个）")
        self.find_edit.setFixedWidth(200)
        self.find_edit.returnPressed.connect(lambda: self._find(True))
        self.find_edit.textChanged.connect(lambda _=None: self._find(True))
        h.addWidget(self.find_edit)

        self.btn_prev = QPushButton("↑")
        self.btn_prev.setFixedWidth(30)
        self.btn_prev.setToolTip("上一个（Shift+Enter）")
        self.btn_prev.clicked.connect(lambda: self._find(False))
        self.btn_next = QPushButton("↓")
        self.btn_next.setFixedWidth(30)
        self.btn_next.setToolTip("下一个（Enter）")
        self.btn_next.clicked.connect(lambda: self._find(True))
        h.addWidget(self.btn_prev)
        h.addWidget(self.btn_next)

        self.repl_edit = QLineEdit()
        self.repl_edit.setPlaceholderText("替换为")
        self.repl_edit.setFixedWidth(180)
        h.addWidget(self.repl_edit)
        self.btn_repl = QPushButton("替换")
        self.btn_repl.setToolTip("替换当前这一处，并跳到下一处")
        self.btn_repl.clicked.connect(self._replace_one)
        self.btn_repl_all = QPushButton("全部替换")
        self.btn_repl_all.setToolTip("一次替换脚本里所有匹配处（可撤销）")
        self.btn_repl_all.clicked.connect(self._replace_all)
        h.addWidget(self.btn_repl)
        h.addWidget(self.btn_repl_all)

        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color:#8a8f98; border:none; background:transparent;")
        h.addWidget(self.lbl_info)
        h.addStretch(1)
        btn_close = QPushButton("✕")
        btn_close.setFixedWidth(30)
        btn_close.setToolTip("关闭（Esc）")
        btn_close.clicked.connect(self.hide_and_focus)
        h.addWidget(btn_close)
        self.hide()

    # ---------------------------------------------------------------- 行为

    def show_find(self, replace: bool = False):
        self.show()
        self.repl_edit.setVisible(replace)
        self.btn_repl.setVisible(replace)
        self.btn_repl_all.setVisible(replace)
        cur = self.editor.textCursor()
        if cur.hasSelection():
            self.find_edit.setText(cur.selectedText()[:80].replace("\u2029", " "))
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self._find(True)

    def hide_and_focus(self):
        self.hide()
        self.editor.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide_and_focus()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) \
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._find(False)
            return
        super().keyPressEvent(event)

    def _flags(self, forward: bool) -> QTextDocument.FindFlags:
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        return flags

    def _find(self, forward: bool = True):
        text = self.find_edit.text()
        if not text:
            self.lbl_info.setText("")
            return
        if self.editor.find(text, self._flags(forward)):
            self.lbl_info.setText("")
            return
        # 到头了就绕回去再找一次（常见编辑器的行为），绕一圈还没有才报"没找到"
        cur = self.editor.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.Start if forward
                         else QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cur)
        found = self.editor.find(text, self._flags(forward))
        self.lbl_info.setText("" if found else "没找到")

    def _replace_one(self):
        text = self.find_edit.text()
        if not text:
            return
        cur = self.editor.textCursor()
        if cur.hasSelection() and cur.selectedText() == text:
            cur.insertText(self.repl_edit.text())
        self._find(True)

    def _replace_all(self):
        text = self.find_edit.text()
        if not text:
            return
        cur = self.editor.textCursor()
        cur.beginEditBlock()
        cur.movePosition(QTextCursor.MoveOperation.Start)
        self.editor.setTextCursor(cur)
        n = 0
        while self.editor.find(text):
            self.editor.textCursor().insertText(self.repl_edit.text())
            n += 1
            if n > 5000:        # 保险：脚本再大也不该无限循环
                break
        cur.endEditBlock()
        self.lbl_info.setText(f"替换了 {n} 处" if n else "没找到")
