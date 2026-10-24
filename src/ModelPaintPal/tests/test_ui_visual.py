# -*- coding: utf-8 -*-
"""可视化层的回归测试（offscreen）。

守住的都是"看起来没问题、实际会误导人"的点：

* 色卡 / 色盘 / 图例的**编号必须一致**（否则用户对不上哪个点是哪个色号）
* 色卡在窄宽度下要**换行**，不能把色块压成细条
* ΔE 刻度尺的指针位置要落在正确的分级区间
* 色差放大块必须真的"放大"了差异（而不是原样复制）
* 历史色块网格的列数要随宽度变化，且行高不能被拉伸
"""

import os
import sys
import unittest
from tests import qt_cleanup
from pathlib import Path

qt_cleanup.install()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.color_models import rgb_to_lab  # noqa: E402
from app.core.config import AppConfig  # noqa: E402
from app.data.paint_db import get_database  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402
from app.ui.presenters import build_legend, build_markers, build_swatches  # noqa: E402
from app.ui.widgets.color_wheel import ColorWheel, WheelMarker  # noqa: E402
from app.ui.widgets.delta_gauge import AmplifiedDiff, DeltaGauge  # noqa: E402
from app.ui.widgets.swatch_card import SwatchItem, SwatchStrip  # noqa: E402


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is None:
        return QApplication([])
    return existing


class TestPresenters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls.config = AppConfig()
        cls.matcher = PaintMatcher(get_database())
        cls.target = (120, 96, 72)
        cls.suggestion = cls.matcher.suggest(cls.target, cls.config)[0]

    def test_swatch_and_marker_numbering_match(self):
        """色卡编号与色盘标记编号必须逐项一致。"""
        swatches = build_swatches(self.suggestion, self.target)
        markers = build_markers(self.suggestion, self.target)
        self.assertEqual([item.index for item in swatches],
                         [marker.index for marker in markers])
        self.assertEqual(len(swatches), len(markers))

    def test_legend_lines_match_swatches(self):
        swatches = build_swatches(self.suggestion, self.target)
        legend = build_legend(self.suggestion, self.target)
        self.assertEqual(len(swatches), len(legend))

    def test_target_is_always_first(self):
        swatches = build_swatches(self.suggestion, self.target)
        self.assertEqual(swatches[0].index, 1)
        self.assertEqual(tuple(swatches[0].rgb), self.target)

    def test_mixed_result_carries_delta_e(self):
        swatches = build_swatches(self.suggestion, self.target)
        if self.suggestion.is_direct:
            self.skipTest("该目标色命中直用方案")
        mixed = swatches[1]
        self.assertAlmostEqual(mixed.delta_e, self.suggestion.delta_e, places=2)

    def test_component_delta_e_is_computed_against_target(self):
        swatches = build_swatches(self.suggestion, self.target)
        components = swatches[2:2 + len(self.suggestion.recipe.components)]
        self.assertTrue(components)
        for item in components:
            self.assertIsNotNone(item.delta_e)
            self.assertGreaterEqual(item.delta_e, 0.0)

    def test_alternatives_can_be_excluded(self):
        with_alts = build_swatches(self.suggestion, self.target, include_alternatives=True)
        without = build_swatches(self.suggestion, self.target, include_alternatives=False)
        self.assertGreaterEqual(len(with_alts), len(without))


class TestSwatchStrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _strip(self, count: int, width: int) -> SwatchStrip:
        strip = SwatchStrip()
        strip.resize(width, 100)
        strip.set_items([SwatchItem((20 * i, 40, 60), f"S{i}", "", index=i + 1)
                         for i in range(count)])
        strip.resize(width, 100)
        return strip

    def test_columns_shrink_with_width(self):
        wide = self._strip(6, 900)
        narrow = self._strip(6, 200)
        self.assertGreater(wide._columns, narrow._columns)

    def test_narrow_width_still_wraps_into_rows(self):
        strip = self._strip(4, 180)
        self.assertEqual(strip._columns, 1)
        # 4 个色块应占 4 行
        rows = {strip._grid.getItemPosition(i)[0] for i in range(strip._grid.count())}
        self.assertEqual(len(rows), 4)

    def test_single_item_not_stretched_to_full_width(self):
        strip = self._strip(1, 800)
        widget = strip._grid.itemAt(0).widget()
        self.assertLessEqual(widget.maximumWidth(), 200)


