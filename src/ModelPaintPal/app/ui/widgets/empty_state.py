# -*- coding: utf-8 -*-
"""空状态占位组件。

需求里的「空状态说明」：没有取色 / 没有历史 / 没有收藏时，给出下一步该做什么，
而不是留一片空白让用户猜。

除了说明文字，还支持一个**主操作按钮**——空状态最该做的事是"就地给出下一步"，
让用户再去别处找按钮等于把空状态当成了装饰。
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from ..theme import Palette, font

__all__ = ["EmptyState"]


class EmptyState(QFrame):
    """图标（用文字/符号代替图片资源）+ 标题 + 说明 + 可选按钮。"""

    def __init__(self,
                 title: str,
                 description: str = "",
                 glyph: str = "◎",
                 action_text: str = "",
                 action_callback: Optional[Callable[[], None]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(
            f"QFrame#Card {{ background-color: {Palette.bg_alt}; "
            f"border: 1px dashed {Palette.border_strong}; border-radius: 10px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        self._glyph = QLabel(glyph)
        self._glyph.setAlignment(Qt.AlignCenter)
        self._glyph.setFont(font(28))
        self._glyph.setStyleSheet(f"color: {Palette.border_strong}; background: transparent;")

        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setFont(font(11, bold=True))
        self._title.setObjectName("SectionLabel")

        self._description = QLabel(description)
        self._description.setAlignment(Qt.AlignCenter)
        self._description.setWordWrap(True)
        self._description.setFont(font(9))
        self._description.setObjectName("DimLabel")
        self._description.setVisible(bool(description))

        self._action: Optional[QPushButton] = None
        if action_text:
            self._action = QPushButton(action_text)
            self._action.setObjectName("PrimaryButton")
            self._action.setMinimumWidth(160)
            self._action.setCursor(Qt.PointingHandCursor)
            if action_callback is not None:
                self._action.clicked.connect(lambda: action_callback())

        layout.addWidget(self._glyph)
        layout.addWidget(self._title)
        layout.addWidget(self._description)
        if self._action is not None:
            layout.addSpacing(6)
            layout.addWidget(self._action, 0, Qt.AlignCenter)

    # ------------------------------------------------------------------ 更新
    def set_text(self, title: str, description: str = "") -> None:
        """更新文案。

        直接持有标签引用，不再靠 ``findChildren(QLabel)`` 的下标猜——
        之前 description 传空时不会覆盖旧文案，空状态会残留上一次的说明。
        """
        self._title.setText(title)
        self._description.setText(description)
        self._description.setVisible(bool(description))

    def set_action(self, text: str, callback: Optional[Callable[[], None]] = None) -> None:
        """切换/隐藏主操作按钮（text 为空表示隐藏）。"""
        if self._action is not None:
            self._action.setParent(None)
            self._action.deleteLater()
            self._action = None
        if not text:
            return
        self._action = QPushButton(text)
        self._action.setObjectName("PrimaryButton")
        self._action.setMinimumWidth(160)
        self._action.setCursor(Qt.PointingHandCursor)
        if callback is not None:
            self._action.clicked.connect(lambda: callback())
        self.layout().addSpacing(6)
        self.layout().addWidget(self._action, 0, Qt.AlignCenter)

    def set_glyph(self, glyph: str) -> None:
        self._glyph.setText(glyph)
