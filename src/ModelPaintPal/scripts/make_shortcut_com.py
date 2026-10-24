"""用 Windows 原生 COM（IShellLinkW + IPersistFile::Save）创建 .lnk。

这是资源管理器「发送到 → 桌面快捷方式」的同一条代码路径，产物与系统生成的
完全一致，避免手写二进制在字段细节上踩坑。优先用本脚本；手写 build_link
只作为无 COM 环境的兜底。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shell_resolve_lnk import (  # noqa: E402
    CLSID_ShellLink, IID_IPersistFile, IID_IShellLinkW, wrap, _QI, _Release,
)

# IShellLinkW 虚表：0-2 IUnknown，19=SetPath，7=SetWorkingDirectory，16=SetIconLocation，6=SetDescription
_SetPath = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p := ctypes.c_void_p, ctypes.c_wchar_p)
_SetWorkDir = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_wchar_p)
_SetIconLoc = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
_SetDesc = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_wchar_p)
# IPersistFile 虚表：6 = Save(pszFileName, fRemember)
_Save = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)

ole32 = ctypes.oledll.ole32


def create_lnk(target: str, lnk_path: str, workdir: str = "", icon: str = "",
               description: str = "") -> None:
    ole32.CoInitializeEx(None, 0x2)
    psl = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(CLSID_ShellLink), None, 1,
                                ctypes.byref(IID_IShellLinkW), ctypes.byref(psl))
    if hr != 0:
        raise OSError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08X}")
    try:
        hr = wrap(_SetPath, psl, 19)(psl, target)
        if hr != 0:
            raise OSError(f"SetPath failed: 0x{hr & 0xFFFFFFFF:08X}")
        if workdir:
            wrap(_SetWorkDir, psl, 7)(psl, workdir)
        if icon:
            wrap(_SetIconLoc, psl, 16)(psl, icon, 0)
        if description:
            wrap(_SetDesc, psl, 6)(psl, description)

        ppf = ctypes.c_void_p()
        hr = wrap(_QI, psl, 0)(psl, ctypes.byref(IID_IPersistFile), ctypes.byref(ppf))
        if hr != 0:
            raise OSError(f"QI(IPersistFile) failed: 0x{hr & 0xFFFFFFFF:08X}")
        try:
            hr = wrap(_Save, ppf, 6)(ppf, lnk_path, True)
            if hr != 0:
                raise OSError(f"IPersistFile::Save failed: 0x{hr & 0xFFFFFFFF:08X}")
        finally:
            wrap(_Release, ppf, 2)(ppf)
    finally:
        wrap(_Release, psl, 2)(psl)


if __name__ == "__main__":
    home = os.path.expandvars(r"%LOCALAPPDATA%\Programs\ModelPaintPal")
    exe = os.path.join(home, "ModelPaintPal.exe")
    if not os.path.exists(exe):
        print(f"ERROR: target exe not found: {exe}")
        raise SystemExit(1)
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_com.lnk")
    create_lnk(exe, out, workdir=home, icon=exe,
               description="ModelPaintPal - 3D 打印模型涂装配色助手")
    size = os.path.getsize(out)
    print(f"WROTE {out} ({size} bytes)")
    head = open(out, "rb").read(2)
    print("first two bytes:", head.hex(), "(lnk header 应为 4c00)")
