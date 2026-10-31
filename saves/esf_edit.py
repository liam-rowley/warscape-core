#!/usr/bin/env python3
"""esf_edit.py: byte-exact ESF (ABCA/ABCE) round-trip writer and editor for Warscape saves and startpos files. Stdlib only.

purpose: parse an ESF save into a tree, write it back byte for byte, and edit it (set a value, copy or remove a record-array item) with every end offset, count and the name table rebuilt
usage: python3 -I saves/core/esf_edit.py info|roundtrip|tree FILE... | dump FILE SPEC | set FILE SPEC @N VALUE -o OUT | copy-item|remove-item FILE SPEC INDEX [--to I] -o OUT
when: the round-trip gate on every new save (sha-equal, no unknown tag); a save needed in another state (a game's recipes import this). SPEC: [//]A/B[3]/C (Esf.select). Writes only with -o, never over the input
not-a-verb: a game-agnostic ESF codec run on the PC against saves outside the repo (warscape-core candidate, D10)

Ported from empire-remastered rml_mod/tools/db/esf_edit.py (J14). Added: unknown packed-array element types are collected
(kept raw, and `roundtrip` fails on them), a failed round trip names the first differing offset with its tag and record path,
and `-o` may not name the input. `set ... @N` and `dump` count N over all children (records too), the same @N esf_diff and
esf_dump print (the earlier remaster's `set` counted values only). Cost: about 15x the file size in RAM while a tree is held; one save per process.
"""
import argparse
import copy
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esf_dump  # noqa: E402
from esf_dump import FIX  # noqa: E402  (tag -> (struct fmt, size))


