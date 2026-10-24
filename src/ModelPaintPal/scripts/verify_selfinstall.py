r"""触发一次应用启动，让它在真实环境里自装桌面快捷方式，然后校验结果。"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import time

EXE = r"C:\Users\xukunhang\AppData\Local\Programs\ModelPaintPal\ModelPaintPal.exe"
LNK = r"D:\Desktop\3D 打印模型涂装配色助手.lnk"


def process_running(name):
    k32 = ctypes.windll.kernel32
    arr = (wt.DWORD * 4096)()
    needed = wt.DWORD()
    ctypes.windll.psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed))
    for pid in arr[: needed.value // ctypes.sizeof(wt.DWORD)]:
        if not pid:
            continue
        h = k32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not h:
            continue
        buf = ctypes.create_unicode_buffer(260)
        n = wt.DWORD(260)
        ctypes.windll.psapi.GetModuleFileNameExW(h, None, buf, ctypes.byref(n))
        k32.CloseHandle(h)
        if name.lower() in buf.value.lower():
            return pid
    return None


print("before:", os.path.getsize(LNK) if os.path.exists(LNK) else "missing", "bytes")
os.startfile(EXE)
print("app launched")
time.sleep(10)
print("app running pid:", process_running("ModelPaintPal.exe"))
print("after:", os.path.getsize(LNK) if os.path.exists(LNK) else "missing", "bytes")

# 解析新 lnk 的结构特征
if os.path.exists(LNK):
    d = open(LNK, "rb").read()
    fl = struct.unpack_from("<I", d, 20)[0]
    print("link_flags 0x%X  HasIDList=%s  IsUnicode=%s" % (fl, bool(fl & 1), bool(fl & 0x80)))
    if fl & 1:
        idsz = struct.unpack_from("<H", d, 76)[0]
        print("IDList size:", idsz)
