# -*- coding: utf-8 -*-
"""收藏夹：常用色单独保存，支持命名与标签，不参与历史滚动淘汰。"""

from __future__ import annotations

from typing import List, Optional

from .logging_setup import get_logger
from .sample_record import SampleRecord, record_from_dict
from .storage import CollectionStore

logger = get_logger(__name__)

__all__ = ["FavoritesStore"]

_FAVORITES_FILE = "favorites.json"


class FavoritesStore:
    def __init__(self, limit: int = 200) -> None:
        self._store = CollectionStore(_FAVORITES_FILE, limit=limit)

    @property
    def limit(self) -> int:
        return self._store.limit

    @limit.setter
    def limit(self, value: int) -> None:
        self._store.limit = max(1, int(value))

    # ------------------------------------------------------------------ 读
    def all(self) -> List[SampleRecord]:
        records: List[SampleRecord] = []
        for item in self._store.load():
            try:
                records.append(record_from_dict(item))
            except Exception:  # 单条脏数据不应拖累整个收藏夹
                logger.warning("忽略一条无法解析的收藏记录: %r", item)
        return sorted(records, key=lambda rec: rec.name or rec.hex)

    def contains_hex(self, hex_value: str) -> bool:
        target = (hex_value or "").upper()
        return any(rec.hex == target for rec in self.all())

    def find(self, uid: str) -> Optional[SampleRecord]:
        for record in self.all():
            if record.uid == uid:
                return record
        return None

    # ------------------------------------------------------------------ 写
    def add(self, record: SampleRecord) -> List[SampleRecord]:
        self._store.append(record.to_dict(), dedup_key="hex")
        return self.all()

    def remove(self, uid: str) -> bool:
        before = len(self._store.load())
        self._store.remove(lambda item: item.get("uid") == uid)
        return len(self._store.load()) < before

    def remove_by_hex(self, hex_value: str) -> bool:
        target = (hex_value or "").upper()
        before = len(self._store.load())
        self._store.remove(lambda item: str(item.get("hex", "")).upper() == target)
        return len(self._store.load()) < before

    def rename(self, uid: str, name: str) -> bool:
        items = self._store.load()
        for item in items:
            if item.get("uid") == uid:
                item["name"] = name
                self._store.save(items)
                return True
        return False

    def clear(self) -> None:
        self._store.clear()
