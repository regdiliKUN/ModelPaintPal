# -*- coding: utf-8 -*-
"""移动端主程序：底部导航 + 屏幕管理，串联所有功能页。"""

from __future__ import annotations

from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.screenmanager import ScreenManager, SlideTransition

from .bootstrap import set_user_dir
from .logic import ensure_init
from .screens.about_screen import AboutScreen
from .screens.coverage_screen import CoverageScreen
from .screens.library_screen import LibraryScreen
from .screens.mix_screen import MixScreen
from .screens.more_screen import MoreScreen
from .screens.pick_screen import PickScreen
from .screens.settings_screen import SettingsScreen
from .screens.suggest_screen import SuggestScreen
from .screens.visualize_screen import VisualizeScreen
from .theme import (ACCENT, BOTTOM_NAV_H, BG, TEXT_DIM, hex_to_kivy)

NAV_ITEMS = [
    ("取色", "pick"),
    ("建议", "suggest"),
    ("色卡", "visualize"),
    ("调配", "mix"),
    ("更多", "more"),
]


class NavBar(BoxLayout):
    def __init__(self, app, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", BOTTOM_NAV_H)
        kwargs.setdefault("spacing", 0)
        super().__init__(**kwargs)
        self.app = app
        self.buttons = {}
        with self.canvas.before:
            Color(*hex_to_kivy("#0b0e14"))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)
        for label, name in NAV_ITEMS:
            b = Button(text=label, on_press=lambda inst, n=name: app.go_to(n))
            b.background_normal = ""
            b.background_color = hex_to_kivy("#0b0e14")
            b.color = hex_to_kivy(TEXT_DIM)
            b.font_size = 14
            b.size_hint_y = None
            b.height = BOTTOM_NAV_H
            self.buttons[name] = b
            self.add_widget(b)
        self._highlight("pick")

    def _upd(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _highlight(self, name):
        for n, b in self.buttons.items():
            active = (n == name)
            b.color = hex_to_kivy(ACCENT if active else "#94a0b3")
            b.background_color = hex_to_kivy("#0b0e14")


class MppApp(App):
    current_rgb = None
    current_source = "manual"

    def build(self):
        set_user_dir(self.user_data_dir)
        ensure_init()
        self.title = "ModelPaintPal 移动端"
        try:
            Window.clearcolor = hex_to_kivy(BG)
        except Exception:
            pass  # 无显示环境（如无头测试）跳过清屏色

        root = BoxLayout(orientation="vertical")
        sm = ScreenManager(transition=SlideTransition())
        self.sm = sm

        self.screens = {}
        for cls, name in [
            (PickScreen, "pick"), (SuggestScreen, "suggest"),
            (VisualizeScreen, "visualize"), (MixScreen, "mix"),
            (MoreScreen, "more"), (CoverageScreen, "coverage"),
            (LibraryScreen, "library"), (SettingsScreen, "settings"),
            (AboutScreen, "about"),
        ]:
            screen = cls(name=name)
            self.screens[name] = screen
            sm.add_widget(screen)

        root.add_widget(sm)
        self.nav = NavBar(self)
        root.add_widget(self.nav)
        return root

    # ------------------------------------------------------------ 导航
    def go_to(self, name):
        if name in self.screens:
            self.sm.current = name
        self.nav._highlight(name if name in dict(NAV_ITEMS) else "more")

    # ------------------------------------------------------------ 颜色共享
    def set_current_color(self, rgb, source="manual"):
        self.current_rgb = tuple(int(v) for v in rgb[:3])
        self.current_source = source
        # 若相关页正显示则立即重算
        cur = self.sm.current
        if cur in self.screens:
            sc = self.screens[cur]
            if hasattr(sc, "on_color"):
                sc.on_color(self.current_rgb)

    def color_set(self, rgb, source="manual"):
        self.set_current_color(rgb, source)

    def toast(self, msg):
        from kivy.uix.label import Label
        from kivy.uix.modalview import ModalView
        mv = ModalView(size_hint=(None, None), size=(min(360, Window.width - 40), 48),
                       background_color=(0, 0, 0, 0.001), auto_dismiss=True,
                       timeout=1.6)
        lb = Label(text=msg, color=hex_to_kivy("#ffffff"), font_size=15)
        mv.add_widget(lb)
        mv.open()
