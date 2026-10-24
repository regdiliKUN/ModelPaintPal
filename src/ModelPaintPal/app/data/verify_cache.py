# -*- coding: utf-8 -*-
"""联网核实的本地缓存。

色号目录是**慢变数据** —— 一个品牌一年也未必更新一次目录。所以缓存给到 90 天，
而不是按「实时检索」的分钟级设计。

缓存只服务于「展示」，不参与任何计算：缓存损坏时的正确行为是**静默降级为
未缓存**（重新去查），而不是让界面崩掉或让用户以为查过了。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..core.logging_setup import get_logger
from ..core.storage import JsonStore

logger = get_logger(__name__)

__all__ = ["TTL_DAYS", "cache_key", "get", "put", "clear", "is_fresh"]

TTL_DAYS = 90
_FILE = "verify_cache.json"
_SUBDIR = "cache"

_store = JsonStore(_FILE, dict, subdir=_SUBDIR)


def cache_key(brand_key: str, code: str) -> str:
    return f"{brand_key}:{code}".lower()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_days(record: dict) -> float:
    stamp = record.get("verified_at") or ""
    if not stamp:
        return float("inf")
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return float("inf")
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 86400.0


def is_fresh(record: Optional[dict], ttl_days: int = TTL_DAYS) -> bool:
    """缓存是否仍然有效。缺字段 / 损坏 → 一律视为失效。"""
    if not isinstance(record, dict):
        return False
    if not record.get("verified_at"):
        return False
    return _age_days(record) <= max(0, int(ttl_days))


def get(brand_key: str, code: str, ttl_days: int = TTL_DAYS) -> Optional[dict]:
    """取一条未过期的缓存；没有或已过期返回 None。"""
    try:
        data: Dict[str, Any] = _store.load() or {}
    except Exception as exc:  # 缓存损坏绝不能影响主流程
        logger.warning("核实缓存读取失败，按未缓存处理: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    record = data.get(cache_key(brand_key, code))
    return record if is_fresh(record, ttl_days) else None


def put(brand_key: str, code: str, payload: dict) -> bool:
    """写入缓存（整体覆盖式写入，条目量很小，不值得做增量）。"""
    try:
        data: Dict[str, Any] = _store.load() or {}
        if not isinstance(data, dict):
            data = {}
        data[cache_key(brand_key, code)] = {
            **(payload or {}),
            "verified_at": _now_iso(),
        }
        return _store.save(data)
    except Exception as exc:
        logger.warning("核实缓存写入失败（不影响结果）: %s", exc)
        return False


def clear() -> bool:
    try:
        return _store.save({})
    except Exception as exc:
        logger.warning("核实缓存清空失败: %s", exc)
        return False
