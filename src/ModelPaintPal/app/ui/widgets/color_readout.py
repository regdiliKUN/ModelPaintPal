# -*- coding: utf-8 -*-
"""色彩数值面板：RGB / HEX / HSV / Lab 一屏展示，每项可一键复制。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
)

from ...core.color_models import ColorSample
from ..theme import Palette, font

__all__ = ["ColorReadout", "ValueRow"]

_FIELDS = ("HEX", "RGB", "HSV", "LAB")


class ValueRow(QFrame):
    """一行「标签 + 数值 + 复制按钮」。"""

    copyRequested = Signal(str, str)  # (标签, 值)

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        self._label_text = label
        self.setObjectName("CardAlt")
        self.setStyleSheet(
            f"QFrame#CardAlt {{ background-color: {Palette.bg_alt}; "
            f"border: 1px solid {Palette.border}; border-radius: 6px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 6, 6)
        layout.setSpacing(8)

        # 固定最小高度：垂直空间紧张时 Qt 会把 QLabel 压到裁切，文字直接消失
        self.setMinimumHeight(28)

        self._name = QLabel(label)
        self._name.setFont(font(9, bold=True))
        self._name.setObjectName("DimLabel")
        self._name.setFixedWidth(34)

        self._value = QLabel("—")
        self._value.setObjectName("MonoLabel")
        self._value.setFont(font(10, mono=True))
        self._value.setObjectName("SectionLabel")
        self._value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._value.setMinimumWidth(120)
        self._value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._copy = QPushButton("复制")
        self._copy.setObjectName("IconButton")
        self._copy.setToolTip(f"复制 {label} 数值到剪贴板")
        self._copy.clicked.connect(lambda: self.copyRequested.emit(self._label_text, self._value.text()))

        layout.addWidget(self._name)
        layout.addWidget(self._value, 1)
        layout.addWidget(self._copy)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class ColorReadout(QFrame):
    """四组色彩数值的容器。"""

    copyRequested = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        header = QLabel("色彩数值")
        header.setObjectName("SectionLabel")
        outer.addWidget(header)

        # 单列铺开：HSV / LAB 的数值较长，两列在 340px 宽度下会被截断
        grid = QGridLayout()
        grid.setSpacing(5)
        self._rows = {}
        for index, field in enumerate(_FIELDS):
            row = ValueRow(field, self)
            row.copyRequested.connect(self.copyRequested.emit)
            self._rows[field] = row
            grid.addWidget(row, index, 0)
        outer.addLayout(grid)

        self._delta = QLabel("")
        self._delta.setFont(font(9))
        self._delta.setObjectName("DimLabel")
        self._delta.setWordWrap(True)
        outer.addWidget(self._delta)

    # ------------------------------------------------------------------ 更新
    def set_sample(self, sample: ColorSample) -> None:
        h, s, v = sample.hsv
        l_val, a_val, b_val = sample.lab
        self._rows["HEX"].set_value(sample.hex)
        self._rows["RGB"].set_value(f"{sample.rgb[0]}, {sample.rgb[1]}, {sample.rgb[2]}")
        self._rows["HSV"].set_value(f"{h:.0f}°, {s:.0f}%, {v:.0f}%")
        self._rows["LAB"].set_value(f"{l_val:.1f}, {a_val:.1f}, {b_val:.1f}")

    def set_delta_text(self, text: str) -> None:
        self._delta.setText(text)

    def clear(self) -> None:
        for row in self._rows.values():
            row.set_value("—")
        self._delta.setText("")
