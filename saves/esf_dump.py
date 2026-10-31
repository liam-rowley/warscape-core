#!/usr/bin/env python3
"""esf_dump.py: read-only reader for Warscape ESF files (saves, startpos), offset based, no tree objects. Stdlib only.

purpose: print the record skeleton, every subtree under a record path, or one grep-able line per node of an ESF save or startpos
usage: python3 -I saves/core/esf_dump.py tree FILE [--depth N] | dump FILE --path A/B/C [--max-array N] [--limit-lines N] | lines FILE > FILE.tree.txt
when: looking inside a save before a diff or a recipe (record names, child positions @N, values); esf_edit.py writes, esf_diff.py compares
not-a-verb: a game-agnostic ESF codec run on the PC against saves outside the repo (warscape-core candidate, D10)

Ported from empire-remastered rml_mod/tools/db/esf_dump.py (J14): the earlier remaster's own `slots` command is dropped.
Format (ABCA startpos / ABCE save): u32 magic, u32 0, u32 timestamp, u32 offset of the name table; root node at 16.
Node tags: 0x01 bool, 0x02 i8, 0x03 i16, 0x04 i32, 0x05 i64, 0x06 u8, 0x07 u16, 0x08 u32, 0x09 u64,
0x0a f32, 0x0b f64, 0x0c xy f32, 0x0d xyz f32, 0x0e utf16 (u16 len), 0x0f ascii (u16 len), 0x10 angle u16,
0x40|t = packed array of t (u32 end offset), 0x80 record (u16 name, u8 version, u32 end),
0x81 record array (u16 name, u8 version, u32 end, u32 count, then per item u32 end + children).
"""
import argparse
import struct
import sys

FIX = {0x01: ('<?', 1), 0x02: ('<b', 1), 0x03: ('<h', 2), 0x04: ('<i', 4), 0x05: ('<q', 8), 0x06: ('<B', 1),
       0x07: ('<H', 2), 0x08: ('<I', 4), 0x09: ('<Q', 8), 0x0a: ('<f', 4), 0x0b: ('<d', 8),
       0x0c: ('<2f', 8), 0x0d: ('<3f', 12), 0x10: ('<H', 2)}
TAGN = {0x01: 'bool', 0x02: 'i8', 0x03: 'i16', 0x04: 'i32', 0x05: 'i64', 0x06: 'u8', 0x07: 'u16', 0x08: 'u32', 0x09: 'u64',
        0x0a: 'f32', 0x0b: 'f64', 0x0c: 'xy', 0x0d: 'xyz', 0x0e: 'utf16', 0x0f: 'ascii', 0x10: 'angle'}
MAGICS = {0xABCA: 'startpos', 0xABCE: 'save'}


def known(tag):
    """True when the layout of this tag is known: a scalar, a string, a packed array of a fixed-size scalar, or a record"""
    return tag in FIX or tag in (0x0e, 0x0f, 0x80, 0x81) or (0x41 <= tag <= 0x50 and (tag & 0x3f) in FIX)


