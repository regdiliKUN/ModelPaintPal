# -*- coding: utf-8 -*-
"""简单弹窗助手（移动端输入框 / 信息框）。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView

from ..theme import D, NAV_BG, S, hex_to_kivy
from ..widgets import AccentButton, Field, GhostButton, Txt


def text_input_dialog(app, title, hint, on_ok, current=""):
    mv = ModalView(size_hint=(0.9, None), height=D(232),
                   background_color=hex_to_kivy(NAV_BG))
    box = BoxLayout(orientation="vertical", spacing=D(10), padding=[D(16)] * 4)
    box.add_widget(Txt(text=title, font_size=S(16), bold=True))
    box.add_widget(Txt(text=hint, font_size=S(12)))
    ti = Field(text=current)
    box.add_widget(ti)

    def _ok(*a):
        mv.dismiss()
        on_ok(ti.text.strip())

    row = BoxLayout(size_hint_y=None, height=D(44), spacing=D(10))
    row.add_widget(GhostButton(text="取消", on_release=lambda *_: mv.dismiss()))
    row.add_widget(AccentButton(text="确定", on_release=_ok, height=D(44)))
    box.add_widget(row)
    mv.add_widget(box)
    mv.open()
    return mv


def info_dialog(app, title, text):
    mv = ModalView(size_hint=(0.9, None), height=D(320),
                   background_color=hex_to_kivy(NAV_BG))
    box = BoxLayout(orientation="vertical", spacing=D(10), padding=[D(16)] * 4)
    box.add_widget(Txt(text=title, font_size=S(16), bold=True))
    body = ScrollView(do_scroll_x=False, bar_width=0)
    inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=D(4))
    inner.bind(minimum_height=inner.setter("height"))
    inner.add_widget(Txt(text=text, font_size=S(13)))
    body.add_widget(inner)
    box.add_widget(body)
    box.add_widget(GhostButton(text="关闭", on_release=lambda *_: mv.dismiss()))
    mv.add_widget(box)
    mv.open()
    return mv
