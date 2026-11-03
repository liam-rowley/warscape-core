#!/usr/bin/env python3
"""Asset pass: the full index of every pack entry and loose file, the UI-first assets registry with roles, and the reference scan.

purpose: write discovery/assets/index.tsv.gz (every copy: size, sha256, format, kind, effective, image w/h/mips/pixel), refs.json (UI art paths named by layouts, templates, scripts and db files), summary.json, and the UI-first rows of registries/assets.jsonl with roles from <adapter>/asset_roles.json
usage: python3 discovery/assets.py [--games <adapter>/games.json] [--stage index|refs|registry|all]   (or `wsc discovery assets`); then `wsc reg render assets`
when: J7; re-run after a game update (the hashes are cached under /extract/<target>/, keyed on each pack's size and mtime, so a re-run reads only what changed)
not-a-verb: reads ~22 GB of game packs in place on the PC; `wsc discovery assets` runs it

Nothing is written in the game folder. The registry keeps hand-set used_by, upscale_method and upscale_status on a re-run.
"""
import argparse
import collections
import fnmatch
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
REPO = paths.REPO
import imagehdr  # noqa: E402
import tsvgz  # noqa: E402
from packfs import LOOSE, PackFS, key  # noqa: E402
from packs import kind  # noqa: E402

GAME = paths.TARGET
OUT = os.path.join(REPO, 'discovery', 'assets')
INDEX = os.path.join(OUT, 'index.tsv.gz')
REFS = os.path.join(OUT, 'refs.json')
SUMMARY = os.path.join(OUT, 'summary.json')
ROLES = paths.adapter_file('asset_roles.json')
REGISTRY = os.path.join(REPO, 'registries', 'assets.jsonl')
CACHE = os.path.join(REPO, 'extract', GAME, 'index_cache.json')
COLUMNS = ('pack', 'path', 'size', 'sha256', 'format', 'kind', 'effective', 'w', 'h', 'mips', 'pixel')
HEAD = 1 << 16
KEEP = ('used_by', 'upscale_method', 'upscale_status')
ID_MAX = 120
ART_EXTS = ('.tga', '.dds', '.png', '.jpg', '.jpeg', '.cur', '.ani', '.cuf')
UI_EXTRA_EXTS = ('.cuf', '.cur', '.ani')


def fmt(path):
    e = os.path.splitext(path.rsplit('\\', 1)[-1])[1].lower()
    return e[1:] if e else 'none'


# ------------------------------------------------------------------ index
def build_index(fs, cache_path=CACHE):
    """Rows of COLUMNS for every copy; sha256 and image headers cached per (source, path, offset, size, pack signature)."""
    try:
        cache = json.load(open(cache_path, encoding='utf-8'))
    except (OSError, ValueError):
        cache = {}
    sig = {}
    rows, by_file = [], collections.defaultdict(list)
    for c in fs.copies():
        by_file[c.file].append(c)
    new = {}
    for file, cs in sorted(by_file.items()):
        st = os.stat(file)
        sig = f'{st.st_size}:{st.st_mtime_ns}'
        fh = open(file, 'rb')
        try:
            for c in sorted(cs, key=lambda c: c.offset):
                ck = f'{c.source}|{c.path}|{c.offset}|{c.size}|{sig}'
                hit = cache.get(ck)
                if hit is None:
                    h, head = hashlib.sha256(), b''
                    for b in PackFS.chunks(c, fh):
                        if len(head) < HEAD:
                            head += b[:HEAD - len(head)]
                        h.update(b)
                    hit = [h.hexdigest(), imagehdr.info(head, os.path.splitext(c.path)[1])]
                new[ck] = hit
                sha, im = hit
                im = im or {}
                rows.append((c.source, c.path, c.size, sha, fmt(c.path), kind(c.path), int(c.effective),
                             im.get('w'), im.get('h'), im.get('mips'), im.get('pixel')))
        finally:
            fh.close()
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(new, f, separators=(',', ':'), sort_keys=True)
    return rows


