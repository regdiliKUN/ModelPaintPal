# -*- coding: utf-8 -*-
"""交互与体验层的回归测试（offscreen）。

覆盖第三轮优化的 UX 修复点，每条都对应一个**真实会误导用户的行为**：

* 设置页初始值必须等于真实配置（否则一动开关就把参数写成最小值）
* 设置改动必须触发重算（否则"改了没生效"）
* 「全部品牌」必须真的搜全库
* 手动输入非法颜色必须就地给出文字原因
* 参数面板连续变更必须防抖（拖动 SpinBox 不能触发几十次重算）
* 调色微调必须能改目标色、但不污染历史
* Toast 必须堆叠而不是互相覆盖
"""

import os
import sys
import time
import unittest
from tests import qt_cleanup

qt_cleanup.install()
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.config import AppConfig  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.widgets.toast import active_toasts, show_toast  # noqa: E402


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is None:
        return QApplication([])
    if not isinstance(existing, QApplication):
        raise AssertionError("进程内已存在 QCoreApplication，无法创建 QApplication")
    return existing


def _pump(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


class _WindowCase(unittest.TestCase):
    """构造窗口时屏蔽磁盘写入与真实计算，保证测试不碰用户配置。"""

    config_overrides: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self.config = AppConfig()
        self.config.show_onboarding = False
        self.config.auto_copy_on_pick = False
        for key, value in self.config_overrides.items():
            setattr(self.config, key, value)
        self.submitted = []

        def _fake_submit(matcher, rgb, config, brands, coverage, token, on_done,
                         on_error=None):
            self.submitted.append({"rgb": tuple(rgb), "brands": list(brands), "token": token})
            return None

        self._patches = [
            mock.patch("app.ui.main_window.save_config", lambda cfg: True),
            mock.patch("app.ui.main_window.submit_suggest", _fake_submit),
            mock.patch("app.ui.panels.settings_panel.save_config", lambda cfg: True),
        ]
        for patch in self._patches:
            patch.start()
        self.window = MainWindow(self.config)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        for patch in self._patches:
            patch.stop()


class TestSettingsSync(_WindowCase):
    config_overrides = {"match_tolerance": 4.5, "max_suggestions": 9,
                        "max_recipe_components": 2, "drop_total": 33}

    def test_widgets_match_config_on_open(self):
        """A1：设置页一打开就必须显示真实配置，而不是各控件的最小值。"""
        panel = self.window._settings_panel
        self.assertAlmostEqual(panel._tolerance.value(), 4.5)
        self.assertEqual(panel._max_suggestions.value(), 9)
        self.assertEqual(panel._max_components.value(), 2)
        self.assertEqual(panel._drop_total.value(), 33)
        self.assertEqual(panel._pick_hotkey.text(), self.config.pick_hotkey)

    def test_toggling_one_option_keeps_others(self):
        """A1：动一个开关不能把其它字段写成最小值。"""
        panel = self.window._settings_panel
        panel._follow.setChecked(not self.config.magnifier_follow)
        self.assertAlmostEqual(self.config.match_tolerance, 4.5)
        self.assertEqual(self.config.max_suggestions, 9)
        self.assertEqual(self.config.max_recipe_components, 2)
        self.assertEqual(self.config.drop_total, 33)

    def test_settings_change_triggers_recompute(self):
        """A2：改容差必须立刻重算，而不是等下一次取色。"""
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        self.submitted.clear()
        self.window._settings_panel._tolerance.setValue(6.0)
        self.app.processEvents()
        self.assertTrue(self.submitted, "改直用容差后应提交一次重算")

    def test_restore_defaults(self):
        """A10：恢复默认设置要把参数写回出厂值。"""
        self.window._settings_panel._on_restore_defaults()
        self.assertAlmostEqual(self.config.match_tolerance, AppConfig().match_tolerance)
        self.assertEqual(self.config.max_suggestions, AppConfig().max_suggestions)
        self.assertEqual(self.window._settings_panel._max_suggestions.value(),
                         AppConfig().max_suggestions)


class TestBrandScope(_WindowCase):
    def test_all_brands_option_passes_empty_scope(self):
        """A3：「全部品牌」必须以空范围提交，让服务层按全库检索。"""
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        self.window._suggest_panel._brand_combo.setCurrentIndex(1)   # 先切到单品牌
        self.submitted.clear()
        self.window._suggest_panel._brand_combo.setCurrentIndex(0)   # 再切回全部品牌
        self.app.processEvents()
        self.assertTrue(self.submitted)
        self.assertEqual(self.submitted[-1]["brands"], [])

    def test_brand_choice_persists_to_config(self):
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        self.submitted.clear()
        self.window._suggest_panel._brand_combo.setCurrentIndex(1)  # 第一个单品牌
        self.app.processEvents()
        self.assertEqual(len(self.config.preferred_brands), 1)
        self.assertEqual(self.submitted[-1]["brands"], self.config.preferred_brands)


class TestManualInputFeedback(_WindowCase):
    def test_invalid_input_shows_inline_reason(self):
        """A4：非法输入必须就地给出文字原因（而不是只染红边框）。"""
        panel = self.window._pick_panel
        panel._input.setText("这不是颜色")
        panel._submit_manual()
        self.assertTrue(panel._error.isVisible() or panel._error.text())
        self.assertIn("无法识别", panel._error.text())
        self.assertIn("#RRGGBB", panel._error.text())

    def test_error_clears_when_typing(self):
        panel = self.window._pick_panel
        panel._input.setText("zzz")
        panel._submit_manual()
        self.assertTrue(panel._error.text())
        panel._input.setText("#123456")
        self.assertFalse(panel._error.isVisible())
        self.assertEqual(panel._error.text(), "")

    def test_empty_input_keeps_import_disabled(self):
        """A13：空输入时「导入」按钮不可点。"""
        panel = self.window._pick_panel
        self.assertFalse(panel._input_button.isEnabled())
        panel._input.setText("#123")
        self.assertTrue(panel._input_button.isEnabled())

    def test_valid_input_is_applied(self):
        panel = self.window._pick_panel
        panel._input.setText("rgb(10, 20, 30)")
        panel._submit_manual()
        self.assertEqual(tuple(self.window._sample.rgb), (10, 20, 30))
        self.assertFalse(panel._error.text())


class TestComputeDebounce(_WindowCase):
    def test_rapid_parameter_changes_compute_once(self):
        """A6：连续 20 次参数变更只应触发 1 次重算。"""
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        self.submitted.clear()
        for value in range(20):
            self.window._coverage_panel._area.setValue(300 + value * 10)
        self.assertEqual(len(self.submitted), 0, "防抖窗口内不应立刻计算")
        _pump(self.app, 0.45)
        self.assertEqual(len(self.submitted), 1, "防抖后应只计算一次")

    def test_pick_is_immediate(self):
        """吸色必须立刻算，不能被防抖拖延。"""
        self.submitted.clear()
        self.window._apply_color((10, 20, 30), source="test", remember=False)
        self.assertEqual(len(self.submitted), 1)


class TestColorTuner(_WindowCase):
    def test_tuning_changes_target_without_history(self):
        """A8：微调能改目标色，但不写历史、不重置滑块。"""
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        history_before = len(self.window._history.all())
        tuner = self.window._pick_panel.tuner()
        tuner.expand(True)
        tuner._sliders["val"][0].setValue(70)
        tuner._emit_change()
        self.app.processEvents()
        self.assertNotEqual(tuple(self.window._sample.rgb), (120, 96, 72))
        self.assertEqual(len(self.window._history.all()), history_before)
        self.assertEqual(self.window._base_rgb, (120, 96, 72))

    def test_reset_restores_base_color(self):
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        tuner = self.window._pick_panel.tuner()
        tuner.expand(True)
        tuner._sliders["val"][0].setValue(70)
        tuner._emit_change()
        self.app.processEvents()
        self.assertNotEqual(tuple(self.window._sample.rgb), (120, 96, 72))
        tuner._on_reset()
        self.app.processEvents()
        self.assertEqual(tuple(self.window._sample.rgb), (120, 96, 72))

    def test_tuner_disabled_before_pick(self):
        self.assertFalse(self.window._pick_panel.tuner().isEnabled())


class TestTunerRoundTrip(_WindowCase):
    def test_drag_back_to_base_refreshes(self):
        """把滑块拖回原位也必须刷新界面（否则显示的还是上一个微调色）。"""
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        tuner = self.window._pick_panel.tuner()
        tuner.expand(True)
        base = tuner._sliders["val"][0].value()
        tuner._sliders["val"][0].setValue(70)
        tuner._emit_change()
        self.app.processEvents()
        self.assertNotEqual(tuple(self.window._sample.rgb), (120, 96, 72))
        tuner._sliders["val"][0].setValue(base)
        tuner._emit_change()
        self.app.processEvents()
        self.assertEqual(tuple(self.window._sample.rgb), (120, 96, 72))


class TestUsageChips(_WindowCase):
    def test_multi_component_recipe_shows_per_paint_ml(self):
        """多色配方必须给出每支漆各要多少 ml。"""
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        from app.data.paint_db import get_database
        from app.services.paint_matcher import PaintMatcher

        suggestions = PaintMatcher(get_database()).suggest(
            (120, 96, 72), self.window._config, brands=[])
        multi = [s for s in suggestions if len(s.recipe.components) > 1]
        if not multi:
            self.skipTest("当前数据下没有多色配方")
        from app.ui.panels.suggestion_card import SuggestionCard

        card = SuggestionCard()
        card.set_suggestion(multi[0], (120, 96, 72))
        texts = [chip.text() for chip in card._chips if chip.text()]
        codes = [comp.paint.code for comp in multi[0].recipe.components]
        for code in codes:
            self.assertTrue(any(code in text for text in texts), f"{code} 的用量缺失: {texts}")


class TestComputeFailure(_WindowCase):
    def test_failure_is_reported_not_shown_as_no_match(self):
        """计算失败要明确提示，不能显示成"没有找到可用建议"。"""
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        token = self.window._suggest_token
        self.window._on_suggest_failed("模拟失败", token)
        self.assertEqual(self.window._suggestions, [])
        self.assertIn("计算失败", self.window._suggest_panel._empty._title.text())
        self.assertIn("模拟失败", self.window._suggest_panel._empty._description.text())

    def test_stale_failure_is_ignored(self):
        """旧任务迟到的失败不能覆盖新一次计算的状态。"""
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        stale = self.window._suggest_token - 1
        self.window._on_suggest_failed("旧任务失败", stale)
        self.assertNotIn("计算失败", self.window._suggest_panel._empty._title.text())


class TestSettingsRecomputeScope(_WindowCase):
    def test_irrelevant_setting_does_not_recompute(self):
        """改历史条数不影响匹配结果，不该触发重算。"""
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        self.submitted.clear()
        self.window._settings_panel._history_limit.setValue(77)
        self.app.processEvents()
        self.assertEqual(self.submitted, [])

    def test_matching_setting_does_recompute(self):
        self.window._apply_color((120, 96, 72), source="test", remember=False)
        self.submitted.clear()
        self.window._settings_panel._tolerance.setValue(1.5)
        self.app.processEvents()
        self.assertEqual(len(self.submitted), 1)


class TestTabShortcuts(_WindowCase):
    def test_view_menu_has_number_shortcuts(self):
        actions = []
        for action in self.window.menuBar().actions():
            menu = action.menu()
            if menu is not None and action.text() == "视图":
                actions = [a.shortcut().toString() for a in menu.actions()]
        self.assertEqual(actions, ["Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4"])


class TestToastStack(_WindowCase):
    def test_two_messages_stack_without_overlap(self):
        """A7：两条提示必须上下排开，不能互相覆盖。"""
        first = show_toast(self.window, "第一条", "success")
        second = show_toast(self.window, "第二条", "info")
        self.app.processEvents()
        self.assertNotEqual(first.y(), second.y())
        self.assertLess(second.y(), first.y())      # 新的在上
        self.assertEqual(len(active_toasts(self.window)), 2)

    def test_same_message_does_not_duplicate(self):
        show_toast(self.window, "重复消息", "info")
        show_toast(self.window, "重复消息", "info")
        self.assertEqual(len(active_toasts(self.window)), 1)

    def test_stack_is_capped(self):
        for index in range(5):
            show_toast(self.window, f"消息 {index}", "info")
        self.assertLessEqual(len(active_toasts(self.window)), 3)


class TestEmptyStateAction(_WindowCase):
    def test_empty_states_offer_pick_action(self):
        """A5：空状态要就地给出「开始吸色」，而不是让用户自己去别处找。"""
        suggest = self.window._suggest_panel
        self.assertIsNotNone(suggest._empty._action)
        self.assertEqual(suggest._empty._action.text(), "开始吸色")
        self.assertIsNotNone(self.window._visualize_panel._empty._action)

    def test_empty_action_is_wired_to_pick(self):
        """空状态按钮必须真的接到「开始吸色」上（而不是摆着好看）。"""
        panel = self.window._suggest_panel
        button = panel._empty._action
        self.assertIsNotNone(button)
        # 点按钮 → 空状态自身发出 pickRequested → 主窗口接收
        received = []
        panel.pickRequested.connect(lambda: received.append(True))
        button.click()
        self.assertEqual(received, [True])

    def test_empty_state_text_updates_without_stale_description(self):
        empty = self.window._suggest_panel._empty
        empty.set_text("标题A", "说明A")
        empty.set_text("标题B", "")
        self.assertEqual(empty._title.text(), "标题B")
        self.assertEqual(empty._description.text(), "")
        self.assertFalse(empty._description.isVisible())


if __name__ == "__main__":
    unittest.main()
