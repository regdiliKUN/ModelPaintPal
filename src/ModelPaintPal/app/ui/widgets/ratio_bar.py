# -*- coding: utf-8 -*-
"""比例堆叠条形图。

用一段横向色条表达配方中各组分的占比，比单纯的数字更容易建立直觉。
段内直接标注「色号 + 百分比 + 滴数」，不依赖图例来回对照。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...core.color_models import contrast_text_color, normalize_rgb
from ..paint import painter_on
from ..theme import Palette, font

__all__ = ["RatioSegment", "RatioBar", "RatioBarCard"]

_BAR_HEIGHT = 34
_GAP = 2
_MIN_SEGMENT = 26


@dataclass
class RatioSegment:
    rgb: Sequence[float]
    label: str
    percent: float
    detail: str = ""


class RatioBar(QWidget):
    """纯绘制的堆叠条。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._segments: list = []
        self.setMinimumHeight(_BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_segments(self, segments: Sequence[RatioSegment]) -> None:
        self._segments = [s for s in segments if s.percent > 0]
        self.update()

    def clear(self) -> None:
        self._segments = []
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSizeHint().__class__(240, _BAR_HEIGHT)

    def paintEvent(self, event) -> None:  # noqa: N802
        with painter_on(self) as painter:
            self._paint(painter)

    def _paint(self, painter: QPainter) -> None:
        rect = self.rect()
        total = sum(seg.percent for seg in self._segments) or 1.0
        x = 0
        for index, seg in enumerate(self._segments):
            width = int(rect.width() * seg.percent / total)
            if index == len(self._segments) - 1:
                width = rect.width() - x  # 最后一段吃掉舍入误差
            if width <= 0:
                continue
            r, g, b = normalize_rgb(seg.rgb)
            painter.fillRect(x, 0, max(1, width - _GAP), rect.height(), QColor(r, g, b))
            if width >= _MIN_SEGMENT:
                tr, tg, tb = contrast_text_color((r, g, b))
                painter.setPen(QColor(tr, tg, tb))
                painter.setFont(font(9, bold=True))
                inner = max(1, width - _GAP - 8)
                # 单行显示「色号 · 滴数」：两行排版在 34px 高的条里会互相压字，
                # 之前的「滴数」贴着底边被裁掉一半。
                text = f"{seg.label} · {seg.detail}" if seg.detail and inner >= 78 else seg.label
                metrics = painter.fontMetrics()
                if metrics.horizontalAdvance(text) > inner:
                    text = metrics.elidedText(text, Qt.ElideRight, inner)
                painter.drawText(x, 0, max(1, width - _GAP), rect.height(),
                                 Qt.AlignCenter, text)
            x += width
        if not self._segments:
            painter.setPen(QPen(QColor(Palette.border_strong)))
            painter.setFont(font(9))
            painter.drawText(rect, Qt.AlignCenter, "暂无配比")


class RatioBarCard(QFrame):
    """堆叠条 + 图例（用量等附加信息）。"""

    def __init__(self, title: str = "混合比例", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        self._title = QLabel(title)
        self._title.setObjectName("SectionLabel")
        layout.addWidget(self._title)

        self._bar = RatioBar(self)
        layout.addWidget(self._bar)

        self._legend = QLabel("")
        self._legend.setWordWrap(True)
        self._legend.setObjectName("DimLabel")
        layout.addWidget(self._legend)

    def set_segments(self, segments: Sequence[RatioSegment], legend: str = "") -> None:
        self._bar.set_segments(segments)
        self._legend.setText(legend)

    def clear(self) -> None:
        self._bar.clear()
        self._legend.setText("")

    def set_title(self, title: str) -> None:
        self._title.setText(title)
