# -*- coding: utf-8 -*-
"""历史记录 / 收藏夹面板。

用色块网格展示，点击即把该颜色重新载入工作区；每个色块带删除 / 收藏按钮。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...core.color_models import contrast_text_color, rgb_to_hex
from ...core.sample_record import SampleRecord
from ..theme import Palette, font
from ..widgets.empty_state import EmptyState

__all__ = ["LibraryPanel", "ColorGrid"]

_CHIP_HEIGHT = 58
_CHIP_MIN_WIDTH = 148
_MAX_COLUMNS = 4


class _Chip(QFrame):
    """单个色块条目。"""

    selected = Signal(object)      # SampleRecord
    removeRequested = Signal(object)
    favoriteRequested = Signal(object)

    def __init__(self, record: SampleRecord, show_favorite: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._record = record
        self.setObjectName("CardAlt")
        r, g, b = record.rgb
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#CardAlt {{ background-color: rgb({r},{g},{b}); "
            f"border: 1px solid {Palette.border}; border-radius: 8px; }}"
        )
        # 固定高度：网格只有 1–2 条记录时，行会被拉伸成 200px 高的大方块
        self.setFixedHeight(_CHIP_HEIGHT)
        self.setMinimumWidth(_CHIP_MIN_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(4)
        # 没有自定义名字时标题就是 HEX，此时副标题不再重复一遍 HEX
        has_name = bool(record.name)
        title_text = record.name if has_name else record.hex
        name = QLabel(title_text)
        name.setFont(font(9, bold=True, mono=not has_name))
        name.setStyleSheet("color: %s; background: transparent;" % _text_color(record.rgb))
        top.addWidget(name, 1)

        if show_favorite:
            fav = QPushButton("★")
            fav.setObjectName("IconButton")
            fav.setToolTip("加入收藏夹")
            fav.setFixedSize(22, 20)
            fav.clicked.connect(lambda: self.favoriteRequested.emit(self._record))
            top.addWidget(fav)

        close = QPushButton("✕")
        close.setObjectName("IconButton")
        close.setToolTip("删除这条记录")
        close.setFixedSize(22, 20)
        close.clicked.connect(lambda: self.removeRequested.emit(self._record))
        top.addWidget(close)
        layout.addLayout(top)

        meta_text = f"{record.hex} · {record.time_text}" if has_name else record.time_text
        meta = QLabel(meta_text)
        meta.setFont(font(8, mono=True))
        meta.setStyleSheet("color: %s; background: transparent;" % _text_color(record.rgb))
        layout.addWidget(meta)
        layout.addStretch(1)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.selected.emit(self._record)
        super().mouseReleaseEvent(event)


def _text_color(rgb: Sequence[int]) -> str:
    """复用色彩引擎的对比色判定与 HEX 格式化，避免各写一套。"""
    return rgb_to_hex(contrast_text_color(rgb))


class ColorGrid(QFrame):
    """色块网格容器（列数随可用宽度自适应）。"""

    colorSelected = Signal(object)
    removeRequested = Signal(object)
    favoriteRequested = Signal(object)
    pickRequested = Signal()

    def __init__(self, show_favorite: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._show_favorite = show_favorite
        self._records: List[SampleRecord] = []
        self._empty_text = ""
        self._columns = 0
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._scroll.setWidget(self._container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll)

        self._empty: Optional[EmptyState] = None

    def set_records(self, records: Sequence[SampleRecord], empty_text: str = "") -> None:
        self._records = list(records)
        self._empty_text = empty_text
        self._rebuild()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._records and self._columns_for_width(self.width()) != self._columns:
            self._rebuild()

    # ------------------------------------------------------------------ 内部
    def _columns_for_width(self, width: int) -> int:
        usable = max(_CHIP_MIN_WIDTH, width - 4)
        per_row = usable // (_CHIP_MIN_WIDTH + 6)
        return max(1, min(_MAX_COLUMNS, int(per_row)))

    def _rebuild(self) -> None:
        self._clear()
        if not self._records:
            # 空状态自带"开始吸色"按钮：让用户就地完成下一步，而不是回左栏找入口
            self._empty = EmptyState(
                "暂无记录", self._empty_text, glyph="◌",
                action_text="开始吸色",
                action_callback=self.pickRequested.emit,
            )
            self.layout().addWidget(self._empty)
            self._scroll.setVisible(False)
            self._columns = 0
            return
        self._scroll.setVisible(True)
        self._columns = self._columns_for_width(self.width())
        for index, record in enumerate(self._records):
            chip = _Chip(record, self._show_favorite, self._container)
            chip.selected.connect(self.colorSelected.emit)
            chip.removeRequested.connect(self.removeRequested.emit)
            chip.favoriteRequested.connect(self.favoriteRequested.emit)
            self._grid.addWidget(chip, index // self._columns, index % self._columns)
        rows = (len(self._records) + self._columns - 1) // self._columns
        # 末尾留一行弹性空间，避免行高被拉满
        self._grid.setRowStretch(rows, 1)
        self._grid.setColumnStretch(self._columns, 1)

    def _clear(self) -> None:
        while self._grid.count():
            child = self._grid.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if self._empty is not None:
            self.layout().removeWidget(self._empty)
            self._empty.setParent(None)
            self._empty.deleteLater()
            self._empty = None


class LibraryPanel(QFrame):
    """历史 + 收藏 的标签页容器。"""

    colorSelected = Signal(object)
    pickRequested = Signal()
    historyRemoved = Signal(str)
    favoriteRemoved = Signal(str)
    favoriteAdded = Signal(object)
    historyCleared = Signal()
    favoritesCleared = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._tabs = _TabWidget(self)
        layout.addWidget(self._tabs, 1)

        # 历史页
        self._history_page = QWidget()
        history_layout = QVBoxLayout(self._history_page)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(6)
        self._history_grid = ColorGrid(show_favorite=True, parent=self._history_page)
        self._history_grid.colorSelected.connect(self.colorSelected.emit)
        self._history_grid.removeRequested.connect(lambda rec: self.historyRemoved.emit(rec.uid))
        self._history_grid.favoriteRequested.connect(self.favoriteAdded.emit)
        self._history_grid.pickRequested.connect(self.pickRequested.emit)
        history_layout.addWidget(self._history_grid, 1)
        self._clear_history = QPushButton("清空历史")
        self._clear_history.setObjectName("GhostButton")
        self._clear_history.clicked.connect(self.historyCleared.emit)
        history_layout.addWidget(self._clear_history)

        # 收藏页
        self._favorite_page = QWidget()
        fav_layout = QVBoxLayout(self._favorite_page)
        fav_layout.setContentsMargins(0, 0, 0, 0)
        fav_layout.setSpacing(6)
        self._favorite_grid = ColorGrid(show_favorite=False, parent=self._favorite_page)
        self._favorite_grid.colorSelected.connect(self.colorSelected.emit)
        self._favorite_grid.removeRequested.connect(lambda rec: self.favoriteRemoved.emit(rec.uid))
        self._favorite_grid.pickRequested.connect(self.pickRequested.emit)
        fav_layout.addWidget(self._favorite_grid, 1)
        self._clear_favorites = QPushButton("清空收藏")
        self._clear_favorites.setObjectName("GhostButton")
        self._clear_favorites.clicked.connect(self.favoritesCleared.emit)
        fav_layout.addWidget(self._clear_favorites)

        self._tabs.addTab(self._history_page, "历史记录")
        self._tabs.addTab(self._favorite_page, "收藏夹")
        self._tabs.finish_tabs()

    # ------------------------------------------------------------------ 刷新
    def set_history(self, records: Sequence[SampleRecord]) -> None:
        self._history_grid.set_records(
            records, "取过的颜色会自动记在这里，点击色块可以重新载入。")

    def set_favorites(self, records: Sequence[SampleRecord]) -> None:
        self._favorite_grid.set_records(
            records, "在左侧点「收藏此色」，或在历史里点 ★，就能把常用色固定在这里。")


class _TabWidget(QFrame):
    """轻量标签页（用按钮切换，避免嵌套 QTabWidget 的样式冲突）。"""

    currentChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._buttons: List[QPushButton] = []
        self._pages: List[QWidget] = []
        self._current = 0

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

        self._bar = QFrame(self)
        self._bar_layout = QHBoxLayout(self._bar)
        self._bar_layout.setContentsMargins(0, 0, 0, 0)
        self._bar_layout.setSpacing(4)
        self._layout.addWidget(self._bar)

        self._stack = QWidget(self)
        self._stack_layout = QVBoxLayout(self._stack)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._stack, 1)

    def addTab(self, page: QWidget, label: str) -> None:  # noqa: N802
        index = len(self._pages)
        button = QPushButton(label)
        button.setCheckable(True)
        button.clicked.connect(lambda: self.setCurrentIndex(index))
        self._bar_layout.addWidget(button)
        self._buttons.append(button)
        self._pages.append(page)
        self._stack_layout.addWidget(page)
        page.setVisible(index == 0)
        if index == 0:
            button.setChecked(True)

    def finish_tabs(self) -> None:
        """标签加完后调用一次，把按钮推到左侧。"""
        self._bar_layout.addStretch(1)

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self._pages):
            return
        self._current = index
        for i, (button, page) in enumerate(zip(self._buttons, self._pages)):
            button.setChecked(i == index)
            page.setVisible(i == index)
        self.currentChanged.emit(index)

    def currentIndex(self) -> int:  # noqa: N802
        return self._current
