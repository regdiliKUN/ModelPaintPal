# -*- coding: utf-8 -*-
"""JSON 持久化基类。

统一处理：目录创建、原子写入、损坏文件隔离（另存为 .corrupt-* 后重建），
避免一次写坏导致应用再也无法启动。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Generic, TypeVar

from .logging_setup import get_logger
from .paths import ensure_dir, user_path

logger = get_logger(__name__)

T = TypeVar("T")

__all__ = ["JsonStore", "CollectionStore"]


class JsonStore(Generic[T]):
    """单个 JSON 文档的读写封装。"""

    def __init__(self, filename: str, default_factory: Callable[[], T],
                 subdir: str = "") -> None:
        parts = [subdir, filename] if subdir else [filename]
        self.path: Path = user_path(*parts)
        self._default_factory = default_factory

    # ------------------------------------------------------------------ 读
    def load(self) -> T:
        if not self.path.exists():
            return self._default_factory()
        try:
            with self.path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            logger.warning("数据文件损坏，已隔离重建: %s (%s)", self.path, exc)
            self._quarantine()
            return self._default_factory()

    # ------------------------------------------------------------------ 写
    def save(self, data: T) -> bool:
        """原子写：先写临时文件再替换，避免半截文件。"""
        try:
            ensure_dir(self.path.parent)
            fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_name, self.path)
            return True
        except (OSError, TypeError, ValueError) as exc:
            logger.error("保存失败 %s: %s", self.path, exc)
            self._safe_remove(tmp_name) if "tmp_name" in dir() else None
            return False

    # -------------------------------------------------------------- 辅助
    def exists(self) -> bool:
        return self.path.exists()

    def delete(self) -> bool:
        try:
            if self.path.exists():
                self.path.unlink()
            return True
        except OSError as exc:
            logger.error("删除失败 %s: %s", self.path, exc)
            return False

    def _quarantine(self) -> None:
        try:
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            idx = 0
            while backup.exists():
                idx += 1
                backup = self.path.with_suffix(self.path.suffix + f".corrupt-{idx}")
            self.path.replace(backup)
        except OSError as exc:
            logger.error("隔离损坏文件失败 %s: %s", self.path, exc)

    @staticmethod
    def _safe_remove(path: str) -> None:
        try:
            if path and os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass


class CollectionStore(JsonStore):
    """带上限的列表型存储（历史记录 / 收藏夹共用）。"""

    def __init__(self, filename: str, limit: int = 200, subdir: str = "") -> None:
        super().__init__(filename, list, subdir=subdir)  # type: ignore[arg-type]
        self.limit = max(1, int(limit))

    def load(self) -> list:
        data = super().load()
        if not isinstance(data, list):
            logger.warning("集合数据格式异常，重置为空: %s", self.path)
            return []
        return [item for item in data if isinstance(item, dict)]

    def append(self, item: Dict[str, Any], dedup_key: str = "") -> list:
        """追加一条并裁剪到上限；``dedup_key`` 非空时先去重再置顶。"""
        if not isinstance(item, dict):
            # 防御：非字典项一旦落盘会污染后续加载，直接拒绝并保留现有数据
            logger.warning("跳过非字典条目，不写入: %r", item)
            return self.load()
        items = self.load()
        if dedup_key:
            items = [old for old in items if old.get(dedup_key) != item.get(dedup_key)]
        items.insert(0, item)
        trimmed = items[: self.limit]
        self.save(trimmed)
        return trimmed

    def remove(self, matcher: Callable[[Dict[str, Any]], bool]) -> list:
        items = [item for item in self.load() if not matcher(item)]
        self.save(items)
        return items

    def clear(self) -> list:
        self.save([])
        return []
