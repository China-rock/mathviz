"""界面图标：全部用 SVG 自绘，不依赖系统字体。

为什么不用字符（⤢ 之类）
-----------------------
同一个字符在不同字体下的形状差异极大：有的系统把它画成四条外扩箭头，
有的缺字，有的字号一大就歪。而这是按钮上唯一的内容 —— 它一歪，整个按钮就废了。
自绘 SVG 的形状、粗细、颜色完全可控，任何机器上长得都一样。
"""

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton

DOT = 24   # 图标的设计画布：24x24


DASH = "fill=\"none\" stroke-linecap=\"round\" stroke-linejoin=\"round\""


def _svg(color: str, stroke: float = 2.2) -> bytes:
    """一条斜双向箭头（⤡）：一端指向左上，一端指向右下。

    两端都用「开放 L 形」箭头尖（沿两条边倒回来）而不是闭合三角 ——
    实心三角在 18px 这么小的尺寸下会糊成一坨。
    """
    shaft = "M 8.5 8.5 L 15.5 15.5"          # 中间的对角杆
    head_nw = "M 12.5 5 L 5 5 L 5 12.5"      # 左上端：尖朝左上
    head_se = "M 11.5 19 L 19 19 L 19 11.5"  # 右下端：尖朝右下
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {DOT} {DOT}">'
            f'<path d="{shaft}" {DASH} stroke="{color}" stroke-width="{stroke}"/>'
            f'<path d="{head_nw}" {DASH} stroke="{color}" stroke-width="{stroke}"/>'
            f'<path d="{head_se}" {DASH} stroke="{color}" stroke-width="{stroke}"/>'
            f'</svg>').encode()


def expand_icon(color: str = "#9aa0a6", px: int = 18) -> QIcon:
    """生成一个双向对角箭头图标（左上 ⟷ 右下）。

    color: 灰色默认值在黑色视频画面上对比适中、不刺眼；
           悬停时会换成更亮的色再调一次。
    """
    r = QSvgRenderer(QByteArray(_svg(color)))
    size = QSize(px, px)
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    r.render(p)
    p.end()
    return QIcon(pm)


class HoverIconButton(QPushButton):
    """图标按钮：常态灰色（低调隐身），悬停变亮。

    为什么不在 stylesheet 里写 :hover 换色 —— QSS 管不着 QIcon 的颜色，
    只能在 enter/leave 事件里重新生成图标。
    """

    def __init__(self, build_icon, idle: str = "#9aa0a6",
                 active: str = "#ffffff", parent=None):
        super().__init__(parent)
        self._build = build_icon
        self._idle, self._active = idle, active
        self.setIcon(build_icon(idle))

    def enterEvent(self, event):
        self.setIcon(self._build(self._active))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setIcon(self._build(self._idle))
        super().leaveEvent(event)
