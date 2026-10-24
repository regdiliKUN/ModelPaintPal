# -*- coding: utf-8 -*-
"""日志初始化测试（get_logger / setup_logging 幂等性）。"""

import logging
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.logging_setup import get_logger, setup_logging  # noqa: E402


class TestLogging(unittest.TestCase):
    def test_get_logger_returns_named_logger(self):
        logger = get_logger("mpp.test")
        self.assertIsInstance(logger, logging.Logger)
        self.assertEqual(logger.name, "mpp.test")

    def test_get_logger_idempotent(self):
        self.assertIs(get_logger("mpp.same"), get_logger("mpp.same"))

    def test_setup_logging_idempotent(self):
        # 重复调用只调整级别，不应重复叠加 handler（否则日志会重复输出）；
        # 用 debug_to_file=False 避免在测试期间往真实用户目录写日志文件。
        setup_logging(logging.INFO, debug_to_file=False)
        count_after_first = len(logging.getLogger().handlers)
        setup_logging(logging.INFO, debug_to_file=False)
        self.assertEqual(len(logging.getLogger().handlers), count_after_first)

    def test_logger_can_emit(self):
        get_logger("mpp.emit").debug("hello")  # 不应抛错


if __name__ == "__main__":
    unittest.main(verbosity=2)
