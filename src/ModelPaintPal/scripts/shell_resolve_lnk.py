"""用 Windows shell 的真实代码路径（IShellLinkW + IPersistFile）加载 .lnk 并取回目标。

这就是资源管理器双击快捷方式时走的解析逻辑；它能加载成功，文件就是合法的。
不依赖 pywin32，纯 ctypes 手写 COM 调用。
"""
import ctypes
from ctypes import Structure, byref, c_void_p, c_wchar_p
import sys

ole32 = ctypes.oledll.ole32


class GUID(Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_str(cls, s):
        import uuid

        return cls.from_buffer_copy(uuid.UUID(s).bytes_le)


CLSID_ShellLink = GUID.from_str("00021401-0000-0000-C000-000000000046")
IID_IShellLinkW = GUID.from_str("000214F9-0000-0000-C000-000000000046")
IID_IPersistFile = GUID.from_str("0000010B-0000-0000-C000-000000000046")

# IUnknown
_QI = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(c_void_p))
_AddRef = ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)
_Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)
# IPersistFile
_Load = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, c_wchar_p, ctypes.c_ulong)
# IShellLinkW::GetPath  (第 3 个虚函数之后的偏移：IUnknown 3 + GetPath 是 IShellLinkW 第 1 个方法)
_GetPath = ctypes.WINFUNCTYPE(
    ctypes.HRESULT, c_void_p, c_wchar_p, ctypes.c_int,
    ctypes.POINTER(ctypes.c_int), ctypes.c_ulong)


def vtbl(obj, index):
    """取 COM 对象虚表第 index 个函数指针。"""
    vtbl_ptr = ctypes.cast(obj, ctypes.POINTER(c_void_p)).contents
    table = ctypes.cast(vtbl_ptr, ctypes.POINTER(c_void_p))
    return table[index]


def wrap(proto, obj, index):
    fn = ctypes.cast(vtbl(obj, index), proto)
    fn.__name__ = proto.__name__
    return fn


def load_lnk(path: str) -> str:
    ole32.CoInitializeEx(None, 0x2)  # APARTMENTTHREADED
    psl = c_void_p()
    hr = ole32.CoCreateInstance(byref(CLSID_ShellLink), None, 1,  # CLSCTX_INPROC_SERVER
                                byref(IID_IShellLinkW), byref(psl))
    if hr != 0:
        raise OSError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08X}")
    try:
        ppf = c_void_p()
        hr = wrap(_QI, psl, 0)(psl, byref(IID_IPersistFile), byref(ppf))
        if hr != 0:
            raise OSError(f"QI(IPersistFile) failed: 0x{hr & 0xFFFFFFFF:08X}")
        try:
            # IPersistFile 虚表：0-2 IUnknown，3=GetClassID，4=IsDirty，5=Load
            hr = wrap(_Load, ppf, 5)(ppf, path, 0)   # STGM_READ
            if hr != 0:
                raise OSError(f"IPersistFile::Load failed: 0x{hr & 0xFFFFFFFF:08X}")
        finally:
            wrap(_Release, ppf, 2)(ppf)

        buf = ctypes.create_unicode_buffer(1024)
        # IShellLinkW 虚表：0-2 IUnknown，3=GetIDList … 19=SetPath，20=GetPath
        hr = wrap(_GetPath, psl, 20)(psl, buf, 1024, None, 0)
        if hr != 0:
            raise OSError(f"IShellLinkW::GetPath failed: 0x{hr & 0xFFFFFFFF:08X}")
        return buf.value
    finally:
        wrap(_Release, psl, 2)(psl)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        try:
            target = load_lnk(p)
            print(f"{p}\n  -> shell 解析成功: {target}")
        except OSError as exc:
            print(f"{p}\n  -> shell 解析失败: {exc}")
            sys.exit(1)