class Val:
    """scalar or packed-array node: tag + payload bytes (kept raw, so unchanged values re-encode bit-exactly)"""
    __slots__ = ('tag', 'data')

    def __init__(self, tag, data):
        self.tag, self.data = tag, data

    def get(self):
        t, d = self.tag, self.data
        if t in FIX:
            v = struct.unpack(FIX[t][0], d)
            return v[0] if len(v) == 1 else v
        if t == 0x0e:
            return d[2:].decode('utf-16-le', 'replace')
        if t == 0x0f:
            return d[2:].decode('latin1')
        if 0x41 <= t <= 0x50 and (t & 0x3f) in FIX:
            fmt, n = FIX[t & 0x3f]
            vs = [struct.unpack_from(fmt, d, i * n) for i in range(len(d) // n)]
            return [v[0] if len(v) == 1 else v for v in vs]
        return d

    def set(self, v):
        t = self.tag
        if t in FIX:
            self.data = struct.pack(FIX[t][0], *(v if isinstance(v, (tuple, list)) else (v,)))
        elif t == 0x0e:
            self.data = struct.pack('<H', len(v)) + v.encode('utf-16-le')
        elif t == 0x0f:
            self.data = struct.pack('<H', len(v)) + v.encode('latin1')
        elif 0x41 <= t <= 0x50 and (t & 0x3f) in FIX:
            fmt = FIX[t & 0x3f][0]
            self.data = b''.join(struct.pack(fmt, *(x if isinstance(x, (tuple, list)) else (x,))) for x in v)
        else:
            raise ValueError('cannot set tag %#x' % t)


class Rec:
    __slots__ = ('name', 'ver', 'kids')

    def __init__(self, name, ver, kids):
        self.name, self.ver, self.kids = name, ver, kids


class RArr:
    __slots__ = ('name', 'ver', 'items')

    def __init__(self, name, ver, items):
        self.name, self.ver, self.items = name, ver, items


class Esf:
    def __init__(self, b):
        self.raw = b
        self.magic, self.zero, self.ts, noff = struct.unpack_from('<IIII', b, 0)
        n = struct.unpack_from('<H', b, noff)[0]
        o = noff + 2
        self.names = []
        for _ in range(n):
            ln = struct.unpack_from('<H', b, o)[0]
            self.names.append(b[o + 2:o + 2 + ln].decode('latin1'))
            o += 2 + ln
        self.tail = b[o:]  # bytes after the name table, kept verbatim
        self.unknown = []  # (offset, tag) of nodes whose layout is not known (packed arrays of an unknown element type)
        self.nodes = self._parse(16, noff)

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as f:
            return cls(f.read())

    # ---- parse
    def _parse(self, o, end):
        b, out = self.raw, []
        while o < end:
            t = b[o]
            if t == 0x80:
                ni, ver, e = struct.unpack_from('<HBI', b, o + 1)
                out.append(Rec(ni, ver, self._parse(o + 8, e)))
                o = e
            elif t == 0x81:
                ni, ver, e, cnt = struct.unpack_from('<HBII', b, o + 1)
                items, p = [], o + 12
                for _ in range(cnt):
                    ie = struct.unpack_from('<I', b, p)[0]
                    items.append(self._parse(p + 4, ie))
                    p = ie
                if p != e:
                    raise ValueError('record array end mismatch at offset %d (%d != %d)' % (o, p, e))
                out.append(RArr(ni, ver, items))
                o = e
            elif t in FIX:
                n = FIX[t][1]
                out.append(Val(t, b[o + 1:o + 1 + n]))
                o += 1 + n
            elif t in (0x0e, 0x0f):
                n = struct.unpack_from('<H', b, o + 1)[0] * (2 if t == 0x0e else 1)
                out.append(Val(t, b[o + 1:o + 3 + n]))
                o += 3 + n
            elif 0x41 <= t <= 0x50:
                e = struct.unpack_from('<I', b, o + 1)[0]
                if (t & 0x3f) not in FIX:
                    self.unknown.append((o, t))
                out.append(Val(t, b[o + 5:e]))
                o = e
            else:
                raise ValueError('unknown tag %#x at offset %d (bytes %s)' % (t, o, b[max(0, o - 16):o + 16].hex()))
            if o > end:
                raise ValueError('node overruns its parent end at offset %d' % o)
        return out

    # ---- write
    def dumps(self):
        buf = bytearray(struct.pack('<IIII', self.magic, self.zero, self.ts, 0))
        self._write(self.nodes, buf)
        struct.pack_into('<I', buf, 12, len(buf))
        buf += struct.pack('<H', len(self.names))
        for s in self.names:
            e = s.encode('latin1')
            buf += struct.pack('<H', len(e)) + e
        return bytes(buf) + self.tail

    def _write(self, nodes, buf):
        for n in nodes:
            if isinstance(n, Val):
                t = n.tag
                buf.append(t)
                if 0x41 <= t <= 0x50:
                    buf += struct.pack('<I', len(buf) + 4 + len(n.data))
                buf += n.data
            elif isinstance(n, Rec):
                buf += struct.pack('<BHBI', 0x80, n.name, n.ver, 0)
                pos = len(buf) - 4
                self._write(n.kids, buf)
                struct.pack_into('<I', buf, pos, len(buf))
            else:
                buf += struct.pack('<BHBII', 0x81, n.name, n.ver, 0, len(n.items))
                pos = len(buf) - 8
                for it in n.items:
                    buf += b'\0\0\0\0'
                    ipos = len(buf) - 4
                    self._write(it, buf)
                    struct.pack_into('<I', buf, ipos, len(buf))
                struct.pack_into('<I', buf, pos, len(buf))

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.dumps())

    # ---- query
    def name_id(self, name, create=True):
        if name in self.names:
            return self.names.index(name)
        if not create:
            raise KeyError(name)
        self.names.append(name)
        return len(self.names) - 1

    def nm(self, node):
        return self.names[node.name]

    def select(self, spec):
        """spec 'A/B[3]/C': descend by record/array name; NAME[i] on a record array = item i (its children become the
        container), on a plain record = i-th sibling of that name; a record array without [i] expands to all items.
        Leading '//' = first segment may sit at any depth. Returns a list of containers (lists of nodes)."""
        anywhere = spec.startswith('//')
        segs = [s for s in spec.strip('/').split('/') if s]
        conts = list(self._all_containers(self.nodes)) if anywhere else [self.nodes]
        first = True
        for seg in segs:
            name, idx = seg, None
            if seg.endswith(']'):
                name, ix = seg[:-1].split('[')
                idx = int(ix)
            nxt = []
            for c in conts:
                hits = [n for n in c if isinstance(n, (Rec, RArr)) and self.nm(n) == name]
                if not (anywhere and first) and idx is not None and hits and isinstance(hits[0], Rec):
                    hits = hits[idx:idx + 1]
                for h in hits:
                    if isinstance(h, Rec):
                        nxt.append(h.kids)
                    elif idx is not None:
                        nxt.append(h.items[idx])
                    else:
                        nxt.extend(h.items)
            conts, first = nxt, False
        return conts

    def select_node(self, spec):
        """the Rec/RArr named by the last segment of spec (the parent container is selected by the preceding ones)"""
        head, _, last = spec.rpartition('/')
        name = last.split('[')[0]
        conts = self.select(head) if head.strip('/') else [self.nodes]
        for c in conts:
            for n in c:
                if isinstance(n, (Rec, RArr)) and self.nm(n) == name:
                    return n
        raise KeyError(spec)

    def _all_containers(self, nodes):
        yield nodes
        for n in nodes:
            if isinstance(n, Rec):
                yield from self._all_containers(n.kids)
            elif isinstance(n, RArr):
                for it in n.items:
                    yield from self._all_containers(it)

    @staticmethod
    def vals(container):
        return [n for n in container if isinstance(n, Val)]

    # ---- edits (counts/offsets are rebuilt by dumps())
    def set_value(self, container, index, value):
        self.vals(container)[index].set(value)

    def copy_item(self, arr, i, to=None):
        it = copy.deepcopy(arr.items[i])
        arr.items.insert(len(arr.items) if to is None else to, it)
        return it

    def remove_item(self, arr, i):
        return arr.items.pop(i)

    def insert_node(self, container, pos, node):
        container.insert(pos, node)

    def tree(self, nodes=None, depth=0, maxd=3, out=None):
        out = [] if out is None else out
        for n in (self.nodes if nodes is None else nodes):
            if isinstance(n, Rec):
                out.append('  ' * depth + '%s v%d' % (self.nm(n), n.ver))
                if depth + 1 < maxd:
                    self.tree(n.kids, depth + 1, maxd, out)
            elif isinstance(n, RArr):
                out.append('  ' * depth + '%s[%d] v%d' % (self.nm(n), len(n.items), n.ver))
                if n.items and depth + 1 < maxd:
                    self.tree(n.items[0], depth + 1, maxd, out)
        return out


def load(path):
    """API: Esf = load(path); e.select('A/B[3]/C') -> containers; e.select_node(spec) -> Rec/RArr; e.vals(container) -> Val list;
    e.set_value(container, i, v); e.copy_item(arr, i, to); e.remove_item(arr, i); e.insert_node(container, pos, node); e.save(path)"""
    return Esf.load(path)


def walk(esf, nodes=None, path=()):
    """yield (path tuple of names, node) for every Rec / RArr; items of a record array add 'NAME[i]' to the path"""
    for n in (esf.nodes if nodes is None else nodes):
        if isinstance(n, Rec):
            yield path + (esf.nm(n),), n
            yield from walk(esf, n.kids, path + (esf.nm(n),))
        elif isinstance(n, RArr):
            yield path + (esf.nm(n),), n
            for i, it in enumerate(n.items):
                yield from walk(esf, it, path + ('%s[%d]' % (esf.nm(n), i),))


def parse_value(tag, s):
    if tag == 0x01:
        return s.lower() in ('1', 'true', 'yes')
    if tag in (0x0a, 0x0b):
        return float(s)
    if tag in (0x0c, 0x0d):
        return tuple(float(x) for x in s.split(','))
    if tag in (0x0e, 0x0f):
        return s
    return int(s, 0)


def first_diff(a, b):
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i
    return min(len(a), len(b))


def locate(raw, off):
    """(record path, tag at the deepest node that starts at or contains off) in the original bytes, for failure reports"""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.esf', delete=False) as f:
        f.write(raw)
    try:
        d = esf_dump.Esf(f.name)
    finally:
        os.unlink(f.name)
    rn, o, e = esf_dump.root_span(d)
    path = [rn]
    while True:
        p = o
        for kind, name, pl in d.children(o, e):
            if kind == 'rec' and pl[0] - 8 <= off < pl[1]:
                if off < pl[0]:
                    return '/'.join(path + [name]), 0x80
                path.append(name)
                o, e = pl[0], pl[1]
                break
            if kind == 'arr' and pl[0] and pl[0][0][0] - 16 <= off < pl[0][-1][1]:
                hit = next(((i, a, z) for i, (a, z) in enumerate(pl[0]) if a - 4 <= off < z), None)
                if hit is None or off < hit[1]:
                    return '/'.join(path + [name]), 0x81
                path.append('%s[%d]' % (name, hit[0]))
                o, e = hit[1], hit[2]
                break
            if kind == 'val':
                _, nxt = d.value(p)
                if p <= off < nxt:
                    return '/'.join(path) + '@value', raw[p]
                p = nxt
                continue
            p = pl[1] if kind == 'rec' else (pl[0][-1][1] if pl[0] else p)
        else:
            return '/'.join(path), None


def roundtrip(path):
    """(ok, sha in, sha out, first diff offset or None, unknown [(offset, tag)]); ok needs sha-equal and no unknown tag"""
    with open(path, 'rb') as f:
        raw = f.read()
    e = Esf(raw)
    out = e.dumps()
    same = out == raw
    return (same and not e.unknown, hashlib.sha256(raw).hexdigest(), hashlib.sha256(out).hexdigest(),
            None if same else first_diff(raw, out), e.unknown)


def info(path):
    with open(path, 'rb') as f:
        raw = f.read()
    e = Esf(raw)
    tags = {}
    nodes = 0
    for c in e._all_containers(e.nodes):
        for n in c:
            nodes += 1
            if isinstance(n, Val):
                tags[n.tag] = tags.get(n.tag, 0) + 1
    root = e.nm(e.nodes[0]) if e.nodes and isinstance(e.nodes[0], Rec) else None
    build = next((v.get() for v in Esf.vals(e.nodes[0].kids) if v.tag in (0x0e, 0x0f)), None) if root else None
    return '\n'.join([
        'file %s size %d sha256 %s' % (path, len(raw), hashlib.sha256(raw).hexdigest()),
        'magic %#x (%s) zero %d stamp %d names %d nodes %d' % (e.magic, esf_dump.MAGICS.get(e.magic, 'unknown'), e.zero, e.ts,
                                                              len(e.names), nodes),
        'root %s v%d, first string %r' % (root, e.nodes[0].ver, build) if root else 'root: not a record',
        'top-level nodes: %s' % [e.nm(n) for n in e.nodes if not isinstance(n, Val)],
        'value tags: %s' % ', '.join('%#x %s=%d' % (t, esf_dump.TAGN.get(t, 'array' if t & 0x40 else '?'), c) for t, c in sorted(tags.items())),
        'unknown tags: %s' % (e.unknown or 'none'),
        'bytes after name table: %d' % len(e.tail)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['info', 'roundtrip', 'tree', 'dump', 'set', 'copy-item', 'remove-item'])
    ap.add_argument('file', nargs='+')
    ap.add_argument('-o', '--out')
    ap.add_argument('--to', type=int)
    ap.add_argument('--depth', type=int, default=3)
    a = ap.parse_args()
    if a.cmd == 'info':
        for f in a.file:
            print(info(f))
    elif a.cmd == 'roundtrip':
        bad = 0
        for f in a.file:
            ok, s1, s2, d, unk = roundtrip(f)
            if ok:
                print('OK   %s %s' % (f, s1[:16]))
            else:
                with open(f, 'rb') as fh:
                    where = locate(fh.read(), d) if d is not None else None
                print('FAIL %s first diff at %s %s unknown %s' % (f, d, where, unk[:5]))
            bad += not ok
        sys.exit(1 if bad else 0)
    elif a.cmd == 'tree':
        print('\n'.join(Esf.load(a.file[0]).tree(maxd=a.depth)))
    else:
        e = Esf.load(a.file[0])
        spec = a.file[1]
        if a.cmd == 'dump':
            for c in e.select(spec):
                print([('@%d' % i, n.get() if isinstance(n, Val) else '<%s>' % e.nm(n)) for i, n in enumerate(c)][:60])
            return
        if not a.out:
            sys.exit('no -o given: not writing')
        if os.path.abspath(a.out) == os.path.abspath(a.file[0]):
            sys.exit('refusing to write over the input')
        if a.cmd == 'set':
            c = e.select(spec)[0]
            n = c[int(a.file[2].lstrip('@'))]   # N = child position @N, as esf_diff and esf_dump print it
            if not isinstance(n, Val):
                sys.exit('@%s is a record, not a value' % a.file[2])
            n.set(parse_value(n.tag, a.file[3]))
        else:
            arr = e.select_node(spec)
            (e.copy_item(arr, int(a.file[2]), a.to) if a.cmd == 'copy-item' else e.remove_item(arr, int(a.file[2])))
        e.save(a.out)
        print('wrote', a.out)


if __name__ == '__main__':
    main()
