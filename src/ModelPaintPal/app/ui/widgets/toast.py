# -*- coding: utf-8 -*-
"""轻量提示条（Toast）。

不用 QMessageBox 打断操作：吸色后、复制配方后等场景只需要一句反馈。

同一个窗口内的多条提示**纵向堆叠**（最多 3 条，超出时挤掉最旧的一条），
相同文案不会重复堆叠而是刷新倒计时——此前多条提示位置完全相同，
后一条会把前一条完全盖住，用户等于什么反馈都没看到。
"""

from __future__ import annotations

import weakref
from typing import List

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from ..theme import Palette, font

__all__ = ["Toast", "show_toast", "active_toasts"]

_DEFAULT_DURATION = 2200
_MAX_VISIBLE = 3
_MARGIN = 22
_GAP = 8

# 每个父窗口一摞提示条；用弱引用，避免窗口销毁后仍被字典持有
_stacks: "weakref.WeakKeyDictionary[QWidget, List[Toast]]" = weakref.WeakKeyDictionary()


class Toast(QFrame):
    """浮动提示条，自动淡出销毁。"""

    def __init__(self, parent: QWidget, message: str, kind: str = "info",
                 duration: int = _DEFAULT_DURATION) -> None:
        super().__init__(parent)
        self.setObjectName("CardAlt")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._message = message

        color = {
            "info": Palette.accent,
            "success": Palette.success,
            "warn": Palette.warn,
            "error": Palette.danger,
        }.get(kind, Palette.accent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(9)

        dot = QLabel("")
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")

        label = QLabel(message)
        label.setFont(font(10))
        label.setStyleSheet("color: %s;" % Palette.text)

        layout.addWidget(dot)
        layout.addWidget(label)

        self.setStyleSheet(
            f"QFrame#CardAlt {{ background-color: {Palette.surface_alt}; "
            f"border: 1px solid {color}; border-radius: 8px; }}"
        )
        self.adjustSize()

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(260)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

        self._lifetime = QTimer(self)
        self._lifetime.setSingleShot(True)
        self._lifetime.timeout.connect(self._fade_out)
        self._lifetime.start(max(500, duration))

        parent.installEventFilter(self)

    # ------------------------------------------------------------------ 定位
    def place(self, offset: int = 0, margin: int = _MARGIN) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        self.move(parent.width() - self.width() - margin,
                  parent.height() - self.height() - margin - offset)
        self.raise_()

    def restart(self, duration: int = _DEFAULT_DURATION) -> None:
        """同文案再次出现时只续命，不叠加。"""
        self._lifetime.start(max(500, duration))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Resize:
            _relayout(self.parentWidget())
        return False

    # ------------------------------------------------------------------ 动画
    def _fade_out(self) -> None:
        self._animation.stop()
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.finished.connect(self._retire)
        self._animation.start()

    def _retire(self) -> None:
        stack = _stacks.get(self.parentWidget()) if self.parentWidget() else None
        if stack and self in stack:
            stack.remove(self)
        _relayout(self.parentWidget())
        self.close()
        self.deleteLater()

    def showEvent(self, event) -> None:  # noqa: N802
        self._animation.stop()
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()
        super().showEvent(event)


def _relayout(parent: QWidget | None) -> None:
    """自下而上重新摆放同一窗口里的所有提示条（最新的排在最上面）。"""
    if parent is None:
        return
    stack = _stacks.get(parent)
    if not stack:
        return
    offset = 0
    for toast in stack:
        toast.place(offset)
        offset += toast.height() + _GAP


def active_toasts(parent: QWidget) -> List[Toast]:
    """当前窗口里还活着的提示条（按创建顺序），测试用。"""
    return list(_stacks.get(parent, []))


def show_toast(parent: QWidget, message: str, kind: str = "info",
               duration: int = _DEFAULT_DURATION) -> Toast:
    stack = _stacks.setdefault(parent, [])
    # 注意：不能用 isVisible() 过滤——父窗口尚未显示时，子控件的 isVisible() 恒为
    # False，会把刚创建的那条也当成"已消失"删掉，堆叠就永远只有一条。
    # 生命周期的回收交给 _retire()（淡出动画结束时调用）。
    for toast in stack:
        if toast._message == message:      # 同一句话不重复堆叠
            toast.restart(duration)
            return toast

    while len(stack) >= _MAX_VISIBLE:      # 超出上限先挤掉最旧的
        oldest = stack.pop(0)
        oldest.close()
        oldest.deleteLater()

    toast = Toast(parent, message, kind, duration)
    stack.append(toast)
    toast.show()
    _relayout(parent)
    return toast