def load_index(path=INDEX):
    h, rows = tsvgz.read(path)
    return [dict(zip(h, r)) for r in rows]


# ------------------------------------------------------------------ roles
def load_roles(path=ROLES):
    rules = json.load(open(path, encoding='utf-8'))['rules']
    for r in rules:
        r['_pats'] = [p.lower() for p in r['paths']]
    return rules


def role_of(path, rules, w=None, h=None):
    """First rule whose path glob (lower case, '/' separators) and optional exts / max_side match; 'unclassified' if none."""
    p = key(path).replace('\\', '/')
    ext = os.path.splitext(p.rsplit('/', 1)[-1])[1]
    for r in rules:
        if r.get('exts') is not None and ext not in r['exts']:
            continue
        if r.get('max_side') and not (w and h and max(int(w), int(h)) <= r['max_side']):
            continue
        if any(fnmatch.fnmatchcase(p, pat) for pat in r['_pats']):
            return r['role']
    return 'unclassified'


# ------------------------------------------------------------------ ids
def _slug(path):
    s = key(path).replace('\\', '/')
    s = re.sub(r'\s+', '_', s)
    s = re.sub(r'[^a-z0-9_./#-]', '-', s)
    s = re.sub(r'^[^a-z0-9]+', '', s)
    return s or 'x'


def ids_for(paths):
    """{path: id}: the slug of the path; every member of a colliding group, and any slug over ID_MAX, gets '#<sha1 prefix>'."""
    groups = collections.defaultdict(list)
    for p in paths:
        groups[_slug(p)].append(p)
    out = {}
    for s, ps in groups.items():
        for p in ps:
            if len(ps) == 1 and len(s) <= ID_MAX:
                out[p] = s
                continue
            hx = hashlib.sha1(key(p).encode('utf-8')).hexdigest()
            n = 7
            while True:
                suf = '#' + hx[:n]
                cand = s[:ID_MAX - len(suf)] + suf
                if cand not in out.values() or n >= 40:
                    break
                n += 1
            out[p] = cand
    if len(set(out.values())) != len(out):
        raise ValueError('asset id collision after hashing')
    return out


# ------------------------------------------------------------------ refs
PATH_RE = re.compile(r'[A-Za-z0-9_ ./\\-]{2,200}?\.(?:tga|dds|png|jpe?g|cur|ani|cuf)(?![A-Za-z0-9])', re.I)
U16_RUN = re.compile(rb'(?:[\x20-\x7e]\x00){4,}')
A8_RUN = re.compile(rb'[\x20-\x7e]{4,}')


def strings(b):
    for m in A8_RUN.finditer(b):
        yield m.group(0).decode('latin-1')
    for m in U16_RUN.finditer(b):
        yield m.group(0).decode('utf-16-le')


def norm_ref(s):
    p = s.strip().strip('"\' ').replace('/', '\\').lower()
    while p.startswith('.\\') or p.startswith('\\'):
        p = p[2:] if p.startswith('.\\') else p[1:]
    if p.startswith('data\\'):
        p = p[5:]
    return p


def basenames(known):
    """{file name: key} for the file names exactly one known asset has (db rows name event pictures by file name only)."""
    c = collections.Counter(k.rsplit('\\', 1)[-1] for k in known)
    return {k.rsplit('\\', 1)[-1]: k for k in known if c[k.rsplit('\\', 1)[-1]] == 1}


def resolve(p, known, names=None):
    """The known asset key a scanned string names: as is, without a leading length byte, from any 'data\\' or 'ui\\' in it,
    with 'ui\\' prepended (layouts name some paths relative to ui\\), or a bare file name only one asset has; else None."""
    if names and '\\' not in p:
        return names.get(p) or names.get(p[1:])
    cands = [p, p[1:]]
    for root in ('data\\', 'ui\\'):
        i = p.find(root)
        while i >= 0:
            cands.append(p[i + 5:] if root == 'data\\' else p[i:])
            i = p.find(root, i + 1)
    for c in cands:
        for x in (c, 'ui\\' + c):
            if x in known:
                return x
    return None


