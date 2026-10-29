# -*- coding: utf-8 -*-
"""配置加载的逐字段容错测试（R17：单字段异常不应清空全部配置）。"""

import unittest

from app.core.config import AppConfig


class TestConfigFromDict(unittest.TestCase):
    def test_good_fields_kept_when_one_bad(self):
        bad = {
            "magnifier_zoom": "oops",   # 非法 int
            "theme": "light",
            "max_suggestions": 9,
        }
        cfg = AppConfig.from_dict(bad)
        # 其余字段照常生效
        self.assertEqual(cfg.theme, "light")
        self.assertEqual(cfg.max_suggestions, 9)
        # 坏字段回落到默认值（而不是整份配置清空）
        self.assertEqual(cfg.magnifier_zoom, 12)

    def test_bad_list_field_falls_back(self):
        cfg = AppConfig.from_dict({"preferred_brands": "tamiya"})  # 应为 list
        self.assertIsInstance(cfg.preferred_brands, list)
        self.assertTrue(len(cfg.preferred_brands) > 0)

    def test_mix_brands_default_is_single_tamiya(self):
        cfg = AppConfig.from_dict({})
        # 基础配色默认统一到单一品牌（田宫），而不是混搭
        self.assertEqual(cfg.mix_brands, ["tamiya"])

    def test_mix_brands_blank_means_mix_and_match(self):
        # 空列表 = 混搭（各瓶可来自不同品牌），是合法持久化状态，不应被纠正成单品牌
        cfg = AppConfig.from_dict({"mix_brands": []})
        self.assertEqual(cfg.mix_brands, [])

    def test_mix_brands_non_list_falls_back(self):
        cfg = AppConfig.from_dict({"mix_brands": "tamiya"})  # 应为 list
        self.assertIsInstance(cfg.mix_brands, list)
        self.assertEqual(cfg.mix_brands, ["tamiya"])

    def test_unknown_keys_ignored(self):
        cfg = AppConfig.from_dict({"totally_unknown": 123, "theme": "dark"})
        self.assertEqual(cfg.theme, "dark")
        self.assertFalse(hasattr(cfg, "totally_unknown"))

    def test_partial_config_completes_with_defaults(self):
        cfg = AppConfig.from_dict({"area_m2": 0.1})
        self.assertEqual(cfg.area_m2, 0.1)
        self.assertIsInstance(cfg.preferred_brands, list)
        self.assertEqual(cfg.theme, "dark")  # 默认

    def test_empty_dict_returns_defaults(self):
        cfg = AppConfig.from_dict({})
        self.assertEqual(cfg.magnifier_zoom, 12)
        self.assertEqual(cfg.theme, "dark")

    def test_none_value_uses_default(self):
        cfg = AppConfig.from_dict({"window_width": None})
        self.assertEqual(cfg.window_width, 1280)

    def test_validate_keeps_known_formula(self):
        cfg = AppConfig()
        cfg.delta_e_formula = "CIE94"
        cfg.validate()
        self.assertEqual(cfg.delta_e_formula, "CIE94")

    def test_to_dict_from_dict_roundtrip(self):
        cfg = AppConfig()
        cfg.theme = "light"
        cfg.max_suggestions = 11
        cfg.preferred_brands = ["tamiya", "gaia"]
        back = AppConfig.from_dict(cfg.to_dict())
        self.assertEqual(back.theme, "light")
        self.assertEqual(back.max_suggestions, 11)
        self.assertEqual(back.preferred_brands, ["tamiya", "gaia"])

    def test_reset_to_defaults(self):
        cfg = AppConfig()
        cfg.theme = "light"
        cfg.max_suggestions = 19
        cfg.preferred_brands = ["gaia"]
        cfg.reset_to_defaults()
        default = AppConfig()
        self.assertEqual(cfg.theme, default.theme)
        self.assertEqual(cfg.max_suggestions, default.max_suggestions)
        self.assertEqual(cfg.preferred_brands, default.preferred_brands)

    def test_validate_clamps_extremes(self):
        cfg = AppConfig()
        cfg.window_width = 100       # 低于 900
        cfg.coats = 99               # 高于 8
        cfg.thinner_ratio = -1.0     # 低于 0
        cfg.validate()
        self.assertEqual(cfg.window_width, 900)
        self.assertEqual(cfg.coats, 8)
        self.assertEqual(cfg.thinner_ratio, 0.0)

    def test_validate_falls_back_unknown_formula(self):
        # 未知公式此前会被 delta_e 内部静默回落 CIEDE2000；
        # 现在 validate 显式纠正，避免「用户设置了却没生效」的隐性错误。
        cfg = AppConfig()
        cfg.delta_e_formula = "NOT_A_FORMULA"
        cfg.validate()
        self.assertEqual(cfg.delta_e_formula, "CIEDE2000")
        cfg2 = AppConfig.from_dict({"delta_e_formula": "lab"})
        cfg2.validate()
        self.assertEqual(cfg2.delta_e_formula, "CIEDE2000")


