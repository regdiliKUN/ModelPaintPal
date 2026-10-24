# -*- coding: utf-8 -*-
"""自绘控件的统一绘制上下文。

8 个自绘控件（色块、比例条、色盘、刻度尺、用量条、取色预览…）都以
「QPainter(self) + 开抗锯齿 + 画 + end()」开头结尾。抄 8 遍的问题不只是重复：

* 任何一个 `paintEvent` 中途抛异常，`end()` 就不会执行，Qt 会在下一次绘制时
  报 "QPainter::begin: Painter already active" 并画出空白帧；
* 抗锯齿漏设一处，就有一个控件边缘发毛。

用上下文管理器收口后，这两件事都只剩一处定义。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

__all__ = ["painter_on"]


@contextmanager
def painter_on(widget: QWidget, antialias: bool = True) -> Iterator[QPainter]:
    """在 ``widget`` 上开启一次绘制，退出时**必定**调用 ``end()``。"""
    painter = QPainter(widget)
    if antialias:
        painter.setRenderHint(QPainter.Antialiasing)
    try:
        yield painter
    finally:
        painter.end()
