# -*- coding: utf-8 -*-
"""核实结果抽屉。

「检索过程可见」的正确落点在这里：把**查了哪几个源、各自耗时与状态**摊开，
而不是把后台的查询改写日志倒给用户。用户关心的是「你到底问了谁、谁没答」。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..theme import Palette, font
from ...services.verify_service import VerifyReport

__all__ = ["VerifyDialog"]

_STATUS_COLOR = {
    "ok": Palette.success,
    "timeout": Palette.warn,
    "limit": Palette.warn,
    "parse": Palette.danger,
    "absent": Palette.text_dim,
    "network": Palette.danger,
    "blocked": Palette.danger,
    "disabled": Palette.text_faint,
}


class VerifyDialog(QDialog):
    """展示一次核实的结果。采用与否通过 ``on_adopt`` 回调交回主窗口处理，
    对话框自己不写数据 —— 写数据只有 ``paint_db.calibrate()`` 一条路径。
    """

    def __init__(self, parent=None, on_adopt=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("核实来源")
        self.setMinimumWidth(460)
        self._report: Optional[VerifyReport] = None
        self._on_adopt = on_adopt

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        self._title = QLabel("核实来源")
        self._title.setObjectName("SectionLabel")
        root.addWidget(self._title)

        self._privacy = QLabel("仅发送品牌与色号文本，不发送任何图像或屏幕内容")
        self._privacy.setObjectName("FaintLabel")
        self._privacy.setFont(font(9))
        root.addWidget(self._privacy)

        self._rows = QWidget()
        self._rows_layout = QVBoxLayout(self._rows)
        self._rows_layout.setContentsMargins(0, 4, 0, 4)
        self._rows_layout.setSpacing(4)
        root.addWidget(self._rows)

        self._verdict = QLabel("")
        self._verdict.setWordWrap(True)
        self._verdict.setObjectName("DimLabel")
        self._verdict.setFont(font(9))
        self._verdict.setStyleSheet(
            f"background-color: {Palette.bg_alt}; border: 1px solid {Palette.border}; "
            f"border-radius: 6px; padding: 8px 10px;"
        )
        root.addWidget(self._verdict)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._keep = QPushButton("保持本地值")
        self._keep.setObjectName("GhostButton")
        self._keep.clicked.connect(self.reject)
        self._adopt = QPushButton("采用核实值")
        self._adopt.setObjectName("PrimaryButton")
        self._adopt.setVisible(False)
        self._adopt.clicked.connect(self._on_adopt_clicked)
        actions.addWidget(self._keep)
        actions.addWidget(self._adopt)
        actions.addStretch(1)
        root.addLayout(actions)

    # ------------------------------------------------------------------ 渲染
    def set_report(self, report: VerifyReport) -> None:
        self._report = report
        self._title.setText(f"核实来源 · {report.code}　本地值 {report.local_hex}")
        self._clear_rows()
        for hit in report.hits:
            self._rows_layout.addWidget(self._hit_row(hit))
        if not report.hits:
            empty = QLabel("没有查到任何核验源的结果")
            empty.setObjectName("FaintLabel")
            self._rows_layout.addWidget(empty)
        # 还在查的时候不要套用 verdict() 的「没查到」措辞
        self._verdict.setText(
            report.note if (report.note and not report.hits) else report.verdict())

        best = report.best
        self._adopt.setVisible(best is not None and bool(best.hex)
                               and best.hex.upper() != report.local_hex.upper())
        if best is not None and best.hex:
            self._adopt.setText(f"采用 {best.hex}")

    def _hit_row(self, hit) -> QWidget:
        row = QFrame()
        row.setObjectName("Card")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        status = QLabel(hit.status_label)
        status.setFont(font(9))
        status.setStyleSheet(
            f"color: {_STATUS_COLOR.get(hit.status, Palette.text_dim)}; "
            f"background: transparent; border: 1px solid "
            f"{_STATUS_COLOR.get(hit.status, Palette.border)}; "
            f"border-radius: 4px; padding: 0 5px;"
        )
        layout.addWidget(status)

        if hit.hex:
            swatch = QLabel("")
            swatch.setFixedSize(16, 16)
            swatch.setStyleSheet(
                f"background-color: {hit.hex}; border: 1px solid {Palette.border_strong}; "
                f"border-radius: 3px;"
            )
            layout.addWidget(swatch)

        name = QLabel(hit.name)
        name.setFont(font(9))
        layout.addWidget(name)

        if hit.hex:
            value = QLabel(hit.hex)
            value.setObjectName("FaintLabel")
            value.setFont(font(9))
            layout.addWidget(value)
        if hit.delta_e is not None:
            gap = QLabel(f"ΔE {hit.delta_e:.2f}")
            gap.setObjectName("FaintLabel")
            gap.setFont(font(9))
            layout.addWidget(gap)

        layout.addStretch(1)
        ms = QLabel(f"{hit.elapsed_ms} ms")
        ms.setObjectName("FaintLabel")
        ms.setFont(font(9))
        ms.setAlignment(Qt.AlignRight)
        layout.addWidget(ms)
        return row

    def _clear_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _on_adopt_clicked(self) -> None:
        if self._on_adopt is not None and self._report is not None:
            best = self._report.best
            if best is not None:
                self._on_adopt(self._report, best.hex)
        self.accept()
