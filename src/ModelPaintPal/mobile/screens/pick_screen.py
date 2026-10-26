# -*- coding: utf-8 -*-
"""取色页：从图库照片按住拖拽取色 + 手动输入/调色 + 当前颜色概览。"""

from __future__ import annotations

import os
import time

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


def blank_png():
    """2x2 全透明 PNG 的路径。

    ``Image`` 在没有 source 时会画成一块**纯白方块**（实测），所以要给个
    透明占位图；也不要用 ``opacity = 0`` 去藏 —— 那个开关一旦拨过，
    控件的绘制状态就再也回不来了（照片上的边框因此全部消失）。
    """
    from PIL import Image as PILImage

    from ..photo import cache_dir

    path = cache_dir() / "blank.png"
    if not path.exists():
        try:
            PILImage.new("RGBA", (2, 2), (0, 0, 0, 0)).save(str(path), "PNG")
        except Exception:
            return ""
    return str(path)


class ZoomPreview(BoxLayout):
    """取样反馈条：放大图 + 色块 + 色值 + 状态文字。

    为什么是「照片下方的一行」而不是跟着手指的浮动放大镜：

    花了好几轮实测，Kivy 在这个环境下画不出任何「运行时贴上去的浮层内容」——
    自绘 canvas 的浮层（挂 Window、挂 canvas.after、挂页面浮层都试过）一片空白；
    ``Image(texture=自定义纹理)`` 也不显示。只有两样东西稳定：
    普通控件的 canvas 指令（ColorRect / Label / Line）和 ``Image(source=文件)``。
    所以放大图走「裁一小块 → 存 PNG → 换 source」这条路，和照片本身完全一致。

    取样窗口只有几十个像素见方，裁切+缩放+存盘不到 2ms，拖动时够跟手。
    """

    SIDE = 72           # 放大图边长（dp）
    ZOOM = 6.0          # 放大倍数
    THROTTLE = 0.05     # 两次重绘的最小间隔（秒），拖动时别把主线程喂满

    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", D(self.SIDE) + D(10))
        kwargs.setdefault("spacing", D(10))
        super().__init__(**kwargs)
        self.last_span = 0
        self._stamp = 0.0

        # nocache 必须开：同名文件重写后，Kivy 默认会命中 kv.loader /
        # kv.texture 缓存，屏幕上永远停在第一帧（放大图看起来「不动」）。
        self._pic = Image(source="", size_hint=(None, None),
                          size=(D(self.SIDE), D(self.SIDE)),
                          fit_mode="fill", nocache=True)
        self._swatch = ColorRect(size_hint=(None, None),
                                 size=(D(30), D(30)), radius=[D(8)])
        col = BoxLayout(orientation="vertical", spacing=D(2))
        self._hex = Title(text="#000000", font_size=S(FS_BODY))
        self._hint = Dim(text="按住照片，这里放大显示取样点")
        col.add_widget(self._hex)
        col.add_widget(self._hint)
        self.add_widget(self._pic)
        self.add_widget(self._swatch)
        self.add_widget(col)
        self.reset()

    # ------------------------------------------------------------ 内容
    def update(self, pil, rgb, u, v, dw, dh, force=False):
        """刷新预览。

        ``u`` / ``v`` 是取样点在图片内的归一化坐标（左下角为原点），
        ``dw`` / ``dh`` 是图片在屏幕上的绘制尺寸（像素）。

        色块和色值每次都刷（便宜），裁图重绘则按 THROTTLE 节流；
        抬手时会 ``force=True`` 补一帧，保证最终看到的就是取到的那个像素。
        """
        self._swatch.color = (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, 1)
        self._hex.text = "#%02X%02X%02X" % tuple(rgb[:3])
        self._hint.text = "松手取这个像素"
        if pil is None:
            return
        now = time.monotonic()
        if not force and now - self._stamp < self.THROTTLE:
            return
        self._stamp = now
        self._render(pil, u, v, dw, dh)

    def _render(self, pil, u, v, dw, dh):
        from PIL import Image as PILImage

        side = max(8, int(round(D(self.SIDE))))
        img_w, img_h = pil.size

        # 放大 N 倍 = 屏幕上这一块只覆盖 1/N 的显示像素，再换算回原图像素
        span_x = side / self.ZOOM * (img_w / max(1.0, dw))
        span_y = side / self.ZOOM * (img_h / max(1.0, dh))
        span = max(1, min(int(round(min(span_x, span_y))), img_w, img_h))
        self.last_span = span

        cx = min(img_w - 1, max(0, int(u * img_w)))
        cy = min(img_h - 1, max(0, int((1.0 - v) * img_h)))   # PIL 行号自上而下
        x0 = min(max(0, cx - span // 2), img_w - span)
        y0 = min(max(0, cy - span // 2), img_h - span)

        crop = pil.crop((x0, y0, x0 + span, y0 + span))
        crop = crop.resize((side, side), PILImage.NEAREST)
        self._reticle(crop, side)

        path = self._path()
        tmp = path.with_name(path.name + ".tmp")
        try:
            crop.save(str(tmp), "PNG")
            # 先写临时文件再原子替换：读取方（后台加载线程）不会读到半截 PNG
            os.replace(str(tmp), str(path))
            if self._pic.source == str(path):
                self._pic.reload()
            else:
                self._pic.source = str(path)
        except Exception:
            return

    def commit(self, rgb):
        """抬手确认后的状态：放大图留在原地，方便核对取到的到底是哪个像素。"""
        self._hex.text = "#%02X%02X%02X" % tuple(rgb[:3])
        self._hint.text = "已取色 · 再按住可换点"

    @staticmethod
    def _reticle(img, side):
        """在放大图正中画四根指向中心的短线：看的就是正中这一像素。

        不画实心十字，是因为实心会把「正在取的那个颜色」遮住 ——
        四根短线从外指向中心，中间留空。
        """
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        c = side // 2
        gap = max(3, side // 8)          # 中心留空
        ln = max(6, side // 4)           # 短线长度
        segs = (
            ((c + gap, c), (c + gap + ln, c)),
            ((c - gap, c), (c - gap - ln, c)),
            ((c, c + gap), (c, c + gap + ln)),
            ((c, c - gap), (c, c - gap - ln)),
        )
        for seg in segs:                 # 先黑后白：深浅照片上都看得见
            draw.line(seg, fill=(0, 0, 0), width=5)
        for seg in segs:
            draw.line(seg, fill=(255, 255, 255), width=2)

    def _path(self):
        from ..photo import cache_dir
        return cache_dir() / "zoom.png"

    def _blank(self):
        return blank_png()

    def reset(self):
        self._pic.source = self._blank()
        self._swatch.color = (0.5, 0.5, 0.5, 1)
        self._hex.text = "#000000"
        self._hint.text = "按住照片，这里放大显示取样点"
        self.last_span = 0


class ZoomPickImage(FloatLayout):
    """按住即在触点取色，拖动看准星，松手确认。

    之前是「必须按住 0.3 秒」，实际操作里几乎没人会按住那么久 ——
    正常点一下约 100ms，抬手时计时器还没到，界面反而弹一句
    「长按照片 0.3 秒」，看起来就是「点了没反应」。

    现在改成：按下立刻取样并刷新放大预览，拖动实时跟随，抬手才写回颜色。
    ``fit_mode="contain"`` 时图片是**居中**放在控件里的，四周有留白，
    所以取样一律先把触点夹到图片矩形内，而不是拒绝并提示 ——
    留白处也能吸到最边上的那个像素，不会再有「点了边框」的挫败感。

    坐标一律用**控件局部坐标**（``touch.pos - self.pos``），因为那正是
    ``canvas`` 画图用的坐标系；见 :meth:`to_local_point` 里的踩坑记录。

    为什么按压点上方没有「准星」浮层：实测**照片这个 Image 会盖住同层级的
    所有控件**（holder 里的兄弟、它自己的子控件都一样），浮层怎么摆都被照片
    挡住。所以「正在吸哪个像素」的准星改画进下方放大图里（见 ZoomPreview）。
    可点范围也无需画框：留白处会被夹到边缘像素，整个取色区都能按。
    """

    def __init__(self, owner, **kwargs):
        kwargs.setdefault("size_hint", (1, 1))
        source = kwargs.pop("source", "") or blank_png()   # 不是 Kivy 属性，得自己接住
        super().__init__(**kwargs)
        self.owner = owner
        self._touch = None
        self._scroll = None
        self._scroll_state = None
        self.sampling = False
        self.sample_center = (0.0, 0.0)

        self._photo = Image(source=source, size_hint=(1, 1),
                            pos_hint={"x": 0, "y": 0}, fit_mode="contain")
        self.add_widget(self._photo)

        # 换图时取样点会失效
        self._photo.bind(texture=lambda *_: self.sampling and self._mark(None, None))

    # ------------------------------------------------------------ 对外接口
    @property
    def source(self):
        return self._photo.source

    @source.setter
    def source(self, value):
        self._photo.source = value

    @property
    def texture(self):
        return self._photo.texture

    # ------------------------------------------------------------ 几何
    def _local_image_rect(self):
        """图片在本控件坐标系里的绘制矩形。

        自己按 ``fit_mode="contain"`` 的规则算，而不是读图片控件的
        ``norm_image_size``：后者依赖子控件已经完成布局，测试里没有帧循环、
        刚构造完时还是默认的 100x100，会让取样窗口整体算错。
        """
        tex = self._photo.texture
        if not tex or self.width <= 0 or self.height <= 0:
            return None
        tw, th = tex.size
        if tw <= 0 or th <= 0:
            return None
        scale = min(self.width / float(tw), self.height / float(th))
        dw, dh = tw * scale, th * scale
        return ((self.width - dw) / 2.0, (self.height - dh) / 2.0, dw, dh)

    def _mark(self, u, v):
        """记录「正在取哪个像素」（准星画在下方放大图里，照片上不叠东西）。"""
        rect = self._local_image_rect()
        if rect is None or u is None:
            self.sampling = False
            return
        lx, ly, dw, dh = rect
        self.sample_center = (lx + u * dw, ly + v * dh)
        self.sampling = True

    def local_image_rect(self):
        """图片在**控件局部坐标**里的绘制矩形：(x, y, w, h)；没图时 None。"""
        return self._local_image_rect()

    def to_local_point(self, touch):
        """触摸坐标 → 控件局部坐标。

        **这是整套取色最关键的一行**。Kivy 把 ``touch.pos`` 派发给子控件时，
        坐标已经被沿路的容器（尤其是 ScrollView 的 ``g_translate``）平移过，
        其原点和 ``self.pos`` 是同一套；而 ``canvas`` 画图用的也是这套坐标。

        换句话说：``touch.pos - self.pos`` 才是手指在控件内的位置。
        以前这里错用了「窗口坐标」的图片矩形去比 ``touch.pos``，
        实测两者纵向差了 706px（滚动越多差越大），比整张照片还高 ——
        于是每次都被判成「点在图外」，v 被夹到边上，吸到的是图片另一头的颜色，
        旧版本还会弹一句「不要点边框」。
        """
        return touch.x - self.x, touch.y - self.y

    # ------------------------------------------------------------ 触摸
    def on_touch_down(self, touch):
        if self.owner.pil_image is None or not self.collide_point(*touch.pos):
            return False
        if self._touch is not None:          # 已经有一根手指在取色
            return False
        self._touch = touch
        self._freeze_scroll(True)
        self._update(*self.to_local_point(touch))

        from kivy.core.window import Window
        Window.bind(on_touch_move=self._on_move, on_touch_up=self._on_up)
        # 吃掉这一下：否则 ScrollView 会一边取色一边把页面拖走
        return True

    def _on_move(self, _win, touch):
        if self._touch is None or touch.uid != self._touch.uid:
            return
        self._update(*self.to_local_point(touch))

    def _on_up(self, _win, touch):
        if self._touch is None or touch.uid != self._touch.uid:
            return
        lx, ly = self.to_local_point(touch)
        # 补一帧不节流的预览：抬手看到的放大图必须就是取到的那个像素
        self._update(lx, ly, force=True)
        hit = self.sample_at(lx, ly)
        self._end()
        if hit is not None:
            self.owner.on_sampled(*hit)

    def _end(self):
        self._touch = None
        self._freeze_scroll(False)
        self._mark(None, None)
        try:
            from kivy.core.window import Window
            Window.unbind(on_touch_move=self._on_move, on_touch_up=self._on_up)
        except Exception:
            pass

    def _freeze_scroll(self, on):
        """取色期间锁住页面滚动，手指下面的内容不能跟着跑。"""
        if on:
            node = self.parent
            while node is not None and not isinstance(node, ScrollView):
                node = node.parent
            self._scroll = node
            if node is not None:
                self._scroll_state = (node.do_scroll_x, node.do_scroll_y)
                node.do_scroll_x = False
                node.do_scroll_y = False
            return
        if self._scroll is not None and self._scroll_state is not None:
            self._scroll.do_scroll_x, self._scroll.do_scroll_y = self._scroll_state
        self._scroll = None
        self._scroll_state = None

    # ------------------------------------------------------------ 取样
    def sample_at(self, x, y):
        """控件局部坐标 → (rgb, u, v)。

        ``u`` / ``v`` 都是**左下角为原点**的归一化坐标。

        触点在图片外（``fit_mode="contain"`` 的留白）时夹到最近的边缘像素，
        **不再拒绝**：留白区只比照片宽出一点，手指本来就容易偏出去一两毫米，
        弹一句「不要点边框」只会让人以为点坏了。
        """
        photo = self.owner.pil_image
        rect = self._local_image_rect()
        if photo is None or rect is None:
            return None
        x0, y0, dw, dh = rect
        u = min(1.0, max(0.0, (x - x0) / dw))
        v = min(1.0, max(0.0, (y - y0) / dh))
        w, h = photo.size
        # PIL 的行号是从上往下数的，所以纵向要翻过来
        px = photo.getpixel((min(w - 1, int(u * w)),
                             min(h - 1, int((1.0 - v) * h))))
        return (tuple(px[:3]), u, v)

    def _update(self, x, y, force=False):
        hit = self.sample_at(x, y)
        rect = self._local_image_rect()
        if hit is None or rect is None:
            return
        rgb, u, v = hit
        self._mark(u, v)
        self.owner.zoom_update(rgb, u, v, rect[2], rect[3], force)


class PickScreen(Screen):
    # 取色区高度按照片比例自适应，但夹在下面这个区间里：
    # 太矮长按照片点不准，太高会把下面的手动输入挤到屏幕外。
    # 注意：曾经「载入时直接把高度拉到 280dp」触发过一次重排，把同一张卡里
    # 的「选择照片」按钮宽度压成 26px，所以这里必须留出上下限并复测。
    #
    # 上限从 300 提到 380：手机照片基本是 3:4 / 9:16 的竖图，在 300dp 高度下
    # contain 出来的宽度只有约 225dp（屏宽 393dp），左右各留一大片空白 ——
    # 用户会以为「图片就这么小、点边上没反应」。380dp 之后 3:4 图能占到
    # 屏宽八成，留白只剩两指宽，取色手感明显不同。
    HOLDER_MIN = 200
    HOLDER_MAX = 380

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
        gal.add_widget(Dim(text="从图库取色：按住照片拖动，松手即取当前像素",
                           font_size=S(FS_SMALL)))
        pick_btn = AccentButton(text="选择照片")
        pick_btn.bind(on_release=lambda *_: self._choose_photo())
        self._pick_btn = pick_btn
        gal.add_widget(pick_btn)

        # 用 FloatLayout 而不是 RelativeLayout：RelativeLayout 里子控件的 pos
        # 是「相对单位」(0~1)，拿 self._img.pos 去换算屏幕坐标会得到 y=0 这种
        # 结果，取样和放大镜全会错位。
        holder = FloatLayout(size_hint_y=None, height=D(self.HOLDER_MIN))
        self._holder = holder
        with holder.canvas.before:
            Color(*hex_to_kivy(BG_ALT))
            self._holder_bg = RoundedRectangle(pos=holder.pos, size=holder.size,
                                               radius=[D(10)])
        holder.bind(pos=lambda inst, val: setattr(self._holder_bg, "pos", val),
                    size=lambda inst, val: setattr(self._holder_bg, "size", val))

        # pos_hint 必须显式给：FloatLayout 不会给没有 pos_hint 的子控件定位，
        # 否则图片会跑到窗口左下角 (0,0)。
        self._img = ZoomPickImage(self, size_hint=(1, 1),
                                  pos_hint={"x": 0, "y": 0})
        holder.add_widget(self._img)

        self._img_hint = Dim(text="尚未选择照片", font_size=S(FS_SMALL),
                             halign="center", pos_hint={"center_x": 0.5,
                                                        "center_y": 0.5})
        self._img_hint.bind(width=lambda inst, val: setattr(inst, "text_size",
                                                            (val, None)))
        holder.add_widget(self._img_hint)
        gal.add_widget(holder)

        # 取样反馈条：放在照片正下方，手指按住照片时它就在旁边，
        # 能一边拖一边看清正在取的像素。
        self._preview = ZoomPreview()
        gal.add_widget(self._preview)
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
        # 清文字而不是 opacity=0：这个开关拨过一次之后，控件的绘制状态就再也
        # 回不来（照片上的描边曾因此整层消失），没必要去碰它。
        self._img_hint.text = ""
        self._fit_holder(photo.width, photo.height)
        self._preview.reset()               # 上一张图的放大结果不能留在新照片下面
        self.app.toast("已载入照片，按住照片拖动取色")

    def _fit_holder(self, w, h):
        """按照片宽高比调取色区高度，横图不留一大片空白。"""
        holder = self._holder
        avail = holder.width or self.width
        if not avail or not w or not h:
            return
        want = avail * float(h) / float(w)      # contain 下的理想高度
        target = max(D(self.HOLDER_MIN), min(D(self.HOLDER_MAX), want))
        if abs(holder.height - target) > 0.5:
            holder.height = target

    # ----------------------------------------------------------------- 取样反馈
    def zoom_update(self, rgb, u, v, dw, dh, force=False):
        """手指下面那一个像素的实时预览（由 ZoomPickImage 调用）。

        不做浮层放大镜：实测这个环境下浮层/自绘 canvas/自定义纹理都不渲染，
        只有「普通控件 + Image(source=文件)」稳定 —— 详见 ZoomPreview 的注释。
        """
        self._preview.update(self.pil_image, rgb, u, v, dw, dh, force=force)

    def zoom_reset(self):
        self._preview.reset()

    def on_sampled(self, px, rel_x, rel_y):
        self.app.color_set(px, source="screen")
        self._preview.commit(px)
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
