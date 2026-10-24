# -*- coding: utf-8 -*-
"""构建脚本：生成 Windows 绿色便携版 / 单文件版。

    python scripts/build.py                 # 默认构建 onedir 便携版并打 zip
    python scripts/build.py --mode onefile  # 单文件 exe
    python scripts/build.py --clean-only    # 只清理构建产物

产物：
    dist/ModelPaintPal/            绿色便携版目录（整目录拷贝即可用）
    dist/ModelPaintPal-Portable.zip
    dist/ModelPaintPal.exe         单文件版（--mode onefile）
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
DIST_TMP = PROJECT_ROOT / "build_tmp"
APP_NAME = "ModelPaintPal"

# 用不到的 Qt 子模块，排除后可显著减小包体
EXCLUDED_MODULES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtQuick3D", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.Qt3DCore",
    "PySide6.QtBluetooth", "PySide6.QtNetworkAuth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtWebSockets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtStateMachine", "PySide6.QtWebChannel",
    "PySide6.QtHttpServer", "PySide6.QtQmlCore", "PySide6.QtQmlNetwork",
    "PySide6.QtQmlXml", "PySide6.QtOpenGLWidgets", "PySide6.QtAxContainer",
    "tkinter", "unittest", "pydoc", "doctest",
]

ENTRY = PROJECT_ROOT / "run.py"


def _run(command: list, cwd: Path) -> int:
    print("$", " ".join(str(part) for part in command))
    completed = subprocess.run(command, cwd=str(cwd))
    return completed.returncode


def _ensure_pyinstaller() -> bool:
    import importlib.util

    if importlib.util.find_spec("PyInstaller") is None:
        print("未检测到 PyInstaller，请先执行：pip install pyinstaller")
        return False
    return True


def _make_icon() -> Path:
    """复用 scripts/make_icon.py 的调色盘设计（单一来源，避免两处图标不一致）。"""
    import importlib.util

    icon_script = PROJECT_ROOT / "scripts" / "make_icon.py"
    spec = importlib.util.spec_from_file_location("make_icon", icon_script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main([])
    return mod.ICO_PATH


def _clean() -> None:
    for path in (DIST_DIR, BUILD_DIR, DIST_TMP):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            print(f"已清理 {path}")
    spec = PROJECT_ROOT / f"{APP_NAME}.spec"
    if spec.exists():
        spec.unlink()


def _build(mode: str, icon: Path) -> int:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", APP_NAME,
        "--icon", str(icon),
        "--runtime-hook", str(PROJECT_ROOT / "scripts" / "runtime_hooks" / "windows_icu.py"),
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(PROJECT_ROOT),
    ]
    if mode == "onedir":
        command.append("--onedir")
    else:
        command.append("--onefile")

    for module in EXCLUDED_MODULES:
        command.extend(["--exclude-module", module])

    # mss 需要在包内带上自己的数据文件
    command.extend(["--collect-submodules", "mss"])
    command.append(str(ENTRY))

    return _run(command, PROJECT_ROOT)


def _check_windows_icu(target: Path) -> None:
    """Qt的新Windows轮子依赖系统ICU，不能被PATH里的Poppler/Conda同名DLL覆盖。"""
    if os.name != "nt":
        return
    import ctypes
    import pefile

    internal = target / "_internal"
    core = internal / "PySide6" / "Qt6Core.dll"
    if not core.exists():
        return
    with pefile.PE(str(core)) as pe:
        required = [symbol.name.decode("ascii")
                    for dependency in pe.DIRECTORY_ENTRY_IMPORT
                    if dependency.dll.lower() == b"icuuc.dll"
                    for symbol in dependency.imports if symbol.name]
    if not required:
        return
    system_icu = Path(os.environ["SystemRoot"]) / "System32" / "icuuc.dll"
    library = ctypes.WinDLL(str(system_icu))
    if any(not hasattr(library, name) for name in required):
        raise RuntimeError("本机Windows ICU缺少Qt所需接口，请使用兼容的Qt构建环境")
    shadow = internal / "icuuc.dll"
    if shadow.is_file():
        shadow.unlink()
    print(f"Windows ICU接口已验证，使用系统DLL：{system_icu}")


def _post_process(mode: str) -> None:
    """把文档、便携标记等放进产物目录。"""
    if mode == "onefile":
        return
    target = DIST_DIR / APP_NAME
    if not target.exists():
        return
    _check_windows_icu(target)

    docs_target = target / "docs"
    docs_target.mkdir(parents=True, exist_ok=True)
    for name in ("README.md", "LICENSE"):
        source = PROJECT_ROOT / name
        if source.exists():
            shutil.copy2(source, target / name)
    for doc in (PROJECT_ROOT / "docs").glob("*.md"):
        shutil.copy2(doc, docs_target / doc.name)

    # 便携模式标记：存在时用户数据写在程序同级，方便整目录带走
    (target / "portable.marker").write_text("portable\n", encoding="utf-8")
    (target / "userdata").mkdir(exist_ok=True)
    print(f"便携版就绪：{target}")


def _zip_portable() -> Path | None:
    source = DIST_DIR / APP_NAME
    if not source.exists():
        return None
    archive = DIST_DIR / f"{APP_NAME}-Portable.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in source.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(source))
    print(f"压缩包：{archive}（{archive.stat().st_size / 1024 / 1024:.1f} MB）")
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 ModelPaintPal 桌面应用")
    parser.add_argument("--mode", choices=("onedir", "onefile"), default="onedir",
                        help="onedir=绿色便携版目录（默认）；onefile=单文件 exe")
    parser.add_argument("--no-zip", action="store_true", help="不生成便携版压缩包")
    parser.add_argument("--clean-only", action="store_true", help="只清理产物后退出")
    parser.add_argument("--no-clean", action="store_true",
                        help="构建前不清空 dist/build（增量重打包，PyInstaller 会自行覆盖同名产物）")
    args = parser.parse_args()

    if args.clean_only:
        _clean()
        return 0

    if not _ensure_pyinstaller():
        return 1

    if args.no_clean:
        print("跳过清理（--no-clean）")
    else:
        _clean()
    icon = _make_icon()

    code = _build(args.mode, icon)
    if code != 0:
        print("PyInstaller 构建失败")
        return code

    _post_process(args.mode)
    if args.mode == "onedir" and not args.no_zip:
        _zip_portable()
    print("构建完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
