# -*- coding: utf-8 -*-
"""移动端界面冒烟测试：构建完整控件树并驱动各页渲染（无需真实显示）。

本测试不调用 ``App.run()``，因此不会创建 GL 窗口，可在无头环境运行；
它验证所有页面能正确构建、各计算结果能渲染为控件、且不抛异常。
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
os.environ.setdefault("KIVY_NO_ARGS", "1")

ROOT = Path(__file__).resolve().parents[2]  # src/ModelPaintPal
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mobile.bootstrap  # noqa: E402  —— 先重定向用户目录
_ = mobile.bootstrap.ROOT  # 确保路径重定向副作用已执行
import mobile.app as appmod  # noqa: E402  —— 触发整套前端导入（不应引入 PySide6）
from kivy.app import App  # noqa: E402
from mobile import logic  # noqa: E402  —— 核心访问器（get_db/get_config/get_matcher）


class UISmokeTest(unittest.TestCase):
    def setUp(self):
        # 构造 App 但不运行（不创建 GL 窗口）
        self.app = appmod.MppApp()
        App._running_app = self.app  # 让各页的 app 属性可解析（仅测试用）
        self.root = self.app.build()

    def test_app_builds_all_screens(self):
        self.assertEqual(len(self.app.screens), 9)
        for name in ("pick", "suggest", "visualize", "mix", "more",
                     "coverage", "library", "settings", "about"):
            self.assertIn(name, self.app.screens)

    def test_full_widget_tree_constructed(self):
        from kivy.uix.boxlayout import BoxLayout
        self.assertIsInstance(self.root, BoxLayout)
        self.assertIsNotNone(self.app.nav)
        self.assertIsNotNone(self.app.sm)

    def test_suggest_screen_renders_cards(self):
        from app.services.paint_matcher import PaintMatcher
        rgb = (226, 174, 121)
        matcher = PaintMatcher(logic.get_db())
        sug = matcher.suggest(rgb, logic.get_config(), brands=[])
        scr = self.app.screens["suggest"]
        scr._on_done(sug)
        self.assertGreater(len(scr._list.children), 0,
                          "建议页应渲染出卡片")

    def test_mix_screen_renders_bar(self):
        from app.services.scheme_engine import compute_base_mix
        cfg = logic.get_config()
        matcher = logic.get_matcher()
        recipe = compute_base_mix((226, 174, 121), cfg, brands=[],
                                  matcher=matcher, total_drops=20)
        scr = self.app.screens["mix"]
        scr._on_done(recipe)
        self.assertEqual(len(scr._bar.segments), 5,
                         "混色比例条应有 5 段（红/黄/蓝/白/黑）")
        self.assertGreater(len(scr._inner.children), 0)

    def test_pick_screen_updates_on_color(self):
        scr = self.app.screens["pick"]
        self.app.color_set((226, 174, 121))
        self.assertEqual(scr.current_hex, "#E2AE79")
        self.assertIsNotNone(self.app.current_rgb)
        # 手动输入的三个滑块要跟着走，否则「吸色」和「手动」显示不一致
        self.assertEqual([int(s.value) for s in scr._sliders], [226, 174, 121])

    def test_visualize_renders_grid(self):
        from app.services.paint_matcher import PaintMatcher
        rgb = (120, 80, 60)
        matcher = PaintMatcher(logic.get_db())
        sug = matcher.suggest(rgb, logic.get_config(), brands=[])
        self.app.current_rgb = rgb
        scr = self.app.screens["visualize"]
        scr._on_done(sug)
        # _inner 内应有色卡对比卡片
        self.assertGreater(len(scr._inner.children), 0)

    # ------------------------------------------------------ 适配回归（关键）
    def test_units_are_density_scaled(self):
        """字号/尺寸必须走 sp/dp，而不是写死像素（1080p 安卓屏会缩成一条）。"""
        from kivy.metrics import dp
        from mobile.widgets import Card, Txt

        txt = Txt(text="适配测试")
        self.assertGreaterEqual(txt.font_size, dp(12) * 0.99,
                                "字号必须按 sp 缩放，否则手机上会小到看不见")
        card = Card()
        self.assertIsNone(card.size_hint_y,
                          "卡片必须自适应高度，否则 ScrollView 内容会被压扁")
        ref = card.padding[0]
        self.assertGreaterEqual(ref, dp(12) * 0.99,
                                "卡片内边距必须按 dp 缩放")

    def test_scroll_cards_have_height(self):
        """滚动容器里的卡片高度必须大于 0（曾经因 size_hint_y=1 全部塌成 0）。"""
        from mobile.widgets import Card, Txt

        card = Card()
        card.add_widget(Txt(text="一行内容"))
        self.assertGreater(card.height, 0, "卡片高度塌陷，页面会只剩顶部一条")

    def test_nav_touch_target(self):
        """底部导航要满足 48dp 触摸目标。"""
        from mobile.theme import D

        self.assertGreaterEqual(self.app.nav.height, D(48))
        self.assertEqual(len(self.app.nav.buttons), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
