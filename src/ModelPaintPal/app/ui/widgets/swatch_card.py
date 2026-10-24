# -*- coding: utf-8 -*-
"""色卡对比组件。

把「目标色 / 混合色 / 各组分色」摆在同一行里做并排对比——这是判断配色是否
可信最直观的方式。

两个关键改进：
* **自动换行**：色卡按可用宽度自动折成多行（以前固定单行，窄窗口下被压成窄条，
  只有 1–2 个色块时又被拉成半个屏幕大的方块）；
* **编号标注**：每个色块带 ① ② ③ 编号，与色盘标记、图例一一对应，
  用户不用靠颜色去猜"哪一块是哪个色号"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout

from ...core.color_models import contrast_text_color, normalize_rgb, rgb_to_hex
from ..paint import painter_on
from ..theme import font

__all__ = ["SwatchItem", "SwatchStrip", "SwatchCompare", "index_badge"]

_MIN_SWATCH_WIDTH = 74
_MAX_SWATCH_WIDTH = 168
_SWATCH_HEIGHT = 76
_BADGE_BAND = 17   # 顶部留给 ΔE 角标的高度
_SPACING = 8


def index_badge(index: int) -> str:
    """1 → ①，超过 20 用 (n) 兜底。"""
    if 1 <= index <= 20:
        return chr(0x2460 + index - 1)
    return f"({index})"


@dataclass
class SwatchItem:
    rgb: Sequence[float]
    title: str = ""
    subtitle: str = ""
    uid: str = ""
    delta_e: Optional[float] = None
    index: int = 0

    @property
    def hex(self) -> str:
        return rgb_to_hex(self.rgb)


class _Swatch(QFrame):
    """单个色块：编号 + 名称 + 说明 + ΔE 角标。

    整体自绘，不用子 QLabel：一张建议卡有 4–6 个色块，每个色块再挂两个带
    setStyleSheet 的 QLabel，就是十几次样式表解析——实测这一项占掉了整张卡片
    渲染时间的六成以上。自绘之后既没有子控件创建开销，也不存在"角标压住文字"
    的排版冲突。
    """

    clicked = Signal(str)

    def __init__(self, item: SwatchItem, parent=None) -> None:
        super().__init__(parent)
        self._item = item
        self.setMinimumSize(_MIN_SWATCH_WIDTH, _SWATCH_HEIGHT)
        self.setMaximumWidth(_MAX_SWATCH_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self._rgb = normalize_rgb(item.rgb)
        text_r, text_g, text_b = contrast_text_color(self._rgb)
        self._text_color = QColor(text_r, text_g, text_b)
        title = item.title or item.hex
        self._title = f"{index_badge(item.index)} {title}" if item.index else title
        self.setToolTip(
            f"{item.title}\n{item.subtitle}\n{item.hex}"
            + (f"\nΔE {item.delta_e:.2f}" if item.delta_e is not None else "")
            + ("\n点击复制色值" if item.uid else "")
        )

    def update_item(self, item: SwatchItem) -> None:
        """原地换数据（复用控件，避免每次渲染都重建 QWidget）。"""
        self._item = item
        self._rgb = normalize_rgb(item.rgb)
        text_r, text_g, text_b = contrast_text_color(self._rgb)
        self._text_color = QColor(text_r, text_g, text_b)
        title = item.title or item.hex
        self._title = f"{index_badge(item.index)} {title}" if item.index else title
        self.setToolTip(
            f"{item.title}\n{item.subtitle}\n{item.hex}"
            + (f"\nΔE {item.delta_e:.2f}" if item.delta_e is not None else "")
            + ("\n点击复制色值" if item.uid else "")
        )
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._item.uid:
            self.clicked.emit(self._item.uid)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        with painter_on(self) as painter:
            self._paint(painter)

    def _paint(self, painter: QPainter) -> None:
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(*self._rgb))
        painter.drawRoundedRect(rect, 8, 8)

        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 8, 8)

        painter.setPen(self._text_color)
        painter.setFont(font(9, bold=True))
        title_rect = QRectF(rect.left() + 6, rect.top() + _BADGE_BAND,
                            rect.width() - 12, rect.height() - _BADGE_BAND - 18)
        painter.drawText(title_rect, Qt.AlignCenter, self._title)

        if self._item.subtitle:
            painter.setFont(font(8))
            painter.drawText(
                QRectF(rect.left() + 6, rect.bottom() - 20, rect.width() - 12, 15),
                Qt.AlignCenter, self._item.subtitle)

        # ΔE 角标：单独占顶部一条带，不与文字抢位置
        if self._item.delta_e is not None:
            text = f"ΔE {self._item.delta_e:.2f}"
            painter.setFont(font(7, bold=True))
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(text) + 10
            badge = QRectF(rect.right() - width - 4, rect.top() + 2, width, 14)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(10, 12, 16, 165))
            painter.drawRoundedRect(badge, 7, 7)
            painter.setPen(QColor(240, 242, 248))
            painter.drawText(badge, Qt.AlignCenter, text)


class SwatchStrip(QFrame):
    """一整条色卡（按宽度自动折行）。"""

    swatchClicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._items: list = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(10, 10, 10, 10)
        self._grid.setSpacing(_SPACING)
        self._grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_items(self, items: Sequence[SwatchItem]) -> None:
        self._items = list(items)
        columns = self._columns_for_width(self.width())
        if (columns == self._columns and self._grid.count() == len(self._items)
                and self._items):
            # 数量与列数都没变：原地更新数据，不重建控件
            for position, item in enumerate(self._items):
                widget = self._grid.itemAt(position).widget()
                if isinstance(widget, _Swatch):
                    widget.update_item(item)
            return
        self._columns = 0
        self._rebuild()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        columns = self._columns_for_width(self.width())
        if columns != self._columns:
            self._rebuild()

    def _columns_for_width(self, width: int) -> int:
        usable = max(_MIN_SWATCH_WIDTH, width - 20)
        per_row = usable // (_MIN_SWATCH_WIDTH + _SPACING)
        return max(1, int(per_row))

    def _rebuild(self) -> None:
        if self.width() <= _MIN_SWATCH_WIDTH and self._items:
            # 还没完成布局（宽度为 0/极小），此时算出的列数一定是 1，
            # 等 resizeEvent 拿到真实宽度后只重建一次，避免"建两遍"。
            self._columns = 0
            return
        while self._grid.count():
            child = self._grid.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not self._items:
            self._columns = 0
            return
        self._columns = self._columns_for_width(self.width())
        for position, item in enumerate(self._items):
            swatch = _Swatch(item, self)
            swatch.clicked.connect(self.swatchClicked.emit)
            self._grid.addWidget(swatch, position // self._columns,
                                 position % self._columns)

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        rows = max(1, (len(self._items) + max(1, self._columns) - 1)
                   // max(1, self._columns))
        hint.setHeight(rows * (_SWATCH_HEIGHT + _SPACING) + 20)
        return hint


class SwatchCompare(QFrame):
    """带标题与说明的色卡对比卡片。"""

    swatchClicked = Signal(str)

    def __init__(self, title: str = "色卡对比", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        self._title = QLabel(title)
        self._title.setObjectName("SectionLabel")
        layout.addWidget(self._title)

        self._strip = SwatchStrip(self)
        self._strip.swatchClicked.connect(self.swatchClicked.emit)
        self._strip.setStyleSheet("QFrame#Card { background-color: transparent; border: none; }")
        layout.addWidget(self._strip)

        self._hint = QLabel("")
        self._hint.setObjectName("FaintLabel")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

    def set_items(self, items: Sequence[SwatchItem], hint: str = "") -> None:
        self._strip.set_items(items)
        self._hint.setText(hint)

    def set_title(self, title: str) -> None:
        self._title.setText(title)
