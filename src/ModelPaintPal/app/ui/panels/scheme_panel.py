# -*- coding: utf-8 -*-
"""基础配色面板：把吸到的目标色分解成「红/黄/蓝/白/黑」五瓶基础漆的调配配方。

核心诉求：用户手头只有这五瓶基础漆，想知道"用这几瓶怎么调出当前吸到的颜色"。
因此本页不展示互不相关的色卡，而是给出——

  * 一条混色条：红/黄/蓝/白/黑按配比占满同一条，直接看出各占百分之多少；
  * 每瓶基础漆对应的整数滴数；
  * 每瓶基础漆在库内最适配的真实漆（牌子可以有区别，但漆就这五瓶）。

计算走异步，与建议页互不阻塞。
"""

from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from ...core.color_models import rgb_to_hex
from ...core.delta_e import format_delta_e
from ...data.brands import BRANDS, brand_keys
from ...services.paint_matcher import PaintSuggestion
from ...services.scheme_engine import MixRecipe
from ..widgets.ratio_bar import RatioBarCard, RatioSegment
from ..widgets.empty_state import EmptyState
from ..widgets.swatch import color_swatch as _swatch, paint_swatch
from ..widgets.status_line import StatusLine

__all__ = ["SchemePanel", "SCHEME_TAB_TITLE"]

SCHEME_TAB_TITLE = "基础配色"

_EMPTY_TITLE = "还没有取样"
_EMPTY_DESC = ("点击左侧「开始吸色」，或按全局快捷键从任意窗口/图片上取一个颜色。"
               "取色后这里会把它分解成一瓶红、一瓶黄、一瓶蓝、一瓶白、一瓶黑"
               "的调配比例（同一条混色条 + 各占百分之多少 + 各几滴）。")


