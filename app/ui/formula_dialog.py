"""数学公式编辑器（小白友好版）：不写 LaTeX 也能拼出公式。

三层用法，从易到难：
1. 「常用公式」标签页：现成的整式（导数定义、勾股定理……）点一下就插入；
2. 分类符号面板：按钮上直接显示公式小图（matplotlib mathtext 渲染），
   点原子符号直接插入；点带空格的模板（分数/根号/求和…）会在下方出现
   「分子 [a] 分母 [b]」这样的中文填空，填完点「插入这段」；
3. 底部源码框：会 LaTeX 的人可以直接手改，实时预览跟着变。

预览走 matplotlib 的 mathtext（不依赖本机 LaTeX）。它不认识 \\begin{…}
环境（矩阵/方程组），此时预览退回显示源码并说明原因 —— 不影响插入。
"""
import io

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

# ---------------------------------------------------------------------------
# 公式目录。每个条目：(中文名, LaTeX 模板, 字段列表, 说明)
#   字段为空 → 原子符号，点了直接插入
#   字段非空 → 模板，{0}{1}… 为占位符，点后在下方出现中文填空
#   demo 用于按钮图标（把字段换成默认值渲出来）
# ---------------------------------------------------------------------------

def _t(cn, tpl, fields=(), tip="", grid=""):
    return {"cn": cn, "tpl": tpl, "fields": list(fields), "tip": tip, "grid": grid}


def _demo(entry):
    return entry["tpl"].format(*[f[1] for f in entry["fields"]])


