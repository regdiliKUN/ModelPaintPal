# -*- coding: utf-8 -*-
"""配色建议入口的参数边界（``max_results`` 语义 / 目标色归一化）。"""

import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.config import AppConfig  # noqa: E402
from app.services.paint_matcher import PaintMatcher  # noqa: E402


class SuggestLimitTest(unittest.TestCase):
    """``max_results`` 的三种语义必须区分开。"""

    @classmethod
    def setUpClass(cls):
        cls.matcher = PaintMatcher()
        cls.config = AppConfig().validate()

    def test_none_uses_config_default(self):
        """None = 没指定，用配置里的条数。"""
        result = self.matcher.suggest((120, 96, 72), self.config, max_results=None)
        self.assertEqual(len(result), self.config.max_suggestions)

    def test_zero_returns_empty(self):
        """0 = 明确要求空结果，不能回退成默认条数。"""
        self.assertEqual(self.matcher.suggest((120, 96, 72), self.config, max_results=0), [])

    def test_negative_returns_empty(self):
        """负数同样按「一条都不要」处理，而不是抛异常或回退默认值。"""
        self.assertEqual(self.matcher.suggest((120, 96, 72), self.config, max_results=-3), [])

    def test_explicit_count_is_honoured(self):
        result = self.matcher.suggest((120, 96, 72), self.config, max_results=2)
        self.assertEqual(len(result), 2)
        self.assertEqual([item.rank for item in result], [1, 2])

    def test_target_is_normalised(self):
        """越界/浮点目标色应被夹紧到 0-255 整数，而不是把下游转换搞崩。"""
        clamped = self.matcher.suggest((300, -20, 127.6), self.config)
        exact = self.matcher.suggest((255, 0, 128), self.config)
        self.assertEqual([item.anchor.uid for item in clamped],
                         [item.anchor.uid for item in exact])


if __name__ == "__main__":
    unittest.main()
