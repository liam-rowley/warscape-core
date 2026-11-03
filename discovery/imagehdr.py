"""Image header readers (stdlib): width, height, mip count and pixel format of DDS, TGA, PNG and JPG bytes.

purpose: read w, h, mips and pixel format (dxt5, bgra8, rgb8, ...) from the first bytes of a DDS, TGA, PNG or JPG file, without decoding it
usage: from imagehdr import info; info(data, ext='.dds') -> {'w': 256, 'h': 256, 'mips': 9, 'pixel': 'dxt5'} or None   (library)
when: the J7 asset index (every tga, dds, png and jpg gets its dimensions) and the registry's format field; ported from empire-remastered ui_scale_mod/asset_inventory/inv_headers.py dds_info
not-a-verb: a library module imported by discovery/assets.py
"""
import struct

EXTS = ('.dds', '.tga', '.png', '.jpg', '.jpeg')
PNG_TYPES = {0: 'l', 2: 'rgb', 3: 'p', 4: 'la', 6: 'rgba'}
TGA_RLE = 8


def dds(b):
    if len(b) < 128 or b[:4] != b'DDS ':
        return None
    h, w = struct.unpack_from('<II', b, 12)
    mips = struct.unpack_from('<I', b, 28)[0] or 1
    pf_flags, fourcc, bits = struct.unpack_from('<I4sI', b, 80)
    amask = struct.unpack_from('<I', b, 104)[0]
    if pf_flags & 0x4:
        pixel = fourcc.rstrip(b'\0').decode('latin-1').lower() or 'fourcc0'
    elif pf_flags & 0x40:
        pixel = {32: 'bgra8' if amask else 'bgrx8', 24: 'bgr8', 16: 'bgr5a1' if amask else 'bgr565'}.get(bits, f'rgb{bits}')
    elif pf_flags & 0x20000:
        pixel = 'la8' if amask else 'l8'
    elif pf_flags & 0x2:
        pixel = 'a8'
    else:
        pixel = f'pf{pf_flags:x}'
    return {'w': w, 'h': h, 'mips': mips, 'pixel': pixel}


def tga(b):
    if len(b) < 18:
        return None
    idlen, cmap, kind = b[0], b[1], b[2]
    w, h, bpp, desc = struct.unpack_from('<HHBB', b, 12)
    base = kind & ~TGA_RLE
    if base not in (1, 2, 3) or cmap > 1 or not w or not h or bpp not in (8, 15, 16, 24, 32):
        return None
    if base == 1:
        pixel = 'p8'
    elif base == 3:
        pixel = 'l8'
    else:
        pixel = {32: 'bgra8', 24: 'bgr8', 16: 'bgr5a1', 15: 'bgr5'}.get(bpp, f'bgr{bpp}')
    return {'w': w, 'h': h, 'mips': 1, 'pixel': pixel + ('_rle' if kind & TGA_RLE else '')}


def png(b):
    if len(b) < 26 or b[:8] != b'\x89PNG\r\n\x1a\n' or b[12:16] != b'IHDR':
        return None
    w, h, depth, ctype = struct.unpack_from('>IIBB', b, 16)
    return {'w': w, 'h': h, 'mips': 1, 'pixel': f'{PNG_TYPES.get(ctype, "c%d" % ctype)}{depth}'}


def jpg(b):
    if b[:2] != b'\xff\xd8':
        return None
    o = 2
    while o + 4 <= len(b):
        if b[o] != 0xFF:
            return None
        m = b[o + 1]
        if m == 0xFF:
            o += 1
            continue
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            o += 2
            continue
        n = struct.unpack_from('>H', b, o + 2)[0]
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            if o + 10 > len(b):
                return None
            h, w, comps = struct.unpack_from('>HHB', b, o + 5)
            return {'w': w, 'h': h, 'mips': 1, 'pixel': {1: 'l8', 3: 'ycc8', 4: 'cmyk8'}.get(comps, f'c{comps}')}
        o += 2 + n
    return None


READERS = {'.dds': dds, '.tga': tga, '.png': png, '.jpg': jpg, '.jpeg': jpg}


def info(b, ext):
    r = READERS.get(ext.lower())
    try:
        return r(b) if r else None
    except struct.error:
        return None
