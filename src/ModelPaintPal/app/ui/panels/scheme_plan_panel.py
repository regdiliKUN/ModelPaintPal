# -*- coding: utf-8 -*-
"""配色方案面板：把吸到的基色展开成色环方案，每个方案色落到库内真实漆。

为什么单独一页：`scheme_engine` 里的互补 / 分裂互补 / 三角 / 矩形四角 / 邻近 /
单色系六套方案此前**只有测试在调用**，界面上没有任何入口。用户能在「基础配色」页
看到五瓶基础漆怎么调，却看不到「这个色配什么色好看」。

与「基础配色」页的分工：
* 基础配色 = 我只有五瓶漆，怎么调出这个色；
* 配色方案 = 我要做一个作品，这个色该和哪些色搭配。

计算走异步（`submit_scheme`），与建议页互不阻塞。
"""

from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from ...core.delta_e import format_delta_e
from ...services.scheme_engine import (
    SCHEME_DESC, SCHEME_LABELS, SCHEME_ORDER, SchemeStop, default_param_for,
)
from ..widgets.empty_state import EmptyState
from ..widgets.status_line import StatusLine
from ..widgets.swatch import color_swatch as _swatch, paint_swatch

__all__ = ["SchemePlanPanel", "PLAN_TAB_TITLE"]

PLAN_TAB_TITLE = "配色方案"

_EMPTY_TITLE = "还没有取样"
_EMPTY_DESC = ("点击左侧「开始吸色」，或按全局快捷键取一个颜色。"
               "取色后这里会给出「基色 + 互补 / 三角 / 邻近…」的整套配色，"
               "并把每个方案色落到库内能直接买的真实漆。")

# 最多渲染多少个停靠点（方案类型里最多的是矩形四角 4 个、邻近/单色系 7 个）
_MAX_STOPS = 7


