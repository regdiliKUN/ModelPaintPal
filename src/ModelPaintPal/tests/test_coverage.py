# -*- coding: utf-8 -*-
"""用量估算的单元测试。

用量是这个软件唯一会直接影响「买几瓶漆」的输出，此前没有任何专门测试：
``suggest_coats`` 的层数微调、``fixed_paint_loss_ml`` 的「不乘面积」语义、
各组分拆分之和是否等于纯漆量，全靠人工核对。这里把这几条口径钉死。
"""

import math
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services.coverage import (  # noqa: E402
    APPLICATION_FACTORS, SURFACE_FACTORS, CoverageInput, anchor_provenance,
    estimate_coverage, suggest_coats,
)


class CoverageValidationTest(unittest.TestCase):
    """非法输入必须在第一现场拒绝，不能算出 NaN 还继续往下走。"""

    def test_non_finite_inputs_raise(self):
        for field, value in (
            ("area_m2", float("nan")),
            ("thinner_ratio", float("inf")),
            ("waste_buffer", float("nan")),
            ("coats", float("nan")),
            ("fixed_paint_loss_ml", float("-inf")),
        ):
            inp = CoverageInput()
            setattr(inp, field, value)
            with self.assertRaises(ValueError, msg=f"{field} 未被拦截"):
                estimate_coverage(inp, {}, 10.0)

    def test_bottle_volume_must_be_finite(self):
        """bottle_ml 是「约几瓶」的唯一来源，NaN/inf 必须报错而不是算出 nan 瓶。"""
        inp = CoverageInput()
        for bad in (float("nan"), float("inf"), "10", None):
            with self.assertRaises(ValueError, msg=f"bottle_ml={bad!r} 未被拦截"):
                estimate_coverage(inp, {}, bad)

    def test_negative_bottle_volume_means_no_bottle_count(self):
        inp = CoverageInput()
        self.assertEqual(estimate_coverage(inp, {}, -5.0).bottles, 0.0)

    def test_non_finite_proportion_raises(self):
        inp = CoverageInput()
        with self.assertRaises(ValueError):
            estimate_coverage(inp, {"x": float("nan")}, 10.0)


