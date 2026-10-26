# -*- coding: utf-8 -*-
"""关于页。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from ..logic import get_db
from ..theme import D, S
from ..widgets import Card, Dim, GhostButton, Txt, Title


class AboutScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "about")
        super().__init__(**kwargs)
        self.name = name
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=D(8),
                         padding=[D(14), D(10), D(14), D(8)])
        body = ScrollView(do_scroll_x=False, bar_width=0)
        inner = BoxLayout(orientation="vertical", spacing=D(12), size_hint_y=None)
        inner.bind(minimum_height=inner.setter("height"))

        card = Card()
        card.add_widget(Title(text="ModelPaintPal 移动端", font_size=S(18)))
        try:
            from app import __version__
            ver = __version__
        except Exception:
            ver = "1.1.0"
        db = get_db()
        card.add_widget(Txt(text=f"版本 {ver}", font_size=S(13)))
        card.add_widget(Txt(text=f"色号库 {len(db)} 条 / {len(db.brands)} 个品牌",
                            font_size=S(13)))
        card.add_widget(Dim(text="色值为基于官方色卡的屏幕近似值，用于相对匹配与配比估算；"
                                 "正式喷涂前请务必小量试喷确认。", font_size=S(12)))
        inner.add_widget(card)

        back = GhostButton(text="返回")
        back.bind(on_release=lambda *_: self.app.go_to("more"))
        inner.add_widget(back)

        body.add_widget(inner)
        root.add_widget(body)
        self.add_widget(root)

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()
