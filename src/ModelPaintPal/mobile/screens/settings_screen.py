# -*- coding: utf-8 -*-
"""设置页：容差 / 条数 / 组分数 / 调色模型 / 重置引导。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner

from ..logic import get_config, save_config
from ..theme import CARD, TEXT, hex_to_kivy
from ..widgets import Card, Dim, GhostButton, Txt, Title


class SettingsScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "settings")
        super().__init__(**kwargs)
        self.name = name
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=8, padding=[14, 12, 14, 10])
        cfg = get_config()
        body = BoxLayout(orientation="vertical", spacing=12)

        card = Card()
        card.add_widget(Title(text="配色参数", font_size=16))

        # 容差
        card.add_widget(Dim(text="匹配容差（ΔE）", font_size=13))
        self._tol = Slider(min=0.5, max=10.0, value=cfg.match_tolerance, step=0.1)
        self._tol.bind(value=lambda v, *a: self._set_tol(v.value))
        card.add_widget(self._tol)
        self._tol_label = Txt(text=f"当前：{cfg.match_tolerance:.1f}", font_size=13)
        card.add_widget(self._tol_label)

        # 建议条数
        card.add_widget(Dim(text="建议条数", font_size=13))
        self._cnt = Spinner(text=str(cfg.max_suggestions), size_hint_y=None, height=42,
                            values=[str(i) for i in range(3, 13)],
                            background_color=hex_to_kivy(CARD),
                            color=hex_to_kivy(TEXT), font_size=15)
        self._cnt.bind(text=lambda s, *a: self._set_cnt(s.text))
        card.add_widget(self._cnt)

        # 配方组分数
        card.add_widget(Dim(text="配方最多组分数", font_size=13))
        self._comp = Spinner(text=str(cfg.max_recipe_components), size_hint_y=None, height=42,
                             values=[str(i) for i in range(1, 5)],
                             background_color=hex_to_kivy(CARD),
                             color=hex_to_kivy(TEXT), font_size=15)
        self._comp.bind(text=lambda s, *a: self._set_comp(s.text))
        card.add_widget(self._comp)

        # 调色模型
        card.add_widget(Dim(text="调色模型", font_size=13))
        self._model = Spinner(text=cfg.mixing_model, size_hint_y=None, height=42,
                              values=["kubelka_munk", "linear_rgb"],
                              background_color=hex_to_kivy(CARD),
                              color=hex_to_kivy(TEXT), font_size=15)
        self._model.bind(text=lambda s, *a: self._set_model(s.text))
        card.add_widget(self._model)
        body.add_widget(card)

        card2 = Card()
        card2.add_widget(Title(text="其它", font_size=16))
        reset = GhostButton(text="重置新手引导", size_hint_y=None, height=44)
        reset.bind(on_release=lambda *_: self._reset_onboarding())
        card2.add_widget(reset)
        body.add_widget(card2)

        back = GhostButton(text="返回", size_hint_y=None, height=44)
        back.bind(on_release=lambda *_: self.app.go_to("more"))
        body.add_widget(back)

        root.add_widget(body)
        self.add_widget(root)

    def _set_tol(self, v):
        cfg = get_config()
        cfg.match_tolerance = float(v)
        self._tol_label.text = f"当前：{cfg.match_tolerance:.1f}"
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
