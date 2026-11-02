"""首次启动向导：配 Key、装 LaTeX。

开发环境下这两件事都不是问题（Key 在 .env 里、LaTeX 早就装好了），所以以前
没有界面。但打包分发后目标机器上一无所有，没有界面就等于软件不可用 ——
用户既不知道去哪申请 Key，也不知道为什么渲染必然失败。
"""
import re

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProxyStyle, QPushButton,
                               QStyle, QVBoxLayout)

from app.core import config, texenv

DEEPSEEK_KEY_URL = "https://platform.deepseek.com/api_keys"

# DeepSeek 的 Key 形如 sk- + 48 位字符，短于这个数基本就是没粘全
_KEY_TYPICAL_LEN = 51


class _DotPasswordStyle(QProxyStyle):
    """把密码字符固定成实心圆点 ●。

    PySide6 没有暴露 QLineEdit::passwordCharacter，遮蔽字符只能由 QStyle 的
    SH_LineEdit_PasswordCharacter 决定：Windows 11 风格给的是 ●，但别的风格
    （Fusion 之类）会用 *，换台机器就可能显示成星号。这里统一压成 ●，
    保证任何机器上都是"输密码"的手感。
    """

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_LineEdit_PasswordCharacter:
            return 0x25CF          # ●
        return super().styleHint(hint, option, widget, returnData)


class ApiKeyDialog(QDialog):
    """让用户输入 DeepSeek API Key。

    保存位置是用户目录的 .env（打包后程序目录可能只读），不入库、不进安装包。
    """

    def __init__(self, parent=None, first_run: bool = False):
        super().__init__(parent)
        self.first_run = first_run
        self.setWindowTitle("配置 DeepSeek API Key"
                            if first_run else "更改 DeepSeek API Key")
        self.setMinimumWidth(520)

        v = QVBoxLayout(self)
        v.setSpacing(10)

        lead = QLabel(
            "MathViz 调用 DeepSeek 把课件变成 Manim 脚本，需要你自己的 Key。\n"
            f"Key 只保存在本机：{config.ENV_FILE}\n"
            "不会随安装包发给别人，也不会上传到除 DeepSeek 之外的任何地方。")
        lead.setWordWrap(True)
        v.addWidget(lead)

        row = QHBoxLayout()
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_key.setStyle(_DotPasswordStyle())     # 遮蔽字符固定为 ●
        self.ed_key.setPlaceholderText("粘贴你的 Key（sk- 开头），以圆点显示")
        self.ed_key.setClearButtonEnabled(True)
        row.addWidget(self.ed_key, 1)
        self.btn_show = QPushButton("显示")
        self.btn_show.setCheckable(True)
        self.btn_show.setFixedWidth(56)
        self.btn_show.setToolTip("按住核对刚粘贴的内容，看完记得点回「隐藏」")
        self.btn_show.toggled.connect(self._on_toggle_show)
        row.addWidget(self.btn_show)
        v.addLayout(row)

        # 圆点遮住之后看不出"到底粘上没有"，所以报个位数
        self.lbl_count = QLabel("")
        self.lbl_count.setEnabled(False)      # 借系统灰，浅色/深色主题都看得清
        v.addWidget(self.lbl_count)

        # 信号放在最后连：预填已有 Key 会触发 textChanged，而 _sync_key 要用
        # btn_show / lbl_count，连早了会在控件还没建好时炸掉
        self.ed_key.textChanged.connect(self._sync_key)
        cur = config.get_api_key()
        if cur:
            self.ed_key.setText(cur)
        self._sync_key()

        v.addWidget(QLabel(
            f"还没有 Key？点下面的按钮去官网申请（注册即送额度）：{DEEPSEEK_KEY_URL}"))

        row_btn = QHBoxLayout()
        btn_apply = QPushButton("去官网申请 Key")
        btn_apply.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DEEPSEEK_KEY_URL)))
        row_btn.addWidget(btn_apply)
        row_btn.addStretch(1)
        btn_ok = QPushButton("保存" if first_run else "保存并关闭")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._on_ok)
        row_btn.addWidget(btn_ok)
        if not first_run:      # 首次启动时不能跳过，否则后面每一步都会失败
            btn_cancel = QPushButton("取消")
            btn_cancel.clicked.connect(self.reject)
            row_btn.addWidget(btn_cancel)
        v.addLayout(row_btn)

    # ---------- 输入体验

    def _on_toggle_show(self, on: bool):
        """显示 / 隐藏切换。显示时用等宽字体，长串 Key 才核对得清。"""
        self.ed_key.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        self.btn_show.setText("隐藏" if on else "显示")
        if on:
            f = self.ed_key.font()
            f.setStyleHint(QFont.StyleHint.Monospace)
            self.ed_key.setFont(f)
        else:
            f = self.ed_key.font()
            f.setStyleHint(QFont.StyleHint.System)
            self.ed_key.setFont(f)
        self._sync_key()

    def _sync_key(self):
        """去掉误粘进来的空白，并把"粘上没有"用位数反馈出来。"""
        text = self.ed_key.text()
        clean = re.sub(r"\s+", "", text)      # Key 里不该有空格/换行，多半是粘来的
        if clean != text:
            pos = self.ed_key.cursorPosition()
            # 光标按「它前面还剩多少字符」落位。直接沿用原偏移的话，被删掉的空白
            # 仍占着位置，光标就会飘到右边的错地方。
            head = len(re.sub(r"\s+", "", text[:pos]))
            self.ed_key.blockSignals(True)
            self.ed_key.setText(clean)
            self.ed_key.setCursorPosition(min(head, len(clean)))
            self.ed_key.blockSignals(False)
            text = clean
        self.key_len = len(text)
        if not text:
            self.lbl_count.setText("")
        elif self.btn_show.isChecked():
            self.lbl_count.setText(f"共 {self.key_len} 位")
        else:
            self.lbl_count.setText(
                f"已输入 {self.key_len} 位（以圆点显示，点右侧「显示」可核对）")

    # ---------- 保存

    def _on_ok(self):
        key = self.ed_key.text().strip()
        if not key:
            QMessageBox.warning(self, "Key 为空", "请粘贴你的 DeepSeek API Key。")
            return
        if len(key) < _KEY_TYPICAL_LEN - 15:
            # 常见事故：只选中了一半就复制，或者换行把后面截掉了
            r = QMessageBox.question(
                self, "Key 看起来不完整",
                f"DeepSeek 的 Key 一般 {_KEY_TYPICAL_LEN} 位左右，"
                f"你这里只有 {len(key)} 位。\n"
                "多半是复制时没选全，仍然保存吗？")
            if r != QMessageBox.StandardButton.Yes:
                return
        elif not key.startswith("sk-"):
            r = QMessageBox.question(
                self, "看起来不像 DeepSeek 的 Key",
                f"DeepSeek 的 Key 通常以 sk- 开头，你填的是「{key[:3]}…」"
                f"（共 {len(key)} 位）。\n"
                "仍然保存吗？")
            if r != QMessageBox.StandardButton.Yes:
                return
        config.save_api_key(key)
        self.accept()


