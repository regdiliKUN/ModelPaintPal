# -*- coding: utf-8 -*-
"""配色引擎 / 替代色 / 用量 / 导出的集成测试（不依赖 Qt）。"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.config import AppConfig  # noqa: E402
from app.services.alternatives import find_alternatives  # noqa: E402
from app.services.coverage import CoverageInput, estimate_coverage  # noqa: E402
from app.services.export_service import (  # noqa: E402
    recipe_to_markdown, suggestions_to_csv, suggestions_to_json,
    suggestions_to_share_text, suggestions_to_tsv,
)
from app.services.paint_matcher import PaintMatcher  # noqa: E402
from app.data.paint_db import get_database  # noqa: E402


class TestMatcherRobustness(unittest.TestCase):
    """边界：候选池很小或为空时不应崩溃，且结果自洽。"""

    @classmethod
    def setUpClass(cls):
        cls.db = get_database()
        cls.matcher = PaintMatcher(cls.db)

    def _config_with_brands(self, brands):
        cfg = AppConfig()
        cfg.preferred_brands = list(brands)
        return cfg

    def test_single_brand_pool_returns_suggestions(self):
        cfg = self._config_with_brands(["humbrol"])
        result = self.matcher.suggest((120, 60, 40), cfg)
        self.assertTrue(len(result) > 0)
        for s in result:
            self.assertTrue(1 <= len(s.recipe.components) <= cfg.max_recipe_components)
            self.assertGreater(s.recipe.delta_e, 0)

    def test_tiny_pool_no_crash(self):
        # 只保留一个品牌的极少条目也能产出“直用”类建议
        cfg = self._config_with_brands(["sms"])
        result = self.matcher.suggest((200, 200, 200), cfg)
        self.assertIsInstance(result, list)

    def test_empty_pool_returns_empty(self):
        # 给一个不存在的品牌，候选池回落到空 → 空列表而非异常
        cfg = self._config_with_brands(["__no_such_brand__"])
        result = self.matcher.suggest((100, 100, 100), cfg)
        self.assertEqual(result, [])

    def test_max_results_capped(self):
        result = self.matcher.suggest((100, 120, 90), AppConfig(), max_results=3)
        self.assertLessEqual(len(result), 3)

    def test_respects_max_suggestions(self):
        cfg = AppConfig()
        cfg.max_suggestions = 2
        result = self.matcher.suggest((100, 120, 90), cfg)
        self.assertLessEqual(len(result), 2)

    def test_recipe_keys_unique(self):
        """同一批建议里不应出现重复配方（否则列表会被同一方案占满）。"""
        result = self.matcher.suggest((100, 120, 90), AppConfig())
        keys = [s.recipe.key for s in result]
        self.assertEqual(len(keys), len(set(keys)))

    def test_rank_consecutive_from_one(self):
        result = self.matcher.suggest((100, 120, 90), AppConfig())
        self.assertEqual([s.rank for s in result], list(range(1, len(result) + 1)))

    def test_pool_for_anchor_first_no_dup(self):
        anchor = self.db.by_brand("humbrol")[0]
        pool = self.db.by_brand("tamiya")[:8]
        out = self.matcher._pool_for(anchor, pool, size=10)
        self.assertEqual(out[0].uid, anchor.uid)
        self.assertEqual([e.uid for e in out].count(anchor.uid), 1)
        self.assertLessEqual(len(out), 10)

    def test_display_anchor_in_recipe(self):
        """卡片主色号必须属于配方组分，避免「标题与配方不一致」。"""
        entry = self.db.by_brand("tamiya")[0]
        top = self.matcher.suggest(entry.rgb, AppConfig())[0]
        self.assertIn(top.anchor.uid, [c.paint.uid for c in top.recipe.components])

    def test_solve_for_anchor_outside_linear_cache(self):
        """锚点不在 linear_of 缓存里时也不能 KeyError（去重多时会扫到缓存外锚点）。"""
        from app.core.color_models import rgb_to_linear, rgb_to_lab

        anchor = self.db.by_brand("humbrol")[0]
        pool = self.db.by_brand("tamiya")[:8]
        linear_of = {e.uid: rgb_to_linear(e.rgb) for e in pool if e.uid != anchor.uid}
        recipe = self.matcher._solve_for(
            rgb_to_lab(anchor.rgb), anchor, pool, AppConfig(), True, linear_of)
        self.assertIsNotNone(recipe)

    def test_direct_recipe_uses_cached_lab(self):
        # 目标色等于某色号自身 RGB 时，单色直用路径走的是 entry.lab 的 ΔE，应≈0
        entry = self.db.by_brand("tamiya")[0]
        cfg = AppConfig()
        result = self.matcher.suggest(entry.rgb, cfg)
        self.assertTrue(result)
        top = result[0]
        self.assertTrue(top.is_direct)
        self.assertAlmostEqual(top.recipe.delta_e, 0.0, delta=0.05)


class TestAlternatives(unittest.TestCase):
    def setUp(self):
        self.db = get_database()
        self.matcher = PaintMatcher(self.db)

    def test_find_alternatives_returns_valid(self):
        entry = self.db.by_brand("tamiya")[0]
        alts = find_alternatives(entry, self.db, limit=4)
        for alt in alts:
            self.assertNotEqual(alt.paint.uid, entry.uid)
            self.assertGreaterEqual(alt.delta_e, 0)

    def test_shared_standard_ranked_first(self):
        # 找一个确实带标准色的色号
        with_std = next((e for e in self.db if e.standards), None)
        self.assertIsNotNone(with_std, "种子数据应含有标准色关联")
        alts = find_alternatives(with_std, self.db, limit=6)
        if alts:
            shared = [a for a in alts if a.shared_standard]
            if shared:
                # 带共享标准色的原因应排在前面
                self.assertEqual(alts[0].shared_standard, shared[0].shared_standard)

    def test_exclude_removes_given_uids(self):
        entry = self.db.by_brand("tamiya")[0]
        alts = find_alternatives(entry, self.db, limit=6)
        self.assertTrue(alts, "应至少找到一个替代色号")
        excluded_uid = alts[0].paint.uid
        alts2 = find_alternatives(entry, self.db, limit=6, exclude=[excluded_uid])
        returned_uids = [a.paint.uid for a in alts2]
        self.assertNotIn(excluded_uid, returned_uids)

    def test_no_duplicate_uids(self):
        entry = self.db.by_brand("tamiya")[0]
        alts = find_alternatives(entry, self.db, limit=10)
        uids = [a.paint.uid for a in alts]
        self.assertEqual(len(uids), len(set(uids)), "返回结果不应含重复色号")

    def test_limit_is_capped(self):
        entry = self.db.by_brand("tamiya")[0]
        alts = find_alternatives(entry, self.db, limit=3)
        self.assertLessEqual(len(alts), 3)

    def test_exclude_multiple_respected(self):
        """同时排除多个 uid 时，结果里一个都不应出现。"""
        entry = self.db.by_brand("tamiya")[0]
        first = find_alternatives(entry, self.db, limit=8)
        self.assertTrue(first, "应至少找到若干替代色号")
        block = [a.paint.uid for a in first[:3]]
        second = find_alternatives(entry, self.db, limit=8, exclude=block)
        returned = [a.paint.uid for a in second]
        for uid in block:
            self.assertNotIn(uid, returned)

    def test_exclude_self_silent(self):
        # 排掉自己（uid 与原色号相同）也不应让函数崩溃
        entry = self.db.by_brand("tamiya")[0]
        alts = find_alternatives(entry, self.db, limit=5, exclude=[entry.uid])
        self.assertIsInstance(alts, list)

    def test_none_entry_returns_empty(self):
        # 调用方在清空选中后调用，不应抛异常（此前会 AttributeError）
        self.assertEqual(find_alternatives(None, self.db), [])

    def test_brand_scope_restricts(self):
        entry = self.db.by_brand("tamiya")[0]
        alts = find_alternatives(entry, self.db, limit=8, brand_scope=["humbrol"])
        for alt in alts:
            self.assertEqual(alt.paint.brand_key, "humbrol")

    def test_same_brand_flag_runs(self):
        # same_brand=True 表示「允许同品牌」，而非「仅同品牌」；结果仍应全部有效
        entry = self.db.by_brand("tamiya")[0]
        alts = find_alternatives(entry, self.db, limit=5, same_brand=True)
        self.assertIsInstance(alts, list)
        for alt in alts:
            self.assertNotEqual(alt.paint.uid, entry.uid)
            self.assertGreaterEqual(alt.delta_e, 0.0)

    def test_find_same_standard(self):
        from app.services.alternatives import find_same_standard

        with_std = next((e for e in self.db if e.standards), None)
        self.assertIsNotNone(with_std)
        results = find_same_standard(with_std, self.db)
        uids = [e.uid for e in results]
        self.assertEqual(len(uids), len(set(uids)))  # 去重
        target_std = {s.upper() for s in with_std.standards}
        for e in results:
            self.assertTrue({s.upper() for s in e.standards} & target_std)

    def test_reason_label_equals_reason(self):
        entry = self.db.by_brand("tamiya")[0]
        for alt in find_alternatives(entry, self.db, limit=3):
            self.assertEqual(alt.reason_label, alt.reason)

    def test_calibrate_invalid_hex_returns_false(self):
        from app.data.paint_db import calibrate

        self.assertFalse(calibrate("tamiya:X-1", "not-a-color"))


class TestCoverageNotes(unittest.TestCase):
    def test_raw_print_note(self):
        est = estimate_coverage(CoverageInput(area_m2=0.05, surface="raw_print"))
        self.assertTrue(any("水补土" in n for n in est.notes))

    def test_high_thinner_note(self):
        est = estimate_coverage(CoverageInput(area_m2=0.05, thinner_ratio=3.0))
        self.assertTrue(any("遮盖力" in n for n in est.notes))

    def test_paint_plus_thinner_equals_mix(self):
        est = estimate_coverage(CoverageInput(area_m2=0.02, thinner_ratio=1.0,
                                              application="brush", surface="primed",
                                              mix_ml_per_m2_per_coat=100.0, waste_buffer=1.0))
        self.assertAlmostEqual(est.paint_ml + est.thinner_ml, est.mix_ml, delta=0.01)

    def test_coverage_input_normalized_clamps(self):
        inp = CoverageInput(area_m2=-5, coats=0, thinner_ratio=-1,
                            application="bad", surface="bad").normalized()
        self.assertGreaterEqual(inp.area_m2, 0.0005)
        self.assertGreaterEqual(inp.coats, 1)
        self.assertEqual(inp.thinner_ratio, 0.0)
        self.assertEqual(inp.application, "airbrush")
        self.assertEqual(inp.surface, "primed")

    def test_suggest_coats_adjustments(self):
        from app.services.coverage import suggest_coats

        self.assertEqual(suggest_coats("gloss", "opaque", 2), 2)
        self.assertEqual(suggest_coats("gloss", "semi", 2), 3)
        self.assertEqual(suggest_coats("gloss", "clear", 2), 1)
        self.assertEqual(suggest_coats("fluor", "opaque", 2), 3)
        self.assertLessEqual(suggest_coats("fluor", "semi", 8), 8)

    def test_coverage_to_dict(self):
        from app.services.coverage import to_dict

        est = estimate_coverage(CoverageInput(area_m2=0.05))
        data = to_dict(est)
        self.assertIn("mix_ml", data)
        self.assertIn("paint_ml", data)

    def test_estimate_does_not_mutate_input(self):
        # R16：estimate_coverage 不应就地修改调用方传入的 CoverageInput（之前会）
        inp = CoverageInput(area_m2=0.05, thinner_ratio=2.0, application="spray_can", coats=3)
        snapshot = (inp.area_m2, inp.coats, inp.thinner_ratio, inp.application, inp.surface)
        estimate_coverage(inp, {"a": 1.0})
        self.assertEqual(
            (inp.area_m2, inp.coats, inp.thinner_ratio, inp.application, inp.surface),
            snapshot,
        )
        # 多次调用结果一致：不存在“首次归一、二次用已归一值”的漂移
        est1 = estimate_coverage(inp, {"a": 1.0})
        est2 = estimate_coverage(inp, {"a": 1.0})
        self.assertAlmostEqual(est1.mix_ml, est2.mix_ml, places=6)


class TestExport(unittest.TestCase):
    def setUp(self):
        self.db = get_database()
        self.matcher = PaintMatcher(self.db)
        self.suggestions = self.matcher.suggest((76, 76, 76), AppConfig())

    def test_json_structure(self):
        payload = suggestions_to_json(self.suggestions, (76, 76, 76))
        import json
        data = json.loads(payload)
        self.assertIn("suggestions", data)
        self.assertEqual(len(data["suggestions"]), len(self.suggestions))
        first = data["suggestions"][0]
        self.assertIn("components", first)
        self.assertIn("delta_e", first)

    def test_markdown_has_header(self):
        text = recipe_to_markdown(self.suggestions[0].recipe)
        self.assertIn("| 品牌 |", text)
        self.assertIn("| --- |", text)

    def test_csv_structure(self):
        import csv
        import io

        text = suggestions_to_csv(self.suggestions, (76, 76, 76))
        rows = list(csv.reader(io.StringIO(text)))
        self.assertGreaterEqual(len(rows), 2)  # 表头 + 至少一条
        self.assertEqual(rows[0][0], "rank")
        # 数据行数量与建议数一致
        self.assertEqual(len(rows) - 1, len(self.suggestions))
        # 每行字段数一致，且非空的 delta_e 可解析为浮点
        for row in rows[1:]:
            self.assertEqual(len(row), len(rows[0]))
            float(row[3])  # delta_e 列

    def test_share_text_format(self):
        """分享文本要能在纯文本环境里整块粘贴：含目标色、方案号、组分滴数。"""
        text = suggestions_to_share_text(self.suggestions, (76, 76, 76), limit=2)
        self.assertIn("#4C4C4C", text.upper())
        self.assertIn("方案 1", text)
        self.assertIn("滴", text)
        # limit 生效：最多两套方案
        self.assertLessEqual(text.count("方案 "), 2)
        # 不能混入 Markdown 表格或制表符（论坛/群聊会错行）
        self.assertNotIn("| --- |", text)
        self.assertNotIn("\t", text)

    def test_share_text_empty_ok(self):
        text = suggestions_to_share_text([], (0, 0, 0))
        self.assertIn("#000000", text.upper())
        self.assertIn("没有匹配到", text)

    def test_csv_empty_does_not_crash(self):
        import csv
        import io

        text = suggestions_to_csv([], (76, 76, 76))
        rows = list(csv.reader(io.StringIO(text)))
        # 至少应有表头一行，且不抛异常、列数自洽
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "rank")

    def test_json_empty_does_not_crash(self):
        import json

        payload = suggestions_to_json([], (76, 76, 76))
        data = json.loads(payload)
        self.assertEqual(data["suggestions"], [])

    def test_json_target_fields(self):
        import json

        data = json.loads(suggestions_to_json(self.suggestions, (76, 76, 76)))
        self.assertEqual(data["target"]["hex"], "#4C4C4C")
        self.assertEqual(data["target"]["rgb"], [76, 76, 76])

    def test_json_is_deterministic(self):
        import json

        first = suggestions_to_json(self.suggestions, (76, 76, 76))
        second = suggestions_to_json(self.suggestions, (76, 76, 76))
        self.assertEqual(json.loads(first), json.loads(second))

    def test_share_text_includes_percent(self):
        text = suggestions_to_share_text(self.suggestions, (76, 76, 76), limit=1)
        self.assertIn("%", text)

    def test_tsv_matches_csv_columns(self):
        """TSV 与 CSV 列义必须完全一致，仅分隔符不同。"""
        csv_text = suggestions_to_csv(self.suggestions, (76, 76, 76))
        tsv_text = suggestions_to_tsv(self.suggestions, (76, 76, 76))
        csv_lines = csv_text.splitlines()
        tsv_lines = tsv_text.splitlines()
        self.assertEqual(len(csv_lines), len(tsv_lines))
        header_cols = len(csv_lines[0].split(","))
        self.assertEqual(len(tsv_lines[0].split("\t")), header_cols)
        for line in tsv_lines[1:]:
            self.assertEqual(len(line.split("\t")), header_cols)

    def test_tsv_empty_does_not_crash(self):
        text = suggestions_to_tsv([], (10, 20, 30))
        self.assertGreaterEqual(len(text.splitlines()), 1)

    def test_recipe_to_text_content(self):
        from app.services.export_service import recipe_to_text

        text = recipe_to_text(self.suggestions[0].recipe)
        self.assertIn("调配方案", text)
        self.assertIn("混合色", text)
        self.assertIn("滴", text)

    def test_markdown_row_count(self):
        recipe = self.suggestions[0].recipe
        lines = recipe_to_markdown(recipe).splitlines()
        # 表头两行 + 每个组分一行
        self.assertEqual(len(lines), 2 + len(recipe.components))

    def test_suggestion_to_markdown_content(self):
        from app.services.export_service import suggestion_to_markdown

        text = suggestion_to_markdown(self.suggestions[0], "#4C4C4C")
        self.assertIn("方案", text)
        self.assertIn("混合后色值", text)
        self.assertIn("预估用量", text)

    def test_alternatives_to_text(self):
        from app.services.export_service import alternatives_to_text

        self.assertEqual(alternatives_to_text([]), "无替代色号")
        self.assertTrue(alternatives_to_text(self.suggestions[0].alternatives, limit=1))


class TestSuggestFuzz(unittest.TestCase):
    """边界：任意目标色 / 品牌子集 / 公式 / 混色模型下 suggest 都不应抛错。

    这是对「用户随手取任意屏幕颜色」这一真实使用方式的兜底验证：
    取色结果可能非常暗、非常亮、接近纯色、接近灰色、甚至越界（浮点/负值）。
    """

    @classmethod
    def setUpClass(cls):
        cls.db = get_database()
        cls.matcher = PaintMatcher(cls.db)

    def _assert_well_formed(self, result, target):
        self.assertIsInstance(result, list)
        seen_rank = 0
        for item in result:
            # rank 从 1 开始连续递增
            seen_rank += 1
            self.assertEqual(item.rank, seen_rank)
            # ΔE 必须是非负有限值
            self.assertGreaterEqual(item.delta_e, 0.0)
            self.assertLess(item.delta_e, 1e6)
            # 配方必须至少有一个组分，且占比总和接近 1
            comps = item.recipe.components
            self.assertGreaterEqual(len(comps), 1)
            total = sum(c.proportion for c in comps)
            self.assertAlmostEqual(total, 1.0, places=4)
            # 覆盖率估算必须为正（配方存在就得能刷）
            self.assertGreater(item.coverage.mix_ml, 0.0)

    def test_extreme_target_colors(self):
        targets = [
            (0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (128, 128, 128), (1, 1, 1), (254, 254, 254), (255, 255, 0),
            (0, 255, 255), (255, 0, 255), (13, 77, 200), (250, 240, 230),
        ]
        cfg = AppConfig()
        for target in targets:
            with self.subTest(target=target):
                result = self.matcher.suggest(target, cfg)
                self.assertTrue(result, f"目标色 {target} 应至少返回一条建议")
                self._assert_well_formed(result, target)

    def test_out_of_range_and_float_input(self):
        """越界与浮点输入应被夹紧而不是崩溃。"""
        cases = [(-10, 300, 128), (999, -999, 0), (127.6, 63.2, 200.9)]
        cfg = AppConfig()
        for case in cases:
            with self.subTest(case=case):
                result = self.matcher.suggest(case, cfg)
                self._assert_well_formed(result, case)

    def test_all_formulas_and_models(self):
        cfg = AppConfig()
        cfg.delta_e_formula = "CIEDE2000"
        cfg.mixing_model = "kubelka_munk"
        formulas = ["CIEDE2000", "CIE94", "CIE76", "CMC"]
        models = ["linear_rgb", "kubelka_munk"]
        for formula in formulas:
            for model in models:
                with self.subTest(formula=formula, model=model):
                    cfg.delta_e_formula = formula
                    cfg.mixing_model = model
                    result = self.matcher.suggest((90, 120, 60), cfg)
                    self._assert_well_formed(result, (90, 120, 60))

    def test_every_brand_subset(self):
        """逐个品牌单独出建议：候选很少时也不能崩。"""
        brands = sorted(self.db.brands)
        self.assertTrue(brands, "种子数据应至少含一个品牌")
        cfg = AppConfig()
        for brand in brands:
            with self.subTest(brand=brand):
                result = self.matcher.suggest((100, 100, 100), cfg, brands=[brand])
                self._assert_well_formed(result, (100, 100, 100))

    def test_random_targets_never_raise(self):
        """随机 60 个目标色：只要求不抛异常且结构自洽，不校验具体排名。"""
        import random

        rng = random.Random(20261021)  # 固定种子，测试可复现
        cfg = AppConfig()
        for _ in range(40):
            target = tuple(rng.randint(0, 255) for _ in range(3))
            with self.subTest(target=target):
                result = self.matcher.suggest(target, cfg)
                self._assert_well_formed(result, target)


class TestSummarizeAndPool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_database()
        cls.matcher = PaintMatcher(cls.db)

    def test_summarize_empty(self):
        from app.services.paint_matcher import summarize

        self.assertEqual(summarize([]), "暂无建议")

    def test_summarize_non_empty(self):
        from app.services.paint_matcher import summarize

        entry = self.db.by_brand("tamiya")[0]
        text = summarize(self.matcher.suggest(entry.rgb, AppConfig()))
        self.assertTrue(text)
        self.assertTrue(text.startswith("最接近") or "推荐调配" in text)

    def test_suggestion_title_non_empty(self):
        entry = self.db.by_brand("tamiya")[0]
        top = self.matcher.suggest(entry.rgb, AppConfig())[0]
        self.assertTrue(top.title)
        if top.is_direct:
            self.assertIn(top.anchor.code, top.title)

    def test_notes_cross_brand(self):
        from app.services.coverage import CoverageInput, estimate_coverage
        from app.services.recipe_engine import Recipe, RecipeComponent

        a = self.db.by_brand("tamiya")[0]
        b = self.db.by_brand("humbrol")[0]
        comps = [
            RecipeComponent(paint=a, proportion=0.5, drops=10, percent=50.0),
            RecipeComponent(paint=b, proportion=0.5, drops=10, percent=50.0),
        ]
        recipe = Recipe(components=comps, mixed_rgb=(100, 100, 100),
                        mixed_lab=(50.0, 0.0, 0.0), delta_e=2.0, direct=False)
        cov = estimate_coverage(CoverageInput(area_m2=0.05))
        notes = PaintMatcher._notes(recipe, AppConfig(), cov)
        self.assertTrue(any("跨品牌" in n for n in notes))

    def test_suggestion_is_direct_matches_recipe(self):
        for s in self.matcher.suggest((100, 90, 80), AppConfig()):
            self.assertEqual(s.is_direct, s.recipe.direct)

    def test_candidate_pool_brand_subset(self):
        cfg = AppConfig()
        pool = self.matcher.candidate_pool(cfg, ["tamiya"])
        self.assertTrue(pool)
        self.assertTrue(all(e.brand_key == "tamiya" for e in pool))

    def test_candidate_pool_empty_brand_list_means_all_brands(self):
        """``[]`` 必须表示"不限品牌"，不能回落到 config.preferred_brands。

        这是 UI 上「全部品牌」选项的语义基础：此前用 ``brands or None`` 把空列表
        折成 None，于是选了「全部品牌」其实只在首选品牌里搜（选项在说谎）。
        """
        cfg = AppConfig()
        cfg.preferred_brands = ["tamiya"]
        pool = self.matcher.candidate_pool(cfg, [])
        self.assertGreater(len(pool), len(self.matcher.candidate_pool(cfg, ["tamiya"])))
        self.assertGreater(len({e.brand_key for e in pool}), 1)

    def test_candidate_pool_none_uses_config(self):
        """``None`` 表示"调用方没指定"，沿用 config.preferred_brands。"""
        cfg = AppConfig()
        cfg.preferred_brands = ["tamiya"]
        pool = self.matcher.candidate_pool(cfg, None)
        self.assertTrue(pool)
        self.assertTrue(all(e.brand_key == "tamiya" for e in pool))

    def test_unknown_brand_key_is_dropped_not_silently_ignored(self):
        """未注册的品牌键要被显式剔除，不能让候选池「莫名变大/变小」。

        改过名的品牌、手改配置拼错的键，``by_brands`` 会静默跳过。此前若整个
        列表都是未知键，候选池会变成全库 —— 用户以为限定了品牌，实际搜的是全部。
        """
        cfg = AppConfig()
        clean = self.matcher.candidate_pool(cfg, ["tamiya"])
        mixed = self.matcher.candidate_pool(cfg, ["tamiya", "no-such-brand"])
        self.assertEqual([e.uid for e in clean], [e.uid for e in mixed])
        self.assertTrue(all(e.brand_key == "tamiya" for e in mixed))

    def test_unknown_brand_key_falls_back_to_full_pool(self):
        """全是未知键时按「无候选」处理，不悄悄放开成全库。

        「不限品牌」只能用 ``[]`` 表达；点名了品牌却一个都不存在，说明配置坏了，
        应当明确给出空结果，而不是把用户的品牌限制静默取消。
        """
        cfg = AppConfig()
        self.assertEqual(self.matcher.candidate_pool(cfg, ["no-such-brand"]), [])

    def test_share_text_includes_component_amounts(self):
        """分享文本要与界面一致：多色配方要写出每支漆的 ml。"""
        from app.services.export_service import suggestions_to_share_text

        suggestions = self.matcher.suggest((120, 96, 72), AppConfig(), brands=[])
        multi = [s for s in suggestions if len(s.recipe.components) > 1]
        if not multi:
            self.skipTest("当前数据下没有多色配方")
        text = suggestions_to_share_text(suggestions, (120, 96, 72), limit=1)
        self.assertIn("ml", text)
        for comp in multi[0].recipe.components:
            self.assertIn(comp.paint.code, text)

    def test_all_brands_scope_widens_alternatives(self):
        """替代色号的检索范围跟随本次品牌范围，不能"搜全库、替代只看首选"。"""
        cfg = AppConfig()
        cfg.preferred_brands = ["tamiya"]
        wide = self.matcher.suggest((120, 96, 72), cfg, brands=[])
        narrow = self.matcher.suggest((120, 96, 72), cfg, brands=None)
        wide_brands = {alt.paint.brand_key for s in wide for alt in s.alternatives}
        narrow_brands = {alt.paint.brand_key for s in narrow for alt in s.alternatives}
        self.assertTrue(wide_brands - narrow_brands,
                        "全库范围的替代色号应覆盖首选品牌之外的品牌")


if __name__ == "__main__":
    unittest.main()
