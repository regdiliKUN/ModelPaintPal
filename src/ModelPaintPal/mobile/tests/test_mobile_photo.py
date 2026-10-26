# -*- coding: utf-8 -*-
"""选图与吸色的回归测试。

覆盖用户实机遇到的 bug：**在图库里选好照片并确认后，界面上什么都没出现**。
根因是 ``plyer.filechooser`` 在 Android 上返回 ``content://`` URI 的假路径，
PIL 打不开 → 掉进异常分支 → 图片区永远停在「尚未选择照片」。
所以这里覆盖的是「字节 → 照片 → 界面」整条链路，而不只是 PIL 能不能开图。
"""

import io
import os
import sys
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
os.environ.setdefault("KIVY_NO_ARGS", "1")

ROOT = Path(__file__).resolve().parents[2]  # src/ModelPaintPal
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mobile.bootstrap  # noqa: E402  —— 先重定向用户目录

_ = mobile.bootstrap.ROOT  # 确保路径重定向副作用已执行
from PIL import Image as PILImage  # noqa: E402

from mobile import photo as photomod  # noqa: E402
from mobile.screens.pick_screen import ZoomPickImage, ZoomPreview  # noqa: E402

QUAD = 200
# 四象限测试图：左上红、右上绿、左下蓝、右下黄
COLORS = {
    "左上": (255, 0, 0),
    "右上": (0, 255, 0),
    "左下": (0, 0, 255),
    "右下": (255, 255, 0),
}


def make_quad_bytes() -> bytes:
    img = PILImage.new("RGB", (QUAD * 2, QUAD * 2), (0, 0, 0))
    img.paste(COLORS["左上"], (0, 0, QUAD, QUAD))
    img.paste(COLORS["右上"], (QUAD, 0, QUAD * 2, QUAD))
    img.paste(COLORS["左下"], (0, QUAD, QUAD, QUAD * 2))
    img.paste(COLORS["右下"], (QUAD, QUAD, QUAD * 2, QUAD * 2))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class PhotoDecodeTest(unittest.TestCase):
    """字节 → Photo：这是原来断掉的第一环。"""

    def test_bytes_become_photo(self):
        p = photomod._load_bytes(make_quad_bytes())
        self.assertEqual(p.pil.mode, "RGB")
        self.assertEqual(p.pil.size, (QUAD * 2, QUAD * 2))
        self.assertTrue(os.path.exists(p.path), "必须落成本地缓存文件给 Image 用")
        self.assertGreater(os.path.getsize(p.path), 0)

    def test_pixel_colors_survive(self):
        p = photomod._load_bytes(make_quad_bytes())
        for name, rgb in COLORS.items():
            x = QUAD // 2 + (QUAD if "右" in name else 0)
            y = QUAD // 2 + (QUAD if "下" in name else 0)
            self.assertEqual(p.pil.getpixel((x, y)), rgb,
                             f"{name} 象限颜色被破坏")

    def test_large_photo_is_downscaled(self):
        buf = io.BytesIO()
        PILImage.new("RGB", (4000, 3000), (12, 34, 56)).save(buf, "JPEG")
        p = photomod._load_bytes(buf.getvalue())
        self.assertLessEqual(max(p.pil.size), photomod.MAX_EDGE,
                             "超大照片必须缩到长边上限内，否则纹理上传会失败")

    def test_exif_rotation_is_applied(self):
        """手机竖拍的照片带 EXIF 旋转标记，Kivy 不认，必须自己摆正。"""
        img = PILImage.new("RGB", (400, 200), (200, 10, 10))
        exif = img.getexif()
        exif[274] = 6                                  # Orientation: 顺时针 90°
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=exif)
        p = photomod._load_bytes(buf.getvalue())
        self.assertEqual(p.pil.size, (200, 400),
                         "带旋转标记的照片没摆正，长按取样会取到错误位置")

    def test_cache_is_pruned(self):
        for _ in range(photomod.KEEP_CACHE + 3):
            photomod._load_bytes(make_quad_bytes())
            time.sleep(0.002)                          # 让 mtime 可区分
        left = list(photomod.cache_dir().glob("picked-*.png"))
        self.assertLessEqual(len(left), photomod.KEEP_CACHE,
                             "缓存没清理，会一直吃手机存储")

    def test_file_uri_is_read(self):
        tmp = photomod.cache_dir() / "unit-uri.png"
        tmp.write_bytes(make_quad_bytes())

        class Uri:                                     # 模拟 Android Uri
            def getScheme(self):
                return "file"

            def getPath(self):
                return str(tmp)

        try:
            self.assertEqual(photomod._read_uri(Uri()), make_quad_bytes())
        finally:
            tmp.unlink()


