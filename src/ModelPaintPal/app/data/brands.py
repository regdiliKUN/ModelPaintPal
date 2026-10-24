# -*- coding: utf-8 -*-
"""品牌元数据。

``volume_ml`` 用于把估算出的用漆量换算成“几瓶漆”。
``thinner`` 用于配方建议里给出稀释提示。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

__all__ = ["Brand", "BRANDS", "brand_keys", "get_brand", "brand_label"]


@dataclass(frozen=True)
class Brand:
    key: str
    name: str            # 展示名（中文 + 英文）
    short: str           # 短名，用于标签
    line: str            # 产品线
    paint_type: str      # acrylic / lacquer / enamel
    volume_ml: float     # 常见单瓶容量
    thinner: str = ""    # 推荐稀释剂
    region: str = ""
    url: str = ""
    pre_thinned: bool = False

    @property
    def type_label(self) -> str:
        return {
            "acrylic": "水性丙烯酸",
            "lacquer": "硝基/油性丙烯酸",
            "enamel": "珐琅（油性）",
            "urethane": "聚氨酯水性",
        }.get(self.paint_type, self.paint_type)


BRANDS: Dict[str, Brand] = {
    "tamiya": Brand(
        key="tamiya", name="田宫 Tamiya", short="田宫",
        line="Tamiya Color 丙烯酸（X / XF）", paint_type="acrylic", volume_ml=10.0,
        thinner="X-20A 水性溶剂或水（喷笔建议 1:1~1:2）", region="日本",
        url="https://www.tamiya.com/",
    ),
    "mr_hobby_h": Brand(
        key="mr_hobby_h", name="郡士 Mr.Hobby 水性", short="郡士H",
        line="Aqueous Hobby Color（H 系列）", paint_type="acrylic", volume_ml=10.0,
        thinner="专用水性溶剂或水（喷笔建议 1:1~1:1.5）", region="日本",
        url="https://www.mr-hobby.com/",
    ),
    "mr_color_c": Brand(
        key="mr_color_c", name="郡士 Mr.Color 油性", short="郡士C",
        line="Mr.Color（C 系列）", paint_type="lacquer", volume_ml=10.0,
        thinner="Mr.Color Thinner（喷笔建议 漆:溶剂 = 1:1.5~1:2）", region="日本",
        url="https://www.mr-hobby.com/",
    ),
    "vallejo_mc": Brand(
        key="vallejo_mc", name="AV 酋长大陆 Vallejo Model Color", short="AV-MC",
        line="Model Color 70.xxx（笔涂为主）", paint_type="acrylic", volume_ml=17.0,
        thinner="Vallejo Thinner / 水（喷笔建议 1:1）", region="西班牙",
        url="https://acrylicosvallejo.com/",
    ),
    "vallejo_ma": Brand(
        key="vallejo_ma", name="AV Vallejo Model Air", short="AV-MA",
        line="Model Air 71.xxx（预稀释，喷笔即用）", paint_type="acrylic", volume_ml=17.0,
        thinner="可直接使用；需进一步稀释时使用 Airbrush Thinner 71.261", region="西班牙",
        url="https://acrylicosvallejo.com/",
        pre_thinned=True,
    ),
    "ak_3gen": Brand(
        key="ak_3gen", name="AK Interactive 3rd Gen", short="AK3",
        line="3rd Generation Acrylic AK11xxx", paint_type="acrylic", volume_ml=18.0,
        thinner="AK Thinner / 专用稀释剂（喷笔建议 1:1）", region="西班牙",
        url="https://ak-interactive.com/",
    ),
    "ak_rc": Brand(
        key="ak_rc", name="AK Real Colors", short="AK-RC",
        line="Real Colors RCxxx（旧版10 ml罐装色号）", paint_type="lacquer", volume_ml=10.0,
        thinner="AK Real Colors Thinner（喷笔建议 1:1.5）", region="西班牙",
        url="https://ak-interactive.com/",
    ),
    "ammo": Brand(
        key="ammo", name="AMMO by Mig Jimenez", short="AMMO",
        line="A.MIG-0xxx 水性丙烯酸", paint_type="acrylic", volume_ml=17.0,
        thinner="AMIG-2000 Acrylic Thinner（喷笔建议 1:1）", region="西班牙",
        url="https://www.migjimenez.com/",
    ),
    "gaia": Brand(
        key="gaia", name="盖亚 Gaia Notes", short="盖亚",
        line="Gaia Color（硝基类）", paint_type="lacquer", volume_ml=15.0,
        thinner="Gaia 专用溶剂（喷笔建议 1:1.5~1:2）", region="日本",
        url="https://www.gaianotes.com/",
    ),
    "humbrol": Brand(
        key="humbrol", name="Humbrol 汉宝", short="汉宝",
        line="Humbrol Enamel（珐琅系列）", paint_type="enamel", volume_ml=14.0,
        thinner="Humbrol Enamel Thinners", region="英国",
        url="https://www.humbrol.com/",
    ),
    "sms": Brand(
        key="sms", name="SMS The Scale Modellers Supply", short="SMS",
        line="Premium Acrylic Lacquer（预稀释）", paint_type="lacquer", volume_ml=30.0,
        thinner="可直接喷；需进一步稀释时使用兼容的 Acrylic Lacquer Thinner", region="澳大利亚",
        url="https://www.scalemodeller.com.au/",
        pre_thinned=True,
    ),
}


def brand_keys() -> List[str]:
    return list(BRANDS.keys())


def get_brand(key: str) -> Optional[Brand]:
    return BRANDS.get(key)


def brand_label(key: str) -> str:
    brand = BRANDS.get(key)
    return brand.short if brand else key
