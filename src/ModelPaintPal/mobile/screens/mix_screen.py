# -*- coding: utf-8 -*-
"""基础漆调配页：把目标色分解为红/黄/蓝/白/黑五瓶的配比（比例条 + 滴数）。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.spinner import Spinner
from kivy.uix.scrollview import ScrollView

from ..logic import (compute_mix, get_config, set_drop_total,
                    set_mix_brands)
from ..theme import (BASE_COLORS, CARD, TEXT, hex_to_kivy)
from ..widgets import (Card, Dim, Txt, Title)
from ..widgets.cards import MixRatioBar


class MixScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "mix")
        super().__init__(**kwargs)
        self.name = name
        self._recipe = None
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=8, padding=[14, 12, 14, 10])
        bar = BoxLayout(size_hint_y=None, height=44, spacing=8)
        cfg = get_config()
        self._brand_spin = Spinner(text="混搭（全部品牌）", size_hint_x=0.6, font_size=14,
                                  background_color=hex_to_kivy(CARD),
                                  color=hex_to_kivy(TEXT))
        brands = list(get_brands().items())
        self._brand_map = {"混搭（全部品牌）": []}
        opts = ["混搭（全部品牌）", "单品牌：田宫"]
        # 提供田宫作为常见默认单品牌，外加全部品牌可选
        self._brand_map["单品牌：田宫"] = ["tamiya"]
        for key, b in brands:
            if key == "tamiya":
                continue
            self._brand_map[f"单品牌：{b.short}"] = [key]
            opts.append(f"单品牌：{b.short}")
        self._brand_spin.values = opts
        self._brand_spin.bind(text=self._on_brand)
        self._drops_spin = Spinner(text=f"总滴数 {cfg.drop_total}", size_hint_x=0.4,
                                   font_size=14, background_color=hex_to_kivy(CARD),
                                   color=hex_to_kivy(TEXT))
        self._drops_spin.values = [f"总滴数 {n}" for n in (10, 15, 20, 30, 40, 50)]
        self._drops_spin.bind(text=self._on_drops)
        bar.add_widget(self._brand_spin)
        bar.add_widget(self._drops_spin)
        root.add_widget(bar)

        self._hint = Dim(text="先在「取色」页取一个颜色", font_size=14, size_hint_y=None, height=30)
        root.add_widget(self._hint)

        body = ScrollView()
        self._inner = BoxLayout(orientation="vertical", spacing=12, size_hint_y=None)
        self._inner.bind(minimum_height=self._inner.setter("height"))
        body.add_widget(self._inner)
        root.add_widget(body)
        self.add_widget(root)

    def _on_brand(self, spin, text):
        set_mix_brands(self._brand_map.get(text, []))
        self._recompute()

    def _on_drops(self, spin, text):
        n = int(text.replace("总滴数 ", "").strip())
        set_drop_total(n)
        self._recompute()

    def _recompute(self):
        rgb = self.app.current_rgb
        if rgb is None:
            return
        cfg = get_config()
        brands = self._brand_map.get(self._brand_spin.text, [])
        self._hint.text = "计算中…"
        compute_mix(rgb, self._on_done, brands=brands, total_drops=cfg.drop_total)

    def _on_done(self, result):
        if isinstance(result, tuple) and result and result[0] == "error":
            self._hint.text = "计算失败：" + str(result[1])
            self.app.toast("计算失败")
            return
        self._recipe = result
        self._render()

    def _render(self):
        self._inner.clear_widgets()
        r = self._recipe
        self._hint.text = (f"用五瓶基础漆调出目标色（近似 ΔE {r.delta_e:.1f}）")
        # 比例条
        bar_card = Card()
        bar_card.add_widget(Title(text="混色比例", font_size=16))
        self._bar = MixRatioBar()
        segs = []
        for c in r.components:
            segs.append((c.role, BASE_COLORS.get(c.role, "#888888"), c.percent))
        self._bar.segments = segs
        bar_card.add_widget(self._bar)
        # 预测色 vs 目标色
        cmp_row = BoxLayout(size_hint_y=None, height=46, spacing=12)
        from ..widgets import ColorRect
        tg = ColorRect(size_hint=(None, None), size=(40, 40), radius=[8])
        tg.color = hex_to_kivy(rgb_to_hex(r.target_rgb))
        pr = ColorRect(size_hint=(None, None), size=(40, 40), radius=[8])
        pr.color = hex_to_kivy(rgb_to_hex(r.predicted_rgb))
        cmp_row.add_widget(Txt(text="目标", size_hint_x=0.2))
        cmp_row.add_widget(tg)
        cmp_row.add_widget(Txt(text="预测", size_hint_x=0.2))
        cmp_row.add_widget(pr)
        bar_card.add_widget(cmp_row)
        self._inner.add_widget(bar_card)

        # 各基础漆推荐真实漆
        for c in r.components:
            card = Card()
            card.add_widget(Title(text=f"{c.role} · {c.percent:.1f}% · {c.drops} 滴",
                                 font_size=15))
            sug = c.suggestion
            if sug is not None:
                a = sug.anchor
                card.add_widget(Txt(text=f"推荐：{a.brand_label} {a.code} {a.name} "
                                         f"（{a.hex}）", font_size=14))
                card.add_widget(Dim(text=f"ΔE {sug.delta_e:.2f} · {sug.mode_label}",
                                   font_size=13))
            else:
                card.add_widget(Dim(text="当前品牌范围暂无匹配", font_size=13))
            self._inner.add_widget(card)

    def on_color(self, rgb):
        self._recompute()

    def on_enter(self):
        if self.app.current_rgb is not None and self._recipe is None:
            self._recompute()

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()


def get_brands():
    from ..logic import brands as _brands
    return _brands()


def rgb_to_hex(rgb):
    from app.core.color_models import rgb_to_hex as _f
    return _f(rgb)
