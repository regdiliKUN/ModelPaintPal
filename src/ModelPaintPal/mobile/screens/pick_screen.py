# -*- coding: utf-8 -*-
"""取色页：从图库照片长按照色 + 手动输入/调色 + 当前颜色概览。"""

from __future__ import annotations

from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput

from ..logic import (add_favorite, add_history, copy_text, get_config,
                     get_matcher)
from ..theme import (CARD, TEXT, hex_to_kivy)
from ..widgets import (AccentButton, Card, ColorRect, Dim, GhostButton, Txt,
                       Title)


class LongPressImage(Image):
    """长按取色：按住 0.35s 在触点取样。"""

    def __init__(self, owner, **kwargs):
        kwargs.setdefault("allow_stretch", True)
        kwargs.setdefault("keep_ratio", True)
        super().__init__(**kwargs)
        self.owner = owner
        self._timer = None
        self._down_pos = None
        self._marker = None

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self._down_pos = (touch.x, touch.y)
        self._timer = Clock.schedule_once(self._do_sample, 0.35)
        return True

    def on_touch_up(self, touch):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._clear_marker()
        return super().on_touch_up(touch)

    def _clear_marker(self):
        if self._marker is not None:
            self.remove_widget(self._marker)
            self._marker = None

    def _do_sample(self, *a):
        if self._down_pos is None or self.owner.pil_image is None:
            return
        tx, ty = self._down_pos
        rel_x = (tx - self.x) / self.width if self.width else 0
        rel_y = 1.0 - ((ty - self.y) / self.height) if self.height else 0
        rel_x = min(1.0, max(0.0, rel_x))
        rel_y = min(1.0, max(0.0, rel_y))
        w, h = self.owner.pil_image.size
        px = self.owner.pil_image.convert("RGB").getpixel(
            (min(w - 1, int(rel_x * w)), min(h - 1, int(rel_y * h))))
        self.owner.on_sampled(px, rel_x, rel_y)