class Esf:
    def __init__(self, path):
        with open(path, 'rb') as f:
            self.b = f.read()
        self.magic, _, self.ts, off = struct.unpack_from('<IIII', self.b, 0)
        n = struct.unpack_from('<H', self.b, off)[0]
        o = off + 2
        self.names = []
        for _ in range(n):
            ln = struct.unpack_from('<H', self.b, o)[0]
            self.names.append(self.b[o + 2:o + 2 + ln].decode('latin1'))
            o += 2 + ln

    def value(self, o):
        """read a non-record node at o -> (value, next offset)"""
        b = self.b
        t = b[o]
        if t in FIX:
            fmt, n = FIX[t]
            v = struct.unpack_from(fmt, b, o + 1)
            return (v[0] if len(v) == 1 else tuple(round(x, 3) for x in v)), o + 1 + n
        if t == 0x0e:
            n = struct.unpack_from('<H', b, o + 1)[0]
            return b[o + 3:o + 3 + 2 * n].decode('utf-16-le', 'replace'), o + 3 + 2 * n
        if t == 0x0f:
            n = struct.unpack_from('<H', b, o + 1)[0]
            return b[o + 3:o + 3 + n].decode('latin1'), o + 3 + n
        if 0x41 <= t <= 0x50:
            end = struct.unpack_from('<I', b, o + 1)[0]
            et = t & 0x3f
            if et in FIX:
                fmt, n = FIX[et]
                cnt = (end - o - 5) // n
                vals = [struct.unpack_from(fmt, b, o + 5 + i * n) for i in range(cnt)]
                vals = [v[0] if len(v) == 1 else v for v in vals]
            else:
                vals = ['<array type %#x, %d bytes>' % (t, end - o - 5)]
            return vals, end
        raise ValueError('unknown tag %#x at offset %d' % (t, o))

    def children(self, o, end):
        """iterate (kind, name, payload) for nodes in [o, end); kind 'rec' -> (start, end, ver), 'arr' -> ([(start, end)], ver)"""
        b = self.b
        while o < end:
            t = b[o]
            if t == 0x80:
                ni, ver, e = struct.unpack_from('<HBI', b, o + 1)
                yield ('rec', self.names[ni], (o + 8, e, ver))
                o = e
            elif t == 0x81:
                ni, ver, e, cnt = struct.unpack_from('<HBII', b, o + 1)
                items = []
                p = o + 12
                for _ in range(cnt):
                    ie = struct.unpack_from('<I', b, p)[0]
                    items.append((p + 4, ie))
                    p = ie
                yield ('arr', self.names[ni], (items, ver))
                o = e
            else:
                v, o2 = self.value(o)
                yield ('val', None, v)
                o = o2


def tree(esf, o, end, depth, maxd, out):
    counts = 0
    for kind, name, p in esf.children(o, end):
        if kind == 'val':
            counts += 1
        elif kind == 'rec':
            out.append('  ' * depth + '%s (v%d, %d bytes)' % (name, p[2], p[1] - p[0]))
            if depth + 1 < maxd:
                tree(esf, p[0], p[1], depth + 1, maxd, out)
        else:
            items, ver = p
            out.append('  ' * depth + '%s[%d] (v%d)' % (name, len(items), ver))
            if items and depth + 1 < maxd:
                tree(esf, items[0][0], items[0][1], depth + 1, maxd, out)
    if counts:
        out.append('  ' * depth + '<%d values>' % counts)


def dump(esf, o, end, depth, out, limit, maxarr):
    for i, (kind, name, p) in enumerate(esf.children(o, end)):
        if len(out) > limit:
            return
        if kind == 'val':
            v = p
            if isinstance(v, list) and len(v) > maxarr:
                v = v[:maxarr] + ['... %d total' % len(p)]
            out.append('  ' * depth + '@%d %r' % (i, v))
        elif kind == 'rec':
            out.append('  ' * depth + '@%d %s {' % (i, name))
            dump(esf, p[0], p[1], depth + 1, out, limit, maxarr)
            out.append('  ' * depth + '}')
        else:
            items, ver = p
            out.append('  ' * depth + '@%d %s[%d] [' % (i, name, len(items)))
            for j, (a, b) in enumerate(items):
                out.append('  ' * (depth + 1) + '#%d' % j)
                dump(esf, a, b, depth + 2, out, limit, maxarr)
                if len(out) > limit:
                    return
            out.append('  ' * depth + ']')


def find(esf, o, end, path, want, hits):
    """append (kind, name path, payload) for every record or record array whose name path ends with want"""
    for kind, name, p in esf.children(o, end):
        if kind == 'val':
            continue
        np = path + [name]
        if np[-len(want):] == want:
            hits.append((kind, np, p))
            continue
        if kind == 'rec':
            find(esf, p[0], p[1], np, want, hits)
        else:
            for a, b in p[0]:
                find(esf, a, b, np, want, hits)


