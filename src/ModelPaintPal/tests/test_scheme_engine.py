# -*- coding: utf-8 -*-
"""基础配色方案引擎的单元测试（纯逻辑，无需 GUI）。"""

from __future__ import annotations

import unittest

from app.core.color_models import hsv_to_rgb, rgb_to_hsv
from app.core.config import AppConfig
from app.data.paint_db import get_database
from app.services.paint_matcher import PaintMatcher, PaintSuggestion
from app.services.scheme_engine import (
    SchemeType, build_scheme, default_param_for, generate_scheme_colors,
)

RED = (255, 0, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

EXPECTED_COUNTS = {
    SchemeType.BASIC: 6,
    SchemeType.COMPLEMENTARY: 2,
    SchemeType.SPLIT: 3,
    SchemeType.TRIADIC: 3,
    SchemeType.TETRADIC: 4,
}


class SchemeEngineTest(unittest.TestCase):
    def test_generate_counts(self):
        for scheme_type, expected in EXPECTED_COUNTS.items():
            colors = generate_scheme_colors(RED, scheme_type)
            self.assertEqual(len(colors), expected, scheme_type)
        # 邻近 / 单色受 param 控制
        self.assertEqual(len(generate_scheme_colors(RED, SchemeType.ANALOGOUS, 5)), 5)
        self.assertEqual(len(generate_scheme_colors(RED, SchemeType.ANALOGOUS, 3)), 3)
        self.assertEqual(len(generate_scheme_colors(RED, SchemeType.MONOCHROMATIC, 4)), 4)

    def test_complementary_is_opposite_hue(self):
        colors = generate_scheme_colors(RED, SchemeType.COMPLEMENTARY)
        self.assertEqual(colors[0].role, "基色")
        # 红(0°) 的补色应在 180° 附近 → 青色
        h, s, v = rgb_to_hsv(colors[1].rgb)
        self.assertAlmostEqual(h % 360.0, 180.0, delta=1.0)
        self.assertGreater(s, 50)
        # 与直接旋转结果一致
        cyanish = hsv_to_rgb((180.0, 100.0, 100.0))
        self.assertTrue(abs(colors[1].rgb[0] - cyanish[0]) <= 4)
        self.assertTrue(abs(colors[1].rgb[1] - cyanish[1]) <= 4)
        self.assertTrue(abs(colors[1].rgb[2] - cyanish[2]) <= 4)

    def test_triadic_is_three_primary_like(self):
        colors = generate_scheme_colors(RED, SchemeType.TRIADIC)
        hues = [rgb_to_hsv(c.rgb)[0] for c in colors]
        # 0 / 120 / 240 三间
        self.assertAlmostEqual(hues[0] % 360, 0.0, delta=1.0)
        self.assertAlmostEqual(hues[1] % 360, 120.0, delta=1.0)
        self.assertAlmostEqual(hues[2] % 360, 240.0, delta=1.0)

    def test_basic_palette_roles(self):
        colors = generate_scheme_colors(RED, SchemeType.BASIC)
        roles = [c.role for c in colors]
        self.assertEqual(roles, ["红", "橙", "黄", "绿", "蓝", "紫"])

    def test_analogous_offsets_are_adjacent_hues(self):
        colors = generate_scheme_colors(RED, SchemeType.ANALOGOUS, 5)
        hues = [rgb_to_hsv(c.rgb)[0] for c in colors]
        # 5 色以 30° 为步长、基色居中：跨度为 ±60°（红 0° → 300° / 60°）
        self.assertAlmostEqual(hues[2] % 360, 0.0, delta=1.0)
        self.assertAlmostEqual(hues[0] % 360, 300.0, delta=1.0)
        self.assertAlmostEqual(hues[4] % 360, 60.0, delta=1.0)

    def test_monochromatic_keeps_hue_same(self):
        base = (200, 40, 40)  # 带色相的红
        colors = generate_scheme_colors(base, SchemeType.MONOCHROMATIC, 5)
        base_h = rgb_to_hsv(base)[0]
        for c in colors:
            self.assertAlmostEqual(rgb_to_hsv(c.rgb)[0] % 360, base_h % 360, delta=2.0)

    def test_extreme_colors_do_not_crash(self):
        for base in (BLACK, WHITE, (128, 128, 128), (12, 34, 200)):
            for scheme_type in (
                SchemeType.BASIC, SchemeType.COMPLEMENTARY, SchemeType.SPLIT,
                SchemeType.TRIADIC, SchemeType.TETRADIC, SchemeType.ANALOGOUS,
                SchemeType.MONOCHROMATIC,
            ):
                colors = generate_scheme_colors(base, scheme_type)
                self.assertTrue(len(colors) >= 2)
                for c in colors:
                    self.assertEqual(len(c.rgb), 3)
                    self.assertTrue(all(0 <= ch <= 255 for ch in c.rgb))

    def test_default_param(self):
        self.assertEqual(default_param_for(SchemeType.ANALOGOUS), 5)
        self.assertEqual(default_param_for(SchemeType.MONOCHROMATIC), 5)
        self.assertEqual(default_param_for(SchemeType.BASIC), 0)

    def test_build_scheme_yields_recipes(self):
        db = get_database()
        self.assertGreater(len(db), 0)
        matcher = PaintMatcher(db)
        config = AppConfig()
        stops = build_scheme(matcher, RED, config, brands=[], scheme_type=SchemeType.TRIADIC)
        self.assertEqual(len(stops), 3)
        for stop in stops:
            self.assertIsInstance(stop.suggestion, PaintSuggestion)
            self.assertIsNotNone(stop.suggestion.anchor)
            self.assertGreaterEqual(stop.suggestion.delta_e, 0.0)

    def test_build_scheme_respects_brand_scope(self):
        db = get_database()
        matcher = PaintMatcher(db)
        config = AppConfig()
        # 限定单一品牌时，每个方案色的配方不应出现其它品牌的主色号
        stops = build_scheme(matcher, (120, 80, 60), config,
                             brands=["tamiya"], scheme_type=SchemeType.COMPLEMENTARY)
        for stop in stops:
            if stop.suggestion is not None:
                self.assertEqual(stop.suggestion.anchor.brand_key, "tamiya")


if __name__ == "__main__":
    unittest.main(verbosity=2)
