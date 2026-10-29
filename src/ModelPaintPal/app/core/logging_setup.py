# -*- coding: utf-8 -*-
"""日志初始化：控制台 + 用户目录滚动文件，绝不因日志失败而拖垮主程序。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from .paths import ensure_dir, user_path

__all__ = ["setup_logging", "get_logger", "ensure_std_streams"]

_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 2
# stderr 落盘文件的上限：超过就轮转一次，避免长期运行攒出巨大的日志
_STDERR_MAX_BYTES = 2_000_000

_configured = False


def ensure_std_streams(log_dir: Optional[Path] = None) -> bool:
    """把为 ``None`` 的 stdout/stderr 接到日志文件，返回是否做了替换。

    PyInstaller 的 ``--windowed`` 产物没有控制台，``sys.stdout`` / ``sys.stderr``
    都是 ``None``。而下面这些输出**不走 logging**、直接写 stderr：

    * Qt 槽函数里抛出的异常（PySide6 用 ``PyErr_Print()``，不经过 ``sys.excepthook``）；
    * 第三方库的警告与 traceback；
    * ``logging`` 自身的 "--- Logging error ---"。

    结果就是「某个按钮点了没反应，日志里一个字都没有」——本轮就踩到一次：信号槽里
    一个控件名拼错，异常被 Qt 吞掉，界面表现为热键设置静默失效。把 stderr 接到文件
    之后，这类问题至少能在 ``logs/stderr.log`` 里查到。
    """
    if sys.stderr is not None and sys.stdout is not None:
        return False
    try:
        directory = ensure_dir(log_dir or user_path("logs"))
        path = Path(directory) / "stderr.log"
        # 启动时做一次简单的容量控制：超限就只保留一个备份，不做轮转链
        try:
            if path.exists() and path.stat().st_size > _STDERR_MAX_BYTES:
                path.replace(path.with_suffix(".log.1"))
        except OSError:
            pass
        stream = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        # 连日志目录都写不了时，宁可维持 None 也不要让启动失败
        return False
    if sys.stderr is None:
        sys.stderr = stream
    if sys.stdout is None:
        sys.stdout = stream
    return True


def setup_logging(level: int = logging.INFO, debug_to_file: bool = True) -> logging.Logger:
    """幂等地安装根日志器；重复调用只会调整级别。"""
    global _configured
    root = logging.getLogger()
    root.setLevel(level)
    if _configured:
        for handler in root.handlers:
            handler.setLevel(level)
        return root

    # 先补好 stdout/stderr：控制台 handler 与 Qt 的 PyErr_Print 都依赖它
    ensure_std_streams()

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
