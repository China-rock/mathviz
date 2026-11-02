"""反馈台（作者端）：把收到的反馈码整理成一份能干活儿的东西。

同学用微信把反馈码发给你，粘进顶部输入框回车 —— 这条反馈就入库了；
后续可以筛选未处理、翻看日志、导出 CSV 交课程报告。

单独启动（不用打开主界面）：

    MathViz.exe --feedback-inbox        # 打包版
    .venv\\Scripts\\python.exe -m app.main --feedback-inbox   # 源码运行

数据存在 %LOCALAPPDATA%\\MathViz\\feedback\\inbox.jsonl（开发时在项目根）。
"""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSplitter, QTextBrowser,
                               QVBoxLayout)

from app.core import feedback
from app.ui import theme


class FeedbackInbox(QDialog):
    """反馈列表 + 详情。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("反馈台 — MathViz")
        self.resize(980, 640)
        self._p = theme.resolve(
            QSettings("MathViz", "MathViz").value("ui_theme", "light", type=str))
        self._items: list[dict] = []

        v = QVBoxLayout(self)
        v.setSpacing(8)

        # ---- 顶部：粘贴导入
        row_in = QHBoxLayout()
        self.ed_code = QLineEdit()
        self.ed_code.setPlaceholderText(
            "把收到的反馈码粘到这里，按回车导入（一次粘多条也行）")
        self.ed_code.returnPressed.connect(self._on_paste_import)
        row_in.addWidget(self.ed_code, 1)

        btn_import = QPushButton("导入")
        btn_import.clicked.connect(self._on_paste_import)
        row_in.addWidget(btn_import)

        btn_file = QPushButton("从文件…")
        btn_file.setToolTip("支持 .zip 反馈包，或含反馈码的文本文件")
        btn_file.clicked.connect(self._on_import_file)
        row_in.addWidget(btn_file)

        self.combo_filter = QComboBox()
        self.combo_filter.addItem("全部", "all")
        self.combo_filter.addItem("待处理", "new")
        self.combo_filter.addItem("已处理", "done")
        for key, label in feedback.KINDS.items():
            self.combo_filter.addItem(label, key)
        self.combo_filter.currentIndexChanged.connect(self._refresh)
        row_in.addWidget(self.combo_filter)
        v.addLayout(row_in)

        # ---- 主体：左列表 + 右详情
        self.split = QSplitter(Qt.Orientation.Horizontal)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.currentItemChanged.connect(self._on_select)
        self.split.addWidget(self.list)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.split.addWidget(self.view)
        self.split.setSizes([320, 640])
        v.addWidget(self.split, 1)

        # ---- 底部操作
        row_btn = QHBoxLayout()
        self.lbl_stat = QLabel("")
        self.lbl_stat.setStyleSheet(f"color:{self._p['sub']};")
        row_btn.addWidget(self.lbl_stat, 1)

        self.btn_done = QPushButton("标记已处理")
        self.btn_done.clicked.connect(lambda: self._set_status("done"))
        row_btn.addWidget(self.btn_done)

        self.btn_undone = QPushButton("标为待处理")
        self.btn_undone.clicked.connect(lambda: self._set_status("new"))
        row_btn.addWidget(self.btn_undone)

        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._on_delete)
        row_btn.addWidget(btn_del)

        btn_csv = QPushButton("导出 CSV")
        btn_csv.clicked.connect(lambda: self._on_export("csv"))
        row_btn.addWidget(btn_csv)

        btn_md = QPushButton("导出 Markdown")
        btn_md.clicked.connect(lambda: self._on_export("md"))
        row_btn.addWidget(btn_md)

        btn_dir = QPushButton("打开目录")
        btn_dir.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(feedback.open_folder()))))
        row_btn.addWidget(btn_dir)

        v.addLayout(row_btn)

        self._refresh()

    # ------------------------------------------------------------ 数据
    def _refresh(self):
        keep = self._current_id()
        mode = self.combo_filter.currentData()
        items = feedback.load_items()
        if mode == "new":
            items = [it for it in items if it.get("status") != "done"]
        elif mode == "done":
            items = [it for it in items if it.get("status") == "done"]
        elif mode in feedback.KINDS:
            items = [it for it in items
                     if (it.get("packet") or {}).get("kind") == mode]
        self._items = items

        self.list.blockSignals(True)
        self.list.clear()
        restore = None
        for it in items:
            p = it.get("packet") or {}
            mark = "● " if it.get("status") != "done" else "　"
            item = QListWidgetItem(
                f"{mark}{feedback.kind_label(p)} · {p.get('title') or '（无标题）'}")
            item.setData(Qt.ItemDataRole.UserRole, it.get("id"))
            item.setToolTip(f"收到 {it.get('received', '')}\n"
                            f"版本 {p.get('app', '')}")
            if it.get("status") != "done":
                f = item.font()
                f.setBold(True)     # 未读加粗 —— 一眼看出哪些没看
                item.setFont(f)
            self.list.addItem(item)
            if it.get("id") == keep:
                restore = item
        self.list.blockSignals(False)

        total = len(feedback.load_items())
        todo = sum(1 for it in feedback.load_items() if it.get("status") != "done")
        self.lbl_stat.setText(f"共 {total} 条，待处理 {todo} 条"
                              f"（当前列表 {len(items)} 条）")
        if restore is not None:
            self.list.setCurrentItem(restore)
        elif items:
            self.list.setCurrentRow(0)
        else:
            self.view.setHtml(self._empty_html())

    def _current_id(self) -> str | None:
        it = self.list.currentItem() if hasattr(self, "list") else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _current(self) -> dict | None:
        fid = self._current_id()
        return next((it for it in self._items if it.get("id") == fid), None)

    # ------------------------------------------------------------ 渲染
    def _empty_html(self) -> str:
        p = self._p
        return (f"<div style='color:{p['sub']}; padding:24px; font-size:13px;'>"
                "还没有反馈。<br><br>"
                "把同学发来的反馈码粘到上面的输入框，按回车就会出现在左边。<br>"
                "邮件附件里的 feedback-*.zip 也可以直接「从文件…」导入。</div>")

    def _detail_html(self, it: dict) -> str:
        p = self._p
        pkt = it.get("packet") or {}
        esc = html.escape
        status = "已处理" if it.get("status") == "done" else "待处理"
        head = (f"<div style='font-size:15px; font-weight:600;'>"
                f"{esc(pkt.get('title') or '（无标题）')}</div>"
                f"<div style='color:{p['sub']}; font-size:12px; margin-top:2px;'>"
                f"{esc(feedback.kind_label(pkt))} · {esc(pkt.get('ts', ''))}"
                f" · 收到 {esc(it.get('received', ''))} · {status}</div>")

        contact = pkt.get("contact") or "（未填）"
        meta = (f"<p style='font-size:13px;'>联系方式：<b>{esc(contact)}</b><br>"
                f"版本：{esc(str(pkt.get('app', '')))}</p>")

        desc = (f"<h3 style='font-size:13px; margin-bottom:4px;'>描述</h3>"
                f"<div style='font-size:13px; white-space:pre-wrap;'>"
                f"{esc(pkt.get('desc', ''))}</div>")

        ctx = ""
        if pkt.get("context"):
            ctx = (f"<h3 style='font-size:13px; margin-bottom:4px;'>现场</h3>"
                   f"<div style='font-size:12px; color:{p['sub']};'>"
                   f"{esc(pkt['context'])}</div>")

        env_rows = "".join(
            f"<tr><td style='color:{p['sub']}; padding:2px 12px 2px 0; "
            f"white-space:nowrap;'>{esc(k)}</td><td>{esc(v)}</td></tr>"
            for k, v in (pkt.get("env") or {}).items())
        env = ""
        if env_rows:
            env = (f"<h3 style='font-size:13px; margin-bottom:4px;'>环境</h3>"
                   f"<table style='font-size:12px;'>{env_rows}</table>")

        logs = ""
        for key, title in (("console", "运行日志（尾部）"), ("crash", "崩溃日志")):
            text = (pkt.get("logs") or {}).get(key) or ""
            if not text:
                continue
            logs += (f"<h3 style='font-size:13px; margin-bottom:4px;'>{title}</h3>"
                     f"<pre style='font-size:11px; line-height:1.45; "
                     f"background:{p['code_bg']}; border:1px solid {p['border']}; "
                     f"padding:8px; white-space:pre-wrap;'>{esc(text)}</pre>")

        return (f"<div style='font-family:sans-serif;'>{head}{meta}"
                f"{desc}{ctx}{env}{logs}</div>")

    def _on_select(self, cur, _prev=None):
        if cur is None:
            self.view.setHtml(self._empty_html())
            return
        fid = cur.data(Qt.ItemDataRole.UserRole)
        it = next((x for x in self._items if x.get("id") == fid), None)
        if it:
            self.view.setHtml(self._detail_html(it))

    # ------------------------------------------------------------ 导入
    def _report(self, added: int, dup: int, bad: list[str]):
        if added:
            self._refresh()
            self.ed_code.clear()
        msg = f"导入 {added} 条"
        if dup:
            msg += f"，{dup} 条已存在（跳过）"
        if bad:
            msg += f"，{len(bad)} 条无法识别"
        self.lbl_stat.setText(msg)

    def _on_paste_import(self):
        text = self.ed_code.text().strip()
        if not text:
            return
        codes = feedback.find_codes(text)
        if not codes:
            QMessageBox.warning(self, "没认出反馈码",
                                "这段文字里没有反馈码。\n"
                                "反馈码以 MXF1- 开头，是同学点「复制反馈码」得到的那段。")
            return
        added = dup = 0
        bad: list[str] = []
        for c in codes:
            try:
                _, is_new = feedback.add_code(c)
                added += 1 if is_new else 0
                dup += 0 if is_new else 1
            except Exception:
                bad.append(c)
        self._report(added, dup, bad)

    def _on_import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择反馈文件", str(feedback.open_folder()),
            "反馈文件 (*.zip *.txt *.md);;所有文件 (*.*)")
        if not path:
            return
        p = Path(path)
        try:
            if p.suffix.lower() == ".zip":
                _, is_new = feedback.add_zip(p)
                self._report(1 if is_new else 0, 0 if is_new else 1, [])
            else:
                self.ed_code.setText(p.read_text(encoding="utf-8", errors="ignore"))
                self._on_paste_import()
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", f"{p.name}：{exc}")

    # ------------------------------------------------------------ 操作
    def _set_status(self, status: str):
        it = self._current()
        if not it:
            return
        feedback.set_status(it["id"], status)
        self._refresh()

    def _on_delete(self):
        it = self._current()
        if not it:
            return
        title = (it.get("packet") or {}).get("title") or "（无标题）"
        r = QMessageBox.question(
            self, "删除这条反馈",
            f"确定删除「{title}」吗？\n删除后无法恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            feedback.delete_item(it["id"])
            self._refresh()

    def _on_export(self, kind: str):
        if not self._items:
            QMessageBox.information(self, "没有可导出的内容", "当前列表是空的。")
            return
        default = f"mathviz-feedback-{kind}.{kind}"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出", str(feedback.open_folder() / default),
            "CSV (*.csv)" if kind == "csv" else "Markdown (*.md)")
        if not path:
            return
        try:
            out = (feedback.export_csv(Path(path), self._items) if kind == "csv"
                   else feedback.export_markdown(Path(path), self._items))
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"已导出 {len(self._items)} 条：\n{out}")
