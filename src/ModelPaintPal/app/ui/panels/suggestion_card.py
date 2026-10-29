# -*- coding: utf-8 -*-
"""单条配色建议卡片。

一张卡片把「要不要调配、怎么配、用多少、买不到怎么办」讲清楚：
* 顶部：ΔE 徽章 + 主色号 + 直用/调配标记 + 色差刻度尺；
* 中部：编号色卡对比条 + 比例堆叠条；
* 底部：用量芯片、替代色号、注意事项、操作按钮。
"""

from __future__ import annotations

from typing import List, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ...core.delta_e import format_delta_e
from ...services.paint_matcher import PaintSuggestion
from ..presenters import build_swatches
from ..theme import Palette, font
from ..widgets.delta_gauge import DeltaGauge
from ..widgets.provenance_box import ProvenanceBox
from ..widgets.ratio_bar import RatioBarCard, RatioSegment
from ..widgets.swatch_card import SwatchStrip

__all__ = ["SuggestionCard"]


class _Badge(QLabel):
    """ΔE 徽章。"""

    def __init__(self, text: str, color: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setFont(font(9, bold=True))
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet(
            f"background-color: {color}; color: #10131A; border-radius: 9px; padding: 3px 9px;"
        )
        self.setFixedHeight(20)


def _chip(text: str, emphasis: bool = False, parent: QWidget | None = None) -> QLabel:
    """用量芯片：把"纯漆 8.54 ml"这类事实做成可扫读的小块。

    样式统一由 QSS 的 `QLabel#Chip` / `QLabel#ChipAccent` 提供——每张卡片要建
    5 个芯片，逐个 setStyleSheet 会让 6 张卡片多解析 30 次样式表。
    """
    label = QLabel(text, parent)
    label.setObjectName("ChipAccent" if emphasis else "Chip")
    return label


class SuggestionCard(QFrame):
    """一条建议。"""

    copyRecipeRequested = Signal(object)     # PaintSuggestion
    copyMarkdownRequested = Signal(object)
    calibrateRequested = Signal(object)
    verifyRequested = Signal(object)         # 请求联网核实主色号来源

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._suggestion: PaintSuggestion | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_subtitle())
        layout.addWidget(self._build_gauge())
        layout.addWidget(self._build_strip())
        layout.addWidget(self._build_ratio())
        layout.addLayout(self._build_usage_row())
        layout.addWidget(self._build_alternatives())
        layout.addWidget(self._build_provenance())
        layout.addWidget(self._build_notes())
        layout.addLayout(self._build_actions())

    def _build_provenance(self) -> QWidget:
        self._prov_box = ProvenanceBox(self)
        self._prov_box.setStyleSheet(
            f"QFrame#Card {{ background-color: {Palette.bg_alt}; "
            f"border: 1px solid {Palette.border}; }}"
        )
        return self._prov_box

    # ------------------------------------------------------------------ 构建
    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(8)
        self._badge = _Badge("—", Palette.accent, self)
        self._title = QLabel("")
        self._title.setObjectName("SectionLabel")
        self._title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        header.addWidget(self._badge)
        header.addWidget(self._title, 1)
        return header

    def _build_subtitle(self) -> QWidget:
        # 英文名 / 光泽 / 漆基类型直接影响能不能混、要不要先喷补土，
        # 不能只藏在 tooltip 里
        self._subtitle = QLabel("")
        self._subtitle.setObjectName("DimLabel")
        self._subtitle.setWordWrap(True)
        self._subtitle.setFont(font(8))
        return self._subtitle

    def _build_gauge(self) -> QWidget:
        self._gauge = DeltaGauge(self)
        return self._gauge

    def _build_strip(self) -> QWidget:
        self._strip = SwatchStrip(self)
        self._strip.setStyleSheet("QFrame#Card { background-color: transparent; border: none; }")
        return self._strip

    def _build_ratio(self) -> QWidget:
        self._ratio = RatioBarCard("混合比例（滴 / 百分比）", self)
        self._ratio.setStyleSheet("QFrame#Card { background-color: %s; border: 1px solid %s; }"
                                  % (Palette.bg_alt, Palette.border))
        return self._ratio

    def _build_usage_row(self) -> QHBoxLayout:
        self._usage_row = QHBoxLayout()
        self._usage_row.setSpacing(6)
        self._usage_row.setContentsMargins(0, 0, 0, 0)
        # 芯片固定建 5 个，后续只改文字：每次渲染都 deleteLater + 新建 5 个 QLabel
        # 会让 6 张卡片多出 30 次控件创建与样式解析。
        self._chips: List[QLabel] = [_chip("", emphasis=(i == 2), parent=self)
                                    for i in range(8)]
        for chip in self._chips:
            self._usage_row.addWidget(chip)
            chip.setVisible(False)
        self._usage_row.addStretch(1)
        return self._usage_row

    def _build_alternatives(self) -> QWidget:
        self._alternatives = QLabel("")
        self._alternatives.setWordWrap(True)
        self._alternatives.setObjectName("DimLabel")
        return self._alternatives

    def _build_notes(self) -> QWidget:
        self._notes = QLabel("")
        self._notes.setWordWrap(True)
        self._notes.setObjectName("FaintLabel")
        return self._notes

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._copy_recipe = QPushButton("复制配方")
        self._copy_recipe.setObjectName("PrimaryButton")
        self._copy_recipe.clicked.connect(self._on_copy_recipe)
        self._copy_md = QPushButton("复制 Markdown")
        self._copy_md.setObjectName("GhostButton")
        self._copy_md.clicked.connect(self._on_copy_markdown)
        self._calibrate = QPushButton("校准色值")
        self._calibrate.setObjectName("GhostButton")
        self._calibrate.setToolTip("按你的试喷结果校正这个色号的数字色值")
        self._calibrate.clicked.connect(self._on_calibrate)
        self._verify = QPushButton("核实来源")
        self._verify.setObjectName("GhostButton")
        self._verify.setToolTip(
            "联网核对这个色号的官方数据（只发送品牌与色号文本，不发送任何图像）")
        self._verify.clicked.connect(self._on_verify)
        actions.addWidget(self._copy_recipe)
        actions.addWidget(self._copy_md)
        actions.addWidget(self._calibrate)
        actions.addWidget(self._verify)
        actions.addStretch(1)
        return actions

    # ------------------------------------------------------------------ 渲染
    def set_suggestion(self, suggestion: PaintSuggestion, target_rgb: Sequence[int]) -> None:
        self._suggestion = suggestion
        self._render_header(suggestion)
        self._render_swatches(suggestion, target_rgb)
        self._render_ratio(suggestion)
        self._render_usage(suggestion)
        self._render_alternatives(suggestion)
        self._render_provenance(suggestion)
        self._notes.setText("提示：" + "；".join(suggestion.notes) if suggestion.notes else "")

    def _render_header(self, suggestion: PaintSuggestion) -> None:
        grade = suggestion.grade
        self._badge.setText(format_delta_e(suggestion.delta_e))
        self._badge.setStyleSheet(
            f"background-color: {grade.color}; color: #10131A; "
            f"border-radius: 9px; padding: 3px 9px;"
        )
        self._gauge.set_value(suggestion.delta_e)

        anchor = suggestion.anchor
        mode = suggestion.mode_label
        # 引用角标只挂在「有来源可查」的色号上；ΔE 徽章不挂（那是算出来的）
        cite = getattr(suggestion, "provenance", None)
        mark = cite.cite_of(anchor.uid) if cite else ""
        cite_text = f" ⟨{mark}⟩" if mark else ""
        self._title.setText(
            f"#{suggestion.rank}  {anchor.full_label}  {anchor.name}  ·  {mode}{cite_text}")
        brand_type = anchor.brand.type_label if anchor.brand else ""
        self._subtitle.setText(
            " · ".join(part for part in (anchor.name_en, anchor.finish_label,
                                         brand_type, f"色差判定：{grade.label}") if part)
        )

    def _render_swatches(self, suggestion: PaintSuggestion,
                         target_rgb: Sequence[int]) -> None:
        self._strip.set_items(build_swatches(suggestion, target_rgb))

    def _render_ratio(self, suggestion: PaintSuggestion) -> None:
        segments = [
            RatioSegment(comp.paint.rgb, comp.paint.code, comp.percent, f"{comp.drops} 滴")
            for comp in suggestion.recipe.components
        ]
        legend = "配比：" + suggestion.recipe.drops_text() + " 滴 · 占比 " + suggestion.recipe.percent_text()
        self._ratio.set_segments(segments, legend)
        self._ratio.setVisible(len(segments) > 1)
        self._ratio.set_title("混合比例（滴 / 百分比）" if len(segments) > 1
                              else "单一色号，无需调配")

    def _render_usage(self, suggestion: PaintSuggestion) -> None:
        coverage = suggestion.coverage
        chips: List[str] = [
            f"纯漆 {coverage.paint_ml:.2f} ml",
            f"稀释剂 {coverage.thinner_ml:.2f} ml",
            f"混合液 {coverage.mix_ml:.2f} ml",
            f"{coverage.coats} 层",
        ]
        if coverage.bottles:
            chips.append(f"≈ {coverage.bottles:.2f} 瓶")
        # 多色配方必须给到"每支漆各要多少 ml"，否则用户还得自己按比例换算
        for comp in suggestion.recipe.components:
            amount = coverage.per_component_ml.get(comp.paint.uid)
            if amount and len(suggestion.recipe.components) > 1:
                chips.append(f"{comp.paint.code} {amount:.2f} ml")
        for index, chip in enumerate(self._chips):
            if index < len(chips):
                chip.setText(chips[index])
                chip.setVisible(True)
            else:
                chip.setVisible(False)

    def _render_alternatives(self, suggestion: PaintSuggestion) -> None:
        if suggestion.alternatives:
            lines = ["替代色号："]
            for alt in suggestion.alternatives[:4]:
                # 同标准色号（品牌官方标注）与「只是颜色接近」不是一回事，
                # 界面上必须让用户自己判断该信哪个。
                label = getattr(alt, "evidence_label", "")
                tail = f" · {label}" if label else ""
                lines.append(f"· {alt.paint.brand_label} {alt.paint.code} "
                             f"{alt.paint.name}（{alt.reason}{tail}）")
            self._alternatives.setText("\n".join(lines))
        else:
            self._alternatives.setText("替代色号：库内暂无同标准色的其它品牌色号")

    def _render_provenance(self, suggestion: PaintSuggestion) -> None:
        prov = getattr(suggestion, "provenance", None)
        # 推算项单独列出，不给编号 —— 它们没有可点开的来源
        inferred = ["配比（Kubelka-Munk 求解）", "用量估算", "色差 ΔE"]
        self._prov_box.set_provenance(prov, inferred)
        # 来源不明时才值得去核实；已经有官方来源的核实意义不大，但仍允许手动触发
        self._verify.setVisible(True)

    # ------------------------------------------------------------------ 交互
    def _on_copy_recipe(self) -> None:
        if self._suggestion is not None:
            self.copyRecipeRequested.emit(self._suggestion)

    def _on_copy_markdown(self) -> None:
        if self._suggestion is not None:
            self.copyMarkdownRequested.emit(self._suggestion)

    def _on_calibrate(self) -> None:
        if self._suggestion is not None:
            self.calibrateRequested.emit(self._suggestion)

    def _on_verify(self) -> None:
        if self._suggestion is not None:
            self.verifyRequested.emit(self._suggestion)
