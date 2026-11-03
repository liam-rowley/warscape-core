#!/usr/bin/env python3
"""Fonts pass of the reference-to-target-game diff: every .cuf file's header, glyph count and round trip, and the font-name map.

purpose: list both games' CUF0 bitmap fonts (header metrics, glyphs, pair table, sha256, byte-exact round trip through cuf.py) and map the font names layouts reference ("Ingame 12, Bold") to files
usage: python3 discovery/fonts.py [--games <adapter>/games.json] [--out discovery/diff/fonts.json]   (run layouts.py first: it reads layouts.json detail.fonts_referenced)
when: J6 fonts area; the engine-drawn text path of UI_PIPELINE (D7) relies on the name map and the round trip
not-a-verb: reads extracted game files, outside the wsc registry operations
"""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
from cuf import Cuf  # noqa: E402
from diffout import row, write  # noqa: E402
from extracted import effective, load_games  # noqa: E402

NAME = re.compile(r'^([A-Za-z_]+(?: [A-Za-z_]+)*) (\d+), (Normal|Bold)$')


def font_file(name):
    """Layout font name -> pack path: 'Ingame 12, Bold' -> font\\ingame_b_12.cuf (the reference game's rule, empire-remastered ui_scale_mod/FORMAT.md)."""
    m = NAME.match(name)
    if not m:
        return None
    fam = m.group(1).lower().replace(' ', '_')
    return f"font\\{fam}{'_b' if m.group(3) == 'Bold' else ''}_{m.group(2)}.cuf"


def read(path):
    d = open(path, 'rb').read()
    out = {'bytes': len(d), 'sha256': hashlib.sha256(d).hexdigest(), 'magic': d[:4].decode('latin-1')}
    try:
        c = Cuf.parse(d)
    except Exception as e:  # noqa: BLE001 (a decode failure is a result)
        out['roundtrip'] = f'fail: {type(e).__name__}: {e}'
        return out
    out.update(header=c.header, glyphs=len(c.glyphs), pairs=len(c.pairs), pair_first=c.pair_first,
               roundtrip='exact' if c.serialise() == d else 'exact (offsets kept)' if c.serialise(keep_offsets=True) == d else 'mismatch')
    return out


def compare(ef, nf, eref, nref):
    rows = []
    mag = lambda fs: sorted({f['magic'] for f in fs.values()})
    rows.append(row('format', '/'.join(mag(ef)), '/'.join(mag(nf)), 'same' if mag(ef) == mag(nf) else 'adapter', '', 'detail.*_files'))
    rt = lambda fs: sum(f.get('roundtrip', '').startswith('exact') for f in fs.values())
    rows.append(row('cuf.py round trip', f'{rt(ef)} of {len(ef)}', f'{rt(nf)} of {len(nf)}',
                    'same' if rt(nf) == len(nf) else 'adapter', '' if rt(nf) == len(nf) else f'see detail.{paths.TARGET}_files', 'detail.*_files'))
    gl = lambda fs: sorted({f.get('glyphs') for f in fs.values()}, key=str)
    rows.append(row('glyph counts', gl(ef), gl(nf), 'same' if gl(ef) == gl(nf) else 'adapter', 'cmap and pair table sized per file', 'detail.*_files'))
    common = sorted(set(ef) & set(nf))
    same = [p for p in common if ef[p]['sha256'] == nf[p]['sha256']]
    rows.append(row('font files', f'{len(ef)}', f'{len(nf)}: {len(common)} shared names, {len(same)} byte-identical',
                    'same' if len(same) == len(common) else 'adapter',
                    'same names; bitmaps differ' if len(same) < len(common) else 'files only in one game: own rows', 'detail.*_files'))
    for p in sorted(set(ef) ^ set(nf)):
        rows.append(row(f'font file {p}', 'yes' if p in ef else '-', 'yes' if p in nf else '-', 'gone' if p in ef else 'new', '', 'detail.*_files'))
    unmapped = lambda refs, fs: sorted(n for n in refs if font_file(n) not in fs)
    rows.append(row('name map (layout font -> file)', f'{len(eref)} names, unmapped {unmapped(eref, ef) or "none"}',
                    f'{len(nref)} names, unmapped {unmapped(nref, nf) or "none"}',
                    'same' if not unmapped(nref, nf) else 'adapter', "rule: '<Family> N, Bold' -> font\\<family>_b_N.cuf", 'detail.name_map'))
    for n in sorted(set(eref) ^ set(nref)):
        rows.append(row(f'font name {n}', eref.get(n, '-'), nref.get(n, '-'), 'gone' if n not in nref else 'new', 'layout references (count)', 'detail.name_map'))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--games')
    ap.add_argument('--out', default=paths.result_dir('diff', 'fonts.json'))
    ap.add_argument('--layouts', default=paths.result_dir('diff', 'layouts.json'))
    a = ap.parse_args(argv)
    g = load_games(a.games)
    ef = {p: read(f) for p, f in effective(g, paths.REFERENCE, exts={'.cuf'}).items()}
    nf = {p: read(f) for p, f in effective(g, paths.TARGET, exts={'.cuf'}).items()}
    refs = json.load(open(a.layouts, encoding='utf-8'))['detail']['fonts_referenced']
    rows = compare(ef, nf, refs[paths.REFERENCE], refs[paths.TARGET])
    names = sorted(set(refs[paths.REFERENCE]) | set(refs[paths.TARGET]))
    write(a.out, 'fonts', rows, {f'{paths.REFERENCE}_files': ef, f'{paths.TARGET}_files': nf,
                                 'name_map': {n: {'file': font_file(n), f'{paths.REFERENCE}_refs': refs[paths.REFERENCE].get(n, 0),
                                                  f'{paths.TARGET}_refs': refs[paths.TARGET].get(n, 0)} for n in names}})
    print(f'{a.out}: {len(rows)} rows; {len(ef)} {paths.titled(paths.REFERENCE)} and {len(nf)} {paths.titled(paths.TARGET)} fonts')
    return 0


if __name__ == '__main__':
    sys.exit(main())
