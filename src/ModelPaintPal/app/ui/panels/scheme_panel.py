# -*- coding: utf-8 -*-
"""基础配色面板：方案类型选择 + 色盘预览 + 每个方案色的真实漆配方。

吸到一个颜色后，这里把"红黄蓝之类的基础配色"展开成具体方案，并给每个方案色
找一份库内最适配的真实漆配方（复用 ``SuggestionCard``）。计算走异步，
与建议页互不阻塞。
"""

from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from ...core.color_models import rgb_to_hex
from ...services.paint_matcher import PaintSuggestion
from ...services.scheme_engine import (
    SCHEME_LABELS, SCHEME_ORDER, SchemeStop,
)
from ..theme import Palette
from ..widgets.color_wheel import ColorWheelCard, WheelMarker
from ..widgets.empty_state import EmptyState
from .suggestion_card import SuggestionCard

__all__ = ["SchemePanel", "SCHEME_TAB_TITLE"]

SCHEME_TAB_TITLE = "基础配色"

_EMPTY_TITLE = "还没有取样"
_EMPTY_DESC = ("点击左侧「开始吸色」，或按全局快捷键从任意窗口/图片上取一个颜色。"
               "取色后这里会给出红黄蓝之类的基础配色，以及每个配色对应的真实漆。")


