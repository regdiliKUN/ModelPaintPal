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
from mobile.screens.pick_screen import (  # noqa: E402
    PickOverlay, PhotoStage, ZoomPreview)

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


class _Touch:
    """够用的触摸替身。

    注意：这里不再模拟「窗口坐标 vs 父容器坐标」的差异 —— 新的取色层把
    取色区做成铺满窗口的独立层，两者本来就是同一套坐标，``x`` / ``y``
    就是要用的那份值。``grab`` 相关的方法是给按下→拖动→抬手链路用的。
    """

    def __init__(self, x, y, uid=1):
        self.uid = uid
        self.x = x
        self.y = y
        self.grab_current = None

    @property
    def pos(self):
        return (self.x, self.y)

    def grab(self, widget):
        self.grab_current = widget

    def ungrab(self, widget):
        if self.grab_current is widget:
            self.grab_current = None


class SampleMappingTest(unittest.TestCase):
    """取样几何与手势：居中留白、贴边夹取、按下即取、松手才写回。"""

    W, H = 300, 400          # 控件比图片「瘦高」，上下会留白

    def setUp(self):
        self.photo = photomod._load_bytes(make_quad_bytes())
        self.samples = []        # 每次预览刷新 (rgb, u, v, dw, dh, force)
        self.commits = []        # 松手确认的颜色
        self.stage = PhotoStage(on_sample=self._sink,
                                on_commit=self.commits.append,
                                size=(self.W, self.H), pos=(0, 0),
                                source=self.photo.path)
        self.stage.pil = self.photo.pil

    def _sink(self, rgb, u, v, dw, dh, force):
        self.samples.append((rgb, u, v, dw, dh, force))

    def _local_point(self, ix, iy):
        """图片像素坐标（PIL，自上而下）→ 控件局部坐标（左下角原点）。"""
        x0, y0, dw, dh = self.stage.local_image_rect()
        w, h = self.photo.pil.size
        return (x0 + (ix + 0.5) / float(w) * dw,
                y0 + (1.0 - (iy + 0.5) / float(h)) * dh)

    def _quad_point(self, name):
        w, h = self.photo.pil.size
        ix = w * 0.25 if "左" in name else w * 0.75
        iy = h * 0.25 if "上" in name else h * 0.75
        return self._local_point(int(ix), int(iy))

    # -------------------------------------------------------------- 几何
    def test_local_rect_is_centered(self):
        x0, y0, dw, dh = self.stage.local_image_rect()
        self.assertAlmostEqual(dw, self.W, delta=1)        # 宽度受限
        self.assertLess(dh, self.H)
        self.assertAlmostEqual(x0, 0, delta=1, msg="水平没居中")
        self.assertAlmostEqual(y0, (self.H - dh) / 2.0, delta=1, msg="垂直没居中")

    def test_each_quadrant_samples_right_color(self):
        for name, rgb in COLORS.items():
            got = self.stage.sample_at(*self._quad_point(name))
            self.assertIsNotNone(got)
            self.assertEqual(got[0], rgb, f"{name} 象限取到的颜色不对")

    def test_letterbox_is_clamped(self):
        """点在留白（图片外）要被夹到最近的边缘像素，而不是拒绝。"""
        x0, y0, dw, dh = self.stage.local_image_rect()
        # 取左半边，避开正中那条象限分界线
        got = self.stage.sample_at(x0 + dw * 0.25, self.H - 1)
        self.assertIsNotNone(got, "留白处直接拒绝了，用户会以为点坏了")
        self.assertAlmostEqual(got[2], 1.0, places=3)
        self.assertEqual(got[0], COLORS["左上"], "夹取后应取到图片最上面一行")

    # -------------------------------------------------------------- 手势
    def test_touch_down_samples_immediately(self):
        t = _Touch(*self._quad_point("右上"))
        self.assertTrue(self.stage.on_touch_down(t))
        self.assertTrue(self.samples, "按下没有立刻取样")
        self.assertEqual(self.samples[-1][0], COLORS["右上"])

    def test_touch_down_marks_sample_point(self):
        """按下要记下「正在取哪个像素」——下方放大图靠它画准星。"""
        x, y = self._quad_point("左下")
        self.stage.on_touch_down(_Touch(x, y))
        self.assertTrue(self.stage.sampling)
        cx, cy = self.stage.sample_center
        self.assertAlmostEqual(cx, x, delta=1.5)
        self.assertAlmostEqual(cy, y, delta=1.5)

    def test_mark_cleared_after_release(self):
        t = _Touch(*self._quad_point("左上"))
        self.stage.on_touch_down(t)
        self.stage.on_touch_up(t)
        self.assertFalse(self.stage.sampling, "抬手后还在显示「正在取色」")

    def test_drag_updates_preview(self):
        t = _Touch(*self._quad_point("左上"))
        self.stage.on_touch_down(t)
        t.x, t.y = self._quad_point("右下")
        self.stage.on_touch_move(t)
        self.assertEqual(self.samples[-1][0], COLORS["右下"],
                         "拖动后放大预览没跟上手指")

    def test_release_commits_once(self):
        t = _Touch(*self._quad_point("左下"))
        self.stage.on_touch_down(t)
        self.stage.on_touch_up(t)
        self.assertEqual(self.commits, [COLORS["左下"]], "松手没写回颜色，或写回了多次")

    def test_press_outside_is_ignored(self):
        t = _Touch(-40, 10)
        self.assertFalse(self.stage.on_touch_down(t))
        self.assertEqual(self.commits, [])