class _MixRow(QFrame):
    """一行：一瓶基础漆 → 占比 / 滴数 / 库内推荐真实漆。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)

        self._swatch = _swatch((200, 30, 35))
        row.addWidget(self._swatch)

        self._role = QLabel("")
        self._role.setObjectName("SectionLabel")
        self._role.setFixedWidth(28)
        row.addWidget(self._role)

        row.addSpacing(6)
        self._ratio = QLabel("")
        self._ratio.setObjectName("DimLabel")
        self._ratio.setFixedWidth(120)
        row.addWidget(self._ratio)

        self._rec = QLabel("")
        self._rec.setWordWrap(True)
        row.addWidget(self._rec, 1)

    def set_component(self, comp, total_drops: int) -> None:
        paint_swatch(self._swatch, comp.base_rgb)
        self._role.setText(comp.role)
        pct = comp.drops / total_drops * 100.0 if total_drops else 0.0
        self._ratio.setText(f"占 {pct:.0f}%  ·  {comp.drops} 滴")

        sug: PaintSuggestion = comp.suggestion
        if sug is not None:
            a = sug.anchor
            self._rec.setText(
                f"推荐真实漆：{a.brand_label} {a.code} {a.name} · {format_delta_e(sug.delta_e)}")
        else:
            self._rec.setText("推荐真实漆：当前品牌范围内暂无匹配")


class SchemePanel(QFrame):
    """基础配色面板（五瓶基础漆调配计算器）。"""

    pickRequested = Signal()
    copyRecipeRequested = Signal(object)
    copyMarkdownRequested = Signal(object)
    calibrateRequested = Signal(object)
    verifyRequested = Signal(object)
    schemeTypeChanged = Signal(str, int)
    # (总滴数) —— 由主窗口据此重新计算配方
    mixRequested = Signal(int)
    # (品牌键列表) —— 基础漆统一到的品牌；空列表 = 混搭（各瓶可来自不同品牌）
    brandChanged = Signal(list)

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
            title=_EMPTY_TITLE, description=_EMPTY_DESC, glyph="◑",
            action_text="开始吸色", action_callback=self.pickRequested.emit,
        )
        layout.addWidget(self._empty, 1)
        self._scroll.setVisible(False)

        self._build_body()
        self._total_drops = 20

    # ------------------------------------------------------------------ 工具条
    def _build_toolbar(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("Card")
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)

        brand_label = QLabel("基础漆品牌")
        brand_label.setObjectName("DimLabel")
        row.addWidget(brand_label)

        self._brand_combo = QComboBox()
        # 第一项「混搭」= 不限品牌（各瓶可来自不同品牌）；其余每个品牌一个单选
        self._brand_combo.addItem("混搭（全部品牌）", "__all__")
        for key in brand_keys():
            self._brand_combo.addItem(BRANDS[key].short, key)
        self._brand_combo.setToolTip(
            "把五瓶基础漆（红/黄/蓝/白/黑）统一到单一品牌；"
            "选「混搭」则每瓶可分别来自不同品牌")
        self._brand_combo.currentIndexChanged.connect(self._on_brand_changed)
        row.addWidget(self._brand_combo)

        label = QLabel("总滴数")
        label.setObjectName("DimLabel")
        row.addWidget(label)

        self._drops_spin = QSpinBox()
        self._drops_spin.setRange(4, 100)
        self._drops_spin.setValue(20)
        self._drops_spin.setSuffix(" 滴")
        self._drops_spin.setToolTip("整套配方的总滴数；占比按此换算成滴数")
        self._drops_spin.valueChanged.connect(self._on_drops_changed)
        row.addWidget(self._drops_spin)

        self._refresh = QPushButton("重算")
        self._refresh.setObjectName("GhostButton")
        self._refresh.setToolTip("用当前吸色重新计算配比")
        self._refresh.clicked.connect(lambda: self.mixRequested.emit(self._total_drops))
        row.addWidget(self._refresh)

        row.addStretch(1)

        self._count_label = StatusLine()
        row.addWidget(self._count_label)
        return bar

    def _on_drops_changed(self, value: int) -> None:
        self._total_drops = value
        self.mixRequested.emit(value)

    def _on_brand_changed(self, _index: int) -> None:
        key = self._brand_combo.currentData()
        if key == "__all__":
            self.brandChanged.emit([])
        else:
            self.brandChanged.emit([key])

    def set_brand(self, brands: Sequence[str]) -> None:
        """按当前选中的品牌回填下拉（主窗口从配置载入后调用）。

        ``brands`` 为空列表表示「混搭」；含一个品牌键表示单一品牌。
        """
        if not brands:
            target = "__all__"
        else:
            target = brands[0]
        idx = self._brand_combo.findData(target)
        if idx >= 0:
            # 程序化回填不能触发 brandChanged：否则「恢复默认」会被当成用户手动换品牌，
            # 白白多写一次盘、多算一次配方
            self._brand_combo.blockSignals(True)
            self._brand_combo.setCurrentIndex(idx)
            self._brand_combo.blockSignals(False)

    # ------------------------------------------------------------------ 主体
    def _build_body(self) -> None:
        # 目标色 / 近似色 对照
        head = QFrame(self._container)
        head.setObjectName("Card")
        h = QHBoxLayout(head)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(12)

        self._target_swatch = _swatch((220, 220, 220), 26)
        self._target_label = QLabel("目标色")
        self._target_label.setObjectName("SectionLabel")
        h.addWidget(self._target_swatch)
        h.addWidget(self._target_label)

        h.addSpacing(10)
        arrow = QLabel("→")
        arrow.setObjectName("FaintLabel")
        h.addWidget(arrow)
        h.addSpacing(10)

        self._pred_swatch = _swatch((220, 220, 220), 26)
        self._pred_label = QLabel("调出近似色")
        self._pred_label.setObjectName("SectionLabel")
        h.addWidget(self._pred_swatch)
        h.addWidget(self._pred_label)

        h.addStretch(1)
        self._de_label = QLabel("")
        self._de_label.setObjectName("FaintLabel")
        h.addWidget(self._de_label)
        self._container_layout.addWidget(head)

        # 混色条：红/黄/蓝/白/黑 占满同一条
        self._bar = RatioBarCard("基础漆配比（同一条混色 · 红/黄/蓝/白/黑）", self._container)
        self._container_layout.addWidget(self._bar)

        # 每瓶基础漆一行
        self._rows: List[_MixRow] = []
        for _ in range(5):
            row = _MixRow(self._container)
            self._container_layout.addWidget(row)
            self._rows.append(row)

    # ------------------------------------------------------------------ 渲染
    def set_mix_recipe(self, recipe: MixRecipe, target_rgb: Sequence[int]) -> None:
        if recipe is None:
            self._show_empty("没有可用配方", "当前品牌范围内没有可参与调配的色号。")
            return
        self._empty.setVisible(False)
        self._scroll.setVisible(True)
        self.set_busy(False)

        paint_swatch(self._target_swatch, target_rgb)
        self._target_label.setText(f"目标 {rgb_to_hex(target_rgb)}")
        paint_swatch(self._pred_swatch, recipe.predicted_rgb)
        self._pred_label.setText(f"近似 {rgb_to_hex(recipe.predicted_rgb)}")
        self._de_label.setText(f"色差 {format_delta_e(recipe.delta_e)}（五瓶内最接近）")

        segments = []
        for comp in recipe.components:
            if comp.drops > 0:
                pct = comp.drops / recipe.total_drops * 100.0
                segments.append(RatioSegment(
                    rgb=comp.base_rgb, label=comp.role,
                    percent=comp.drops,
                    detail=f"{comp.drops}滴 · {pct:.0f}%"))
        self._bar.set_segments(
            segments,
            legend=f"总滴数 {recipe.total_drops} · 按配比调匀即得近似色"
                   f"（{format_delta_e(recipe.delta_e)}）")

        for row, comp in zip(self._rows, recipe.components):
            row.setVisible(True)
            row.set_component(comp, recipe.total_drops)

        self._count_label.set_idle("红/黄/蓝/白/黑 五瓶基础漆")

    def set_busy(self, busy: bool) -> None:
        self._count_label.set_busy(busy)

    def set_initial_type(self, scheme_type: str) -> None:
        """兼容主窗口启动时调用（本页已无方案类型下拉，留作空操作）。"""
        return

    def set_total_drops(self, total: int) -> None:
        """由主窗口在启动时按配置同步总滴数。"""
        self._drops_spin.blockSignals(True)
        self._drops_spin.setValue(int(total))
        self._drops_spin.blockSignals(False)
        self._total_drops = int(total)

    def show_empty(self, title: str = _EMPTY_TITLE, description: str = "") -> None:
        self._show_empty(title, description or _EMPTY_DESC)

    def _show_empty(self, title: str, description: str) -> None:
        self._empty.set_text(title, description)
        self._empty.setVisible(True)
        self._scroll.setVisible(False)
        self._count_label.clear_text()
