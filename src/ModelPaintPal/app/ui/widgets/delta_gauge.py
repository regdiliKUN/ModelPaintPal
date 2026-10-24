# -*- coding: utf-8 -*-
"""色差可视化三件套：ΔE 刻度尺 / 上下分割对比 / 色差放大块。

为什么需要它们：界面上原本只有一个 `ΔE 1.93` 的数字。ΔE 是个专业指标，
1.9 到底算"能用"还是"要调"，用户必须记住阈值表才能判断。这三个组件把
抽象数字变成可以**直接看**的东西：

* **刻度尺**：把 1 / 2 / 3.5 / 5 这些行业阈值画成色带，指针落在哪一段一目了然；
* **分割对比**：目标色与混合结果左右拼接，接缝处最容易看出色差；
* **放大块**：把 Lab 空间的差值放大 N 倍后单独画一块，微小色差也能被看见。
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...core.color_models import lab_to_rgb, normalize_rgb, rgb_to_hex, rgb_to_lab
from ...core.delta_e import DELTA_E_GRADES, grade_delta_e
from ..paint import painter_on
from ..theme import Palette, font

__all__ = ["DeltaGauge", "SplitPreview", "AmplifiedDiff", "DeltaCompare"]

_GAUGE_HEIGHT = 56
_MAX_SHOWN = 5.0
_TICKS = (0.0, 1.0, 2.0, 3.5, 5.0)
_BAR_TOP = 24
_BAR_HEIGHT = 9


def _band_color(index: int) -> str:
    return DELTA_E_GRADES[min(index, len(DELTA_E_GRADES) - 1)][2]


def _band_bounds() -> List[float]:
    """ΔE 分级阈值 → 色带边界（0 → 1 → 2 → 3.5 → 5）。"""
    bounds = [0.0] + [limit for limit, _, _ in DELTA_E_GRADES if limit != float("inf")]
    bounds.append(_MAX_SHOWN)
    return sorted(set(min(b, _MAX_SHOWN) for b in bounds))


class DeltaGauge(QWidget):
    """ΔE 刻度尺：色带 + 阈值刻度 + 当前值指针。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value: Optional[float] = None
        self.setMinimumHeight(_GAUGE_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: Optional[float]) -> None:
        # NaN/inf 会让指针坐标变成 NaN，Qt 画出来是一片空白且不报错；
        # 与其画个"看不见的指针"，不如退回"取色后显示色差"的空状态。
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            self._value = None
        else:
            self._value = max(0.0, float(value))
        self.update()

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        with painter_on(self) as painter:
            self._paint(painter)

    def _paint(self, painter: QPainter) -> None:
        left, right = 6, max(7, self.width() - 6)
        width = right - left
        self._paint_bands(painter, left, width)
        self._paint_ticks(painter, left, width)
        if self._value is None:
            painter.setFont(font(8))
            painter.setPen(QColor(Palette.text_faint))
            painter.drawText(QRectF(left, 0, width, _BAR_TOP - 2),
                             Qt.AlignLeft | Qt.AlignVCenter, "取色后显示色差")
        else:
            self._paint_pointer(painter, left, width)

    @staticmethod
    def _paint_bands(painter: QPainter, left: float, width: float) -> None:
        bounds = _band_bounds()
        for index in range(len(bounds) - 1):
            x0 = left + width * bounds[index] / _MAX_SHOWN
            x1 = left + width * bounds[index + 1] / _MAX_SHOWN
            color = QColor(_band_color(index))
            color.setAlpha(170)
            painter.fillRect(QRectF(x0, _BAR_TOP, max(1.0, x1 - x0), _BAR_HEIGHT), color)
        painter.setPen(QPen(QColor(Palette.border), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(left, _BAR_TOP, width, _BAR_HEIGHT))

    @staticmethod
    def _paint_ticks(painter: QPainter, left: float, width: float) -> None:
        painter.setFont(font(7))
        painter.setPen(QColor(Palette.text_faint))
        for tick in _TICKS:
            x = left + width * tick / _MAX_SHOWN
            painter.drawLine(QPointF(x, _BAR_TOP + _BAR_HEIGHT),
                             QPointF(x, _BAR_TOP + _BAR_HEIGHT + 3))
            painter.drawText(QRectF(x - 14, _BAR_TOP + _BAR_HEIGHT + 3, 28, 12),
                             Qt.AlignHCenter | Qt.AlignTop, f"{tick:g}")

    def _paint_pointer(self, painter: QPainter, left: float, width: float) -> None:
        value = float(self._value or 0.0)
        x = left + width * min(value, _MAX_SHOWN) / _MAX_SHOWN
        marker = QColor(grade_delta_e(value).color)

        painter.setPen(Qt.NoPen)
        painter.setBrush(marker)
        painter.drawPolygon(QPolygonF([
            QPointF(x - 5, _BAR_TOP - 7), QPointF(x + 5, _BAR_TOP - 7),
            QPointF(x, _BAR_TOP - 1),
        ]))
        painter.setPen(QPen(marker, 2))
        painter.drawLine(QPointF(x, _BAR_TOP), QPointF(x, _BAR_TOP + _BAR_HEIGHT))

        painter.setFont(font(8, bold=True))
        painter.setPen(marker)
        label = f"ΔE {value:.2f}" + (" >" if value > _MAX_SHOWN else "")
        text_w = painter.fontMetrics().horizontalAdvance(label) + 6
        text_x = min(max(0.0, x - text_w / 2), self.width() - text_w)
        painter.drawText(QRectF(text_x, _BAR_TOP - 20, text_w, 14), Qt.AlignCenter, label)


class SplitPreview(QWidget):
    """目标色 / 对照色 左右分割预览（接缝处最容易看出色差）。"""

    def __init__(self, parent=None, height: int = 96) -> None:
        super().__init__(parent)
        self._left = (128, 128, 128)
        self._right = (128, 128, 128)
        self._left_label = ""
        self._right_label = ""
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_pair(self, left_rgb: Sequence[int], right_rgb: Sequence[int],
                 left_label: str = "目标色", right_label: str = "混合结果") -> None:
        self._left = normalize_rgb(left_rgb)
        self._right = normalize_rgb(right_rgb)
        self._left_label = left_label
        self._right_label = right_label
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with painter_on(self) as painter:
            self._paint(painter)

    def _paint(self, painter: QPainter) -> None:
        rect = self.rect()
        half = rect.width() / 2.0
        left_rect = QRectF(rect.left(), rect.top(), half, rect.height())
        right_rect = QRectF(rect.left() + half, rect.top(), half, rect.height())

        painter.fillRect(left_rect, QColor(*self._left))
        painter.fillRect(right_rect, QColor(*self._right))

        # 接缝：一条 1px 白线，让眼睛有对比基准
        painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
        painter.drawLine(QPointF(rect.left() + half, rect.top()),
                         QPointF(rect.left() + half, rect.bottom()))

        painter.setFont(font(8))
        for area, rgb, label in ((left_rect, self._left, self._left_label),
                                 (right_rect, self._right, self._right_label)):
            if not label:
                continue
            text_color = QColor(18, 18, 20) if sum(rgb) > 380 else QColor(238, 238, 242)
            painter.setPen(text_color)
            painter.drawText(area.adjusted(8, 6, -8, -6), Qt.AlignLeft | Qt.AlignTop, label)
            painter.drawText(area.adjusted(8, 6, -8, -6), Qt.AlignRight | Qt.AlignBottom,
                             rgb_to_hex(rgb))


class AmplifiedDiff(QWidget):
    """把两个颜色的 Lab 差值放大 N 倍，单独画一块，肉眼几乎看不见的色差也能显形。"""

    def __init__(self, parent=None, height: int = 44) -> None:
        super().__init__(parent)
        self._rgb = (40, 40, 40)
        self._factor = 4.0
        self._caption = "色差放大"
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_pair(self, target_rgb: Sequence[int], other_rgb: Sequence[int],
                 factor: float = 4.0) -> None:
        base = rgb_to_lab(normalize_rgb(target_rgb))
        other = rgb_to_lab(normalize_rgb(other_rgb))
        amplified = tuple(base[i] + (other[i] - base[i]) * factor for i in range(3))
        self._rgb = lab_to_rgb(amplified)
        self._factor = factor
        self._caption = f"色差放大 ×{factor:g}（仅用于肉眼判断差异方向）"
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with painter_on(self) as painter:
            self._paint(painter)

    def _paint(self, painter: QPainter) -> None:
        rect = QRect(self.rect())
        painter.fillRect(rect, QColor(*self._rgb))
        painter.setPen(QColor(255, 255, 255, 90))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.setFont(font(8))
        painter.setPen(QColor(18, 18, 20) if sum(self._rgb) > 380 else QColor(238, 238, 242))
        painter.drawText(rect.adjusted(8, 4, -8, -4), Qt.AlignLeft | Qt.AlignVCenter,
                         self._caption)
        painter.drawText(rect.adjusted(8, 4, -8, -4), Qt.AlignRight | Qt.AlignVCenter,
                         rgb_to_hex(self._rgb))


class DeltaCompare(QFrame):
    """把「分割对比 + 色差放大 + 刻度尺」拼成一张卡（色卡对比页用）。"""

    def __init__(self, title: str = "色差对比", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        self._title = QLabel(title)
        self._title.setObjectName("SectionLabel")
        layout.addWidget(self._title)

        self._split = SplitPreview(self, height=104)
        layout.addWidget(self._split)

        self._diff = AmplifiedDiff(self, height=40)
        layout.addWidget(self._diff)

        self._gauge = DeltaGauge(self)
        layout.addWidget(self._gauge)

        self._verdict = QLabel("")
        self._verdict.setWordWrap(True)
        self._verdict.setObjectName("DimLabel")
        self._verdict.setFont(font(9))
        layout.addWidget(self._verdict)

    def set_pair(self, target_rgb: Sequence[int], other_rgb: Sequence[int],
                 delta_e: float, factor: float = 4.0,
                 left_label: str = "目标色", right_label: str = "混合结果") -> None:
        self._split.set_pair(target_rgb, other_rgb, left_label, right_label)
        self._diff.set_pair(target_rgb, other_rgb, factor)
        self._gauge.set_value(delta_e)
        self._verdict.setText(
            f"{grade_delta_e(delta_e).label} · 阈值参考：ΔE<1 几乎不可辨，"
            f"<2 并排才可察，<3.5 喷涂可接受"
        )

    def clear(self) -> None:
        self._gauge.set_value(None)
        self._verdict.setText("")
