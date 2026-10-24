# -*- coding: utf-8 -*-
"""取色历史记录（滚动保存、可去重、可按 uid 删除）。"""

from __future__ import annotations

from typing import Callable, List, Optional

from .logging_setup import get_logger
from .sample_record import SampleRecord, record_from_dict
from .storage import CollectionStore

logger = get_logger(__name__)

__all__ = ["HistoryStore"]

_HISTORY_FILE = "history.json"


class HistoryStore:
    """历史记录的领域封装，内部仍复用通用的 ``CollectionStore``。"""

    def __init__(self, limit: int = 200) -> None:
        self._store = CollectionStore(_HISTORY_FILE, limit=limit)

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
            except Exception:  # 单条脏数据不应拖累整段历史加载
                logger.warning("忽略一条无法解析的历史记录: %r", item)
        return records

    def recent(self, count: int = 24) -> List[SampleRecord]:
        return self.all()[: max(0, int(count))]

    def find(self, uid: str) -> Optional[SampleRecord]:
        for record in self.all():
            if record.uid == uid:
                return record
        return None

    # ------------------------------------------------------------------ 写
    def add(self, record: SampleRecord) -> List[SampleRecord]:
        """写入一条；同色（hex 相同）自动去重并置顶。"""
        self._store.append(record.to_dict(), dedup_key="hex")
        return self.all()

    def rename(self, uid: str, name: str) -> bool:
        return self._mutate(uid, lambda rec: setattr(rec, "name", name))

    def set_note(self, uid: str, note: str) -> bool:
        return self._mutate(uid, lambda rec: setattr(rec, "note", note))

    def remove(self, uid: str) -> bool:
        before = len(self.all())
        self._store.remove(lambda item: item.get("uid") == uid)
        return len(self.all()) < before

    def clear(self) -> None:
        self._store.clear()

    # -------------------------------------------------------------- 内部
    def _mutate(self, uid: str, mutator: Callable[[SampleRecord], None]) -> bool:
        items = self._store.load()
        changed = False
        for item in items:
            if item.get("uid") == uid:
                record = record_from_dict(item)
                mutator(record)
                item.update(record.to_dict())
                changed = True
                break
        if changed:
            self._store.save(items)
        return changed
