# -*- coding: utf-8 -*-
"""移动端引导：把桌面端的核心逻辑层挂到 Kivy/Android 的目录约定上。

桌面端的 ``app.core.paths`` 在 Windows 下会把用户数据写到 ``%APPDATA%``，
在 Android 上这不可写。这里在导入任何会触发 ``JsonStore`` 创建的模块之前，
把 ``user_path()`` 重定向到一个可写目录：

* Android（python-for-android 会设置 ``ANDROID_ARGUMENT``）：``<私有文件目录>/userdata``
* 其它（桌面端测试）：仓库内的 ``.mobile_userdata``，避免污染桌面端数据
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent  # src/ModelPaintPal
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.core.paths as _paths  # noqa: E402

_MOBILE_USER_DIR: Optional[Path] = None


def _default_base() -> Path:
    env = os.environ.get("ANDROID_ARGUMENT")
    if env:
        return Path(env) / "userdata"
    return ROOT / ".mobile_userdata"


def set_user_dir(path) -> None:
    """显式指定用户数据目录（App 启动后可用 Kivy 的 user_data_dir 覆盖默认）。"""
    global _MOBILE_USER_DIR
    _MOBILE_USER_DIR = Path(path)


def _patched_user_path(*parts: str) -> Path:
    base = _MOBILE_USER_DIR if _MOBILE_USER_DIR is not None else _default_base()
    return base.joinpath(*parts)


# 在导入 config / 收藏 / 历史 等会构造 JsonStore 的模块之前完成替换
_paths.user_path = _patched_user_path
if hasattr(_paths, "USER_DATA_DIR"):
    try:
        _paths.USER_DATA_DIR = _patched_user_path()
    except Exception:  # pragma: no cover - 防御
        pass

__all__ = ["ROOT", "set_user_dir"]