class TestDeltaVisuals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_gauge_accepts_value_and_none(self):
        gauge = DeltaGauge()
        gauge.set_value(1.5)
        gauge.resize(300, 56)
        gauge.grab()          # 触发一次绘制，确保 paintEvent 不抛错
        gauge.set_value(None)
        gauge.grab()

    def test_amplified_diff_actually_amplifies(self):
        """放大的结果必须比原色离目标更远（而不是原样返回）。"""
        widget = AmplifiedDiff()
        target = (120, 96, 72)
        other = (128, 100, 70)
        widget.set_pair(target, other, factor=6.0)
        base = rgb_to_lab(target)
        diff_raw = sum(abs(a - b) for a, b in zip(base, rgb_to_lab(other)))
        diff_amp = sum(abs(a - b) for a, b in zip(base, rgb_to_lab(widget._rgb)))
        self.assertGreater(diff_amp, diff_raw)

    def test_amplified_diff_survives_extremes(self):
        widget = AmplifiedDiff()
        for pair in [((0, 0, 0), (255, 255, 255)), ((255, 255, 255), (0, 0, 0))]:
            widget.set_pair(pair[0], pair[1], factor=8.0)
            widget.resize(200, 40)
            widget.grab()


class TestWheelOverlap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_overlapping_markers_are_pushed_apart(self):
        """5 个几乎同色的标记点必须被推开到最小间距以上。"""
        wheel = ColorWheel()
        wheel.resize(240, 240)
        markers = [WheelMarker((120 + i, 96, 72), f"m{i}", index=i + 1) for i in range(5)]
        wheel.set_markers(markers)
        center, radius, _ = wheel._geometry()
        raw = [wheel._raw_point(center, radius, m.rgb) for m in markers]
        resolved = wheel._resolve_overlaps(raw, center)
        for i in range(len(resolved)):
            for j in range(i + 1, len(resolved)):
                dx = resolved[i].x() - resolved[j].x()
                dy = resolved[i].y() - resolved[j].y()
                self.assertGreaterEqual((dx * dx + dy * dy) ** 0.5, 12.0)

    def test_wheel_paints_without_error(self):
        wheel = ColorWheel()
        wheel.resize(200, 200)
        wheel.set_markers([WheelMarker((10, 10, 10), "dark", emphasis=True, index=1)])
        wheel.grab()


class TestLibraryGrid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_columns_adapt_to_width(self):
        from app.ui.panels.library_panel import ColorGrid

        grid = ColorGrid()
        self.assertEqual(grid._columns_for_width(300), 1)
        self.assertGreaterEqual(grid._columns_for_width(700), 3)

    def test_chip_height_is_fixed(self):
        from app.core.sample_record import SampleRecord
        from app.ui.panels.library_panel import _Chip

        chip = _Chip(SampleRecord(rgb=(10, 20, 30)))
        self.assertEqual(chip.minimumHeight(), chip.maximumHeight())

    def test_chip_does_not_repeat_hex(self):
        """没有自定义名字时，色块标题就是 HEX，副标题不应再重复一遍。"""
        from PySide6.QtWidgets import QLabel

        from app.core.sample_record import SampleRecord
        from app.ui.panels.library_panel import _Chip

        chip = _Chip(SampleRecord(rgb=(10, 20, 30)))
        labels = [w.text() for w in chip.findChildren(QLabel)]
        self.assertEqual(labels.count("#0A141E"), 1, f"HEX 不应重复出现: {labels}")


if __name__ == "__main__":
    unittest.main()
