# -*- coding: utf-8 -*-
"""移动端通用控件（尺寸全部按 dp / sp 自适应）。"""

from __future__ import annotations

from kivy.graphics import Color, RoundedRectangle
from kivy.properties import ColorProperty, ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from ..theme import (ACCENT, BG_ALT, BTN, CARD, CARD_HI, CTRL_H, D, FONT, FS_BODY,
                     FS_SMALL, PAD, RADIUS, ROW_H, S, TEXT, TEXT_DIM, hex_to_kivy)


# ----------------------------------------------------------------- 底色卡片
class Card(BoxLayout):
    """圆角底色卡片。

    高度随内容自适应（``size_hint_y=None`` + ``minimum_height``），
    因此可以安全地放进 ``ScrollView`` 的纵向容器里——
    固定高度的卡片在滚动容器中会把整页压扁。
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("padding", [D(PAD)] * 4)
        kwargs.setdefault("spacing", D(8))
        super().__init__(**kwargs)
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(*hex_to_kivy(CARD))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size,
                                        radius=[D(RADIUS)])
        self.bind(pos=self._update_bg, size=self._update_bg)

    def _update_bg(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._bg.radius = [D(RADIUS)]


# ----------------------------------------------------------------- 纯色块
class ColorRect(Widget):
    """填充整个区域的纯色块（可选圆角）。

    绘图指令只创建一次，颜色/位置/尺寸变化时仅更新属性——
    在绑定回调里 ``canvas.clear()`` 重建指令会破坏 Kivy 的渲染上下文栈，
    导致 ``RenderContext.pop_state`` 越界崩溃。
    """

    color = ColorProperty(hex_to_kivy("#888888"))
    radius = ListProperty([0])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            self._fill = Color(*self.color)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                          radius=self.radius)
        self.bind(pos=self._upd, size=self._upd, color=self._upd_color,
                  radius=self._upd)

    def _upd(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._rect.radius = self.radius

    def _upd_color(self, *args):
        self._fill.rgba = self.color


# ----------------------------------------------------------------- 文本
class Txt(Label):
    """自动换行 + 自动高度的文本（默认 15sp）。

    高度跟随 ``texture_size``，这样放进纵向布局时不会被默认的 100px 高度撑开，
    也不会因为父容器高度不足而被裁掉。
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("color", hex_to_kivy(TEXT))
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", S(FS_BODY))
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("markup", False)
        super().__init__(**kwargs)
        self.bind(width=self._on_width, texture_size=self._on_texture)
        self._on_width()

    def _on_width(self, *args):
        self.text_size = (max(self.width, 1.0), None)

    def _on_texture(self, *args):
        self.height = max(self.texture_size[1], self.font_size * 1.3)


class Dim(Txt):
    def __init__(self, **kwargs):
        kwargs.setdefault("color", hex_to_kivy(TEXT_DIM))
        kwargs.setdefault("font_size", S(FS_SMALL))
        super().__init__(**kwargs)


class Title(Txt):
    def __init__(self, **kwargs):
        kwargs.setdefault("font_size", S(FS_BODY + 1))
        kwargs.setdefault("bold", True)
        super().__init__(**kwargs)


# ----------------------------------------------------------------- 按钮
class AccentButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_color", hex_to_kivy(BTN))
        kwargs.setdefault("color", hex_to_kivy("#ffffff"))
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", S(FS_BODY))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", D(48))
        kwargs.setdefault("background_normal", "")
        super().__init__(**kwargs)


class GhostButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_color", hex_to_kivy(BG_ALT))
        kwargs.setdefault("color", hex_to_kivy(TEXT))
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", S(FS_BODY - 1))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", D(44))
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("border", (0, 0, 0, 0))
        super().__init__(**kwargs)


class OutlineButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_color", hex_to_kivy(CARD))
        kwargs.setdefault("color", hex_to_kivy(TEXT))
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", S(FS_BODY - 1))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", D(44))
        kwargs.setdefault("background_normal", "")
        super().__init__(**kwargs)


# ----------------------------------------------------------------- 表单控件
class Select(Spinner):
    """统一样式的下拉选择。

    Spinner 默认带九宫格底图（``background_normal``），会盖掉 ``background_color``，
    在深色卡片上看起来就是一个黑块，这里关掉底图。
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", hex_to_kivy(CARD_HI))
        kwargs.setdefault("color", hex_to_kivy(TEXT))
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", S(FS_BODY - 1))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", D(CTRL_H))
        super().__init__(**kwargs)


class Field(TextInput):
    """统一样式的单行输入框。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("background_color", hex_to_kivy(CARD_HI))
        kwargs.setdefault("foreground_color", hex_to_kivy(TEXT))
        kwargs.setdefault("cursor_color", hex_to_kivy(ACCENT))
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", S(FS_BODY - 1))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", D(CTRL_H))
        kwargs.setdefault("padding", [D(10), D(10)])
        super().__init__(**kwargs)


# ----------------------------------------------------------------- 信息行
class InfoRow(BoxLayout):
    def __init__(self, label: str = "", value: str = "", **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", D(ROW_H))
        kwargs.setdefault("spacing", D(8))
        super().__init__(**kwargs)
        self._k = Txt(text=label, size_hint_x=0.42, font_size=S(FS_BODY - 1),
                      color=hex_to_kivy(TEXT_DIM))
        self._v = Txt(text=value, font_size=S(FS_BODY - 1))
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
    "Select", "Field",
    "MixRatioBar", "SuggestionCard", "SwatchGrid",
]
