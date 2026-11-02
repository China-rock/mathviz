"""问题反馈窗口（「帮助 → 关于 → 问题反馈」进来）。

设计取向：这个软件发给同学用，对方不会为了报个 bug 去注册账号或配邮箱。
所以主按钮是「复制反馈码」—— 复制完粘到微信发我即可；同时提供
「复制并打开邮箱」，装了邮件客户端的人可以一步发走，收件人已经填好。
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from app.core import feedback
from app.ui import theme


class FeedbackDialog(QDialog):
    """收集一条反馈，产出「反馈码」。"""

    def __init__(self, parent=None, context: str = ""):
        super().__init__(parent)
        self.setWindowTitle("问题反馈")
        self.setMinimumWidth(560)
        self._context = context
        self._last_code: str | None = None
        self._p = theme.resolve(
            QSettings("MathViz", "MathViz").value("ui_theme", "light", type=str))

        v = QVBoxLayout(self)
        v.setSpacing(10)

        lead = QLabel(
            "遇到 bug 或有改进想法，在这里说一声就行。反馈会压缩成一小段"
            "「反馈码」，复制后粘到微信 / QQ 发给我即可。\n"
            "反馈里会自动带上环境信息和最近日志（API Key 和用户名会自动隐去），"
            "这样我才能定位问题。")
        lead.setWordWrap(True)
        v.addWidget(lead)

        # ---- 收件人：明写在界面上，避免「点完不知道发给了谁」
        row_to = QHBoxLayout()
        lbl_to = QLabel(f"发到：<b>{feedback.AUTHOR_EMAIL}</b>")
        lbl_to.setTextInteractionFlags(
            lbl_to.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        row_to.addWidget(lbl_to, 1)
        btn_mail_copy = QPushButton("复制邮箱")
        btn_mail_copy.setToolTip("手动发邮件时用得上")
        btn_mail_copy.clicked.connect(self._copy_email)
        row_to.addWidget(btn_mail_copy)
        v.addLayout(row_to)

        # ---- 表单
        form = QFormLayout()
        form.setSpacing(8)

        self.combo_kind = QComboBox()
        for key, label in feedback.KINDS.items():
            self.combo_kind.addItem(label, key)
        form.addRow("类型", self.combo_kind)

        self.ed_title = QLineEdit()
        self.ed_title.setMaxLength(feedback.MAX_TITLE)
        self.ed_title.setPlaceholderText("一句话概括，例如：渲染到一半进度条卡住不动")
        form.addRow("标题", self.ed_title)

        self.ed_desc = QPlainTextEdit()
        self.ed_desc.setPlaceholderText(
            "详细说说：你做了什么操作、期望看到什么、实际发生了什么。\n"
            "如果能复现，写清楚是哪一步出的问题。")
        self.ed_desc.setMinimumHeight(130)
        form.addRow("描述", self.ed_desc)
        # 反馈码要塞进微信/邮件正文，不能让人把整份日志粘过来
        self.lbl_desc_count = QLabel("")
        self.lbl_desc_count.setEnabled(False)
        form.addRow("", self.lbl_desc_count)
        self.ed_desc.textChanged.connect(self._sync_desc_count)
        self._sync_desc_count()

        self.ed_contact = QLineEdit()
        self.ed_contact.setMaxLength(feedback.MAX_CONTACT)
        self.ed_contact.setPlaceholderText("邮箱 / QQ / 微信（选填，方便我回访）")
        st = QSettings("MathViz", "MathViz")
        self.ed_contact.setText(st.value("feedback_contact", "", type=str))
        form.addRow("联系方式", self.ed_contact)

        v.addLayout(form)

        self.chk_attach = QCheckBox("附带环境信息和最近日志")
        self.chk_attach.setChecked(True)
        self.chk_attach.setToolTip(
            "系统版本、Manim / LaTeX 版本、最近 60 行日志。\n"
            "不包含 API Key，路径中的用户名会被替换成「<用户>」。")
        v.addWidget(self.chk_attach)

        if context:
            lbl_ctx = QLabel(f"会自动附上当前状态：{context}")
            lbl_ctx.setWordWrap(True)
            lbl_ctx.setStyleSheet(f"color:{self._p['sub']}; font-size:11px;")
            v.addWidget(lbl_ctx)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(
            f"color:{self._p['accent']}; font-size:12px;")
        self.lbl_status.hide()
        v.addWidget(self.lbl_status)

        # ---- 按钮
        row_btn = QHBoxLayout()
        btn_zip = QPushButton("另存为文件")
        btn_zip.setToolTip("打包成 zip，方便当邮件附件或网盘发送")
        btn_zip.clicked.connect(self._on_save)
        row_btn.addWidget(btn_zip)
        row_btn.addStretch(1)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        row_btn.addWidget(btn_cancel)

        btn_mail = QPushButton("复制并打开邮箱")
        btn_mail.clicked.connect(self._on_mail)
        row_btn.addWidget(btn_mail)

        btn_copy = QPushButton("复制反馈码")
        btn_copy.setDefault(True)
        btn_copy.clicked.connect(self._on_copy)
        row_btn.addWidget(btn_copy)

        v.addLayout(row_btn)

    # ------------------------------------------------------------ 内部
    def _copy_email(self):
        QGuiApplication.clipboard().setText(feedback.AUTHOR_EMAIL)
        self._status(f"邮箱已复制：{feedback.AUTHOR_EMAIL}")

    def _sync_desc_count(self):
        """描述字数：超过上限就变红并说清超出部分不会被发送。"""
        n = len(self.ed_desc.toPlainText())
        limit = feedback.MAX_DESC
        if n > limit:
            self.lbl_desc_count.setText(f"{n} / {limit}（超出部分不会发送）")
            self.lbl_desc_count.setStyleSheet(
                f"color:{self._p['warn_fg']}; font-size:11px;")
        else:
            self.lbl_desc_count.setText(f"{n} / {limit}")
            self.lbl_desc_count.setStyleSheet("font-size:11px;")

    def _status(self, text: str, bad: bool = False):
        color = self._p["warn_fg"] if bad else self._p["accent"]
        self.lbl_status.setStyleSheet(f"color:{color}; font-size:12px;")
        self.lbl_status.setText(text)
        self.lbl_status.show()

    def _validate(self) -> bool:
        if len(self.ed_desc.toPlainText().strip()) < 5:
            QMessageBox.warning(
                self, "还差一点",
                "「描述」太短了，至少写一句发生了什么，否则我很难判断问题。")
            self.ed_desc.setFocus()
            return False
        return True

    def _packet(self, log_lines: int) -> dict:
        return feedback.build_packet(
            kind=self.combo_kind.currentData(),
            title=self.ed_title.text(),
            desc=self.ed_desc.toPlainText(),
            contact=self.ed_contact.text(),
            include_env=self.chk_attach.isChecked(),
            log_lines=log_lines,
            context=self._context,
        )

    def _remember_contact(self):
        QSettings("MathViz", "MathViz").setValue(
            "feedback_contact", self.ed_contact.text().strip())

    def _prepare(self) -> tuple[str, dict, str]:
        """生成反馈码 + 存档 zip。返回 (码, 反馈包, 存档提示)。"""
        self._remember_contact()
        packet = self._packet(feedback.LOG_LINES_IN_CODE)
        code = feedback.encode(packet)
        note = ""
        try:   # zip 带着更长的日志，失败也不影响主流程
            path = feedback.save_zip(self._packet(feedback.LOG_LINES_IN_ZIP))
            note = f"完整日志已存档：{path.name}"
        except Exception as exc:
            note = f"（存档 zip 失败：{exc}）"
        self._last_code = code
        return code, packet, note

    # ------------------------------------------------------------ 动作
    def _on_copy(self):
        if not self._validate():
            return
        try:
            code, _packet, note = self._prepare()
        except Exception as exc:
            self._status(f"生成反馈码失败：{exc}", bad=True)
            return
        QGuiApplication.clipboard().setText(code)
        kb = len(code) / 1024
        self._status(
            f"已复制（{kb:.1f} KB）。粘到微信 / QQ 发给作者即可 ⟶ "
            f"{feedback.AUTHOR_EMAIL}。{note}")

    def _on_mail(self):
        if not self._validate():
            return
        self._remember_contact()
        try:
            # 邮件链接有长度上限，日志行数按需递减，保证码不会被客户端截断
            code, _packet, url, lines = feedback.fit_for_mailto(
                lambda n: self._packet(n))
            note = ""
            try:
                path = feedback.save_zip(self._packet(feedback.LOG_LINES_IN_ZIP))
                note = f"完整日志已存档：{path.name}"
            except Exception as exc:
                note = f"（存档 zip 失败：{exc}）"
        except Exception as exc:
            self._status(f"生成反馈码失败：{exc}", bad=True)
            return

        QGuiApplication.clipboard().setText(code)
        if lines < feedback.LOG_LINES_IN_CODE:
            note = f"日志已精简到 {lines} 行以适配邮件长度；" + note

        ok = QDesktopServices.openUrl(QUrl(url))
        if ok:
            self._status(
                f"已打开邮件，收件人和正文都填好了，直接发送即可。{note}")
        else:
            # 没装邮件客户端时 openUrl 返回 False —— 不弹错误，给下一步
            QMessageBox.information(
                self, "没有找到邮件程序",
                f"系统里没有配置默认邮件客户端。\n\n"
                f"反馈码已经复制到剪贴板，你可以：\n"
                f"· 手动发邮件到 {feedback.AUTHOR_EMAIL}，粘贴进去；\n"
                f"· 或者直接粘到微信 / QQ 发给作者。")

    def _on_save(self):
        if not self._validate():
            return
        self._remember_contact()
        try:
            path = feedback.save_zip(
                self._packet(feedback.LOG_LINES_IN_ZIP))
        except Exception as exc:
            self._status(f"保存失败：{exc}", bad=True)
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("已保存")
        box.setText(f"反馈包已保存：\n{path}")
        btn_open = box.addButton("打开所在文件夹",
                                 QMessageBox.ButtonRole.AcceptRole)
        box.addButton("好", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is btn_open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