class TestConfigAttributeGuard(unittest.TestCase):
    """拼写错误的字段名必须立刻报错，而不是静默创建一个孤立属性。"""

    def test_unknown_attribute_assignment_raises(self):
        cfg = AppConfig()
        with self.assertRaises(AttributeError):
            cfg.mix_model = "kubelka_munk"   # 正确字段名是 mixing_model
        self.assertFalse(hasattr(cfg, "mix_model"))

    def test_known_field_assignment_works(self):
        cfg = AppConfig()
        cfg.mixing_model = "linear_rgb"
        self.assertEqual(cfg.mixing_model, "linear_rgb")

    def test_error_message_lists_hint(self):
        cfg = AppConfig()
        try:
            cfg.not_a_field = 1
        except AttributeError as exc:
            self.assertIn("not_a_field", str(exc))
        else:
            self.fail("应当抛出 AttributeError")


if __name__ == "__main__":
    unittest.main()


class ComponentLimitConsistencyTest(unittest.TestCase):
    """「最多组分」的配置上限必须与引擎能力、界面范围三者一致。

    引擎只搜索单色/双色/三色；界面控件范围是 1–3。此前 ``validate()`` 允许 4，
    手改配置成 4 的用户会得到「看起来设了 4、实际最多 3」的静默失效。
    """

    def test_validate_caps_at_three(self):
        from app.core.config import AppConfig

        cfg = AppConfig()
        cfg.max_recipe_components = 4
        self.assertEqual(cfg.validate().max_recipe_components, 3)
        cfg.max_recipe_components = 0
        self.assertEqual(cfg.validate().max_recipe_components, 1)

    def test_settings_spinbox_range_matches_engine(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from tests import qt_cleanup

        qt_cleanup.install()
        from PySide6.QtWidgets import QApplication

        from app.core.config import AppConfig
        from app.ui.panels.settings_panel import SettingsPanel

        app = QApplication.instance() or QApplication([])
        panel = SettingsPanel(AppConfig())
        try:
            self.assertEqual(panel._max_components.minimum(), 1)
            self.assertEqual(panel._max_components.maximum(), 3)
        finally:
            panel.deleteLater()
            app.processEvents()

    def test_recipes_never_exceed_config(self):
        from app.core.config import AppConfig
        from app.services.paint_matcher import PaintMatcher

        matcher = PaintMatcher()
        for limit in (1, 2, 3):
            cfg = AppConfig().validate()
            cfg.max_recipe_components = limit
            for target in ((120, 96, 72), (216, 118, 68)):
                for item in matcher.suggest(target, cfg):
                    self.assertLessEqual(len(item.recipe.components), limit,
                                         f"limit={limit} 却给出了更多组分")


class ExtremeConfigTest(unittest.TestCase):
    """极端配置组合下的行为约定。

    单个参数各自的边界已有测试，但**组合**没有：容差最小 + 条数最大 + 组分最大 +
    滴数最大同时出现时，既不该崩，也不该给出超出配置的配方。这轮把这些组合跑一遍，
    确认没有缺陷（此前完全没有覆盖）。
    """

    def test_min_and_max_combinations_do_not_break(self):
        from app.core.config import AppConfig
        from app.services.paint_matcher import PaintMatcher

        matcher = PaintMatcher()
        cases = [
            dict(match_tolerance=0.2, max_suggestions=20, max_recipe_components=3,
                 drop_total=200, area_m2=50.0, coats=8, thinner_ratio=5.0,
                 waste_buffer=3.0, fixed_paint_loss_ml=20.0),
            dict(match_tolerance=20.0, max_suggestions=1, max_recipe_components=1,
                 drop_total=4, area_m2=0.0005, coats=1, thinner_ratio=0.0,
                 waste_buffer=1.0, fixed_paint_loss_ml=0.0),
        ]
        for overrides in cases:
            cfg = AppConfig().validate()
            for key, value in overrides.items():
                setattr(cfg, key, value)
            cfg.validate()
            items = matcher.suggest((216, 118, 68), cfg)
            self.assertLessEqual(len(items), cfg.max_suggestions)
            for item in items:
                self.assertLessEqual(len(item.recipe.components),
                                     cfg.max_recipe_components)
                self.assertGreaterEqual(item.coverage.paint_ml, 0.0)
                self.assertTrue(all(c.drops >= 0 for c in item.recipe.components))

    def test_drop_total_respected_at_the_extremes(self):
        from app.core.config import AppConfig
        from app.services.paint_matcher import PaintMatcher

        matcher = PaintMatcher()
        for total in (4, 200):
            cfg = AppConfig().validate()
            cfg.drop_total = total
            for item in matcher.suggest((216, 118, 68), cfg):
                if not item.is_direct:
                    self.assertEqual(sum(c.drops for c in item.recipe.components), total)
