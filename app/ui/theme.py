"""界面主题：浅色 / 深色两套配色 + 界面字号档位。

为什么要单独一个模块：界面里有十几处颜色是**硬编码**在控件自己的
setStyleSheet 里的（列表项、对话气泡、投放区、代码高亮……）。
全局 QSS 管不到这些（它们会覆盖全局），所以主题切换必须两件事一起做：
  1) 给 QApplication 上一份全局 QSS（覆盖大多数标准控件）
  2) 把那十几处硬编码的样式按当前配色重写一遍
这个模块负责给出配色与那些片段，主窗口负责把它们刷到具体控件上。

字号不提供"自由缩放系数"：Qt6 没有全局缩放 API（QT_SCALE_FACTOR 只能在
进程启动前设），能稳定调的只有字体。三档字号足以缓解高分屏上"字太小"，
再往上就该调系统 DPI 了。
"""
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from app.core import config

LIGHT = {
    "name": "light",
    "bg": "#f5f6f8",          # 窗口底色
    "panel": "#ffffff",       # 卡片 / 输入区
    "text": "#23272e",
    "sub": "#5b6270",         # 次要说明文字
    "border": "#d0d4d9",
    "accent": "#2f6feb",
    # Win11 风格的轨迹/滑块配色（滚动条是"细悬浮条"，滑块是从灰白到深灰的 hover）
    "track": "#e5e7eb",
    "track_alt": "#c7cad1",
    "thumb": "#c6c6c6",
    "thumb_hot": "#767676",
    "hover_dot": "#1654d8",    # 滑块圆点 hover/按下时压深一号
    "hover": "#eef1f5",
    "field": "#ffffff",
    "sel_bg": "#dcebff",
    "sel_text": "#14335c",
    "bubble_user": "#dcecff",
    "bubble_bot": "#f0f1f3",
    "formula_bg": "#eef3fa",
    "formula_fg": "#15457f",
    "code_bg": "#ffffff",
    "gutter_bg": "#f0f0f0",
    "gutter_fg": "#999999",
    "drop_border": "#c8ccd4",
    "drop_bg": "#fbfcfd",
    "drop_border_hot": "#4a9eff",
    "drop_bg_hot": "#f2f8ff",
    "warn_bg": "#fdecea",
    "warn_fg": "#b3261e",
    # 代码高亮（浅色沿用原来的配色）
    "kw": "#0033b3", "def": "#6f42c1", "self": "#7a3e9d",
    "const": "#b01700", "num": "#1750eb", "str": "#067d17", "cmt": "#8c8c8c",
}

DARK = {
    "name": "dark",
    "bg": "#1e2126",
    "panel": "#252930",
    "text": "#e6e8ea",
    "sub": "#9aa3ad",
    "border": "#3a4048",
    "accent": "#5b9bff",
    "track": "#33383f",
    "track_alt": "#41474f",
    "thumb": "#4a5058",
    "thumb_hot": "#7a828c",
    "hover_dot": "#86bcff",
    "hover": "#2f353d",
    "field": "#1a1d22",
    "sel_bg": "#2d4a73",
    "sel_text": "#ffffff",
    "bubble_user": "#2d4a73",
    "bubble_bot": "#2b2f36",
    "formula_bg": "#2b2f36",
    "formula_fg": "#9fc7ff",
    "code_bg": "#1a1d22",
    "gutter_bg": "#23262b",
    "gutter_fg": "#6b7280",
    "drop_border": "#3f4650",
    "drop_bg": "#22262c",
    "drop_border_hot": "#5b9bff",
    "drop_bg_hot": "#22303f",
    "warn_bg": "#4a2320",
    "warn_fg": "#ff9d90",
    # 代码高亮（VSCode Dark+ 的取色，在深底上对比最清楚）
    "kw": "#569cd6", "def": "#4ec9b0", "self": "#4fc1ff",
    "const": "#dcdcaa", "num": "#b5cea8", "str": "#ce9178", "cmt": "#6a9955",
}

PALETTES = {"light": LIGHT, "dark": DARK}

# 界面字号三档（pt）。改的是应用默认字体，布局会跟着重新排。
FONT_LEVELS = {"normal": 9, "large": 11, "xlarge": 13}


def palette(name: str) -> dict:
    return PALETTES.get((name or "").strip(), LIGHT)


# ------------------------------------------------------------- 跟随系统主题

SYSTEM = "system"          # 第三种模式：不是一套配色，而是"问他要哪套"


