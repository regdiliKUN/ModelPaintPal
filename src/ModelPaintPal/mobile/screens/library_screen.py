# -*- coding: utf-8 -*-
"""收藏 / 历史页。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from ..logic import (clear_favorites, clear_history, get_favorites, get_history,
                    remove_favorite, remove_history)
from ..theme import CARD, hex_to_kivy
from ..widgets import ColorRect, Dim, GhostButton, Txt, Title


class LibraryScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "library")
        super().__init__(**kwargs)
        self.name = name
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=8, padding=[14, 12, 14, 10])
        bar = BoxLayout(size_hint_y=None, height=44, spacing=8)
        bar.add_widget(Txt(text="收藏与历史", font_size=18, bold=True, size_hint_x=0.5))
        cf = GhostButton(text="清空收藏", size_hint_x=0.25)
        ch = GhostButton(text="清空历史", size_hint_x=0.25)
        cf.bind(on_release=lambda *_: (clear_favorites(), self.refresh(), self.app.toast("已清空收藏")))
        ch.bind(on_release=lambda *_: (clear_history(), self.refresh(), self.app.toast("已清空历史")))
        bar.add_widget(cf)
        bar.add_widget(ch)
        root.add_widget(bar)

        body = ScrollView()
        self._inner = BoxLayout(orientation="vertical", spacing=16, size_hint_y=None)
        self._inner.bind(minimum_height=self._inner.setter("height"))
        body.add_widget(self._inner)
        root.add_widget(body)
        self.add_widget(root)

    def refresh(self):
        self._inner.clear_widgets()
        self._add_section("收藏", get_favorites().all(), remove_favorite, "fav")
        self._add_section("历史", get_history().recent(60), remove_history, "his")

    def _add_section(self, title, items, remove_fn, tag):
        card = TitleCard(title)
        if not items:
            card.add_widget(Dim(text="（空）", font_size=13))
        for rec in items:
            row = BoxLayout(size_hint_y=None, height=44, spacing=10)
            rgb = tuple(int(v) for v in rec.rgb)
            sw = ColorRect(size_hint=(None, None), size=(32, 32), radius=[6])
            sw.color = hex_to_kivy(rec.hex)
            row.add_widget(sw)
            col = BoxLayout(orientation="vertical", spacing=0)
            col.add_widget(Txt(text=rec.hex, font_size=14))
            col.add_widget(Dim(text=rec.source or "", font_size=11))
            row.add_widget(col)
            load = GhostButton(text="载入", size_hint_x=0.22, height=36)
            rem = GhostButton(text="删除", size_hint_x=0.22, height=36)
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


class TitleCard(BoxLayout):
    def __init__(self, title, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", 8)
        super().__init__(**kwargs)
        from ..theme import PAD
        self.padding = [PAD, PAD, PAD, PAD]
        from kivy.graphics import Color, RoundedRectangle
        with self.canvas.before:
            Color(*hex_to_kivy(CARD))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[14])
        self.bind(pos=self._upd, size=self._upd)
        self.add_widget(Title(text=title, font_size=16))

    def _upd(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size
