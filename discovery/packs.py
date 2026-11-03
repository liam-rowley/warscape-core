#!/usr/bin/env python3
"""Packs pass of the reference-to-target-game diff: pack headers, entry counts, top folders, index hashes, content-kind moves, loose files.

purpose: compare two Warscape installs' data\\*.pack sets (header, type, flags, entry count, top folders, index sha256) and map each content kind (top folder) to the packs that carry it; list loose data\\ files and which shadow pack entries
usage: python3 discovery/packs.py [--games <adapter>/games.json] [--out discovery/diff/packs.json]
when: J6 packs area; re-run after a game update (the output is deterministic, so a git diff shows what changed); J7 builds its pack reader adapter from this
not-a-verb: reads multi-GB game packs in place on the PC (index only), outside the wsc registry operations

Reads only each pack's header and index (proxy/tools/pack_list.py read_header), never the data. The reference game's mod packs (games.json
<reference>.mod_packs) are left out so the comparison is vanilla to vanilla.
"""
import argparse
import collections
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402  (puts proxy/tools on the path: pack_list)
TARGET, REFERENCE = paths.TARGET, paths.REFERENCE
from diffout import row, write  # noqa: E402
from pack_list import read_header, read_index  # noqa: E402

PACK_TYPES = {0: 'boot', 1: 'release', 2: 'patch', 3: 'mod', 4: 'movie'}
# one top folder per voice language (both games); an explicit list, because ui, db and fx are two letters too
VOICE_LANGS = {'ar', 'cz', 'du', 'fr', 'ge', 'hi', 'it', 'pe', 'pl', 'po', 'ru', 'sp', 'sw', 'tu', 'uk', 'us', 'us_trib'}


def kind(path):
    """Content kind of an entry: its top folder, two levels for ui\\ (ui\\fonts, ui\\common ui, ...) where content is split."""
    parts = path.lower().split('\\')
    if len(parts) == 1:
        return '(root)'
    if parts[0] in VOICE_LANGS:
        return 'voices (language folders)'
    if parts[0] == 'ui' and len(parts) > 2:
        return 'ui\\' + parts[1]
    return parts[0]


def scan(data_dir, skip=()):
    packs = {}
    for name in sorted(os.listdir(data_dir), key=str.lower):
        p = os.path.join(data_dir, name)
        if not name.lower().endswith('.pack') or name in skip or not os.path.isfile(p):
            continue
        h = read_header(p)
        _, entries = read_index(p)
        top = collections.Counter(kind(e['path']) for e in entries)
        packs[name] = {'magic': h['magic'], 'pack_type': h['pack_type'], 'pack_type_name': PACK_TYPES.get(h['pack_type'], '?'),
                       'flags': h['flags'], 'pack_names': h['pack_names'], 'entries': h['count'],
                       'bytes': os.path.getsize(p), 'data_bytes': sum(e['size'] for e in entries),
                       'index_sha256': hashlib.sha256(h['index']).hexdigest(), 'kinds': dict(sorted(top.items())),
                       '_paths': [e['path'].lower() for e in entries]}
    return packs


def loose(data_dir, pack_paths):
    out = collections.defaultdict(lambda: {'files': 0, 'bytes': 0, 'shadow_pack_entries': 0})
    for d, _, files in os.walk(data_dir):
        for f in files:
            rel = os.path.relpath(os.path.join(d, f), data_dir)
            if rel.lower().endswith('.pack') and os.sep not in rel:
                continue
            k = rel.split(os.sep)[0] if os.sep in rel else '(data root)'
            o = out[k]
            o['files'] += 1
            o['bytes'] += os.path.getsize(os.path.join(d, f))
            if rel.lower().replace('/', '\\') in pack_paths:
                o['shadow_pack_entries'] += 1
    return dict(sorted(out.items(), key=lambda x: x[0].lower()))


