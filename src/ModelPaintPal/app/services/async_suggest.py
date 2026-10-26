# -*- coding: utf-8 -*-
"""配色建议的异步计算。

把最重的 ``PaintMatcher.suggest`` 放到 ``QThreadPool`` 的工作线程里跑，主线程只负责
渲染，保证连续吸色时界面不卡顿。每个任务带一个递增的 ``token``，渲染时只采纳
「最新一次」的结果，旧任务即便先算完也会被丢弃（去抖）。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..core.config import AppConfig
from ..core.logging_setup import get_logger
from ..services.coverage import CoverageInput
from ..services.paint_matcher import PaintMatcher, PaintSuggestion
from ..services.scheme_engine import build_scheme

logger = get_logger(__name__)


class SuggestSignaller(QObject):
    """跨线程投递结果的信号载体（QRunnable 自身无法持有信号）。"""

    finished = Signal(list, int)      # (suggestions, token)
    failed = Signal(str, int)         # (错误描述, token)


class SuggestTask(QRunnable):
    """一次配色建议计算任务。"""

    def __init__(self,
                 matcher: PaintMatcher,
                 target_rgb: Sequence[int],
                 config: AppConfig,
                 brands: Optional[List[str]],
                 coverage_input: Optional[CoverageInput],
                 token: int) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._matcher = matcher
        self._target = tuple(int(c) for c in target_rgb)
        self._config = config
        self._brands = brands
        self._coverage = coverage_input
        self._token = token
        self.signaller = SuggestSignaller()

    def run(self) -> None:
        try:
            result: List[PaintSuggestion] = self._matcher.suggest(
                target_rgb=self._target,
                config=self._config,
                brands=self._brands,
                coverage_input=self._coverage,
            )
        except Exception as exc:  # 任何异常都不应把工作线程带崩
            # 计算失败必须和"没有匹配结果"区分开：前者要让用户知道可以重试/换范围，
            # 后者只是数据事实。此前两者都返回空列表，界面统一显示"没有找到可用建议"。
            logger.exception("配色计算失败: %s", exc)
            self.signaller.failed.emit(f"{exc}" or exc.__class__.__name__, self._token)
            return
        self.signaller.finished.emit(result, self._token)


def submit_suggest(matcher: PaintMatcher,
                   target_rgb: Sequence[int],
                   config: AppConfig,
                   brands: Optional[List[str]],
                   coverage_input: Optional[CoverageInput],
                   token: int,
                   on_done,
                   on_error=None) -> SuggestTask:
    """提交一次异步建议计算。

    成功走 ``on_done(suggestions, token)``；失败（若有 ``on_error``）走
    ``on_error(message, token)``，让界面能区分"算错了"与"没匹配到"。
    """
    task = SuggestTask(matcher, target_rgb, config, brands, coverage_input, token)
    task.signaller.finished.connect(on_done)
    if on_error is not None:
        task.signaller.failed.connect(on_error)
    QThreadPool.globalInstance().start(task)
    return task


class SchemeSignaller(QObject):
    """跨线程投递方案计算结果的信号载体。"""

    finished = Signal(object, int)     # (List[SchemeStop], token)
    failed = Signal(str, int)          # (错误描述, token)


class SchemeTask(QRunnable):
    """一次基础配色方案计算任务。"""

    def __init__(self,
                 matcher: PaintMatcher,
                 base_rgb: Sequence[int],
                 config: AppConfig,
                 brands: Optional[List[str]],
                 coverage_input: Optional[CoverageInput],
                 scheme_type: str,
                 param: int,
                 token: int) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._matcher = matcher
        self._base = tuple(int(c) for c in base_rgb)
        self._config = config
        self._brands = brands
        self._coverage = coverage_input
        self._scheme_type = scheme_type
        self._param = param
        self._token = token
        self.signaller = SchemeSignaller()

    def run(self) -> None:
        try:
            result = build_scheme(
                matcher=self._matcher,
                base_rgb=self._base,
                config=self._config,
                brands=self._brands,
                coverage_input=self._coverage,
                scheme_type=self._scheme_type,
                param=self._param,
            )
        except Exception as exc:  # 任何异常都不应把工作线程带崩
            logger.exception("配色方案计算失败: %s", exc)
            self.signaller.failed.emit(f"{exc}" or exc.__class__.__name__, self._token)
            return
        self.signaller.finished.emit(result, self._token)


def submit_scheme(matcher: PaintMatcher,
                  base_rgb: Sequence[int],
                  config: AppConfig,
                  brands: Optional[List[str]],
                  coverage_input: Optional[CoverageInput],
                  scheme_type: str,
                  param: int,
                  token: int,
                  on_done,
                  on_error=None) -> SchemeTask:
    """提交一次异步基础配色方案计算（接口与 ``submit_suggest`` 对齐）。"""
    task = SchemeTask(matcher, base_rgb, config, brands, coverage_input,
                      scheme_type, param, token)
    task.signaller.finished.connect(on_done)
    if on_error is not None:
        task.signaller.failed.connect(on_error)
    QThreadPool.globalInstance().start(task)
    return task
