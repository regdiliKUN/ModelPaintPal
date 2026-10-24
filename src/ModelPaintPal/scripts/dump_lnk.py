"""诊断 .lnk：逐段解析并与正常文件对比。"""
from pathlib import Path
import struct
import sys


def dump(p):
    d = Path(p).read_bytes()
    print("=====", p, len(d), "bytes")
    hs = struct.unpack_from("<I", d, 0)[0]
    fl = struct.unpack_from("<I", d, 20)[0]
    print("flags 0x%X" % fl, "HasIDList", bool(fl & 1), "HasLinkInfo", bool(fl & 2),
          "HasName", bool(fl & 4), "HasRelPath", bool(fl & 8), "HasWorkDir", bool(fl & 0x10),
          "HasArgs", bool(fl & 0x20), "HasIcon", bool(fl & 0x40), "IsUnicode", bool(fl & 0x80),
          "HasExpString", bool(fl & 0x100))
    li = hs
    if fl & 1:  # HasIDList：先跳过 IDList（IDListSize 不含自身这 2 字节）
        idsz = struct.unpack_from("<H", d, li)[0]
        li = li + 2 + idsz
    size, hsz, liflags = struct.unpack_from("<III", d, li)
    print("linkinfo@%d size" % li, size, "headersize", hsz, "flags 0x%X" % liflags)
    if liflags & 1:
        voff, lpoff, cnoff, csoff = struct.unpack_from("<IIII", d, li + 12)
        print("voff", voff, "lpoff", lpoff, "cnoff", cnoff, "csoff", csoff)
        vsize, dtype, dserial, vlabeloff = struct.unpack_from("<IIII", d, li + voff)
        print("volume size", vsize, "type", dtype, "serial 0x%08X" % dserial, "labeloff", vlabeloff)
        if 0x10 <= vlabeloff and vlabeloff + 2 <= vsize:
            lab = d[li + voff + vlabeloff:li + voff + vsize - 2].decode("utf-16-le", errors="replace")
            print("volume label:", repr(lab))
        if lpoff:
            seg = d[li + lpoff:]
            txt = seg.decode("utf-16-le", errors="replace").split("\x00")[0]
            print("local base path:", repr(txt))
    pos = li + size
    order = ["NAME", "RELPATH", "WORKDIR", "ARGS", "ICON"]
    i = 0
    while pos + 2 <= len(d) - 4:
        cnt = struct.unpack_from("<H", d, pos)[0]
        if cnt == 0 or pos + 2 + 2 * cnt > len(d):
            break
        s = d[pos + 2:pos + 2 + 2 * (cnt - 1)].decode("utf-16-le", errors="replace")
        print("STR", order[i] if i < 5 else i, cnt, repr(s))
        pos += 2 + 2 * cnt
        i += 1
    print("remaining bytes:", d[pos:].hex(), "len", len(d) - pos)


if __name__ == "__main__":
    for path in sys.argv[1:]:
        dump(path)