def show_tex_guide(parent=None, title: str = "需要先安装 LaTeX") -> bool:
    """没有 LaTeX 时给一份能照着做的说明。返回 True 表示用户点了「去下载」。"""
    _, detail = texenv.check()
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText("没检测到 LaTeX，公式渲染无法进行。")
    box.setInformativeText(detail)
    btn_go = box.addButton("去下载 MiKTeX", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("以后再说", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(btn_go)
    box.exec()
    if box.clickedButton() is btn_go:
        QDesktopServices.openUrl(QUrl(texenv.MIKTEX_DOWNLOAD_URL))
        return True
    return False


def tex_ready(parent=None) -> bool:
    """渲染前的 LaTeX 预检：缺环境就弹引导，并把这次渲染拦下来。

    拦下来是对的 —— 不拦的话用户要等 manim 跑半天，最后只看到一句
    "latex is not recognized"，根本不知道该装什么。
    """
    ok, _ = texenv.check()
    if ok:
        return True
    show_tex_guide(parent)
    return False


def maybe_notify_tex(parent=None) -> None:
    """启动时的温柔提醒：只提示一次，别每次启动都弹。"""
    ok, _ = texenv.check()
    if ok:
        return
    st = QSettings("MathViz", "MathViz")
    if st.value("tex_notified", False, type=bool):
        return
    st.setValue("tex_notified", True)
    show_tex_guide(parent, title="提示：还差一个 LaTeX 环境")
