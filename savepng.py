"""纯 Python PNG 写入 (RGBA), 走 Surface 原始缓冲, 无逐像素开销"""
import struct, zlib

def save_png(surf, path):
    w, h = surf.get_size()
    buf = surf.get_view("0").raw          # 内部布局: 每 4 字节一个像素 (小端 ARGB -> B,G,R,A)
    rows = []
    for y in range(h):
        row = bytearray(buf[y*w*4:(y+1)*w*4])
        # B,G,R,A -> R,G,B,A
        row[0::4], row[2::4] = row[2::4], row[0::4]
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    open(path, "wb").write(png)