class _FakeOwner:
    """替代 PickScreen，只记录回调。"""

    def __init__(self, pil):
        self.pil_image = pil
        self.samples = []        # [(rgb, u, v)]
        self.zooms = []          # [(rgb, u, v, dw, dh, force)]
        self.resets = 0

    def on_sampled(self, px, rel_x, rel_y):
        self.samples.append((px, rel_x, rel_y))

    def zoom_update(self, rgb, u, v, dw, dh, force=False):
        self.zooms.append((rgb, u, v, dw, dh, force))

    def zoom_reset(self):
        self.resets += 1


class _Touch:
    """够用的触摸替身：只需要 uid / x / y / pos。"""

    def __init__(self, x, y, uid=1):
        self.uid = uid
        self.x = x
        self.y = y

    @property
    def pos(self):
        return (self.x, self.y)


class SampleMappingTest(unittest.TestCase):
    """坐标映射与手势：居中留白、贴边夹取、按下即取、松手才写回。"""

    W, H = 300, 400          # 控件比图片「瘦高」，上下会留白

    def setUp(self):
        self.photo = photomod._load_bytes(make_quad_bytes())
        self.owner = _FakeOwner(self.photo.pil)
        self.img = ZoomPickImage(self.owner, size=(self.W, self.H),
                                 pos=(0, 0), source=self.photo.path)

    def tearDown(self):
        if self.img._touch is not None:
            self.img._end()

    def _local_point(self, ix, iy):
        """图片像素坐标 → 控件局部坐标（取像素中心）。"""
        x0, y0, dw, dh = self.img.local_image_rect()
        w, h = self.photo.pil.size
        rel_x = (ix + 0.5) / w
        rel_y = 1.0 - (iy + 0.5) / h
        return x0 + rel_x * dw, y0 + rel_y * dh

    def _quad_point(self, name):
        ix = QUAD // 2 + (QUAD if "右" in name else 0)
        iy = QUAD // 2 + (QUAD if "下" in name else 0)
        return self._local_point(ix, iy)

    def test_local_rect_is_centered(self):
        rect = self.img.local_image_rect()
        self.assertIsNotNone(rect, "拿不到绘制矩形就无法吸色")
        _, y0, dw, dh = rect
        self.assertAlmostEqual(dw, self.W, delta=1.0)
        self.assertAlmostEqual(dh, self.W, delta=1.0)
        self.assertAlmostEqual(y0, (self.H - dh) / 2.0, delta=1.0,
                               msg="图片应上下居中，否则取样位置整体偏移")

    def test_touch_pos_is_parent_space(self):
        """触摸坐标是「父容器坐标系」，不是窗口坐标系。

        实机上照片在 ScrollView 里的卡片里，Kivy 派发给控件的 ``touch.pos``
        已经被 ScrollView 平移过（实测和窗口坐标差 700px 以上，滚得越多差越大）。
        旧代码拿窗口坐标的图片矩形去比 ``touch.pos``，于是每次都被判成
        「点在图外」，v 被夹到图片另一头 —— 用户看到的就是「吸色经常失败、
        点上面还说不要点边框」。这里用「父容器有偏移 + 控件不在原点」把它钉住。
        """
        from kivy.uix.floatlayout import FloatLayout

        parent = FloatLayout(size=(400, 500), pos=(100, 50))
        img = ZoomPickImage(self.owner, size_hint=(1, 1),
                            pos_hint={"x": 0, "y": 0},
                            source=self.photo.path)
        parent.add_widget(img)
        parent.do_layout()

        # 控件局部要取右上象限的中心，先算局部点，再还原成 Kivy 会派发的父坐标
        lx0, ly0, dw, dh = img.local_image_rect()
        local = (lx0 + dw * 0.75, ly0 + dh * 0.75)
        got = img.sample_at(*local)
        self.assertEqual(got[0], COLORS["右上"], "局部坐标取样就不对")

        touch = _Touch(img.x + local[0], img.y + local[1])
        self.assertTrue(img.on_touch_down(touch))
        self.assertEqual(self.owner.zooms[-1][0], COLORS["右上"],
                         "touch.pos 被当成窗口坐标算了，取到的是别的像素")
        img._end()

    def test_each_quadrant_samples_right_color(self):
        for name, rgb in COLORS.items():
            got = self.img.sample_at(*self._quad_point(name))
            self.assertIsNotNone(got, f"点 {name} 象限没有取到色")
            self.assertEqual(got[0], rgb, f"{name} 象限取到的颜色不对")

    def test_letterbox_is_clamped(self):
        """点到照片上方的留白，要夹到顶边继续取色，而不是弹「不能点边框」。

        用户反馈的就是这条：照片本身是深色截图，和深色底框分不清，
        手指偏出一两毫米就会命中「请按住照片本身，四周灰色留白处不能取色」。
        """
        x0, y0, dw, dh = self.img.local_image_rect()
        for dx in (-30, 0, 30):
            # 取左半边，避开正中那条象限分界线
            got = self.img.sample_at(x0 + dw * 0.25 + dx, y0 + dh + 60)
            self.assertIsNotNone(got)
            rgb, _u, v = got
            self.assertEqual(v, 1.0, "没有夹到图片顶边")
            self.assertEqual(rgb, COLORS["左上"], "顶边左半边应是左上象限的颜色")

    def test_touch_down_samples_immediately(self):
        """按下就出放大预览，不用等 0.3 秒 —— 这是「点了没反应」的根因。"""
        t = _Touch(*self._quad_point("右上"))
        self.assertTrue(self.img.on_touch_down(t),
                        "取色时应该吃掉这一下，否则页面会跟着滚")
        self.assertEqual(self.img._touch, t)
        self.assertEqual(len(self.owner.zooms), 1, "按下没有立刻刷新放大预览")
        self.assertEqual(self.owner.zooms[0][0], COLORS["右上"])
        self.assertEqual(self.owner.samples, [], "还没松手就写回颜色了")

    def test_touch_down_marks_sample_point(self):
        """按下要记下「正在取哪个像素」——下方放大图靠它画准星。"""
        x, y = self._quad_point("右下")
        self.img.on_touch_down(_Touch(x, y))
        self.assertTrue(self.img.sampling, "按下后没有任何取样状态")
        cx, cy = self.img.sample_center
        self.assertAlmostEqual(cx, x, delta=2.0)
        self.assertAlmostEqual(cy, y, delta=2.0)

        x0, y0, dw, dh = self.img.local_image_rect()
        self.assertGreaterEqual(cx, x0 - 1)
        self.assertLessEqual(cx, x0 + dw + 1, "取样点跑到图片外面去了")

    def test_mark_cleared_after_release(self):
        t = _Touch(*self._quad_point("左上"))
        self.img.on_touch_down(t)
        self.img._on_up(None, t)
        self.assertFalse(self.img.sampling, "松手后还停在取样状态")

    def test_drag_updates_preview(self):
        t = _Touch(*self._quad_point("左上"))
        self.img.on_touch_down(t)
        t.x, t.y = self._quad_point("右下")
        self.img._on_move(None, t)
        self.assertEqual(self.owner.zooms[-1][0], COLORS["右下"],
                         "拖动后放大预览没跟上手指")

    def test_release_commits_once(self):
        t = _Touch(*self._quad_point("左下"))
        self.img.on_touch_down(t)
        self.img._on_up(None, t)
        self.assertEqual(len(self.owner.samples), 1, "松手应该确认一次颜色")
        self.assertEqual(self.owner.samples[0][0], COLORS["左下"])
        self.assertIsNone(self.img._touch, "松手后没清掉触摸状态")
        self.assertTrue(self.owner.zooms[-1][5],
                        "最后一帧没强制刷新，会被节流吞掉")

    def test_scroll_is_frozen_while_picking(self):
        """取色期间必须锁住 ScrollView，否则手指下面的内容会跟着跑。"""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.scrollview import ScrollView

        sv = ScrollView(do_scroll_x=False, do_scroll_y=True, size=(self.W, self.H))
        inner = BoxLayout(size_hint_y=None, height=self.H)
        sv.add_widget(inner)
        inner.add_widget(self.img)

        self.img.on_touch_down(_Touch(*self._quad_point("左上")))
        self.assertFalse(sv.do_scroll_y, "取色时页面还能滚动")
        self.img._on_up(None, self.img._touch)
        self.assertTrue(sv.do_scroll_y, "松手后要恢复滚动")