COLLAPSE = {'QUAD_TREE_BIT_ARRAY'}  # fog-of-war bit trees: millions of lines, no meaning for edits


def lines(esf, o, end, path, w, cut=120):
    """stream one line per node: path (NAME[i] for array items, NAME#n for repeated sibling records, @k = child index), tag, value"""
    seen = {}
    for i, (kind, name, p) in enumerate(esf.children(o, end)):
        if kind == 'val':
            r = repr(p)
            if len(r) > cut:
                r = r[:cut] + '...(%d)' % (len(p) if isinstance(p, (list, str)) else 0)
            w('%s@%d\t%s\n' % (path, i, r))
        elif kind == 'rec':
            seen[name] = seen.get(name, 0) + 1
            q = '%s/%s' % (path, name) if seen[name] == 1 else '%s/%s#%d' % (path, name, seen[name] - 1)
            if name in COLLAPSE:
                w('%s\trec v%d %d bytes (collapsed)\n' % (q, p[2], p[1] - p[0]))
                continue
            w('%s\trec v%d\n' % (q, p[2]))
            lines(esf, p[0], p[1], q, w, cut)
        else:
            items, ver = p
            q = '%s/%s' % (path, name)
            w('%s\tarr v%d n=%d\n' % (q, ver, len(items)))
            for j, (x, y) in enumerate(items):
                lines(esf, x, y, '%s[%d]' % (q, j), w, cut)


def root_span(esf):
    """(root record name, first child offset, end offset); the root node sits at 16"""
    b = esf.b
    if b[16] != 0x80:
        raise ValueError('no record at offset 16 (tag %#x): not an ESF save or startpos' % b[16])
    ni, ver, e = struct.unpack_from('<HBI', b, 17)
    return esf.names[ni], 16 + 8, e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['tree', 'dump', 'lines'])
    ap.add_argument('file')
    ap.add_argument('--depth', type=int, default=4)
    ap.add_argument('--path', help='dump: record path suffix, names joined by / (e.g. WORLD/FACTION_ARRAY)')
    ap.add_argument('--limit-lines', type=int, default=200000)
    ap.add_argument('--max-array', type=int, default=64)
    ap.add_argument('--prefix', default='CAMPAIGN_ENV/CAMPAIGN_MODEL', help='lines: path below the root shortened to ~')
    a = ap.parse_args()
    esf = Esf(a.file)
    rn, o, e = root_span(esf)
    if a.cmd == 'lines':
        sys.setrecursionlimit(10000)
        out = sys.stdout
        pre = rn + '/' + a.prefix
        out.write('# %s magic=%#x root=%s\n# path prefix ~ = %s; %s collapsed\n' % (a.file, esf.magic, rn, pre, ','.join(sorted(COLLAPSE))))
        lines(esf, o, e, rn, lambda t: out.write('~' + t[len(pre):] if t.startswith(pre) else t))
        return
    out = ['# %s magic=%#x root=%s' % (a.file, esf.magic, rn)]
    if a.cmd == 'tree':
        tree(esf, o, e, 0, a.depth, out)
    else:
        if not a.path:
            sys.exit('dump needs --path')
        hits = []
        find(esf, o, e, [rn], a.path.split('/'), hits)
        out.append('# %d hits for %s' % (len(hits), a.path))
        for kind, np, p in hits:
            out.append('## ' + '/'.join(np))
            if kind == 'rec':
                dump(esf, p[0], p[1], 0, out, a.limit_lines, a.max_array)
            else:
                for i, (x, y) in enumerate(p[0]):
                    out.append('#%d' % i)
                    dump(esf, x, y, 1, out, a.limit_lines, a.max_array)
            if len(out) > a.limit_lines:
                out.append('... truncated')
                break
    sys.stdout.write('\n'.join(out) + '\n')


if __name__ == '__main__':
    main()