def is_referrer(k):
    e = os.path.splitext(k.rsplit('\\', 1)[-1])[1]
    return (k.startswith('ui\\') and e in ('', '.luac', '.lua', '.templates', '.twin', '.xml')) or k.endswith('uied.templates') \
        or (e in ('.luac', '.lua') and k.startswith(('script\\', 'scripts\\', 'campaigns\\', 'campaign_maps\\'))) \
        or k.startswith('db\\')


def scan_refs(fs, known):
    """({asset key: [referrer keys]}, {unresolved path: [referrer keys]}, referrer count)."""
    refs, miss, n = collections.defaultdict(set), collections.defaultdict(set), 0
    names = basenames(known)
    for c in fs.list():
        k = key(c.path)
        if not is_referrer(k) or c.size > (64 << 20):
            continue
        n += 1
        b = fs.read(c)
        for s in strings(b):
            for m in PATH_RE.finditer(s):
                p = norm_ref(m.group(0))
                hit = resolve(p, known, names)
                (refs[hit] if hit else miss[p]).add(k)
    return ({a: sorted(v) for a, v in sorted(refs.items())}, {a: sorted(v) for a, v in sorted(miss.items())}, n)


# ------------------------------------------------------------------ registry
def ui_first(index, refs):
    eff = [r for r in index if r['effective'] == '1']
    keys = set(refs)
    return [r for r in eff if key(r['path']).startswith('ui\\') or os.path.splitext(r['path'])[1].lower() in UI_EXTRA_EXTS
            or (key(r['path']) in keys and os.path.splitext(r['path'])[1].lower() in ART_EXTS)]


def format_of(r):
    f = r['format']
    if r.get('w'):
        f += f" {r['pixel']} {r['w']}x{r['h']}" + (f" m{r['mips']}" if r['format'] == 'dds' else '')
    return f


def registry_rows(index, refs, rules, old=()):
    sel = ui_first(index, refs)
    ids = ids_for([r['path'] for r in sel])
    keep = {key(o['path']): o for o in old if 'path' in o}  # by path: an id gains a '#' suffix when a new path collides
    out = []
    for r in sel:
        role = role_of(r['path'], rules, r.get('w'), r.get('h'))
        size = f" {r['w']}x{r['h']}" if r.get('w') else ''
        row = {'id': ids[r['path']], 'description': f"{role.replace('_', ' ')}: {r['format']}{size} from {r['pack']}",
               'pack': r['pack'], 'path': r['path'], 'format': format_of(r), 'size': int(r['size']),
               'hash': 'sha256:' + r['sha256'], 'role': role}
        for k in KEEP:
            if k in keep.get(key(r['path']), {}):
                row[k] = keep[key(r['path'])][k]
        out.append(row)
    return sorted(out, key=lambda x: x['id'])


def read_registry(path=REGISTRY):
    try:
        return [json.loads(x) for x in open(path, encoding='utf-8') if x.strip()]
    except OSError:
        return []


def write_registry(rows, path=REGISTRY):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def pack_fingerprints(index):
    """{pack file: {'entries': n, 'bytes': sum of its entry sizes}} for the pack sources of the index (loose files are not a pack).
    `wsc discovery gate --install` compares it with the installed packs' own indexes (J11)."""
    out = {}
    for r in index:
        if r['pack'] != LOOSE:
            f = out.setdefault(r['pack'], {'entries': 0, 'bytes': 0})
            f['entries'] += 1
            f['bytes'] += int(r['size'])
    return dict(sorted(out.items()))