class _StopRow(QFrame):
    """一行：方案角色 → 目标色 → 库内推荐配方。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)

        self._role = QLabel("")
        self._role.setObjectName("SectionLabel")
        self._role.setFixedWidth(84)
        row.addWidget(self._role)

        self._swatch = _swatch((200, 200, 200), 20)
        row.addWidget(self._swatch)

        self._hex = QLabel("")
        self._hex.setObjectName("FaintLabel")
        self._hex.setFixedWidth(72)
        row.addWidget(self._hex)

        self._recipe = QLabel("")
        self._recipe.setWordWrap(False)
        row.addWidget(self._recipe, 1)

        self._de = QLabel("")
        self._de.setObjectName("FaintLabel")
        row.addWidget(self._de)

    def set_stop(self, stop: SchemeStop) -> None:
        paint_swatch(self._swatch, stop.target_rgb)
        self._role.setText(stop.role)
        self._hex.setText(stop.target_hex)

        suggestion = stop.suggestion
        if suggestion is None:
            self._recipe.setText("当前品牌范围内暂无匹配色号")
            self._de.setText("")
            return
        if suggestion.is_direct:
            text = (f"{suggestion.anchor.brand_label} {suggestion.anchor.code} "
                    f"{suggestion.anchor.name} · 单色直用")
        else:
            parts = " + ".join(
                f"{c.paint.brand_label} {c.paint.code}" for c in suggestion.recipe.components)
            text = f"{parts} · {suggestion.recipe.drops_text()} 滴"
        self._recipe.setText(text)
        # 超出容差时把「需接受色偏」写进文字，而不是只换个颜色——
        # 只靠颜色区分的话，色弱用户和黑白截图里都看不出来。
        if suggestion.is_within_tolerance:
            self._de.setObjectName("FaintLabel")
            self._de.setText(format_delta_e(suggestion.delta_e))
        else:
            self._de.setObjectName("ErrorLabel")
            self._de.setText(f"{format_delta_e(suggestion.delta_e)} · 色差偏大")
        self._de.style().unpolish(self._de)
        self._de.style().polish(self._de)


class SchemePlanPanel(QFrame):
    """配色方案面板（色环方案 → 真实漆配方）。"""

    pickRequested = Signal()
    # (方案类型, 参数) —— 参数只对邻近/单色系有意义（色数/层次数）
    planRequested = Signal(str, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scheme_type = SCHEME_ORDER[0][0]
        self._param = default_param_for(self._scheme_type)

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
        self._container_layout.setSpacing(8)
        self._container_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        self._empty = EmptyState(
            title=_EMPTY_TITLE, description=_EMPTY_DESC, glyph="◈",
            action_text="开始吸色", action_callback=self.pickRequested.emit,
        )
        layout.addWidget(self._empty, 1)
        self._scroll.setVisible(False)

        self._rows: List[_StopRow] = []
        for _ in range(_MAX_STOPS):
            row = _StopRow(self._container)
            row.setVisible(False)
            self._container_layout.addWidget(row)
            self._rows.append(row)

        self._hint = QLabel("")
        self._hint.setObjectName("DimLabel")
        self._hint.setWordWrap(True)
        self._container_layout.addWidget(self._hint)

    # ------------------------------------------------------------------ 工具条
    def _build_toolbar(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("Card")
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)

        label = QLabel("方案类型")
        label.setObjectName("DimLabel")
        row.addWidget(label)

        self._type_combo = QComboBox()
        for key, text, desc in SCHEME_ORDER:
            self._type_combo.addItem(text, key)
            self._type_combo.setItemData(self._type_combo.count() - 1, desc, Qt.ToolTipRole)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        row.addWidget(self._type_combo)

        self._count_label = QLabel("色数")
        self._count_label.setObjectName("DimLabel")
        row.addWidget(self._count_label)

        self._count_spin = QSpinBox()
        self._count_spin.setRange(3, 7)
        self._count_spin.setToolTip("邻近色/单色系的色数或层次数；其它方案固定")
        self._count_spin.valueChanged.connect(self._on_count_changed)
        row.addWidget(self._count_spin)

        self._refresh = QPushButton("重算")
        self._refresh.setObjectName("GhostButton")
        self._refresh.setToolTip("用当前吸色重新计算配色方案")
        self._refresh.clicked.connect(self._emit_request)
        row.addWidget(self._refresh)

        row.addStretch(1)

        self._status = StatusLine()
        row.addWidget(self._status)
        self._sync_param_controls()
        return bar

    def _sync_param_controls(self) -> None:
        """只有邻近色/单色系用得到「色数」，其它方案把控件灰掉而不是隐藏。

        隐藏会让工具条在切换方案时左右跳动，用户的手会跟着抖。
        """
        needs_param = default_param_for(self._scheme_type) > 0
        self._count_label.setEnabled(needs_param)
        self._count_spin.setEnabled(needs_param)
        if needs_param:
            self._count_spin.blockSignals(True)
            self._count_spin.setValue(max(3, min(7, self._param or default_param_for(self._scheme_type))))
            self._count_spin.blockSignals(False)

    def _on_type_changed(self, _index: int) -> None:
        self._scheme_type = self._type_combo.currentData() or SCHEME_ORDER[0][0]
        self._param = default_param_for(self._scheme_type)
        self._sync_param_controls()
        self._emit_request()

    def _on_count_changed(self, value: int) -> None:
        self._param = int(value)
        self._emit_request()

    def _emit_request(self) -> None:
        self.planRequested.emit(self._scheme_type, int(self._param or 0))

    # ------------------------------------------------------------------ 外部
    def scheme_type(self) -> str:
        return self._scheme_type

    def param(self) -> int:
        return int(self._param or 0)

    def set_scheme(self, scheme_type: str, param: int = 0) -> None:
        """按配置回填（主窗口启动时调用）；未知类型保持当前选择。"""
        if scheme_type not in SCHEME_LABELS:
            return
        index = self._type_combo.findData(scheme_type)
        if index < 0:
            return
        self._type_combo.blockSignals(True)
        self._type_combo.setCurrentIndex(index)
        self._type_combo.blockSignals(False)
        self._scheme_type = scheme_type
        self._param = int(param or default_param_for(scheme_type))
        self._sync_param_controls()

    def set_busy(self, busy: bool) -> None:
        self._status.set_busy(busy)

    def set_stops(self, stops: Sequence[SchemeStop]) -> None:
        if not stops:
            self._show_empty("没有可用配色", "当前品牌范围内没有可参与调配的色号。")
            return
        self._empty.setVisible(False)
        self._scroll.setVisible(True)
        for row, stop in zip(self._rows, stops):
            row.setVisible(True)
            row.set_stop(stop)
        for row in self._rows[len(stops):]:
            row.setVisible(False)

        matched = sum(1 for stop in stops if stop.suggestion is not None)
        self._status.set_idle(f"{len(stops)} 个方案色 · {matched} 个已落到真实漆")
        self._hint.setText(SCHEME_DESC.get(self._scheme_type, ""))

    def show_empty(self, title: str = _EMPTY_TITLE, description: str = "") -> None:
        self._show_empty(title, description or _EMPTY_DESC)

    def _show_empty(self, title: str, description: str) -> None:
        self._empty.set_text(title, description)
        self._empty.setVisible(True)
        self._scroll.setVisible(False)
        self._status.clear_text()
