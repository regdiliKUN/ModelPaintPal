# -*- coding: utf-8 -*-
"""喷涂用量参数面板。

所有参数都直接绑定到 ``AppConfig``，改动即时存盘并重算建议。

参数命名遵循一个原则：**标签说人话，说明放在标签下面**。
"单位用量 / 余量系数"这类只有作者看得懂的词，改成"每层每平米用量 / 调漆余量"，
并在控件下方固定一行小字解释它的物理含义与取值范围，而不是塞进 tooltip
（tooltip 要悬停才出现，等于没有说明）。
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ...core.config import AppConfig
from ...services.coverage import CoverageInput, REFERENCE_DILUTION_FACTOR
from ...services.paint_matcher import PaintSuggestion
from ..theme import Palette
from ..widgets.form_row import form_label, hint_label, with_hint
from ..widgets.usage_bar import UsageBar

__all__ = ["CoveragePanel"]

_APPLICATION_LABELS = {
    "airbrush": "喷笔（损耗 1.35×）",
    "brush": "笔涂（损耗 1.05×）",
    "spray_can": "喷罐（损耗 1.60×）",
}
_SURFACE_LABELS = {
    "primed": "已上水补土（1.00×）",
    "raw_print": "3D 打印件未处理（1.30×）",
    "glossy": "光面塑料（1.10×）",
}

# 常用题材的一键预设：面积是最难估的参数，给出锚点比让用户瞎填有用得多
_PRESETS = (
    ("1/35 战车", {"area_cm2": 500.0, "coats": 2, "surface": "primed", "application": "airbrush"}),
    ("1/100 飞机", {"area_cm2": 300.0, "coats": 2, "surface": "primed", "application": "airbrush"}),
    ("1/6 手办", {"area_cm2": 900.0, "coats": 3, "surface": "raw_print", "application": "airbrush"}),
)

_FIELD_WIDTH = 210


class CoveragePanel(QFrame):
    """参数表单 + 当前建议的用量摘要。"""

    configChanged = Signal()

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._updating = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        self._scroll.setWidget(container)
        outer.addWidget(self._scroll)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        title = QLabel("喷涂参数与用量")
        title.setObjectName("SectionLabel")
        layout.addWidget(title)

        intro = hint_label("这些参数只影响「用多少漆」的估算，不影响配色匹配结果。", self)
        layout.addWidget(intro)

        layout.addLayout(self._build_presets())
        layout.addLayout(self._build_form())
        layout.addWidget(self._build_summary())
        layout.addWidget(self._build_formula_hint())
        layout.addStretch(1)
        self.sync_from_config()

    # ------------------------------------------------------------------ 构建
    def _build_presets(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        label = QLabel("快速套用")
        label.setObjectName("DimLabel")
        row.addWidget(label)
        for title, values in _PRESETS:
            button = QPushButton(title)
            button.setObjectName("GhostButton")
            button.setToolTip("按「%s」的常见面积/层数/基材填好参数" % title)
            button.clicked.connect(lambda _=False, v=values: self._apply_preset(v))
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _build_form(self) -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self._add_area_field(form)
        self._add_coat_fields(form)
        self._add_material_fields(form)
        return form

    def _add_area_field(self, form: QFormLayout) -> None:
        self._area = QDoubleSpinBox()
        self._area.setRange(1.0, 500000.0)
        self._area.setDecimals(0)
        self._area.setSuffix(" cm²")
        self._area.setSingleStep(50.0)
        self._area.setMaximumWidth(_FIELD_WIDTH)
        self._area.valueChanged.connect(self._on_area_changed)
        form.addRow(form_label("喷涂面积"), with_hint(
            self._area, "整个模型的展开面积，1/35 战车约 500"))

    def _add_coat_fields(self, form: QFormLayout) -> None:
        self._coats = QSpinBox()
        self._coats.setRange(1, 8)
        self._coats.setMaximumWidth(_FIELD_WIDTH)
        self._coats.valueChanged.connect(self._on_changed)
        form.addRow(form_label("喷涂层数"), with_hint(
            self._coats, "遮盖力弱的色号会自动 +1 层"))

        self._thinner = QDoubleSpinBox()
        self._thinner.setRange(0.0, 5.0)
        self._thinner.setDecimals(2)
        self._thinner.setSingleStep(0.25)
        self._thinner.setSuffix(" : 1")
        self._thinner.setMaximumWidth(_FIELD_WIDTH)
        self._thinner.valueChanged.connect(self._on_changed)
        form.addRow(form_label("稀释比（稀释剂:漆）"), with_hint(
            self._thinner, "1.00 = 1:1；预稀释漆填 0"))

        self._auto_prethinned = QCheckBox("预稀释产品自动按额外稀释剂 0 估算")
        self._auto_prethinned.stateChanged.connect(self._on_changed)
        form.addRow("", self._auto_prethinned)

    def _add_material_fields(self, form: QFormLayout) -> None:
        self._application = QComboBox()
        for key, text in _APPLICATION_LABELS.items():
            self._application.addItem(text, key)
        self._application.setMaximumWidth(_FIELD_WIDTH + 40)
        self._application.currentIndexChanged.connect(self._on_changed)
        form.addRow(form_label("施工方式"), with_hint(
            self._application, "过喷损耗系数；固定残留可在下方另填"))

        self._surface = QComboBox()
        for key, text in _SURFACE_LABELS.items():
            self._surface.addItem(text, key)
        self._surface.setMaximumWidth(_FIELD_WIDTH + 40)
        self._surface.currentIndexChanged.connect(self._on_changed)
        form.addRow(form_label("基材状态"), with_hint(
            self._surface, "3D 打印件未喷补土时，层纹会显著多吃漆"))

        self._rate = QDoubleSpinBox()
        self._rate.setRange(5.0, 200.0)
        self._rate.setDecimals(1)
        self._rate.setSingleStep(5.0)
        self._rate.setSuffix(" ml/m²/层")
        self._rate.setMaximumWidth(_FIELD_WIDTH + 40)
        self._rate.valueChanged.connect(self._on_changed)
        form.addRow(form_label("原漆每层每平米用量"), with_hint(
            self._rate, "默认 55；由旧版参考1:1参数保留估算，非实测。请按喷笔校准"))

        self._buffer = QDoubleSpinBox()
        self._buffer.setRange(1.0, 3.0)
        self._buffer.setDecimals(2)
        self._buffer.setSingleStep(0.05)
        self._buffer.setSuffix(" ×")
        self._buffer.setMaximumWidth(_FIELD_WIDTH)
        self._buffer.valueChanged.connect(self._on_changed)
        form.addRow(form_label("调漆余量"), with_hint(
            self._buffer, "比例余量，1.15=多调15%；如另填固定损耗，请避免重复计入"))

        self._fixed_loss = QDoubleSpinBox()
        self._fixed_loss.setRange(0.0, 20.0)
        self._fixed_loss.setDecimals(2)
        self._fixed_loss.setSingleStep(0.05)
        self._fixed_loss.setSuffix(" ml 原漆")
        self._fixed_loss.setMaximumWidth(_FIELD_WIDTH)
        self._fixed_loss.valueChanged.connect(self._on_changed)
        form.addRow(form_label("固定试喷/残留损耗"), with_hint(
            self._fixed_loss, "每次调漆单独加一次，不随面积或层数缩小；默认 0，可按实测填写"))

    def _build_summary(self) -> QFrame:
        card = QFrame(self)
        card.setObjectName("CardAlt")
        card.setStyleSheet(
            f"QFrame#CardAlt {{ background-color: {Palette.bg_alt}; "
            f"border: 1px solid {Palette.border}; border-radius: 8px; }}"
        )
        box = QVBoxLayout(card)
        box.setContentsMargins(12, 8, 12, 10)
        box.setSpacing(4)
        heading = QLabel("当前方案用量")
        heading.setObjectName("SectionLabel")
        box.addWidget(heading)
        self._usage_bar = UsageBar(card)
        box.addWidget(self._usage_bar)
        self._summary = QLabel("")
        self._summary.setObjectName("DimLabel")
        self._summary.setWordWrap(True)
        box.addWidget(self._summary)
        self._summary_card = card
        return card

    def _build_formula_hint(self) -> QLabel:
        # 显式换行而不是交给 wordWrap：QLabel 在 QVBoxLayout 里按 sizeHint 定高，
        # 长文本被裁成一行的情况比自动换行可靠得多。
        return hint_label(
            "估算模型：原漆 = 面积 × 层数 × 原漆单位用量 × 施工损耗 × 基材系数 × 余量 + 固定损耗\n"
            "稀释剂 = 原漆 × 稀释比；混合液 = 原漆 + 稀释剂。各项均需实喷校准。",
            self,
        )

    # ------------------------------------------------------------------ 同步
    def sync_from_config(self) -> None:
        """按配置回填控件；``_updating`` 用 try/finally 保证复位（同设置页）。"""
        self._updating = True
        try:
            self._apply_config_values()
        finally:
            self._updating = False

    def _apply_config_values(self) -> None:
        self._area.setValue(round(self._config.area_m2 * 10000.0))
        self._coats.setValue(self._config.coats)
        self._thinner.setValue(self._config.thinner_ratio)
        self._application.setCurrentIndex(
            max(0, self._application.findData(self._config.application)))
        self._surface.setCurrentIndex(
            max(0, self._surface.findData(self._config.surface)))
        self._rate.setValue(self._config.mix_ml_per_m2_per_coat / REFERENCE_DILUTION_FACTOR)
        self._buffer.setValue(self._config.waste_buffer)
        self._fixed_loss.setValue(self._config.fixed_paint_loss_ml)
        self._auto_prethinned.setChecked(self._config.auto_prethinned)

    def coverage_input(self) -> CoverageInput:
        return CoverageInput(
            area_m2=self._config.area_m2,
            coats=self._config.coats,
            thinner_ratio=self._config.thinner_ratio,
            application=self._config.application,
            surface=self._config.surface,
            mix_ml_per_m2_per_coat=self._config.mix_ml_per_m2_per_coat,
            waste_buffer=self._config.waste_buffer,
            fixed_paint_loss_ml=self._config.fixed_paint_loss_ml,
        )

    def set_suggestions(self, suggestions: Sequence[PaintSuggestion]) -> None:
        if not suggestions:
            self._summary.setText("取色后可在这里看到按当前参数估算的用量。")
            self._usage_bar.set_values(0.0, 0.0)
            return
        top = suggestions[0]
        # 使用引擎已经按组分遮盖力、预稀释属性调整好的同一份用量。
        estimate = top.coverage
        lines = [f"当前首选方案：{top.anchor.full_label} {top.anchor.name}",
                 f"纯漆 {estimate.paint_ml:.2f} ml · 稀释剂 {estimate.thinner_ml:.2f} ml "
                 f"· 混合液 {estimate.mix_ml:.2f} ml（{estimate.coats} 层）"]
        if estimate.bottles:
            lines.append(f"≈ {estimate.bottles:.2f} 瓶（{top.anchor.volume_ml:g} ml/瓶）")
        lines.extend(estimate.notes)
        self._summary.setText("\n".join(lines))
        self._usage_bar.set_values(estimate.paint_ml, estimate.thinner_ml)

    # ------------------------------------------------------------------ 回调
    def _apply_preset(self, values: dict) -> None:
        self._updating = True
        self._area.setValue(values["area_cm2"])
        self._coats.setValue(values["coats"])
        self._surface.setCurrentIndex(
            max(0, self._surface.findData(values["surface"])))
        self._application.setCurrentIndex(
            max(0, self._application.findData(values["application"])))
        self._updating = False
        self._config.area_m2 = max(0.0005, values["area_cm2"] / 10000.0)
        self._on_changed()

    def _on_area_changed(self, value: float) -> None:
        if self._updating:
            return
        self._config.area_m2 = max(0.0005, value / 10000.0)
        self._on_changed()

    def _on_changed(self) -> None:
        if self._updating:
            return
        self._config.coats = self._coats.value()
        self._config.thinner_ratio = self._thinner.value()
        self._config.application = self._application.currentData() or "airbrush"
        self._config.surface = self._surface.currentData() or "primed"
        self._config.mix_ml_per_m2_per_coat = self._rate.value() * REFERENCE_DILUTION_FACTOR
        self._config.waste_buffer = self._buffer.value()
        self._config.fixed_paint_loss_ml = self._fixed_loss.value()
        self._config.auto_prethinned = self._auto_prethinned.isChecked()
        self.configChanged.emit()
