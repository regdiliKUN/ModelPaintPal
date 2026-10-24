# -*- coding: utf-8 -*-
"""表单小工具：把「控件 + 一行说明」组合成一个可放进 QFormLayout 的字段。

用量参数页与设置页有十几处「标签 + 控件 + 一句人话说明」的重复结构，
说明文字的字号/颜色/换行规则必须一致，否则页面看起来像两个人做的。

说明文字**不换行**：`QFormLayout` 按 sizeHint 定行高，而带 wordWrap 的 QLabel
在列宽变化后需要的高度会变多，行高不会跟着长——文字就会压到下一行上去。
这里改为单行显示 + tooltip 兜底，行高恒定，任何窗口宽度下都不会互相压字。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from ..theme import font

__all__ = ["form_label", "hint_label", "with_hint"]

_MAX_HINT_CHARS = 30


def form_label(text: str, parent: QWidget | None = None) -> QLabel:
    """表单左侧标签。

    QFormLayout 的标签列宽由标签自身的 sizeHint 决定，实测会差几像素，
    长标签（如「配比基准总量」）会被画到卡片边框外面去。这里给一个下限宽度，
    让标签列稳定下来。
    """
    label = QLabel(text, parent)
    label.setMinimumWidth(104)
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return label


def hint_label(text: str, parent: QWidget | None = None,
               wrap: bool = False) -> QLabel:
    """说明文字：小一号、低对比。

    ``wrap=False``（默认，用于表单行内）：单行，避免 QFormLayout 行高不跟着长
    导致压字；``wrap=True`` 用于独立的整段说明（不在表单里，行高由布局正常计算）。
    """
    label = QLabel(text, parent)
    label.setWordWrap(wrap)
    label.setFont(font(8))
    label.setObjectName("FaintLabel")
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter if not wrap else Qt.AlignLeft)
    if len(text) > _MAX_HINT_CHARS:
        label.setToolTip(text)
    return label


def with_hint(widget: QWidget, text: str, parent: QWidget | None = None) -> QWidget:
    """控件右侧挂一行说明，整体作为一个表单字段。

    横向排列而不是纵向：`QFormLayout` 的字段列宽由最宽控件决定，说明放在控件
    下方时可用宽度只有控件本身那么宽（约 200px），一句人话会被截断；放到右侧
    就能用满整行剩余空间，同时省下一半行高。
    """
    holder = QWidget(parent)
    box = QHBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(10)
    box.addWidget(widget, 0, Qt.AlignVCenter)
    hint = hint_label(text, holder)
    hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    box.addWidget(hint, 1)
    return holder
