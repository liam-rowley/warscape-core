#!/usr/bin/env python3
"""Shaders pass (static) of the reference-to-target-game diff: the effect sources each game ships, file by file.

purpose: list both games' fx\\ effect sources (sha256, size, technique names, includes) and diff them file by file (identical, changed with a line-diff size, new, gone), flagging shadow, imposter, sprite and LOD names for J8
usage: python3 discovery/shaders.py [--games <adapter>/games.json] [--out discovery/diff/shaders.json]   (needs the extract: discovery/README.md)
when: J6 shaders area; J8 (runtime shader catalogue, frame anatomy) starts from the flagged files; re-run after a game update
not-a-verb: reads extracted game files, outside the wsc registry operations
"""
import argparse
import difflib
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
from diffout import row, write  # noqa: E402
from extracted import effective, load_games  # noqa: E402

TECH = re.compile(r'^\s*technique\d*\s+([A-Za-z_]\w*)', re.M)
INCL = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.M)
FLAG = re.compile(r'shadow|impost|sprite|lod', re.I)


def read(path):
    d = open(path, 'rb').read()
    t = d.decode('latin-1')
    return {'bytes': len(d), 'sha256': hashlib.sha256(d).hexdigest(), 'lines': t.count('\n') + 1,
            'techniques': sorted(set(TECH.findall(t))), 'includes': sorted(set(i.lower() for i in INCL.findall(t))),
            '_text': t}


def line_diff(a, b):
    n = 0
    for op in difflib.SequenceMatcher(None, a.splitlines(), b.splitlines(), autojunk=False).get_opcodes():
        if op[0] != 'equal':
            n += max(op[2] - op[1], op[4] - op[3])
    return n


def flags(path, info):
    hits = sorted({m.group(0).lower() for m in FLAG.finditer(path)} | {m.group(0).lower() for t in info['techniques'] for m in FLAG.finditer(t)})
    return hits


def classify(ef, nf):
    out = {}
    for p in sorted(set(ef) | set(nf)):
        e, n = ef.get(p), nf.get(p)
        if not n:
            out[p] = {'status': 'gone'}
        elif not e:
            out[p] = {'status': 'new'}
        elif e['sha256'] == n['sha256']:
            out[p] = {'status': 'identical'}
        else:
            out[p] = {'status': 'changed', 'lines_changed': line_diff(e['_text'], n['_text']),
                      'techniques_added': sorted(set(n['techniques']) - set(e['techniques'])),
                      'techniques_removed': sorted(set(e['techniques']) - set(n['techniques']))}
        fl = sorted(set(flags(p, n or e)))
        if fl:
            out[p]['flag_j8'] = fl
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--games')
    ap.add_argument('--out', default=paths.result_dir('diff', 'shaders.json'))
    a = ap.parse_args(argv)
    g = load_games(a.games)
    ef = {p: read(f) for p, f in effective(g, paths.REFERENCE, under='fx\\').items()}
    nf = {p: read(f) for p, f in effective(g, paths.TARGET, under='fx\\').items()}
    cl = classify(ef, nf)
    count = lambda s: sum(1 for c in cl.values() if c['status'] == s)
    tech = lambda fs: sum(len(f['techniques']) for f in fs.values())
    rows = [row('fx sources', f'{len(ef)} files, {tech(ef)} techniques', f'{len(nf)} files, {tech(nf)} techniques', 'adapter',
                'same fx\\ layout and HLSL effect format; compare per file', 'detail.files'),
            row('fx files identical', '-', count('identical'), 'same', '', 'detail.files'),
            row('fx files changed', '-', count('changed'), 'adapter',
                f"{sum(c.get('lines_changed', 0) for c in cl.values())} lines differ in total", 'detail.files'),
            row(f'fx files new in {paths.titled(paths.TARGET)}', '-', count('new'), 'new', '', 'detail.files'),
            row(f'fx files gone in {paths.titled(paths.TARGET)}', count('gone'), '-', 'gone', '', 'detail.files')]
    for p, c in cl.items():
        if c.get('flag_j8') and c['status'] != 'identical':
            what = c['status'] + (f", {c['lines_changed']} lines" if c['status'] == 'changed' else '')
            rows.append(row(f'J8 {p}', '-' if c['status'] == 'new' else 'yes', '-' if c['status'] == 'gone' else what,
                            {'changed': 'adapter', 'new': 'new', 'gone': 'gone'}[c['status']], 'flag: ' + ', '.join(c['flag_j8']), 'detail.files'))
    for d in (ef, nf):
        for f in d.values():
            del f['_text']
    write(a.out, 'shaders', rows, {f'{paths.REFERENCE}_files': ef, f'{paths.TARGET}_files': nf, 'files': cl,
                                   'compiled_shaders': 'none shipped as files in either game; the runtime catalogue by hash is J8 (empire-remastered gfx_mod/shaders/catalog.json)'})
    print(f'{a.out}: {len(rows)} rows; {len(ef)} {paths.titled(paths.REFERENCE)} and {len(nf)} {paths.titled(paths.TARGET)} fx files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