class IdentitySpaceTest(unittest.TestCase):
    """取色层的坐标约定：``touch.pos - self.pos`` 必须就是取样坐标。

    上一版用 ``get_window_matrix()`` 推导「控件画在哪」、再用 ``touch.sx/sy``
    反推手指位置，两条推导在手机上都可能不准（实测仍整体偏下）。这一版改成
    「父容器坐标 = 窗口坐标 = 局部坐标 + self.pos」这一条唯一的关系，
    所以这里把它钉死：控件放在任何位置，取样都必须对得上。
    """

    def setUp(self):
        self.photo = photomod._load_bytes(make_quad_bytes())
        self.samples = []
        # 故意把控件放在一个不为零的位置：父容器是取色层，它铺满窗口
        self.stage = PhotoStage(on_sample=lambda *a: self.samples.append(a),
                                size=(600, 500), pos=(0, 120),
                                source=self.photo.path)
        self.stage.pil = self.photo.pil

    def _at(self, name):
        x0, y0, dw, dh = self.stage.local_image_rect()
        w, h = self.photo.pil.size
        ix = w * 0.25 if "左" in name else w * 0.75
        iy = h * 0.25 if "上" in name else h * 0.75
        lx = x0 + (ix + 0.5) / float(w) * dw
        ly = y0 + (1.0 - (iy + 0.5) / float(h)) * dh
        return lx, ly

    def test_local_point_subtracts_pos(self):
        lx, ly = self._at("右上")
        touch = _Touch(lx + self.stage.x, ly + self.stage.y)
        got = self.stage.to_local_point(touch)
        self.assertAlmostEqual(got[0], lx, places=3)
        self.assertAlmostEqual(got[1], ly, places=3)

    def test_press_uses_pos_relative_coordinates(self):
        """控件不在原点时，按下去取的必须是手指底下那个色。"""
        for name, rgb in COLORS.items():
            lx, ly = self._at(name)
            touch = _Touch(lx + self.stage.x, ly + self.stage.y)
            self.assertTrue(self.stage.on_touch_down(touch), f"{name} 按下被拒")
            self.assertEqual(self.samples[-1][0], rgb, f"{name} 取色错位")
            self.stage.on_touch_up(touch)

    def test_drag_and_release_use_same_space_as_press(self):
        lx, ly = self._at("左上")
        t = _Touch(lx + self.stage.x, ly + self.stage.y)
        self.stage.on_touch_down(t)
        lx2, ly2 = self._at("右下")
        t.x, t.y = lx2 + self.stage.x, ly2 + self.stage.y
        self.stage.on_touch_move(t)
        self.assertEqual(self.samples[-1][0], COLORS["右下"], "拖动时坐标跑偏")
        self.stage.on_touch_up(t)
        self.assertEqual(self.samples[-1][0], COLORS["右下"], "抬手时坐标跑偏")


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


