# -*- coding: utf-8 -*-
"""配色方案面板（色环方案 → 真实漆）。

这个页面是给 `scheme_engine` 里那 7 种方案补的入口——此前它们只有测试在调用，
界面上摸不到。测试重点不是像素，而是「换方案会重算、色数控件只在有意义的方案上可用、
超容差的色差要明说」。
"""

import os
import sys
import unittest
from pathlib import Path

from tests import qt_cleanup

qt_cleanup.install()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.config import AppConfig  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402
from app.services.scheme_engine import (  # noqa: E402
    SCHEME_ORDER, SchemeType, build_scheme, default_param_for,
)
from app.ui.panels.scheme_plan_panel import SchemePlanPanel  # noqa: E402

TARGET = (120, 96, 72)


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        if not isinstance(existing, QApplication):
            raise AssertionError("进程内已存在 QCoreApplication，无法创建 QApplication")
        return existing
    return QApplication([])


class SchemePlanPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.config = AppConfig().validate()
        cls.matcher = PaintMatcher()

    def setUp(self):
        self.panel = SchemePlanPanel()
        self.requests = []
        self.panel.planRequested.connect(
            lambda scheme_type, param: self.requests.append((scheme_type, param)))

    def tearDown(self):
        self.panel.deleteLater()

    def test_default_is_basic_palette(self):
        self.assertEqual(self.panel.scheme_type(), SchemeType.BASIC)
        self.assertEqual(len(SCHEME_ORDER), 7)

    def test_param_controls_only_enabled_for_param_schemes(self):
        """色数只对邻近/单色系有意义，其它方案应灰掉而不是隐藏（隐藏会让工具条跳动）。"""
        self.assertFalse(self.panel._count_spin.isEnabled())
        self.panel.set_scheme(SchemeType.ANALOGOUS, 5)
        self.assertTrue(self.panel._count_spin.isEnabled())
        self.assertEqual(self.panel._count_spin.value(), 5)
        self.panel.set_scheme(SchemeType.TRIADIC)
        self.assertFalse(self.panel._count_spin.isEnabled())

    def test_changing_type_emits_request(self):
        self.panel.set_scheme(SchemeType.COMPLEMENTARY)
        self.requests.clear()
        self.panel._type_combo.setCurrentIndex(
            self.panel._type_combo.findData(SchemeType.TETRADIC))
        self.assertEqual(self.requests[-1], (SchemeType.TETRADIC, 0))

    def test_changing_count_emits_request_with_param(self):
        self.panel.set_scheme(SchemeType.ANALOGOUS, 5)
        self.requests.clear()
        self.panel._count_spin.setValue(7)
        self.assertEqual(self.requests[-1], (SchemeType.ANALOGOUS, 7))

    def test_unknown_scheme_type_is_ignored(self):
        """配置里残留的旧方案名不能把界面搞崩，也不能改掉当前选择。"""
        before = self.panel.scheme_type()
        self.panel.set_scheme("no-such-scheme", 3)
        self.assertEqual(self.panel.scheme_type(), before)

    def test_stops_are_rendered_and_extra_rows_hidden(self):
        stops = build_scheme(self.matcher, TARGET, self.config,
                            scheme_type=SchemeType.BASIC)
        self.assertEqual(len(stops), 5)
        self.panel.set_stops(stops)
        # 面板本身没 show()，isVisible() 恒为 False；用 isHidden() 判断「被显式隐藏」
        shown = [row for row in self.panel._rows if not row.isHidden()]
        self.assertEqual(len(shown), len(stops))
        first = self.panel._rows[0]
        self.assertEqual(first._role.text(), stops[0].role)
        self.assertEqual(first._hex.text(), stops[0].target_hex)

    def test_empty_stops_switch_to_empty_state(self):
        self.panel.set_stops([])
        self.assertTrue(self.panel._empty.isVisibleTo(self.panel))
        self.assertFalse(self.panel._scroll.isVisibleTo(self.panel))

    def test_out_of_tolerance_delta_e_says_so(self):
        """色差偏大要写进文字，不能只靠颜色——色弱用户和黑白截图里看不出来。"""
        stops = build_scheme(self.matcher, TARGET, self.config,
                            scheme_type=SchemeType.BASIC)
        self.panel.set_stops(stops)
        for row, stop in zip(self.panel._rows, stops):
            if stop.suggestion is None:
                continue
            if stop.suggestion.is_within_tolerance:
                self.assertNotIn("色差偏大", row._de.text())
            else:
                self.assertIn("色差偏大", row._de.text())

    def test_busy_state_reuses_status_line(self):
        self.panel.set_busy(True)
        self.assertTrue(self.panel._status.is_busy)
        self.panel.set_busy(False)
        self.assertFalse(self.panel._status.is_busy)


class DefaultParamTest(unittest.TestCase):
    def test_default_param_matches_scheme(self):
        self.assertEqual(default_param_for(SchemeType.ANALOGOUS), 5)
        self.assertEqual(default_param_for(SchemeType.MONOCHROMATIC), 5)
        self.assertEqual(default_param_for(SchemeType.BASIC), 0)


if __name__ == "__main__":
    unittest.main()
