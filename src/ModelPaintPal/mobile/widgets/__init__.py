# -*- coding: utf-8 -*-
"""移动端通用控件。"""

from __future__ import annotations

from kivy.graphics import Color, RoundedRectangle
from kivy.properties import ColorProperty, ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from ..theme import (BG_ALT, CARD, TEXT, TEXT_DIM, hex_to_kivy, PAD)


# ----------------------------------------------------------------- 底色卡片
class Card(BoxLayout):
    """带圆角底色的卡片容器。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        super().__init__(**kwargs)
        self.padding = [PAD, PAD, PAD, PAD]
        self.spacing = 8
        with self.canvas.before:
            Color(*hex_to_kivy(CARD))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[14])
        self.bind(pos=self._update_bg, size=self._update_bg)

    def _update_bg(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size


# ----------------------------------------------------------------- 纯色块
class ColorRect(Widget):
    """填充整个区域的纯色块（可选圆角）。"""

    color = ColorProperty(hex_to_kivy("#888888"))
    radius = ListProperty([0])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            Color(*self.color)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)
        self.bind(pos=self._upd, size=self._upd, color=self._upd_color)

    def _upd(self, *args):
        self._r.pos = self.pos
        self._r.size = self.size
        self._r.radius = self.radius

    def _upd_color(self, *args):
        self.canvas.clear()
        with self.canvas:
            Color(*self.color)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)


# ----------------------------------------------------------------- 文本
class Txt(Label):
    def __init__(self, **kwargs):
        kwargs.setdefault("color", hex_to_kivy(TEXT))
        kwargs.setdefault("font_size", 16)
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        kwargs.setdefault("text_size", (None, None))
        kwargs.setdefault("markup", False)
        super().__init__(**kwargs)
        self.bind(size=self._ret)
        self.text_size = (self.width, None)

    def _ret(self, *a):
        if self.halign in ("left", "right"):
            self.text_size = (self.width, None)


class Dim(Txt):
    def __init__(self, **kwargs):
        kwargs.setdefault("color", hex_to_kivy(TEXT_DIM))
        kwargs.setdefault("font_size", 13)
        super().__init__(**kwargs)


class Title(Txt):
    def __init__(self, **kwargs):
        kwargs.setdefault("font_size", 22)
        kwargs.setdefault("bold", True)
        super().__init__(**kwargs)


# ----------------------------------------------------------------- 按钮
class AccentButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_color", hex_to_kivy("#2f6fd0"))
        kwargs.setdefault("color", hex_to_kivy("#ffffff"))
        kwargs.setdefault("font_size", 16)
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", 48)
        kwargs.setdefault("background_normal", "")
        super().__init__(**kwargs)


class GhostButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_color", hex_to_kivy(BG_ALT))
        kwargs.setdefault("color", hex_to_kivy(TEXT))
        kwargs.setdefault("font_size", 15)
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", 44)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("border", (0, 0, 0, 0))
        super().__init__(**kwargs)


class OutlineButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_color", hex_to_kivy(CARD))
        kwargs.setdefault("color", hex_to_kivy(TEXT))
        kwargs.setdefault("font_size", 15)
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", 44)
        kwargs.setdefault("background_normal", "")
        super().__init__(**kwargs)


# ----------------------------------------------------------------- 信息行
class InfoRow(BoxLayout):
    def __init__(self, label: str = "", value: str = "", **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", 30)
        kwargs.setdefault("spacing", 8)
        super().__init__(**kwargs)
        self._k = Txt(text=label, size_hint_x=0.42, font_size=14, color=hex_to_kivy(TEXT_DIM))
        self._v = Txt(text=value, font_size=14)
        self.add_widget(self._k)
        self.add_widget(self._v)

    def set(self, label: str = None, value: str = None):
        if label is not None:
            self._k.text = label
        if value is not None:
            self._v.text = value


from .cards import MixRatioBar, SuggestionCard, SwatchGrid  # noqa: E402,F401

__all__ = [
    "Card", "ColorRect", "Txt", "Dim", "Title",
    "AccentButton", "GhostButton", "OutlineButton", "InfoRow",
    "MixRatioBar", "SuggestionCard", "SwatchGrid",
]
