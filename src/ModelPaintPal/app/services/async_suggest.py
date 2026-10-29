# -*- coding: utf-8 -*-
"""配色建议 / 配色方案 / 基础漆调配的异步计算。

把最重的 ``PaintMatcher.suggest`` 放到 ``QThreadPool`` 的工作线程里跑，主线程只负责
渲染，保证连续吸色时界面不卡顿。每个任务带一个递增的 ``token``，渲染时只采纳
「最新一次」的结果，旧任务即便先算完也会被丢弃（去抖）。

更进一步：排队中的旧任务会在**开工前**就放弃（见 ``_LatestSequence``），而不只是
把结果丢掉。连续吸色 / 拖调色滑块时线程池里会堆十几个陈旧任务，光丢弃结果的话
最新一次仍要排在它们后面算，界面看起来就像卡住了。

三类任务（建议 / 方案 / 调配）只有「算什么」不同，过期判定、异常兜底、信号投递
完全一致，统一由 ``_TaskBase`` 承担——此前这三段是逐行复制的，改一处漏两处是迟早
的事。
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..core.config import AppConfig
from ..core.logging_setup import get_logger
from ..services.coverage import CoverageInput
from ..services.paint_matcher import PaintMatcher, PaintSuggestion
from ..services.scheme_engine import build_scheme, compute_base_mix

logger = get_logger(__name__)

# 任务种类（只用于区分各自的「最新请求」序列，互不干扰）
_KIND_SUGGEST = "suggest"
_KIND_PLAN = "plan"
_KIND_MIX = "mix"


class _LatestSequence:
    """给每类计算发递增序号，用来判断排队中的任务是否已被新请求取代。

    只用序号相等性判断（``seq != latest``），不比较 token 大小：token 由各窗口
    自己从 0 开始计数，换一个窗口就会回退，按大小比较会把新窗口的第一次计算
    误判成过期。序号由本注册表单调发放，与调用方的 token 解耦。
    """

    def __init__(self) -> None:
        self._seq: dict = {}

    def next(self, kind: str) -> int:
        value = self._seq.get(kind, 0) + 1
        self._seq[kind] = value
        return value

    def is_stale(self, kind: str, value: int) -> bool:
        return self._seq.get(kind) != value


_LATEST = _LatestSequence()


def _stale_checker(kind: str):
    """登记一次新请求，返回「我是否已被后来的请求取代」的判定函数。"""
    seq = _LATEST.next(kind)
    return lambda: _LATEST.is_stale(kind, seq)


class _Signaller(QObject):
    """跨线程投递结果的信号载体（QRunnable 自身无法持有信号）。"""

    finished = Signal(object, int)     # (结果, token)
    failed = Signal(str, int)          # (错误描述, token)


class _TaskBase(QRunnable):
    """三类异步任务的共同骨架。

    子类只需实现 :meth:`_make_signaller` 与 :meth:`_compute`；过期判定、异常兜底、
    「算错了」与「没匹配到」的区分都在这里统一处理，不会因为复制粘贴而漂移。
    """

    #: 日志与提示里的中文名，例如「配色计算」
    label = "计算"

    def __init__(self, token: int, stale_check=None) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._token = token
        # 由 submit_* 注入；直接构造任务（测试/同步调用）时为 None，永不判过期
        self._stale_check = stale_check
        self.signaller = self._make_signaller()

    def _make_signaller(self) -> _Signaller:
        raise NotImplementedError

    def _compute(self):
        raise NotImplementedError

    def run(self) -> None:
        # 排队期间已经有更新的请求 → 这次算完也只会被界面丢弃，直接跳过。
        if self._stale_check is not None and self._stale_check():
            logger.debug("跳过已被新请求取代的%s (token=%s)", self.label, self._token)
            return
        try:
            result = self._compute()
        except Exception as exc:  # 任何异常都不应把工作线程带崩
            # 计算失败必须和"没有匹配结果"区分开：前者要让用户知道可以重试/换范围，
            # 后者只是数据事实。此前两者都返回空列表，界面统一显示"没有找到可用建议"。
            logger.exception("%s失败: %s", self.label, exc)
            self.signaller.failed.emit(f"{exc}" or exc.__class__.__name__, self._token)
            return
        self.signaller.finished.emit(result, self._token)


class SuggestTask(_TaskBase):
    """一次配色建议计算任务。"""

    label = "配色计算"

    def __init__(self,
                 matcher: PaintMatcher,
                 target_rgb: Sequence[int],
                 config: AppConfig,
                 brands: Optional[List[str]],
                 coverage_input: Optional[CoverageInput],
                 token: int,
                 stale_check=None) -> None:
        self._matcher = matcher
        self._target = tuple(int(c) for c in target_rgb)
        self._config = config
        self._brands = brands
        self._coverage = coverage_input
        super().__init__(token, stale_check)

    def _make_signaller(self) -> _Signaller:
        return _Signaller()

    def _compute(self) -> List[PaintSuggestion]:
        return self._matcher.suggest(
            target_rgb=self._target,
            config=self._config,
            brands=self._brands,
            coverage_input=self._coverage,
        )


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
    task = SuggestTask(matcher, target_rgb, config, brands, coverage_input, token,
                       stale_check=_stale_checker(_KIND_SUGGEST))
    task.signaller.finished.connect(on_done)
    if on_error is not None:
        task.signaller.failed.connect(on_error)
    QThreadPool.globalInstance().start(task)
    return task


class PlanTask(_TaskBase):
    """一次基础配色方案计算任务。"""

    label = "配色方案计算"

    def __init__(self,
                 matcher: PaintMatcher,
                 base_rgb: Sequence[int],
                 config: AppConfig,
                 brands: Optional[List[str]],
                 coverage_input: Optional[CoverageInput],
                 scheme_type: str,
                 param: int,
                 token: int,
                 stale_check=None) -> None:
        self._matcher = matcher
        self._base = tuple(int(c) for c in base_rgb)
        self._config = config
        self._brands = brands
        self._coverage = coverage_input
        self._scheme_type = scheme_type
        self._param = param
        super().__init__(token, stale_check)

    def _make_signaller(self) -> _Signaller:
        return _Signaller()

    def _compute(self):
        return build_scheme(
            matcher=self._matcher,
            base_rgb=self._base,
            config=self._config,
            brands=self._brands,
            coverage_input=self._coverage,
            scheme_type=self._scheme_type,
            param=self._param,
        )


def submit_plan(matcher: PaintMatcher,
                  base_rgb: Sequence[int],
                  config: AppConfig,
                  brands: Optional[List[str]],
                  coverage_input: Optional[CoverageInput],
                  scheme_type: str,
                  param: int,
                  token: int,
                  on_done,
                  on_error=None) -> PlanTask:
    """提交一次异步配色方案计算（色环方案 → 真实漆，接口与 ``submit_suggest`` 对齐）。"""
    task = PlanTask(matcher, base_rgb, config, brands, coverage_input,
                    scheme_type, param, token,
                    stale_check=_stale_checker(_KIND_PLAN))
    task.signaller.finished.connect(on_done)
    if on_error is not None:
        task.signaller.failed.connect(on_error)
    QThreadPool.globalInstance().start(task)
    return task


class MixTask(_TaskBase):
    """一次基础漆调配计算任务（把目标色分解为红/黄/蓝/白/黑配比）。"""

    label = "基础漆调配计算"

    def __init__(self,
                 matcher: PaintMatcher,
                 target_rgb: Sequence[int],
                 config: AppConfig,
                 brands: Optional[List[str]],
                 coverage_input: Optional[CoverageInput],
                 total_drops: int,
                 token: int,
                 stale_check=None) -> None:
        self._matcher = matcher
        self._target = tuple(int(c) for c in target_rgb)
        self._config = config
        self._brands = brands
        self._coverage = coverage_input
        self._total = int(total_drops)
        super().__init__(token, stale_check)

    def _make_signaller(self) -> _Signaller:
        return _Signaller()

    def _compute(self):
        return compute_base_mix(
            target_rgb=self._target,
            config=self._config,
            brands=self._brands,
            coverage_input=self._coverage,
            matcher=self._matcher,
            total_drops=self._total,
        )


def submit_mix(matcher: PaintMatcher,
               target_rgb: Sequence[int],
               config: AppConfig,
               brands: Optional[List[str]],
               coverage_input: Optional[CoverageInput],
               total_drops: int,
               token: int,
               on_done,
               on_error=None) -> MixTask:
    """提交一次异步基础漆调配计算（接口与 ``submit_suggest`` 对齐）。"""
    task = MixTask(matcher, target_rgb, config, brands, coverage_input,
                   total_drops, token,
                   stale_check=_stale_checker(_KIND_MIX))
    task.signaller.finished.connect(on_done)
    if on_error is not None:
        task.signaller.failed.connect(on_error)
    QThreadPool.globalInstance().start(task)
    return task
