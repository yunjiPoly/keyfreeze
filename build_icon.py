"""Generate a KeyFreeze .ico file (padlock) using only the standard library.

Produces a PNG-compressed ICO (supported since Windows Vista) containing several
sizes so the icon looks crisp in Explorer, on the taskbar and on the desktop.
"""

import binascii
import struct
import zlib


# --------------------------------------------------------------------------- #
# Tiny PNG encoder (RGBA, no interlace)                                       #
# --------------------------------------------------------------------------- #
def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", binascii.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    raw = b"".join(
        b"\x00" + rgba[y * width * 4:(y + 1) * width * 4]
        for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def wrap_ico(pngs: list[tuple[int, int, bytes]]) -> bytes:
    """pngs: list of (size, size, png_bytes)."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries = []
    offset = 6 + 16 * len(pngs)
    for size, _, data in pngs:
        entries.append(
            struct.pack(
                "<BBBBHHII",
                size % 256,          # width
                size % 256,          # height
                0,                   # palette
                0,                   # reserved
                1,                   # color planes
                32,                  # bits per pixel
                len(data),           # data length
                offset,              # data offset
            )
        )
        offset += len(data)
    return header + b"".join(entries) + b"".join(d for _, _, d in pngs)


# --------------------------------------------------------------------------- #
# Shape coverage tests (unit square)                                          #
# --------------------------------------------------------------------------- #
def _rounded_rect(x: float, y: float, x0, y0, x1, y1, r) -> float:
    if x < x0 or x > x1 or y < y0 or y > y1:
        return 0.0
    # Straight body (not inside any of the four corner squares).
    if (x0 + r <= x <= x1 - r) or (y0 + r <= y <= y1 - r):
        return 1.0
    # Corner squares: keep only the rounded quarter-circle.
    cx = x0 + r if x < x0 + r else x1 - r
    cy = y0 + r if y < y0 + r else y1 - r
    return 1.0 if (x - cx) ** 2 + (y - cy) ** 2 <= r * r else 0.0


def _circle(x: float, y: float, cx, cy, r) -> float:
    return 1.0 if (x - cx) ** 2 + (y - cy) ** 2 <= r * r else 0.0


def _annulus(x: float, y: float, cx, cy, r_outer, r_inner) -> float:
    d2 = (x - cx) ** 2 + (y - cy) ** 2
    return 1.0 if r_inner * r_inner <= d2 <= r_outer * r_outer else 0.0


def _rect(x: float, y: float, x0, y0, x1, y1) -> float:
    return 1.0 if x0 <= x <= x1 and y0 <= y <= y1 else 0.0


# --------------------------------------------------------------------------- #
# The padlock drawing                                                        #
# --------------------------------------------------------------------------- #
BODY = (46, 134, 222)        # blue
SHACKLE = (23, 88, 158)      # darker blue
KEYHOLE = (255, 255, 255)    # white


def _coverage(fn, px: int, py: int, size: int) -> float:
    """4x4 supersampled coverage of `fn` for one output pixel."""
    hits = 0
    for sy in range(4):
        for sx in range(4):
            x = px + (sx + 0.5) / 4.0
            y = py + (sy + 0.5) / 4.0
            hits += fn(x * size / 256.0, y * size / 256.0)
    return hits / 16.0


def _composite(dst, src_rgba, a):
    """Composite an opaque color (src_rgba, coverage a) over dst (r,g,b,a)."""
    if a <= 0.0:
        return dst
    sr, sg, sb = src_rgba
    dr, dg, db, da = dst
    out_a = a + da * (1.0 - a)
    if out_a <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)
    out_r = (sr * a + dr * da * (1.0 - a)) / out_a
    out_g = (sg * a + dg * da * (1.0 - a)) / out_a
    out_b = (sb * a + db * da * (1.0 - a)) / out_a
    return (out_r, out_g, out_b, out_a)


def draw(size: int) -> bytes:
    # Shapes, normalized to a 256x256 canvas.
    def shackle(x, y):
        return _annulus(x, y, 128, 90, 58, 34)

    def body(x, y):
        return _rounded_rect(x, y, 46, 112, 210, 224, 26)

    def keyhole_circle(x, y):
        return _circle(x, y, 128, 152, 15)

    def keyhole_stem(x, y):
        return _rect(x, y, 120, 152, 136, 192)

    buf = bytearray()
    for py in range(size):
        for px in range(size):
            s = _coverage(shackle, px, py, size)
            b = _coverage(body, px, py, size)
            kc = _coverage(keyhole_circle, px, py, size)
            ks = _coverage(keyhole_stem, px, py, size)

            px_rgba = (0.0, 0.0, 0.0, 0.0)
            px_rgba = _composite(px_rgba, SHACKLE, s)
            px_rgba = _composite(px_rgba, BODY, b)
            # The keyhole is punched out of the body.
            px_rgba = _composite(px_rgba, KEYHOLE, kc)
            px_rgba = _composite(px_rgba, KEYHOLE, ks)

            r, g, b, a = px_rgba
            buf += bytes((int(round(r)), int(round(g)), int(round(b)),
                          int(round(a * 255))))
    return bytes(buf)


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pngs = [(s, s, encode_png(s, s, draw(s))) for s in sizes]
    ico = wrap_ico(pngs)
    out = "keyfreeze.ico"
    with open(out, "wb") as f:
        f.write(ico)
    print(f"wrote {out} ({len(ico)} bytes, {len(sizes)} sizes)")


if __name__ == "__main__":
    main()
