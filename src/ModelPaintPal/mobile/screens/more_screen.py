# -*- coding: utf-8 -*-
"""更多页：入口菜单（用量 / 收藏历史 / 设置 / 关于）。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from ..theme import D, S, TEXT_DIM, hex_to_kivy
from ..widgets import Dim, OutlineButton, Title


class MoreScreen(Screen):
    ITEMS = [("用量估算", "coverage"), ("收藏与历史", "library"),
             ("设置", "settings"), ("关于", "about")]

    def __init__(self, **kwargs):
        name = kwargs.pop("name", "more")
        super().__init__(**kwargs)
        self.name = name
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=D(10),
                         padding=[D(14), D(12), D(14), D(10)])
        root.add_widget(Title(text="更多", font_size=S(22)))

        body = ScrollView(do_scroll_x=False, bar_width=0)
        inner = BoxLayout(orientation="vertical", spacing=D(10), size_hint_y=None)
        inner.bind(minimum_height=inner.setter("height"))

        for label, target in self.ITEMS:
            b = OutlineButton(text=label, height=D(54))
            b.bind(on_release=lambda inst, t=target: self.app.go_to(t))
            inner.add_widget(b)

        inner.add_widget(Dim(text="取色 → 找漆 → 给配比 → 估用量",
                             font_size=S(12), color=hex_to_kivy(TEXT_DIM)))
        body.add_widget(inner)
        root.add_widget(body)
        self.add_widget(root)

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()
