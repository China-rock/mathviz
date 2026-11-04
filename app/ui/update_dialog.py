"""「检查更新」对话框：查 → 看说明 → 下载 → 交给安装包接管。

界面只做三件事，其余（版本比较、下载、起安装包）都在 app/core/updater.py，
这样无窗口环境下也能测。
"""
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QTextBrowser,
                               QVBoxLayout)

from app.core import config, updater


class CheckWorker(QThread):
    """拉一次 latest release。失败也走信号，不在这儿弹窗。"""

    done = Signal(object)
    fail = Signal(str)

    def run(self):
        try:
            self.done.emit(updater.fetch_latest())
        except Exception as e:
            self.fail.emit(str(e))


class DownloadWorker(QThread):
    """流式下载安装包，带进度与取消。"""

    progress = Signal(int, int)
    done = Signal(str)
    fail = Signal(str)

    def __init__(self, url: str, dest, parent=None):
        super().__init__(parent)
        self.url = url
        self.dest = dest
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.done.emit(str(updater.download(
                self.url, self.dest,
                progress=lambda got, total: self.progress.emit(got, total),
                cancelled=lambda: self._cancel)))
        except updater.UpdateCancelled:
            self.fail.emit("已取消下载")
        except Exception as e:
            self.fail.emit(str(e))


class UpdateDialog(QDialog):
    """有新版本时的信息 + 下载窗口。

    用户点了「立即更新」并下载成功后，`setup_path` 里是安装包路径，
    exec() 返回 Accepted —— 由主窗口负责退出程序、起安装包。
    """

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self.setup_path = ""
        self._dl = None
        self._cancelled = False

        latest = info.get("version", "")
        self.setWindowTitle(f"发现新版本 {latest}")
        self.setMinimumWidth(560)

        v = QVBoxLayout(self)
        v.setSpacing(10)

        title = QLabel(f"<b style='font-size:15px'>MathViz {latest}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(title)

        bits = [f"当前版本 {config.APP_VERSION}"]
        if info.get("published"):
            bits.append(f"发布于 {info['published']}")
        inst = info.get("installer")
        if inst and inst.get("size"):
            bits.append(updater.human_size(inst["size"]))
        sub = QLabel("　·　".join(bits))
        sub.setStyleSheet("color: gray;")
        v.addWidget(sub)

        notes = QTextBrowser()
        notes.setMinimumHeight(220)
        notes.setOpenExternalLinks(True)
        body = info.get("notes") or "（这次发布没有写说明）"
        try:
            notes.setMarkdown(body)          # Qt 5.14+：能看清粗体/列表
        except Exception:
            notes.setPlainText(body)
        v.addWidget(notes, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        v.addWidget(self.lbl_status)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        v.addWidget(self.bar)

        row = QHBoxLayout()
        self.btn_page = QPushButton("打开发布页")
        self.btn_page.setToolTip("在浏览器里看完整说明 / 手动下载")
        self.btn_page.clicked.connect(self._open_page)
        row.addWidget(self.btn_page)
        row.addStretch(1)

        self.box = QDialogButtonBox()
        # 「稍后」用 ActionRole 而不是 RejectRole：下载中它要变成「取消」，
        # 若挂着 RejectRole，按钮框会自己 emit rejected 把窗口关掉、下载成孤儿。
        self.btn_later = self.box.addButton("稍后", QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_go = self.box.addButton("⬇ 立即更新",
                                         QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_go.setDefault(True)
        self.btn_later.clicked.connect(self._on_later)
        self.btn_go.clicked.connect(self._start_download)
        row.addWidget(self.box)
        v.addLayout(row)

        if not inst or not inst.get("url"):
            # 这次 release 没传 exe（或者只发了源码包）
            self.btn_go.setEnabled(False)
            self.lbl_status.setText("这次发布没有附带安装包，请点「打开发布页」手动下载。")
        elif not updater.can_self_update():
            self.btn_go.setEnabled(False)
            self.lbl_status.setText(
                "当前是源码运行，不能在程序里直接升级 —— 请打开发布页下载安装包。")

    # ---------- 动作

    def _open_page(self):
        QDesktopServices.openUrl(QUrl(self.info.get("page") or updater.RELEASE_PAGE))

    def _start_download(self):
        inst = self.info.get("installer") or {}
        url = inst.get("url")
        if not url:
            return
        name = inst.get("name") or f"MathViz-{self.info.get('version', '')}-Setup.exe"
        dest = updater.download_dir() / name

        self.btn_go.setEnabled(False)
        self.btn_later.setText("取消")
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.lbl_status.setText("正在下载…")

        self._dl = DownloadWorker(url, dest, self)
        self._dl.progress.connect(self._on_progress)
        self._dl.done.connect(self._on_done)
        self._dl.fail.connect(self._on_fail)
        self._dl.finished.connect(self._dl.deleteLater)
        self._dl.start()

    def _on_later(self):
        """一个按钮两种身份：下载中 = 取消，否则 = 稍后再说。"""
        if self._dl is not None and self._dl.isRunning():
            self._cancelled = True
            self._dl.cancel()
            self.lbl_status.setText("正在取消…")
            self.btn_later.setEnabled(False)
            return
        self.reject()

    def _on_progress(self, got: int, total: int):
        if total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(min(100, int(got * 100 / total)))
            self.lbl_status.setText(
                f"正在下载… {updater.human_size(got)} / {updater.human_size(total)}")
        else:
            self.bar.setRange(0, 0)          # 服务器没给 Content-Length
            self.lbl_status.setText(f"正在下载… {updater.human_size(got)}")

    def _on_done(self, path: str):
        self.setup_path = path
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.lbl_status.setText("下载完成，即将关闭主程序并启动安装。")
        self.accept()

    def _on_fail(self, msg: str):
        self.bar.setVisible(False)
        self.lbl_status.setText(msg)
        self.btn_go.setEnabled(True)
        self.btn_later.setText("稍后")
        self.btn_later.setEnabled(True)
        if self._cancelled:
            self._cancelled = False
            self.lbl_status.setText("已取消下载。")

    # ---------- 关窗时别留孤儿线程

    def closeEvent(self, event):
        if self._dl is not None and self._dl.isRunning():
            self._dl.cancel()
            self._dl.wait(3000)
        super().closeEvent(event)
