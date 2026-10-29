# -*- coding: utf-8 -*-
"""应用配置项。

所有可调参数集中在此，UI 上的选项直接绑定到这里；未知/缺失字段自动回落到
默认值，保证老版本配置文件也能被新版本读取。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, get_type_hints

from .logging_setup import get_logger
from .storage import JsonStore

logger = get_logger(__name__)

CONFIG_FILENAME = "config.json"

__all__ = ["AppConfig", "load_config", "save_config", "update_config"]


def _coerce_field(hint, value: Any, default: Any) -> Any:
    """把任意 JSON 值按字段类型安全地收敛；无法收敛时抛错交由调用方回落默认值。"""
    if value is None:
        return default
    origin = getattr(hint, "__origin__", None)
    if origin is list:
        if isinstance(value, list):
            return [str(v) for v in value if v is not None]
        raise TypeError("expected list")
    if hint is bool:
        if isinstance(value, bool):
            return value
        raise TypeError("expected bool")
    if hint is int:
        return int(value)
    if hint is float:
        return float(value)
    if hint is str:
        return str(value)
    # 未识别类型：原样接受（由后续 validate 兜底）
    return value


@dataclass
class AppConfig:
    """可序列化的配置快照。字段名即配置文件键名，请勿随意重命名。"""

    def __setattr__(self, name: str, value: Any) -> None:
        """禁止写入不存在的配置项。

        dataclass 默认对未知属性「静默新建」，于是 ``cfg.mix_model = ...`` 这类
        字段名拼写错误不会报错，只会让后续逻辑读到默认值——问题极难定位。
        这里直接抛 ``AttributeError``，把拼写错误暴露在第一现场。
        """
        if name not in type(self).__dataclass_fields__:
            raise AttributeError(
                f"AppConfig 没有配置项 {name!r}；"
                f"可用字段见 dataclasses.fields(AppConfig)"
            )
        object.__setattr__(self, name, value)

    # ---------------- 取色 ----------------
    magnifier_zoom: int = 12
    magnifier_grid: int = 15           # 放大镜取样的像素边长（奇数便于居中）
    magnifier_follow: bool = True
    pick_hotkey: str = "Ctrl+Shift+X"  # 全局开始吸色
    copy_hex_hotkey: str = "Ctrl+Shift+C"
    auto_copy_on_pick: bool = False
    sample_average: int = 1            # 1=单像素；3/5 表示取 n×n 平均

    # ---------------- 色差 ----------------
    delta_e_formula: str = "CIEDE2000"
    match_tolerance: float = 3.0       # 判定“可直接用”的 ΔE 上限
    max_suggestions: int = 6

    # ---------------- 配色建议 ----------------
    preferred_brands: List[str] = field(default_factory=lambda: [
        "tamiya", "mr_hobby_h", "mr_color_c", "vallejo_mc", "ak_3gen",
    ])
    # 基础配色页「五瓶基础漆」统一到单一品牌；空列表 = 混搭（各瓶可来自不同品牌）
    mix_brands: List[str] = field(default_factory=lambda: ["tamiya"])
    allow_metallic_in_mix: bool = False
    allow_clear_in_mix: bool = False
    allow_cross_brand_mix: bool = False  # 默认只在同一产品线内混配
    mixing_model: str = "kubelka_munk"  # kubelka_munk | linear_rgb
    max_recipe_components: int = 3
    drop_total: int = 20                # 换算滴数时的基准总滴数

    # ---------------- 配色方案 ----------------
    # 取值见 services/scheme_engine.SCHEME_ORDER。这里存字符串而不是枚举，
    # 是为了让 core 层不依赖 services（依赖方向只能是 services → core）。
    # 未知值由面板忽略并保持当前选择，不会把界面搞崩。
    scheme_type: str = "basic"
    scheme_param: int = 0              # 仅邻近色/单色系有意义（色数/层次数 3–7）

    # ---------------- 用量估算 ----------------
    area_m2: float = 0.05               # 默认按 1/35 战车级别的展开面积
    coats: int = 2
    thinner_ratio: float = 1.0          # 稀释剂:漆 的体积比（1.0 = 1:1）
    application: str = "airbrush"       # airbrush | brush | spray_can
    surface: str = "primed"             # primed | raw_print | glossy
    # 保留旧配置键；按参考稀释比1:1折算原漆用量（110 -> 55），不随当前稀释比变动。
    mix_ml_per_m2_per_coat: float = 110.0
    waste_buffer: float = 1.15          # 比例余量
    fixed_paint_loss_ml: float = 0.0    # 另计的固定原漆损耗，默认不增加旧估算
    auto_prethinned: bool = True       # 预稀释产品按额外稀释剂0估算，可关闭

    # ---------------- 界面 ----------------
    theme: str = "dark"
    history_limit: int = 200
    favorites_limit: int = 200
    show_onboarding: bool = True
    window_width: int = 1280
    window_height: int = 860

    # ---------------- 其它 ----------------
    language: str = "zh-CN"
    check_updates_on_start: bool = False

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        defaults = cls()
        valid = {f.name for f in fields(cls)}
        type_hints = get_type_hints(cls)
        kwargs: Dict[str, Any] = {}
        for name in valid:
            if name not in (data or {}):
                kwargs[name] = getattr(defaults, name)
                continue
            value = data[name]
            hint = type_hints.get(name)
            try:
                kwargs[name] = _coerce_field(hint, value, getattr(defaults, name))
            except (TypeError, ValueError) as exc:
                # 仅该字段回落默认值，其余用户配置全部保留（不再整份清空）
                logger.warning("配置项 %s 类型异常，使用默认值: %r (%s)", name, value, exc)
                kwargs[name] = getattr(defaults, name)
        return cls(**kwargs)

    def reset_to_defaults(self) -> "AppConfig":
        """把当前实例的所有字段恢复为出厂默认值（UI「恢复默认设置」用）。

        走 ``object.__setattr__`` 以沿用 dataclass 的字段写入语义、同时绕过
        ``__setattr__`` 的字段名校验开销（字段名取自 ``fields(self)``，本就合法）。
        """
        default = type(self)()
        for f in fields(self):
            object.__setattr__(self, f.name, getattr(default, f.name))
        return self

    def validate(self) -> "AppConfig":
        """把越界值夹回安全区间，避免 UI 崩溃或算出荒谬结果。"""
        self.magnifier_zoom = max(2, min(40, int(self.magnifier_zoom)))
        self.magnifier_grid = max(3, min(41, int(self.magnifier_grid)))
        if self.magnifier_grid % 2 == 0:
            self.magnifier_grid += 1
        self.sample_average = max(1, min(9, int(self.sample_average)))
        if self.sample_average % 2 == 0:
            self.sample_average += 1
        self.delta_e_formula = str(self.delta_e_formula).upper()
        if self.delta_e_formula not in ("CIEDE2000", "CIE94", "CIE76", "CMC"):
            # 未知公式会被 delta_e 内部静默回落 CIEDE2000，属于「用户设了却没生效」的
            # 隐性错误；这里显式回落并给出默认值，让配置状态可读、可预测。
            self.delta_e_formula = "CIEDE2000"
        self.match_tolerance = max(0.2, min(20.0, float(self.match_tolerance)))
        self.max_suggestions = max(1, min(20, int(self.max_suggestions)))
        # 上限必须与引擎能力一致：`recipe_engine` 只搜索单色/双色/三色，
        # 设置页的控件范围也是 1–3。此前这里允许 4，手改配置成 4 的用户会得到一个
        # 「看起来设了 4、实际最多 3」的静默失效。
        self.max_recipe_components = max(1, min(3, int(self.max_recipe_components)))
        self.drop_total = max(4, min(200, int(self.drop_total)))
        self.area_m2 = max(0.0005, min(50.0, float(self.area_m2)))
        self.coats = max(1, min(8, int(self.coats)))
        self.thinner_ratio = max(0.0, min(5.0, float(self.thinner_ratio)))
        if self.application not in ("airbrush", "brush", "spray_can"):
            self.application = "airbrush"
        if self.surface not in ("primed", "raw_print", "glossy"):
            self.surface = "primed"
        if self.mixing_model not in ("kubelka_munk", "linear_rgb"):
            self.mixing_model = "kubelka_munk"
        self.mix_ml_per_m2_per_coat = max(10.0, min(400.0, float(self.mix_ml_per_m2_per_coat)))
        self.waste_buffer = max(1.0, min(3.0, float(self.waste_buffer)))
        self.fixed_paint_loss_ml = max(0.0, min(20.0, float(self.fixed_paint_loss_ml)))
        self.history_limit = max(10, min(2000, int(self.history_limit)))
        self.favorites_limit = max(10, min(2000, int(self.favorites_limit)))
        self.window_width = max(900, min(2560, int(self.window_width)))
        self.window_height = max(600, min(1600, int(self.window_height)))
        if not isinstance(self.preferred_brands, list):
            self.preferred_brands = ["tamiya"]
        if not isinstance(self.mix_brands, list):
            self.mix_brands = ["tamiya"]
        self.scheme_type = str(self.scheme_type or "basic")
        self.scheme_param = max(0, min(7, int(self.scheme_param)))
        return self


_store = JsonStore(CONFIG_FILENAME, lambda: AppConfig().to_dict())


def load_config() -> AppConfig:
    raw = _store.load()
    if not isinstance(raw, dict):
        logger.warning("配置文件结构异常，使用默认配置")
        return AppConfig().validate()
    return AppConfig.from_dict(raw).validate()


def save_config(config: AppConfig) -> bool:
    return _store.save(config.to_dict())


def update_config(**changes: Any) -> AppConfig:
    """读-改-写一步到位，返回校验后的新配置。"""
    config = load_config()
    for key, value in changes.items():
        if hasattr(config, key):
            setattr(config, key, value)
        else:
            logger.warning("尝试设置不存在的配置项: %s", key)
    config.validate()
    save_config(config)
    return config
