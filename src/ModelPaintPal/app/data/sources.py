# -*- coding: utf-8 -*-
"""色号数据的来源注册表。

为什么链接不直接写进 ``paint_seed``
-----------------------------------
672 条色号如果每条内联一个 URL，会同时带来三个问题：

1. 数据体积膨胀，且改一个链接要动 672 处；
2. URL 失效后无法统一维护；
3. **没法做一致性校验** —— 无法断言「这个来源是不是我们认识的那个」。

改成论文参考文献的做法：种子数据里只存来源 ID（``S:xxx``），真正的元数据集中
在这里。于是自检可以加一条硬断言：

    **色号引用的来源 ID 必须在注册表中存在**

这条断言是「不得编造来源」的机械保证 —— 手写 URL 无论写错还是编造，机器都
看不出来；但引用一个不存在的 ID，自检会直接失败。

未标注怎么处理
--------------
``paint_seed`` 目前仍是 8 元组（没有溯源字段），这些条目一律落到
``derived`` 且 ``src_ref`` 为空。这时候分两种状态，界面上必须区别对待：

* ``derived`` + 无 ``src_ref`` —— **未标注**：来源不明，不是"推定"。
  说"推定"等于暗示有人推过，那是撒谎。
* ``derived`` + 有 ``src_ref`` —— **推定**：确实是按同系色推出来的。

默认把未标注的置信度压到最低档，而不是抬到可信档 —— 这与项目一贯的
「数据不足就认」原则一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "Source",
    "SOURCES",
    "SOURCE_KINDS",
    "KIND_ORDER",
    "DEFAULT_CONFIDENCE",
    "FACT_KINDS",
    "ENTRY_SOURCES",
    "STALE_MONTHS",
    "get_source",
    "kind_label",
    "kind_confidence",
    "is_fact_kind",
    "is_stale",
    "annotate",
    "orphan_sources",
]

# 超过这个月数认为是「数据可能过期」。色卡目录是慢变数据，给到两年。
STALE_MONTHS = 24

# kind -> (界面标签, 默认置信度)
# 置信度是「这个色值有多可信」，不是「这条建议有多好」。
SOURCE_KINDS: Dict[str, Tuple[str, float]] = {
    "official":   ("厂家官方", 0.85),
    "standard":   ("标准色号体系", 0.80),
    "retail":     ("经销/零售目录", 0.75),
    "chart":      ("第三方色卡站", 0.70),
    "calibrated": ("本机试喷实测", 0.90),
    "derived":    ("推定", 0.45),
}

# 引用编号的排序权重：越可信的排越前。编号因此与输入顺序无关，
# 满足「同输入必须逐位可复现」的项目约定。
KIND_ORDER: Tuple[str, ...] = (
    "official", "standard", "retail", "chart", "calibrated", "derived",
)

# 算作「事实引用」的 kind。derived 不是 —— 它是推断。
FACT_KINDS = ("official", "standard", "retail", "chart", "calibrated")

DEFAULT_CONFIDENCE = 0.45


@dataclass(frozen=True)
class Source:
    """一条来源记录。"""

    id: str
    name: str
    url: str = ""
    kind: str = "official"
    accessed: str = ""      # YYYY-MM，采集/访问时间
    note: str = ""

    @property
    def kind_label(self) -> str:
        return SOURCE_KINDS.get(self.kind, (self.kind,))[0]


SOURCES: Dict[str, Source] = {
    # ---------------------------------------------------------- 厂家官方
    "S:gsi-h-official": Source(
        "S:gsi-h-official", "GSI Creos 官方产品目录 · Aqueous Hobby Color",
        "https://www.mr-hobby.com/", "official", "2026-10",
        "H 系列命名规则与色号表（DATA_ITERATIONS 第 1 轮）",
    ),
    "S:gsi-c-official": Source(
        "S:gsi-c-official", "GSI Creos 官方产品目录 · Mr.Color",
        "https://www.mr-hobby.com/", "official", "2026-10",
        "C 系列（DATA_ITERATIONS 第 1 轮）",
    ),
    "S:tamiya-official": Source(
        "S:tamiya-official", "Tamiya 官网 Acrylic / Enamel 产品列表",
        "https://www.tamiya.com/", "official", "2026-10",
        "X / XF 色号表（DATA_ITERATIONS 第 2 轮）",
    ),
    "S:vallejo-official": Source(
        "S:vallejo-official", "Acrylicos Vallejo 官网 Color Selection 目录",
        "https://acrylicosvallejo.com/", "official", "2026-10",
        "Model Color / Model Air（DATA_ITERATIONS 第 3 轮）",
    ),
    "S:ak-official": Source(
        "S:ak-official", "AK Interactive 官网产品页",
        "https://ak-interactive.com/", "official", "2026-10",
        "3rd Generation / Real Colors（DATA_ITERATIONS 第 5 轮）",
    ),
    "S:ammo-conversion": Source(
        "S:ammo-conversion", "AMMO by Mig 官方 Acrylic Colors Conversion Chart",
        "https://www.migjimenez.com/", "official", "2026-10",
        "跨品牌转换表，替代色号功能的两条证据链之一（DATA_ITERATIONS 第 6 轮）",
    ),
    "S:gaia-official": Source(
        "S:gaia-official", "Gaia Notes 官网产品线页",
        "https://www.gaianotes.com/", "official", "2026-10",
        "基本色 / 中性灰 / 军色分段（DATA_ITERATIONS 第 7 轮）",
    ),
    "S:humbrol-official": Source(
        "S:humbrol-official", "Humbrol 官网产品目录",
        "https://www.humbrol.com/", "official", "2026-10",
    ),
    "S:sms-official": Source(
        "S:sms-official", "SMS The Scale Modellers Supply 官方目录",
        "https://www.scalemodeller.com.au/", "official", "2026-10",
        "澳大利亚预稀释漆，与星影独立；具体色号的数字色值仍是近似值",
    ),
    # ------------------------------------------------------ 标准色号体系
    "S:fs595-public": Source(
        "S:fs595-public", "Federal Standard 595 公开色度表",
        "https://en.wikipedia.org/wiki/Federal_Standard_595", "standard", "2026-10",
        "FS14241 #87A298 / FS24031 #575450 / FS16376 #A9A99E（第 8 轮）",
    ),
    "S:ral-public": Source(
        "S:ral-public", "RAL 经典色卡公开色度数据", "", "standard", "2026-10",
    ),
    "S:rlm-public": Source(
        "S:rlm-public", "RLM 德国空军色号公开色度数据", "", "standard", "2026-10",
        "H-64~H-70 对应 RLM 71/70/79/65/74/75/02",
    ),
    "S:bs381c-public": Source(
        "S:bs381c-public", "BS 381C 英国标准色公开色度数据", "", "standard", "2026-10",
    ),
    # ------------------------------------------------------ 第三方色卡站
    "S:paint-vault": Source(
        "S:paint-vault", "paint-vault.com 数字化色卡库",
        "https://paint-vault.com/", "chart", "2026-10",
        "提供 HEX + CIELAB，本库多处取值以此为参照（第 9 轮）",
    ),
    "S:paintatlas": Source(
        "S:paintatlas", "paintatlas.com 数字化色卡库",
        "https://paintatlas.com/", "chart", "2026-10",
        "Vallejo 71.003 #C71F1C / 71.106 #C8B269（第 9 轮）",
    ),
    # ---------------------------------------------------------- 特殊来源
    "S:derived": Source(
        "S:derived", "按同系列相邻色推定", "", "derived", "",
        "无独立来源，仅用于相对匹配，务必试喷校准",
    ),
    "S:user-calibrated": Source(
        "S:user-calibrated", "本机试喷实测（用户校准）", "", "calibrated", "",
        "由「校准色值」写入 userdata/paint_overrides.json",
    ),
}

# ---------------------------------------------------------------------------
# 逐条色号的来源标注
#
# 672 条不可能一次补完，所以这里只登记**有明确文档依据**的条目 —— 全部来自
# docs/DATA_ITERATIONS.md 里写明的交叉校验结论，不在这里出现的条目一律按
# 「未标注」处理。补数据就往这个表里加，不用动 paint_seed。
#
# uid -> (kind, source_id, accessed)
# ---------------------------------------------------------------------------
ENTRY_SOURCES: Dict[str, Tuple[str, str, str]] = {
    # 第 2 / 9 轮：paint-vault 与官方取值一致，采纳
    "tamiya:X-32": ("chart", "S:paint-vault", "2026-10"),
    "tamiya:XF-56": ("chart", "S:paint-vault", "2026-10"),
    # 第 9 轮：paintatlas 的 Vallejo 取值替换了原估算值
    "vallejo_ma:71.003": ("chart", "S:paintatlas", "2026-10"),
    "vallejo_ma:71.106": ("chart", "S:paintatlas", "2026-10"),
    # 第 8 轮：FS 标准色锚点
    "gaia:061": ("standard", "S:fs595-public", "2026-10"),
    "gaia:062": ("standard", "S:fs595-public", "2026-10"),
}


def get_source(source_id: str) -> Optional[Source]:
    return SOURCES.get(source_id or "")


def kind_label(kind: str) -> str:
    return SOURCE_KINDS.get(kind, (kind, DEFAULT_CONFIDENCE))[0]


def kind_confidence(kind: str) -> float:
    return SOURCE_KINDS.get(kind, (kind, DEFAULT_CONFIDENCE))[1]


def is_fact_kind(kind: str) -> bool:
    return kind in FACT_KINDS


def is_stale(date_text: str, today: str = "") -> bool:
    """``YYYY-MM`` 距今超过 STALE_MONTHS 个月即视为过期。

    空日期返回 False —— 「不知道什么时候采的」是**未标注**问题，不是过期问题，
    两者在界面上是两个独立的信号，不能混。
    """
    if not date_text or len(date_text) < 7:
        return False
    from datetime import date

    if today:
        now_year, now_month = int(today[:4]), int(today[5:7])
    else:
        today_date = date.today()
        now_year, now_month = today_date.year, today_date.month
    try:
        year, month = int(date_text[:4]), int(date_text[5:7])
    except ValueError:
        return False
    month = max(1, min(12, month))
    return (now_year * 12 + now_month) - (year * 12 + month) > STALE_MONTHS


def annotate(uid: str) -> Tuple[str, str, str]:
    """取一条色号的来源标注；未登记的返回 derived 空引用（=未标注）。"""
    return ENTRY_SOURCES.get(uid, ("derived", "", ""))


def orphan_sources(used_ids) -> List[str]:
    """注册表里定义了但没有任何色号引用的来源（可疑，需要人工看一眼）。"""
    used = set(used_ids)
    return [sid for sid in SOURCES if sid not in used
            and sid not in ("S:derived", "S:user-calibrated")]
