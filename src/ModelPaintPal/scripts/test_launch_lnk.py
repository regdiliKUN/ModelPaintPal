r"""真实双击测试：os.startfile(.lnk) → 检测 ModelPaintPal.exe 进程。

注意：这个测试必须以脚本文件运行，不能 python -c 内联——
MSYS/Git Bash 会把命令行里的 `D:\...` 改写成 `D:/...`，
ShellExecute 对正斜杠的 .lnk 路径会误报 1155「没有应用程序关联」。
"""
import ctypes
import ctypes.wintypes as wt
import os
import time

LNK = os.path.join("D:\\", "Desktop", "3D 打印模型涂装配色助手.lnk")
EXE_NAME = "ModelPaintPal.exe"


def running_pids():
    k32 = ctypes.windll.kernel32
    arr = (wt.DWORD * 4096)()
    needed = wt.DWORD()
    ctypes.windll.psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed))
    out = []
    for pid in arr[: needed.value // ctypes.sizeof(wt.DWORD)]:
        if not pid:
            continue
        h = k32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not h:
            continue
        name = ctypes.create_unicode_buffer(260)
        n = wt.DWORD(260)
        ctypes.windll.psapi.GetModuleFileNameExW(h, None, name, ctypes.byref(n))
        k32.CloseHandle(h)
        if EXE_NAME in name.value:
            out.append((pid, name.value))
    return out


def main():
    print("lnk path in python:", LNK)
    print("exists:", os.path.exists(LNK))
    try:
        os.startfile(LNK)
        print("startfile OK")
    except OSError as exc:
        print("startfile FAIL:", exc)
        return 1
    time.sleep(6)
    pids = running_pids()
    if pids:
        print("LAUNCH SUCCESS:", pids)
        return 0
    print("LAUNCH NOT DETECTED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
