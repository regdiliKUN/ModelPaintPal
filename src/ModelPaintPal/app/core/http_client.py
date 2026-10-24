# -*- coding: utf-8 -*-
"""薄 HTTP 客户端（只用标准库）。

放在 ``core`` 是因为项目依赖方向铁律是 ``ui → services → data → core``，
网络是最底层的能力，不能被上层反向依赖。

为什么不用 httpx / requests
---------------------------
运行时依赖是 PySide6 / Pillow / numpy / mss —— 全都是本地计算库。为了一个
默认关闭的核验功能往打包里塞一个网络库，会让便携版平白胖一圈。这里只用
``urllib``，够用。

只有一件事是硬要求：**失败必须失败得干净**。超时、限流、断网、抓到的页面
结构变了，每一种都要能被区分开上报，绝不能糊成一句「没查到」。
「解析失败」和「查无此色」含义相反 —— 前者是**我们**没抓明白，后者是**那边**
没有这条数据，混在一起会误导用户。
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

__all__ = [
    "FetchResult",
    "STATUS_LABELS",
    "fetch",
    "fetch_all",
    "ensure_text_query",
]

DEFAULT_TIMEOUT = 3.0
DEFAULT_RETRIES = 1
USER_AGENT = "ModelPaintPal/1.0 (local paint-matching tool)"

# 状态与界面上的显示文案。状态码本身不解释原因，文案才解释。
STATUS_LABELS = {
    "ok": "成功",
    "timeout": "超时",
    "limit": "限流",
    "parse": "解析失败",
    "absent": "查无此色",
    "network": "网络不可达",
    "disabled": "未启用",
    "blocked": "请求被拒绝",
}


@dataclass
class FetchResult:
    """一次抓取的结果。失败也带完整上下文，便于界面如实呈现。"""

    key: str = ""
    ok: bool = False
    status: str = "network"
    url: str = ""
    body: str = ""
    status_code: int = 0
    elapsed_ms: int = 0
    note: str = ""

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


def ensure_text_query(payload: dict) -> None:
    """隐私红线守卫：只允许文本字段出网。

    这个应用会抓全屏取色，一旦联网，用户最担心的就是屏幕内容被传出去。
    所以任何请求参数在发出前都要过这一关 —— 出现二进制/字节串直接抛错。
    """
    for name, value in (payload or {}).items():
        if isinstance(value, (bytes, bytearray)):
            raise ValueError(f"请求参数 {name} 是二进制数据，禁止出网")
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, (bytes, bytearray)):
                    raise ValueError(f"请求参数 {name} 含二进制数据，禁止出网")


def fetch(url: str,
          params: Optional[dict] = None,
          timeout: float = DEFAULT_TIMEOUT,
          retries: int = DEFAULT_RETRIES,
          key: str = "") -> FetchResult:
    """抓一个 URL。异常一律转成 FetchResult，不往上抛。"""
    ensure_text_query(params or {})
    started = time.monotonic()
    target = url
    if params:
        from urllib.parse import urlencode

        target = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"

    last = FetchResult(key=key or url, url=target)
    for attempt in range(max(1, retries) + 1):
        request = urllib.request.Request(
            target, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                body = raw.decode("utf-8", errors="replace")
                last = FetchResult(
                    key=key or url, ok=True, status="ok", url=target,
                    body=body, status_code=int(getattr(response, "status", 200) or 200),
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
                return last
        except urllib.error.HTTPError as exc:
            last = FetchResult(
                key=key or url, ok=False,
                status="limit" if exc.code == 429 else "blocked",
                url=target, status_code=int(exc.code),
                elapsed_ms=int((time.monotonic() - started) * 1000),
                note=f"HTTP {exc.code}",
            )
            if exc.code == 429:
                return last          # 限流重试没意义，只会更糟
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            last = FetchResult(
                key=key or url, ok=False, status="network", url=target,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                note=str(reason),
            )
        except TimeoutError:
            last = FetchResult(
                key=key or url, ok=False, status="timeout", url=target,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                note=f"超过 {timeout:g}s",
            )
    return last


def fetch_all(jobs: Sequence[Tuple[str, str, dict]],
              timeout: float = DEFAULT_TIMEOUT,
              max_workers: int = 4) -> Dict[str, FetchResult]:
    """并发抓多个源。

    ``jobs`` 为 ``(key, url, params)`` 三元组；返回按 key 索引的结果表。
    任何一个源挂掉都不影响其它源 —— 这正是「多源并行」的意义。
    """
    results: Dict[str, FetchResult] = {}
    if not jobs:
        return results
    workers = max(1, min(int(max_workers), len(jobs)))

    def run(job: Tuple[str, str, dict]) -> FetchResult:
        key, url, params = job
        return fetch(url, params, timeout=timeout, key=key)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(run, jobs):
            results[result.key] = result
    return results
