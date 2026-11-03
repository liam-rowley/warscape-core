"""Warscape bitmap font (.cuf) reader / writer (the same CUF0 format in the earlier and the later game, J6).

purpose: parse and re-serialise CUF0 bitmap fonts byte for byte (header metrics, cmap, glyphs, pair-advance table)
usage: python3 discovery/cuf.py FILE.cuf ...  (round-trip self test)   |   from cuf import Cuf; Cuf.parse(bytes).serialise()
when: reading or regenerating engine-drawn fonts (J6 fonts pass; UI_PIPELINE engine text)
not-a-verb: a binary codec library, ported unchanged from empire-remastered ui_scale_mod/tools/cuf.py

Layout (all little-endian), fully accounted for — every byte of all 43 vanilla files round-trips:

  0x00  char[4]   "CUF0"
  0x04  i16[11]   header metrics h0..h10 (see HEADER_NAMES; meanings partly inferred)
  0x1A  u16       nglyphs (419 in every vanilla file)
  0x1C  u32       bitmap_size (sum of w*h over glyphs)
  0x20  u16[65536] cmap: UTF-16 code unit -> glyph index (0xFFFF = none)
        glyph[n]   (i8 top, u8 advance, u8 w, u8 h)   top = rows above the baseline (-128 = no bitmap)
        u32[n]     offset of each glyph's bitmap inside the bitmap block
        u8[bitmap_size]  8-bit coverage, row-major, w*h per glyph, glyphs cropped to ink
        u16 N, u16 first_char      pair table covers glyphs cmap[first_char] .. +N-1 (vanilla: 350, '!')
        u8[N][N]   pair advance: pen step from glyph L's bitmap origin to glyph R's (row = L, col = R)
"""
import struct, sys

HEADER_NAMES = ['ascent', 'cap_height', 'size', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'size2', 'line_height']
CMAP_OFF = 0x20
CMAP_LEN = 65536


class Glyph:
    __slots__ = ('top', 'adv', 'w', 'h', 'bitmap')

    def __init__(self, top, adv, w, h, bitmap=b''):
        self.top, self.adv, self.w, self.h, self.bitmap = top, adv, w, h, bitmap

    def __repr__(self):
        return f'Glyph(top={self.top}, adv={self.adv}, w={self.w}, h={self.h})'


