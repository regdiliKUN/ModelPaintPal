# -*- coding: utf-8 -*-
"""新手引导浮层。

半透明遮罩 + 高亮挖洞 + 步骤说明卡。目标区域由主窗口传入的 widget 实时计算，
窗口缩放时高亮框跟着走。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .theme import Palette, font

__all__ = ["OnboardingOverlay", "OnboardingStep", "DEFAULT_STEPS"]


@dataclass
class OnboardingStep:
    title: str
    body: str
    target_getter: Optional[object] = None   # callable() -> QWidget | None


class OnboardingOverlay(QWidget):
    """覆盖在内容区之上的引导层。"""

    finished = Signal()
    skipped = Signal()

    CARD_WIDTH = 380

    def __init__(self, parent: QWidget, steps: Optional[List[OnboardingStep]] = None) -> None:
        super().__init__(parent)
        self._steps: List[OnboardingStep] = list(steps or [])
        self._index = 0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background: transparent;")

        self._card = QFrame(self)
        self._card.setObjectName("Card")
        self._card.setFixedWidth(self.CARD_WIDTH)
        self._card.setStyleSheet(
            f"QFrame#Card {{ background-color: {Palette.surface}; "
            f"border: 1px solid {Palette.accent}; border-radius: 12px; }}"
        )

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self._step_label = QLabel("")
        self._step_label.setObjectName("FaintLabel")
        layout.addWidget(self._step_label)

        self._title = QLabel("")
        self._title.setFont(font(12, bold=True))
        self._title.setObjectName("SectionLabel")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setObjectName("DimLabel")
        layout.addWidget(self._body)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._skip = QPushButton("跳过")
        self._skip.setObjectName("GhostButton")
        self._skip.clicked.connect(self._on_skip)
        self._prev = QPushButton("上一步")
        self._prev.setObjectName("GhostButton")
        self._prev.clicked.connect(self._on_prev)
        self._next = QPushButton("下一步")
        self._next.setObjectName("PrimaryButton")
        self._next.clicked.connect(self._on_next)
        buttons.addWidget(self._skip)
        buttons.addStretch(1)
        buttons.addWidget(self._prev)
        buttons.addWidget(self._next)
        layout.addLayout(buttons)

        self.hide()

    # ------------------------------------------------------------------ 控制
    def set_steps(self, steps: List[OnboardingStep]) -> None:
        self._steps = list(steps)

    def start(self) -> None:
        if not self._steps:
            self.hide()
            return
        self._index = 0
        self._sync_size()
        self._render_step()
        self.show()
        self.raise_()

    def _on_next(self) -> None:
        if self._index + 1 >= len(self._steps):
            self.hide()
            self.finished.emit()
            return
        self._index += 1
        self._render_step()

    def _on_prev(self) -> None:
        self._index = max(0, self._index - 1)
        self._render_step()

    def _on_skip(self) -> None:
        self.hide()
        self.skipped.emit()

    # ------------------------------------------------------------------ 渲染
    def _render_step(self) -> None:
        step = self._steps[self._index]
        self._step_label.setText(f"步骤 {self._index + 1} / {len(self._steps)}")
        self._title.setText(step.title)
        self._body.setText(step.body)
        self._prev.setVisible(self._index > 0)
        self._next.setText("开始使用" if self._index + 1 >= len(self._steps) else "下一步")
        self._card.adjustSize()
        self._place_card()
        self.update()

    def _target_rect(self) -> Optional[QRect]:
        step = self._steps[self._index]
        getter = step.target_getter
        if getter is None:
            return None
        try:
            widget = getter() if callable(getter) else getter
        except Exception:
            return None
        if widget is None or not widget.isVisible():
            return None
        top_left = widget.mapTo(self, widget.rect().topLeft())
        return QRect(top_left, widget.rect().size()).adjusted(-6, -6, 6, 6)

    def _place_card(self) -> None:
        self._card.adjustSize()
        rect = self._target_rect()
        if rect is None:
            x = (self.width() - self._card.width()) // 2
            y = (self.height() - self._card.height()) // 2
        else:
            x = rect.right() + 24
            if x + self._card.width() > self.width() - 16:
                x = max(16, rect.left() - self._card.width() - 24)
            y = rect.center().y() - self._card.height() // 2
        y = max(16, min(y, self.height() - self._card.height() - 16))
        self._card.move(max(16, x), y)

    def _sync_size(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._sync_size()
        self._place_card()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        full = QPainterPath()
        full.addRect(self.rect())
        target = self._target_rect()
        if target is not None:
            hole = QPainterPath()
            hole.addRoundedRect(target, 12, 12)
            full = full.subtracted(hole)
        painter.fillPath(full, QColor(8, 9, 13, 190))
        if target is not None:
            painter.setPen(QColor(Palette.accent))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(target, 12, 12)
        painter.end()


DEFAULT_STEPS: List[OnboardingStep] = [
    OnboardingStep(
        "第一步：取一个颜色",
        "点「开始吸色」，或用全局快捷键 Ctrl+Shift+X。鼠标旁会出现放大镜，"
        "移动到位后单击左键取样，右键或 Esc 取消。",
    ),
    OnboardingStep(
        "第二步：看配色建议",
        "取色后右侧会列出可参考的漆种：ΔE 越小越接近，低于容差时会直接标为「可直接瓶用」，"
        "否则给出滴数配比。",
    ),
    OnboardingStep(
        "第三步：复制或校准",
        "每张建议卡片都能一键复制配方（纯文本 / Markdown）。若你试喷后觉得色值偏了，"
        "点「校准色值」把这个色号改成你实测的颜色。",
    ),
    OnboardingStep(
        "第四步：沉淀常用色",
        "取过的颜色自动进「历史记录」，点 ★ 或左侧「收藏此色」可固定到收藏夹，"
        "下次点色块即可重新载入。",
    ),
]
