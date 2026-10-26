# -*- coding: utf-8 -*-
"""较复杂的展示控件：徽标、建议卡片、混色比例条、色卡网格。"""

from __future__ import annotations

from kivy.graphics import Color, RoundedRectangle
from kivy.properties import ColorProperty, ListProperty, ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.relativelayout import RelativeLayout

from ..logic import copy_text, recipe_text
from ..theme import (ACCENT_2, DANGER, TEXT, WARN, hex_to_kivy)
from . import Card, ColorRect, Dim, GhostButton, Txt


# ----------------------------------------------------------------- 徽标（带圆角底色）
class Badge(Label):
    bg = ColorProperty(hex_to_kivy(ACCENT_2))

    def __init__(self, **kwargs):
        kwargs.setdefault("color", hex_to_kivy("#ffffff"))
        kwargs.setdefault("font_size", 12)
        kwargs.setdefault("bold", True)
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (66, 26))
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw, bg=self._redraw)

    def _redraw(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*self.bg)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[6])


# ----------------------------------------------------------------- 混色比例条
class MixRatioBar(BoxLayout):
    """同一条混色比例条：红/黄/蓝/白/黑按百分比分段。"""

    segments = ListProperty([])  # [(role, hex, percent), ...]

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", 46)
        kwargs.setdefault("spacing", 2)
        super().__init__(**kwargs)
        self.bind(segments=self._rebuild)
        self._rebuild()

    def _rebuild(self, *args):
        self.clear_widgets()
        for role, hexv, percent in self.segments:
            if percent <= 0.01:
                continue
            seg = RelativeLayout(size_hint_x=max(percent, 2.0))
            col = hex_to_kivy(hexv)
            txt_color = (0, 0, 0, 1) if hexv.lower() in ("#ffffff", "#fff") else (1, 1, 1, 1)

            def redraw(seg=seg, col=col, *a):
                seg.canvas.before.clear()
                with seg.canvas.before:
                    Color(*col)
                    RoundedRectangle(pos=seg.pos, size=seg.size, radius=[4])

            seg.bind(pos=redraw, size=redraw)
            lab = Label(text=f"{role}\n{percent:.0f}%", color=txt_color,
                        font_size=12, halign="center", valign="middle")
            seg.add_widget(lab)
            redraw(seg)
            self.add_widget(seg)


# ----------------------------------------------------------------- 建议卡片
class SuggestionCard(Card):
    suggestion = ObjectProperty(None, allownone=True)
    target_hex = StringProperty("")
    on_action = ObjectProperty(None)  # (suggestion, action) -> None
    on_toast = ObjectProperty(None)   # (msg) -> None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.spacing = 6
        self._expanded = False

        self._head = BoxLayout(size_hint_y=None, height=40, spacing=10)
        self._sw = ColorRect(size_hint=(None, None), size=(34, 34), radius=[6])
        self._title = Txt(font_size=15, bold=True)
        self._badge = Badge()
        self._head.add_widget(self._sw)
        self._head.add_widget(self._title)
        self._head.add_widget(self._badge)
        self.add_widget(self._head)

        self._mode = Dim(font_size=13)
        self.add_widget(self._mode)

        self._recipe = Txt(font_size=14)
        self.add_widget(self._recipe)

        self._detail = BoxLayout(orientation="vertical", size_hint_y=None, spacing=6)
        self._detail.height = 0
        self._detail.opacity = 0
        self.add_widget(self._detail)

        self._actions = BoxLayout(size_hint_y=None, height=40, spacing=8)
        self._copy_btn = GhostButton(text="复制配方", font_size=13, height=36)
        self._cal_btn = GhostButton(text="校准", font_size=13, height=36)
        self._ver_btn = GhostButton(text="核实", font_size=13, height=36)
        self._more_btn = GhostButton(text="更多 ▾", font_size=13, height=36)
        self._copy_btn.bind(on_release=lambda *_: self._on_copy())
        self._cal_btn.bind(on_release=lambda *_: self._dispatch("calibrate"))
        self._ver_btn.bind(on_release=lambda *_: self._dispatch("verify"))
        self._more_btn.bind(on_release=lambda *_: self._toggle())
        for b in (self._copy_btn, self._cal_btn, self._ver_btn, self._more_btn):
            self._actions.add_widget(b)
        self.add_widget(self._actions)

        self.bind(suggestion=self._render, target_hex=self._render)

    def _dispatch(self, action):
        if callable(self.on_action) and self.suggestion is not None:
            self.on_action(self.suggestion, action)

    def _on_copy(self):
        if self.suggestion is None:
            return
        copy_text(recipe_text(self.suggestion.recipe))
        if callable(self.on_toast):
            self.on_toast("配方已复制到剪贴板")

    def _toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._detail.height = self._detail.minimum_height
            self._detail.opacity = 1
            self._more_btn.text = "收起 ▴"
        else:
            self._detail.height = 0
            self._detail.opacity = 0
            self._more_btn.text = "更多 ▾"

    def _render(self, *args):
        sug = self.suggestion
        if sug is None:
            return
        a = sug.anchor
        self._sw.color = hex_to_kivy(a.hex)
        self._title.text = f"{a.full_label} {a.name}"
        de = sug.delta_e
        self._badge.text = f"ΔE {de:.1f}"
        if de <= 1.5:
            self._badge.bg = hex_to_kivy(ACCENT_2)
        elif de <= 3.0:
            self._badge.bg = hex_to_kivy(WARN)
        else:
            self._badge.bg = hex_to_kivy(DANGER)
        self._mode.text = sug.mode_label
        if sug.recipe.direct:
            self._recipe.text = "单色直用，无需调配"
        else:
            lines = [f"· {c.label}  {c.percent_label}（{c.drops}滴）"
                     for c in sug.recipe.components]
            self._recipe.text = "\n".join(lines)
        self._detail.clear_widgets()
        cov = getattr(sug, "coverage", None)
        if cov is not None:
            self._detail.add_widget(Dim(text=cov.as_text(), font_size=12))
        alts = getattr(sug, "alternatives", None) or []
        if alts:
            alt_txt = "替代：" + "，".join(
                f"{x.entry.brand_label} {x.entry.code}" for x in alts[:3])
            self._detail.add_widget(Dim(text=alt_txt, font_size=12))
        if self._expanded:
            self._detail.height = self._detail.minimum_height


# ----------------------------------------------------------------- 色卡网格
class SwatchGrid(GridLayout):
    def __init__(self, **kwargs):
        kwargs.setdefault("cols", 4)
        kwargs.setdefault("spacing", 10)
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self.bind(minimum_height=self.setter("height"))

    def set_swatches(self, items, on_pick=None):
        """items: [(hex, label), ...]"""
        self.clear_widgets()
        for hexv, label in items:
            cell = RelativeLayout(size_hint_y=None, height=84)
            sw = ColorRect(size_hint=(1, 0.7), pos_hint={"top": 1}, radius=[8])
            sw.color = hex_to_kivy(hexv)
            cell.add_widget(sw)
            txt = Label(text=label, color=hex_to_kivy(TEXT), font_size=12,
                        size_hint_y=None, height=24, pos_hint={"y": 0})
            cell.add_widget(txt)
            if on_pick:
                cell.bind(on_release=lambda inst, h=hexv: on_pick(h))
            self.add_widget(cell)
