# -*- coding: utf-8 -*-
"""取色页：从图库照片长按照色 + 手动输入/调色 + 当前颜色概览。"""

from __future__ import annotations

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from ..logic import (add_favorite, add_history, copy_text, get_config,
                     get_matcher)
from ..theme import ACCENT, BG_ALT, D, FS_BODY, FS_SMALL, S, hex_to_kivy
from ..widgets import (AccentButton, Card, ColorRect, Dim, Field, GhostButton,
                       Txt, Title)


class LongPressImage(Image):
    """长按取色：按住 0.35s 在触点取样。"""

    def __init__(self, owner, **kwargs):
        kwargs.setdefault("fit_mode", "contain")  # keep_ratio/allow_stretch 已弃用
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

    def _do_sample(self, *args):
        self._timer = None
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
        self._current_hex = "#000000"
        self._build()

    # ----------------------------------------------------------------- 构建
    def _build(self):
        root = BoxLayout(orientation="vertical", spacing=D(10),
                         padding=[D(14), D(10), D(14), D(8)])
        # 当前颜色卡片固定在顶部（不放进 ScrollView），保证任何时候都完整可见
        root.add_widget(self._build_current_card())

        body = ScrollView(do_scroll_x=False, bar_width=0)
        inner = BoxLayout(orientation="vertical", spacing=D(12), size_hint_y=None)
        inner.bind(minimum_height=inner.setter("height"))
        body.add_widget(inner)
        self._scroll_inner = inner

        inner.add_widget(self._build_gallery_card())
        inner.add_widget(self._build_manual_card())

        root.add_widget(body)
        self.add_widget(root)

    def _build_current_card(self) -> Card:
        cur = Card()
        top = BoxLayout(size_hint_y=None, height=D(66), spacing=D(14))
        self._cur_swatch = ColorRect(size_hint=(None, None),
                                     size=(D(64), D(64)), radius=[D(12)])
        col = BoxLayout(orientation="vertical", spacing=D(2))
        self._cur_hex = Title(text="#000000", font_size=S(22))
        self._cur_rgb = Dim(text="RGB 0,0,0", font_size=S(12))
        self._cur_close = Txt(text="最近漆：—", font_size=S(12))
        col.add_widget(self._cur_hex)
        col.add_widget(self._cur_rgb)
        col.add_widget(self._cur_close)
        top.add_widget(self._cur_swatch)
        top.add_widget(col)
        cur.add_widget(top)

        btns = BoxLayout(size_hint_y=None, height=D(44), spacing=D(8))
        b1 = GhostButton(text="复制 HEX")
        b2 = GhostButton(text="收藏")
        b1.bind(on_release=lambda *_: (copy_text(self.current_hex),
                                       self.app.toast("已复制 " + self.current_hex)))
        b2.bind(on_release=lambda *_: self._fav())
        btns.add_widget(b1)
        btns.add_widget(b2)
        cur.add_widget(btns)
        return cur

    def _build_gallery_card(self) -> Card:
        gal = Card()
        gal.add_widget(Dim(text="从图库取色：选一张照片，长按图片任意位置吸色",
                           font_size=S(FS_SMALL)))
        pick_btn = AccentButton(text="选择照片")
        pick_btn.bind(on_release=lambda *_: self._choose_photo())
        gal.add_widget(pick_btn)

        holder = RelativeLayout(size_hint_y=None, height=D(170))
        with holder.canvas.before:
            Color(*hex_to_kivy(BG_ALT))
            self._holder_bg = RoundedRectangle(pos=holder.pos, size=holder.size,
                                               radius=[D(10)])
        holder.bind(pos=lambda inst, val: setattr(self._holder_bg, "pos", val),
                    size=lambda inst, val: setattr(self._holder_bg, "size", val))

        self._img = LongPressImage(self, size_hint=(1, 1))
        self._img.opacity = 0
        holder.add_widget(self._img)

        self._img_hint = Dim(text="尚未选择照片", font_size=S(FS_SMALL),
                             halign="center", pos_hint={"center_x": 0.5,
                                                        "center_y": 0.5})
        self._img_hint.bind(width=lambda inst, val: setattr(inst, "text_size",
                                                            (val, None)))
        holder.add_widget(self._img_hint)
        gal.add_widget(holder)
        return gal

    def _build_manual_card(self) -> Card:
        man = Card()
        man.add_widget(Title(text="手动输入", font_size=S(FS_BODY + 1)))

        hex_row = BoxLayout(size_hint_y=None, height=D(46), spacing=D(8))
        self._hex_in = Field(text="#E2AE79", size_hint_x=0.7)
        apply_b = GhostButton(text="应用", size_hint_x=0.3)
        apply_b.bind(on_release=lambda *_: self._apply_hex())
        self._hex_in.bind(on_text_validate=lambda *_: self._apply_hex())
        hex_row.add_widget(self._hex_in)
        hex_row.add_widget(apply_b)
        man.add_widget(hex_row)

        self._sliders = []
        self._val_labels = []
        for label in ("R", "G", "B"):
            row = BoxLayout(size_hint_y=None, height=D(40), spacing=D(8))
            row.add_widget(Txt(text=label, size_hint_x=None, width=D(18),
                               font_size=S(14), bold=True))
            sl = Slider(min=0, max=255, value=0,
                        value_track=True,
                        value_track_color=hex_to_kivy(ACCENT),
                        value_track_width=D(4),
                        cursor_size=(D(22), D(22)))
            ch = "RGB".index(label)
            sl.bind(value=lambda inst, val, ch=ch: self._on_slider(ch, val))
            row.add_widget(sl)
            self._sliders.append(sl)
            val = Txt(text="0", size_hint_x=None, width=D(38),
                      font_size=S(13), halign="right")
            row.add_widget(val)
            self._val_labels.append(val)
            man.add_widget(row)
        return man

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
            self._img.opacity = 1
            self._img_hint.opacity = 0
            self.app.toast("已载入照片，长按吸色")
        except Exception:
            self.app.toast("照片载入失败")

    def on_sampled(self, px, rel_x, rel_y):
        self.app.color_set(px, source="screen")
        self._img._clear_marker()
        msize = D(24)
        mx = self._img.x + rel_x * self._img.width
        my = self._img.y + (1 - rel_y) * self._img.height
        mk = ColorRect(size_hint=(None, None), size=(msize, msize),
                       radius=[msize / 2.0])
        mk.color = hex_to_kivy("#ffffff")
        mk.pos = (mx - msize / 2.0, my - msize / 2.0)
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
            self._val_labels[i].text = str(rgb[i])
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
        return self._current_hex

    @current_hex.setter
    def current_hex(self, value):
        self._current_hex = value

    @property
    def app(self):
        from ..app import MppApp
        return MppApp.get_running_app()