class Cuf:
    def __init__(self):
        self.header = [0] * 11
        self.cmap = [0xFFFF] * CMAP_LEN
        self.glyphs = []
        self.offsets = None          # kept only to reproduce vanilla ordering quirks byte-exactly
        self.pair_first = 33
        self.pairs = []              # list of bytearray rows

    # ---- io ---------------------------------------------------------------------------------
    @classmethod
    def load(cls, path):
        with open(path, 'rb') as fh:
            return cls.parse(fh.read())

    @classmethod
    def parse(cls, d):
        c = cls()
        if d[:4] != b'CUF0':
            raise ValueError('not a CUF0 file')
        *h, n, bsz = struct.unpack_from('<11hHI', d, 4)
        c.header = list(h)
        c.cmap = list(struct.unpack_from(f'<{CMAP_LEN}H', d, CMAP_OFF))
        o = CMAP_OFF + 2 * CMAP_LEN
        recs = [struct.unpack_from('<bBBB', d, o + 4 * i) for i in range(n)]
        o += 4 * n
        offs = struct.unpack_from(f'<{n}I', d, o)
        o += 4 * n
        bmp = d[o:o + bsz]
        o += bsz
        for (t, a, w, hh), off in zip(recs, offs):
            c.glyphs.append(Glyph(t, a, w, hh, bytes(bmp[off:off + w * hh])))
        c.offsets = list(offs)
        N, c.pair_first = struct.unpack_from('<HH', d, o)
        o += 4
        c.pairs = [bytearray(d[o + r * N:o + (r + 1) * N]) for r in range(N)]
        o += N * N
        if o != len(d):
            raise ValueError(f'{len(d) - o} trailing bytes')
        return c

    def serialise(self, keep_offsets=False):
        n = len(self.glyphs)
        out = bytearray(b'CUF0')
        bmp = bytearray()
        offs = []
        for i, g in enumerate(self.glyphs):
            assert len(g.bitmap) == g.w * g.h, (i, g)
            if keep_offsets and self.offsets and len(self.offsets) == n:
                offs.append(self.offsets[i])
                end = self.offsets[i] + len(g.bitmap)
                if len(bmp) < end:
                    bmp.extend(b'\0' * (end - len(bmp)))
                bmp[self.offsets[i]:end] = g.bitmap
            elif not g.bitmap and g.adv == 0:
                offs.append(0)               # vanilla quirk: empty zero-advance glyphs point at 0
            else:
                offs.append(len(bmp))
                bmp += g.bitmap
        out += struct.pack('<11hHI', *self.header, n, len(bmp))
        out += struct.pack(f'<{CMAP_LEN}H', *self.cmap)
        for g in self.glyphs:
            out += struct.pack('<bBBB', g.top, g.adv, g.w, g.h)
        out += struct.pack(f'<{n}I', *offs)
        out += bmp
        N = len(self.pairs)
        out += struct.pack('<HH', N, self.pair_first)
        for row in self.pairs:
            assert len(row) == N
            out += row
        return bytes(out)

    def save(self, path, **kw):
        with open(path, 'wb') as fh:
            fh.write(self.serialise(**kw))

    # ---- helpers ----------------------------------------------------------------------------
    @property
    def pair_base(self):
        return self.cmap[self.pair_first]

    def glyph_index(self, ch):
        return self.cmap[ord(ch)] if ord(ch) < CMAP_LEN else 0xFFFF

    def step(self, gl, gr):
        """Pen step from glyph gl to glyph gr (None = end of string)."""
        b, N = self.pair_base, len(self.pairs)
        if gr is not None and 0 <= gl - b < N and 0 <= gr - b < N:
            return self.pairs[gl - b][gr - b]
        return self.glyphs[gl].adv

    def chars(self):
        """{glyph index: first code unit mapped to it}"""
        inv = {}
        for cu, gi in enumerate(self.cmap):
            if gi != 0xFFFF:
                inv.setdefault(gi, cu)
        return inv

    def render(self, text, use_pairs=True, pad=4):
        """Render a line with PIL ('L' image) for eyeballing spacing."""
        from PIL import Image
        gis = [self.glyph_index(ch) for ch in text]
        gis = [g for g in gis if g != 0xFFFF]
        lh = self.header[10]
        asc = self.header[0]
        xs, x = [], pad
        for i, g in enumerate(gis):
            xs.append(x)
            nxt = gis[i + 1] if i + 1 < len(gis) else None
            x += self.step(g, nxt) if use_pairs else self.glyphs[g].adv
        img = Image.new('L', (x + pad + 40, lh + 2 * pad), 0)
        px = img.load()
        for g, x0 in zip(gis, xs):
            gl = self.glyphs[g]
            if gl.top == -128:
                continue
            y0 = pad + asc - gl.top
            for yy in range(gl.h):
                for xx in range(gl.w):
                    v = gl.bitmap[yy * gl.w + xx]
                    X, Y = x0 + xx, y0 + yy
                    if 0 <= X < img.width and 0 <= Y < img.height:
                        px[X, Y] = max(px[X, Y], v)
        return img


def _selftest(paths):
    bad = 0
    for p in paths:
        d = open(p, 'rb').read()
        c = Cuf.parse(d)
        same_keep = c.serialise(keep_offsets=True) == d
        same_pack = c.serialise() == d
        if not same_keep:
            bad += 1
        print(f'{p}: glyphs={len(c.glyphs)} header={c.header} pairs={len(c.pairs)}@{c.pair_first} '
              f'roundtrip={"exact" if same_pack else ("exact(offsets kept)" if same_keep else "FAIL")}')
    print('failures:', bad)


if __name__ == '__main__':
    _selftest(sys.argv[1:])
