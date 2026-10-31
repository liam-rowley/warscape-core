#!/usr/bin/env python3
"""esf_diff.py: node-level diff of two ESF files (saves, startpos) by record path. Stdlib only.

purpose: list changed values, added and removed records and record-array items between two saves, by record path (NAME[i], NAME#n, @N = child position)
usage: python3 -I saves/core/esf_diff.py A.save B.save [--under PATH] [--max N] [--ignore-float EPS] [--skip NAME,NAME|@<game>/noise.txt]
when: mapping which records encode a game state from two saves made one action apart (saves/SAVE_FORMAT.md), and checking that a recipe changed only what it meant to; read-only, offset based (two files in memory, no tree objects)
not-a-verb: a game-agnostic ESF reader run on the PC against saves outside the repo (warscape-core candidate, D10)

Ported from empire-remastered rml_mod/tools/db/esf_diff.py (J14). Added: `--skip @FILE` reads the record names to skip from a
file (one per line, # comments), so each game keeps its noise list beside its map.
"""
import argparse
import difflib
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esf_dump import Esf, root_span  # noqa: E402


def kids(esf, o, e):
    """list of (sig, kind, name, payload, span) for children in [o, e); span = (start, end) bytes of the node"""
    out = []
    b = esf.b
    for kind, name, p in esf.children(o, e):
        out.append((kind, name, p))
    return out


def node_bytes_key(esf, mv, kind, p):
    """offset-independent identity of a node: hash of its value bytes with nested offsets zeroed (records walked)"""
    h = hashlib.blake2b(digest_size=12)
    _hash_into(esf, mv, kind, p, h)
    return h.digest()


def _hash_into(esf, mv, kind, p, h):
    if kind == 'val':
        h.update(repr(p).encode())
    elif kind == 'rec':
        h.update(b'R%d' % p[2])
        for k, n, q in esf.children(p[0], p[1]):
            h.update((n or '').encode())
            _hash_into(esf, mv, k, q, h)
    else:
        items, ver = p
        h.update(b'A%d,%d' % (ver, len(items)))
        for a, z in items:
            h.update(b'|')
            for k, n, q in esf.children(a, z):
                h.update((n or '').encode())
                _hash_into(esf, mv, k, q, h)


