# -*- coding: utf-8 -*-
"""配方搜索加速（色号对缓存 / 细化剪枝）与异步任务取消的回归测试。

这三处优化的共同前提是「只省时间，不改结果」，因此测试的重点不是「更快」，
而是**结果逐位不变**：把缓存关掉、把剪枝余量调到无穷大之后，配方、滴数、
ΔE 必须与优化后完全一致。任何一条断言失败，都说明缓存或剪枝改变了业务结论。
"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.color_models import rgb_to_lab, rgb_to_linear  # noqa: E402
from app.core.config import AppConfig  # noqa: E402
from app.data.paint_db import get_database  # noqa: E402
from app.services import recipe_engine  # noqa: E402
from app.services.async_suggest import SuggestTask, _stale_checker  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402
from app.services.recipe_engine import solve_recipe  # noqa: E402

# 覆盖深色 / 高饱和 / 近中性 / 肤色等不同区域的固定目标色，避免随机带来的不稳定
TARGETS = [
    (120, 96, 72),
    (217, 161, 140),
    (216, 118, 68),
    (30, 90, 160),
    (128, 128, 128),
    (240, 240, 232),
    (12, 14, 16),
]


def _pools(config, target_lab, matcher):
    """复刻 suggest 里的候选池划分，返回若干「锚点 → 16 条候选」的池子。"""
    pool = matcher.candidate_pool(config, None)
    ranked = matcher.rank_by_distance(target_lab, pool, config.delta_e_formula, len(pool))
    compatible = {}
    for _, entry in ranked:
        group = compatible.setdefault(entry.brand_key, [])
        if len(group) < 16:
            group.append(entry)
    return ranked, compatible


def _solve(config, target_lab, candidates, matcher, pair_cache):
    linear_of = {entry.uid: rgb_to_linear(entry.rgb) for entry in matcher.db.entries}
    prepared = [(entry, linear_of[entry.uid]) for entry in candidates]
    return solve_recipe(
        target_lab=target_lab,
        candidates=candidates,
        max_components=config.max_recipe_components,
        model=config.mixing_model,
        formula=config.delta_e_formula,
        drop_total=config.drop_total,
        # 容差压到 0：保证不会因为「单色已在容差内」提前返回，测试必须真的跑到
        # 双色/三色搜索，否则缓存与剪枝根本不会被触发（测了个寂寞）。
        tolerance=0.0,
        prepared=prepared,
        pair_cache=pair_cache,
    )


def _signature(recipe):
    """配方的可比指纹：组分、滴数、比例与色差。"""
    if recipe is None:
        return None
    return (
        tuple((c.paint.uid, c.drops, round(c.proportion, 12)) for c in recipe.components),
        recipe.mixed_hex,
        round(recipe.delta_e, 12),
    )


class PairCacheTransparencyTest(unittest.TestCase):
    """色号对缓存必须完全透明。"""

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()
        cls.matcher = PaintMatcher(get_database())

    def test_shared_cache_across_anchors_matches_no_cache(self):
        """多个锚点共享一份缓存，结果必须与每个锚点独立重算逐位一致。"""
        for target in TARGETS:
            target_lab = rgb_to_lab(target)
            ranked, compatible = _pools(self.config, target_lab, self.matcher)
            anchors = [entry for _, entry in ranked[:4]]
            shared: dict = {}
            for anchor in anchors:
                candidates = self.matcher._pool_for(
                    anchor, compatible[anchor.brand_key], size=16)
                without = _solve(self.config, target_lab, candidates, self.matcher, None)
                with_cache = _solve(self.config, target_lab, candidates, self.matcher, shared)
                self.assertEqual(_signature(without), _signature(with_cache),
                                 f"目标 {target} / 锚点 {anchor.uid} 的配方被缓存改变了")
            self.assertTrue(shared, "缓存应至少记录过若干色号对")

    def test_cache_hit_returns_same_recipe(self):
        """同一输入第二次走缓存命中，结果必须与第一次完全相同。"""
        target_lab = rgb_to_lab(TARGETS[0])
        ranked, compatible = _pools(self.config, target_lab, self.matcher)
        anchor = ranked[0][1]
        candidates = self.matcher._pool_for(anchor, compatible[anchor.brand_key], size=16)
        cache: dict = {}
        first = _solve(self.config, target_lab, candidates, self.matcher, cache)
        second = _solve(self.config, target_lab, candidates, self.matcher, cache)
        self.assertEqual(_signature(first), _signature(second))


class RefinePruningTransparencyTest(unittest.TestCase):
    """双色细化剪枝必须完全透明。"""

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()
        cls.matcher = PaintMatcher(get_database())

    def test_pruning_does_not_change_recipes(self):
        """把余量调到无穷大（等于不剪枝）后，结果必须逐位相同。"""
        original = recipe_engine._PAIR_REFINE_MARGIN
        try:
            recipe_engine._PAIR_REFINE_MARGIN = float("inf")
            baseline = []
            for target in TARGETS:
                target_lab = rgb_to_lab(target)
                ranked, compatible = _pools(self.config, target_lab, self.matcher)
                anchor = ranked[0][1]
                candidates = self.matcher._pool_for(
                    anchor, compatible[anchor.brand_key], size=16)
                baseline.append(_signature(
                    _solve(self.config, target_lab, candidates, self.matcher, None)))
        finally:
            recipe_engine._PAIR_REFINE_MARGIN = original

        pruned = []
        for target in TARGETS:
            target_lab = rgb_to_lab(target)
            ranked, compatible = _pools(self.config, target_lab, self.matcher)
            anchor = ranked[0][1]
            candidates = self.matcher._pool_for(anchor, compatible[anchor.brand_key], size=16)
            pruned.append(_signature(
                _solve(self.config, target_lab, candidates, self.matcher, None)))

        self.assertEqual(baseline, pruned, "细化剪枝改变了配方结果")


class StaleTaskCancellationTest(unittest.TestCase):
    """排队中的陈旧任务必须在开工前放弃。"""

    def test_only_latest_sequence_is_fresh(self):
        first = _stale_checker("unit-test")
        self.assertFalse(first())
        second = _stale_checker("unit-test")
        self.assertTrue(first(), "被新请求取代的判定函数应返回过期")
        self.assertFalse(second())

    def test_superseded_task_does_not_compute(self):
        """过期任务不应调用 matcher，也不应发出任何信号。"""
        calls = []

        class CountingMatcher:
            def suggest(self, **kwargs):
                calls.append(1)
                return []

        done, failed = [], []
        task = SuggestTask(CountingMatcher(), (120, 96, 72), AppConfig(), None, None,
                           token=3, stale_check=lambda: True)
        task.signaller.finished.connect(lambda sug, tok: done.append(tok))
        task.signaller.failed.connect(lambda msg, tok: failed.append(tok))
        task.run()
        self.assertEqual(calls, [])
        self.assertEqual(done, [])
        self.assertEqual(failed, [])

    def test_task_without_stale_check_still_runs(self):
        """直接构造任务（测试 / 同步调用）不带判定函数，必须照常计算。"""
        calls = []

        class CountingMatcher:
            def suggest(self, **kwargs):
                calls.append(1)
                return []

        task = SuggestTask(CountingMatcher(), (120, 96, 72), AppConfig(), None, None, token=1)
        task.run()
        self.assertEqual(calls, [1])


class TriplePruningTransparencyTest(unittest.TestCase):
    """三色搜索的剪枝余量口径。

    双色用 1.5 的保守余量，三色用 0——两者不一样不是笔误：三色细化窗口只有
    ±0.03 的权重区间（粗格的 30%），可改善量比双色更小。这条测试把「放宽到
    1.5 也不改结果」这个结论钉住，将来若真有人为了省时间收紧余量，会先在这里失败。
    """

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()
        cls.matcher = PaintMatcher(get_database())

    def _signatures(self):
        out = []
        for target in TARGETS:
            target_lab = rgb_to_lab(target)
            ranked, compatible = _pools(self.config, target_lab, self.matcher)
            for anchor in [entry for _, entry in ranked[:3]]:
                candidates = self.matcher._pool_for(
                    anchor, compatible[anchor.brand_key], size=16)
                out.append(_signature(
                    _solve(self.config, target_lab, candidates, self.matcher, None)))
        return out

    def test_triple_margin_is_transparent(self):
        original = recipe_engine._TRIPLE_REFINE_MARGIN
        try:
            recipe_engine._TRIPLE_REFINE_MARGIN = 0.0
            baseline = self._signatures()
        finally:
            recipe_engine._TRIPLE_REFINE_MARGIN = original

        for margin in (0.5, 1.5):
            try:
                recipe_engine._TRIPLE_REFINE_MARGIN = margin
                self.assertEqual(baseline, self._signatures(),
                                 f"三色剪枝余量 {margin} 改变了配方结果")
            finally:
                recipe_engine._TRIPLE_REFINE_MARGIN = original


class CrossCallCacheTest(unittest.TestCase):
    """跨调用缓存：同一目标色重算必须命中，且结果不变。

    「用量参数」页拖面积/层数/稀释比会触发整段重算，但搜索输入（目标色、混合模型、
    色差公式）一个字都没变。缓存就架在这里：命中的是色号对/三元组的最优配比，
    它只取决于这三样东西，与容差、总滴数、候选池组成无关。
    """

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()

    def setUp(self):
        self.matcher = PaintMatcher(get_database())

    def _signature_list(self, suggestions):
        return [
            (item.anchor.uid, round(item.delta_e, 12),
             tuple((c.paint.uid, c.drops) for c in item.recipe.components))
            for item in suggestions
        ]

    def test_second_call_reuses_search_results(self):
        """第二次调用不应再做任何粗扫（缓存必须真的命中，而不是只"不影响结果"）。"""
        target = TARGETS[0]
        first = self.matcher.suggest(target, self.config)
        self.assertTrue(self.matcher._search_cache, "第一次调用后缓存应为空")

        calls = {"pair": 0, "triple": 0}
        real_pair, real_triple = recipe_engine._coarse_pair, recipe_engine._coarse_triple

        def counted_pair(*args, **kwargs):
            calls["pair"] += 1
            return real_pair(*args, **kwargs)

        def counted_triple(*args, **kwargs):
            calls["triple"] += 1
            return real_triple(*args, **kwargs)

        recipe_engine._coarse_pair = counted_pair
        recipe_engine._coarse_triple = counted_triple
        try:
            second = self.matcher.suggest(target, self.config)
        finally:
            recipe_engine._coarse_pair = real_pair
            recipe_engine._coarse_triple = real_triple

        self.assertEqual(self._signature_list(first), self._signature_list(second))
        self.assertEqual(calls["pair"], 0, "双色粗扫应全部命中缓存")
        self.assertEqual(calls["triple"], 0, "三色粗扫应全部命中缓存")

    def test_coverage_only_change_keeps_recipes(self):
        """只改面积/层数/稀释比：配方与滴数必须一模一样，只有用量变。"""
        target = TARGETS[1]
        base = self.matcher.suggest(target, self.config)
        changed = AppConfig().validate()
        changed.area_m2 = 0.2
        changed.coats = 4
        changed.thinner_ratio = 0.5
        other = self.matcher.suggest(target, changed)
        self.assertEqual(self._signature_list(base), self._signature_list(other))
        self.assertNotEqual(base[0].coverage.mix_ml, other[0].coverage.mix_ml)

    def test_tolerance_does_not_invalidate_cache(self):
        """容差不进缓存键：它只决定"直接用还是调色"，不改变色号对的最优配比。

        注意容差**确实会**改变最终方案——超过容差才去调色、容差内直接单色用，
        这是设计而不是缓存问题。所以这里断言的是两件互不冲突的事：
        缓存键不变（不会白白重算），且两档容差下都调色时配方完全一致。
        """
        target = TARGETS[2]
        tight = AppConfig().validate()
        tight.match_tolerance = 0.5
        loose = AppConfig().validate()
        loose.match_tolerance = 2.0
        a = self.matcher.suggest(target, tight)
        key_after_tight = self.matcher._search_cache_key
        b = self.matcher.suggest(target, loose)
        self.assertEqual(key_after_tight, self.matcher._search_cache_key,
                         "改容差不应重建搜索缓存")
        # 两档容差都小于单色最优 ΔE，都走调色，配方必须一模一样
        if a and b and not a[0].is_direct and not b[0].is_direct:
            self.assertEqual(self._signature_list(a), self._signature_list(b))

    def test_new_target_drops_old_cache(self):
        """换目标色必须整体丢弃缓存，否则会拿别人的配比。"""
        self.matcher.suggest(TARGETS[0], self.config)
        first_key = self.matcher._search_cache_key
        self.matcher.suggest(TARGETS[3], self.config)
        self.assertNotEqual(first_key, self.matcher._search_cache_key)

    def test_formula_change_rebuilds_cache(self):
        """换色差公式后缓存必须重建：同一对色号在不同公式下的最优点不同。"""
        target = TARGETS[0]
        self.matcher.suggest(target, self.config)
        other = AppConfig().validate()
        other.delta_e_formula = "CIE76"
        before_key = self.matcher._search_cache_key
        self.matcher.suggest(target, other)
        self.assertNotEqual(before_key, self.matcher._search_cache_key)


if __name__ == "__main__":
    unittest.main()
