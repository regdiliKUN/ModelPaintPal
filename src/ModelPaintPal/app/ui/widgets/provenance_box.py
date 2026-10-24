# -*- coding: utf-8 -*-
"""来源与置信度展示区（可折叠）。

把「这条结论凭什么」摊开给用户看：

* 上方一行摘要 —— 有几条引用、置信度多少、有没有缺口；
* 展开后列出每条来源的名称 / 链接 / 类型 / 采集时间。

刻意不做的事：**不给计算类结论编号**。配比、用量、ΔE 都是算出来的，编号会
让人以为点得开却点不出东西。它们统一归到「推算」那一组里。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..theme import Palette, font
from ...services.provenance import ProvenanceSummary

__all__ = ["ProvenanceBox"]

_KIND_COLOR = {
    "official": Palette.success,
    "standard": Palette.highlight,
    "retail": Palette.accent,
    "chart": Palette.accent_dim,
    "calibrated": Palette.success,
    "derived": Palette.warn,
}


class ProvenanceBox(QFrame):
    """可折叠的来源区。默认收起，避免把卡片撑得老高。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._prov: Optional[ProvenanceSummary] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 8)
        root.setSpacing(4)
        root.addLayout(self._build_head())
        self._body = self._build_body()
        root.addWidget(self._body)

    def _build_head(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._toggle = QPushButton("▸ 来源")
        self._toggle.setObjectName("GhostButton")
        self._toggle.setCheckable(True)
        self._toggle.setFlat(True)
        self._toggle.setFont(font(9))
        self._toggle.setStyleSheet(
            f"color: {Palette.text_dim}; background: transparent; border: none; padding: 0 2px;"
        )
        self._toggle.toggled.connect(self._on_toggled)
        row.addWidget(self._toggle)

        self._summary = QLabel("")
        self._summary.setObjectName("FaintLabel")
        self._summary.setFont(font(9))
        row.addWidget(self._summary)

        self._confidence = QLabel("")
        self._confidence.setObjectName("Chip")
        row.addWidget(self._confidence)
        row.addStretch(1)
        return row

    def _build_body(self) -> QWidget:
        self._refs = QWidget()
        self._refs_layout = QVBoxLayout(self._refs)
        self._refs_layout.setContentsMargins(4, 2, 0, 0)
        self._refs_layout.setSpacing(3)
        self._refs.setVisible(False)
        return self._refs

    # ------------------------------------------------------------------ 渲染
    def set_provenance(self, prov: Optional[ProvenanceSummary],
                       inferred: Optional[list] = None) -> None:
        self._prov = prov
        self._clear_body()
        if prov is None:
            self._summary.setText("未记录来源")
            self._confidence.setVisible(False)
            self._toggle.setVisible(True)
            return

        self._render_summary(prov)
        self._render_refs(prov, inferred or [])

    def _render_summary(self, prov: ProvenanceSummary) -> None:
        parts = [f"{len(prov.refs)} 条引用"] if prov.refs else ["无外部引用"]
        if prov.unannotated_count:
            parts.append(f"{prov.unannotated_count} 个未标注")
        if prov.derived_count:
            parts.append(f"{prov.derived_count} 个推定")
        if prov.stale_count:
            parts.append("数据可能过期")
        parts.append("含推算项")
        self._summary.setText(" · ".join(parts))
        self._toggle.setText(f"▸ 来源 · {parts[0]}")

        level, color = self._confidence_level(prov)
        self._confidence.setText(level)
        self._confidence.setStyleSheet(
            f"color: {color}; background: transparent; "
            f"border: 1px solid {color}; border-radius: 9px; padding: 1px 7px;"
        )
        self._confidence.setVisible(True)

    @staticmethod
    def _confidence_level(prov: ProvenanceSummary) -> tuple:
        if prov.calibrated:
            return "本机实测", Palette.success
        if prov.confidence >= 0.80:
            return "官方实测", Palette.success
        if prov.confidence >= 0.65:
            return "第三方色卡", Palette.accent
        if prov.unannotated_count:
            return "未标注来源", Palette.warn
        return "推定", Palette.warn

    def _render_refs(self, prov: ProvenanceSummary, inferred: list) -> None:
        if not prov.refs:
            label = QLabel("本条结论没有可点击的外部来源")
            label.setObjectName("FaintLabel")
            label.setFont(font(9))
            self._refs_layout.addWidget(label)
        for ref in prov.refs:
            self._refs_layout.addWidget(self._ref_row(ref))

        tail = QLabel("推算（无引用）：" + "；".join(inferred) if inferred
                      else "推算（无引用）：配比、用量、色差均为本地计算")
        tail.setObjectName("FaintLabel")
        tail.setFont(font(9))
        tail.setWordWrap(True)
        self._refs_layout.addWidget(tail)

        if prov.unannotated_count:
            gap = QLabel(f"另有 {prov.unannotated_count} 个色号未登记来源，"
                         "色值仅用于相对匹配，建议试喷后校准")
            gap.setObjectName("FaintLabel")
            gap.setFont(font(9))
            gap.setWordWrap(True)
            self._refs_layout.addWidget(gap)

    def _ref_row(self, ref) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        index = QLabel(str(ref.index))
        index.setFixedWidth(16)
        index.setAlignment(Qt.AlignCenter)
        index.setFont(font(9, bold=True))
        index.setStyleSheet(
            f"background: {_KIND_COLOR.get(ref.kind, Palette.accent_dim)}; "
            f"color: #10131A; border-radius: 4px; padding: 1px 0;"
        )
        layout.addWidget(index)

        text = QLabel()
        text.setFont(font(9))
        text.setWordWrap(True)
        url_part = (f'　<a style="color:{Palette.accent};" href="{ref.url}">'
                    f'{ref.url}</a>') if ref.url else ""
        date_part = f"　采集于 {ref.date}" if ref.date else ""
        stale_part = "　<span style='color:%s;'>已过期</span>" % Palette.warn if ref.stale else ""
        text.setText(
            f"{ref.name}"
            f"<span style='color:{Palette.text_faint};'>　{ref.kind_label}"
            f"，置信度 {ref.confidence:.2f}{date_part}{stale_part}</span>{url_part}"
        )
        text.setOpenExternalLinks(True)
        layout.addWidget(text, 1)
        return row

    # ------------------------------------------------------------------ 交互
    def _clear_body(self) -> None:
        while self._refs_layout.count():
            item = self._refs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _on_toggled(self, checked: bool) -> None:
        self._toggle.setText(("▾ 来源" if checked else "▸ 来源")
                             + self._suffix())
        self._refs.setVisible(checked)

    def _suffix(self) -> str:
        prov = self._prov
        if prov is None:
            return ""
        if prov.refs:
            return f" · {len(prov.refs)} 条引用"
        return " · 无外部引用"
