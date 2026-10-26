# -*- coding: utf-8 -*-
"""配色建议页：列出与目标色最接近的漆（含配方/缓冲区/校准/核实）。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from ..logic import (compute_suggest, copy_text, get_config, run_verify,
                     save_config, share_text)
from ..theme import CTRL_H, D, S
from ..widgets import AccentButton, Dim, Select
from ..widgets.cards import SuggestionCard
from .dialogs import info_dialog, text_input_dialog


class SuggestScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "suggest")
        super().__init__(**kwargs)
        self.name = name
        self._suggestions = []
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=D(8),
                         padding=[D(14), D(10), D(14), D(8)])
        # 工具条
        bar = BoxLayout(size_hint_y=None, height=D(CTRL_H), spacing=D(8))
        cfg = get_config()
        self._brand_spin = Select(text="全部品牌", size_hint_x=0.46)
        brands = list(get_brands().items())
        self._brand_map = {"全部品牌": []}
        opts = ["全部品牌"]
        for key, b in brands:
            self._brand_map[b.short] = [key]
            opts.append(b.short)
        self._brand_spin.values = opts
        self._brand_spin.bind(text=self._on_brand)

        self._formula_spin = Select(text=cfg.delta_e_formula, size_hint_x=0.32)
        self._formula_spin.values = ["CIEDE2000", "CIE94", "CIE76", "CMC"]
        self._formula_spin.bind(text=self._on_formula)

        share_b = AccentButton(text="分享", size_hint_x=0.22, font_size=S(13))
        share_b.bind(on_release=lambda *_: self._share())
        bar.add_widget(self._brand_spin)
        bar.add_widget(self._formula_spin)
        bar.add_widget(share_b)
        root.add_widget(bar)

        self._hint = Dim(text="先在「取色」页取一个颜色", font_size=S(13))
        root.add_widget(self._hint)

        body = ScrollView(do_scroll_x=False, bar_width=0)
        self._list = BoxLayout(orientation="vertical", spacing=D(12), size_hint_y=None)
        self._list.bind(minimum_height=self._list.setter("height"))
        body.add_widget(self._list)
        root.add_widget(body)
        self.add_widget(root)

    def _on_brand(self, spin, text):
        self._recompute()

    def _on_formula(self, spin, text):
        cfg = get_config()
        cfg.delta_e_formula = text
        save_config()
        self._recompute()

    def _recompute(self):
        rgb = self.app.current_rgb
        if rgb is None:
            return
        brands = self._brand_map.get(self._brand_spin.text, [])
        self._hint.text = "计算中…"
        compute_suggest(rgb, self._on_done, brands=brands)

    def _on_done(self, result):
        if isinstance(result, tuple) and result and result[0] == "error":
            self._hint.text = "计算失败：" + str(result[1])
            self.app.toast("计算失败")
            return
        self._suggestions = result
        self._render()

    def _render(self):
        self._list.clear_widgets()
        if not self._suggestions:
            self._hint.text = "没有找到可用建议，换个品牌范围试试"
            return
        self._hint.text = f"共 {len(self._suggestions)} 条建议"
        target = getattr(self.app, "current_hex", "") if self.app.current_rgb else ""
        for sug in self._suggestions:
            card = SuggestionCard(suggestion=sug, target_hex=target)
            card.on_action = self._on_action
            card.on_toast = self.app.toast
            self._list.add_widget(card)

    def _on_action(self, suggestion, action):
        if action == "calibrate":
            self._calibrate(suggestion)
        elif action == "verify":
            self._verify(suggestion)

    def _calibrate(self, suggestion):
        anchor = suggestion.anchor
        text_input_dialog(self.app, f"校准 {anchor.full_label} {anchor.name}",
                          "输入实测色值 #RRGGBB",
                          lambda val: self._do_calibrate(anchor, val),
                          current=anchor.hex)

    def _do_calibrate(self, anchor, val):
        from ..logic import calibrate
        if calibrate(anchor.uid, val):
            self.app.toast(f"已校准 {anchor.code} → {val.upper()}")
            self._recompute()
        else:
            self.app.toast("色值格式不正确")

    def _verify(self, suggestion):
        anchor = suggestion.anchor
        self.app.toast("核实中…")
        run_verify(anchor, lambda rep: self._on_verify(anchor, rep))

    def _on_verify(self, anchor, report):
        if isinstance(report, tuple) and report and report[0] == "error":
            info_dialog(self.app, "核实失败", str(report[1]))
            return
        hits = getattr(report, "hits", []) or []
        lines = [f"{anchor.full_label} {anchor.name}", ""]
        for hit in hits:
            if hit.hex:
                lines.append(f"{hit.name}：{hit.status_label} #{hit.hex}"
                             + (f" ΔE {hit.delta_e:.1f}" if hit.delta_e is not None else ""))
            else:
                lines.append(f"{hit.name}：{hit.status_label}")
        info_dialog(self.app, "联网核实", "\n".join(lines) or "无结果")

    def _share(self):
        if not self._suggestions or self.app.current_rgb is None:
            self.app.toast("还没有建议可分享")
            return
        text = share_text(self._suggestions, self.app.current_rgb)
        if copy_text(text):
            self.app.toast("分享文本已复制")

    def on_color(self, rgb):
        self._recompute()

    def on_enter(self):
        if self.app.current_rgb is not None and not self._suggestions:
            self._recompute()

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()


def get_brands():
    from ..logic import brands as _brands
    return _brands()