class Differ:
    def __init__(self, A, B, maxout, eps, skip):
        self.A, self.B = A, B
        self.ma, self.mb = memoryview(A.b), memoryview(B.b)
        self.out = []
        self.maxout = maxout
        self.eps = eps
        self.skip = skip
        self.delta = 0

    def emit(self, s):
        if len(self.out) < self.maxout:
            self.out.append(s)
        elif len(self.out) == self.maxout:
            self.out.append('... output capped at %d lines' % self.maxout)

    def same_bytes(self, a0, a1, b0, b1):
        # identical spans at the same relative layout (works when no shift happened before this node)
        return (a1 - a0) == (b1 - b0) and a0 == b0 and self.ma[a0:a1] == self.mb[b0:b1]

    def same_values(self, va, vb):
        if va == vb or repr(va) == repr(vb):   # repr: nan == nan (a REGION@42 can hold nan; nan != nan is not a change)
            return True
        if self.eps and isinstance(va, (float, tuple)) and type(va) is type(vb):
            ta = va if isinstance(va, tuple) else (va,)
            tb = vb if isinstance(vb, tuple) else (vb,)
            return len(ta) == len(tb) and all(abs(x - y) <= self.eps for x, y in zip(ta, tb)
                                              if isinstance(x, float) and isinstance(y, float))
        return False

    def summary(self, esf, kind, p, n=6):
        if kind == 'val':
            r = repr(p)
            return r if len(r) < 120 else r[:117] + '...'
        rng = [(p[0], p[1])] if kind == 'rec' else p[0][:1]
        vals = []
        for a, z in rng:
            for k, nm, q in esf.children(a, z):
                if k == 'val':
                    r = repr(q)
                    vals.append(r if len(r) < 40 else r[:37] + '...')
                else:
                    vals.append('<%s>' % nm)
                if len(vals) >= n:
                    break
        extra = '' if kind == 'rec' else ' (%d items, first:)' % len(p[0])
        return extra + ' ' + ', '.join(vals)

    def node(self, ka, pa, kb, pb, path):
        A, B = self.A, self.B
        if ka == 'val':
            if not self.same_values(pa, pb):
                self.emit('~ %s: %s -> %s' % (path, self.summary(A, 'val', pa), self.summary(B, 'val', pb)))
            return
        if ka == 'rec':
            if self.same_bytes(pa[0], pa[1], pb[0], pb[1]):
                return
            if pa[2] != pb[2]:
                self.emit('~ %s: version v%d -> v%d' % (path, pa[2], pb[2]))
            self.seq(pa[0], pa[1], pb[0], pb[1], path)
            return
        ia, ib = pa[0], pb[0]
        if ia and ib and self.same_bytes(ia[0][0] - 4, ia[-1][1], ib[0][0] - 4, ib[-1][1]):
            return
        if len(ia) == len(ib):
            for i, ((a0, a1), (b0, b1)) in enumerate(zip(ia, ib)):
                if not self.same_bytes(a0, a1, b0, b1):
                    self.seq(a0, a1, b0, b1, '%s[%d]' % (path, i))
            return
        # different counts: align items by offset-independent content hash
        ha = [node_bytes_key(A, self.ma, 'rec', (a, z, 0)) for a, z in ia]
        hb = [node_bytes_key(B, self.mb, 'rec', (a, z, 0)) for a, z in ib]
        self.emit('# %s: %d -> %d items' % (path, len(ia), len(ib)))
        sm = difflib.SequenceMatcher(None, ha, hb, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == 'equal':
                continue
            if op == 'replace' and (i2 - i1) == (j2 - j1):
                for d in range(i2 - i1):
                    self.seq(ia[i1 + d][0], ia[i1 + d][1], ib[j1 + d][0], ib[j1 + d][1], '%s[%d->%d]' % (path, i1 + d, j1 + d))
                continue
            for i in range(i1, i2):
                self.emit('- %s[%d]: %s' % (path, i, self.summary(A, 'rec', (ia[i][0], ia[i][1], 0))))
            for j in range(j1, j2):
                self.emit('+ %s[%d]: %s' % (path, j, self.summary(B, 'rec', (ib[j][0], ib[j][1], 0))))

    def seq(self, a0, a1, b0, b1, path):
        A, B = self.A, self.B
        ca = list(A.children(a0, a1))
        cb = list(B.children(b0, b1))
        sa = [(k, n) for k, n, _ in ca]
        sb = [(k, n) for k, n, _ in cb]
        if sa == sb:
            pairs = [(i, i) for i in range(len(ca))]
            extra = []
        else:
            sm = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
            pairs, extra = [], []
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op == 'equal' or (op == 'replace' and i2 - i1 == j2 - j1):
                    pairs += [(i1 + d, j1 + d) for d in range(i2 - i1)]
                else:
                    extra += [('-', i) for i in range(i1, i2)] + [('+', j) for j in range(j1, j2)]
        dup = {}
        for k, n, _ in ca:
            if k == 'rec':
                dup[n] = dup.get(n, 0) + 1
        seen = {}
        for i, j in pairs:
            ka, na, pa = ca[i]
            kb, nb, pb = cb[j]
            if ka == 'rec':
                seen[na] = seen.get(na, 0) + 1
            if na in self.skip:
                continue
            if ka == 'val':
                p = '%s@%d' % (path, i)
            elif ka == 'rec' and dup.get(na, 0) > 1:
                p = '%s/%s#%d' % (path, na, seen[na] - 1)   # n-th sibling record of that name
            else:
                p = '%s/%s' % (path, na)
            if ka != kb or na != nb:
                self.emit('~ %s: %s %s -> %s %s' % (p, ka, na, kb, nb))
                continue
            self.node(ka, pa, kb, pb, p)
        for sgn, i in extra:
            esf, c = (A, ca) if sgn == '-' else (B, cb)
            k, n, p = c[i]
            label = '@%d' % i if k == 'val' else '/' + n + ('[]' if k == 'arr' else '')
            self.emit('%s %s%s: %s' % (sgn, path, label, self.summary(esf, k, p)))


def skip_names(spec):
    """'A,B' or '@file' (one name per line, # comments; several specs joined by commas) -> set of record names"""
    out = set()
    for part in (x.strip() for x in spec.split(',')):
        if part.startswith('@'):
            with open(part[1:], encoding='utf-8') as f:
                out |= {ln.split('#')[0].strip() for ln in f} - {''}
        elif part:
            out.add(part)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('a')
    ap.add_argument('b')
    ap.add_argument('--under', help='only diff below this record path (names, e.g. CAMPAIGN_ENV/CAMPAIGN_MODEL/WORLD)')
    ap.add_argument('--max', type=int, default=4000, help='max output lines')
    ap.add_argument('--ignore-float', type=float, default=0.0, help='treat floats within EPS as equal')
    ap.add_argument('--skip', default='', help='record names not to descend: NAME,NAME or @FILE (e.g. the game repo noise.txt)')
    a = ap.parse_args()
    A, B = Esf(a.a), Esf(a.b)
    ra, oa, ea = root_span(A)
    rb, ob, eb = root_span(B)
    d = Differ(A, B, a.max, a.ignore_float, skip_names(a.skip))
    if a.under:
        from esf_dump import find
        want = a.under.split('/')
        ha, hb = [], []
        find(A, oa, ea, [ra], want, ha)
        find(B, ob, eb, [rb], want, hb)
        for (ka, pa_, pa), (kb, pb_, pb) in zip(ha, hb):
            d.node(ka, pa, kb, pb, '/'.join(pa_))
        if len(ha) != len(hb):
            d.emit('# %s: %d hits in A, %d in B' % (a.under, len(ha), len(hb)))
    else:
        d.seq(oa, ea, ob, eb, ra)
    sys.stdout.write('\n'.join(d.out) + '\n')
    sys.stdout.write('# %d diff lines\n' % len(d.out))


if __name__ == '__main__':
    main()
