# -*- coding: utf-8 -*-
"""异步求算的单元测试（不依赖真实显示，验证离线程计算与同步结果一致）。"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.config import AppConfig  # noqa: E402
from app.services.async_suggest import SuggestTask  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402


class AsyncSuggestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 注意：这里**不能**创建 QCoreApplication。
        # 一旦进程里先出现 QCoreApplication，后续 UI 测试的 QApplication([]) 会拿不到
        # 可用的 QApplication（instance() 返回的是那个 QCoreApplication），
        # 创建 QWidget 时 Qt 直接 abort —— 表现为整套测试跑到 UI 用例就无声退出。
        # 本测试所有信号都是同线程直连（task.run() 同步执行），不需要事件循环。
        cls.matcher = PaintMatcher()
        cls.config = AppConfig()

    def test_async_equals_sync(self):
        """离线程计算出的建议必须与主线程同步计算完全一致。"""
        target = (200, 178, 105)
        sync_result = self.matcher.suggest(target, self.config)

        collected = []
        task = SuggestTask(self.matcher, target, self.config, None, None, token=1)
        task.signaller.finished.connect(lambda sug, tok: collected.append((sug, tok)))
        task.run()  # 同步执行 run()（信号直连，立即回调）

        self.assertEqual(len(collected), 1)
        async_result, token = collected[0]
        self.assertEqual(token, 1)
        self.assertEqual(len(async_result), len(sync_result))
        for a, b in zip(async_result, sync_result):
            self.assertEqual(a.anchor.uid, b.anchor.uid)
            self.assertAlmostEqual(a.delta_e, b.delta_e, places=6)
            self.assertEqual(
                [c.paint.uid for c in a.recipe.components],
                [c.paint.uid for c in b.recipe.components],
            )

    def test_task_reports_failure_instead_of_empty_list(self):
        """工作线程内的异常必须被吞掉并**走 failed 通道**，不能把线程带崩。

        "算错了"和"没匹配到"是两件事：前者要提示用户重试/换范围，
        后者只是数据事实。把异常吞成空列表会让界面显示"没有找到可用建议"，
        用户会以为自己的颜色无解。
        """
        class BoomMatcher:
            def suggest(self, **kwargs):
                raise RuntimeError("boom")

        done, failed = [], []
        task = SuggestTask(BoomMatcher(), (10, 20, 30), self.config, None, None, token=9)
        task.signaller.finished.connect(lambda sug, tok: done.append((sug, tok)))
        task.signaller.failed.connect(lambda msg, tok: failed.append((msg, tok)))
        task.run()
        self.assertEqual(done, [])
        self.assertEqual(failed[0][1], 9)
        self.assertIn("boom", failed[0][0])

    def test_async_equals_sync_with_brand_scope(self):
        cfg = AppConfig()
        cfg.mixing_model = "linear_rgb"
        cfg.delta_e_formula = "CIE76"
        target = (90, 60, 130)
        sync_result = self.matcher.suggest(target, cfg, brands=["tamiya"])
        collected = []
        task = SuggestTask(self.matcher, target, cfg, ["tamiya"], None, token=4)
        task.signaller.finished.connect(lambda sug, tok: collected.append((sug, tok)))
        task.run()
        async_result = collected[0][0]
        self.assertEqual(len(async_result), len(sync_result))
        for a, b in zip(async_result, sync_result):
            self.assertEqual(a.anchor.uid, b.anchor.uid)
            self.assertAlmostEqual(a.delta_e, b.delta_e, places=6)

    def test_empty_target_returns_empty(self):
        collected = []
        task = SuggestTask(self.matcher, (0, 0, 0), self.config, None, None, token=7)
        # 纯黑一定落在某色号容差内，结果非空；这里仅验证 token 回传正确
        task.signaller.finished.connect(lambda sug, tok: collected.append((sug, tok)))
        task.run()
        self.assertEqual(collected[0][1], 7)
        self.assertTrue(len(collected[0][0]) > 0)


if __name__ == "__main__":
    unittest.main()
