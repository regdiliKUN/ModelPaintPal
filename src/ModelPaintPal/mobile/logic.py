# -*- coding: utf-8 -*-
"""移动端的「逻辑胶水层」：在路径重定向之后惰性导入桌面端核心，并提供线程安全计算。

所有计算都丢到后台线程，结果通过 ``Clock`` 切回主线程，避免卡 UI（手机上尤其重要）。
桌面端的纯 Python 核心（配色引擎 / 色差 / 配方 / 漆库 / 覆盖率）全部复用，零改写。
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional, Sequence

from kivy.clock import Clock

# 单例缓存
_matcher = None
_config = None
_history = None
_favorites = None
_db = None
_coverage_input = None
_lock = threading.Lock()


def ensure_init() -> None:
    """在路径已重定向后，惰性导入会触发 JsonStore 的模块（只跑一次）。"""
    global _matcher, _config, _history, _favorites, _db, _coverage_input
    if _config is not None:
        return
    with _lock:
        if _config is not None:
            return
        from app.core.config import load_config
        from app.core.history_store import HistoryStore
        from app.core.favorites_store import FavoritesStore
        from app.data.paint_db import get_database
        from app.services.paint_matcher import PaintMatcher

        _config = load_config()
        _db = get_database()
        _matcher = PaintMatcher(_db)
        _history = HistoryStore(limit=_config.history_limit)
        _favorites = FavoritesStore(limit=_config.favorites_limit)
        _coverage_input = _default_coverage_input()


def _default_coverage_input():
    from app.services.coverage import CoverageInput
    return CoverageInput()


# ----------------------------------------------------------------- 访问器
def get_matcher():
    ensure_init()
    return _matcher


def get_config():
    ensure_init()
    return _config


def get_db():
    ensure_init()
    return _db


def get_history():
    ensure_init()
    return _history


def get_favorites():
    ensure_init()
    return _favorites


def get_coverage_input():
    ensure_init()
    return _coverage_input


def set_coverage_input(inp) -> None:
    global _coverage_input
    _coverage_input = inp


def brands() -> Dict[str, Any]:
    from app.data.brands import BRANDS
    return dict(BRANDS)


def reload_db() -> None:
    """校准 / 换库后重建漆库与匹配器。"""
    global _matcher, _db
    ensure_init()
    from app.data.paint_db import get_database
    _db = get_database(force=True)
    _matcher = get_matcher().__class__(_db)


# ----------------------------------------------------------------- 线程计算
def _run(fn: Callable[[], Any], on_done: Callable[[Any], None]) -> None:
    def work():
        try:
            result = fn()
        except Exception as exc:  # 计算失败不应让后台线程崩溃
            err = repr(exc)  # 捕获值，避免 except 作用域结束后 exc 被删除
            Clock.schedule_once(lambda dt: on_done(("error", err)), 0)
            return
        Clock.schedule_once(lambda dt: on_done(result), 0)
    threading.Thread(target=work, daemon=True).start()


def compute_suggest(rgb: Sequence[int], on_done,
                    brands: Optional[Sequence[str]] = None) -> None:
    def fn():
        ensure_init()
        return _matcher.suggest(rgb, _config, brands=brands,
                                coverage_input=_coverage_input)
    _run(fn, on_done)


def compute_mix(rgb: Sequence[int], on_done,
               brands: Optional[Sequence[str]] = None,
               total_drops: Optional[int] = None) -> None:
    def fn():
        ensure_init()
        from app.services.scheme_engine import compute_base_mix
        return compute_base_mix(rgb, _config, brands=brands,
                                matcher=_matcher, total_drops=total_drops)
    _run(fn, on_done)


def compute_coverage(inp, proportions: Optional[Dict[str, float]] = None,
                     bottle_ml: float = 0.0):
    ensure_init()
    from app.services.coverage import estimate_coverage
    return estimate_coverage(inp, proportions=proportions, bottle_ml=bottle_ml)


def run_verify(entry, on_done) -> None:
    def fn():
        ensure_init()
        from app.services.verify_service import verify_entry
        return verify_entry(entry)
    _run(fn, on_done)


def calibrate(uid: str, hex_value: str) -> bool:
    ensure_init()
    from app.data.paint_db import calibrate as _calibrate
    ok = _calibrate(uid, hex_value)
    if ok:
        reload_db()
    return ok


def adopt_verify(uid: str, hex_value: str) -> bool:
    ensure_init()
    from app.services.verify_service import adopt
    ok = adopt(_db.get(uid), hex_value)
    if ok:
        reload_db()
    return ok


# ----------------------------------------------------------------- 收藏 / 历史
def add_history(rgb: Sequence[int], source: str = "manual") -> None:
    ensure_init()
    from app.core.sample_record import SampleRecord
    _history.add(SampleRecord(rgb=tuple(int(v) for v in rgb[:3]), source=source))


def add_favorite(rgb: Sequence[int], source: str = "manual") -> None:
    ensure_init()
    from app.core.sample_record import SampleRecord
    _favorites.add(SampleRecord(rgb=tuple(int(v) for v in rgb[:3]), source=source))


def remove_history(uid: str) -> None:
    ensure_init()
    _history.remove(lambda item: item.get("uid") == uid)


def remove_favorite(uid: str) -> None:
    ensure_init()
    _favorites.remove(lambda item: item.get("uid") == uid)


def clear_history() -> None:
    ensure_init()
    _history.clear()


def clear_favorites() -> None:
    ensure_init()
    _favorites.clear()


# ----------------------------------------------------------------- 配置
def save_config() -> None:
    ensure_init()
    from app.core.config import save_config as _save
    _save(_config)


def set_preferred_brands(brands: Sequence[str]) -> None:
    ensure_init()
    _config.preferred_brands = list(brands)
    save_config()


def set_mix_brands(brands: Sequence[str]) -> None:
    ensure_init()
    _config.mix_brands = list(brands)
    save_config()


def set_drop_total(total: int) -> None:
    ensure_init()
    _config.drop_total = int(total)
    save_config()


# ----------------------------------------------------------------- 导出文本
def recipe_text(recipe) -> str:
    from app.services.export_service import recipe_to_text
    return recipe_to_text(recipe)


def suggestion_markdown(suggestion, target_hex: str = "") -> str:
    from app.services.export_service import suggestion_to_markdown
    return suggestion_to_markdown(suggestion, target_hex=target_hex)


def suggestions_json(suggestions, target_rgb) -> str:
    from app.services.export_service import suggestions_to_json
    from app.core.color_models import rgb_to_hex
    return suggestions_to_json(suggestions, rgb_to_hex(target_rgb))


def share_text(suggestions, target_rgb) -> str:
    from app.services.export_service import suggestions_to_share_text
    from app.core.color_models import rgb_to_hex
    return suggestions_to_share_text(suggestions, rgb_to_hex(target_rgb),
                                     title=f"涂装配色：{rgb_to_hex(target_rgb)}")


# ----------------------------------------------------------------- 剪贴板
def copy_text(text: str) -> bool:
    try:
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(text)
        return True
    except Exception:
        return False
