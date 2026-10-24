# -*- coding: utf-8 -*-
"""桌面快捷方式的自安装（应用在真实用户环境下运行时执行）。

为什么放在应用里：创建「能被 shell 正常解析」的 .lnk 必须走真实的 shell COM
（IShellLinkW + IPersistFile::Save）。打包后的 exe 由用户双击启动，运行在
正常桌面环境，COM 完全可用——这是最可靠的创建时机；任何失败都静默降级，
绝不影响应用启动。

设计：
- 目标 exe 由 ``sys.executable``（frozen）推出；开发模式下跳过。
- 已有快捷方式时先用 COM ``Load`` 读取其目标，指向一致就不动（幂等）；
  读取失败（= 快捷方式损坏，比如手写二进制版本）或指向不一致 → 重建。
- 桌面目录一律走注册表解析：桌面被重定向（如 ``D:\\Desktop``）或被
  OneDrive 接管时，``<home>/Desktop`` 是个空目录，往里写用户看不见。
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SHORTCUT_NAME = "3D 打印模型涂装配色助手.lnk"

_CLSID_SHELL_LINK = "00021401-0000-0000-C000-000000000046"
_IID_ISHELL_LINK_W = "000214F9-0000-0000-C000-000000000046"
_IID_IPERSIST_FILE = "0000010B-0000-0000-C000-000000000046"

# IShellLinkW 虚表索引（0-2 为 IUnknown）：4=SetIDList，7=SetWorkingDirectory，
# 16=SetIconLocation，6=SetDescription，19=SetPath，20=GetPath。
_VTBL_SET_IDLIST = 4
_VTBL_SET_WORKDIR = 7
_VTBL_SET_ICON = 16
_VTBL_SET_DESC = 6
_VTBL_SET_PATH = 19
_VTBL_GET_PATH = 20
# IPersistFile 虚表：0-2 IUnknown，3=GetClassID，4=IsDirty，5=Load，6=Save。
_VTBL_LOAD = 5
_VTBL_SAVE = 6

_HRESULT = ctypes.HRESULT
_VOIDP = ctypes.c_void_p
_WSTR = ctypes.c_wchar_p


class _GUID(ctypes.Structure):
    """按 GUID 的内存布局（bytes_le）构造，供 byref 传给 COM。"""

    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort),
                ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def _uuid_guid(s: str) -> _GUID:
    import uuid

    return _GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


def _vtbl_func(obj, index: int, proto):
    """取 COM 对象虚表第 index 个函数并按 proto 包装。"""
    vtbl_ptr = ctypes.cast(obj, ctypes.POINTER(_VOIDP)).contents
    table = ctypes.cast(vtbl_ptr, ctypes.POINTER(_VOIDP))
    return ctypes.cast(table[index], proto)


def _qi(psl, iid: _GUID):
    """QueryInterface 包装，返回 (hr, 接口指针)。"""
    qi = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, ctypes.POINTER(_GUID),
                            ctypes.POINTER(_VOIDP))
    out = _VOIDP()
    hr = _vtbl_func(psl, 0, qi)(psl, ctypes.byref(iid), ctypes.byref(out))
    return hr, out


def _release(obj) -> None:
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, _VOIDP)
    _vtbl_func(obj, 2, release)(obj)


def resolve_desktop() -> Path:
    """返回用户「真正看到的」桌面目录（注册表优先，重定向/OneDrive 都能对）。"""
    if sys.platform != "win32":
        return Path.home() / "Desktop"

    import winreg

    candidates = []
    for sub in (
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as key:
                raw = winreg.QueryValueEx(key, "Desktop")[0]
        except OSError:
            continue
        if raw:
            candidates.append(Path(os.path.expandvars(raw)))
    profile = os.environ.get("USERPROFILE")
    if profile:
        candidates.append(Path(profile) / "Desktop")
    candidates.append(Path.home() / "Desktop")

    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def _com_load_target(lnk_path: str) -> str:
    """用真实 shell 读 .lnk 的目标路径；损坏/不可解析返回空串。"""
    ole32 = ctypes.oledll.ole32
    ole32.CoInitializeEx(None, 0x2)

    psl = _VOIDP()
    hr = ole32.CoCreateInstance(ctypes.byref(_uuid_guid(_CLSID_SHELL_LINK)), None, 1,
                                ctypes.byref(_uuid_guid(_IID_ISHELL_LINK_W)),
                                ctypes.byref(psl))
    if hr != 0 or not psl.value:
        return ""
    try:
        hr, ppf = _qi(psl, _uuid_guid(_IID_IPERSIST_FILE))
        if hr != 0 or not ppf.value:
            return ""
        try:
            load = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, _WSTR, ctypes.c_uint)
            if _vtbl_func(ppf, _VTBL_LOAD, load)(ppf, lnk_path, 0) != 0:
                return ""
            get_path = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, _WSTR, ctypes.c_int,
                                          _VOIDP, ctypes.c_uint)
            buf = ctypes.create_unicode_buffer(1024)
            if _vtbl_func(psl, _VTBL_GET_PATH, get_path)(psl, buf, 1024, None, 0) != 0:
                return ""
            return buf.value
        finally:
            _release(ppf)
    finally:
        _release(psl)


def _com_create(target: str, lnk_path: str, workdir: str, icon: str,
                description: str) -> None:
    """用真实 shell COM 创建 .lnk（IShellLinkW + IPersistFile::Save）。

    先走 SetPath；写完后回读校验，若路径没存上（个别环境对路径型 COM 方法
    有拦截）则退回 SHParseDisplayName + SetIDList（资源管理器拖拽创建快捷
    方式的同一条路径），仍失败才抛错。
    """
    ole32 = ctypes.oledll.ole32
    ole32.CoInitializeEx(None, 0x2)

    psl = _VOIDP()
    hr = ole32.CoCreateInstance(ctypes.byref(_uuid_guid(_CLSID_SHELL_LINK)), None, 1,
                                ctypes.byref(_uuid_guid(_IID_ISHELL_LINK_W)),
                                ctypes.byref(psl))
    if hr != 0 or not psl.value:
        raise OSError(f"CoCreateInstance(ShellLink) failed: 0x{hr & 0xFFFFFFFF:08X}")
    try:
        def call(vtbl_index: int, proto, *args) -> None:
            fn = _vtbl_func(psl, vtbl_index, proto)
            hr_ = fn(psl, *args)
            if hr_ != 0:
                raise OSError(f"IShellLinkW vtbl[{vtbl_index}] failed: "
                              f"0x{hr_ & 0xFFFFFFFF:08X}")

        set_path = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, _WSTR)
        call(_VTBL_SET_PATH, set_path, target)
        if workdir:
            set_work = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, _WSTR)
            call(_VTBL_SET_WORKDIR, set_work, workdir)
        if icon:
            set_icon = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, _WSTR, ctypes.c_int)
            call(_VTBL_SET_ICON, set_icon, icon, 0)
        if description:
            set_desc = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, _WSTR)
            call(_VTBL_SET_DESC, set_desc, description)

        if _com_read_path(psl) != target:
            # SetPath 没存上（被环境拦截）→ 用真实 PIDL 走 SetIDList 兜底
            logger.debug("SetPath 未生效，尝试 SHParseDisplayName + SetIDList")
            pidl = _VOIDP()
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            parse = shell32.SHParseDisplayName
            parse.argtypes = [_WSTR, _VOIDP, ctypes.POINTER(_VOIDP),
                              ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
            parse.restype = ctypes.HRESULT
            attrs = ctypes.c_uint(0)
            hr_ = parse(target, None, ctypes.byref(pidl), 0, ctypes.byref(attrs))
            if hr_ != 0 or not pidl.value:
                raise OSError(f"SHParseDisplayName failed: 0x{hr_ & 0xFFFFFFFF:08X}")
            try:
                set_idlist = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, _VOIDP)
                call(_VTBL_SET_IDLIST, set_idlist, pidl)
            finally:
                ole32.CoTaskMemFree(pidl)

        ppf = _VOIDP()
        hr, ppf = _qi(psl, _uuid_guid(_IID_IPERSIST_FILE))
        if hr != 0 or not ppf.value:
            raise OSError(f"QI(IPersistFile) failed: 0x{hr & 0xFFFFFFFF:08X}")
        try:
            save = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, _WSTR, ctypes.c_int)
            hr = _vtbl_func(ppf, _VTBL_SAVE, save)(ppf, lnk_path, 1)
            if hr != 0:
                raise OSError(f"IPersistFile::Save failed: 0x{hr & 0xFFFFFFFF:08X}")
        finally:
            _release(ppf)
    finally:
        _release(psl)


def _com_read_path(psl) -> str:
    """从（已创建的）ShellLink 对象读回路径，用于创建后自检。"""
    get_path = ctypes.WINFUNCTYPE(_HRESULT, _VOIDP, _WSTR, ctypes.c_int,
                                  _VOIDP, ctypes.c_uint)
    buf = ctypes.create_unicode_buffer(1024)
    if _vtbl_func(psl, _VTBL_GET_PATH, get_path)(psl, buf, 1024, None, 0) != 0:
        return ""
    return buf.value


def _lnk_mentions_exe(lnk_path: Path, exe_name: str) -> bool:
    """lnk 二进制里是否真的出现了 exe 文件名（IDList/路径串都算）。

    注意 IDList 可能把路径拆成多段（盘符/目录/文件各一项），所以只匹配
    文件名本身；这只作为「没写坏」的下限校验。
    """
    try:
        data = lnk_path.read_bytes()
    except OSError:
        return False
    if not exe_name:
        return False
    return (exe_name.encode("utf-16-le") in data
            or exe_name.encode("mbcs", errors="ignore") in data)


def _read_target(lnk: Path) -> str:
    """读取既有快捷方式指向的目标；读不出来返回空串（视为需要重建）。"""
    if not lnk.exists():
        return ""
    try:
        return _com_load_target(str(lnk))
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取已有快捷方式失败: %s", exc)
        return ""


def _restore_or_drop(lnk: Path, backup: bytes | None) -> None:
    """校验失败时的收尾：有备份就还原，没有才删除半成品。"""
    if backup is not None:
        try:
            lnk.write_bytes(backup)
            logger.warning("快捷方式写入后校验未通过，已还原原文件: %s", lnk)
            return
        except OSError as exc:
            logger.warning("还原原快捷方式失败: %s", exc)
    try:
        lnk.unlink()
    except OSError:
        pass
    logger.warning("快捷方式写入后校验未通过，已删除半成品（下次启动重试）: %s", lnk)


def default_lnk_path(desktop: Path | None = None) -> Path:
    return (desktop or resolve_desktop()) / SHORTCUT_NAME


def ensure_desktop_shortcut() -> Path | None:
    """确保桌面快捷方式存在且指向当前 exe；成功返回 lnk 路径，失败返回 None。

    只在打包（frozen）环境下执行；开发模式跳过。任何异常都吞掉并记日志。
    """
    try:
        if not getattr(sys, "frozen", False):
            return None
        exe = Path(sys.executable)
        if not exe.exists():
            return None
        desktop = resolve_desktop()
        lnk = default_lnk_path(desktop)
        expected = str(exe)

        # 先给已有文件留一份字节备份：万一创建后校验不通过，要把用户原来的
        # 快捷方式**还原**回去，而不是删掉——删掉等于"优化了一个便利功能，
        # 顺手弄丢了用户桌面上的入口"。
        backup = lnk.read_bytes() if lnk.exists() else None

        current = _read_target(lnk)
        if current and os.path.normcase(current) == os.path.normcase(expected):
            logger.info("桌面快捷方式已就绪: %s", lnk)
            return lnk
        # COM 读不出目标（受限环境常见）但字节里确实写着本 exe：视为已就绪，
        # 不去重建，避免每次启动都"删除-重建-校验失败"地折腾用户的桌面。
        if not current and backup is not None and _lnk_mentions_exe(lnk, exe.name):
            logger.info("桌面快捷方式已存在且指向本程序（按字节校验）: %s", lnk)
            return lnk

        lnk.parent.mkdir(parents=True, exist_ok=True)
        try:
            lnk.unlink()
        except OSError:
            pass
        _com_create(expected, str(lnk), str(exe.parent), expected,
                    "ModelPaintPal - 3D 打印模型涂装配色助手")
        # 创建后校验：既读回目标，也检查文件字节里确实提到 exe 文件名
        #（防「被环境写成了指向别处的空壳 lnk」，例如 IDList 只剩「此电脑」）。
        created = ""
        try:
            created = _com_load_target(str(lnk))
        except Exception as exc:  # noqa: BLE001
            logger.debug("创建后回读失败: %s", exc)
        ok = (created and os.path.normcase(created) == os.path.normcase(expected)) \
            or _lnk_mentions_exe(lnk, exe.name)
        if not ok:
            _restore_or_drop(lnk, backup)
            return None
        logger.info("已创建桌面快捷方式: %s -> %s", lnk, expected)
        return lnk
    except Exception as exc:  # noqa: BLE001 — 快捷方式只是便利功能，绝不影响启动
        logger.warning("创建桌面快捷方式失败（不影响使用）: %s", exc)
        return None
