# -*- coding: utf-8 -*-
"""单条色号的联网核实。

范围刻意收得很窄
----------------
这不是「联网搜索」。这个应用是即时工具，不是问答产品 —— 用户吸完一个色想要的是
配方，不会想再搜点别的。联网在这里只有一个正当用途：

    **这个色号的色值，官方那边现在还是这么写的吗？**

所以：一次只核一个色号，只发 ``{品牌, 色号}`` 文本，结果**只展示不改数据**，
用户点「采用」才走已有的 ``paint_db.calibrate()`` 回路写入。

内置核验源为什么是空的
----------------------
各品牌官网结构各异，不少还有 Cloudflare 拦截（``DATA_ITERATIONS.md`` 第 6 轮
就记过 AMMO 的 PDF 被拦）。凭空写几个抓取 URL，抓不到是常态，还会让人误以为
这个功能真的在工作。

所以这里**不内置任何抓取端点**：机制（并发 / 去重 / 排序 / 降级 / 缓存）全部
实现并可测，真正的核验源由用户在 ``userdata/verify_providers.json`` 里配置，
模板自取。没有配置时，界面如实说「未配置核验源」，而不是假装查过了。

失败怎么呈现
------------
``parse``（我们没抓明白）与 ``absent``（那边没有这条数据）必须分开 ——
两者含义相反，合并成「没查到」会误导用户以为这个色号不存在。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..core.color_models import hex_to_rgb
from ..core.delta_e import delta_e
from ..core.http_client import DEFAULT_TIMEOUT, fetch_all
from ..core.logging_setup import get_logger
from ..core.storage import JsonStore
from ..data import verify_cache
from ..data.paint_db import PaintEntry, calibrate

logger = get_logger(__name__)

__all__ = [
    "Provider",
    "VerifyHit",
    "VerifyReport",
    "load_providers",
    "save_providers",
    "verify_entry",
    "adopt",
]

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")
_PROVIDERS_FILE = "verify_providers.json"
_providers_store = JsonStore(_PROVIDERS_FILE, list)


@dataclass(frozen=True)
class Provider:
    """一个核验源。``url`` 里可用 ``{brand}`` / ``{code}`` / ``{query}`` 占位。"""

    id: str
    name: str
    url: str
    kind: str = "chart"
    note: str = ""


@dataclass
class VerifyHit:
    """一个源给出的结果。失败也保留完整上下文。"""

    provider_id: str
    name: str
    url: str
    status: str = "network"
    status_label: str = "网络不可达"
    elapsed_ms: int = 0
    hex: str = ""
    delta_e: Optional[float] = None
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id, "name": self.name, "url": self.url,
            "status": self.status, "status_label": self.status_label,
            "elapsed_ms": self.elapsed_ms, "hex": self.hex,
            "delta_e": self.delta_e, "note": self.note,
        }


@dataclass
class VerifyReport:
    """一次核实的完整结果。"""

    uid: str = ""
    code: str = ""
    brand_key: str = ""
    local_hex: str = ""
    local_source: str = ""
    local_date: str = ""
    hits: List[VerifyHit] = field(default_factory=list)
    from_cache: bool = False
    configured: bool = True
    note: str = ""

    # ------------------------------------------------------------------ 查询
    @property
    def ok_hits(self) -> List[VerifyHit]:
        return [h for h in self.hits if h.ok]

    @property
    def best(self) -> Optional[VerifyHit]:
        ok = self.ok_hits
        if not ok:
            return None
        return min(ok, key=lambda h: (h.delta_e if h.delta_e is not None else 1e9))

    @property
    def all_failed(self) -> bool:
        return bool(self.hits) and not self.ok_hits

    def verdict(self) -> str:
        """给用户的一句话结论。失败要说清楚「本地值没动」。"""
        if not self.configured:
            return ("尚未配置联网核验源，无法核实。"
                    "本地值保持不变。")
        if not self.hits:
            return "没有可查询的核验源，本地值保持不变。"
        best = self.best
        if best is not None:
            gap = "" if best.delta_e is None else f"ΔE {best.delta_e:.2f}"
            return (f"{len(self.ok_hits)} 个源响应，与本地值最接近的是"
                    f"「{best.name}」{best.hex or ''}（{gap}）。"
                    f"本地值 {self.local_hex} 未被自动修改。")
        failed = len(self.hits)
        return (f"未能核实（{failed} 个源均未取得结果）。"
                f"当前值仍是「{self.local_source or '未登记来源'}」"
                f"{('于 ' + self.local_date) if self.local_date else ''}的数据 —— "
                f"本地值一字未改。")

    def to_dict(self) -> dict:
        return {
            "uid": self.uid, "code": self.code, "brand_key": self.brand_key,
            "local_hex": self.local_hex, "local_source": self.local_source,
            "local_date": self.local_date, "from_cache": self.from_cache,
            "configured": self.configured, "note": self.note,
            "verdict": self.verdict(),
            "hits": [h.to_dict() for h in self.hits],
        }


# ---------------------------------------------------------------------------
# 核验源配置
# ---------------------------------------------------------------------------
def load_providers() -> List[Provider]:
    """读取用户配置的核验源；没配过返回空列表（不内置任何端点）。"""
    try:
        raw = _providers_store.load() or []
    except Exception as exc:
        logger.warning("核验源配置读取失败: %s", exc)
        return []
    out: List[Provider] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        if not pid or not url:
            continue
        out.append(Provider(
            id=pid,
            name=str(item.get("name") or pid),
            url=url,
            kind=str(item.get("kind") or "chart"),
            note=str(item.get("note") or ""),
        ))
    return out


def save_providers(providers: Sequence[Provider]) -> bool:
    return _providers_store.save([
        {"id": p.id, "name": p.name, "url": p.url, "kind": p.kind, "note": p.note}
        for p in providers
    ])


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _extract_hex(body: str, code: str) -> tuple:
    """从抓到的正文里取色值。

    返回 ``(hex, status)``：
