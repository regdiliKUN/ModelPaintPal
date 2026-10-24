# -*- coding: utf-8 -*-
"""HSV 色盘。

把目标色与各候选色号画在同一个色相环上：半径表示饱和度，角度表示色相。
一眼就能看出「候选色偏了哪个方向」。

三个体验要点（都是"看图才发现"的问题）：
* **重叠消解**：几个相近色号的点会完全叠在一起，看起来只有一个点。这里按
  "与已放置点的最小间距"逐个把重叠点沿半径向外推开，并画一条细引线指回真实位置；
* **编号标注**：点上直接画 ①②③，与色卡、图例使用同一套编号，不用靠颜色猜；
* **目标十字**：目标色额外画十字准星，和候选色一眼区分开。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...core.color_models import normalize_rgb, rgb_to_hsv
from ..paint import painter_on
from ..theme import font
from .swatch_card import index_badge

__all__ = ["WheelMarker", "ColorWheel", "ColorWheelCard"]

_WHEEL_MARGIN = 14
_MIN_GAP = 17.0        # 两个标记点的最小间距（像素）


@dataclass
class WheelMarker:
    rgb: Sequence[float]
    label: str = ""
    emphasis: bool = False   # True = 目标色，画更大的环 + 十字
    index: int = 0           # 与色卡编号一致


class ColorWheel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._markers: List[WheelMarker] = []
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_markers(self, markers: Sequence[WheelMarker]) -> None:
        self._markers = list(markers)
        self.update()

    def clear(self) -> None:
        self._markers = []
        self.update()

    # ------------------------------------------------------------------ 布局
    def _geometry(self) -> Tuple[QPointF, float, QRect]:
        rect = self.rect().adjusted(_WHEEL_MARGIN, _WHEEL_MARGIN, -_WHEEL_MARGIN, -_WHEEL_MARGIN)
        side = max(40, min(rect.width(), rect.height()))
        radius = side / 2.0
        center = QPointF(rect.center().x(), rect.center().y())
        square = QRect(int(center.x() - radius), int(center.y() - radius), int(side), int(side))
        return center, radius, square

    @staticmethod
    def _raw_point(center: QPointF, radius: float, rgb) -> QPointF:
        hue, saturation, _value = rgb_to_hsv(rgb)
        angle = math.radians(hue)
        distance = (saturation / 100.0) * radius
        return QPointF(center.x() + math.cos(angle) * distance,
                       center.y() - math.sin(angle) * distance)

    def _resolve_overlaps(self, points: List[QPointF], center: QPointF) -> List[QPointF]:
        """把彼此太近的点推开，保证每个点都能被看见。

        只沿半径方向推是不够的：色相接近的两个色号在盘上几乎同角，沿各自半径
        往外推之后仍然彼此挨着。这里改成"以原位置为圆心，按环逐圈找空位"，
        并且**优先沿半径向外**（这样点的位置仍然对应它的饱和度方向），
        找不到才左右偏转。
        """
        placed: List[QPointF] = []
        for point in points:
            if self._is_free(point, placed):
                placed.append(QPointF(point))
                continue
            dx = point.x() - center.x()
            dy = point.y() - center.y()
            base_angle = math.atan2(dy, dx) if math.hypot(dx, dy) > 1e-6 else -math.pi / 2
            chosen = QPointF(point)
            found = False
            for ring in range(1, 7):
                radius = ring * (_MIN_GAP * 0.75)
                for delta in (0, 30, -30, 60, -60, 90, -90, 120, -120, 150, -150, 180):
                    angle = base_angle + math.radians(delta)
                    candidate = QPointF(point.x() + math.cos(angle) * radius,
                                        point.y() + math.sin(angle) * radius)
                    if self._is_free(candidate, placed):
                        chosen = candidate
                        found = True
                        break
                if found:
                    break
            placed.append(chosen)
        return placed

    @staticmethod
    def _is_free(candidate: QPointF, placed: List[QPointF]) -> bool:
        for other in placed:
            if math.hypot(candidate.x() - other.x(), candidate.y() - other.y()) < _MIN_GAP:
                return False
        return True

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        with painter_on(self) as painter:
            self._paint(painter)

    def _paint(self, painter: QPainter) -> None:
        center, radius, square = self._geometry()
        self._paint_wheel(painter, center, radius, square)
        if self._markers:
            self._paint_markers(painter, center, radius)

    @staticmethod
    def _paint_wheel(painter: QPainter, center: QPointF, radius: float,
                     square: QRect) -> None:
        # 色相环：用扇形逐度填充，避免依赖外部图片资源
        steps = 120
        for index in range(steps):
            hue = index * 360.0 / steps
            color = QColor()
            color.setHsvF(hue / 360.0, 1.0, 1.0)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawPie(square, int(-hue * 16), int(-(360.0 / steps + 1.1) * 16))

        # 中心渐变为白（饱和度 0），形成标准 HSV 盘
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, QColor(255, 255, 255))
        gradient.setColorAt(0.55, QColor(255, 255, 255, 130))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, radius, radius)

    def _paint_markers(self, painter: QPainter, center: QPointF, radius: float) -> None:
        raw = [self._raw_point(center, radius, normalize_rgb(m.rgb)) for m in self._markers]
        resolved = self._resolve_overlaps(raw, center)

        # 先画引线，再画点，避免线压在点上
        for original, placed in zip(raw, resolved):
            if math.hypot(original.x() - placed.x(), original.y() - placed.y()) > 0.6:
                painter.setPen(QPen(QColor(12, 12, 16, 150), 1, Qt.DotLine))
                painter.drawLine(original, placed)

        for marker, point in zip(self._markers, resolved):
            self._paint_marker(painter, marker, point)

    def _paint_marker(self, painter: QPainter, marker: "WheelMarker", point: QPointF) -> None:
        r, g, b = normalize_rgb(marker.rgb)
        size = 13.0 if marker.emphasis else 10.0
        painter.setPen(QPen(QColor(12, 12, 16, 220), 2.0))
        painter.setBrush(QBrush(QColor(r, g, b)))
        painter.drawEllipse(point, size / 2.0, size / 2.0)
        if marker.emphasis:
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1.4))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(point, size / 2.0 + 4.0, size / 2.0 + 4.0)
            self._paint_crosshair(painter, point, size)
        if marker.index:
            self._paint_badge(painter, point, size, marker.index)

    @staticmethod
    def _paint_crosshair(painter: QPainter, point: QPointF, size: float) -> None:
        """目标色的十字准星：和候选色一眼区分开。"""
        painter.setPen(QPen(QColor(255, 255, 255, 190), 1.2))
        cross = size / 2.0 + 7.0
        painter.drawLine(QPointF(point.x() - cross, point.y()),
                         QPointF(point.x() - size / 2.0 - 2, point.y()))
        painter.drawLine(QPointF(point.x() + size / 2.0 + 2, point.y()),
                         QPointF(point.x() + cross, point.y()))
        painter.drawLine(QPointF(point.x(), point.y() - cross),
                         QPointF(point.x(), point.y() - size / 2.0 - 2))
        painter.drawLine(QPointF(point.x(), point.y() + size / 2.0 + 2),
                         QPointF(point.x(), point.y() + cross))

    @staticmethod
    def _paint_badge(painter: QPainter, point: QPointF, size: float, index: int) -> None:
        """编号徽标：黑底白字，任何底色上都读得清。"""
        text = index_badge(index)
        painter.setFont(font(7, bold=True))
        metrics = painter.fontMetrics()
        width = max(14, metrics.horizontalAdvance(text) + 6)
        badge = QRect(int(point.x() + size / 2.0 + 2),
                      int(point.y() - size / 2.0 - 12),
                      int(width), 13)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(12, 14, 18, 210))
        painter.drawRoundedRect(badge, 6, 6)
        painter.setPen(QColor(240, 242, 248))
        painter.drawText(badge, Qt.AlignCenter, text)


class ColorWheelCard(QFrame):
    """色盘 + 底部图例。"""

    def __init__(self, title: str = "色盘定位", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        self._title = QLabel(title)
        self._title.setObjectName("SectionLabel")
        layout.addWidget(self._title)

        self._wheel = ColorWheel(self)
        layout.addWidget(self._wheel, 1)

        self._legend = QLabel("")
        self._legend.setWordWrap(True)
        self._legend.setObjectName("DimLabel")
        layout.addWidget(self._legend)

    def set_markers(self, markers: Sequence[WheelMarker], legend: str = "") -> None:
        self._wheel.set_markers(markers)
        self._legend.setText(legend)

    def clear(self) -> None:
        self._wheel.clear()
        self._legend.setText("")
