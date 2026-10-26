# -*- coding: utf-8 -*-
"""移动端主程序：底部导航 + 屏幕管理，串联所有功能页。"""

from __future__ import annotations

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
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
from .theme import (ACCENT, BG, D, FONT, NAV_BG, NAV_H, S, TEXT, TEXT_DIM,
                    hex_to_kivy)

NAV_ITEMS = [
    ("取色", "pick"),
    ("建议", "suggest"),
    ("色卡", "visualize"),
    ("调配", "mix"),
    ("更多", "more"),
]


class NavItem(Button):
    """底部导航项：激活时高亮。"""

    def __init__(self, label, name, on_press_cb, **kwargs):
        kwargs.setdefault("text", label)
        kwargs.setdefault("font_name", FONT)
        kwargs.setdefault("font_size", S(12))
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_color", hex_to_kivy(NAV_BG))
        kwargs.setdefault("color", hex_to_kivy(TEXT_DIM))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", D(NAV_H))
        super().__init__(**kwargs)
        self.nav_name = name
        self.bind(on_release=lambda *_: on_press_cb(name))
        with self.canvas.before:
            Color(*hex_to_kivy(NAV_BG))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def set_active(self, active: bool):
        self.color = hex_to_kivy(ACCENT if active else TEXT_DIM)


class NavBar(BoxLayout):
    def __init__(self, app, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", D(NAV_H))
        kwargs.setdefault("spacing", 0)
        kwargs.setdefault("padding", [0, 0, 0, 0])
        super().__init__(**kwargs)
        self.app = app
        self.buttons = {}
        self._active = "pick"
        with self.canvas.before:
            Color(*hex_to_kivy(NAV_BG))
            self._bg = RoundedRectangle(pos=self.pos, size=self.size)
        # 激活项顶部的短横指示条（放在导航条自己的画布上，位置由索引算出，
        # 避免跟着按钮的 size/pos 更新顺序出现偏移）
        with self.canvas.after:
            Color(*hex_to_kivy(ACCENT))
            self._ind = RoundedRectangle(pos=self.pos, size=(0, 0), radius=[D(2)])
        self.bind(pos=self._refresh, size=self._refresh)
        for label, name in NAV_ITEMS:
            b = NavItem(label, name, self._on_nav)
            self.buttons[name] = b
            self.add_widget(b)
        self._highlight("pick")

    def _on_nav(self, name):
        self.app.go_to(name)

    def _place_indicator(self, *args):
        names = [n for _, n in NAV_ITEMS]
        if self._active not in names:
            self._ind.size = (0, 0)
            return
        idx = names.index(self._active)
        slot = self.width / len(names)
        w = D(22)
        self._ind.pos = (self.x + idx * slot + (slot - w) / 2.0, self.top - D(3))
        self._ind.size = (w, D(3))

    def _refresh(self, *args):
        self._upd()
        self._place_indicator()

    def _upd(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _highlight(self, name):
        self._active = name
        for n, b in self.buttons.items():
            b.set_active(n == name)
        self._place_indicator()


class MppApp(App):
    current_rgb = None
    current_source = "manual"
    _toast = None

    def build(self):
        set_user_dir(self.user_data_dir)
        ensure_init()
        self.title = "ModelPaintPal"
        try:
            Window.clearcolor = hex_to_kivy(BG)
            # 键盘弹出时把输入框顶上来，避免被遮挡
            Window.softinput_mode = "below_target"
        except Exception:
            pass  # 无显示环境（如无头测试）跳过窗口设置

        root = BoxLayout(orientation="vertical")
        sm = ScreenManager(transition=SlideTransition(duration=0.18))
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

    def on_start(self):
        # 安卓返回键：逐级退回主页面
        try:
            Window.bind(on_keyboard=self._on_key)
        except Exception:
            pass
        # 给个初始色：否则顶部卡片写 #000000、手动输入框却写着 #E2AE79
        if self.current_rgb is None:
            self.color_set((0xE2, 0xAE, 0x79), source="manual")

    def _on_key(self, window, key, *args):
        if key == 27:  # ESC / 安卓返回键
            if self.sm.current != "pick":
                self.go_to("pick")
                return True
        return False

    # ------------------------------------------------------------ 导航
    def go_to(self, name):
        if name in self.screens:
            self.sm.current = name
        nav_names = {n for _, n in NAV_ITEMS}
        self.nav._highlight(name if name in nav_names else "more")

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
        """屏幕底部浮一条短提示。

        注意**不要**用 ``ModalView`` 实现：它默认会盖一层 70% 黑遮罩（整个界面
        闪一下暗），而且挂在 Window 上的模态层会干扰后续控件的绘制状态 —— 实测
        出现「按钮只画出一小条」的渲染错乱。这里直接把一个浮动 BoxLayout 加进
        Window 的浮层，不抢焦点、不影响布局。
        """
        try:
            self._drop_toast()
            width = min(D(320), max(Window.width - D(40), D(160)))
            height = D(52)
            box = BoxLayout(size_hint=(None, None), size=(width, height),
                            pos=((Window.width - width) / 2.0,
                                 self.nav.height + D(20)))
            with box.canvas.before:
                Color(*hex_to_kivy("#2b3342"))
                r = RoundedRectangle(pos=box.pos, size=box.size, radius=[D(14)])
            box.bind(pos=lambda inst, val: setattr(r, "pos", val),
                     size=lambda inst, val: setattr(r, "size", val))
            lb = Label(text=msg, color=hex_to_kivy(TEXT), font_name=FONT,
                       font_size=S(14), halign="center", valign="middle")
            lb.bind(size=lambda inst, val: setattr(inst, "text_size", val))
            box.add_widget(lb)
            Window.add_widget(box)
            self._toast = box
            Clock.schedule_once(lambda dt: self._drop_toast(), 1.8)
        except Exception:
            pass  # 提示失败不应影响主流程

    def _drop_toast(self):
        box, self._toast = self._toast, None
        if box is None:
            return
        try:
            Window.remove_widget(box)
        except Exception:
            pass