def summarise(index, reg, refs, miss, nref, packs):
    by_role = collections.Counter(r['role'] for r in reg)
    unref = collections.Counter(r['role'] for r in reg if key(r['path']) not in refs)
    eff = [r for r in index if r['effective'] == '1']
    imgs = [r for r in index if r['format'] in ('tga', 'dds', 'png', 'jpg', 'jpeg')]
    return {
        'schema': 1,
        'index_rows': len(index), 'effective': len(eff), 'shadowed': len(index) - len(eff),
        'pack_fingerprint': pack_fingerprints(index), 'pack_order': packs,
        'per_source': dict(sorted(collections.Counter(r['pack'] for r in index).items())),
        'per_format': dict(sorted(collections.Counter(r['format'] for r in index).items())),
        'images': len(imgs), 'images_without_dimensions': sorted(r['path'] for r in imgs if not r['w']),
        'registry_rows': len(reg), 'roles': dict(sorted(by_role.items())),
        'unclassified': by_role.get('unclassified', 0),
        'unreferenced': dict(sorted(unref.items())),
        'refs': {'referrers': nref, 'resolved_paths': len(refs), 'unresolved_paths': len(miss),
                 'unresolved_sample': sorted(miss)[:40]},
    }


def readme(s):
    out = [f'# {paths.titled(paths.TARGET)} assets (J7)', '',
           'Generated by `python3 core/wsc.py discovery render` from `summary.json` (written by `discovery/core/assets.py`). Do not edit.',
           'Full index: `index.tsv.gz` (every pack entry and loose file). Registry: `registries/assets.jsonl` (the UI-first set).',
           f'References: `refs.json`. Contact sheets: `sheets.json` (images under `/extract/{paths.TARGET}/sheets/`).', '',
           '| Index rows | Effective | Shadowed | Images | Registry rows | Unclassified | Refs resolved | Refs unresolved |',
           '|---|---|---|---|---|---|---|---|',
           f"| {s['index_rows']} | {s['effective']} | {s['shadowed']} | {s['images']} | {s['registry_rows']} | {s['unclassified']} | "
           f"{s['refs']['resolved_paths']} | {s['refs']['unresolved_paths']} |", '',
           'Pack order (later wins, then loose files): ' + ', '.join(s['pack_order']) + '.', '',
           '## Registry rows per role', '',
           '"Unreferenced" means no layout, template, script or db file names the path as a string; many such assets are named',
           'at runtime from db keys (flags, unit cards, portraits), so it is not "unused".', '',
           '| Role | Rows | Unreferenced |', '|---|---|---|']
    out += [f"| {r} | {n} | {s['unreferenced'].get(r, 0)} |" for r, n in s['roles'].items()]
    out += ['', '## Index rows per source', '', '| Source | Rows |', '|---|---|']
    out += [f'| {k} | {v} |' for k, v in s['per_source'].items()]
    if s['images_without_dimensions']:
        out += ['', 'Images whose header did not parse: ' + ', '.join(f'`{p}`' for p in s['images_without_dimensions']) + '.']
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--games', default=paths.adapter_file('games.json'))
    ap.add_argument('--stage', choices=('index', 'refs', 'registry', 'all'), default='all')
    a = ap.parse_args(argv)
    games = json.load(open(a.games, encoding='utf-8'))
    fs = PackFS.from_games(games, GAME)
    os.makedirs(OUT, exist_ok=True)
    if a.stage in ('index', 'all'):
        n = tsvgz.write(INDEX, COLUMNS, build_index(fs))
        print(f'{INDEX}: {n} rows')
    index = load_index()
    if a.stage in ('refs', 'registry', 'all'):
        known = {key(r['path']) for r in index if r['effective'] == '1'}
        refs, miss, nref = scan_refs(fs, known)
        with open(REFS, 'w', encoding='utf-8', newline='\n') as f:
            json.dump({'schema': 1, 'note': 'UI art paths (asset key) named by layouts, templates, scripts and db files (raw string scan; J10 decides which screen uses what)',
                       'refs': refs}, f, indent=0, sort_keys=True)
            f.write('\n')
        reg = registry_rows(index, refs, load_roles(), read_registry())
        write_registry(reg)
        s = summarise(index, reg, refs, miss, nref, fs.packs)
        with open(SUMMARY, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(s, f, indent=1, sort_keys=True)
            f.write('\n')
        print(f'{REGISTRY}: {len(reg)} rows, {s["unclassified"]} unclassified; refs: {len(refs)} resolved, {len(miss)} unresolved from {nref} files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