class ZoomPreviewTest(unittest.TestCase):
    """取样反馈条：放大图必须真的显示「取到的那个像素」，上下不能颠倒。

    历史上这里踩过坑：``v`` 一开始按「自上而下」算，放大窗口整个上下翻过来，
    取到的是照片上对称位置的另一个颜色。四象限异色图就是为了咬住这件事。
    """

    def setUp(self):
        self.photo = photomod._load_bytes(make_quad_bytes())
        self.preview = ZoomPreview()

    def _zoom_pixels(self):
        return PILImage.open(self.preview._path()).convert("RGB")

    def test_zoom_shows_sampled_pixel(self):
        # 左上象限：u=0.25、v=0.75（左下角为原点）
        self.preview.update(self.photo.pil, COLORS["左上"], 0.25, 0.75,
                            QUAD * 2, QUAD * 2, force=True)
        path = self.preview._path()
        self.assertTrue(os.path.exists(path), "放大图没落盘，Image 就没东西可显示")
        self.assertGreater(self.preview.last_span, 0)

        got = self._zoom_pixels()
        self.assertEqual(got.size[0], got.size[1], "放大图必须是正方形")
        center = got.getpixel((got.size[0] // 2, got.size[1] // 2))
        self.assertEqual(center, COLORS["左上"],
                         "放大图里的颜色和取样值对不上（v 方向算反了？）")

    def test_zoom_follows_sample_point(self):
        for name, rgb in COLORS.items():
            u = 0.25 + (0.5 if "右" in name else 0)
            v = 0.75 - (0.5 if "下" in name else 0)     # 左下角为原点
            self.preview.update(self.photo.pil, rgb, u, v, QUAD * 2, QUAD * 2,
                                force=True)
            got = self._zoom_pixels()
            self.assertEqual(got.getpixel((10, 10)), rgb, f"{name} 象限放大图不对")

    def test_bigger_zoom_means_smaller_window(self):
        self.preview.update(self.photo.pil, (255, 0, 0), 0.25, 0.75, 400, 400,
                            force=True)
        span_six = self.preview.last_span
        self.preview.ZOOM = 12.0
        self.preview.update(self.photo.pil, (255, 0, 0), 0.25, 0.75, 400, 400,
                            force=True)
        self.assertLess(self.preview.last_span, span_six,
                        "倍数调大了，取样窗口却没变小，等于没放大")

    def test_swatch_and_hex_follow_rgb(self):
        self.preview.update(self.photo.pil, (18, 52, 86), 0.5, 0.5, 400, 400,
                            force=True)
        self.assertEqual(self.preview._hex.text, "#123456")
        self.assertAlmostEqual(self.preview._swatch.color[0], 18 / 255.0, places=3)

    def test_reset_clears_preview(self):
        self.preview.update(self.photo.pil, (255, 0, 0), 0.25, 0.75, 400, 400,
                            force=True)
        self.preview.reset()
        self.assertEqual(self.preview.last_span, 0)
        self.assertIn("blank.png", self.preview._pic.source,
                      "换照片后旧放大图还留在预览里")


class ScreenWiringTest(unittest.TestCase):
    """界面接线：照片载入后控件的可见状态必须真的变了。"""

    def setUp(self):
        from kivy.app import App

        import mobile.app as appmod
        from mobile.theme import D

        self.D = D
        self.app = appmod.MppApp()
        App._running_app = self.app          # 让各页的 app 属性可解析（仅测试用）
        self.toasts = []
        self.app.toast = lambda msg: self.toasts.append(msg)
        self.app.build()
        self.scr = self.app.screens["pick"]

    def test_photo_becomes_visible(self):
        photo = photomod._load_bytes(make_quad_bytes())
        self.scr._on_photo_picked(photo, "")

        self.assertEqual(self.scr._img.source, photo.path,
                         "图片控件还是占位图 —— 用户会以为没选上")
        self.assertEqual(self.scr._img_hint.text, "",
                         "「尚未选择照片」的提示没消失")
        self.assertEqual(self.scr._img.source, photo.path)
        self.assertIsNotNone(self.scr._img.texture, "图片没载入纹理，屏幕上会是空的")
        self.assertIs(self.scr.pil_image, photo.pil)
        self.assertTrue(self.toasts)

    def test_preview_follows_sample(self):
        """整页接线：取样回调必须真的把放大图刷出来（用户要看到「正在吸色」）。"""
        photo = photomod._load_bytes(make_quad_bytes())
        self.scr._on_photo_picked(photo, "")
        self.assertEqual(self.scr._preview.last_span, 0, "换图前不该有旧放大图")

        self.scr.zoom_update(COLORS["左上"], 0.25, 0.75,
                             photo.width, photo.height, True)
        self.assertGreater(self.scr._preview.last_span, 0)
        got = PILImage.open(self.scr._preview._path()).convert("RGB")
        self.assertEqual(got.getpixel((10, 10)), COLORS["左上"])

    def test_holder_height_follows_aspect(self):
        """取色区高度按照片比例走，但要夹在上下限之间。

        上限：太高会把下面「手动输入」挤到屏幕外；
        下限：太矮的话手指比图片还宽，根本点不准。
        """
        holder = self.scr._holder
        holder.width = 1000                       # 模拟已经布局出来的宽度

        self.scr._fit_holder(1000, 1000)          # 正方形，理想高度 1000
        self.assertAlmostEqual(holder.height, self.D(self.scr.HOLDER_MAX), delta=1)

        self.scr._fit_holder(2000, 500)           # 4:1 横图，理想高度 250
        self.assertAlmostEqual(holder.height, self.D(self.scr.HOLDER_MIN), delta=1)

        self.scr._fit_holder(1000, 1500)          # 1:1.5 竖图，理想高度 1500
        self.assertAlmostEqual(holder.height, self.D(self.scr.HOLDER_MAX), delta=1)

        self.assertGreaterEqual(self.D(self.scr.HOLDER_MIN), self.D(160),
                                "取色区下限太矮，手指按住会盖住整张图")

    def test_pick_error_is_reported(self):
        before = self.scr._img.source
        self.scr._on_photo_picked(None, "照片载入失败（FileNotFoundError）")
        self.assertEqual(self.scr._img.source, before)
        self.assertTrue(any("失败" in t for t in self.toasts),
                        "载入失败必须告诉用户，不能静默")

    def test_cancel_is_silent(self):
        self.scr._on_photo_picked(None, "")
        self.assertEqual(self.toasts, [], "用户取消不该弹提示")


class PickAndDeliverTest(unittest.TestCase):
    """选图入口的两个约定：回调必须回主线程、连点不能弹两次图库。"""

    def test_callback_is_marshalled_to_main_thread(self):
        """Android 上解码在后台线程完成，回调必须经 Clock 切回主线程。

        直接在子线程里调回调会改 Kivy 控件状态 —— 轻则界面不刷新，
        重则整段绘制指令崩掉，所以这一层必须有人守着。
        """
        from kivy.clock import Clock

        box = {}
        worker = threading.Thread(
            target=lambda: photomod._deliver(
                lambda photo, error: box.update(photo=photo, error=error), "P", ""))
        worker.start()
        worker.join()

        self.assertEqual(box, {}, "回调跑到后台线程里去了")
        Clock.tick()
        self.assertEqual(box.get("photo"), "P")
        self.assertEqual(box.get("error"), "")

    def test_double_tap_opens_one_picker(self):
        calls = []
        saved_pick, saved_android = photomod._pick_desktop, photomod.is_android
        photomod.is_android = lambda: False
        photomod._pick_desktop = lambda finish: calls.append(finish)
        try:
            photomod.pick_image(lambda photo, error: None)
            photomod.pick_image(lambda photo, error: None)
        finally:
            photomod._pick_desktop, photomod.is_android = saved_pick, saved_android
            photomod._pending = False            # 上面故意没有回调，手动复位

        self.assertEqual(len(calls), 1, "连点两下弹了两次图库")


if __name__ == "__main__":
    unittest.main(verbosity=2)