def _windows_prefers_light() -> bool | None:
    """读 Windows 的「设置 → 个性化 → 颜色 → 选择模式」。

    注册表里的 AppsUseLightTheme：1 = 浅色，0 = 深色。
    用 QSettings 读（它在 Windows 上就是访注册表的），不需要子进程。
    读不到（非 Windows / 键不存在 / 权限）返回 None。
    """
    if os.name != "nt":
        return None
    try:
        st = QSettings(
            r"HKEY_CURRENT_USER\Software\Microsoft\Windows"
            r"\CurrentVersion\Themes\Personalize",
            QSettings.Format.NativeFormat)
        raw = st.value("AppsUseLightTheme")
        if raw is None:
            return None
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() not in ("0", "false", "no")
    except Exception:
        return None


def system_prefers_dark() -> bool:
    """系统现在是深色还是浅色。

    三条路依次试，谁先答得出来用谁：
      1) Qt 6.6+ 的 styleHints().colorScheme() —— 跨平台正解（某些平台会答
         Unknown，比如我们的 offscreen 测试环境）
      2) Windows 注册表的 AppsUseLightTheme —— Qt 答 Unknown 时的兜底
      3) 系统默认调色板的窗口底色亮度 —— 最后一招，暗就当深色
    """
    try:
        from PySide6.QtGui import QGuiApplication
        scheme = QGuiApplication.styleHints().colorScheme()
        if str(scheme).endswith("Dark"):
            return True
        if str(scheme).endswith("Light"):
            return False
    except Exception:
        pass
    light = _windows_prefers_light()
    if light is not None:
        return not light
    try:
        from PySide6.QtGui import QGuiApplication, QPalette
        bg = QGuiApplication.palette().color(QPalette.ColorRole.Window)
        return bg.lightness() < 128
    except Exception:
        return False


def resolve(mode: str) -> dict:
    """把用户的选择（light / dark / system）解析成真正要用的那套配色。"""
    m = (mode or "").strip()
    if m == SYSTEM:
        return DARK if system_prefers_dark() else LIGHT
    return PALETTES.get(m, LIGHT)


def app_font(base_family: str, level: str) -> QFont:
    """按档位给出应用字体（保留系统字体族，只改大小）。"""
    f = QFont(base_family)
    f.setPointSize(FONT_LEVELS.get(level, FONT_LEVELS["normal"]))
    return f


# --------------------------------------------------------------- chevron 图形
#
# 为什么必须自己画：
#   · 第一版用 CSS 的 border 三角形技巧画箭头 —— Qt 在 ::down-arrow / ::up-arrow
#     这类没有盒模型的 subcontrol 上不认这套 trick，会把它当作实心矩形填充，
#     于是"箭头"变成小方块。
#   · 退化方案是不写 ::*-arrow 规则、指望原生风格代画 —— Qt 一旦接手了
#     subcontrol 样式就会丢掉原生箭头，什么都不画。
# 所以：用 QPainter 画一条 Win11 那种细线 V 形（两笔 polyline、圆角笔帽），
# 存进 PNG 给 QSS 的 image 引用。颜色随主题，所以每种配色各生成一份。

_ASSETS_DIR_CACHE: dict[str, Path] = {}


def _assets_dir() -> Path:
    """放 UI 图形资源的目录（落到渲染工作目录，天然无空格）。

    每个工作目录只探一次：原来每次应用主题都 touch + unlink 一个探测文件，
    属于白做的 IO；更麻烦的是它会在"批量删除告警"的环境里反复计数 ——
    测试里建几十次窗口就能撞上阈值，把整组用例拦下来。
    """
    base = str(config.default_work_dir())
    if base in _ASSETS_DIR_CACHE:
        return _ASSETS_DIR_CACHE[base]
    d = config.default_work_dir() / "ui_assets"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".probe"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
        _ASSETS_DIR_CACHE[base] = d
    except Exception:
        _ASSETS_DIR_CACHE[base] = Path(tempfile.gettempdir()) / "mathviz_ui_assets"
    return _ASSETS_DIR_CACHE[base]


