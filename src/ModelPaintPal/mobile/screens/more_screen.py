# -*- coding: utf-8 -*-
"""更多页：入口菜单（用量 / 收藏历史 / 设置 / 关于）。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen

from ..widgets import AccentButton, Txt


class MoreScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "more")
        super().__init__(**kwargs)
        self.name = name
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=12, padding=[14, 12, 14, 10])
        root.add_widget(Txt(text="更多", font_size=22, bold=True))
        items = [("用量估算", "coverage"), ("收藏与历史", "library"),
                 ("设置", "settings"), ("关于", "about")]
        for label, target in items:
            b = AccentButton(text=label, size_hint_y=None, height=54)
            b.bind(on_release=lambda inst, t=target: self.app.go_to(t))
            root.add_widget(b)
        root.add_widget(Txt(text="取色 → 找漆 → 给配比 → 估用量", font_size=13, color=(0.58, 0.63, 0.7, 1)))
        self.add_widget(root)

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()
