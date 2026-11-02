"""「选项」设置对话框。

为什么是弹窗而不是继续塞菜单：选项会越来越多（确认弹窗、自动播放器模式、
缓存……），菜单里勾选一眼看不到全貌，弹窗一页摆开，改完点确定即可。
读写统一走 QSettings("MathViz", "MathViz")，键值与主窗口约定见各类目注释。
"""
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from app.core import cache, config
from app.ui.first_run import ApiKeyDialog


class SettingsDialog(QDialog):
    """设置窗口。主窗口在 exec() 返回后读取各项并生效。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选项")
        self.setMinimumWidth(460)

        v = QVBoxLayout(self)
        v.setSpacing(10)

        # ---- DeepSeek Key：打包版没有 .env 可手改，必须能在界面里配
        g_key = QGroupBox("DeepSeek Key")
        kv = QHBoxLayout(g_key)
        self.lbl_key = QLabel()
        self.lbl_key.setWordWrap(True)
        kv.addWidget(self.lbl_key, 1)
        btn_key = QPushButton("更改…")
        btn_key.clicked.connect(self._change_key)
        kv.addWidget(btn_key)
        v.addWidget(g_key)

        # ---- 外观：主题 + 字号（改完全局立即生效，不用重启）
        g_look = QGroupBox("外观")
        form = QFormLayout(g_look)
        self.combo_theme = QComboBox()
        self.combo_theme.addItem("跟随系统", "system")
        self.combo_theme.addItem("浅色", "light")
        self.combo_theme.addItem("深色", "dark")
        self.combo_theme.setToolTip(
            "界面配色（只影响软件界面，不影响成片 —— 成片底色是脚本决定的，\n"
            "想改白底请在脚本开头加 config.background_color = WHITE）。\n"
            "· 跟随系统：读 Windows 的「颜色 → 选择模式」，跟着它深浅切换；\n"
            "  开着软件改系统配色，这边会立刻跟上，不用重启。\n"
            "· 浅色 / 深色：不管系统怎么设，锁死在这一套。")
        form.addRow("主题：", self.combo_theme)
        self.combo_font = QComboBox()
        self.combo_font.addItem("标准", "normal")
        self.combo_font.addItem("大", "large")
        self.combo_font.addItem("特大", "xlarge")
        self.combo_font.setToolTip(
            "界面字号。高分屏上字太小可以调大 —— Qt 没有全局缩放开关，\n"
            "能稳定调的只有字体大小（图标按钮的固定尺寸不会跟着变）。")
        form.addRow("界面字号：", self.combo_font)
        v.addWidget(g_look)

        # ---- 界面行为
        g_ui = QGroupBox("界面行为")
        uv = QVBoxLayout(g_ui)
        self.chk_clear_confirm = QCheckBox("清空工作区前弹出确认窗口")
        self.chk_clear_confirm.setToolTip(
            "关掉后点「清空」会立即重置工作区，不再二次确认。\n"
            "成片在 media/ 里不受影响，但脚本与对话找不回来——请谨慎。")
        uv.addWidget(self.chk_clear_confirm)
        self.chk_auto_player = QCheckBox("渲染成功后自动进入播放器模式")
        self.chk_auto_player.setToolTip(
            "关掉后渲染完成仍停留在工作台，想看片再手动切换\n"
            "（视频右上角的 ⤢ 按钮 / 双击画面 / 查看菜单都可以）。")
        uv.addWidget(self.chk_auto_player)
        v.addWidget(g_ui)

        # ---- 缓存
        g_cache = QGroupBox("生成缓存")
        cv = QVBoxLayout(g_cache)
        self.chk_cache = QCheckBox("启用生成缓存（命中即跳过 AI，双击历史成果直接复用）")
        cv.addWidget(self.chk_cache)
        row = QHBoxLayout()
        btn_stats = QPushButton("缓存统计…")
        btn_stats.clicked.connect(lambda: self.parent()._show_cache_stats())
        btn_clear = QPushButton("清除全部缓存…")
        btn_clear.clicked.connect(lambda: self.parent()._clear_cache())
        row.addWidget(btn_stats)
        row.addWidget(btn_clear)
        row.addStretch(1)
        cv.addLayout(row)
        v.addWidget(g_cache)

        # ---- 快捷入口
        g_dirs = QGroupBox("位置")
        dv = QVBoxLayout(g_dirs)
        row2 = QHBoxLayout()
        btn_logs = QPushButton("打开日志文件夹")
        btn_logs.clicked.connect(
            lambda: self.parent()._open_dir(config.DATA_DIR / "logs"))
        btn_media = QPushButton("打开成片文件夹")
        btn_media.clicked.connect(
            lambda: self.parent()._open_dir(config.OUTPUT_MEDIA_DIR))
        row2.addWidget(btn_logs)
        row2.addWidget(btn_media)
        row2.addStretch(1)
        dv.addLayout(row2)
        v.addWidget(g_dirs)

        v.addWidget(QLabel("设置在点击「确定」后生效。"))

        row_ok = QHBoxLayout()
        row_ok.addStretch(1)
        btn_ok = QPushButton("确定")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        row_ok.addWidget(btn_ok)
        row_ok.addWidget(btn_cancel)
        v.addLayout(row_ok)

    def _refresh_key_label(self):
        if config.get_api_key():
            self.lbl_key.setText(f"已配置（来源：{config.api_key_source()}）")
        else:
            self.lbl_key.setText("未配置 —— 生成与对话都用不了，点「更改…」填入")

    def _change_key(self):
        dlg = ApiKeyDialog(self, first_run=False)
        if dlg.exec():
            self._refresh_key_label()
            win = self.parent()
            if hasattr(win, "_refresh_key_status"):
                win._refresh_key_status()

    def load(self):
        """从 QSettings 读当前值（主窗口打开对话框时调用）。"""
        self._refresh_key_label()
        st = QSettings("MathViz", "MathViz")
        self.chk_clear_confirm.setChecked(
            st.value("clear_confirm", True, type=bool))
        self.chk_auto_player.setChecked(
            st.value("auto_player_mode", True, type=bool))
        self.chk_cache.setChecked(cache.is_enabled())
        ti = self.combo_theme.findData(st.value("ui_theme", "light", type=str))
        self.combo_theme.setCurrentIndex(ti if ti >= 0 else 0)
        fi = self.combo_font.findData(st.value("ui_font", "normal", type=str))
        self.combo_font.setCurrentIndex(fi if fi >= 0 else 0)

    def apply(self):
        """写回 QSettings 并触发主窗口的联动（缓存开关要刷列表标记）。"""
        st = QSettings("MathViz", "MathViz")
        st.setValue("clear_confirm", self.chk_clear_confirm.isChecked())
        st.setValue("auto_player_mode", self.chk_auto_player.isChecked())
        win = self.parent()
        if getattr(win, "act_cache", None) is not None:
            win._toggle_cache(self.chk_cache.isChecked())   # 内部会刷标记与历史
        # 主题与字号：主窗口负责刷新全局 QSS 与那几处硬编码样式
        if hasattr(win, "_apply_theme"):
            win._apply_theme(self.combo_theme.currentData(),
                             self.combo_font.currentData())
