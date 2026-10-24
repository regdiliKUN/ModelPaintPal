# -*- coding: utf-8 -*-
"""联网核实的异步执行（与 async_suggest 同一套路）。

网络请求必须离开主线程 —— 哪怕全部超时也要 3 秒，卡在主线程上就是界面假死。
"""

from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..core.logging_setup import get_logger
from ..data.paint_db import PaintEntry
from .verify_service import Provider, verify_entry

logger = get_logger(__name__)

__all__ = ["submit_verify"]


class VerifySignaller(QObject):
    finished = Signal(object)     # VerifyReport
    failed = Signal(str)


class VerifyTask(QRunnable):
    """一次核实任务。"""

    def __init__(self,
                 entry: PaintEntry,
                 enabled: bool = True,
                 providers: Optional[Sequence[Provider]] = None,
                 timeout: float = 3.0) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._entry = entry
        self._enabled = enabled
        self._providers = providers
        self._timeout = timeout
        self.signaller = VerifySignaller()

    def run(self) -> None:
        try:
            report = verify_entry(
                self._entry,
                enabled=self._enabled,
                providers=self._providers,
                timeout=self._timeout,
            )
        except Exception as exc:  # 网络代码最容易抛意料之外的异常
            logger.exception("核实失败: %s", exc)
            self.signaller.failed.emit(f"{exc}" or exc.__class__.__name__)
            return
        self.signaller.finished.emit(report)


def submit_verify(entry: PaintEntry,
                  enabled: bool = True,
                  providers: Optional[Sequence[Provider]] = None,
                  timeout: float = 3.0,
                  on_done=None,
                  on_error=None) -> VerifyTask:
    task = VerifyTask(entry, enabled, providers, timeout)
    if on_done is not None:
        task.signaller.finished.connect(on_done)
    if on_error is not None:
        task.signaller.failed.connect(on_error)
    QThreadPool.globalInstance().start(task)
    return task
