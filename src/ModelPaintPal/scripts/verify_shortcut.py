"""校验桌面 .lnk 的二进制结构，并确认它指向已安装的 exe。

用法：
    python scripts/verify_shortcut.py                    # 自动解析真实桌面目录
    python scripts/verify_shortcut.py <某个.lnk 路径>    # 校验指定文件

桌面目录必须走注册表解析（同 make_shortcut.resolve_desktop）：桌面被重定向到
D:\\Desktop 或由 OneDrive 接管时，`<home>/Desktop` 是空目录，会在那里白找一圈。
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_shortcut import resolve_desktop  # noqa: E402

DEFAULT_NAME = "3D 打印模型涂装配色助手.lnk"


def read_local_path(data: bytes) -> str:
    """LINKINFO 的 LocalBasePath 是 ANSI（系统代码页），不是 UTF-16。"""
    header_size = struct.unpack_from("<I", data, 0)[0]
    li = header_size
    local_path_off = struct.unpack_from("<I", data, li + 16)[0]
    start = li + local_path_off
    end = data.index(b"\x00", start)
    return data[start:end].decode("mbcs")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    lnk = Path(argv[0]) if argv else resolve_desktop() / DEFAULT_NAME
    if not lnk.exists():
        print(f"ERROR: 快捷方式不存在: {lnk}")
        return 1

    data = lnk.read_bytes()
    print("file:", lnk)
    print("file size:", len(data))
    print("header_size:", struct.unpack_from("<I", data, 0)[0],
          "link_flags: 0x%X" % struct.unpack_from("<I", data, 20)[0])

    target = read_local_path(data)
    print("Resolved target path:", target)
    # TerminalBlock：ExtraData 段必须以 4 字节全 0 收尾，缺了 Explorer 会判损坏
    print("terminal block:", "OK" if data[-4:] == b"\x00\x00\x00\x00" else "MISSING（会打不开）")

    expected = str(Path.home() / "AppData" / "Local" / "Programs" / "ModelPaintPal" / "ModelPaintPal.exe")
    ok = (target.lower() == expected.lower() and Path(target).exists()
          and data[-4:] == b"\x00\x00\x00\x00")
    print("MATCH:", ok)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
