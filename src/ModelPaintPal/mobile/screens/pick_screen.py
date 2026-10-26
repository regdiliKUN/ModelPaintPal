# -*- coding: utf-8 -*-
"""取色页：从图库照片长按照色 + 手动输入/调色 + 当前颜色概览。"""

from __future__ import annotations

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from ..logic import (add_favorite, add_history, copy_text, get_config,
                     get_matcher)
from ..photo import pick_image
from ..theme import ACCENT, BG_ALT, D, FS_BODY, FS_SMALL, S, hex_to_kivy
from ..widgets import (AccentButton, Card, ColorRect, Dim, Field, GhostButton,
                       Txt, Title)


class LongPressImage(Image):
    """长按取色：按住 0.3s 在触点取样。

    两个容易踩的点：

    1. ``fit_mode="contain"`` 时图片是**居中**放在控件里的，四周留白。
       直接拿「控件内相对位置」当「图片内相对位置」会偏（实测 300×300 控件
       里放 200×100 的图，绘制矩形是 ``pos=(0,75) size=(300,150)``）。
       所以先用 ``norm_image_size`` 算出真实绘制矩形再换算。
    2. 这里**不能**在 ``on_touch_down`` 里返回 True，否则 ScrollView 拿不到
       这一下，手指落在照片上就滑不动页面。改成返回 False，用 Window 的
       全局事件跟踪「按住不动」，一旦移动超过阈值就当作滚动、放弃取样。
    """

    HOLD = 0.30          # 按住多久算长按
    SLOP = 12            # 手指移动超过 dp(12) 就认为在滚动

    def __init__(self, owner, **kwargs):
        kwargs.setdefault("fit_mode", "contain")  # keep_ratio/allow_stretch 已弃用
        super().__init__(**kwargs)
        self.owner = owner
        self._timer = None
        self._touch = None
        self._down = None
        self._bound = False

    # ------------------------------------------------------------ 触摸
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos) or self.owner.pil_image is None:
            return False
        self._track(touch)
        return False        # 关键：不吃掉事件，页面还能正常滚动

    def _track(self, touch):
        from kivy.core.window import Window

        self._untrack()
        self._touch = touch
        self._down = (touch.x, touch.y)
        self._timer = Clock.schedule_once(self._do_sample, self.HOLD)
        Window.bind(on_touch_move=self._on_move, on_touch_up=self._on_up)
        self._bound = True

    def _untrack(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._touch = None          # 不再跟踪这一根手指
        if not self._bound:
            return
        self._bound = False
        try:
            from kivy.core.window import Window
            Window.unbind(on_touch_move=self._on_move, on_touch_up=self._on_up)
        except Exception:
            pass

    def _on_move(self, _win, touch):
        if self._touch is None or touch.uid != self._touch.uid:
            return
        if self._down is None:
            return
        dx = abs(touch.x - self._down[0])
        dy = abs(touch.y - self._down[1])
        if dx > D(self.SLOP) or dy > D(self.SLOP):
            self._untrack()          # 在滚动，不是长按

    def _on_up(self, _win, touch):
        if self._touch is None or touch.uid != self._touch.uid:
            return
        was_pending = self._timer is not None
        self._untrack()
        if was_pending:
            self.owner.on_hold_hint()

    # ------------------------------------------------------------ 取样
    def draw_rect(self):
        """图片在屏幕上的实际绘制矩形：(x, y, w, h)；没图时返回 None。

        **必须用 ``to_window()``**：控件在 ScrollView 里时 ``self.pos`` 只是
        内容区内的相对值（实测和窗口坐标差 1000px 以上），直接拿去做触点判定
        会让吸色整体偏移 —— 手指点红色却取到别的颜色。
        """
        if not self.texture:
            return None
        try:
            dw, dh = self.norm_image_size
        except Exception:
            return None
        if dw <= 0 or dh <= 0:
            return None
        wx, wy = self.to_window(self.x, self.y)
        return (wx + (self.width - dw) / 2.0,
                wy + (self.height - dh) / 2.0, dw, dh)

    def _do_sample(self, *args):
        self._timer = None
        photo = self.owner.pil_image
        rect = self.draw_rect()
        if photo is None or rect is None or self._down is None:
            return
        x0, y0, dw, dh = rect
        tx, ty = self._down
        if not (x0 <= tx <= x0 + dw and y0 <= ty <= y0 + dh):
            self._untrack()
            self.owner.on_hold_hint("请按住照片本身，四周灰色留白处不能取色")
            return
        rel_x = min(1.0, max(0.0, (tx - x0) / dw))
        rel_y = min(1.0, max(0.0, 1.0 - (ty - y0) / dh))
        w, h = photo.size
        px = photo.getpixel((min(w - 1, int(rel_x * w)),
                             min(h - 1, int(rel_y * h))))
        self.owner.on_sampled(px, rel_x, rel_y)


class PickScreen(Screen):
    # 取色区高度固定：曾经在「载入照片时把高度从 170dp 拉伸到 280dp」，
    # 结果触发的重排让同一张卡里的「选择照片」按钮宽度塌成 26px（实测），
    # 所以这里不给动态改高度的机会，一次定高。
    HOLDER_H = 240

    def __init__(self, **kwargs):
        name = kwargs.pop("name", "pick")
        super().__init__(**kwargs)
        self.name = name
        self.pil_image = None
        self.photo_path = None
        self._current_hex = "#000000"
        self._syncing = False        # 程序性回填滑块时不要反算颜色
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

        # 用 FloatLayout 而不是 RelativeLayout：RelativeLayout 里子控件的 pos
        # 是「相对单位」(0~1)，拿 self._img.pos 去换算屏幕坐标会得到 y=0 这种
        # 结果，长按取样和落点标记全会错位。
        holder = FloatLayout(size_hint_y=None, height=D(self.HOLDER_H))
        self._holder = holder
        with holder.canvas.before:
            Color(*hex_to_kivy(BG_ALT))
            self._holder_bg = RoundedRectangle(pos=holder.pos, size=holder.size,
                                               radius=[D(10)])
        holder.bind(pos=lambda inst, val: setattr(self._holder_bg, "pos", val),
                    size=lambda inst, val: setattr(self._holder_bg, "size", val))

        # pos_hint 必须显式给：FloatLayout 不会给没有 pos_hint 的子控件定位，
        # 否则图片会跑到窗口左下角 (0,0)。
        self._img = LongPressImage(self, size_hint=(1, 1),
                                   pos_hint={"x": 0, "y": 0})
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
        self.app.toast("正在打开图库…")
        pick_image(self._on_photo_picked)

    def _on_photo_picked(self, photo, error):
        if photo is None:
            if error:                       # 取消时 error 为空，不打扰用户
                self.app.toast(error)
            return
        self.pil_image = photo.pil
        self.photo_path = photo.path
        self._img.source = photo.path       # 每次都是新的缓存文件名，不会命中旧缓存
        self._img.opacity = 1
        self._img_hint.opacity = 0
        self.app.toast("已载入照片，长按图片吸色")

    def on_hold_hint(self, msg="长按照片 0.3 秒即可吸色"):
        self.app.toast(msg)

    def on_sampled(self, px, rel_x, rel_y):
        self.app.color_set(px, source="screen")
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
        if self._syncing:            # 由 on_color 回填时不要反过来改颜色
            return
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
        self._syncing = True
        try:
            for i, sl in enumerate(self._sliders):
                if int(sl.value) != rgb[i]:
                    sl.value = rgb[i]
                self._val_labels[i].text = str(rgb[i])
        finally:
            self._syncing = False
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
