# -*- coding: utf-8 -*-
"""用量参数页：面积/层数/稀释/工具/表面 → 估算用漆量（含每组分）。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from ..logic import (compute_coverage, get_config,
                    save_config, set_coverage_input)
from ..theme import CARD, TEXT, hex_to_kivy
from ..widgets import Card, Dim, GhostButton, Txt, Title


class CoverageScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "coverage")
        super().__init__(**kwargs)
        self.name = name
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=8, padding=[14, 12, 14, 10])
        cfg = get_config()
        body = BoxLayout(orientation="vertical", spacing=12)

        card = Card()
        card.add_widget(Title(text="喷涂参数", font_size=16))

        self._area = TextInput(text=str(int(cfg.area_m2 * 10000)), multiline=False,
                               size_hint_y=None, height=42, input_type="number",
                               background_color=hex_to_kivy(CARD),
                               foreground_color=hex_to_kivy(TEXT), font_size=15)
        self._area.bind(on_text_validate=lambda *_: self._apply())
        card.clear_widgets()
        card.add_widget(Title(text="喷涂参数", font_size=16))

        area_row = BoxLayout(size_hint_y=None, height=42, spacing=8)
        area_row.add_widget(Dim(text="面积 cm²", size_hint_x=0.35))
        area_row.add_widget(self._area)
        card.add_widget(area_row)

        self._coats = Spinner(text=str(cfg.coats), size_hint_y=None, height=42,
                              values=[str(i) for i in range(1, 9)],
                              background_color=hex_to_kivy(CARD),
                              color=hex_to_kivy(TEXT), font_size=15)
        self._coats.bind(text=lambda *a: self._apply())
        coats_row = BoxLayout(size_hint_y=None, height=42, spacing=8)
        coats_row.add_widget(Dim(text="层数", size_hint_x=0.35))
        coats_row.add_widget(self._coats)
        card.add_widget(coats_row)

        self._thinner = TextInput(text=str(cfg.thinner_ratio), multiline=False,
                                  size_hint_y=None, height=42, input_type="number",
                                  background_color=hex_to_kivy(CARD),
                                  foreground_color=hex_to_kivy(TEXT), font_size=15)
        self._thinner.bind(on_text_validate=lambda *_: self._apply())
        thinner_row = BoxLayout(size_hint_y=None, height=42, spacing=8)
        thinner_row.add_widget(Dim(text="稀释比(漆:稀)", size_hint_x=0.35))
        thinner_row.add_widget(self._thinner)
        card.add_widget(thinner_row)

        self._app_spin = Spinner(text=cfg.application, size_hint_y=None, height=42,
                                 values=["airbrush", "spray_can", "brush"],
                                 background_color=hex_to_kivy(CARD),
                                 color=hex_to_kivy(TEXT), font_size=15)
        self._app_spin.bind(text=lambda *a: self._apply())
        app_row = BoxLayout(size_hint_y=None, height=42, spacing=8)
        app_row.add_widget(Dim(text="工具", size_hint_x=0.35))
        app_row.add_widget(self._app_spin)
        card.add_widget(app_row)

        self._surf_spin = Spinner(text=cfg.surface, size_hint_y=None, height=42,
                                  values=["primed", "raw_print", "smooth"],
                                  background_color=hex_to_kivy(CARD),
                                  color=hex_to_kivy(TEXT), font_size=15)
        self._surf_spin.bind(text=lambda *a: self._apply())
        surf_row = BoxLayout(size_hint_y=None, height=42, spacing=8)
        surf_row.add_widget(Dim(text="表面", size_hint_x=0.35))
        surf_row.add_widget(self._surf_spin)
        card.add_widget(surf_row)

        body.add_widget(card)

        self._result = Card()
        self._result.add_widget(Title(text="用量估算", font_size=16))
        self._result_text = Txt(text="—", font_size=14)
        self._result.add_widget(self._result_text)
        body.add_widget(self._result)

        back = GhostButton(text="返回", size_hint_y=None, height=44)
        back.bind(on_release=lambda *_: self.app.go_to("more"))
        body.add_widget(back)

        root.add_widget(body)
        self.add_widget(root)

    def _apply(self):
        try:
            cfg = get_config()
            cfg.area_m2 = max(0.0005, float(self._area.text or 0) / 10000.0)
            cfg.coats = int(self._coats.text)
            cfg.thinner_ratio = max(0.0, float(self._thinner.text or 0))
            cfg.application = self._app_spin.text
            cfg.surface = self._surf_spin.text
            save_config()
            inp = build_input()
            set_coverage_input(inp)
            self._show(inp)
        except (ValueError, TypeError):
            self.app.toast("参数格式不正确")

    def _show(self, inp):
        try:
            est = compute_coverage(inp)
            self._result_text.text = est.as_text()
        except Exception as exc:
            self._result_text.text = "估算失败：" + str(exc)

    def on_enter(self):
        self._apply()

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()


def build_input():
    from app.services.coverage import CoverageInput
    cfg = get_config()
    return CoverageInput(
        area_m2=cfg.area_m2, coats=cfg.coats, thinner_ratio=cfg.thinner_ratio,
        application=cfg.application, surface=cfg.surface,
        mix_ml_per_m2_per_coat=cfg.mix_ml_per_m2_per_coat,
        waste_buffer=cfg.waste_buffer, fixed_paint_loss_ml=cfg.fixed_paint_loss_ml,
    )