* ``ok``     —— 找到色号且附近有色值；
* ``absent`` —— 页面里根本没有这个色号（**那边**没有这条数据）；
* ``parse``  —— 有色号但取不出色值（**我们**没抓明白，页面结构变了）。
    """
    if not body:
        return "", "parse"
    index = body.find(code)
    if index < 0:
        return "", "absent"
    window = body[max(0, index - 300): index + 300]
    match = _HEX_RE.search(window)
    if match:
        return match.group(0).upper(), "ok"
    return "", "parse"


def _hit_from_result(provider: Provider, result, local_rgb) -> VerifyHit:
    hit = VerifyHit(
        provider_id=provider.id, name=provider.name, url=result.url,
        status=result.status, status_label=result.status_label,
        elapsed_ms=result.elapsed_ms, note=result.note,
    )
    if not result.ok:
        return hit
    value, status = _extract_hex(result.body, result.key.split(":", 1)[-1])
    hit.status = status
    hit.status_label = {"ok": "成功", "absent": "查无此色", "parse": "解析失败"}[status]
    if status == "ok":
        hit.hex = value
        try:
            hit.delta_e = round(delta_e(local_rgb, hex_to_rgb(value), "CIEDE2000"), 2)
        except ValueError:
            hit.status = "parse"
            hit.status_label = "解析失败"
    return hit


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def verify_entry(entry: PaintEntry,
                 enabled: bool = True,
                 providers: Optional[Sequence[Provider]] = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 use_cache: bool = True,
                 fetcher=None) -> VerifyReport:
    """核实一条色号。**绝不修改本地数据** —— 采用与否由用户在界面上决定。"""
    brand_key = entry.brand_key
    code = entry.code
    local_hex = entry.hex
    report = VerifyReport(
        uid=entry.uid, code=code, brand_key=brand_key, local_hex=local_hex,
        local_source=(entry.source.name if entry.source else ""),
        local_date=entry.src_date,
    )

    if not enabled:
        report.configured = False
        report.note = "联网核验已关闭"
        return report

    chosen = list(providers) if providers is not None else load_providers()
    if not chosen:
        report.configured = False
        report.note = "未配置核验源"
        return report

    if use_cache:
        cached = verify_cache.get(brand_key, code)
        if cached and isinstance(cached.get("hits"), list):
            report.from_cache = True
            report.hits = [VerifyHit(**h) for h in cached["hits"]
                           if isinstance(h, dict)]
            report.note = "来自本地缓存"
            return report

    local_rgb = hex_to_rgb(local_hex)
    brand = entry.brand.short if entry.brand else brand_key
    jobs = []
    for provider in chosen:
        url = provider.url.format(brand=brand, code=code, query=f"{brand} {code}")
        jobs.append((f"{provider.id}:{code}", url, {}))

    results: Dict[str, object] = (
        fetcher(jobs) if fetcher is not None
        else fetch_all(jobs, timeout=timeout)
    )

    hits: List[VerifyHit] = []
    for provider in chosen:
        result = results.get(f"{provider.id}:{code}")
        if result is None:
            continue
        hits.append(_hit_from_result(provider, result, local_rgb))

    # 排序：成功的按 ΔE 升序在前，失败的整体靠后（失败之间保持原顺序）
    hits.sort(key=lambda h: (0 if h.ok else 1,
                             h.delta_e if h.delta_e is not None else 1e9))
    report.hits = hits

    if report.ok_hits:
        verify_cache.put(brand_key, code, {"hits": [h.to_dict() for h in hits]})
    return report


def adopt(entry: PaintEntry, hex_value: str) -> bool:
    """把核实到的色值写回本地 —— 复用既有的校准回路，不新开一条写入路径。"""
    return calibrate(entry.uid, hex_value)