class CoverageMathTest(unittest.TestCase):
    """口径：原漆量 = 面积 × 层数 × 单位量 × 施工 × 基材 × 余量 + 固定损耗。"""

    def test_thinner_follows_ratio_only(self):
        base = estimate_coverage(CoverageInput(thinner_ratio=0.0), {}, 0.0)
        self.assertEqual(base.thinner_ml, 0.0)
        wet = estimate_coverage(CoverageInput(thinner_ratio=2.0), {}, 0.0)
        self.assertAlmostEqual(wet.paint_ml, base.paint_ml, places=6,
                               msg="原漆需求不应随额外稀释比变化")
        self.assertAlmostEqual(wet.thinner_ml, wet.paint_ml * 2.0, places=2)
        self.assertAlmostEqual(wet.mix_ml, wet.paint_ml + wet.thinner_ml, places=2)

    def test_more_coats_need_more_paint(self):
        one = estimate_coverage(CoverageInput(coats=1), {}, 0.0)
        three = estimate_coverage(CoverageInput(coats=3), {}, 0.0)
        self.assertGreater(three.paint_ml, one.paint_ml)
        self.assertAlmostEqual(three.paint_ml / one.paint_ml, 3.0, places=2)

    def test_surface_and_application_factors_apply(self):
        primed = estimate_coverage(CoverageInput(surface="primed", application="brush"), {}, 0.0)
        raw = estimate_coverage(CoverageInput(surface="raw_print", application="brush"), {}, 0.0)
        self.assertAlmostEqual(raw.paint_ml / primed.paint_ml,
                               SURFACE_FACTORS["raw_print"], places=3)
        can = estimate_coverage(CoverageInput(surface="primed", application="spray_can"), {}, 0.0)
        self.assertAlmostEqual(can.paint_ml / primed.paint_ml,
                               APPLICATION_FACTORS["spray_can"] / APPLICATION_FACTORS["brush"],
                               places=3)

    def test_fixed_loss_is_not_multiplied_by_area_or_coats(self):
        """固定损耗是「另计」的一笔，不该被面积/层数放大。"""
        small = estimate_coverage(CoverageInput(area_m2=0.01, coats=1, fixed_paint_loss_ml=2.0), {}, 0.0)
        plain = estimate_coverage(CoverageInput(area_m2=0.01, coats=1, fixed_paint_loss_ml=0.0), {}, 0.0)
        self.assertAlmostEqual(small.paint_ml - plain.paint_ml, 2.0, places=2)
        big = estimate_coverage(CoverageInput(area_m2=0.2, coats=4, fixed_paint_loss_ml=2.0), {}, 0.0)
        big_plain = estimate_coverage(CoverageInput(area_m2=0.2, coats=4, fixed_paint_loss_ml=0.0), {}, 0.0)
        self.assertAlmostEqual(big.paint_ml - big_plain.paint_ml, 2.0, places=2)

    def test_component_split_sums_to_paint(self):
        inp = CoverageInput()
        est = estimate_coverage(inp, {"a": 0.6, "b": 0.3, "c": 0.1}, 10.0)
        self.assertAlmostEqual(sum(est.per_component_ml.values()), est.paint_ml, places=2)
        self.assertAlmostEqual(est.per_component_ml["a"] / est.paint_ml, 0.6, places=3)

    def test_component_split_ignores_negative_weights(self):
        inp = CoverageInput()
        est = estimate_coverage(inp, {"a": 1.0, "b": -3.0}, 10.0)
        self.assertAlmostEqual(est.per_component_ml["b"], 0.0, places=6)
        self.assertAlmostEqual(est.per_component_ml["a"], est.paint_ml, places=2)

    def test_zero_total_proportions_yield_no_split(self):
        inp = CoverageInput()
        est = estimate_coverage(inp, {"a": 0.0, "b": 0.0}, 10.0)
        self.assertEqual(est.per_component_ml, {})

    def test_bottle_count_uses_single_bottle_volume(self):
        est = estimate_coverage(CoverageInput(), {}, 10.0)
        self.assertAlmostEqual(est.bottles, round(est.paint_ml / 10.0, 2), places=2)
        self.assertFalse(math.isnan(est.bottles))


class SuggestCoatsTest(unittest.TestCase):
    def test_semi_needs_extra_coat(self):
        self.assertEqual(suggest_coats("flat", "semi", 2), 3)

    def test_clear_needs_fewer_coats_but_never_below_one(self):
        self.assertEqual(suggest_coats("gloss", "opaque", 2), 2)
        self.assertEqual(suggest_coats("clear", "clear", 1), 1)

    def test_fluor_needs_extra_coat(self):
        self.assertEqual(suggest_coats("fluor", "opaque", 2), 3)

    def test_capped_at_eight(self):
        self.assertEqual(suggest_coats("fluor", "semi", 8), 8)


class AnchorProvenanceTest(unittest.TestCase):
    """界面上要能回答「这个 1.35 是谁说的」，只列真正参与计算的那几个锚点。"""

    def test_only_participating_anchors_are_listed(self):
        keys = [item["key"] for item in
                anchor_provenance(CoverageInput(application="airbrush", surface="raw_print"))]
        self.assertIn("airbrush", keys)
        self.assertIn("raw_print", keys)
        self.assertIn("mix_ml_per_m2_per_coat", keys)
        self.assertNotIn("brush", keys)

    def test_primed_has_no_anchor_because_it_is_the_neutral_value(self):
        keys = [item["key"] for item in anchor_provenance(CoverageInput(surface="primed"))]
        self.assertNotIn("primed", keys)

    def test_every_anchor_declares_a_source_and_confidence(self):
        for item in anchor_provenance(CoverageInput()):
            self.assertTrue(item["source"])
            self.assertGreater(item["confidence"], 0.0)
            self.assertLessEqual(item["confidence"], 1.0)


if __name__ == "__main__":
    unittest.main()
