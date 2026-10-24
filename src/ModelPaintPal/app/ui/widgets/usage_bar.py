# -*- coding: utf-8 -*-
"""用量构成条：把「纯漆 / 稀释剂」的体积比例画成一条可扫读的条形。

文字写「纯漆 8.54 ml，稀释剂 8.54 ml」时，用户还得在脑子里换算比例；
画成条形后，"这次要调一半稀释剂"是一眼的事。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..paint import painter_on
from ..theme import Palette, font

__all__ = ["UsageBar"]

_BAR_HEIGHT = 30


class UsageBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._paint = 0.0
        self._thinner = 0.0
        self.setMinimumHeight(_BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_values(self, paint_ml: float, thinner_ml: float) -> None:
        self._paint = max(0.0, float(paint_ml))
        self._thinner = max(0.0, float(thinner_ml))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with painter_on(self) as painter:
            self._draw(painter)

    def _draw(self, painter: QPainter) -> None:
        rect = QRectF(self.rect())
        total = self._paint + self._thinner
        if total <= 0.0:
            painter.setPen(QColor(Palette.text_faint))
            painter.setFont(font(8))
            painter.drawText(rect, Qt.AlignCenter, "取色后显示纯漆 / 稀释剂构成")
            return

        paint_ratio = self._paint / total
        split = rect.width() * paint_ratio
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Palette.accent_dim))
        painter.drawRoundedRect(QRectF(0, 0, max(2.0, split - 1), rect.height()), 4, 4)
        painter.setBrush(QColor(Palette.border_strong))
        painter.drawRoundedRect(
            QRectF(split + 1, 0, max(2.0, rect.width() - split - 1), rect.height()), 4, 4)

        painter.setFont(font(8, bold=True))
        painter.setPen(QColor(255, 255, 255, 235))
        if split > 70:
            painter.drawText(QRectF(6, 0, split - 8, rect.height()),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             f"纯漆 {self._paint:.2f} ml（{paint_ratio * 100:.0f}%）")
        if rect.width() - split > 90:
            label_color = QColor(Palette.text)
            label_color.setAlpha(235)
            painter.setPen(label_color)
            painter.drawText(QRectF(split + 6, 0, rect.width() - split - 8, rect.height()),
                             Qt.AlignRight | Qt.AlignVCenter,
                             f"稀释剂 {self._thinner:.2f} ml（{(1 - paint_ratio) * 100:.0f}%）")
