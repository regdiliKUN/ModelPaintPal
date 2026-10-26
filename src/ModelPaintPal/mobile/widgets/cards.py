# -*- coding: utf-8 -*-
"""较复杂的展示控件：徽标、建议卡片、混色比例条、色卡网格。

所有尺寸都通过 :func:`D` / :func:`S` 换算，保证在不同密度屏幕上是同一个手感。
"""

from __future__ import annotations

from kivy.graphics import Color, RoundedRectangle
from kivy.properties import ColorProperty, ListProperty, ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.relativelayout import RelativeLayout

from ..logic import copy_text, recipe_text
from ..theme import (ACCENT_2, D, DANGER, FONT, S, TEXT, TEXT_DIM, WARN,
                     hex_to_kivy)
from . import Card, ColorRect, Dim, GhostButton, Txt


# ----------------------------------------------------------------- 徽标（带圆角底色）
class Badge(Label):
    bg = ColorProperty(hex_to_kivy(ACCENT_2))

    def __init__(self, **kwargs):
        kwargs.setdefault("color", hex_to_kivy("#ffffff"))
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", S(11))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (D(64), D(26)))
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)
        with self.canvas.before:
            self._bg_color = Color(*self.bg)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size,
                                             radius=[D(7)])
        self.text_size = self.size
        self.bind(pos=self._redraw, size=self._redraw, bg=self._redraw)

    def _redraw(self, *args):
        self.text_size = self.size
        self._bg_color.rgba = self.bg
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._bg_rect.radius = [D(7)]


# ----------------------------------------------------------------- 混色比例条
class MixRatioBar(BoxLayout):
    """混色比例条：红/黄/蓝/白/黑按百分比分段。

    分段只用纯色块表示，文字说明放在下方单行图例里——
    把 "角色\\n百分比" 塞进窄分段会在小比例时糊成一团。
    """

    segments = ListProperty([])  # [(role, hex, percent), ...]

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("spacing", D(8))
        super().__init__(**kwargs)
        self.bind(segments=self._rebuild, minimum_height=self.setter("height"))
        self._rebuild()

    def _rebuild(self, *args):
        self.clear_widgets()
        bar = BoxLayout(size_hint_y=None, height=D(22), spacing=D(2))
        parts = []
        for role, hexv, percent in self.segments:
            if percent <= 0.01:
                continue
            seg = ColorRect(size_hint_x=max(percent, 0.8), radius=[D(4)])
            seg.color = hex_to_kivy(hexv)
            bar.add_widget(seg)
            parts.append(f"{role} {percent:.1f}%")
        self.add_widget(bar)
        legend = Txt(text=" · ".join(parts), font_size=S(11),
                     color=hex_to_kivy(TEXT_DIM))
        self.add_widget(legend)


# ----------------------------------------------------------------- 建议卡片
class SuggestionCard(Card):
    suggestion = ObjectProperty(None, allownone=True)
    target_hex = StringProperty("")
    on_action = ObjectProperty(None)  # (suggestion, action) -> None
    on_toast = ObjectProperty(None)   # (msg) -> None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.spacing = D(6)
        self._expanded = False

        self._head = BoxLayout(size_hint_y=None, height=D(32), spacing=D(10))
        self._sw = ColorRect(size_hint=(None, None), size=(D(28), D(28)), radius=[D(6)])
        self._title = Txt(font_size=S(14), bold=True)
        self._badge = Badge()
        self._head.add_widget(self._sw)
        self._head.add_widget(self._title)
        self._head.add_widget(self._badge)
        self.add_widget(self._head)

        self._mode = Dim(font_size=S(11))
        self.add_widget(self._mode)

        self._recipe = Txt(font_size=S(12))
        self.add_widget(self._recipe)

        self._detail = BoxLayout(orientation="vertical", size_hint_y=None, spacing=D(6))
        self._detail.height = 0
        self._detail.opacity = 0
        self._detail.bind(minimum_height=self._sync_detail)
        self.add_widget(self._detail)

        self._actions = BoxLayout(size_hint_y=None, height=D(36), spacing=D(6))
        self._copy_btn = GhostButton(text="复制配方", font_size=S(11), height=D(34))
        self._cal_btn = GhostButton(text="校准", font_size=S(11), height=D(34))
        self._ver_btn = GhostButton(text="核实", font_size=S(11), height=D(34))
        self._more_btn = GhostButton(text="更多", font_size=S(11), height=D(34))
        self._copy_btn.bind(on_release=lambda *_: self._on_copy())
        self._cal_btn.bind(on_release=lambda *_: self._dispatch("calibrate"))
        self._ver_btn.bind(on_release=lambda *_: self._dispatch("verify"))
        self._more_btn.bind(on_release=lambda *_: self._toggle())
        for b in (self._copy_btn, self._cal_btn, self._ver_btn, self._more_btn):
            self._actions.add_widget(b)
        self.add_widget(self._actions)

        self.bind(suggestion=self._render, target_hex=self._render)
        # 构造时已传入 suggestion 不会触发绑定回调，这里主动渲染一次，
        # 否则卡片会是空的（标题/配方/ΔE 都不显示）。
        self._render()

    def _sync_detail(self, *args):
        if self._expanded:
            self._detail.height = self._detail.minimum_height

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
            self._more_btn.text = "收起"
        else:
            self._detail.height = 0
            self._detail.opacity = 0
            self._more_btn.text = "更多"

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
            self._detail.add_widget(Dim(text=cov.as_text(), font_size=S(11),
                                        color=hex_to_kivy(TEXT_DIM)))
        alts = getattr(sug, "alternatives", None) or []
        if alts:
            alt_txt = "替代：" + "，".join(
                f"{x.paint.brand_label} {x.paint.code}" for x in alts[:3])
            self._detail.add_widget(Dim(text=alt_txt, font_size=S(11),
                                        color=hex_to_kivy(TEXT_DIM)))


# ----------------------------------------------------------------- 色卡网格
class _SwatchCell(RelativeLayout):
    """色卡单元格：点按整格触发回调。"""

    def __init__(self, hexv, label, on_pick=None, **kwargs):
        super().__init__(**kwargs)
        self._hexv = hexv
        self._on_pick = on_pick
        sw = ColorRect(size_hint=(1, 0.72), pos_hint={"top": 1}, radius=[D(8)])
        sw.color = hex_to_kivy(hexv)
        self.add_widget(sw)
        txt = Label(text=label, color=hex_to_kivy(TEXT), font_name=FONT,
                    font_size=S(11), size_hint_y=None, height=D(22),
                    pos_hint={"y": 0})
        self.add_widget(txt)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos) and callable(self._on_pick):
            self._on_pick(self._hexv)
            return True
        return super().on_touch_up(touch)


class SwatchGrid(GridLayout):
    def __init__(self, **kwargs):
        kwargs.setdefault("cols", 3)
        kwargs.setdefault("spacing", D(10))
        kwargs.setdefault("size_hint_y", None)
        super().__init__(**kwargs)
        self.bind(minimum_height=self.setter("height"))

    def set_swatches(self, items, on_pick=None):
        """items: [(hex, label), ...]"""
        self.clear_widgets()
        for hexv, label in items:
            cell = _SwatchCell(hexv, label, on_pick=on_pick,
                               size_hint_y=None, height=D(80))
            self.add_widget(cell)
