"""视频画布：用 QGraphicsVideoItem 播画面，而不是 QVideoWidget。

为什么不用 QVideoWidget
-----------------------
QVideoWidget 在 Windows 上承载着一层原生渲染表面。它带来的后果是：

  · 任何叠在它上面（或它旁边同父级）的普通控件都画不出来
    —— Qt 自己认为 visible()，屏幕上却一个像素都没有
  · 连 tooltip 也会被拖累：提示框整体变黑条、文字消失

本项目预览区右上角的 ⤢（进播放器模式）按钮就栽在这上面：
    "Qt 认为按钮可见" 与 "屏幕上真的看得见" 是两回事。
（用「显示/隐藏同一区域屏幕截图」做像素差分，差异率 0.0% —— 实锤。）

QGraphicsVideoItem 的做法
------------------------
视频只是 QGraphicsScene 里的一个item，画在 QGraphicsView 的 viewport 上，
和别的 Qt 控件走同一套绘制顺序 —— 叠加控件、tooltip 全部恢复正常。
对外仍然是一个普通 QWidget（`VideoCanvas`），主窗口按 QWidget 用即可。
"""

from PySide6.QtCore import QSizeF, QTimer, Qt
from PySide6.QtGui import QPainter
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (QFrame, QGraphicsScene, QGraphicsView,
                               QSizePolicy, QVBoxLayout, QWidget)


class VideoCanvas(QWidget):
    """视频画面容器。用法：player.setVideoOutput(canvas.video_item())。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background:#000;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.scene = QGraphicsScene(self)
        self.item = QGraphicsVideoItem()
        # 与原 QVideoWidget 一致：保持画面原始比例，多余的边留黑
        self.item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.scene.addItem(self.item)

        self.view = QGraphicsView(self.scene)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setContentsMargins(0, 0, 0, 0)
        self.view.setViewportMargins(0, 0, 0, 0)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setStyleSheet("background:#000;border:0;")
        lay.addWidget(self.view)

        self._sync_scene()

    def video_item(self) -> QGraphicsVideoItem:
        """交给 QMediaPlayer.setVideoOutput() 的对象。"""
        return self.item

    def paintEvent(self, event):
        # 保持纯黑底，避免画布未铺满时露出窗口底色闪烁
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)

    def showEvent(self, event):
        super().showEvent(event)
        # 从全屏退回（reparent + 插回布局）时，resizeEvent 触发的那一刻
        # 子控件 QGraphicsView 可能还带着全屏的旧尺寸 —— 立即同步会拿到
        # 过期的 viewport 大小，且之后不再有 resize 事件来纠正，画面就被
        # "放大裁切"。所以每次 show 后再补一次下一轮事件循环的对齐。
        QTimer.singleShot(0, self._sync_scene)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_scene()
        # 同理：此刻 view 还没被布局挪到位，等这一轮布局结束后再对齐一次
        QTimer.singleShot(0, self._sync_scene)

    def _sync_scene(self):
        """场景矩形跟齐视口，视频 item 铺满整个画布（比例由 item 自己维持）。"""
        w = max(0, self.view.viewport().width())
        h = max(0, self.view.viewport().height())
        self.scene.setSceneRect(0, 0, w, h)
        self.item.setPos(0, 0)
        self.item.setSize(QSizeF(w, h))
