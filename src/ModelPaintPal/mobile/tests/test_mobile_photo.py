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
from mobile.screens.pick_screen import LongPressImage  # noqa: E402

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
        self.samples = []
        self.hints = []

    def on_sampled(self, px, rel_x, rel_y):
        self.samples.append((px, rel_x, rel_y))

    def on_hold_hint(self, msg="长按"):
        self.hints.append(msg)


class _FakeTimer:
    def cancel(self):
        pass


class SampleMappingTest(unittest.TestCase):
    """坐标映射：``fit_mode="contain"`` 居中留白后，原来的换算会整体偏移。"""

    W, H = 300, 400          # 控件比图片「瘦高」，上下会留白

    def setUp(self):
        self.photo = photomod._load_bytes(make_quad_bytes())
        self.owner = _FakeOwner(self.photo.pil)
        self.img = LongPressImage(self.owner, size=(self.W, self.H),
                                  pos=(0, 0), source=self.photo.path)

    def _screen_point(self, ix, iy):
        """图片像素坐标 → 屏幕坐标（取像素中心）。"""
        x0, y0, dw, dh = self.img.draw_rect()
        w, h = self.photo.pil.size
        rel_x = (ix + 0.5) / w
        rel_y = 1.0 - (iy + 0.5) / h
        return x0 + rel_x * dw, y0 + rel_y * dh

    def test_draw_rect_is_centered(self):
        rect = self.img.draw_rect()
        self.assertIsNotNone(rect, "拿不到绘制矩形就无法吸色")
        _, y0, dw, dh = rect
        self.assertAlmostEqual(dw, self.W, delta=1.0)
        self.assertAlmostEqual(dh, self.W, delta=1.0)
        self.assertAlmostEqual(y0, (self.H - dh) / 2.0, delta=1.0,
                               msg="图片应上下居中，否则取样位置整体偏移")

    def test_draw_rect_uses_window_coords(self):
        """父容器有偏移时，draw_rect 必须换算成窗口坐标。

        实机上图片放在 ScrollView 里的卡片里，``img.pos`` 只是内容区内的相对值
        （实测和窗口坐标差 1000px 以上），不换算会让吸色整体偏上/偏左。
        """
        from kivy.uix.floatlayout import FloatLayout

        parent = FloatLayout(size=(self.W, self.H), pos=(100, 50))
        img = LongPressImage(self.owner, size_hint=(1, 1),
                             pos_hint={"x": 0, "y": 0},
                             source=self.photo.path)
        parent.add_widget(img)
        parent.do_layout()

        x0, y0, dw, dh = img.draw_rect()
        self.assertAlmostEqual(x0, 100, delta=1.0,
                               msg="没算上父容器的 x 偏移")
        self.assertAlmostEqual(y0, 50 + (self.H - dh) / 2.0, delta=1.0,
                               msg="没算上父容器的 y 偏移")

    def test_each_quadrant_samples_right_color(self):
        for name, rgb in COLORS.items():
            ix = QUAD // 2 + (QUAD if "右" in name else 0)
            iy = QUAD // 2 + (QUAD if "下" in name else 0)
            sx, sy = self._screen_point(ix, iy)
            self.img._down = (sx, sy)
            self.owner.samples.clear()
            self.img._do_sample()
            self.assertEqual(len(self.owner.samples), 1,
                             f"点 {name} 象限没有取到色")
            self.assertEqual(self.owner.samples[0][0], rgb,
                             f"{name} 象限取到的颜色不对")

    def test_tap_on_letterbox_is_ignored(self):
        x0, y0, _dw, _dh = self.img.draw_rect()
        self.img._down = (x0 + 5, y0 - 10)             # 落在下方留白里
        self.owner.samples.clear()
        self.img._do_sample()
        self.assertEqual(self.owner.samples, [], "留白处不该取色")
        self.assertTrue(self.owner.hints, "点到留白要提示用户")

    def test_drag_cancels_sampling(self):
        class Touch:
            uid = 1
            x = 100.0
            y = 100.0

        t = Touch()
        self.img._touch = t
        self.img._down = (100.0, 100.0)
        self.img._timer = _FakeTimer()
        self.img._on_move(None, t)                     # 未超过阈值 → 继续等
        self.assertIsNotNone(self.img._touch)
        t.x = 100.0 + self.img.SLOP * 4
        self.img._on_move(None, t)                     # 超过阈值 → 当作滚动
        self.assertIsNone(self.img._touch, "拖动时没放弃取样，页面会滑不动")

    def test_quick_tap_gives_hint(self):
        class Touch:
            uid = 2
            x = 10.0
            y = 10.0

        self.img._touch = Touch()
        self.img._timer = _FakeTimer()                 # 0.3s 还没到就抬手了
        self.img._on_up(None, self.img._touch)
        self.assertTrue(self.owner.hints, "轻点应提示要长按")


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

        self.assertEqual(self.scr._img.opacity, 1,
                         "图片控件还是全透明 —— 用户会以为没选上")
        self.assertEqual(self.scr._img_hint.opacity, 0,
                         "「尚未选择照片」的提示没消失")
        self.assertEqual(self.scr._img.source, photo.path)
        self.assertIsNotNone(self.scr._img.texture, "图片没载入纹理，屏幕上会是空的")
        self.assertIs(self.scr.pil_image, photo.pil)
        self.assertTrue(self.toasts)

    def test_holder_height_is_fixed(self):
        """载入照片时不能改取色区高度：那会触发重排，把同卡按钮宽度压成一条。

        这是实机截图里发现的问题（按钮从 1328px 塌成 26px），所以固定为常量。
        """
        before = self.scr._holder.height
        self.assertGreaterEqual(before, self.D(200), "取色区太矮，长按照片很难点准")
        photo = photomod._load_bytes(make_quad_bytes())
        self.scr._on_photo_picked(photo, "")
        self.assertEqual(self.scr._holder.height, before,
                         "取色区高度不该随照片载入变化")

    def test_pick_error_is_reported(self):
        before = self.scr._img.opacity
        self.scr._on_photo_picked(None, "照片载入失败（FileNotFoundError）")
        self.assertEqual(self.scr._img.opacity, before)
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
