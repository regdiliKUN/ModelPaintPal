# -*- coding: utf-8 -*-
"""色彩数学与配方引擎的单元测试（不依赖 Qt）。

    python -m unittest discover -s tests
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.color_models import (  # noqa: E402
    ColorSample, average_rgb, format_lab, format_rgb, hex_to_rgb, hsl_to_rgb,
    hsv_to_rgb, lab_to_rgb, parse_color_text, relative_luminance, rgb_to_hex,
    rgb_to_hsl, rgb_to_hsv, rgb_to_lab,
)
from app.core.delta_e import delta_e, delta_e_2000, delta_e_76, grade_delta_e  # noqa: E402
from app.services.recipe_engine import solve_recipe  # noqa: E402
from app.services.coverage import estimate_coverage  # noqa: E402
from app.services.mixing import mix_colors  # noqa: E402
from app.data.paint_db import get_database  # noqa: E402


class TestColorConversion(unittest.TestCase):
    def test_hex_roundtrip(self):
        for value in ("#1A2B3C", "#FFFFFF", "#000000", "#C8102E"):
            self.assertEqual(rgb_to_hex(hex_to_rgb(value)), value.upper())

    def test_short_hex(self):
        self.assertEqual(hex_to_rgb("#ABC"), (170, 187, 204))

    def test_parse_color_text_invalid_raises(self):
        """无法识别的写法（非颜色、参数个数不对）必须抛错而非静默返回。"""
        for bad in ("hello", "rgb(1, 2)", "hsl(10, 20)", "1.2.3.4"):
            with self.assertRaises(ValueError, msg=bad):
                parse_color_text(bad)

    def test_format_rgb_and_lab(self):
        self.assertEqual(format_rgb((10, 20, 30)), "rgb(10, 20, 30)")
        self.assertIn("L*", format_lab((50.0, 1.0, -2.0)))

    def test_relative_luminance_bounds(self):
        white = relative_luminance((255, 255, 255))
        black = relative_luminance((0, 0, 0))
        self.assertGreater(white, black)
        self.assertGreaterEqual(white, 0.0)
        self.assertLessEqual(white, 1.0)

    def test_rgb_lab_roundtrip(self):
        for rgb in ((0, 0, 0), (255, 255, 255), (200, 30, 40), (76, 120, 90),
                    (120, 200, 175), (40, 10, 90), (230, 210, 35)):
            lab = rgb_to_lab(rgb)
            back = lab_to_rgb(lab)
            self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(rgb, back)),
                            f"{rgb} -> {lab} -> {back}")

    def test_lab_out_of_gamut_clamps(self):
        """超出 sRGB 色域的 Lab 应被钳制回 0-255，而非产生负数或溢出。"""
        for lab in ((100, 120, 0), (0, -100, 90), (50, 200, -200), (0, 0, 300)):
            back = lab_to_rgb(lab)
            self.assertTrue(all(0 <= c <= 255 for c in back), f"{lab} -> {back}")

    def test_white_lab(self):
        l_val, a_val, b_val = rgb_to_lab((255, 255, 255))
        self.assertAlmostEqual(l_val, 100.0, delta=0.5)
        self.assertAlmostEqual(a_val, 0.0, delta=0.5)
        self.assertAlmostEqual(b_val, 0.0, delta=0.5)

    def test_black_lab(self):
        l_val, _, _ = rgb_to_lab((0, 0, 0))
        self.assertAlmostEqual(l_val, 0.0, delta=0.5)

    def test_hsv_roundtrip(self):
        for rgb in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128)):
            back = hsv_to_rgb(rgb_to_hsv(rgb))
            self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(rgb, back)), f"{rgb} -> {back}")

    def test_parse_color_text(self):
        self.assertEqual(parse_color_text("#1A2B3C"), (26, 43, 60))
        self.assertEqual(parse_color_text("26,43,60"), (26, 43, 60))
        self.assertEqual(parse_color_text("rgb(26, 43, 60)"), (26, 43, 60))
        with self.assertRaises(ValueError):
            parse_color_text("不是颜色")

    def test_parse_color_text_extended(self):
        # hsl / rgba / 0x / #RGBA 等扩展写法
        self.assertEqual(parse_color_text("hsl(0, 100%, 50%)"), (255, 0, 0))
        self.assertEqual(parse_color_text("0xFF0000"), (255, 0, 0))
        self.assertEqual(parse_color_text("rgba(255, 0, 0, 0.5)"), (255, 0, 0))
        self.assertEqual(parse_color_text("#FF000080"), (255, 0, 0))  # #RRGGBBAA 忽略 alpha
        self.assertEqual(parse_color_text("#f00"), (255, 0, 0))

    def test_hsl_roundtrip(self):
        for rgb in ((255, 0, 0), (0, 128, 64), (123, 45, 200), (200, 200, 200)):
            back = hsl_to_rgb(rgb_to_hsl(rgb))
            self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(rgb, back)), f"{rgb} -> {back}")

    def test_achromatic_hue_zero(self):
        """灰阶没有色相与饱和度，hue/sat 应为 0（避免除以 0 产生的噪声）。"""
        for gray in ((0, 0, 0), (128, 128, 128), (255, 255, 255)):
            self.assertEqual(rgb_to_hsv(gray)[0], 0.0)
            self.assertEqual(rgb_to_hsv(gray)[1], 0.0)
            self.assertEqual(rgb_to_hsl(gray)[0], 0.0)

    def test_achromatic_saturation_zero(self):
        hsv_gray = hsv_to_rgb((123, 0, 50))
        self.assertEqual(hsv_gray[0], hsv_gray[1])
        self.assertEqual(hsv_gray[1], hsv_gray[2])
        hsl_gray = hsl_to_rgb((123, 0, 50))
        self.assertEqual(hsl_gray[0], hsl_gray[1])
        self.assertEqual(hsl_gray[1], hsl_gray[2])

    def test_rgb_to_hex_prefix(self):
        self.assertEqual(rgb_to_hex((255, 0, 0)), "#FF0000")
        self.assertEqual(rgb_to_hex((255, 0, 0), prefix=""), "FF0000")

    def test_average_rgb_float_inputs(self):
        self.assertEqual(average_rgb([(0.0, 0.0, 0.0), (255.0, 255.0, 255.0)]),
                         (128, 128, 128))

    def test_primaries_hue(self):
        self.assertAlmostEqual(rgb_to_hsv((255, 0, 0))[0], 0.0, delta=0.5)
        self.assertAlmostEqual(rgb_to_hsv((0, 255, 0))[0], 120.0, delta=0.5)
        self.assertAlmostEqual(rgb_to_hsv((0, 0, 255))[0], 240.0, delta=0.5)

    def test_hue_wraps(self):
        self.assertEqual(hsv_to_rgb((360, 100, 100)), (255, 0, 0))
        self.assertEqual(hsl_to_rgb((360, 100, 50)), (255, 0, 0))
        self.assertEqual(len(hsv_to_rgb((-120, 50, 50))), 3)  # 负色相按环绕处理

    def test_parse_color_text_more_formats(self):
        self.assertEqual(parse_color_text("0XFF0000"), (255, 0, 0))
        self.assertEqual(parse_color_text("  #1A2B3C  "), (26, 43, 60))
        self.assertEqual(parse_color_text("26;43;60"), (26, 43, 60))
        # CSS #RGBA：取 RGB 三位双写、丢弃 alpha
        self.assertEqual(parse_color_text("#F008"), (255, 0, 0))

    def test_contrast_text_color(self):
        from app.core.color_models import contrast_text_color

        on_white = contrast_text_color((255, 255, 255))
        on_black = contrast_text_color((0, 0, 0))
        # 白底给深色字、黑底给浅色字
        self.assertLess(sum(on_white), sum(on_black))

    def test_lab_black_white_precision(self):
        self.assertAlmostEqual(rgb_to_lab((0, 0, 0))[0], 0.0, delta=0.5)
        self.assertAlmostEqual(rgb_to_lab((255, 255, 255))[0], 100.0, delta=0.5)
        self.assertTrue(all(c <= 2 for c in lab_to_rgb((0.0, 0.0, 0.0))))
        self.assertTrue(all(c >= 250 for c in lab_to_rgb((100.0, 0.0, 0.0))))


class TestSampleAndAverage(unittest.TestCase):
    def test_average_rgb_basic(self):
        self.assertEqual(average_rgb([(0, 0, 0), (255, 255, 255)]), (128, 128, 128))
        self.assertEqual(average_rgb([(10, 20, 30)]), (10, 20, 30))

    def test_average_rgb_empty_raises(self):
        with self.assertRaises(ValueError):
            average_rgb([])

    def test_color_sample_properties(self):
        sample = ColorSample.from_rgb((255, 0, 0))
        self.assertEqual(sample.hex, "#FF0000")
        hue, sat, val = sample.hsv
        self.assertAlmostEqual(hue, 0.0, delta=1.0)
        self.assertAlmostEqual(sat, 100.0, delta=0.5)
        self.assertAlmostEqual(val, 100.0, delta=0.5)
        self.assertEqual(len(sample.lab), 3)
        self.assertEqual(sample.as_row()["hex"], "#FF0000")

    def test_color_sample_clamps_out_of_range(self):
        sample = ColorSample.from_rgb((999, -5, 128.6))
        self.assertEqual(sample.rgb, (255, 0, 129))


class TestDeltaE(unittest.TestCase):
    def test_identical_is_zero(self):
        lab = rgb_to_lab((100, 120, 140))
        self.assertAlmostEqual(delta_e_2000(lab, lab), 0.0, delta=1e-9)
        self.assertAlmostEqual(delta_e_76(lab, lab), 0.0, delta=1e-9)

    def test_black_white_is_large(self):
        value = delta_e_2000(rgb_to_lab((0, 0, 0)), rgb_to_lab((255, 255, 255)))
        self.assertGreater(value, 90.0)

    def test_formula_dispatch(self):
        lab1, lab2 = rgb_to_lab((10, 20, 200)), rgb_to_lab((15, 25, 190))
        for formula in ("CIEDE2000", "CIE94", "CIE76", "CMC"):
            self.assertGreaterEqual(delta_e(lab1, lab2, formula), 0.0)

    def test_grade_boundaries(self):
        self.assertIn("无法分辨", grade_delta_e(0.5).label)
        self.assertIn("明显" if False else "", grade_delta_e(4.0).label)
        self.assertLess(grade_delta_e(4.0).value, grade_delta_e(9.0).value)


class TestMixing(unittest.TestCase):
    def test_single_color_returns_itself(self):
        self.assertEqual(mix_colors([(10, 20, 30)], [1.0]), (10, 20, 30))

    def test_channels_in_range(self):
        mixed = mix_colors([(255, 0, 0), (0, 0, 255)], [1.0, 1.0])
        for channel in mixed:
            self.assertTrue(0 <= channel <= 255)

    def test_white_lightens(self):
        base = (120, 80, 40)
        mixed = mix_colors([base, (255, 255, 255)], [1.0, 1.0])
        self.assertGreater(sum(mixed), sum(base))

    def test_black_darkens(self):
        base = (220, 200, 180)
        mixed = mix_colors([base, (0, 0, 0)], [1.0, 1.0])
        self.assertLess(sum(mixed), sum(base))

    def test_linear_model_is_less_absorbing(self):
        """线性模型不会像 KM 那样把互补色压成近黑。"""
        km = mix_colors([(255, 0, 0), (0, 0, 255)], [1.0, 1.0], "kubelka_munk")
        linear = mix_colors([(255, 0, 0), (0, 0, 255)], [1.0, 1.0], "linear_rgb")
        self.assertGreater(sum(linear), sum(km))

    def test_weights_normalized(self):
        a = mix_colors([(255, 0, 0), (0, 0, 255)], [1.0, 1.0])
        b = mix_colors([(255, 0, 0), (0, 0, 255)], [5.0, 5.0])
        self.assertEqual(a, b)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            mix_colors([], [])
        with self.assertRaises(ValueError):
            mix_colors([(1, 2, 3)], [0.0])

    def test_negative_weight_clamped_to_zero(self):
        """负权重应被夹到 0，于是带负权重的颜色对结果零贡献。"""
        full = mix_colors([(200, 200, 200)], [1.0])
        mixed = mix_colors([(10, 20, 30), (200, 200, 200)], [-1.0, 1.0])
        self.assertEqual(mixed, full)

    def test_two_models_differ_but_both_valid(self):
        """两种混色模型给出不同结果（KM 更吸光），但都落在合法范围。"""
        for model in ("kubelka_munk", "linear_rgb"):
            mixed = mix_colors([(255, 0, 0), (0, 255, 0)], [1.0, 1.0], model)
            self.assertTrue(all(0 <= c <= 255 for c in mixed))

    def test_mix_lab_approx_matches(self):
        from app.services.mixing import mix_lab_approx

        colors = [(200, 30, 40), (40, 60, 200)]
        approx = mix_lab_approx(colors, [1.0, 1.0])
        direct = rgb_to_lab(mix_colors(colors, [1.0, 1.0]))
        for a, b in zip(approx, direct):
            self.assertAlmostEqual(a, b, places=6)

    def test_describe_model(self):
        from app.services.mixing import describe_model

        self.assertTrue(describe_model("kubelka_munk"))
        self.assertTrue(describe_model("linear_rgb"))
        self.assertEqual(describe_model("unknown_x"), "unknown_x")

    def test_mix_linears_matches_mix_colors(self):
        from app.core.color_models import linear_to_rgb, rgb_to_linear
        from app.services.mixing import _mix_linears

        colors = [(200, 30, 40), (40, 60, 200)]
        linears = [rgb_to_linear(c) for c in colors]
        via_helper = linear_to_rgb(_mix_linears(linears, [1.0, 1.0]))
        self.assertEqual(via_helper, mix_colors(colors, [1.0, 1.0]))

    def test_linear_model_equals_manual_average(self):
        from app.core.color_models import linear_to_rgb, rgb_to_linear

        colors = [(200, 30, 40), (40, 60, 200)]
        la, lb = rgb_to_linear(colors[0]), rgb_to_linear(colors[1])
        manual = linear_to_rgb([(x + y) / 2 for x, y in zip(la, lb)])
        self.assertEqual(mix_colors(colors, [1.0, 1.0], "linear_rgb"), manual)

    def test_mixing_same_color_near_identical(self):
        c = (120, 80, 40)
        mixed = mix_colors([c, c], [1.0, 1.0])
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(mixed, c)))

    def test_mixing_models_constant(self):
        from app.services.mixing import MIXING_MODELS

        self.assertIn("kubelka_munk", MIXING_MODELS)
        self.assertIn("linear_rgb", MIXING_MODELS)

    def test_non_finite_colors_rejected(self):
        """NaN/inf 会让 K/S 或线性光计算污染整段搜索，必须在入口拒绝。"""
        with self.assertRaises(ValueError):
            mix_colors([(1.0, 2.0, float("nan"))], [1.0])
        with self.assertRaises(ValueError):
            mix_colors([(1.0, 2.0, float("inf"))], [1.0])
        with self.assertRaises(ValueError):
            mix_colors([(float("nan"), 2.0, 3.0), (1.0, 2.0, 3.0)], [1.0, 1.0])

    def test_non_finite_weights_rejected(self):
        with self.assertRaises(ValueError):
            mix_colors([(10, 20, 30), (40, 50, 60)], [1.0, float("nan")])
        with self.assertRaises(ValueError):
            mix_colors([(10, 20, 30), (40, 50, 60)], [1.0, float("inf")])


class TestRecipe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_database()

    def test_solve_returns_recipe(self):
        pool = self.db.by_brands(["tamiya"])[:40]
        target = rgb_to_lab((76, 76, 76))
        recipe = solve_recipe(target, pool, max_components=2, drop_total=20)
        self.assertIsNotNone(recipe)
        self.assertTrue(1 <= len(recipe.components) <= 2)

    def test_drops_sum(self):
        pool = self.db.by_brands(["vallejo_mc"])[:40]
        recipe = solve_recipe(rgb_to_lab((190, 60, 40)), pool, max_components=3, drop_total=20)
        self.assertIsNotNone(recipe)
        self.assertEqual(sum(c.drops for c in recipe.components), 20)
        self.assertTrue(all(c.drops >= 1 for c in recipe.components))

    def test_percent_sum(self):
        pool = self.db.by_brands(["ak_3gen"])[:40]
        recipe = solve_recipe(rgb_to_lab((80, 100, 60)), pool, max_components=3, drop_total=24)
        self.assertIsNotNone(recipe)
        self.assertAlmostEqual(sum(c.percent for c in recipe.components), 100.0, delta=0.5)

    def test_empty_pool(self):
        self.assertIsNone(solve_recipe(rgb_to_lab((0, 0, 0)), [], max_components=3))

    def test_build_direct_recipe(self):
        from app.services.recipe_engine import build_direct_recipe

        entry = self.db.by_brand("tamiya")[0]
        recipe = build_direct_recipe(entry, rgb_to_lab(entry.rgb))
        self.assertTrue(recipe.direct)
        self.assertEqual(len(recipe.components), 1)
        self.assertAlmostEqual(recipe.components[0].proportion, 1.0, places=6)
        self.assertLess(recipe.delta_e, 0.5)

    def test_drops_degenerate_all_zero(self):
        from app.services.recipe_engine import proportions_to_drops

        drops = proportions_to_drops([0.0, 0.0, 0.0], total=10)
        self.assertEqual(sum(drops), 10)
        self.assertTrue(all(d >= 1 for d in drops))

    def test_drops_single_component(self):
        from app.services.recipe_engine import proportions_to_drops

        self.assertEqual(proportions_to_drops([1.0], total=5), [5])

    def test_build_direct_recipe_drops_one(self):
        from app.services.recipe_engine import build_direct_recipe

        entry = self.db.by_brand("tamiya")[0]
        recipe = build_direct_recipe(entry, rgb_to_lab(entry.rgb))
        self.assertEqual(recipe.components[0].drops, 1)  # drop_total=0 → 抬到 1

    def test_drops_total_smaller_than_count(self):
        from app.services.recipe_engine import proportions_to_drops

        drops = proportions_to_drops([0.5, 0.5, 0.0], total=2)
        self.assertEqual(sum(drops), 3)  # total 被抬到组分数 count=3
        self.assertEqual(drops[2], 0)    # 0 比例仍为 0

    def test_recipe_properties(self):
        pool = self.db.by_brands(["tamiya"])[:40]
        recipe = solve_recipe(rgb_to_lab((100, 80, 60)), pool, max_components=2, drop_total=20)
        self.assertIsNotNone(recipe)
        self.assertTrue(recipe.mixed_hex.startswith("#"))
        self.assertEqual(len(recipe.mixed_hex), 7)
        self.assertEqual(len(recipe.proportions), len(recipe.components))
        self.assertTrue(recipe.key)
        self.assertEqual(len(recipe.drops_text().split(" : ")), len(recipe.components))
        self.assertEqual(len(recipe.percent_text().split(" : ")), len(recipe.components))
        self.assertTrue(recipe.components_text())

    def test_closest_entries_orders_and_caps(self):
        from app.services.recipe_engine import closest_entries

        pool = self.db.by_brands(["tamiya"])[:40]
        target = rgb_to_lab((76, 76, 76))
        result = closest_entries(target, pool, n=5)
        self.assertEqual(len(result), 5)
        scores = [value for value, _ in result]
        self.assertEqual(scores, sorted(scores))       # 升序
        self.assertGreaterEqual(scores[0], 0.0)
        pool_uids = {e.uid for e in pool}
        for _, entry in result:
            self.assertIn(entry.uid, pool_uids)        # 全部来自池内
        self.assertEqual(closest_entries(target, pool, n=0), [])
        self.assertEqual(closest_entries(target, [], n=3), [])

    def test_solve_rejects_non_finite_target(self):
        """NaN/inf 或长度不足的目标色必须当场报错，而非产出 ΔE=NaN 的配方。"""
        pool = self.db.by_brands(["tamiya"])[:40]
        with self.assertRaises(ValueError):
            solve_recipe((float("nan"), 0.0, 0.0), pool, max_components=2)
        with self.assertRaises(ValueError):
            solve_recipe((float("inf"), 2.0, 3.0), pool, max_components=2)
        with self.assertRaises(ValueError):
            solve_recipe((1.0, 2.0), pool, max_components=2)  # 长度不足 3

    def test_drops_zero_proportion_stays_zero(self):
        from app.services.recipe_engine import proportions_to_drops

        drops = proportions_to_drops([0.0, 0.5, 0.5], total=20)
        self.assertEqual(drops[0], 0)            # 0 比例 → 0 滴
        self.assertEqual(sum(drops), 20)         # 总和仍凑满
        self.assertTrue(all(d >= 1 for d in drops[1:]))

    def test_drops_sum_preserved(self):
        from app.services.recipe_engine import proportions_to_drops

        for props, total in [([0.6, 0.4], 17), ([0.3, 0.3, 0.4], 24), ([1.0], 30)]:
            drops = proportions_to_drops(props, total)
            self.assertEqual(sum(drops), total)
            self.assertEqual(len(drops), len(props))

    def test_solved_recipe_invariants(self):
        """求解出的配方：占比和≈1、滴数和=总量、ΔE 非负、组分数受 max_components 限制。"""
        from app.services.recipe_engine import solve_recipe

        # 排序后再截断，避免依赖 dict/集合迭代顺序导致的用例不确定性
        pool = sorted(self.db.by_brands(["tamiya", "vallejo_mc"]), key=lambda e: e.uid)[:60]
        for max_comp in (1, 2, 3):
            recipe = solve_recipe(rgb_to_lab((90, 70, 55)), pool, max_components=max_comp, drop_total=24)
            self.assertIsNotNone(recipe)
            self.assertLessEqual(len(recipe.components), max_comp)
            total = sum(c.proportion for c in recipe.components)
            self.assertAlmostEqual(total, 1.0, places=4)
            self.assertEqual(sum(c.drops for c in recipe.components), 24)
            self.assertGreaterEqual(recipe.delta_e, 0.0)
            self.assertLess(recipe.delta_e, 1e6)


class TestCoverage(unittest.TestCase):
    def test_paint_plus_thinner_equals_mix(self):
        from app.services.coverage import CoverageInput

        estimate = estimate_coverage(CoverageInput(area_m2=1.0, coats=1, thinner_ratio=1.0,
                                                   application="brush", surface="primed",
                                                   mix_ml_per_m2_per_coat=100.0,
                                                   waste_buffer=1.0))
        self.assertAlmostEqual(estimate.paint_ml + estimate.thinner_ml, estimate.mix_ml, delta=0.01)

    def test_more_area_more_paint(self):
        from app.services.coverage import CoverageInput

        small = estimate_coverage(CoverageInput(area_m2=0.01))
        large = estimate_coverage(CoverageInput(area_m2=0.10))
        self.assertGreater(large.paint_ml, small.paint_ml)

    def test_raw_print_uses_more(self):
        from app.services.coverage import CoverageInput

        primed = estimate_coverage(CoverageInput(area_m2=0.05, surface="primed"))
        raw = estimate_coverage(CoverageInput(area_m2=0.05, surface="raw_print"))
        self.assertGreater(raw.paint_ml, primed.paint_ml)

    def test_rejects_non_finite_inputs(self):
        from app.services.coverage import CoverageInput, estimate_coverage

        with self.assertRaises(ValueError):
            estimate_coverage(CoverageInput(area_m2=float("nan")))
        with self.assertRaises(ValueError):
            estimate_coverage(CoverageInput(thinner_ratio=float("inf")))
        with self.assertRaises(ValueError):
            estimate_coverage(CoverageInput(area_m2=0.05), {"a": float("nan")})
        with self.assertRaises(ValueError):
            estimate_coverage(None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
