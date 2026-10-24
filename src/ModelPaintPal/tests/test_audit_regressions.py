"""Regressions reproduced in the installed application on 2026-10-25."""

import unittest
import json

from app.core.color_models import rgb_to_lab
from app.core.config import AppConfig
from app.data.paint_db import get_database
from app.services.coverage import CoverageInput, estimate_coverage
from app.services.paint_matcher import PaintMatcher
from app.services.recipe_engine import _build_recipe, build_direct_recipe
from app.services.export_service import suggestions_to_json
from app.data.brands import BRANDS


class TestAuditRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_database()
        cls.matcher = PaintMatcher(cls.db)

    def test_executable_drops_determine_color_and_amounts(self):
        paints = self.db.by_brand('tamiya')[:2]
        recipe = _build_recipe(paints, [0.73, 0.27], rgb_to_lab((217, 161, 140)),
                               'kubelka_munk', 'CIEDE2000', 20)
        total = sum(c.drops for c in recipe.components)
        for component in recipe.components:
            self.assertAlmostEqual(component.proportion, component.drops / total)
            self.assertAlmostEqual(component.percent, component.drops * 100 / total)
        executable = _build_recipe(paints, [0.75, 0.25], rgb_to_lab((217, 161, 140)),
                                   'kubelka_munk', 'CIEDE2000', 20)
        self.assertEqual(recipe.mixed_rgb, executable.mixed_rgb)
        self.assertEqual(recipe.delta_e, executable.delta_e)

    def test_recommendations_are_sorted_by_actual_delta_e(self):
        cfg = AppConfig(max_recipe_components=2)
        suggestions = self.matcher.suggest((217, 161, 140), cfg, brands=[])
        distances = [s.delta_e for s in suggestions]
        self.assertEqual(distances, sorted(distances))

    def test_default_recipes_stay_in_one_product_line(self):
        cfg = AppConfig(max_recipe_components=2)
        suggestions = self.matcher.suggest((217, 161, 140), cfg, brands=[])
        self.assertTrue(suggestions)
        for suggestion in suggestions:
            self.assertEqual(len({c.paint.brand_key for c in suggestion.recipe.components}), 1)

    def test_outside_tolerance_note_does_not_claim_direct_or_measured(self):
        cfg = AppConfig(match_tolerance=0.01)
        recipe = build_direct_recipe(self.db.by_brand('ak_3gen')[0],
                                     rgb_to_lab((217, 161, 140)))
        self.assertGreater(recipe.delta_e, cfg.match_tolerance)
        notes = ' '.join(self.matcher._notes(recipe, cfg, estimate_coverage(CoverageInput())))
        self.assertNotIn('可直接瓶用', notes)
        self.assertNotIn('实测', notes)
        self.assertIn('单色近似', notes)

    def test_more_thinner_does_not_reduce_required_paint(self):
        estimates = [estimate_coverage(CoverageInput(thinner_ratio=r)) for r in (0, 1, 2)]
        self.assertEqual(len({e.paint_ml for e in estimates}), 1)
        self.assertLess(estimates[0].mix_ml, estimates[1].mix_ml)
        self.assertLess(estimates[1].mix_ml, estimates[2].mix_ml)

    def test_fixed_loss_is_added_once(self):
        for area in (0.005, 0.05):
            for coats in (1, 3):
                base = estimate_coverage(CoverageInput(area_m2=area, coats=coats))
                fixed = estimate_coverage(CoverageInput(area_m2=area, coats=coats,
                                                       fixed_paint_loss_ml=0.3))
                self.assertAlmostEqual(fixed.paint_ml - base.paint_ml, 0.3, places=3)
                self.assertAlmostEqual(fixed.thinner_ml - base.thinner_ml, 0.3, places=3)

    def test_legacy_config_keeps_reference_one_to_one_estimate(self):
        cfg = AppConfig.from_dict({'mix_ml_per_m2_per_coat': 110.0})
        estimate = estimate_coverage(CoverageInput(mix_ml_per_m2_per_coat=cfg.mix_ml_per_m2_per_coat))
        self.assertAlmostEqual(estimate.paint_ml, 8.539, places=3)
        self.assertAlmostEqual(estimate.mix_ml, 17.078, places=3)

    def test_prethinned_can_be_automatic_or_manually_overridden(self):
        paint = self.db.by_brand('sms')[0]
        recipe = build_direct_recipe(paint, paint.lab)
        cfg = AppConfig(thinner_ratio=2.0)
        automatic = self.matcher._estimate(recipe, cfg, None)
        self.assertEqual(automatic.thinner_ml, 0.0)
        cfg.auto_prethinned = False
        manual = self.matcher._estimate(recipe, cfg, None)
        self.assertAlmostEqual(manual.paint_ml, automatic.paint_ml, places=3)
        self.assertAlmostEqual(manual.thinner_ml, manual.paint_ml * 2, delta=0.002)

    def test_cross_line_mix_requires_opt_in(self):
        cfg = AppConfig(max_recipe_components=2, allow_cross_brand_mix=True)
        suggestions = self.matcher.suggest((217, 161, 140), cfg, brands=[])
        mixed = [s for s in suggestions if len({c.paint.brand_key for c in s.recipe.components}) > 1]
        self.assertTrue(mixed)
        self.assertTrue(all(any('兼容性未验证' in note for note in s.notes) for s in mixed))

    def test_export_contains_execution_basis_and_component_amounts(self):
        cfg = AppConfig(max_recipe_components=2)
        payload = json.loads(suggestions_to_json(self.matcher.suggest((217, 161, 140), cfg),
                                                 (217, 161, 140)))
        self.assertEqual(payload['ratio_basis'], 'integer_drops')
        self.assertEqual(payload['delta_e_kind'], 'predicted_swatch')
        for row in payload['suggestions']:
            total = sum(c['drops'] for c in row['components'])
            self.assertIn('per_component', row['coverage_ml'])
            for c in row['components']:
                self.assertAlmostEqual(c['percent'], c['drops'] * 100 / total, delta=0.051)

    def test_metadata_separates_sms_and_corrects_real_colors(self):
        self.assertNotIn('星影', BRANDS['sms'].name)
        self.assertEqual(BRANDS['sms'].region, '澳大利亚')
        self.assertEqual(BRANDS['ak_rc'].paint_type, 'lacquer')

    def test_new_settings_survive_config_round_trip(self):
        cfg = AppConfig(allow_cross_brand_mix=True, auto_prethinned=False, fixed_paint_loss_ml=0.25)
        restored = AppConfig.from_dict(cfg.to_dict())
        self.assertTrue(restored.allow_cross_brand_mix)
        self.assertFalse(restored.auto_prethinned)
        self.assertEqual(restored.fixed_paint_loss_ml, 0.25)

    def test_fixed_loss_rejects_nonfinite_values(self):
        with self.assertRaises(ValueError):
            estimate_coverage(CoverageInput(fixed_paint_loss_ml=float('nan')))


if __name__ == '__main__':
    unittest.main()
