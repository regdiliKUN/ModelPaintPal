# -*- coding: utf-8 -*-
"""可视化面板：色差对比（分割 + 放大 + 刻度尺）+ 大图色卡 + 色盘定位 + 图例。

页面按"从判断到定位"的顺序组织：
1. **色差对比**：先回答"这个配色到底像不像"——分割预览、放大差异、刻度尺；
2. **色卡对比**：再看具体是哪几个色号，编号与色盘一致；
3. **色盘定位**：最后看候选色偏在哪个方向（色相/饱和度）。
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from ...services.paint_matcher import PaintSuggestion
from ..presenters import build_legend, build_markers, build_swatches, split_pair
from ..theme import Palette, font
from ..widgets.color_wheel import ColorWheelCard
from ..widgets.delta_gauge import DeltaCompare
from ..widgets.empty_state import EmptyState
from ..widgets.swatch_card import SwatchCompare

__all__ = ["VisualizePanel"]


class _LegendRow(QWidget):
    """图例的一行：色块 + 编号 + 文本。"""

    def __init__(self, rgb: Sequence[int], text: str, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        chip = QLabel("")
        chip.setFixedSize(12, 12)
        r, g, b = (int(c) for c in rgb[:3])
        chip.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid {Palette.border_strong};"
            f" border-radius: 3px;"
        )
        label = QLabel(text)
        label.setFont(font(8))
        label.setWordWrap(True)
        label.setObjectName("DimLabel")
        row.addWidget(chip, 0, Qt.AlignTop)
        row.addWidget(label, 1)


class VisualizePanel(QFrame):
    """色差对比 + 色卡 + 色盘的组合视图。"""

    swatchClicked = Signal(str)
    pickRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        inner = QVBoxLayout(container)
        inner.setContentsMargins(0, 0, 4, 0)
        inner.setSpacing(10)

        self._delta = DeltaCompare("色差对比（目标 vs 混合结果）", container)
        inner.addWidget(self._delta)

        self._compare = SwatchCompare("色卡对比（编号与色盘一致）", container)
        self._compare.swatchClicked.connect(self.swatchClicked.emit)
        inner.addWidget(self._compare)

        row = QHBoxLayout()
        row.setSpacing(10)
        self._wheel = ColorWheelCard("色盘定位", container)
        row.addWidget(self._wheel, 3)

        self._legend_card = QFrame(container)
        self._legend_card.setObjectName("Card")
        legend_layout = QVBoxLayout(self._legend_card)
        legend_layout.setContentsMargins(12, 10, 12, 12)
        legend_layout.setSpacing(6)
        legend_title = QLabel("图例")
        legend_title.setObjectName("SectionLabel")
        legend_layout.addWidget(legend_title)
        self._legend_box = QVBoxLayout()
        self._legend_box.setSpacing(5)
        legend_layout.addLayout(self._legend_box)
        legend_layout.addStretch(1)
        row.addWidget(self._legend_card, 2)

        # 给这一行 stretch=1：窗口变高时由色盘吸收多余空间，页面底部不留空洞
        inner.addLayout(row, 1)
        self._scroll.setWidget(container)
        layout.addWidget(self._scroll, 1)

        self._empty = EmptyState(
            title="还没有可对比的颜色",
            description="先取一个颜色。取色后这里会并排显示目标色、混合结果与各组分色号，"
                        "并在色盘上标出它们的相对位置。",
            glyph="◑",
            action_text="开始吸色",
            action_callback=self.pickRequested.emit,
        )
        layout.addWidget(self._empty)
        self._scroll.setVisible(False)

    # ------------------------------------------------------------------ 渲染
    def set_data(self, target_rgb: Sequence[int],
                 suggestions: Sequence[PaintSuggestion]) -> None:
        if not suggestions:
            self.clear()
            return
        self._empty.setVisible(False)
        self._scroll.setVisible(True)

        top = suggestions[0]
        left_rgb, right_rgb, right_label = split_pair(top, target_rgb)
        self._delta.set_pair(left_rgb, right_rgb, top.delta_e, right_label=right_label)

        self._compare.set_items(
            build_swatches(top, target_rgb),
            hint="点击色块可复制对应色值。色卡为屏幕近似色，实干漆膜会因光泽与膜厚产生偏移。",
        )
        self._wheel.set_markers(
            build_markers(top, target_rgb),
            legend="半径 = 饱和度，角度 = 色相；十字准星是目标色，编号与色卡一一对应。",
        )
        self._set_legend(top, target_rgb)

    def _set_legend(self, suggestion: PaintSuggestion, target_rgb: Sequence[int]) -> None:
        while self._legend_box.count():
            item = self._legend_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        swatches = build_swatches(suggestion, target_rgb)
        for line, swatch in zip(build_legend(suggestion, target_rgb), swatches):
            self._legend_box.addWidget(_LegendRow(swatch.rgb, line, self._legend_card))

        footer = QLabel("色块越接近目标色，ΔE 角标越小；点击色块可复制色值。")
        footer.setFont(font(8))
        footer.setWordWrap(True)
        footer.setObjectName("FaintLabel")
        self._legend_box.addWidget(footer)

    def clear(self) -> None:
        self._compare.set_items([])
        self._wheel.clear()
        self._delta.clear()
        while self._legend_box.count():
            item = self._legend_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._empty.setVisible(True)
        self._scroll.setVisible(False)