class PickScreen(Screen):
    def __init__(self, **kwargs):
        name = kwargs.pop("name", "pick")
        super().__init__(**kwargs)
        self.name = name
        self.pil_image = None
        self._build()

    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=10, padding=[14, 12, 14, 10])
        body = ScrollView()
        inner = BoxLayout(orientation="vertical", spacing=14, size_hint_y=None)
        inner.bind(minimum_height=inner.setter("height"))
        body.add_widget(inner)

        # 当前颜色概览
        cur = Card()
        top = BoxLayout(size_hint_y=None, height=72, spacing=14)
        self._cur_swatch = ColorRect(size_hint=(None, None), size=(64, 64), radius=[12])
        col = BoxLayout(orientation="vertical", spacing=2)
        self._cur_hex = Title(text="#000000", font_size=20)
        self._cur_rgb = Dim(text="RGB 0,0,0")
        self._cur_close = Txt(text="最近漆：—", font_size=14)
        col.add_widget(self._cur_hex)
        col.add_widget(self._cur_rgb)
        col.add_widget(self._cur_close)
        top.add_widget(self._cur_swatch)
        top.add_widget(col)
        cur.add_widget(top)
        btns = BoxLayout(size_hint_y=None, height=44, spacing=8)
        b1 = GhostButton(text="复制 HEX")
        b2 = GhostButton(text="收藏")
        b1.bind(on_release=lambda *_: (copy_text(self.current_hex),
                                       self.app.toast("已复制 " + self.current_hex)))
        b2.bind(on_release=lambda *_: self._fav())
        btns.add_widget(b1)
        btns.add_widget(b2)
        cur.add_widget(btns)
        inner.add_widget(cur)

        # 从图库取色
        gal = Card()
        gal.add_widget(Dim(text="从图库取色：选一张照片，长按图片任意位置吸色", font_size=13))
        pick_btn = AccentButton(text="选择照片")
        pick_btn.bind(on_release=lambda *_: self._choose_photo())
        gal.add_widget(pick_btn)
        self._img = LongPressImage(self)
        self._img.size_hint = (1, None)
        self._img.height = 240
        gal.add_widget(self._img)
        inner.add_widget(gal)

        # 手动输入
        man = Card()
        man.add_widget(Title(text="手动输入", font_size=16))
        hex_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        self._hex_in = TextInput(text="#E2AE79", multiline=False, size_hint_x=0.7,
                                 background_color=hex_to_kivy(CARD),
                                 foreground_color=hex_to_kivy(TEXT), font_size=16)
        apply_b = GhostButton(text="应用", size_hint_x=0.3)
        apply_b.bind(on_release=lambda *_: self._apply_hex())
        self._hex_in.bind(on_text_validate=lambda *_: self._apply_hex())
        hex_row.add_widget(self._hex_in)
        hex_row.add_widget(apply_b)
        man.add_widget(hex_row)
        self._sliders = []
        self._val_labels = []
        for label in ("R", "G", "B"):
            row = BoxLayout(size_hint_y=None, height=40, spacing=8)
            row.add_widget(Txt(text=label, size_hint_x=0.1, font_size=15))
            sl = Slider(min=0, max=255, value=0, size_hint_x=0.78)
            ch = "RGB".index(label)
            sl.bind(value=lambda inst, val, ch=ch: self._on_slider(ch, val))
            row.add_widget(sl)
            self._sliders.append(sl)
            val = Txt(text="0", size_hint_x=0.12, font_size=14)
            row.add_widget(val)
            self._val_labels.append(val)
            man.add_widget(row)
        inner.add_widget(man)

        root.add_widget(body)
        self.add_widget(root)

    # ----------------------------------------------------------------- 照片
    def _choose_photo(self):
        try:
            from plyer import filechooser
            filechooser.open_file(
                filters=[("Image", "*.jpg", "*.jpeg", "*.png")],
                on_selection=self._on_photo_selected)
        except Exception:
            self.app.toast("无法打开图库（桌面端请用手动输入）")

    def _on_photo_selected(self, selection):
        if not selection:
            return
        path = selection[0]
        try:
            from PIL import Image as PILImage
            self.pil_image = PILImage.open(path)
            self._img.source = path
            self._img.reload()
            self.app.toast("已载入照片，长按吸色")
        except Exception:
            self.app.toast("照片载入失败")

    def on_sampled(self, px, rel_x, rel_y):
        self.app.color_set(px, source="screen")
        self._img._clear_marker()
        mx = self._img.x + rel_x * self._img.width
        my = self._img.y + (1 - rel_y) * self._img.height
        mk = ColorRect(size_hint=(None, None), size=(26, 26), radius=[13])
        mk.color = hex_to_kivy("#ffffff")
        mk.pos = (mx - 13, my - 13)
        self._img.add_widget(mk)
        self._img._marker = mk
        self.app.toast(f"已吸色 #{px[0]:02X}{px[1]:02X}{px[2]:02X}")

    # ----------------------------------------------------------------- 手动
    def _apply_hex(self):
        raw = self._hex_in.text.strip().lstrip("#")
        if len(raw) == 3:
            raw = "".join(c * 2 for c in raw)
        if len(raw) != 6:
            self.app.toast("HEX 格式应为 #RRGGBB")
            return
        try:
            r, g, b = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
        except ValueError:
            self.app.toast("HEX 格式错误")
            return
        self.app.color_set((r, g, b), source="manual")

    def _on_slider(self, ch, value):
        rgb = [int(self._sliders[0].value), int(self._sliders[1].value),
               int(self._sliders[2].value)]
        rgb[ch] = int(value)
        for i, sl in enumerate(self._sliders):
            self._val_labels[i].text = str(int(sl.value))
        self.app.color_set(tuple(rgb), source="manual")

    # ----------------------------------------------------------------- 概览
    def on_color(self, rgb):
        from app.core.color_models import rgb_to_hex
        self.current_hex = rgb_to_hex(rgb)
        self._cur_swatch.color = hex_to_kivy(self.current_hex)
        self._cur_hex.text = self.current_hex
        self._cur_rgb.text = f"RGB {rgb[0]},{rgb[1]},{rgb[2]}"
        if self._hex_in.text.upper() != self.current_hex.upper():
            self._hex_in.text = self.current_hex
        for i, sl in enumerate(self._sliders):
            if int(sl.value) != rgb[i]:
                sl.value = rgb[i]
        try:
            m = get_matcher()
            cfg = get_config()
            sugs = m.suggest(rgb, cfg, brands=cfg.preferred_brands or None,
                             max_results=1)
            if sugs:
                a = sugs[0].anchor
                self._cur_close.text = (f"最近漆：{a.full_label} {a.name} "
                                        f"ΔE {sugs[0].delta_e:.1f}")
            else:
                self._cur_close.text = "最近漆：—"
        except Exception:
            self._cur_close.text = "最近漆：—"

    def _fav(self):
        if self.app.current_rgb is None:
            self.app.toast("还没有颜色")
            return
        add_favorite(self.app.current_rgb)
        add_history(self.app.current_rgb)
        self.app.toast("已收藏当前颜色")

    @property
    def current_hex(self):
        return getattr(self, "_current_hex", "#000000")

    @current_hex.setter
    def current_hex(self, value):
        self._current_hex = value

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()