class _FakeScreen:
    """PickOverlay 只依赖这三样东西。"""

    def __init__(self, photo):
        self.pil_image = photo.pil
        self.photo_path = photo.path
        self.applied = []

    def apply_sample(self, rgb):
        self.applied.append(rgb)


class OverlayTest(unittest.TestCase):
    """全屏取色层：铺满窗口、接管照片、松手把颜色写回主界面。"""

    def setUp(self):
        self.photo = photomod._load_bytes(make_quad_bytes())
        self.screen = _FakeScreen(self.photo)
        self.overlay = PickOverlay(self.screen)
        self.overlay._fit_window()

    def test_fills_window(self):
        from kivy.core.window import Window

        self.assertAlmostEqual(self.overlay.x, 0, delta=1)
        self.assertAlmostEqual(self.overlay.y, 0, delta=1)
        self.assertAlmostEqual(self.overlay.width, Window.width, delta=1)
        self.assertAlmostEqual(self.overlay.height, Window.height, delta=1)

    def test_stage_owns_photo(self):
        self.assertIs(self.overlay.stage.pil, self.photo.pil)
        self.assertEqual(self.overlay.stage.source, self.photo.path)

    def test_sampling_updates_preview(self):
        t = _Touch(10, 10)
        self.overlay.stage.on_touch_down(t)
        self.assertGreater(self.overlay.preview.last_span, 0,
                           "按住之后放大图没出来")
        self.overlay.stage.on_touch_up(t)

    def test_release_writes_color_back(self):
        from kivy.core.window import Window

        stage = self.overlay.stage
        x0, y0, dw, dh = stage.local_image_rect()
        t = _Touch(x0 + dw * 0.25, y0 + dh * 0.75)      # 左上象限
        stage.on_touch_down(t)
        stage.on_touch_up(t)
        self.assertEqual(self.screen.applied, [COLORS["左上"]])
        self.assertTrue(0 <= t.x <= Window.width)


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

    def tearDown(self):
        overlay = getattr(self.scr, "_overlay", None)
        if overlay is not None and getattr(overlay, "_is_open", False):
            overlay.dismiss(force=True)

    def test_photo_becomes_visible(self):
        photo = photomod._load_bytes(make_quad_bytes())
        self.scr._on_photo_picked(photo, "")

        self.assertEqual(self.scr._thumb.source, photo.path,
                         "缩略图还是占位图 —— 用户会以为没选上")
        self.assertEqual(self.scr._img_hint.text, "",
                         "「尚未选择照片」的提示没消失")
        self.assertIsNotNone(self.scr._thumb.texture,
                             "缩略图没载入纹理，屏幕上会是空的")
        self.assertIs(self.scr.pil_image, photo.pil)

    def test_opens_fullscreen_picker(self):
        """选完照片直接进全屏取色 —— 缩在小卡片里点不准。"""
        photo = photomod._load_bytes(make_quad_bytes())
        self.scr._on_photo_picked(photo, "")
        overlay = getattr(self.scr, "_overlay", None)
        self.assertIsNotNone(overlay, "选完照片没有打开全屏取色层")
        self.assertIsInstance(overlay, PickOverlay)
        self.assertTrue(overlay._is_open)
        self.assertIs(overlay.stage.pil, photo.pil)
        self.assertEqual(overlay.stage.source, photo.path)

    def test_apply_sample_sets_current_color(self):
        self.scr.apply_sample((18, 52, 86))
        self.assertEqual(tuple(self.app.current_rgb), (18, 52, 86))

    def test_picker_needs_photo(self):
        self.scr.pil_image = None
        self.scr.open_picker()
        self.assertTrue(any("照片" in t for t in self.toasts),
                        "没有照片时点取色应该提示，而不是打开一个空白层")

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

    def test_pick_error_is_reported(self):
        before = self.scr._thumb.source
        self.scr._on_photo_picked(None, "照片载入失败（FileNotFoundError）")
        self.assertEqual(self.scr._thumb.source, before)
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
