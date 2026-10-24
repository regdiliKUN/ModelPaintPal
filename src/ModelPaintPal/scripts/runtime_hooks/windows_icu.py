"""Prefer Windows ICU before Qt is imported in onedir and onefile builds."""

import ctypes
import os
from pathlib import Path

if os.name == "nt":
    system_icu = Path(os.environ["SystemRoot"]) / "System32" / "icuuc.dll"
    if system_icu.is_file():
        ctypes.WinDLL(str(system_icu))
