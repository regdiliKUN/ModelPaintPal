# -*- coding: utf-8 -*-
"""面板顶部的一行状态文字（空闲文案 / 计算中 / 清空）。

「建议」和「基础配色」两个面板此前各自复制了一份同样的逻辑：三行 ``setText``
加两段内联样式，外加一个只写不读的 ``_busy`` 字段。状态一旦有两份实现就一定会
漂移——改了一处忘了另一处，用户看到的就是两个页签的「计算中」长得不一样。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from ..theme import Palette

__all__ = ["StatusLine"]

_BUSY_TEXT = "计算中…"


class StatusLine(QLabel):
    """带「忙碌态」的一行状态文字。

    忙碌时不覆盖已有结果，只在计数位提示，避免界面闪烁；忙碌结束后自动回到
    上一次设置的**空闲文案**（而不是留一个空标签）。
    """

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self.setObjectName("FaintLabel")
        self._idle_text = ""
        self._busy = False
        self._apply_style()

    # ------------------------------------------------------------------ 状态
    @property
    def is_busy(self) -> bool:
        return self._busy

    def set_idle(self, text: str) -> None:
        """设置空闲态文案（计算完成后展示的常规提示）。"""
        self._idle_text = text
        self._busy = False
        self._apply_style()
        self.setText(text)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._apply_style()
        self.setText(_BUSY_TEXT if self._busy else self._idle_text)

    def clear_text(self) -> None:
        """切到空状态时清空（同时清掉空闲文案，避免下次忙碌结束后闪回旧文案）。"""
        self._idle_text = ""
        self._busy = False
        self._apply_style()
        self.setText("")

    def _apply_style(self) -> None:
        color = Palette.highlight if self._busy else Palette.text_faint
        self.setStyleSheet(f"color: {color}; background: transparent;")
