# -*- coding: utf-8 -*-
"""色卡对比页：目标色与各候选漆并列展示，点按复制色值。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from ..logic import compute_suggest, copy_text, get_config
from ..theme import D, S
from ..widgets import Card, Dim, Title
from ..widgets.cards import SwatchGrid


class VisualizeScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "visualize")
        super().__init__(**kwargs)
        self.name = name
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=D(8),
                         padding=[D(14), D(10), D(14), D(8)])
        self._hint = Dim(text="先在「取色」页取一个颜色", font_size=S(13))
        root.add_widget(self._hint)
        body = ScrollView(do_scroll_x=False, bar_width=0)
        self._inner = BoxLayout(orientation="vertical", spacing=D(12), size_hint_y=None)
        self._inner.bind(minimum_height=self._inner.setter("height"))
        body.add_widget(self._inner)
        root.add_widget(body)
        self.add_widget(root)

    def _recompute(self):
        rgb = self.app.current_rgb
        if rgb is None:
            return
        self._hint.text = "对比生成中…"
        cfg = get_config()
        compute_suggest(rgb, self._on_done, brands=cfg.preferred_brands or None)

    def _on_done(self, result):
        if isinstance(result, tuple) and result and result[0] == "error":
            self._hint.text = "计算失败：" + str(result[1])
            return
        from app.core.color_models import rgb_to_hex
        self._inner.clear_widgets()
        target_hex = rgb_to_hex(self.app.current_rgb)
        items = [(target_hex, "目标色")]
        for sug in result:
            items.append((sug.anchor.hex, sug.anchor.code))
        card = Card()
        card.add_widget(Title(text="色卡对比（点按复制色值）", font_size=S(16)))
        grid = SwatchGrid(cols=3)
        grid.set_swatches(items, on_pick=self._on_pick)
        card.add_widget(grid)
        self._inner.add_widget(card)
        self._hint.text = f"目标色 vs {len(result)} 个候选漆"

    def _on_pick(self, hexv):
        copy_text(hexv)
        self.app.toast("已复制 " + hexv)

    def on_color(self, rgb):
        self._recompute()

    def on_enter(self):
        if self.app.current_rgb is not None:
            self._recompute()

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()