# 每组：(标签名, 条目列表)
GROUPS = [
    ("常用公式", [
        _t("导数定义", r"f'(x)=\lim_{{h \to 0}} \frac{{f(x+h)-f(x)}}{{h}}",
           tip="导数的极限定义，最常用的整式之一"),
        _t("重要极限", r"\lim_{{x \to 0}} \frac{{\sin x}}{{x}}=1"),
        _t("勾股定理", r"a^{{2}}+b^{{2}}=c^{{2}}"),
        _t("求根公式", r"x=\frac{{-b \pm \sqrt{{b^{{2}}-4ac}}}}{{2a}}"),
        _t("欧拉公式", r"e^{{i\pi}}+1=0"),
        _t("泰勒展开", r"f(x)=\sum_{{n=0}}^{{\infty}} \frac{{f^{{(n)}}(a)}}{{n!}}(x-a)^{{n}}"),
        _t("二项式平方", r"(a+b)^{{2}}=a^{{2}}+2ab+b^{{2}}"),
        _t("高斯积分", r"\int_{{-\infty}}^{{\infty}} e^{{-x^{{2}}}}\,dx=\sqrt{{\pi}}"),
        _t("等差求和", r"1+2+\cdots+n=\frac{{n(n+1)}}{{2}}"),
        _t("函数记号", r"f(x)=x^{{2}}+1"),
        _t("斜率公式", r"k=\frac{{y_{{2}}-y_{{1}}}}{{x_{{2}}-x_{{1}}}}"),
        _t("圆的方程", r"(x-a)^{{2}}+(y-b)^{{2}}=r^{{2}}"),
    ]),
    ("分数与根式", [
        _t("分数", r"\frac{{{0}}}{{{1}}}", [("分子", "a"), ("分母", "b")],
           "上面除以下面"),
        _t("根号", r"\sqrt{{{0}}}", [("里面的数", "x")]),
        _t("n 次根", r"\sqrt[{0}]{{{1}}}", [("开几次方", "n"), ("里面的数", "x")]),
        _t("繁分式", r"\frac{{1}}{{1+\frac{{{0}}}{{{1}}}}}",
           [("分子", "a"), ("分母", "b")]),
        _t("带系数分式", r"\frac{{{0}}}{{{1}}}{{{2}}}",
           [("分子", "1"), ("分母", "2"), ("后面的式子", "x")]),
    ]),
    ("上下标", [
        _t("上标（平方）", r"{{{0}}}^{{{1}}}", [("底数", "x"), ("指数", "2")]),
        _t("下标", r"{{{0}}}_{{{1}}}", [("主体", "x"), ("下标", "i")]),
        _t("上下标同用", r"{{{0}}}_{{{1}}}^{{{2}}}",
           [("主体", "a"), ("下标", "i"), ("指数", "2")]),
        _t("e 的指数", r"e^{{{0}}}", [("指数", "x")]),
        _t("一撇（导数记号）", r"{{{0}}}'", [("函数", "f")]),
    ]),
    ("求和积分", [
        _t("求和", r"\sum_{{{0}}}^{{{1}}} {{{2}}}",
           [("从", "i=1"), ("到", "n"), ("求和的项", "i")]),
        _t("积分", r"\int_{{{0}}}^{{{1}}} {{{2}}}\,d{{{3}}}",
           [("下限", "a"), ("上限", "b"), ("被积函数", "f(x)"), ("积分变量", "x")]),
        _t("不定积分", r"\int {{{0}}}\,d{{{1}}}",
           [("被积函数", "f(x)"), ("变量", "x")]),
        _t("极限", r"\lim_{{{0}}} {{{1}}}",
           [("趋近", r"x \to 0"), ("式子", "f(x)")]),
        _t("连乘", r"\prod_{{{0}}}^{{{1}}} {{{2}}}",
           [("从", "i=1"), ("到", "n"), ("项", "a_i")]),
        _t("双重积分", r"\iint_{{D}} {{{0}}}\,dxdy", [("被积函数", "f(x,y)")]),
    ]),
    ("希腊字母", [
        _t("alpha", r"\alpha"), _t("beta", r"\beta"), _t("gamma", r"\gamma"),
        _t("delta（小）", r"\delta"), _t("Delta（大）", r"\Delta"),
        _t("epsilon", r"\varepsilon"), _t("theta", r"\theta"),
        _t("lambda", r"\lambda"), _t("mu", r"\mu"), _t("pi", r"\pi"),
        _t("rho", r"\rho"), _t("sigma", r"\sigma"), _t("Sigma（大）", r"\Sigma"),
        _t("phi", r"\varphi"), _t("Phi（大）", r"\Phi"), _t("omega", r"\omega"),
        _t("Omega（大）", r"\Omega"), _t("eta", r"\eta"), _t("tau", r"\tau"),
        _t("xi", r"\xi"), _t("zeta", r"\zeta"),
    ]),
    ("关系与运算", [
        _t("小于等于", r"\leq"), _t("大于等于", r"\geq"), _t("不等于", r"\neq"),
        _t("约等于", r"\approx"), _t("正负号", r"\pm"), _t("乘号", r"\times"),
        _t("除号", r"\div"), _t("无穷", r"\infty"),
        _t("属于", r"\in"), _t("不属于", r"\notin"), _t("包含于", r"\subset"),
        _t("并集", r"\cup"), _t("交集", r"\cap"), _t("空集", r"\emptyset"),
        _t("推出", r"\Rightarrow"), _t("等价", r"\Leftrightarrow"),
        _t("任意", r"\forall"), _t("存在", r"\exists"),
        _t("偏导数", r"\partial"), _t("梯度", r"\nabla"),
        _t("向量箭头", r"\vec{{{0}}}", [("字母", "v")]),
        _t("绝对值", r"\left|{{{0}}}\right|", [("里面的数", "x")]),
        _t("范数", r"\left\|{{{0}}}\right\|", [("向量", "v")]),
        _t("角度", r"{{{0}}}^{{\circ}}", [("度数", "30")]),
    ]),
    ("函数与括号", [
        _t("sin", r"\sin"), _t("cos", r"\cos"), _t("tan", r"\tan"),
        _t("ln", r"\ln"), _t("log", r"\log"), _t("log 底 a", r"\log_{{{0}}} {{{1}}}",
           [("底", "a"), ("真数", "x")]),
        _t("max", r"\max"), _t("min", r"\min"),
        _t("圆括号（自适应）", r"\left( {{{0}}} \right)", [("里面的式子", r"\frac{a}{b}")]),
        _t("方括号（自适应）", r"\left[ {{{0}}} \right]", [("里面的式子", "x")]),
        _t("花括号（自适应）", r"\left\{{ {{{0}}} \right\}}", [("里面的式子", "x")]),
        _t("箭头 to", r"\to"), _t("映射", r"{{{0}}}: {{{1}}} \to {{{2}}}",
           [("f(x) 记号", "f"), ("定义域", "A"), ("值域", "B")]),
        _t("省略号（中）", r"\cdots"), _t("省略号（下）", r"\ldots"),
    ]),
    ("矩阵与方程组", [
        _t("矩阵", "", tip="像表格一样选行数列数、逐格填写，所见即所得", grid="matrix"),
        _t("行列式", "", tip="竖线括号的行列式，同样按格子填写", grid="det"),
        _t("方程组 / 分段函数", "", tip="一行一条方程（或一段分支），花括号括起", grid="cases"),
    ]),
]

# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

_render_cache: dict = {}


# ---------------------------------------------------------------------------
# 矩阵网格编辑器：像 Excel 一样选行×列、逐格填写，所见即所得。
# 背景：matplotlib mathtext 不支持 \begin{…} 矩阵环境，无法走「小图按钮 +
# 预览」的路子；Qt 生态也没有现成的轻量公式编辑器组件（Web 方案要内嵌
# Chromium）。自绘网格最可控：网格本身就是预览，点「插入」拼出 LaTeX。
# ---------------------------------------------------------------------------

class MatrixDialog(QDialog):
    """矩阵 / 行列式 / 方程组的网格编辑器。accept() 后读 latex()。"""

    BRACKETS = [("方括号 [ ]", "bmatrix"), ("圆括号 ( )", "pmatrix"),
                ("竖线 | |（行列式）", "vmatrix"), ("大括号 { }", "BMatrix")]
    TITLES = {"matrix": "矩阵编辑器", "det": "行列式编辑器",
              "cases": "方程组 / 分段函数编辑器"}

    def __init__(self, parent=None, kind: str = "matrix"):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle(self.TITLES[kind])
        self.resize(500, 380)
        self._build()
        self._rebuild_grid()

    def _build(self):
        from PySide6.QtWidgets import QComboBox, QSpinBox
        v = QVBoxLayout(self)

        tip = QLabel("选好行数列数，逐格点进去填数字或字母，然后点「插入到公式」。\n"
                     "格子里的内容就是最终显示的样子，所见即所得。")
        tip.setStyleSheet("color:#57606a;")
        v.addWidget(tip)

        opt = QHBoxLayout()
        opt.addWidget(QLabel("行数："))
        self.spin_r = QSpinBox()
        self.spin_r.setRange(1, 6)
        self.spin_r.setValue(3 if self.kind == "cases" else 2)
        self.spin_r.valueChanged.connect(self._rebuild_grid)
        opt.addWidget(self.spin_r)
        if self.kind != "cases":
            opt.addWidget(QLabel("列数："))
            self.spin_c = QSpinBox()
            self.spin_c.setRange(1, 6)
            self.spin_c.setValue(2)
            self.spin_c.valueChanged.connect(self._rebuild_grid)
            if self.kind == "det":
                # 行列式只对 n×n 方阵有意义：列数锁死，跟着行数走
                self.spin_c.setEnabled(False)
                self.spin_c.setToolTip("行列式必须是方阵，列数自动跟随行数")
                lbl_square = QLabel("（行列式必须方阵，列数跟随行数）")
                lbl_square.setStyleSheet("color:#8b949e; font-size:11px;")
                opt.addWidget(lbl_square)
            opt.addWidget(self.spin_c)
        if self.kind == "matrix":
            opt.addWidget(QLabel("括号："))
            self.combo_b = QComboBox()
            for name, _env in self.BRACKETS:
                self.combo_b.addItem(name)
            self.combo_b.currentIndexChanged.connect(self._update_brackets)
            opt.addWidget(self.combo_b)
        opt.addStretch(1)
        v.addLayout(opt)

        # 括号 + 网格：括号用大号字符贴在两侧，网格本身就是"预览"
        grid_row = QHBoxLayout()
        self.lbl_lb = QLabel("[")
        self.lbl_rb = QLabel("]")
        for w in (self.lbl_lb, self.lbl_rb):
            f = w.font()
            f.setPointSize(30)
            w.setFont(f)
        grid_row.addWidget(self.lbl_lb)
        self.table = QTableWidget()
        self.table.horizontalHeader().hide()
        self.table.verticalHeader().hide()
        self.table.setMinimumHeight(160)
        grid_row.addWidget(self.table, 1)
        grid_row.addWidget(self.lbl_rb)
        v.addLayout(grid_row, 1)

        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color:#c0392b;")
        self.lbl_err.hide()
        v.addWidget(self.lbl_err)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("插入到公式")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._accept)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        v.addLayout(row)

    def _update_brackets(self, idx: int = -1):
        lb, rb = "[", "]"
        if hasattr(self, "combo_b"):
            name = self.BRACKETS[max(self.combo_b.currentIndex(), 0)][0]
            lb = {"方": "[", "圆": "(", "竖": "|", "大": "{"}.get(name[0], "[")
            rb = {"[": "]", "(": ")", "|": "|", "{": "}"}[lb]
        elif self.kind == "cases":
            lb, rb = "{", ""
        elif self.kind == "det":
            lb, rb = "|", "|"
        self.lbl_lb.setText(lb)
        self.lbl_rb.setText(rb)

    def _rebuild_grid(self):
        rows = self.spin_r.value()
        if self.kind == "cases":
            cols = 1
        elif self.kind == "det":
            cols = rows          # 方阵：列数跟着行数走
            if self.spin_c.value() != rows:
                self.spin_c.blockSignals(True)
                self.spin_c.setValue(rows)
                self.spin_c.blockSignals(False)
        else:
            cols = self.spin_c.value()
        self.table.setRowCount(rows)
        self.table.setColumnCount(cols)
        for r in range(rows):
            for c in range(cols):
                default = (f"x+y={r+1}" if self.kind == "cases"
                           else str(r * cols + c + 1))
                self.table.setItem(r, c, QTableWidgetItem(default))
        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self._update_brackets()

    def _build_latex(self):
        rows, env = [], ""
        n_r, n_c = self.table.rowCount(), self.table.columnCount()
        if self.kind == "det" and n_r != n_c:
            return None, f"行列式必须是方阵（现在 {n_r} 行 {n_c} 列）"
        for r in range(n_r):
            cells = []
            for c in range(n_c):
                it = self.table.item(r, c)
                text = (it.text().strip() if it else "")
                if not text:
                    return None, f"第 {r+1} 行第 {c+1} 列还没填"
                cells.append(text)
            rows.append(" & ".join(cells))
        if self.kind == "cases":
            env = "cases"
        elif self.kind == "det":
            env = "vmatrix"
        else:
            env = self.BRACKETS[self.combo_b.currentIndex()][1]
        return "\\begin{%s} %s \\end{%s}" % (env, " \\\\ ".join(rows), env), ""

    def _accept(self):
        latex, err = self._build_latex()
        if latex is None:
            self.lbl_err.setText(f"⚠ {err}")
            self.lbl_err.show()
            return
        self._latex_out = latex
        self.accept()

    def latex(self) -> str:
        return getattr(self, "_latex_out", "")


