# -*- coding: utf-8 -*-
"""一个纯色小方块（不带文字）。

三个面板都要画「目标色 / 组分色 / 方案色」的小色块，此前各写了一份 `_swatch`。
合并成一个函数，顺便把「颜色怎么刷到 QLabel 上」这件事收在一处——以后要改成圆角、
加描边或者画棋盘格透明底，只改这里。
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel

from ...core.color_models import normalize_rgb
from ..theme import Palette

__all__ = ["color_swatch", "paint_swatch"]


def paint_swatch(label: QLabel, rgb: Sequence[int]) -> None:
    """把已有 QLabel 刷成指定颜色（避免重复创建控件）。"""
    r, g, b = normalize_rgb(rgb)
    label.setStyleSheet(
        f"background:{QColor(r, g, b).name()};"
        f"border:1px solid {Palette.border_strong};border-radius:3px;")


def color_swatch(rgb: Sequence[int], size: int = 18) -> QLabel:
    """新建一个指定大小的纯色方块。"""
    label = QLabel()
    label.setFixedSize(size, size)
    paint_swatch(label, rgb)
    return label