def _chevron_png(color: str, direction: str, size: int = 16) -> str:
    """生成一条 chevron 箭头，返回可直接塞进 QSS url() 的路径（失败返回空串）。

    画布按「显示尺寸 × 2」画：QSS 里声明的是逻辑像素，图比它大 2 倍，
    在高 DPI 屏上才不会糊；同时笔画粗细也按这个倍率给定，
    缩回去之后正好是一条 Win11 那种约 1.4px 的细线。
    """
    dpr = 2
    try:
        d = _assets_dir()
        name = f"chev_{direction}_{color.lstrip('#')}_{size}@{dpr}x.png"
        path = d / name
        if path.exists():
            return path.as_posix()
        d.mkdir(parents=True, exist_ok=True)
        px = size * dpr
        img = QImage(px, px, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(1.4 * dpr)      # 逻辑 1.4px —— Win11 的 chevron 是细线，不是实心三角
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        s = float(px)
        # 让 V 形撑满这个框（Win11 的 chevron 扁而宽）：左右到 0.20/0.80，上下到 0.34/0.68
        left, right, top, bottom = s * 0.20, s * 0.80, s * 0.34, s * 0.68
        if direction == "down":
            pts = [QPointF(left, top), QPointF(s / 2, bottom), QPointF(right, top)]
        else:
            pts = [QPointF(left, bottom), QPointF(s / 2, top), QPointF(right, bottom)]
        painter.drawPolyline(pts)
        painter.end()
        return path.as_posix() if img.save(str(path), "PNG") else ""
    except Exception:
        return ""


def _arrow_images(p: dict) -> dict:
    """当前配色下的两个箭头图（下拉框 16px，SpinBox 收一号用 14px）。"""
    return {"down": _chevron_png(p["sub"], "down", 12),
            "up": _chevron_png(p["sub"], "up", 12),
            "down_s": _chevron_png(p["sub"], "down", 14),
            "up_s": _chevron_png(p["sub"], "up", 14)}


def _img_rule(rule: str, path: str, size: int) -> str:
    """把一张图挂到某个 subcontrol 上；图生成失败就退化成"不画"。"""
    if not path:
        return ""
    return f"{rule} {{ image: url(\"{path}\"); width: {size}px; height: {size}px; }}"


def app_qss(p: dict) -> str:
    """全局样式表：覆盖标准控件，让它们跟随主题。

    注意这里**不**碰 QWidget 的 background —— 一律染底色会把视频画布、
    进度条这类自定义绘制区域也涂掉。只给真正需要配色的标准控件上色。
    """
    # QWidget 这条必须放在最前面：它是给"没有自己样式的普通面板"兜底上色的，
    # 后面那些更具体的规则（QToolTip / QPushButton / 视频画布自己的黑底……）
    # 靠"后出现者胜"覆盖掉它。
    arrows = _arrow_images(p)
    arrow_down = _img_rule("QComboBox::down-arrow", arrows["down"], 12)
    # SpinBox 框小，箭头也相应收一号
    arrow_up = _img_rule("QSpinBox::up-arrow", arrows["up_s"], 14)
    arrow_down_spin = _img_rule("QSpinBox::down-arrow", arrows["down_s"], 14)
    return f"""
    QWidget {{ background-color: {p['bg']}; color: {p['text']}; }}
    QMainWindow, QDialog, QMenuBar, QMenu {{
        background-color: {p['bg']}; color: {p['text']};
    }}
    QMenu::item:selected {{ background-color: {p['sel_bg']}; color: {p['sel_text']}; }}
    QToolTip {{ background-color: {p['panel']}; color: {p['text']};
               border: 1px solid {p['border']}; }}
    QPushButton, QComboBox, QSpinBox, QLineEdit, QPlainTextEdit, QTextEdit,
    QTextBrowser, QListWidget, QTreeView, QTableView {{
        background-color: {p['field']}; color: {p['text']};
        border: 1px solid {p['border']}; border-radius: 4px;
    }}
    QPushButton {{ padding: 3px 8px; }}
    QPushButton:hover {{ background-color: {p['hover']}; }}
    QPushButton:disabled {{ color: {p['sub']}; }}
    QComboBox QAbstractItemView, QMenu {{
        background-color: {p['panel']}; color: {p['text']};
        selection-background-color: {p['sel_bg']};
        selection-color: {p['sel_text']};
    }}
    QTabWidget::pane {{ border: 1px solid {p['border']}; background-color: {p['bg']}; }}
    QTabBar::tab {{ background-color: {p['bg']}; color: {p['sub']};
                   padding: 4px 10px; }}
    QTabBar::tab:selected {{ background-color: {p['panel']}; color: {p['text']}; }}
    QGroupBox {{ color: {p['text']}; }}
    QProgressBar {{ background-color: {p['field']}; color: {p['text']};
                   border: 1px solid {p['border']}; border-radius: 4px; }}
    QProgressBar::chunk {{ background-color: {p['accent']}; }}
    QLabel {{ color: {p['text']}; }}
    QStatusBar {{ background-color: {p['bg']}; color: {p['sub']}; }}
    QSplitter::handle {{ background-color: {p['border']}; }}

    /* ---- 下拉框：Win11 是细边框 + 一个小小的空心 chevron（不是实心三角） ---- */
    QComboBox::drop-down {{ border: none; width: 20px; background: transparent; }}
    QComboBox::drop-down:hover {{ background: {p['hover']}; }}
    {arrow_down}

    /* ---- SpinBox：显式把上下按钮钉在右侧。
       不写这两条时，Windows 原生样式配上 QSS 边框会让上下按钮
       各占半个框、横跨整个宽度，把数字整个盖住（只见箭头不见数）。---- */
    QSpinBox {{ padding-right: 18px; }}
    QSpinBox::up-button {{
        subcontrol-origin: border; subcontrol-position: top right;
        width: 18px; border: none; background: transparent;
    }}
    QSpinBox::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right;
        width: 18px; border: none; background: transparent;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {p['hover']}; }}
    {arrow_up}
    {arrow_down_spin}

    /* ---- 滚动条：Win11 的悬浮细条 —— 没有箭头、没有沟槽底色，
       滑块靠 margin 收成窄窄一条，悬浮到上面才压深颜色 ---- */
    QScrollBar:vertical {{ background: transparent; width: 14px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {p['thumb']}; border-radius: 3px;
        margin: 2px 4px; min-height: 24px; border: none;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p['thumb_hot']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 14px; margin: 0; }}
    QScrollBar::handle:horizontal {{
        background: {p['thumb']}; border-radius: 3px;
        margin: 4px 2px; min-width: 24px; border: none;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {p['thumb_hot']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; border: none; }}

    /* ---- 滑块（播放器进度条）：Win11 的细圆角轨道 + 已播段主题色，
       手柄用一颗圆点（Win11 原生是竖胶囊，圆点在拖拽定位时更好按） ---- */
    QSlider {{ background: transparent; }}
    QSlider::groove:horizontal {{
        height: 4px; background: {p['track']}; border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{ background: {p['accent']}; border-radius: 2px; }}
    QSlider::add-page:horizontal {{ background: {p['track']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        width: 12px; height: 12px; margin: -4px 0;
        border-radius: 6px; background: {p['accent']};
        border: 2px solid {p['panel']};
    }}
    QSlider::handle:horizontal:hover {{ background: {p['hover_dot']}; }}
    QSlider::handle:horizontal:pressed {{ background: {p['hover_dot']}; }}

    /* ---- 进度条：无边框圆角轨道 + 主题色填充块（还要容得下百分比文字）---- */
    QProgressBar {{
        border: none; background: {p['track']}; color: {p['text']};
        border-radius: 3px; max-height: 14px; text-align: center;
    }}
    QProgressBar::chunk {{ background-color: {p['accent']}; border-radius: 3px; }}
    """


def list_qss(p: dict) -> str:
    """知识点列表 / 历史成果列表的条目样式（硬编码的那两个）。"""
    return (f"QListWidget {{ background:{p['field']}; color:{p['text']};"
            f" border:1px solid {p['border']}; border-radius:6px; }}"
            f"QListWidget::item {{ padding:5px 8px; margin:1px 2px;"
            f" border-radius:6px; color:{p['text']}; }}"
            f"QListWidget::item:hover {{ background:{p['hover']}; }}"
            f"QListWidget::item:selected {{ background:{p['sel_bg']};"
            f" color:{p['sel_text']}; }}")


def chat_view_qss(p: dict) -> str:
    return (f"QTextBrowser {{ background:{p['panel']}; border:1px solid {p['border']};"
            f" border-radius:8px; padding:6px; color:{p['text']}; }}")


def input_frame_qss(p: dict) -> str:
    return (f"QFrame#inputFrame {{ background:{p['panel']};"
            f" border:1px solid {p['border']}; border-radius:10px; }}"
            f"QFrame#inputFrame QPushButton {{ border:1px solid transparent;"
            f" background:transparent; border-radius:4px; }}"
            f"QFrame#inputFrame QPushButton:hover {{ background:{p['hover']}; }}"
            f"QFrame#inputFrame QPushButton:pressed {{ background:{p['sel_bg']}; }}"
            f"QFrame#inputFrame QPushButton:disabled {{ color:{p['sub']}; }}")


def find_bar_qss(p: dict) -> str:
    return (f"QWidget#findBar {{ background:{p['bg']}; border:1px solid {p['border']};"
            f" border-radius:6px; }}")


def drop_qss(p: dict, hot: bool) -> str:
    color = p["drop_border_hot"] if hot else p["drop_border"]
    bg = p["drop_bg_hot"] if hot else p["drop_bg"]
    return (f"QFrame#dropZone {{ border: 2px dashed {color};"
            f" border-radius: 14px; background: {bg}; }}\n"
            f"QFrame#dropZone:disabled {{ border-color:{p['border']};"
            f" background:{p['bg']}; }}")


def bubble_colors(p: dict) -> dict:
    """对话气泡与公式块的颜色（HTML 里写死的那几个）。"""
    return {
        "user": p["bubble_user"],
        "bot": p["bubble_bot"],
        "system": p["sub"],
        "formula_bg": p["formula_bg"],
        "formula_fg": p["formula_fg"],
    }
