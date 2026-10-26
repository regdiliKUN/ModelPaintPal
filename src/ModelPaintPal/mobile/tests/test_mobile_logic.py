# -*- coding: utf-8 -*-
"""移动端核心移植的纯逻辑测试（无需图形界面）。

验证：路径重定向、核心库复用、配色建议 / 基础漆调配 / 用量 / 收藏历史 / 校准 / 导出
全部可用，且未意外引入 PySide6 依赖。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # src/ModelPaintPal
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mobile.bootstrap  # noqa: E402  —— 必须先重定向路径（副作用：把用户目录指向可写位置）
_ = mobile.bootstrap.ROOT  # 确保 bootstrap 副作用已执行（避免未使用告警）
import mobile.logic as L  # noqa: E402


class LogicPortTest(unittest.TestCase):
    def setUp(self):
        L.ensure_init()

    def test_no_pyside6_leaked(self):
        # 移动端前端不应依赖 PySide6
        import sys as _sys
        self.assertNotIn("PySide6", _sys.modules,
                         "移动端逻辑不应加载 PySide6")

    def test_user_dir_is_writable_and_redirected(self):
        from app.core import paths
        p = paths.user_path("config.json")
        self.assertTrue(str(p).endswith("config.json"))
        # 默认在非系统目录（仓库内 .mobile_userdata 或 Android 私有目录）
        self.assertNotIn("AppData", str(p))

    def test_database_and_matcher(self):
        db = L.get_db()
        self.assertGreater(len(db), 100, "漆库应包含大量色号")
        self.assertGreater(len(db.brands), 5, "应覆盖多个品牌")

    def test_suggest_returns_results(self):
        m = L.get_matcher()
        cfg = L.get_config()
        sugs = m.suggest((226, 174, 121), cfg, brands=[])
        self.assertGreater(len(sugs), 0, "应给出配色建议")
        top = sugs[0]
        self.assertIsNotNone(top.anchor)
        self.assertGreaterEqual(top.delta_e, 0.0)

    def test_base_mix_five_paints(self):
        from app.services.scheme_engine import compute_base_mix
        m = L.get_matcher()
        cfg = L.get_config()
        recipe = compute_base_mix((226, 174, 121), cfg, brands=[], matcher=m,
                                  total_drops=20)
        roles = [c.role for c in recipe.components]
        self.assertEqual(set(roles), {"红", "黄", "蓝", "白", "黑"},
                         "基础漆必须是红/黄/蓝/白/黑五瓶")
        total_pct = sum(c.percent for c in recipe.components)
        self.assertAlmostEqual(total_pct, 100.0, delta=1.0)
        total_drops = sum(c.drops for c in recipe.components)
        self.assertEqual(total_drops, 20)

    def test_mix_brand_scope(self):
        from app.services.scheme_engine import compute_base_mix
        m = L.get_matcher()
        cfg = L.get_config()
        # 限定单一品牌（田宫）时，每个基础漆的推荐应来自田宫（或无匹配）
        recipe = compute_base_mix((220, 80, 60), cfg, brands=["tamiya"],
                                  matcher=m, total_drops=20)
        for c in recipe.components:
            if c.suggestion is not None:
                self.assertEqual(c.suggestion.anchor.brand_key, "tamiya")

    def test_coverage_estimate(self):
        from app.services.coverage import CoverageInput
        inp = CoverageInput(area_m2=0.01, coats=2, thinner_ratio=1.0)
        est = L.compute_coverage(inp)
        self.assertGreater(est.paint_ml, 0.0)
        self.assertGreater(est.mix_ml, 0.0)

    def test_favorites_and_history(self):
        L.add_history((10, 20,30), source="manual")
        L.add_favorite((40, 50, 60), source="manual")
        hist = L.get_history().recent(60)
        favs = L.get_favorites().all()
        self.assertTrue(any(tuple(x.rgb) == (10, 20, 30) for x in hist))
        self.assertTrue(any(tuple(x.rgb) == (40, 50, 60) for x in favs))
        # 清理
        for x in list(hist):
            L.remove_history(x.uid)
        for x in list(favs):
            L.remove_favorite(x.uid)

    def test_calibrate_roundtrip(self):
        from app.data.paint_db import get_database
        db = get_database()
        entry = db.entries[0]
        original = entry.hex
        try:
            ok = L.calibrate(entry.uid, "#123456")
            self.assertTrue(ok)
            self.assertEqual(L.get_db().get(entry.uid).hex.upper(), "#123456")
        finally:
            L.calibrate(entry.uid, original)  # 还原，避免污染用户数据


if __name__ == "__main__":
    unittest.main(verbosity=2)
