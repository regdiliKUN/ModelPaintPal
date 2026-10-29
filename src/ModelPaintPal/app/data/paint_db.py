# -*- coding: utf-8 -*-
"""模型漆色号数据库。

职责：
1. 把 ``paint_seed`` 里的紧凑元组展开成带 Lab 缓存的 ``PaintEntry``；
2. 合并用户校准（``user_overrides.json``），让试喷结果能反哺数据库；
3. 提供按品牌 / 漆种 / 标准色的检索，供配色引擎与 UI 使用。

数据库是只读视图；任何修改都通过 ``calibrate()`` 落到用户目录，不污染随包数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from ..core.color_models import hex_to_rgb, rgb_to_hex, rgb_to_lab
from ..core.logging_setup import get_logger
from ..core.storage import JsonStore
from .brands import BRANDS, Brand
from .paint_seed import FINISH_LABELS, OPACITY_LABELS, SEED_TABLES
from . import sources as _sources

logger = get_logger(__name__)

__all__ = ["PaintEntry", "PaintDatabase", "get_database", "reload_database"]

_OVERRIDES_FILE = "paint_overrides.json"
# 参与混合的漆种（透明漆/荧光漆混合行为不可预测，默认排除）
_MIXABLE_FINISHES = ("gloss", "semi", "flat")
_NON_MIXABLE = ("clear", "fluor")


@dataclass
class PaintEntry:
    """一条色号记录（不可变，Lab 惰性计算后缓存）。"""

    uid: str
    brand_key: str
    code: str
    name: str
    name_en: str
    rgb: tuple
    finish: str
    opacity: str
    standards: List[str] = field(default_factory=list)
    note: str = ""
    volume_ml: float = 10.0
    # ---- 溯源（见 app/data/sources.py）----
    # src_kind 为空串时由 __post_init__ 收敛为 derived；confidence 为 None 时
    # 取该 kind 的默认置信度。这样调用方只给 kind 也能拿到一个自洽的记录。
    src_kind: str = ""
    src_ref: str = ""
    src_date: str = ""
    confidence: Optional[float] = None
    _lab: Optional[tuple] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.src_kind not in _sources.SOURCE_KINDS:
            self.src_kind = "derived"
        if self.confidence is None or not isinstance(self.confidence, (int, float)):
            self.confidence = _sources.kind_confidence(self.src_kind)
        else:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))

    # -------------------------------------------------------------- 派生量
    @property
    def hex(self) -> str:
        return rgb_to_hex(self.rgb)

    @property
    def source(self) -> Optional["_sources.Source"]:
        """这条色号引用的来源记录；未标注时返回 None。"""
        return _sources.get_source(self.src_ref)

    @property
    def is_annotated(self) -> bool:
        """是否登记了来源。未登记 = 来源不明，界面要显示「未标注」而非「推定」。"""
        return bool(self.src_ref) and self.src_ref in _sources.SOURCES

    @property
    def is_fact(self) -> bool:
        return _sources.is_fact_kind(self.src_kind)

    @property
    def is_stale(self) -> bool:
        """来源数据是否过期（与「未标注」是两个独立信号）。"""
        return _sources.is_stale(self.src_date)

    @property
    def provenance(self) -> dict:
        """给 UI / 导出用的溯源视图。"""
        src = self.source
        return {
            "uid": self.uid,
            "kind": self.src_kind,
            "kind_label": _sources.kind_label(self.src_kind),
            "annotated": self.is_annotated,
            "source_id": self.src_ref,
            "source_name": src.name if src else "",
            "url": src.url if src else "",
            "date": self.src_date,
            "stale": self.is_stale,
            "confidence": round(float(self.confidence or 0.0), 2),
            "is_fact": self.is_fact,
        }

    @property
    def lab(self) -> tuple:
        if self._lab is None:
            self._lab = rgb_to_lab(self.rgb)
        return self._lab

    @property
    def brand(self) -> Optional[Brand]:
        return BRANDS.get(self.brand_key)

    @property
    def brand_label(self) -> str:
        brand = self.brand
        return brand.short if brand else self.brand_key

    @property
    def full_label(self) -> str:
        return f"{self.brand_label} {self.code}"

    @property
    def finish_label(self) -> str:
        return FINISH_LABELS.get(self.finish, self.finish)

    @property
    def opacity_label(self) -> str:
        return OPACITY_LABELS.get(self.opacity, self.opacity)

    @property
    def is_metallic(self) -> bool:
        return self.finish in ("metal", "pearl")

    @property
    def is_clear(self) -> bool:
        return self.finish == "clear" or self.opacity == "clear"

    def is_mixable(self, allow_metallic: bool = False, allow_clear: bool = False) -> bool:
        """是否可作为调色组分。"""
        if self.is_clear and not allow_clear:
            return False
        if self.finish == "fluor" and not allow_clear:
            return False
        if self.is_metallic and not allow_metallic:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "brand": self.brand_key,
            "code": self.code,
            "name": self.name,
            "name_en": self.name_en,
            "hex": self.hex,
            "finish": self.finish,
            "opacity": self.opacity,
            "standards": list(self.standards),
            "note": self.note,
            "volume_ml": self.volume_ml,
            # 溯源字段只增不改，保证旧版导出的 JSON 仍能被 from_dict 读回
            "src_kind": self.src_kind,
            "src_ref": self.src_ref,
            "src_date": self.src_date,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PaintEntry":
        rgb = data.get("rgb")
        if not rgb:
            rgb = hex_to_rgb(data["hex"])
        return cls(
            uid=data.get("uid") or f"{data['brand']}:{data['code']}",
            brand_key=data["brand"],
            code=data["code"],
            name=data.get("name", ""),
            name_en=data.get("name_en", ""),
            rgb=tuple(int(c) for c in rgb),
            finish=data.get("finish", "flat"),
            opacity=data.get("opacity", "opaque"),
            standards=list(data.get("standards") or []),
            note=data.get("note", ""),
            volume_ml=float(data.get("volume_ml", 10.0)),
            src_kind=data.get("src_kind", ""),
            src_ref=data.get("src_ref", ""),
            src_date=data.get("src_date", ""),
            confidence=data.get("confidence"),
        )


class PaintDatabase:
    """色号集合。构造后即为只读快照，支持整体重建。"""

    def __init__(self, entries: Sequence[PaintEntry]) -> None:
        self._entries: List[PaintEntry] = list(entries)
        self._by_uid: Dict[str, PaintEntry] = {e.uid: e for e in self._entries}
        self._by_brand: Dict[str, List[PaintEntry]] = {}
        for entry in self._entries:
            self._by_brand.setdefault(entry.brand_key, []).append(entry)
        self._by_standard: Dict[str, List[PaintEntry]] = {}
        for entry in self._entries:
            for standard in entry.standards:
                self._by_standard.setdefault(standard.upper(), []).append(entry)

    # ---------------------------------------------------------------- 访问
    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    @property
    def entries(self) -> List[PaintEntry]:
        return list(self._entries)

    @property
    def brands(self) -> List[str]:
        return list(self._by_brand.keys())

    def get(self, uid: str) -> Optional[PaintEntry]:
        return self._by_uid.get(uid)

    def by_brand(self, brand_key: str) -> List[PaintEntry]:
        return list(self._by_brand.get(brand_key, []))

    def by_brands(self, brand_keys: Iterable[str]) -> List[PaintEntry]:
        """按调用方给定的品牌顺序拼接候选；重复品牌只取一次。

        这里刻意不用 ``set(brand_keys)``：集合迭代顺序受哈希随机化影响，
        会让同一组品牌在不同进程里得到不同候选顺序，进而让配方搜索的并列最优、
        截断位置甚至偶尔的 max_components 判定结果发生漂移——同一输入必须可复现。
        """
        out: List[PaintEntry] = []
        seen: Set[str] = set()
        for key in brand_keys:
            if key in seen:
                continue
            seen.add(key)
            out.extend(self._by_brand.get(key, []))
        return out

    def by_standard(self, standard: str) -> List[PaintEntry]:
        return list(self._by_standard.get(standard.upper(), []))

    def search(self, text: str, brand_keys: Optional[Iterable[str]] = None) -> List[PaintEntry]:
        """按色号 / 中英文名 / 标准色号模糊搜索。"""
        keyword = (text or "").strip().lower()
        pool = self.by_brands(brand_keys) if brand_keys else self._entries
        if not keyword:
            return list(pool)
        return [
            entry for entry in pool
            if keyword in entry.code.lower()
            or keyword in entry.name.lower()
            or keyword in entry.name_en.lower()
            or any(keyword in std.lower() for std in entry.standards)
        ]

    def standards_of(self, entry: PaintEntry) -> Set[str]:
        return {std.upper() for std in entry.standards}

    def count_by_brand(self) -> Dict[str, int]:
        return {key: len(items) for key, items in self._by_brand.items()}


# ---------------------------------------------------------------------------
# 构建与缓存
# ---------------------------------------------------------------------------
_overrides_store = JsonStore(_OVERRIDES_FILE, dict)
_database: Optional[PaintDatabase] = None


def _build_from_seed() -> List[PaintEntry]:
    overrides: dict = _overrides_store.load() or {}
    entries: List[PaintEntry] = []
    for brand_key, rows in SEED_TABLES.items():
        brand = BRANDS.get(brand_key)
        volume = brand.volume_ml if brand else 10.0
        for row in rows:
            if len(row) < 8:
                logger.error("跳过字段不足的记录 %s: %r", brand_key, row)
                continue
            # 只解前 8 位：12 元组的新格式多出来的 4 位是溯源字段，单独取。
            # 这样 8 元组老数据一行都不用改就能继续用。
            code, name, name_en, hex_value, finish, opacity, standards, note = row[:8]
            uid = f"{brand_key}:{code}"
            try:
                rgb = hex_to_rgb(hex_value)
            except ValueError:
                logger.error("跳过非法色值 %s (%s)", uid, hex_value)
                continue

            # 溯源优先级：行内 12 元组 > ENTRY_SOURCES 逐条标注 > 未标注
            if len(row) >= 12:
                src_kind, src_ref, src_date = row[8], row[9], row[10]
                src_conf = row[11] or None
            else:
                src_kind, src_ref, src_date = _sources.annotate(uid)
                src_conf = None

            patch = overrides.get(uid)
            calibrated = False
            if isinstance(patch, dict) and patch.get("hex"):
                try:
                    rgb = hex_to_rgb(patch["hex"])
                    calibrated = True
                except ValueError:
                    logger.warning("校准色值非法，忽略: %s", patch["hex"])
            if calibrated:
                # 用户拿喷笔实测出来的值，比任何外部目录都可信 —— 来源升级。
                # 这也是「误差交还给用户」这条回路在溯源体系里的落点。
                src_kind = "calibrated"
                src_ref = "S:user-calibrated"
                src_date = patch.get("date") or src_date or ""
                src_conf = None

            standards_list = [s.strip() for s in standards.split(";") if s.strip()]
            entries.append(PaintEntry(
                uid=uid, brand_key=brand_key, code=code, name=name, name_en=name_en,
                rgb=rgb, finish=finish, opacity=opacity, standards=standards_list,
                note=note, volume_ml=volume,
                src_kind=src_kind, src_ref=src_ref, src_date=src_date,
                confidence=src_conf,
            ))
    return entries


def build_database() -> PaintDatabase:
    return PaintDatabase(_build_from_seed())


def get_database(force: bool = False) -> PaintDatabase:
    """进程内单例；``force=True`` 用于校准后立即重建。"""
    global _database
    if _database is None or force:
        _database = build_database()
        logger.info("色号库加载完成：%d 条 / %d 个品牌",
                    len(_database), len(_database.brands))
    return _database


def reload_database() -> PaintDatabase:
    return get_database(force=True)


def calibrate(uid: str, hex_value: str) -> bool:
    """写入用户校准值（覆盖随包数据的近似色值）。

    只接受**库里真实存在**的色号：此前对任意 uid 都会写成功，于是在设置页留下一条
    「X-99 → #FF0000」的幽灵校准记录——它不对应任何色号、不影响任何结果，而单条
    删除是按色号列表走的，用户只能「清空全部校准」才能把它弄掉。
    """
    try:
        hex_to_rgb(hex_value)
    except ValueError as exc:
        logger.error("校准失败: %s", exc)
        return False
    if get_database().get(uid) is None:
        logger.warning("校准失败：色号 %s 不在当前色号库中", uid)
        return False
    overrides = _overrides_store.load() or {}
    # 记下校准时间：它是这条色号新的采集时间，过没过期要靠它判断。
    from datetime import date as _date
    overrides[uid] = {"hex": hex_value.upper(),
                      "date": _date.today().strftime("%Y-%m")}
    if _overrides_store.save(overrides):
        reload_database()
        return True
    return False


def reset_calibration(uid: str = "") -> bool:
    """清除校准（传 uid 清一条，不传则清空）。"""
    if not uid:
        ok = _overrides_store.save({})
    else:
        overrides = _overrides_store.load() or {}
        if uid in overrides:
            overrides.pop(uid)
            ok = _overrides_store.save(overrides)
        else:
            ok = True
    if ok:
        reload_database()
    return ok


def calibration_map() -> Dict[str, str]:
    """当前生效的校准表（只含库里真实存在的色号）。

    文件里可能残留历史遗留的无效 uid（例如旧版本写进去的、或色号库调整后消失的），
    界面不该把它们列成「已校准」——那不是用户能理解的记录。
    """
    overrides = _overrides_store.load() or {}
    database = get_database()
    return {
        key: str(value.get("hex", ""))
        for key, value in overrides.items()
        if isinstance(value, dict) and database.get(key) is not None
    }
