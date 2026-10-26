# -*- coding: utf-8 -*-
"""设置页：容差 / 条数 / 组分数 / 调色模型 / 重置引导。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from ..logic import get_config, save_config
from ..theme import D, S
from ..widgets import Card, Dim, GhostButton, Select, Title


class SettingsScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "settings")
        super().__init__(**kwargs)
        self.name = name
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=D(8),
                         padding=[D(14), D(10), D(14), D(8)])
        body = ScrollView(do_scroll_x=False, bar_width=0)
        inner = BoxLayout(orientation="vertical", spacing=D(12), size_hint_y=None)
        inner.bind(minimum_height=inner.setter("height"))

        cfg = get_config()
        card = Card()
        card.add_widget(Title(text="配色参数", font_size=S(16)))

        card.add_widget(Dim(text=f"匹配容差（ΔE）：{cfg.match_tolerance:.1f}",
                            font_size=S(13)))
        self._tol = Slider(min=0.5, max=10.0, value=cfg.match_tolerance, step=0.1,
                           size_hint_y=None, height=D(40))
        self._tol.bind(value=self._on_tol)
        card.add_widget(self._tol)

        card.add_widget(Dim(text="建议条数", font_size=S(13)))
        self._cnt = Select(text=str(cfg.max_suggestions),
                           values=[str(i) for i in range(3, 13)])
        self._cnt.bind(text=lambda s, *a: self._set_cnt(s.text))
        card.add_widget(self._cnt)

        card.add_widget(Dim(text="配方最多组分数", font_size=S(13)))
        self._comp = Select(text=str(cfg.max_recipe_components),
                            values=[str(i) for i in range(1, 5)])
        self._comp.bind(text=lambda s, *a: self._set_comp(s.text))
        card.add_widget(self._comp)

        card.add_widget(Dim(text="调色模型", font_size=S(13)))
        self._model = Select(text=cfg.mixing_model,
                             values=["kubelka_munk", "linear_rgb"])
        self._model.bind(text=lambda s, *a: self._set_model(s.text))
        card.add_widget(self._model)
        inner.add_widget(card)

        card2 = Card()
        card2.add_widget(Title(text="其它", font_size=S(16)))
        reset = GhostButton(text="重置新手引导")
        reset.bind(on_release=lambda *_: self._reset_onboarding())
        card2.add_widget(reset)
        inner.add_widget(card2)

        back = GhostButton(text="返回")
        back.bind(on_release=lambda *_: self.app.go_to("more"))
        inner.add_widget(back)

        body.add_widget(inner)
        root.add_widget(body)
        self.add_widget(root)

    def _on_tol(self, slider, value):
        cfg = get_config()
        cfg.match_tolerance = float(value)
        save_config()

    def _set_cnt(self, v):
        get_config().max_suggestions = int(v)
        save_config()

    def _set_comp(self, v):
        get_config().max_recipe_components = int(v)
        save_config()

    def _set_model(self, v):
        get_config().mixing_model = v
        save_config()

    def _reset_onboarding(self):
        get_config().show_onboarding = True
        save_config()
        self.app.toast("已重置，下次启动显示引导")

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()
