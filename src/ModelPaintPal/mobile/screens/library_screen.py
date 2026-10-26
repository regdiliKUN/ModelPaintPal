# -*- coding: utf-8 -*-
"""收藏 / 历史页。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from ..logic import (clear_favorites, clear_history, get_favorites, get_history,
                     remove_favorite, remove_history)
from ..theme import D, S, hex_to_kivy
from ..widgets import Card, ColorRect, Dim, GhostButton, Txt, Title


class LibraryScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "library")
        super().__init__(**kwargs)
        self.name = name
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=D(8),
                         padding=[D(14), D(10), D(14), D(8)])
        root.add_widget(Title(text="收藏与历史", font_size=S(19)))

        body = ScrollView(do_scroll_x=False, bar_width=0)
        self._inner = BoxLayout(orientation="vertical", spacing=D(12), size_hint_y=None)
        self._inner.bind(minimum_height=self._inner.setter("height"))
        body.add_widget(self._inner)
        root.add_widget(body)
        self.add_widget(root)

    def refresh(self):
        if not self._inner:
            return
        self._inner.clear_widgets()
        self._add_section("收藏", get_favorites().all(), remove_favorite,
                          lambda: (clear_favorites(), self.refresh()))
        self._add_section("历史", get_history().recent(60), remove_history,
                          lambda: (clear_history(), self.refresh()))

    def _add_section(self, title, items, remove_fn, on_clear):
        card = Card()
        head = BoxLayout(size_hint_y=None, height=D(36), spacing=D(8))
        head.add_widget(Txt(text=title, font_size=S(16), bold=True))
        clr = GhostButton(text="清空", size_hint_x=None, width=D(64), height=D(34),
                          font_size=S(12))
        clr.bind(on_release=lambda *_: on_clear())
        head.add_widget(clr)
        card.add_widget(head)

        if not items:
            card.add_widget(Dim(text="（空）", font_size=S(12)))
        for rec in items:
            row = BoxLayout(size_hint_y=None, height=D(48), spacing=D(10))
            rgb = tuple(int(v) for v in rec.rgb)
            sw = ColorRect(size_hint=(None, None), size=(D(32), D(32)), radius=[D(6)])
            sw.color = hex_to_kivy(rec.hex)
            row.add_widget(sw)
            col = BoxLayout(orientation="vertical", spacing=D(2))
            col.add_widget(Txt(text=rec.hex, font_size=S(13)))
            col.add_widget(Dim(text=rec.source or "", font_size=S(11)))
            row.add_widget(col)
            load = GhostButton(text="载入", size_hint_x=None, width=D(58), height=D(34),
                               font_size=S(12))
            rem = GhostButton(text="删除", size_hint_x=None, width=D(58), height=D(34),
                              font_size=S(12))
            uid = rec.uid
            load.bind(on_release=lambda *_: self._load(rgb))
            rem.bind(on_release=lambda *_: (remove_fn(uid), self.refresh()))
            row.add_widget(load)
            row.add_widget(rem)
            card.add_widget(row)
        self._inner.add_widget(card)

    def _load(self, rgb):
        self.app.color_set(rgb, source="manual")
        self.app.go_to("pick")
        self.app.toast("已载入颜色")

    def on_enter(self):
        self.refresh()

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()
