# -*- coding: utf-8 -*-
"""取色页：从图库照片按住拖拽取色 + 手动输入/调色 + 当前颜色概览。"""

from __future__ import annotations

import os
import time

from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.modalview import ModalView
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


class PhotoStage(FloatLayout):
    """全屏取色区：整块都是取色板，按住即取，拖动跟手，松手确认。

    **这里刻意不做任何窗口/矩阵换算**，只用 ``touch.pos - self.pos``。

    上一版是用 ``get_window_matrix()`` 算出「控件画在哪」，再拿 ``touch.sx/sy``
    反推「手指在窗口的哪儿」，两者相减。但那两条都是**推导值**：矩阵要从
    整条父容器的 ``to_window/to_widget`` 组合出来，手机实测仍然整体偏下
    几百像素；而控件树派发给我们的 ``touch.pos``（减去自己的 ``pos``）才是
    唯一权威的那份坐标 —— 按钮点得中，就证明它跟控件的绘制位置是一致的。

    所以这一版把取色区做成**铺满窗口的独立层**：没有 ScrollView、没有页面
    平移、父容器全在原点。于是「父容器坐标」和「窗口坐标」在这里是同一个
    东西，按下与拖动无论走哪条派发路径，算出来的局部坐标都相同。
    """

    def __init__(self, on_sample=None, on_commit=None, **kwargs):
        kwargs.setdefault("size_hint", (1, 1))
        source = kwargs.pop("source", "") or blank_png()
        super().__init__(**kwargs)
        self.on_sample = on_sample          # (rgb, u, v, dw, dh, force)
        self.on_commit = on_commit          # (rgb)
        self.pil = None                     # 取样用的 PIL 图（由调用方塞进来）
        self.sampling = False
        self.sample_center = (0.0, 0.0)
        self._touch = None

        self._photo = Image(source=source, size_hint=(1, 1),
                            pos_hint={"x": 0, "y": 0}, fit_mode="contain")
        self.add_widget(self._photo)
        # 换图后取样点失效
        self._photo.bind(texture=lambda *_: self.sampling and self._mark(None, None))

    # ------------------------------------------------------------ 对外
    @property
    def source(self):
        return self._photo.source

    @source.setter
    def source(self, value):
        self._photo.source = value

    @property
    def texture(self):
        return self._photo.texture

    def to_local_point(self, touch):
        """手指在控件里的位置（左下角原点，和 canvas 同一套）。

        ``touch.pos`` 是 Kivy 派发到本控件的那份坐标（父容器坐标系），
        ``self.pos`` 也正好是父容器坐标系里的值 —— 相减就是局部坐标。
        不要换成 ``to_window()`` / ``get_window_matrix()``：那是把同一件事
        再推导一遍，多一道推导就多一处能在手机上翻车的地方。
        """
        return touch.x - self.x, touch.y - self.y

    def local_image_rect(self):
        """图片在**控件局部坐标**里的绘制矩形：(x, y, w, h)；没图时 None。

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
        """记录「正在取哪个像素」（准星画在放大图里，照片上不叠东西）。"""
        rect = self.local_image_rect()
        if rect is None or u is None:
            self.sampling = False
            return
        x0, y0, dw, dh = rect
        self.sample_center = (x0 + u * dw, y0 + v * dh)
        self.sampling = True

    # ------------------------------------------------------------ 取样
    def sample_at(self, x, y):
        """控件局部坐标 → (rgb, u, v)。

        ``u`` / ``v`` 都是**左下角为原点**的归一化坐标。

        触点在图片外（``fit_mode="contain"`` 的留白）时夹到最近的边缘像素，
        **不再拒绝**：留白区本来就只比照片宽一点，手指容易偏出去一两毫米，
        弹一句「不要点边框」只会让人以为点坏了。
        """
        photo = self.pil
        rect = self.local_image_rect()
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
        rect = self.local_image_rect()
        if hit is None or rect is None:
            return
        rgb, u, v = hit
        self._mark(u, v)
        if self.on_sample is not None:
            self.on_sample(rgb, u, v, rect[2], rect[3], force)

    # ------------------------------------------------------------ 触摸
    def on_touch_down(self, touch):
        if self.pil is None or self._touch is not None:
            return False
        if not self.collide_point(*touch.pos):
            return False
        self._touch = touch
        touch.grab(self)
        # 按下立刻取样：正常点一下只有 100ms 左右，等不得
        self._update(*self.to_local_point(touch))
        return True

    def on_touch_move(self, touch):
        # 不要用 touch.grab_current 判断：这个 Kivy 构建里 grab() 只往
        # grab_list 里追加，grab_current 一直是 None（实测），拿它比会永远
        # 判成「不是我的手指」，拖动和抬手全部失效。
        if self._touch is None or touch is not self._touch:
            return False
        self._update(*self.to_local_point(touch))
        return True

    def on_touch_up(self, touch):
        if self._touch is None or touch is not self._touch:
            return False
        lx, ly = self.to_local_point(touch)
        # 补一帧不节流的预览：抬手看到的放大图必须就是取到的那个像素
        self._update(lx, ly, force=True)
        hit = self.sample_at(lx, ly)
        touch.ungrab(self)
        self._touch = None
        self._mark(None, None)
        if hit is not None and self.on_commit is not None:
            self.on_commit(hit[0])
        return True


class PickOverlay(ModalView):
    """全屏取色层。

    照片铺满整块屏幕，取色区**不放进 ScrollView** —— 这就是这一版和上一版
    最大的区别：手指坐标和照片的绘制位置从此处在同一套坐标里，没有页面
    滚动、没有卡片偏移参与运算。

    放大预览放在**顶部**：手指按在照片中下部时，它不会被自己的手挡住。
    """

    def __init__(self, screen, **kwargs):
        kwargs.setdefault("size_hint", (1, 1))
        kwargs.setdefault("auto_dismiss", False)
        kwargs.setdefault("background_color", (0, 0, 0, 0.97))
        super().__init__(**kwargs)
        self.screen = screen

        root = BoxLayout(orientation="vertical", spacing=D(6),
                         padding=[0, D(6), 0, D(8)])

        bar = BoxLayout(size_hint_y=None, height=D(46), spacing=D(10),
                        padding=[D(14), 0, D(14), 0])
        close = GhostButton(text="关闭", size_hint_x=None, width=D(78))
        close.bind(on_release=lambda *_: self.dismiss())
        self._hex = Title(text="#000000", font_size=S(22), halign="right")
        bar.add_widget(close)
        bar.add_widget(self._hex)
        root.add_widget(bar)

        self.preview = ZoomPreview()
        self.preview.padding = [D(14), 0, D(14), 0]
        root.add_widget(self.preview)

        self.stage = PhotoStage(on_sample=self._on_sample,
                                on_commit=self._on_commit,
                                source=getattr(screen, "photo_path", "") or "")
        self.stage.pil = getattr(screen, "pil_image", None)
        root.add_widget(self.stage)
        self.add_widget(root)
        self.preview.reset()
        self._fit_window()

    # ------------------------------------------------------------ 尺寸
    def on_open(self):
        self._fit_window()

    def _fit_window(self):
        """铺满窗口。

        取色区能不能对齐，全靠这一步：只要这一层和它的父容器都在原点、
        且尺寸等于窗口，``touch.pos`` 和控件坐标就是同一套。
        """
        try:
            from kivy.core.window import Window
            self.size = Window.size
            self.pos = (0, 0)
        except Exception:
            pass

    # ------------------------------------------------------------ 回调
    def _on_sample(self, rgb, u, v, dw, dh, force=False):
        self._hex.text = "#%02X%02X%02X" % tuple(rgb[:3])
        self.preview.update(self.stage.pil, rgb, u, v, dw, dh, force=force)

    def _on_commit(self, rgb):
        self.preview.commit(rgb)
        self.screen.apply_sample(rgb)


class TapArea(FloatLayout):
    """一块「点一下就触发」的区域。

    不用 Button，是因为里面要放一张 ``contain`` 的缩略图；``Image`` 本身
    不吃触摸，事件会落回这里。按下只记位置、抬手才触发，中间位移超过阈值
    就当是在滑页面，避免划着划着突然弹出全屏层。
    """

    def __init__(self, on_tap=None, **kwargs):
        super().__init__(**kwargs)
        self.on_tap = on_tap
        self._down = None

    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True
        if self.on_tap is None or not self.collide_point(*touch.pos):
            return False
        self._down = (touch.uid, touch.x, touch.y)
        return True

    def on_touch_up(self, touch):
        started, self._down = self._down, None
        if started and started[0] == touch.uid:
            moved = abs(touch.x - started[1]) + abs(touch.y - started[2])
            if moved <= D(14) and self.collide_point(*touch.pos):
                self.on_tap()
                return True
        return super().on_touch_up(touch)


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
        gal.add_widget(Dim(text="从图库取色：点下面的照片，进入全屏取色",
                           font_size=S(FS_SMALL)))
        pick_btn = AccentButton(text="选择照片")
        pick_btn.bind(on_release=lambda *_: self._choose_photo())
        self._pick_btn = pick_btn
        gal.add_widget(pick_btn)

        # 用 FloatLayout 而不是 RelativeLayout：RelativeLayout 里子控件的 pos
        # 是「相对单位」(0~1)，里面子控件的 pos 也会是 0~1 的比值，
        # 拿它去算屏幕坐标会得到 y=0 这种结果。
        holder = TapArea(self.open_picker, size_hint_y=None,
                         height=D(self.HOLDER_MIN))
        self._holder = holder
        with holder.canvas.before:
            Color(*hex_to_kivy(BG_ALT))
            self._holder_bg = RoundedRectangle(pos=holder.pos, size=holder.size,
                                               radius=[D(10)])
        holder.bind(pos=lambda inst, val: setattr(self._holder_bg, "pos", val),
                    size=lambda inst, val: setattr(self._holder_bg, "size", val))

        # pos_hint 必须显式给：FloatLayout 不会给没有 pos_hint 的子控件定位，
        # 否则图片会跑到窗口左下角 (0,0)。
        self._thumb = Image(source=blank_png(), size_hint=(1, 1),
                            pos_hint={"x": 0, "y": 0}, fit_mode="contain",
                            nocache=True)
        holder.add_widget(self._thumb)

        self._img_hint = Dim(text="尚未选择照片", font_size=S(FS_SMALL),
                             halign="center", pos_hint={"center_x": 0.5,
                                                        "center_y": 0.5})
        self._img_hint.bind(width=lambda inst, val: setattr(inst, "text_size",
                                                            (val, None)))
        holder.add_widget(self._img_hint)
        gal.add_widget(holder)

        self._open_hint = Dim(text="点照片进入全屏取色", font_size=S(FS_SMALL),
                              halign="center")
        self._open_hint.bind(width=lambda inst, val: setattr(inst, "text_size",
                                                             (val, None)))
        gal.add_widget(self._open_hint)
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
        self._thumb.source = photo.path     # 每次都是新的缓存文件名，不会命中旧缓存
        # 清文字而不是 opacity=0：这个开关拨过一次之后，控件的绘制状态就再也
        # 回不来（照片上的描边曾因此整层消失），没必要去碰它。
        self._img_hint.text = ""
        self._fit_holder(photo.width, photo.height)
        # 选完照片直接进全屏取色：手机照片就那么大一块，缩在小卡片里根本
        # 点不准，全屏之后每个像素都放大了。
        self.open_picker()

    def open_picker(self):
        """打开全屏取色层。"""
        if self.pil_image is None:
            self.app.toast("先选一张照片")
            return
        self._overlay = PickOverlay(self)
        # 不要淡入动画：动画期间 on_open 还没跑，尺寸没铺满窗口，
        # 那几百毫秒里按下去会偏。
        self._overlay.open(animation=False)

    def apply_sample(self, rgb):
        """全屏层里松手确认的颜色，写回全局当前颜色。"""
        self.app.color_set(rgb, source="screen")

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
    # 全屏取色层的回调在 PickOverlay 里，这里只需要把最终颜色写回全局。

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
