# -*- coding: utf-8 -*-
"""吸色放大镜窗口。

浮在光标旁边的无边框小窗：
* 上半部分是放大到像素级的取样区（最近邻放大，不做插值，避免误导）；
* 中心十字标记当前像素；
* 底部实时显示 HEX / RGB / 位置。

窗口设置 ``WindowTransparentForInput``，不会挡住用户的点击。
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from ..theme import Palette, font

__all__ = ["MagnifierWindow"]


def _to_logical_point(cursor: Tuple[int, int]) -> "QPoint":
    """物理像素 → Qt 逻辑坐标。

    进程声明了 Per-Monitor DPI Awareness 后 ``GetCursorPos`` 返回物理像素，
    而 Qt 的 ``screenAt`` 用逻辑坐标，这里做一次换算。
    """
    app = QApplication.instance()
    ratio = app.devicePixelRatio() if app else 1.0
    return QPoint(int(cursor[0] / (ratio or 1.0)), int(cursor[1] / (ratio or 1.0)))


class MagnifierWindow(QWidget):
    """跟随光标的放大镜。"""

    INFO_HEIGHT = 44
    BORDER = 3

    def __init__(self, grid: int = 15, zoom: int = 12) -> None:
        super().__init__(None)
        self._grid = max(3, int(grid))
        self._zoom = max(2, int(zoom))
        self._image: Optional[QImage] = None
        self._rgb: Tuple[int, int, int] = (0, 0, 0)
        self._cursor: Tuple[int, int] = (0, 0)
        self._hint = "左键取色 · 右键/Esc 取消"

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.Tool | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._apply_size()

    # ------------------------------------------------------------------ 配置
    def configure(self, grid: int, zoom: int) -> None:
        self._grid = max(3, int(grid))
        self._zoom = max(2, int(zoom))
        self._apply_size()

    def set_hint(self, text: str) -> None:
        self._hint = text
        self.update()

    def _apply_size(self) -> None:
        side = self._grid * self._zoom + self.BORDER * 2
        self.setFixedSize(side, side + self.INFO_HEIGHT)

    # ------------------------------------------------------------------ 数据
    def set_sample(self, image, rgb: Sequence[int], cursor: Tuple[int, int]) -> None:
        """``image`` 为 PIL.Image（RGB），尺寸应为 grid×grid。"""
        self._rgb = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        self._cursor = cursor
        try:
            data = image.tobytes("raw", "RGB")
            qimage = QImage(data, image.width, image.height, QImage.Format_RGB888)
            self._image = qimage.copy()  # 必须拷贝，PIL 缓冲区随后即失效
        except Exception:  # pragma: no cover - 极端情况下静默降级
            self._image = None
        self.update()

    # ------------------------------------------------------------------ 定位
    def follow(self, cursor: Tuple[int, int], follow_enabled: bool = True) -> None:
        if not follow_enabled:
            return
        screen = QApplication.screenAt(_to_logical_point(cursor)) or QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.geometry()
        offset = 22
        x = cursor[0] + offset
        y = cursor[1] + offset
        if x + self.width() > geometry.right():
            x = cursor[0] - self.width() - offset
        if y + self.height() > geometry.bottom():
            y = cursor[1] - self.height() - offset
        self.move(max(geometry.left(), x), max(geometry.top(), y))

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        side = self._grid * self._zoom
        canvas = QRect(self.BORDER, self.BORDER, side, side)

        # 背景
        painter.fillRect(self.rect(), QColor(16, 18, 24, 236))

        if self._image is not None and not self._image.isNull():
            painter.drawImage(canvas, self._image)
        else:
            painter.fillRect(canvas, QColor(40, 44, 54))

        # 像素网格
        pen = QPen(QColor(255, 255, 255, 38))
        pen.setWidth(1)
        painter.setPen(pen)
        for index in range(1, self._grid):
            offset = self.BORDER + index * self._zoom
            painter.drawLine(self.BORDER, offset, self.BORDER + side, offset)
            painter.drawLine(offset, self.BORDER, offset, self.BORDER + side)

        # 中心十字 + 高亮框
        center = canvas.center()
        half = self._zoom / 2.0
        painter.setPen(QPen(QColor(0, 0, 0, 220), 3))
        painter.drawRect(center.x() - half, center.y() - half, self._zoom, self._zoom)
        painter.setPen(QPen(QColor(255, 255, 255, 240), 1))
        painter.drawRect(center.x() - half, center.y() - half, self._zoom, self._zoom)
        painter.setPen(QPen(QColor(255, 60, 60, 230), 1))
        painter.drawLine(center.x() - 9, center.y(), center.x() + 9, center.y())
        painter.drawLine(center.x(), center.y() - 9, center.x(), center.y() + 9)

        # 外框
        painter.setPen(QPen(QColor(76, 141, 255, 220), self.BORDER))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

        # 信息区
        info_rect = QRect(0, side + self.BORDER * 2, self.width(), self.INFO_HEIGHT)
        r, g, b = self._rgb
        painter.fillRect(info_rect, QColor(24, 27, 34, 240))
        painter.setPen(QColor(r, g, b))
        painter.setBrush(QColor(r, g, b))
        painter.drawRect(10, info_rect.top() + 14, 16, 16)

        painter.setPen(QColor(Palette.text))
        painter.setFont(font(10, bold=True, mono=True))
        painter.drawText(info_rect.adjusted(34, 6, -8, -22), Qt.AlignLeft | Qt.AlignVCenter,
                         f"#{r:02X}{g:02X}{b:02X}  rgb({r},{g},{b})")

        painter.setPen(QColor(Palette.text_dim))
        painter.setFont(font(8))
        painter.drawText(info_rect.adjusted(10, 22, -8, -4), Qt.AlignLeft | Qt.AlignVCenter,
                         f"{self._cursor[0]},{self._cursor[1]} · {self._hint}")
        painter.end()
