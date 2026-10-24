# -*- coding: utf-8 -*-
"""路径与运行模式判定。

打包（PyInstaller onefile/onedir）与源码运行共用同一套解析逻辑：
* ``PROJECT_ROOT``   源码根目录
* ``USER_DATA_DIR`` 可写目录（便携模式下落在 exe 同级，安装模式下落在 %APPDATA%）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

__all__ = [
    "PROJECT_ROOT",
    "IS_FROZEN",
    "BUNDLE_DIR",
    "USER_DATA_DIR",
    "resource_path",
    "user_path",
    "ensure_dir",
]


def _detect_bundle_dir() -> Path:
    """PyInstaller 注入的临时解包目录，或源码根目录。"""
    if getattr(sys, "frozen", False):  # pragma: no cover - 仅打包态触发
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


IS_FROZEN: bool = bool(getattr(sys, "frozen", False))
BUNDLE_DIR: Path = _detect_bundle_dir()
PROJECT_ROOT: Path = BUNDLE_DIR

# 便携模式：exe 同级存在 portable.marker 即把所有用户数据写在程序旁，
# 方便整目录拷走（符合“绿色便携版”诉求）。
_PORTABLE_MARKER = "portable.marker"


def _detect_user_data_dir() -> Path:
    exe_dir = Path(sys.executable).resolve().parent if IS_FROZEN else PROJECT_ROOT
    if (exe_dir / _PORTABLE_MARKER).exists():
        return exe_dir / "userdata"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "ModelPaintPal"
    return Path.home() / ".modelpaintpal"


USER_DATA_DIR: Path = _detect_user_data_dir()


def resource_path(*parts: str) -> Path:
    """定位随包发布的只读资源（数据库、图标等）。"""
    return BUNDLE_DIR.joinpath(*parts)


def user_path(*parts: str) -> Path:
    """定位用户可写数据（配置、历史、收藏、校准覆盖）。"""
    return USER_DATA_DIR.joinpath(*parts)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def enable_portable_mode() -> Optional[Path]:
    """在 exe 同级放下便携标记（仅打包态有意义），返回标记路径。"""
    if not IS_FROZEN:
        return None
    marker = Path(sys.executable).resolve().parent / _PORTABLE_MARKER
    marker.write_text("portable\n", encoding="utf-8")
    return marker
