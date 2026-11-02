"""批量生成/渲染对话框：勾选知识点，选质量，然后交给 BatchWorker 串行排队。

为什么是"串行"而不是并行：一支片子要占一份 manim 子进程 + 一份 LaTeX 编译，
并行只会让几支一起卡在同一个 CPU 上，还让日志变成一锅粥。串行的用户体验是
"一支接一支地出片"，看得见进度，也随时能停。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QRadioButton,
                               QVBoxLayout)


class BatchDialog(QDialog):
    def __init__(self, points: list[dict], parent=None, default_quality: str = "low"):
        super().__init__(parent)
        self.setWindowTitle("批量生成与渲染")
        self.resize(620, 480)

        v = QVBoxLayout(self)
        tip = QLabel(
            "勾选要排队处理的知识点。每一支依次执行：\n"
            "生成脚本 → 静态检查（不过则自动修复一次）→ 渲染 → 成片体检。\n"
            "串行执行、全程可停（当前这一支渲完才停），失败的不会拖累后面的。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#5b6270;")
        v.addWidget(tip)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for kp in points:
            desc = (kp.get("description") or "").strip()
            label = kp.get("title") or "未命名"
            if desc:
                label += f"　—　{desc[:46]}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, kp)
            self.list.addItem(item)
        v.addWidget(self.list, 1)

        row = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        btn_none = QPushButton("全不选")
        btn_none.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        row.addWidget(btn_all)
        row.addWidget(btn_none)
        row.addSpacing(12)
        row.addWidget(QLabel("画质："))
        self.rb_low = QRadioButton("480p 预览（快）")
        self.rb_medium = QRadioButton("720p（折中）")
        self.rb_high = QRadioButton("1080p 高清（慢）")
        checked = {"high": self.rb_high, "medium": self.rb_medium}.get(
            default_quality, self.rb_low)
        checked.setChecked(True)
        row.addWidget(self.rb_low)
        row.addWidget(self.rb_medium)
        row.addWidget(self.rb_high)
        row.addStretch(1)
        v.addLayout(row)

        self.lbl_count = QLabel()
        self.lbl_count.setStyleSheet("color:#3b4250; font-weight:600;")
        v.addWidget(self.lbl_count)

        self.list.itemChanged.connect(self._update_count)
        for rb in (self.rb_low, self.rb_medium, self.rb_high):
            rb.toggled.connect(self._update_count)
        self._update_count()

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("开始排队")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    # ---------------------------------------------------------------- 内部

    def _set_all(self, state):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)

    def _update_count(self, *_) -> None:
        n = len(self.selection()[0])
        # 单支的粗略耗时（秒）：480p 几十秒，1080p 通常 1~4 分钟
        per = 70 if self.rb_high.isChecked() else (55 if self.rb_medium.isChecked() else 45)
        total = n * per
        if total >= 60:
            cost = f"约 {total // 60} 分 {total % 60} 秒"
        else:
            cost = f"约 {total} 秒"
        note = {"high": "（1080p 每支通常 1~4 分钟，取决于动画复杂度）",
                "medium": "（720p 折中，交作业、插课件都够）",
                "low": "（480p 每支通常几十秒）"}[self.selection()[1]]
        self.lbl_count.setText(f"已选 {n} 个知识点 · 粗估 {cost} {note}")

    # ---------------------------------------------------------------- 结果

    def selection(self) -> tuple[list[int], str]:
        """返回 (被勾选的下标列表, "low"/"medium"/"high")。"""
        idxs = [i for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]
        q = "high" if self.rb_high.isChecked() else (
            "medium" if self.rb_medium.isChecked() else "low")
        return idxs, q
