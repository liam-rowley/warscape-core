"""A read-only view of one game's data\\ folder: every pack entry plus the loose files, with the game's precedence applied.

purpose: list, stat and read a Warscape game's files across its PFH0 packs and loose data\\ files (read by index offset, never a copy)
usage: from packfs import PackFS; fs = PackFS.from_games(games, paths.TARGET); fs.list() / fs.stat(path) / fs.read(path) / fs.copies()   (library)
when: every J7 pass (asset index, registry, refs, sheets, loc, db); J6's passes keep using extracted.py, switching is optional
not-a-verb: a library module imported by the discovery passes, which read multi-GB packs in place on the PC

Precedence: packs in `pack_order` (games.json; packs not listed sort after it by header type, then name), a later pack's copy
replacing an earlier one; then loose files. Whether a loose file really beats a pack entry at runtime is the open fact
the game's open fact files.loose_override (no vanilla case exists), so `loose_wins` is a parameter. Paths are keyed lower case with backslashes.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402,F401  (puts proxy/tools on the path: pack_list)
from pack_list import read_header, read_index  # noqa: E402

LOOSE = 'loose'
CHUNK = 1 << 22


def key(path):
    return path.replace('/', '\\').lower()


class Copy:
    """One copy of a file: a pack entry (source = pack file name) or a loose file (source = 'loose', offset 0)."""
    __slots__ = ('path', 'source', 'size', 'offset', 'file', 'effective', 'order')

    def __init__(self, path, source, size, offset, file, order):
        self.path, self.source, self.size, self.offset, self.file, self.order = path, source, size, offset, file, order
        self.effective = False

    def __repr__(self):
        return f'Copy({self.source}:{self.path}, {self.size} bytes{", effective" if self.effective else ""})'


class PackFS:
    def __init__(self, data_dir, pack_order=(), loose_wins=True, skip=()):
        self.data_dir = data_dir
        names = [n for n in os.listdir(data_dir) if n.lower().endswith('.pack') and n not in skip
                 and os.path.isfile(os.path.join(data_dir, n))]
        stems = [s.lower() for s in pack_order]
        heads = {n: read_header(os.path.join(data_dir, n)) for n in names}
        rank = lambda n: (0, stems.index(n[:-5].lower())) if n[:-5].lower() in stems else (1, heads[n]['pack_type'], n.lower())
        self.packs = sorted(names, key=rank)
        self.pack_types = {n: heads[n]['pack_type'] for n in self.packs}
        self._copies = []
        for i, n in enumerate(self.packs):
            p = os.path.join(data_dir, n)
            for e in read_index(p)[1]:
                self._copies.append(Copy(e['path'], n, e['size'], e['offset'], p, i))
        lo = len(self.packs) if loose_wins else -1
        for d, _, files in os.walk(data_dir):
            for f in files:
                full = os.path.join(d, f)
                rel = os.path.relpath(full, data_dir).replace('/', '\\')
                if '\\' not in rel and rel.lower().endswith('.pack'):
                    continue
                self._copies.append(Copy(rel, LOOSE, os.path.getsize(full), 0, full, lo))
        self._eff = {}
        for c in self._copies:
            k = key(c.path)
            if k not in self._eff or c.order >= self._eff[k].order:
                self._eff[k] = c
        for c in self._eff.values():
            c.effective = True

    @classmethod
    def from_games(cls, games, game, **kw):
        g = games[game]
        return cls(os.path.join(g['root'], g['data']), g.get('pack_order', ()), skip=set(g.get('mod_packs', ())), **kw)

    def copies(self):
        """Every copy, shadowed ones included, in pack order then index order."""
        return list(self._copies)

    def list(self, under='', exts=None):
        """The effective copy of each path, sorted by key; `under` is a lower-case prefix, `exts` a set ('' = none)."""
        out = []
        for k in sorted(self._eff):
            if under and not k.startswith(under):
                continue
            if exts is not None and os.path.splitext(k.rsplit('\\', 1)[-1])[1] not in exts:
                continue
            out.append(self._eff[k])
        return out

    def stat(self, path):
        return self._eff.get(key(path))

    def read(self, path_or_copy, n=None):
        c = path_or_copy if isinstance(path_or_copy, Copy) else self.stat(path_or_copy)
        if c is None:
            raise FileNotFoundError(path_or_copy)
        with open(c.file, 'rb') as f:
            f.seek(c.offset)
            return f.read(c.size if n is None else min(n, c.size))

    @staticmethod
    def chunks(c, fh=None):
        """Yield a copy's bytes in chunks (big sound and terrain entries); pass an open handle of c.file to reuse it."""
        f = fh or open(c.file, 'rb')
        try:
            f.seek(c.offset)
            left = c.size
            while left:
                b = f.read(min(CHUNK, left))
                if not b:
                    raise IOError(f'{c}: short read, {left} bytes left')
                left -= len(b)
                yield b
        finally:
            if fh is None:
                f.close()


def write_pack(path, entries, pack_type=1):
    """Write a minimal PFH0 pack ({entry path: bytes}, in order): the host tests' synthetic pack."""
    idx = b''.join(struct.pack('<I', len(b)) + p.encode('latin-1') + b'\0' for p, b in entries.items())
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sIIIII', b'PFH0', pack_type, 0, 0, len(entries), len(idx)) + idx)
        for b in entries.values():
            f.write(b)
