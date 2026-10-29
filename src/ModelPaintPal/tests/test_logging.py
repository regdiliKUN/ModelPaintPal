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


class StdStreamFallbackTest(unittest.TestCase):
    """窗口模式（sys.stderr is None）下，非 logging 的输出也要能落盘。

    Qt 槽函数里的异常走 PyErr_Print() 直接写 stderr，不经过 sys.excepthook；
    打包成 --windowed 后 stderr 是 None，这类错误会彻底消失。本轮就踩到一次：
    槽函数里控件名拼错，热键设置静默失效，日志里什么都没有。
    """

    def test_none_streams_are_redirected_to_file(self):
        import tempfile
        from pathlib import Path

        from app.core.logging_setup import ensure_std_streams

        original_out, original_err = sys.stdout, sys.stderr
        with tempfile.TemporaryDirectory() as tmp:
            try:
                sys.stdout = None
                sys.stderr = None
                replaced = ensure_std_streams(Path(tmp))
                self.assertTrue(replaced)
                self.assertIsNotNone(sys.stderr)
                print("来自槽函数的 traceback", file=sys.stderr)
                sys.stderr.flush()
                text = (Path(tmp) / "stderr.log").read_text(encoding="utf-8")
                self.assertIn("来自槽函数的 traceback", text)
            finally:
                sys.stdout, sys.stderr = original_out, original_err

    def test_healthy_streams_are_left_alone(self):
        import tempfile
        from pathlib import Path

        from app.core.logging_setup import ensure_std_streams

        with tempfile.TemporaryDirectory() as tmp:
            before = sys.stderr
            self.assertFalse(ensure_std_streams(Path(tmp)))
            self.assertIs(sys.stderr, before)
            self.assertFalse((Path(tmp) / "stderr.log").exists())
