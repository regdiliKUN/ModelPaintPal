"""UI and service agreement for the 1.1.0 fixes."""

import os
import unittest
from unittest.mock import patch

from tests import qt_cleanup

qt_cleanup.install()

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from app.core.config import AppConfig  # noqa: E402
from app.data.paint_db import get_database  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402
from app.ui.panels.coverage_panel import CoveragePanel  # noqa: E402
from app.ui.panels.settings_panel import SettingsPanel  # noqa: E402


class TestAuditUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_coverage_panel_uses_same_adjusted_estimate_as_card(self):
        cfg = AppConfig()
        matcher = PaintMatcher(get_database())
        paint = next(p for p in matcher.db.by_brand('sms') if p.opacity == 'semi')
        suggestions = matcher.suggest(paint.rgb, cfg, brands=['sms'])
        panel = CoveragePanel(cfg)
        panel.set_suggestions(suggestions)
        estimate = suggestions[0].coverage
        text = panel._summary.text()
        self.assertIn(f'{estimate.coats} 层', text)
        self.assertIn(f'稀释剂 {estimate.thinner_ml:.2f} ml', text)
        self.assertEqual(estimate.thinner_ml, 0.0)
        self.assertEqual(panel._rate.value(), cfg.mix_ml_per_m2_per_coat / 2)
        panel.deleteLater()
        self.app.processEvents()

    def test_new_controls_commit_and_request_recompute(self):
        cfg = AppConfig()
        with patch('app.ui.panels.settings_panel.save_config'):
            settings = SettingsPanel(cfg)
            changes = []
            settings.settingsChanged.connect(lambda: changes.append(True))
            settings._allow_cross_brand.setChecked(True)
            self.assertTrue(cfg.allow_cross_brand_mix)
            self.assertTrue(changes)
            settings.deleteLater()
            self.app.processEvents()
        panel = CoveragePanel(cfg)
        panel._auto_prethinned.setChecked(False)
        panel._fixed_loss.setValue(0.25)
        self.assertFalse(cfg.auto_prethinned)
        self.assertEqual(panel.coverage_input().fixed_paint_loss_ml, 0.25)
        panel._rate.setValue(40.0)
        self.assertEqual(cfg.mix_ml_per_m2_per_coat, 80.0)
        panel.deleteLater()
        self.app.processEvents()

    def test_small_coverage_panel_can_scroll_to_all_controls(self):
        panel = CoveragePanel(AppConfig())
        panel.resize(650, 400)
        panel.show()
        self.app.processEvents()
        self.assertGreater(panel._scroll.verticalScrollBar().maximum(), 0)
        panel.close()
        panel.deleteLater()
        self.app.processEvents()

    def test_coverage_labels_do_not_claim_automotive_measurement(self):
        panel = CoveragePanel(AppConfig())
        text = '\n'.join(label.text() for label in panel.findChildren(QLabel))
        self.assertNotIn('汽车底色漆约', text)
        self.assertIn('原漆单位用量', text)
        panel.deleteLater()
        self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
