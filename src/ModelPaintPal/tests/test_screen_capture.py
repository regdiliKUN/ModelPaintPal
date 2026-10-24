# -*- coding: utf-8 -*-
"""屏幕抓取边界与采样正确性测试（R14：边缘取色不越界、取光标处像素）。"""

import unittest

from PIL import Image

from app.core.screen_capture import ScreenCapture, average_pixels


class _FakeCapture(ScreenCapture):
    """用固定虚拟桌面 + 记录 grab 调用，专测 region 的夹取逻辑。"""

    def __init__(self, bounds):
        super().__init__()
        self._bounds = bounds
        self.grab_calls = []

    def monitors(self):
        return [self._bounds]

    def grab(self, left, top, width, height):
        self.grab_calls.append((left, top, width, height))
        return Image.new("RGB", (width, height), (1, 2, 3))


class TestRegionClamp(unittest.TestCase):
    def setUp(self):
        self.bounds = {"left": 0, "top": 0, "width": 1920, "height": 1080}

    def test_cursor_at_top_left_is_clamped(self):
        cap = _FakeCapture(self.bounds)
        image, left, top = cap.region(5, 5, 15)
        # 越界部分被夹到 (0,0)，且返回真实原点供采样
        self.assertEqual((left, top), (0, 0))
        self.assertEqual(cap.grab_calls[-1], (0, 0, 15, 15))

    def test_cursor_at_bottom_right_is_clamped(self):
        cap = _FakeCapture(self.bounds)
        image, left, top = cap.region(1915, 1075, 15)
        # 右/下边界同理夹取到 1920-15 / 1080-15
        self.assertEqual((left, top), (1905, 1065))
        self.assertEqual(cap.grab_calls[-1], (1905, 1065, 15, 15))

    def test_cursor_center_unchanged(self):
        cap = _FakeCapture(self.bounds)
        image, left, top = cap.region(960, 540, 15)
        self.assertEqual((left, top), (960 - 7, 540 - 7))

    def test_non_negative_bounds(self):
        # 左侧有负坐标的显示器组（如主屏在右），夹取后不应产生负的 grab 起点
        cap = _FakeCapture({"left": -640, "top": 0, "width": 2560, "height": 1080})
        image, left, top = cap.region(-638, 5, 15)
        self.assertGreaterEqual(left, -640)
        self.assertEqual(cap.grab_calls[-1][0], -640)


class TestAveragePixelsOffset(unittest.TestCase):
    def _image_with_spot(self, size=15, cx=2, cy=2, color=(255, 0, 0)):
        img = Image.new("RGB", (size, size), (0, 0, 0))
        img.putpixel((cx, cy), color)
        return img

    def test_default_uses_center(self):
        img = self._image_with_spot(cx=7, cy=7, color=(10, 20, 30))
        self.assertEqual(average_pixels(img, 1), (10, 20, 30))

    def test_offset_samples_cursor_pixel(self):
        # 当区域被夹取、光标不在图中心时，按真实偏移采样
        img = self._image_with_spot(cx=2, cy=2, color=(255, 0, 0))
        self.assertEqual(average_pixels(img, 1, cx=2, cy=2), (255, 0, 0))

    def test_offset_away_from_spot(self):
        img = self._image_with_spot(cx=2, cy=2, color=(255, 0, 0))
        # 在远离亮点的中心采样应得到黑
        self.assertEqual(average_pixels(img, 1, cx=10, cy=10), (0, 0, 0))

    def test_empty_crop_returns_black(self):
        # 完全越出图像的坐标 → 空裁剪 → 安全回落纯黑
        img = Image.new("RGB", (15, 15), (5, 5, 5))
        self.assertEqual(average_pixels(img, 1, cx=999, cy=999), (0, 0, 0))

    def test_block_average_uniform(self):
        # 3×3 全同色块，平均值应等于该色
        img = Image.new("RGB", (9, 9), (10, 20, 30))
        self.assertEqual(average_pixels(img, 3, cx=4, cy=4), (10, 20, 30))

    def test_block_average_mixes_colors(self):
        # 中心 3×3 里放一格红、其余黑，平均值应介于纯黑与纯红之间
        img = Image.new("RGB", (9, 9), (0, 0, 0))
        img.putpixel((4, 4), (255, 0, 0))
        red = average_pixels(img, 3, cx=4, cy=4)[0]
        self.assertGreater(red, 0)
        self.assertLess(red, 255)


class TestPixelMethod(unittest.TestCase):
    def test_pixel_grabs_single_pixel(self):
        cap = _FakeCapture({"left": 0, "top": 0, "width": 100, "height": 100})
        value = cap.pixel(3, 4)
        self.assertEqual(cap.grab_calls[-1], (3, 4, 1, 1))
        self.assertEqual(value, (1, 2, 3))

    def test_region_degenerate_monitor_no_crash(self):
        # 显示器尺寸为 0 时不做夹取，但仍应正常返回而不抛错
        cap = _FakeCapture({"left": 0, "top": 0, "width": 0, "height": 0})
        image, left, top = cap.region(50, 50, 15)
        self.assertTrue(cap.grab_calls)
        self.assertIsNotNone(image)


if __name__ == "__main__":
    unittest.main()