def render_mathtext(text: str, fontsize: int = 20, dpi: int = 150,
                    figsize=(6.0, 1.1)):
    """把 LaTeX 片段渲染成 QPixmap，返回 (pixmap 或 None, 失败原因)。"""
    key = (text, fontsize, dpi)
    if key in _render_cache:
        return _render_cache[key]
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        return None, f"未可用渲染后端（{e}）"
    try:
        fig = plt.figure(figsize=figsize)
        fig.text(0.5, 0.5, f"${text}$", fontsize=fontsize,
                 ha="center", va="center")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", transparent=True, dpi=dpi,
                    bbox_inches="tight")
        plt.close(fig)
        pm = QPixmap()
        if not pm.loadFromData(buf.getvalue(), "PNG"):
            return None, "图像解码失败"
        if pm.isNull() or pm.width() == 0:
            return None, "渲染结果为空"
        result = (pm, "")
    except Exception as e:
        if "\\begin{" in text:
            result = (None, "含 \\begin{…} 环境，mathtext 无法预览")
        else:
            result = (None, str(e).splitlines()[0][:90]
                      or f"mathtext 不支持（{type(e).__name__}）")
    _render_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# 弹窗
# ---------------------------------------------------------------------------

BTN_SIZE = QSize(92, 48)


class FormulaDialog(QDialog):
    """公式编辑弹窗。exec() 返回 Accepted 后读 latex() 拿到源码。"""

    def __init__(self, parent=None, initial: str = ""):
        super().__init__(parent)
        self.setWindowTitle("数学公式编辑器")
        self.resize(660, 560)
        self._builder_entries: list = []
        self._build()
        if initial:
            self.edit.setPlainText(initial)
        self._render()

    # ---------- 界面

    def _build(self):
        v = QVBoxLayout(self)

        tip = QLabel("点下面的按钮拼公式，填空即可 —— 不用写 LaTeX；"
                     "会的话也可以直接在底部源码框里改。")
        tip.setStyleSheet("color:#57606a;")
        tip.setWordWrap(True)
        v.addWidget(tip)

        # 预览区
        self.lbl_preview = QLabel("（还没有公式）")
        self.lbl_preview.setMinimumHeight(110)
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet(
            "QLabel { background:#fafbfc; border:1px solid #e4e6ea;"
            " border-radius:6px; }")
        v.addWidget(self.lbl_preview, 1)
        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color:#8b949e;")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.hide()
        v.addWidget(self.lbl_hint)

        # 分类标签页：每页一组图像按钮
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 2)
        self._page_built: dict[int, bool] = {}
        for i, (name, _items) in enumerate(GROUPS):
            page = QWidget()
            grid = QGridLayout(page)
            grid.setSpacing(4)
            self.tabs.addTab(page, name)
            self._page_built[i] = False   # 懒渲染：切到该页才生成按钮
        # 连接信号要在 addTab 之后：addTab 会触发 currentChanged，
        # 若提前连接，第一页会在页面尚未就绪时被构建两次
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._build_page(0)

        # 模板填空区（点带空格的模板按钮时出现）
        self.builder_box = QWidget()
        self.builder_box.setStyleSheet(
            "QWidget { background:#f6f9ff; border:1px solid #d6e4ff;"
            " border-radius:6px; }")
        self.builder_form = QFormLayout(self.builder_box)
        self.builder_form.setContentsMargins(8, 6, 8, 6)
        self.builder_form.setSpacing(4)
        self.builder_row = QHBoxLayout()
        self.builder_row.addStretch(1)
        btn_add = QPushButton("＋ 插入这段")
        btn_add.clicked.connect(self._insert_built)
        self.builder_row.addWidget(btn_add)
        self.builder_form.addRow(self.builder_row)
        self.builder_box.hide()
        v.addWidget(self.builder_box)

        # 源码框（高级，可手改）
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("公式源码（LaTeX，可改）："))
        src_row.addStretch(1)
        btn_clear_src = QPushButton("清空")
        btn_clear_src.setFixedWidth(56)
        btn_clear_src.clicked.connect(lambda: self.edit.setPlainText(""))
        src_row.addWidget(btn_clear_src)
        v.addLayout(src_row)
        self.edit = QPlainTextEdit()
        self.edit.setFixedHeight(56)
        self.edit.setPlaceholderText(
            r"例如：f(x)=x^2     \frac{a}{b}     \lim_{x \to 0} \frac{\sin x}{x}=1")
        self.edit.textChanged.connect(self._schedule_render)
        v.addWidget(self.edit)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("插入到对话")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        row.addWidget(btn_cancel)
        row.addWidget(self.btn_ok)
        v.addLayout(row)

        # 输入防抖：连续敲键盘不必每次都重绘
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self._render)

    def _build_page(self, idx: int):
        """首次切到某页时才渲染这页的按钮图标（每个图标一次 mathtext 绘制）。"""
        if self._page_built.get(idx):
            return
        name, items = GROUPS[idx]
        page = self.tabs.widget(idx)
        grid = page.layout()
        # 腾出最后一行给 builder 之前先清掉旧内容
        while grid.count():
            it = grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        col_n = 5
        for i, entry in enumerate(items):
            b = QPushButton()
            b.setFixedSize(BTN_SIZE)
            b.setToolTip(f"{entry['cn']}\n{entry['tip'] or '点击插入'}")
            demo = _demo(entry)
            pm, _err = render_mathtext(demo, fontsize=17, dpi=200,
                                       figsize=(1.6, 0.6))
            if pm is not None:
                b.setIcon(QIcon(pm.scaled(
                    BTN_SIZE - QSize(6, 6),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)))
                b.setIconSize(BTN_SIZE - QSize(6, 6))
            else:
                # 矩阵/方程组这类环境渲染不出来 → 用文字按钮
                b.setText(entry["cn"])
            b.clicked.connect(lambda _=False, e=entry: self._on_entry(e))
            grid.addWidget(b, i // col_n, i % col_n)
        self._page_built[idx] = True

    # ---------- 行为

    def _on_tab_changed(self, idx: int):
        self._build_page(idx)
        self.builder_box.hide()   # 换页时收起填空区

    def _on_entry(self, entry: dict):
        if entry.get("grid"):
            # 矩阵/行列式/方程组 → 打开网格编辑器
            dlg = MatrixDialog(self, entry["grid"])
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.latex():
                self._append(dlg.latex())
            return
        if not entry["fields"]:
            self._append(entry["tpl"])
            return
        # 模板：展开中文填空区
        self._builder_entries = [entry]
        # 清掉旧的字段行（保留最后的"插入这段"行）
        while self.builder_form.rowCount() > 1:
            self.builder_form.removeRow(0)
        self._builder_edits = []
        for label, default in entry["fields"]:
            e = QLineEdit(default)
            e.textChanged.connect(self._update_builder_preview)
            self._builder_edits.append(e)
            self.builder_form.insertRow(self.builder_form.rowCount() - 1,
                                        label, e)
        self.builder_box.show()
        self._update_builder_preview()
        if self._builder_edits:
            self._builder_edits[0].setFocus()
            self._builder_edits[0].selectAll()

    def _built_latex(self) -> str:
        if not self._builder_entries:
            return ""
        entry = self._builder_entries[0]
        vals = [e.text().strip() or d[1] for e, d in
                zip(self._builder_edits, entry["fields"], strict=True)]
        return entry["tpl"].format(*vals)

    def _update_builder_preview(self):
        """填空时把结果实时写进源码框（预览由源码框统一驱动）。"""
        text = self._built_latex()
        if self.edit.toPlainText() != text:
            self.edit.setPlainText(text)

    def _insert_built(self):
        self._append(self._built_latex())
        self.builder_box.hide()

    def _append(self, snip: str):
        cur = self.edit.textCursor()
        cur.insertText(snip)
        self.edit.setFocus()

    def _schedule_render(self):
        self._timer.start()

    def latex(self) -> str:
        return self.edit.toPlainText().strip()

    def _render(self):
        text = self.latex()
        if not text:
            self.lbl_preview.setText("（还没有公式）")
            self.lbl_preview.setPixmap(QPixmap())
            self.lbl_hint.hide()
            return
        pm, err = render_mathtext(text)
        if pm is None:
            self.lbl_preview.setPixmap(QPixmap())
            self.lbl_preview.setText(text)
            self.lbl_hint.setText(
                f"这个公式暂时无法预览（{err}）—— 不影响插入，"
                "AI 收到的就是这段源码。")
            self.lbl_hint.show()
        else:
            self.lbl_hint.hide()
            self.lbl_preview.setText("")
            self.lbl_preview.setPixmap(pm)