def compare(emp, nap, nap_loose):
    rows = []
    fmt_e = sorted({p['magic'] for p in emp.values()})
    fmt_n = sorted({p['magic'] for p in nap.values()})
    rows.append(row('format', '/'.join(fmt_e), '/'.join(fmt_n), 'same' if fmt_e == fmt_n else 'adapter',
                    '' if fmt_e == fmt_n else 'header differs', 'pack_list.read_header'))
    te = sorted({f"{p['pack_type']}={p['pack_type_name']}" for p in emp.values()})
    tn = sorted({f"{p['pack_type']}={p['pack_type_name']}" for p in nap.values()})
    rows.append(row('pack types', ' '.join(te), ' '.join(tn), 'same' if set(tn) <= set(te) else 'new', '', 'header u32 at 4'))
    fe = sorted({p['flags'] for p in emp.values()})
    fn = sorted({p['flags'] for p in nap.values()})
    rows.append(row('header flags (u32 at 8)', fe, fn, 'same' if fe == fn else 'adapter', '', 'header u32 at 8'))
    ne, nn = sorted(emp), sorted(nap)
    common = sorted(set(ne) & set(nn), key=str.lower)
    rows.append(row('pack set', f'{len(ne)} packs', f'{len(nn)} packs, {len(common)} names shared ({", ".join(common)})',
                    'adapter', 'names and roles differ: map by content kind, not by pack name', 'detail.packs'))
    by_kind = lambda packs: {k: sorted(n for n, p in packs.items() if k in p['kinds']) for k in {k for p in packs.values() for k in p['kinds']}}
    ke, kn = by_kind(emp), by_kind(nap)
    for k in sorted(set(ke) | set(kn)):
        e, n = ke.get(k, []), kn.get(k, [])
        ce = sum(emp[p]['kinds'][k] for p in e)
        cn = sum(nap[p]['kinds'][k] for p in n)
        v = 'gone' if not n else 'new' if not e else 'same' if e == n else 'adapter'
        rows.append(row(f'kind {k}', f'{ce} in {", ".join(e) or "-"}', f'{cn} in {", ".join(n) or "-"}', v,
                        'look it up in the other pack(s)' if v == 'adapter' else '', 'detail.packs.*.kinds'))
    lf = sum(x['files'] for x in nap_loose.values())
    ls = sum(x['shadow_pack_entries'] for x in nap_loose.values())
    rows.append(row('loose data files', f'(not compared: {paths.titled(REFERENCE)} data\\ holds mod files)', f'{lf} files in {len(nap_loose)} folders, {ls} with the same path as a pack entry',
                    'new', f'loose-only files are read from disk; the shadowing ones are candidates for {TARGET}.files.loose_probe_dirs', f'detail.{TARGET}_loose'))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--games', default=paths.adapter_file('games.json'))
    ap.add_argument('--out', default=paths.result_dir('diff', 'packs.json'))
    a = ap.parse_args(argv)
    g = json.load(open(a.games, encoding='utf-8'))
    ed = os.path.join(g[REFERENCE]['root'], g[REFERENCE]['data'])
    nd = os.path.join(g[TARGET]['root'], g[TARGET]['data'])
    emp = scan(ed, set(g[REFERENCE]['mod_packs']))
    nap = scan(nd)
    nap_paths = {p for x in nap.values() for p in x['_paths']}
    nl = loose(nd, nap_paths)
    rows = compare(emp, nap, nl)
    for d in (emp, nap):
        for p in d.values():
            del p['_paths']
    write(a.out, 'packs', rows, {f'{REFERENCE}_packs': emp, f'{TARGET}_packs': nap, f'{TARGET}_loose': nl,
                                 f'{REFERENCE}_mod_packs_skipped': sorted(g[REFERENCE]['mod_packs'])})
    print(f'{a.out}: {len(rows)} rows ({len(emp)} {paths.titled(REFERENCE)} packs, {len(nap)} {paths.titled(TARGET)} packs)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
