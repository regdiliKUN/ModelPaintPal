# -*- coding: utf-8 -*-
"""日志初始化：控制台 + 用户目录滚动文件，绝不因日志失败而拖垮主程序。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from .paths import ensure_dir, user_path

__all__ = ["setup_logging", "get_logger"]

_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 2

_configured = False


def setup_logging(level: int = logging.INFO, debug_to_file: bool = True) -> logging.Logger:
    """幂等地安装根日志器；重复调用只会调整级别。"""
    global _configured
    root = logging.getLogger()
    root.setLevel(level)
    if _configured:
        for handler in root.handlers:
            handler.setLevel(level)
        return root

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    console = logging.StreamHandler(stream=sys.stderr)
    console.setFormatter(formatter)
    console.setLevel(level)
    root.addHandler(console)

    if debug_to_file:
        try:
            log_dir = ensure_dir(user_path("logs"))
            file_handler = RotatingFileHandler(
                log_dir / "app.log", maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)
            root.addHandler(file_handler)
        except OSError as exc:  # 只读目录 / 权限不足时静默降级
            root.warning("无法创建日志文件，仅输出到控制台: %s", exc)

    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
