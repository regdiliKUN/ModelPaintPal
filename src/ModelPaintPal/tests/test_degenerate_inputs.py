# -*- coding: utf-8 -*-
"""退化输入的边界行为：空库 / 单条库 / 极端参数。

这类用例平时跑不到，但一旦触发就是「界面空白但没报错」或者「数字自相矛盾」，
排查成本远高于写测试的成本。这里的每条断言都对应过一个真实的口径问题。
"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.config import AppConfig  # noqa: E402
from app.data.paint_db import PaintDatabase, PaintEntry, get_database  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402
from app.services.scheme_engine import build_scheme, compute_base_mix  # noqa: E402

TARGET = (120, 96, 72)


def _entry(uid: str, rgb=(120, 96, 72), finish="flat") -> PaintEntry:
    return PaintEntry(uid=uid, brand_key="tamiya", code=uid.split(":")[-1],
                      name="测试漆", name_en="Test", rgb=rgb, finish=finish,
                      opacity="opaque")


class EmptyDatabaseTest(unittest.TestCase):
    """空库必须真的空——不能被「假值回退」换成全库。"""

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()
        cls.empty = PaintMatcher(PaintDatabase([]))

    def test_matcher_keeps_the_empty_database(self):
        """``PaintDatabase`` 实现了 ``__len__``，空库是假值。

        此前 ``PaintMatcher(db or get_database())`` 会把调用方明确传入的空库
        悄悄换成全库，于是「空库返回空建议」这条边界永远测不出来。
        """
        self.assertEqual(len(self.empty.db), 0)

    def test_suggest_returns_empty_list(self):
        self.assertEqual(self.empty.suggest(TARGET, self.config), [])

    def test_build_scheme_degrades_to_no_suggestions(self):
        stops = build_scheme(self.empty, TARGET, self.config, scheme_type="basic")
        self.assertTrue(stops)
        self.assertTrue(all(stop.suggestion is None for stop in stops))

    def test_base_mix_still_returns_ratios(self):
        """五瓶基础漆的配比是纯数学，不依赖色号库；没有真实漆可推荐时留空即可。"""
        recipe = compute_base_mix(TARGET, self.config, matcher=self.empty)
        self.assertEqual(len(recipe.components), 5)
        self.assertAlmostEqual(sum(c.percent for c in recipe.components), 100.0, places=6)
        self.assertTrue(all(c.suggestion is None for c in recipe.components))


class TinyDatabaseTest(unittest.TestCase):
    """只有一两条色号时不能崩，也不能给出超过候选数的组分。"""

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()

    def test_single_entry_returns_direct_recipe(self):
        matcher = PaintMatcher(PaintDatabase([_entry("tamiya:X-1")]))
        result = matcher.suggest(TARGET, self.config)
        self.assertTrue(result)
        self.assertEqual(len(result[0].recipe.components), 1)
        self.assertTrue(result[0].is_direct)

    def test_two_entries_never_exceed_pool_size(self):
        matcher = PaintMatcher(PaintDatabase([
            _entry("tamiya:X-1", (120, 96, 72)),
            _entry("tamiya:X-2", (30, 60, 120)),
        ]))
        for item in matcher.suggest(TARGET, self.config):
            self.assertLessEqual(len(item.recipe.components), 2)

    def test_non_mixable_only_pool_falls_back_to_direct(self):
        """池里全是金属漆（默认不允许混配）时，应退回单色直用而不是空结果。"""
        matcher = PaintMatcher(PaintDatabase([_entry("tamiya:X-10", finish="metal")]))
        result = matcher.suggest(TARGET, self.config)
        self.assertTrue(result)
        self.assertTrue(result[0].is_direct)


class DropBudgetTest(unittest.TestCase):
    """总滴数不能小于组分个数，否则「总滴数」与各段滴数之和互相矛盾。"""

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()
        cls.matcher = PaintMatcher(get_database())

    def test_total_drops_matches_component_sum(self):
        for requested in (0, 1, 3, 5, 20, 100):
            recipe = compute_base_mix(TARGET, self.config, matcher=self.matcher,
                                      total_drops=requested)
            total = sum(comp.drops for comp in recipe.components)
            self.assertEqual(recipe.total_drops, total,
                             f"请求 {requested} 滴时，标题总数与实际滴数不一致")
            self.assertGreaterEqual(total, len(recipe.components))

    def test_zero_weight_component_gets_zero_drops(self):
        """比例为 0 的组分给 0 滴，不强行凑 1 滴（否则会出现「1 滴占 0%」的漆）。

        这不是缺陷，是刻意约定：滴数必须能反推出百分比。这里把它钉住，
        免得以后有人为了「每个组分都有滴数」去改坏它。
        """
        recipe = compute_base_mix(TARGET, self.config, matcher=self.matcher, total_drops=5)
        for comp in recipe.components:
            if comp.weight <= 0:
                self.assertEqual(comp.drops, 0)
            else:
                self.assertGreaterEqual(comp.drops, 1)
        self.assertEqual(sum(c.drops for c in recipe.components), recipe.total_drops)


if __name__ == "__main__":
    unittest.main()
