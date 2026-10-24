# -*- coding: utf-8 -*-
"""取色记录的统一数据结构（历史记录与收藏夹共用）。"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

from .color_models import normalize_rgb, rgb_to_hex

__all__ = ["SampleRecord", "record_from_rgb", "record_from_dict"]


class SampleRecord:
    """一条取色记录。序列化为纯 dict，便于 JSON 存储。"""

    __slots__ = ("uid", "rgb", "name", "source", "created_at", "note", "tags")

    def __init__(self,
                 rgb: Sequence[float],
                 name: str = "",
                 source: str = "screen",
                 created_at: Optional[float] = None,
                 note: str = "",
                 tags: Optional[Sequence[str]] = None,
                 uid: str = "") -> None:
        self.uid: str = uid or uuid.uuid4().hex[:12]
        self.rgb = normalize_rgb(rgb)
        self.name = name
        self.source = source
        self.created_at = float(created_at if created_at is not None else time.time())
        self.note = note
        self.tags = list(tags or [])

    # ---------------------------------------------------------------- 属性
    @property
    def hex(self) -> str:
        return rgb_to_hex(self.rgb)

    @property
    def display_name(self) -> str:
        return self.name or self.hex

    @property
    def time_text(self) -> str:
        return time.strftime("%m-%d %H:%M", time.localtime(self.created_at))

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "rgb": list(self.rgb),
            "hex": self.hex,
            "name": self.name,
            "source": self.source,
            "created_at": self.created_at,
            "note": self.note,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SampleRecord":
        rgb = data.get("rgb") or [0, 0, 0]
        return cls(
            rgb=rgb,
            name=data.get("name", ""),
            source=data.get("source", "screen"),
            created_at=data.get("created_at"),
            note=data.get("note", ""),
            tags=data.get("tags", []),
            uid=data.get("uid", ""),
        )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<SampleRecord {self.hex} {self.display_name!r}>"


def record_from_rgb(rgb: Sequence[float], **kwargs: Any) -> SampleRecord:
    return SampleRecord(rgb, **kwargs)


def record_from_dict(data: Dict[str, Any]) -> SampleRecord:
    """宽容解析：任何字段缺失/非法都回落到安全默认值，历史文件里出现脏数据也不会崩。

    注意：回退分支**不再**复用原始 ``rgb``——若原始 ``rgb`` 本身是非法值（例如
    字符串、None、长度不足），二次构造仍会抛错，进而连累 ``all()`` 加载整段历史。
    这里统一用 ``[0, 0, 0]`` 兜底，保证单条脏数据只废掉自己这一条。
    """
    if not isinstance(data, dict):
        return SampleRecord(rgb=[0, 0, 0])
    try:
        return SampleRecord.from_dict(data)
    except (TypeError, ValueError, KeyError):
        return SampleRecord(rgb=_safe_rgb(data.get("rgb")))


def _safe_rgb(value: Any) -> List[int]:
    """从任意脏数据里尽力抠出一个合法 RGB，失败则回落纯黑。

    用 ``normalize_rgb`` 而不是直接 ``int()``：脏数据里可能出现 999 / -20 这类
    越界通道值，不夹紧就会让 ``rgb_to_hex`` 生成非法色值、UI 画出色块异常。
    """
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return [0, 0, 0]
    try:
        return list(normalize_rgb(value[:3]))
    except (TypeError, ValueError):
        return [0, 0, 0]