class _SchemeGroup(QFrame):
    """一个方案色：表头（角色 + 目标色值 + 最佳配方摘要）+ 配方卡片。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        self._header = QLabel("")
        self._header.setObjectName("SectionLabel")
        self._header.setWordWrap(True)
        layout.addWidget(self._header)

        self._card = SuggestionCard(self)
        layout.addWidget(self._card)

    def set_stop(self, stop: SchemeStop, base_rgb: Sequence[int]) -> None:
        self._stop = stop
        role = stop.role
        if stop.suggestion is not None:
            sug: PaintSuggestion = stop.suggestion
            anchor = sug.anchor
            summary = (f"{anchor.full_label} {anchor.name} · ΔE {sug.delta_e:.2f}"
                       f"（{sug.mode_label}）")
        else:
            summary = "库内暂无可用配方"
        self._header.setText(f"{role}  ·  目标 {stop.target_hex}  →  {summary}")
        if stop.suggestion is not None:
            self._card.setVisible(True)
            self._card.set_suggestion(stop.suggestion, stop.target_rgb)
        else:
            self._card.setVisible(False)

    def connect_signals(self, panel: "SchemePanel") -> None:
        self._card.copyRecipeRequested.connect(panel.copyRecipeRequested.emit)
        self._card.copyMarkdownRequested.connect(panel.copyMarkdownRequested.emit)
        self._card.calibrateRequested.connect(panel.calibrateRequested.emit)
        self._card.verifyRequested.connect(panel.verifyRequested.emit)


class SchemePanel(QFrame):
    """基础配色面板。"""

    pickRequested = Signal()
    copyRecipeRequested = Signal(object)
    copyMarkdownRequested = Signal(object)
    calibrateRequested = Signal(object)
    verifyRequested = Signal(object)
    # (scheme_type, param) —— 由主窗口据此重新计算方案
    schemeTypeChanged = Signal(str, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_toolbar())

        self._wheel = ColorWheelCard("基础配色预览（色环定位）", self)
        layout.addWidget(self._wheel)

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
            title=_EMPTY_TITLE, description=_EMPTY_DESC, glyph="◑",
            action_text="开始吸色", action_callback=self.pickRequested.emit,
        )
        layout.addWidget(self._empty, 1)
        self._scroll.setVisible(False)

        self._groups: List[_SchemeGroup] = []
        self._busy = False
        self._current_type = SCHEME_ORDER[0][0]

    # ------------------------------------------------------------------ 工具条
    def _build_toolbar(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("Card")
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)

        label = QLabel("配色类型")
        label.setObjectName("DimLabel")
        row.addWidget(label)

        self._type_combo = QComboBox()
        for key, lbl, _ in SCHEME_ORDER:
            self._type_combo.addItem(lbl, key)
        self._type_combo.setToolTip("把吸到的颜色展开成哪类基础配色")
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        row.addWidget(self._type_combo)

        self._param_label = QLabel("色数")
        self._param_label.setObjectName("DimLabel")
        row.addWidget(self._param_label)
        self._param_spin = QSpinBox()
        self._param_spin.setRange(3, 7)
        self._param_spin.setValue(5)
        self._param_spin.setToolTip("邻近色/单色系的层次数量")
        self._param_spin.valueChanged.connect(self._on_param_changed)
        row.addWidget(self._param_spin)
        self._param_label.setVisible(False)
        self._param_spin.setVisible(False)

        self._refresh = QPushButton("重算")
        self._refresh.setObjectName("GhostButton")
        self._refresh.setToolTip("用当前吸色重新计算方案")
        self._refresh.clicked.connect(self._on_refresh)
        row.addWidget(self._refresh)

        row.addStretch(1)

        self._count_label = QLabel("")
        self._count_label.setObjectName("FaintLabel")
        row.addWidget(self._count_label)
        return bar

    # ------------------------------------------------------------------ 交互
    def _on_type_changed(self, index: int) -> None:
        key = self._type_combo.itemData(index)
        if key is None:
            return
        self._current_type = key
        uses_param = key in ("analogous", "monochromatic")
        self._param_label.setVisible(uses_param)
        self._param_spin.setVisible(uses_param)
        self.schemeTypeChanged.emit(key, self._current_param())

    def _on_param_changed(self, _value: int) -> None:
        self.schemeTypeChanged.emit(self._current_type, self._current_param())

    def _on_refresh(self) -> None:
        self.schemeTypeChanged.emit(self._current_type, self._current_param())

    def _current_param(self) -> int:
        if self._current_type in ("analogous", "monochromatic"):
            return self._param_spin.value()
        return 0

    def set_initial_type(self, scheme_type: str) -> None:
        """由主窗口在启动时同步默认类型。"""
        idx = self._type_combo.findData(scheme_type)
        if idx >= 0:
            self._type_combo.blockSignals(True)
            self._type_combo.setCurrentIndex(idx)
            self._type_combo.blockSignals(False)
        self._current_type = scheme_type
        uses_param = scheme_type in ("analogous", "monochromatic")
        self._param_label.setVisible(uses_param)
        self._param_spin.setVisible(uses_param)

    # ------------------------------------------------------------------ 渲染
    def set_scheme(self, stops: Sequence[SchemeStop],
                   base_rgb: Sequence[int]) -> None:
        if not stops:
            self._hide_groups()
            self._show_empty("没有可用方案",
                             "当前品牌范围内没有可参与调配的色号。试着在建议页切到「全部品牌」"
                             "，或到设置里放宽金属漆/透明漆的限制。")
            return
        self._empty.setVisible(False)
        self._wheel.setVisible(True)
        self._scroll.setVisible(True)
        self._render_wheel(stops, base_rgb)
        self._ensure_groups(len(stops))
        for group, stop in zip(self._groups, stops):
            group.set_stop(stop, base_rgb)
            group.setVisible(True)
        for group in self._groups[len(stops):]:
            group.setVisible(False)
        self.set_busy(False)
        self._count_label.setText(
            f"{len(stops)} 个配色点 · {SCHEME_LABELS.get(self._current_type, '')}")

    def _render_wheel(self, stops: Sequence[SchemeStop],
                      base_rgb: Sequence[int]) -> None:
        markers = [WheelMarker(base_rgb, "吸取值", emphasis=True, index=0)]
        legend = [f"吸取值 {rgb_to_hex(base_rgb)}"]
        for i, stop in enumerate(stops, start=1):
            markers.append(WheelMarker(stop.target_rgb, stop.role, index=i))
            legend.append(f"{'①②③④⑤⑥⑦'[i-1]} {stop.role} {stop.target_hex}")
        self._wheel.set_markers(markers, "  ·  ".join(legend))

    def _ensure_groups(self, count: int) -> None:
        while len(self._groups) < count:
            group = _SchemeGroup(self._container)
            group.connect_signals(self)
            self._container_layout.addWidget(group)
            self._groups.append(group)

    def _hide_groups(self) -> None:
        for group in self._groups:
            group.setVisible(False)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self._count_label.setText("计算中…")
            self._count_label.setStyleSheet(
                f"color: {Palette.highlight}; background: transparent;")
        else:
            self._count_label.setStyleSheet(
                f"color: {Palette.text_faint}; background: transparent;")

    def show_empty(self, title: str = _EMPTY_TITLE, description: str = "") -> None:
        self._hide_groups()
        self._wheel.clear()
        self._wheel.setVisible(False)
        self._show_empty(title, description or _EMPTY_DESC)

    def _show_empty(self, title: str, description: str) -> None:
        self._empty.set_text(title, description)
        self._empty.setVisible(True)
        self._scroll.setVisible(False)
        self._count_label.setText("")
