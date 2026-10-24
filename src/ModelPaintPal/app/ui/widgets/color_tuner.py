# -*- coding: utf-8 -*-
"""调色微调器：在当前吸取值上做 HSV 微调，实时看到"再亮一点/再灰一点"的匹配结果。

为什么需要它：吸到的颜色往往不能直接用（屏幕色与漆膜有色差、光照不同）。
以前要试"亮 5%"只能重新吸色，或者自己算一个新 HEX 再手输——
现在拖一下滑块就行，而且滑块以**当前取色**为基准，随时可一键还原。
"""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from ...core.color_models import hsv_to_rgb, normalize_rgb, rgb_to_hsv
from ..theme import Palette, font

__all__ = ["ColorTuner"]

# 滑块停止移动多久后才发信号：一次拖动会触发上百次 valueChanged，
# 每次都重算建议会让界面完全卡死（单次计算 ~140 ms）。
_DEBOUNCE_MS = 120

_CHANNELS = (
    ("hue", "色相", 0, 359, "°"),
    ("sat", "饱和度", 0, 100, "%"),
    ("val", "明度", 0, 100, "%"),
)


class ColorTuner(QFrame):
    """折叠式 HSV 微调面板。"""

    changed = Signal(tuple)      # (r, g, b)
    resetRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CardAlt")
        self.setStyleSheet(
            f"QFrame#CardAlt {{ background-color: {Palette.bg_alt}; "
            f"border: 1px solid {Palette.border}; border-radius: 8px; }}"
        )
        self._base_rgb = (128, 128, 128)
        self._last_emitted: tuple = (128, 128, 128)
        self._sliders: dict = {}
        self._value_labels: dict = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 8)
        outer.setSpacing(6)
        outer.addLayout(self._build_header())
        self._body = self._build_body()
        outer.addWidget(self._body)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_change)

        self.setEnabled(False)

    # ------------------------------------------------------------------ 构建
    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(6)
        self._toggle = QPushButton("微调颜色  ▾")
        self._toggle.setObjectName("GhostButton")
        self._toggle.setCheckable(True)
        self._toggle.setToolTip("在当前取色的基础上微调色相 / 饱和度 / 明度，"
                                "实时重算配色建议（不改动你的原始取色记录）")
        self._toggle.clicked.connect(self._on_toggle)
        header.addWidget(self._toggle, 1)
        return header

    def _build_body(self) -> QFrame:
        body = QFrame(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)
        for key, label, low, high, unit in _CHANNELS:
            body_layout.addLayout(self._build_channel_row(body, key, label, low, high, unit))
        body_layout.addLayout(self._build_footer(body))
        body.setVisible(False)
        return body

    def _build_channel_row(self, parent: QWidget, key: str, label: str,
                           low: int, high: int, unit: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        name = QLabel(label)
        name.setObjectName("DimLabel")
        name.setFont(font(9))
        name.setFixedWidth(44)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider.setSingleStep(1)
        slider.setPageStep(10 if high > 100 else 5)
        slider.valueChanged.connect(self._on_value_changed)
        value = QLabel("—")
        value.setObjectName("DimLabel")
        value.setFont(font(9, mono=True))
        value.setFixedWidth(46)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(name)
        row.addWidget(slider, 1)
        row.addWidget(value)
        self._sliders[key] = (slider, unit)
        self._value_labels[key] = value
        return row

    def _build_footer(self, parent: QWidget) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(6)
        self._hint = QLabel("拖动滑块即可试算；不改动原始取色")
        self._hint.setObjectName("HintLabel")
        self._hint.setFont(font(8))
        self._reset = QPushButton("还原")
        self._reset.setObjectName("GhostButton")
        self._reset.setToolTip("回到吸色时的原始颜色")
        self._reset.clicked.connect(self._on_reset)
        footer.addWidget(self._hint, 1)
        footer.addWidget(self._reset)
        return footer

    # ------------------------------------------------------------------ 外部
    def set_base(self, rgb: Optional[Sequence[int]]) -> None:
        """设定微调基准色（每次吸色/导入后调用）。"""
        if rgb is None:
            self.setEnabled(False)
            for label in self._value_labels.values():
                label.setText("—")
            return
        self.setEnabled(True)
        self._base_rgb = normalize_rgb(rgb)
        self._last_emitted = tuple(self._base_rgb)
        hue, sat, val = rgb_to_hsv(self._base_rgb)
        values = {"hue": int(round(hue)), "sat": int(round(sat)), "val": int(round(val))}
        for key, (slider, unit) in self._sliders.items():
            slider.blockSignals(True)
            slider.setValue(values[key])
            slider.blockSignals(False)
            self._value_labels[key].setText(f"{values[key]}{unit}")

    def current_rgb(self) -> tuple:
        return self._current_rgb()

    def is_dirty(self) -> bool:
        """当前微调结果是否已偏离基准色。"""
        return self._current_rgb() != tuple(self._base_rgb)

    def expand(self, expanded: bool = True) -> None:
        self._toggle.setChecked(expanded)
        self._on_toggle()

    # ------------------------------------------------------------------ 内部
    def _current_rgb(self) -> tuple:
        hue = self._sliders["hue"][0].value()
        sat = self._sliders["sat"][0].value()
        val = self._sliders["val"][0].value()
        return hsv_to_rgb((hue, sat, val))

    def _on_toggle(self) -> None:
        expanded = self._toggle.isChecked()
        self._toggle.setText("微调颜色  ▴" if expanded else "微调颜色  ▾")
        self._body.setVisible(expanded)

    def _on_value_changed(self, _value: int) -> None:
        for key, (slider, unit) in self._sliders.items():
            self._value_labels[key].setText(f"{slider.value()}{unit}")
        self._debounce.start()

    def _emit_change(self) -> None:
        # 与"上一次发出去的颜色"比较，而不是与基准色比较：
        # 否则用户把滑块拖回原位时不会发信号，界面会一直停在旧颜色上。
        rgb = self._current_rgb()
        if rgb == self._last_emitted:
            return
        self._last_emitted = rgb
        self.changed.emit(rgb)

    def _on_reset(self) -> None:
        self.set_base(self._base_rgb)
        self.resetRequested.emit()
