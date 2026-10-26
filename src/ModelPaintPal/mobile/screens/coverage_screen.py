# -*- coding: utf-8 -*-
"""用量参数页：面积/层数/稀释/工具/表面 → 估算用漆量（含每组分）。"""

from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView

from ..logic import compute_coverage, get_config, save_config, set_coverage_input
from ..theme import CTRL_H, D, S
from ..widgets import Card, Dim, Field, GhostButton, Select, Txt, Title


class CoverageScreen(Screen):
    LABEL_W = 108  # 设计值 dp

    def __init__(self, **kwargs):
        name = kwargs.pop("name", "coverage")
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
        card.add_widget(Title(text="喷涂参数", font_size=S(16)))

        self._area = Field(text=str(int(cfg.area_m2 * 10000)), input_type="number")
        self._area.bind(on_text_validate=lambda *_: self._apply())
        card.add_widget(self._row("面积 cm²", self._area))

        self._coats = Select(text=str(cfg.coats),
                             values=[str(i) for i in range(1, 9)])
        self._coats.bind(text=lambda *a: self._apply())
        card.add_widget(self._row("层数", self._coats))

        self._thinner = Field(text=str(cfg.thinner_ratio), input_type="number")
        self._thinner.bind(on_text_validate=lambda *_: self._apply())
        card.add_widget(self._row("稀释比(漆:稀)", self._thinner))

        self._app_spin = Select(text=cfg.application,
                                values=["airbrush", "spray_can", "brush"])
        self._app_spin.bind(text=lambda *a: self._apply())
        card.add_widget(self._row("工具", self._app_spin))

        self._surf_spin = Select(text=cfg.surface,
                                 values=["primed", "raw_print", "smooth"])
        self._surf_spin.bind(text=lambda *a: self._apply())
        card.add_widget(self._row("表面", self._surf_spin))
        inner.add_widget(card)

        self._result = Card()
        self._result.add_widget(Title(text="用量估算", font_size=S(16)))
        self._result_text = Txt(text="—", font_size=S(13))
        self._result.add_widget(self._result_text)
        inner.add_widget(self._result)

        back = GhostButton(text="返回")
        back.bind(on_release=lambda *_: self.app.go_to("more"))
        inner.add_widget(back)

        body.add_widget(inner)
        root.add_widget(body)
        self.add_widget(root)

    def _row(self, label, control) -> BoxLayout:
        row = BoxLayout(size_hint_y=None, height=D(CTRL_H), spacing=D(8))
        row.add_widget(Dim(text=label, size_hint_x=None, width=D(self.LABEL_W),
                           font_size=S(13)))
        row.add_widget(control)
        return row

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
