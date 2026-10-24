# -*- coding: utf-8 -*-
"""取色面板：主界面最显眼的位置，负责「吸色 → 看到结果 → 快捷操作」。"""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ...core.color_models import (
    ColorSample, contrast_text_color, parse_color_text, rgb_to_hex,
)
from ..paint import painter_on
from ..theme import Palette, font
from ..widgets.color_readout import ColorReadout
from ..widgets.color_tuner import ColorTuner

__all__ = ["PickPanel"]

_PREVIEW_HEIGHT = 96
_EMPTY_RGB = (26, 28, 36)


class _Preview(QFrame):
    """当前颜色的大色块（未取色时显示虚线占位，而不是假装取到了一个深色）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rgb: Optional[tuple] = None
        self.setMinimumHeight(_PREVIEW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_rgb(self, rgb: Optional[Sequence[int]]) -> None:
        self._rgb = None if rgb is None else (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        with painter_on(self) as painter:
            self._paint(painter)

    def _paint(self, painter: QPainter) -> None:
        if self._rgb is None:
            # 空状态：深色底 + 虚线框 + 明确文案，避免把占位色当成真实取色
            painter.fillRect(self.rect(), QColor(_EMPTY_RGB[0], _EMPTY_RGB[1], _EMPTY_RGB[2]))
            pen = QPen(QColor(Palette.border_strong))
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
            painter.setPen(QColor(Palette.text_faint))
            painter.setFont(font(10))
            painter.drawText(self.rect(), Qt.AlignCenter, "尚未取色\n点下方按钮或按热键吸一个颜色")
            return

        r, g, b = self._rgb
        tr, tg, tb = contrast_text_color((r, g, b))
        painter.fillRect(self.rect(), QColor(r, g, b))
        painter.setPen(QColor(tr, tg, tb))
        painter.setFont(font(20, bold=True, mono=True))
        painter.drawText(self.rect(), Qt.AlignCenter, rgb_to_hex((r, g, b)))
        painter.setFont(font(8))
        painter.setPen(QColor(tr, tg, tb, 190))
        painter.drawText(self.rect().adjusted(0, 0, 0, -14),
                         Qt.AlignBottom | Qt.AlignHCenter, "当前颜色")


class PickPanel(QFrame):
    """取色 + 数值 + 调色微调 + 快捷操作。"""

    pickRequested = Signal()
    copyRequested = Signal(str, str)
    favoriteRequested = Signal()
    manualSubmitted = Signal(tuple)
    tuneChanged = Signal(tuple)
    tuneReset = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._sample: Optional[ColorSample] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(self._build_title())
        layout.addWidget(self._build_preview_block())
        layout.addLayout(self._build_pick_block())
        layout.addLayout(self._build_input_block())
        layout.addWidget(self._build_error_label())
        layout.addLayout(self._build_action_block())
        layout.addWidget(self._build_tuner())
        layout.addWidget(self._build_readout())
        layout.addStretch(1)

    # ------------------------------------------------------------------ 构建
    def _build_title(self) -> QLabel:
        title = QLabel("屏幕吸色")
        title.setObjectName("SectionLabel")
        return title

    def _build_preview_block(self) -> QWidget:
        self._preview = _Preview(self)
        return self._preview

    def _build_pick_block(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)
        self._pick_button = QPushButton("开始吸色")
        self._pick_button.setObjectName("PrimaryButton")
        self._pick_button.setMinimumHeight(40)
        self._pick_button.setFont(font(11, bold=True))
        self._pick_button.setCursor(Qt.PointingHandCursor)
        self._pick_button.setToolTip("从屏幕任意位置吸一个颜色（也可以按下面的热键）")
        self._pick_button.clicked.connect(self.pickRequested.emit)

        self._hotkey_hint = QLabel("")
        self._hotkey_hint.setObjectName("FaintLabel")
        self._hotkey_hint.setAlignment(Qt.AlignCenter)
        self._hotkey_hint.setWordWrap(True)

        box.addWidget(self._pick_button)
        box.addWidget(self._hotkey_hint)
        return box

    def _build_input_block(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._input = QLineEdit()
        self._input.setPlaceholderText("粘贴 #RRGGBB 或 r,g,b 后回车")
        self._input.setClearButtonEnabled(True)
        self._input.returnPressed.connect(self._submit_manual)
        self._input.textChanged.connect(self._on_input_changed)
        self._input_button = QPushButton("导入")
        self._input_button.setObjectName("GhostButton")
        self._input_button.setEnabled(False)
        self._input_button.setToolTip("解析输入框里的颜色并载入")
        self._input_button.clicked.connect(self._submit_manual)
        row.addWidget(self._input, 1)
        row.addWidget(self._input_button)
        return row

    def _build_error_label(self) -> QLabel:
        # 输入错误提示：以前只把边框染红，原因塞在 tooltip 里（要悬停才看得到）
        self._error = QLabel("")
        self._error.setObjectName("ErrorLabel")
        self._error.setWordWrap(True)
        self._error.setFont(font(8))
        self._error.setVisible(False)
        return self._error

    def _build_action_block(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._favorite_button = QPushButton("收藏此色")
        self._favorite_button.setObjectName("GhostButton")
        self._favorite_button.setEnabled(False)
        self._favorite_button.clicked.connect(self.favoriteRequested.emit)
        self._copy_hex_button = QPushButton("复制 HEX")
        self._copy_hex_button.setObjectName("GhostButton")
        self._copy_hex_button.setEnabled(False)
        self._copy_hex_button.clicked.connect(self._copy_hex)
        row.addWidget(self._favorite_button)
        row.addWidget(self._copy_hex_button)
        return row

    def _build_tuner(self) -> ColorTuner:
        self._tuner = ColorTuner(self)
        self._tuner.changed.connect(self.tuneChanged.emit)
        self._tuner.resetRequested.connect(self.tuneReset.emit)
        return self._tuner

    def _build_readout(self) -> ColorReadout:
        self._readout = ColorReadout(self)
        self._readout.copyRequested.connect(self.copyRequested.emit)
        return self._readout

    # ------------------------------------------------------------------ 外部
    def set_sample(self, sample: Optional[ColorSample], sync_tuner: bool = True) -> None:
        self._sample = sample
        if sample is None:
            self._preview.set_rgb(None)
            self._readout.clear()
            self._favorite_button.setEnabled(False)
            self._copy_hex_button.setEnabled(False)
            self._tuner.set_base(None)
            return
        self._preview.set_rgb(sample.rgb)
        self._readout.set_sample(sample)
        self._favorite_button.setEnabled(True)
        self._copy_hex_button.setEnabled(True)
        if sync_tuner:
            self._tuner.set_base(sample.rgb)

    def set_delta_text(self, text: str) -> None:
        self._readout.set_delta_text(text)

    def set_hotkey_hint(self, text: str) -> None:
        self._hotkey_hint.setText(text)

    def set_picking(self, active: bool) -> None:
        self._pick_button.setText("吸色中…（点击取样）" if active else "开始吸色")
        self._pick_button.setEnabled(not active)

    def tuner(self) -> ColorTuner:
        return self._tuner

    # ------------------------------------------------------------------ 内部
    def _copy_hex(self) -> None:
        if self._sample is not None:
            self.copyRequested.emit("HEX", self._sample.hex)

    def _on_input_changed(self, text: str) -> None:
        self._input_button.setEnabled(bool(text.strip()))
        # 只要用户开始改输入，就把上一次的错误提示撤掉；用文案判空而不是 isVisible()，
        # 因为控件在窗口未显示时 isVisible() 恒为 False，错误提示会残留。
        if self._error.text():
            self._clear_error()

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)
        self._input.setStyleSheet("border: 1px solid %s;" % Palette.danger)
        self._input.setFocus()

    def _clear_error(self) -> None:
        self._error.setVisible(False)
        self._error.setText("")
        self._input.setStyleSheet("")

    def _submit_manual(self) -> None:
        text = self._input.text().strip()
        if not text:
            self._show_error("请先输入颜色，例如 #C8B269 或 200,178,105")
            return
        try:
            rgb = parse_color_text(text)
        except ValueError:
            # 把异常翻成可操作的提示：告诉用户「能接受什么」，而不是只丢一句"无法识别"
            self._show_error(
                f"无法识别「{text[:24]}」。支持 #RRGGBB / #RGB / rgb(200,178,105) / "
                f"hsl(40,48%,78%) / 200,178,105"
            )
            return
        self._clear_error()
        self.manualSubmitted.emit(rgb)
