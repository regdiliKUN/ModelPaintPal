# -*- coding: utf-8 -*-
"""配色建议面板：工具条 + 建议卡片列表 + 空状态。"""

from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ...core.delta_e import available_formulas
from ...data.brands import BRANDS, brand_keys
from ...services.paint_matcher import PaintSuggestion
from ..widgets.empty_state import EmptyState
from ..widgets.status_line import StatusLine
from .suggestion_card import SuggestionCard

__all__ = ["SuggestPanel"]

_EMPTY_HINT = ("点击左侧「开始吸色」，或按全局快捷键从任意窗口/图片上取一个颜色。"
               "取色后这里会给出可参考的漆种、配比与用量。")


class SuggestPanel(QFrame):
    """建议列表容器。"""

    copyRecipeRequested = Signal(object)
    copyMarkdownRequested = Signal(object)
    calibrateRequested = Signal(object)
    verifyRequested = Signal(object)
    brandFilterChanged = Signal(list)
    formulaChanged = Signal(str)
    pickRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_toolbar())

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 4, 0)
        self._container_layout.setSpacing(10)
        self._container_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        self._empty = EmptyState(
            title="还没有取样",
            description=_EMPTY_HINT,
            glyph="⌖",
            action_text="开始吸色",
            action_callback=self.pickRequested.emit,
        )
        layout.addWidget(self._empty, 1)
        self._scroll.setVisible(False)

        self._cards: List[SuggestionCard] = []

    # ------------------------------------------------------------------ 工具条
    def _build_toolbar(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("Card")
        # 固定高度：否则在没有卡片时（空状态）这条工具条会被纵向拉满，
        # 「建议范围」悬在半个屏幕中间。
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)

        label = QLabel("建议范围")
        label.setObjectName("DimLabel")
        row.addWidget(label)

        self._brand_combo = QComboBox()
        self._brand_combo.addItem("全部品牌（11 家）", [])
        for key in brand_keys():
            self._brand_combo.addItem(BRANDS[key].short, [key])
        # 常用组合
        self._brand_combo.addItem("日系（田宫+郡士）", ["tamiya", "mr_hobby_h", "mr_color_c"])
        self._brand_combo.addItem("欧系（AV+AK+AMMO）", ["vallejo_mc", "vallejo_ma", "ak_3gen", "ammo"])
        self._brand_combo.setToolTip("限定参与匹配与调色的品牌范围；「全部品牌」= 不限")
        self._brand_combo.currentIndexChanged.connect(self._on_brand_changed)
        row.addWidget(self._brand_combo)

        formula_label = QLabel("色差公式")
        formula_label.setObjectName("DimLabel")
        row.addWidget(formula_label)

        self._formula_combo = QComboBox()
        self._formula_combo.addItems(list(available_formulas()))
        self._formula_combo.setToolTip("CIEDE2000 为工业标准；CIE76 更快，蓝紫区偏乐观")
        self._formula_combo.currentTextChanged.connect(self.formulaChanged.emit)
        row.addWidget(self._formula_combo)

        row.addStretch(1)

        self._count_label = StatusLine()
        row.addWidget(self._count_label)
        return bar

    # ------------------------------------------------------------------ 数据
    def set_suggestions(self, suggestions: Sequence[PaintSuggestion],
                        target_rgb: Sequence[int]) -> None:
        if not suggestions:
            self._hide_cards()
            self._show_empty("没有找到可用建议",
                             "当前品牌范围内没有可参与调配的色号。试着在上方切换到「全部品牌」，"
                             "或到设置里放宽金属漆/透明漆的限制。")
            return
        self._empty.setVisible(False)
        self._scroll.setVisible(True)
        self._ensure_cards(len(suggestions))
        for card, suggestion in zip(self._cards, suggestions):
            card.set_suggestion(suggestion, target_rgb)
            card.setVisible(True)
        self._count_label.set_idle(f"{len(suggestions)} 条建议 · 色号库 {self._db_hint()}")

    def _ensure_cards(self, count: int) -> None:
        """卡片池：连续吸色时建议条数通常不变，复用已有卡片而不是全量重建。

        重建 6 张卡片意味着 60+ 个 QWidget 的创建/销毁与样式解析，
        实测占掉整次渲染七成以上的时间。
        """
        while len(self._cards) < count:
            card = SuggestionCard(self._container)
            card.copyRecipeRequested.connect(self.copyRecipeRequested.emit)
            card.copyMarkdownRequested.connect(self.copyMarkdownRequested.emit)
            card.calibrateRequested.connect(self.calibrateRequested.emit)
            card.verifyRequested.connect(self.verifyRequested.emit)
            self._container_layout.addWidget(card)
            self._cards.append(card)

    def set_busy(self, busy: bool) -> None:
        """计算中状态：不清空已有结果，只在计数位提示，避免界面闪烁。"""
        self._count_label.set_busy(busy)

    def _db_hint(self) -> str:
        from ...data.paint_db import get_database

        return f"{len(get_database())} 色"

    def show_empty(self, title: str = "还没有取样", description: str = "") -> None:
        self._hide_cards()
        self._show_empty(title, description or _EMPTY_HINT)

    def _show_empty(self, title: str, description: str) -> None:
        self._empty.set_text(title, description)
        self._empty.setVisible(True)
        self._scroll.setVisible(False)
        self._count_label.clear_text()

    def _hide_cards(self) -> None:
        for card in self._cards:
            card.setVisible(False)

    # ------------------------------------------------------------------ 设置同步
    def sync_settings(self, brands: Sequence[str], formula: str) -> None:
        index = self._brand_combo.findData(list(brands))
        if index >= 0:
            self._brand_combo.blockSignals(True)
            self._brand_combo.setCurrentIndex(index)
            self._brand_combo.blockSignals(False)
        self._formula_combo.blockSignals(True)
        self._formula_combo.setCurrentText(formula)
        self._formula_combo.blockSignals(False)

    def _on_brand_changed(self, index: int) -> None:
        data = self._brand_combo.itemData(index)
        self.brandFilterChanged.emit(list(data) if data else [])
