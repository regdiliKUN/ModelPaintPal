# -*- coding: utf-8 -*-
"""向量化粗扫（``vector_scan``）与标量实现的等价性。

这块代码是「同一套公式写两遍」——一遍给逐对调用的标量路径，一遍给批量数组。
两份实现一旦漂移，配方就会在某个目标色上悄悄换一支漆，而界面完全看不出来。
所以这里不做抽样，直接把整池色号对逐个比一遍。

容差取 1e-9：实测最大差 3.9e-14（浮点 ULP 级），1e-9 已经宽出五个数量级，
既不会误报，也能拦住任何真正的公式走样（那种差异至少是 1e-3 量级）。
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
from app.core.delta_e import resolve_delta_e  # noqa: E402
from app.services import recipe_engine, vector_scan  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402

TARGETS = [(120, 96, 72), (216, 118, 68), (30, 90, 160), (12, 14, 16), (240, 240, 232)]


def _pool(matcher, config, target_lab):
    pool = matcher.candidate_pool(config, None)
    ranked = matcher.rank_by_distance(target_lab, pool, config.delta_e_formula, len(pool))
    compatible = {}
    for _, entry in ranked:
        group = compatible.setdefault(entry.brand_key, [])
        if len(group) < 16:
            group.append(entry)
    anchor = ranked[0][1]
    candidates = matcher._pool_for(anchor, compatible[anchor.brand_key], size=16)
    prepared = [(entry, rgb_to_linear(entry.rgb)) for entry in candidates]
    return prepared


class VectorScanEquivalenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()
        cls.matcher = PaintMatcher()
        if not vector_scan.AVAILABLE:
            raise unittest.SkipTest("当前环境没有 numpy，向量化路径不可用")

    def test_matches_scalar_for_every_pair(self):
        """720 个色号对逐个比对：最优配比必须完全一致，ΔE 差必须在 1e-9 以内。"""
        de_fn = resolve_delta_e("CIEDE2000")
        checked = 0
        for target in TARGETS:
            target_lab = rgb_to_lab(target)
            prepared = _pool(self.matcher, self.config, target_lab)
            profiles = [recipe_engine._profile_of(lin, self.config.mixing_model)
                        for _, lin in prepared]
            batch = vector_scan.coarse_pair_best(
                profiles, target_lab, self.config.mixing_model,
                recipe_engine._COARSE_STEPS, "CIEDE2000")
            self.assertIsNotNone(batch)
            self.assertEqual(len(batch), len(profiles) * (len(profiles) - 1) // 2)
            for (i, j), (t, value) in batch.items():
                scalar_t, scalar_v = recipe_engine._coarse_pair(
                    (profiles[i], profiles[j]), target_lab,
                    self.config.mixing_model, de_fn)
                self.assertAlmostEqual(t, scalar_t, places=12,
                                       msg=f"最优配比不一致 target={target} pair=({i},{j})")
                self.assertAlmostEqual(value, scalar_v, delta=1e-9,
                                       msg=f"ΔE 不一致 target={target} pair=({i},{j})")
                checked += 1
        self.assertGreater(checked, 500, "样本量太小，等于没测")

    def test_linear_rgb_model_matches_scalar(self):
        """另一种混合模型（线性光平均）也要对得上。"""
        de_fn = resolve_delta_e("CIEDE2000")
        target_lab = rgb_to_lab(TARGETS[0])
        prepared = _pool(self.matcher, self.config, target_lab)
        profiles = [recipe_engine._profile_of(lin, "linear_rgb") for _, lin in prepared]
        batch = vector_scan.coarse_pair_best(
            profiles, target_lab, "linear_rgb", recipe_engine._COARSE_STEPS, "CIEDE2000")
        for (i, j), (t, value) in batch.items():
            scalar_t, scalar_v = recipe_engine._coarse_pair(
                (profiles[i], profiles[j]), target_lab, "linear_rgb", de_fn)
            self.assertAlmostEqual(t, scalar_t, places=12)
            self.assertAlmostEqual(value, scalar_v, delta=1e-9)

    def test_subset_pairs_only(self):
        """只传部分色号对时，只算这些，不多算也不少算。"""
        target_lab = rgb_to_lab(TARGETS[1])
        prepared = _pool(self.matcher, self.config, target_lab)
        profiles = [recipe_engine._profile_of(lin, self.config.mixing_model)
                    for _, lin in prepared]
        subset = [(0, 1), (2, 5), (7, 9)]
        batch = vector_scan.coarse_pair_best(
            profiles, target_lab, self.config.mixing_model,
            recipe_engine._COARSE_STEPS, "CIEDE2000", pairs=subset)
        self.assertEqual(set(batch), set(subset))

    def test_empty_pair_list_returns_empty_dict(self):
        profiles = [(0.1, 0.2, 0.3), (0.4, 0.5, 0.6)]
        self.assertEqual(
            vector_scan.coarse_pair_best(profiles, (50.0, 0.0, 0.0), "kubelka_munk", 20,
                                         "CIEDE2000", pairs=[]), {})


class TripleCandidateEquivalenceTest(unittest.TestCase):
    """三色「向量化找候选 + 标量裁决」必须与纯标量全网格扫描逐位一致。

    这是本轮唯一一处「向量化不直接出结果」的地方：三色权重网格里有大量近平局，
    直接取向量化的 argmin 会因 1e-14 的差异选中别的网格点，最终换掉配方里的一支漆。
    所以向量化只负责排除绝大多数点，真正的比较仍走标量——这里验证两者结论相同。
    """

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()
        cls.matcher = PaintMatcher()
        if not vector_scan.AVAILABLE:
            raise unittest.SkipTest("当前环境没有 numpy，向量化路径不可用")

    def test_candidates_match_full_grid_for_every_triple(self):
        import itertools

        de_fn = resolve_delta_e("CIEDE2000")
        checked = 0
        for target in TARGETS:
            target_lab = rgb_to_lab(target)
            prepared = _pool(self.matcher, self.config, target_lab)
            profiles = [recipe_engine._profile_of(lin, self.config.mixing_model)
                        for _, lin in prepared]
            pool_n = min(len(profiles), recipe_engine._TRIPLE_POOL)
            triples = list(itertools.combinations(range(pool_n), 3))
            batch = vector_scan.coarse_triple_candidates(
                profiles[:pool_n], target_lab, self.config.mixing_model,
                recipe_engine._TRIPLE_GRID, triples, "CIEDE2000")
            self.assertEqual(len(batch), len(triples))
            for (i, j, k), candidates in batch.items():
                self.assertTrue(candidates, "候选列表不能为空")
                triple = (profiles[i], profiles[j], profiles[k])
                full_v, full_w = recipe_engine._coarse_triple(
                    triple, target_lab, self.config.mixing_model, de_fn)
                cand_v, cand_w = recipe_engine._coarse_triple(
                    triple, target_lab, self.config.mixing_model, de_fn, candidates)
                self.assertEqual(full_w, cand_w,
                                 f"最优配比不一致 target={target} triple=({i},{j},{k})")
                self.assertAlmostEqual(full_v, cand_v, places=12)
                checked += 1
        self.assertGreater(checked, 200, "样本量太小，等于没测")

    def test_unsupported_formula_returns_none(self):
        profiles = [(0.1, 0.2, 0.3), (0.4, 0.5, 0.6), (0.7, 0.8, 0.9)]
        for formula in ("CIE76", "CIE94", "CMC"):
            self.assertIsNone(vector_scan.coarse_triple_candidates(
                profiles, (50.0, 0.0, 0.0), "kubelka_munk", 10, [(0, 1, 2)], formula))


class VectorScanFallbackTest(unittest.TestCase):
    """不可用时必须返回 None，让调用方回退到标量路径——性能是可选项，正确性不是。"""

    def test_unsupported_formula_returns_none(self):
        profiles = [(0.1, 0.2, 0.3), (0.4, 0.5, 0.6)]
        for formula in ("CIE76", "CIE94", "CMC"):
            self.assertIsNone(vector_scan.coarse_pair_best(
                profiles, (50.0, 0.0, 0.0), "kubelka_munk", 20, formula))

    def test_missing_numpy_returns_none(self):
        original = vector_scan.AVAILABLE
        vector_scan.AVAILABLE = False
        try:
            self.assertIsNone(vector_scan.coarse_pair_best(
                [(0.1, 0.2, 0.3), (0.4, 0.5, 0.6)], (50.0, 0.0, 0.0),
                "kubelka_munk", 20, "CIEDE2000"))
        finally:
            vector_scan.AVAILABLE = original

    def test_single_colour_pool_returns_none(self):
        self.assertIsNone(vector_scan.coarse_pair_best(
            [(0.1, 0.2, 0.3)], (50.0, 0.0, 0.0), "kubelka_munk", 20, "CIEDE2000"))


class VectorScanIntegrationTest(unittest.TestCase):
    """接入后配方必须与「关掉向量化」逐位相同。"""

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig().validate()

    def test_suggest_identical_with_and_without_vector_path(self):
        if not vector_scan.AVAILABLE:
            self.skipTest("当前环境没有 numpy")
        matcher = PaintMatcher()

        def run():
            out = []
            for target in TARGETS:
                for item in matcher.suggest(target, self.config):
                    out.append((item.anchor.uid, round(item.delta_e, 10),
                                tuple((c.paint.uid, c.drops)
                                      for c in item.recipe.components)))
            return out

        with_vector = run()
        original = vector_scan.AVAILABLE
        vector_scan.AVAILABLE = False
        try:
            matcher._search_cache_key = None      # 强制冷启动，别吃上一次的缓存
            without_vector = run()
        finally:
            vector_scan.AVAILABLE = original
        self.assertEqual(with_vector, without_vector)


if __name__ == "__main__":
    unittest.main()
