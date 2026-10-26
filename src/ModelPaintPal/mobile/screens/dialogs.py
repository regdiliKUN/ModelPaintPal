# -*- coding: utf-8 -*-
"""简单弹窗助手（移动端输入框 / 信息框）。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.textinput import TextInput

from ..theme import CARD, TEXT, hex_to_kivy
from ..widgets import AccentButton, GhostButton, Txt


def text_input_dialog(app, title, hint, on_ok, current=""):
    mv = ModalView(size_hint=(0.9, None), height=230, background_color=hex_to_kivy("#0b0e14"))
    box = BoxLayout(orientation="vertical", spacing=12, padding=16)
    box.add_widget(Txt(text=title, font_size=17, bold=True))
    ti = TextInput(text=current, multiline=False, size_hint_y=None, height=44,
                   background_color=hex_to_kivy(CARD),
                   foreground_color=hex_to_kivy(TEXT), font_size=16)
    box.add_widget(ti)

    def _ok(*a):
        mv.dismiss()
        on_ok(ti.text.strip())

    row = BoxLayout(size_hint_y=None, height=44, spacing=10)
    row.add_widget(GhostButton(text="取消", on_release=lambda *_: mv.dismiss()))
    row.add_widget(AccentButton(text="确定", on_release=_ok))
    box.add_widget(row)
    mv.add_widget(box)
    mv.open()
    return mv


def info_dialog(app, title, text):
    mv = ModalView(size_hint=(0.9, None), height=300, background_color=hex_to_kivy("#0b0e14"))
    box = BoxLayout(orientation="vertical", spacing=12, padding=16)
    box.add_widget(Txt(text=title, font_size=17, bold=True))
    body = Txt(text=text, font_size=14)
    box.add_widget(body)
    box.add_widget(GhostButton(text="关闭", size_hint_y=None, height=44,
                              on_release=lambda *_: mv.dismiss()))
    mv.add_widget(box)
    mv.open()
    return mv
