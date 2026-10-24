"""对照实验：用同一个 build_link 生成指向 notepad 的 .lnk，验证 builder 本身是否可用。"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from make_shortcut import build_link  # noqa: E402


def running(names):
    k32 = ctypes.windll.kernel32
    arr = (wt.DWORD * 4096)()
    needed = wt.DWORD()
    ctypes.windll.psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed))
    found = []
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
        low = name.value.lower()
        if any(nm in low for nm in names):
            found.append((pid, name.value))
    return found


def main():
    tmp = tempfile.mkdtemp(prefix="mpal_lnk_")
    variants = {
        "full": dict(workdir=os.path.dirname(os.__file__), icon="notepad.exe"),
        "bare": dict(workdir="", icon=""),
    }
    targets = {"full": r"C:\Windows\System32\notepad.exe", "bare": r"C:\Windows\System32\notepad.exe"}
    for tag, kw in variants.items():
        lnk = os.path.join(tmp, f"test_{tag}.lnk")
        data = build_link(targets[tag], kw["workdir"], kw["icon"], f"builder test {tag}")
        with open(lnk, "wb") as f:
            f.write(data)
        print(f"[{tag}] wrote {lnk} ({len(data)} bytes)")
        try:
            os.startfile(lnk)
            print(f"[{tag}] startfile OK")
        except OSError as exc:
            print(f"[{tag}] startfile FAIL:", exc)
            continue
        time.sleep(4)
        pids = running(["notepad.exe"])
        print(f"[{tag}] notepad detected:", pids)
        if not pids:
            continue
        for pid, _ in pids:
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x0001, False, pid)
            if h:
                k32.TerminateProcess(h, 0)
                k32.CloseHandle(h)
        break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
