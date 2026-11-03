#!/usr/bin/env python3
"""Exe pass of the reference-to-target-game diff: PE diff, and every reference-game engine signature searched in the target exe.

purpose: diff two Warscape exes' PE facts (sections, imports, size, LAA/ASLR/NX, strings) and search the other exe for every reference-game guard-site, patch-site and named-function signature with relocated and relative dwords masked; hits are candidates (unique, shared, multiple, none), never engine sites
usage: python3 discovery/exe.py [--games <adapter>/games.json] [--out discovery/diff/exe.json]
when: J6 exe area; J9 starts its engine_sites from the unique hits (each verified there with anchor bytes and a run id); re-run after a game update
not-a-verb: reads both game exes in place (read only), outside the wsc registry operations

Signatures: guard sites use the bytes and dontCare mask of empire-remastered rml_mod/src/exe_guard_sites.h; patch and gfxcfg sites
(rml_mod/data/exe_patches.json table, cfg_table) use a window of the reference exe around the anchor; named functions
(perf_mod/re/annotations/functions.jsonl) use their first FUNC_LEN bytes. Masked: rel32 operands of call/jmp/jcc, and any dword
whose value falls inside the reference image (absolute addresses that move between builds). The patched value bytes stay unmasked.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
from diffout import row, write  # noqa: E402
from exe_info import imports, parse_pe, rva_to_off  # noqa: E402

FUNC_LEN = 32
VA = f'{paths.REFERENCE}_va'
RVA = f'{paths.TARGET}_rva'
WINDOW = 16
MAX_HITS = 8
STRINGS = re.compile(rb'[\x20-\x7e]{6,}')
GUARD = re.compile(r'\{\s*"([^"]+)",\s*"([^"]+)",\s*0x([0-9a-fA-F]+),\s*(\d+),\s*\{([^}]*)\},\s*0x([0-9a-fA-F]+),\s*(\d+)\s*\}')


def pe_facts(b):
    pe = parse_pe(b)
    imp = imports(b, pe)
    return pe, {'bytes': len(b), 'sha1': hashlib.sha1(b).hexdigest(), 'time_date_stamp': f"0x{pe['time_date_stamp']:08x}",
                'size_of_image': f"0x{pe['size_of_image']:08x}", 'image_base': f"0x{pe['image_base']:08x}",
                'large_address_aware': bool(pe['characteristics'] & 0x20), 'aslr': bool(pe['dll_characteristics'] & 0x40),
                'nx': bool(pe['dll_characteristics'] & 0x100), 'has_relocs': bool(pe['dirs'][5][0]) if len(pe['dirs']) > 5 else False,
                'sections': {s['name']: {'vsize': s['vsize'], 'raw_size': s['raw_size'], 'characteristics': f"0x{s['characteristics']:08x}"}
                             for s in pe['sections']},
                'imports': {d: len(v) for d, v in sorted(imp.items())}, 'strings_6plus': len(STRINGS.findall(b)), '_imports': imp}


def mask_for(window, image_base, size_of_image):
    """True = byte must match. Masks rel32 after E8/E9/0F 8x and dwords that look like addresses inside the image."""
    m = [True] * len(window)
    i = 0
    while i < len(window):
        op = window[i]
        if op in (0xE8, 0xE9) and i + 5 <= len(window):
            m[i + 1:i + 5] = [False] * 4
            i += 5
            continue
        if op == 0x0F and i + 6 <= len(window) and 0x80 <= window[i + 1] <= 0x8F:
            m[i + 2:i + 6] = [False] * 4
            i += 6
            continue
        i += 1
    for j in range(len(window) - 3):
        v = struct.unpack_from('<I', window, j)[0]
        if image_base <= v < image_base + size_of_image:
            m[j:j + 4] = [False] * 4
    return m


def search(hay, pat, mask, limit=MAX_HITS):
    """Offsets where pat matches hay on the masked-in bytes; anchored on the longest exact run."""
    best, cur, start = (0, 0), 0, 0
    for i, k in enumerate(mask + [False]):
        if k:
            if cur == 0:
                start = i
            cur += 1
        else:
            if cur > best[1]:
                best = (start, cur)
            cur = 0
    a0, alen = best
    if alen < 4:
        return None   # too little fixed content to search
    anchor = pat[a0:a0 + alen]
    hits, pos = [], hay.find(anchor)
    while pos != -1 and len(hits) <= limit:
        s = pos - a0
        if s >= 0 and s + len(pat) <= len(hay) and all(not k or hay[s + i] == pat[i] for i, k in enumerate(mask)):
            hits.append(s)
        pos = hay.find(anchor, pos + 1)
    return hits


def off_to_rva(pe, off):
    for s in pe['sections']:
        if s['raw_off'] <= off < s['raw_off'] + s['raw_size']:
            return s['rva'] + off - s['raw_off']
    return None


def signatures(erepo, eb, epe):
    base, soi = epe['image_base'], epe['size_of_image']
    sigs = []
    src = open(os.path.join(erepo, 'rml_mod', 'src', 'exe_guard_sites.h'), encoding='utf-8').read()
    for name, owner, va, n, by, dc, _ in GUARD.findall(src):
        pat = bytes(int(x, 16) for x in by.replace(' ', '').split(',') if x)[:int(n)]
        dcm = int(dc, 16)
        sigs.append({'source': 'guard_site', 'name': name, VA: f'0x{int(va, 16):x}', 'pat': pat,
                     'mask': [not (dcm >> i) & 1 for i in range(len(pat))], 'note': owner})
    pj = json.load(open(os.path.join(erepo, 'rml_mod', 'data', 'exe_patches.json'), encoding='utf-8'))
    for tbl, label in (('table', 'patch_site'), ('cfg_table', 'cfg_site')):
        for s in pj[tbl]:
            if not s.get('anchor_file_offset'):
                continue
            a = int(s['anchor_file_offset'], 16)
            lo = max(0, a - WINDOW)
            pat = eb[lo:a + WINDOW + len(bytes.fromhex(s['anchor']))]
            mask = mask_for(pat, base, soi)
            v = int(s.get('value_file_offset') or s['anchor_file_offset'], 16) - lo
            for i in range(max(0, v), min(len(pat), v + len(bytes.fromhex(s.get('stock') or '')))):
                mask[i] = False   # the tunable value itself (stock or mod patched on disk) may differ per game
            sigs.append({'source': label, 'name': f"{s['name']} ({s.get('config_key', '')})", VA: s.get('va_if_base_0x400000', ''),
                         'pat': pat, 'mask': mask, 'anchor_at': a - lo, 'note': s.get('stock_value', '')})
    for line in open(os.path.join(erepo, 'perf_mod', 're', 'annotations', 'functions.jsonl'), encoding='utf-8'):
        f = json.loads(line)
        if f['name'].startswith('dyninit_') or not f['name']:
            continue   # static initialisers: generated names, no engine meaning
        off = rva_to_off(epe, int(f['va'], 16) - base)
        if off is None:
            continue
        pat = eb[off:off + FUNC_LEN]
        sigs.append({'source': 'function', 'name': f['name'], VA: f['va'], 'pat': pat,
                     'mask': mask_for(pat, base, soi), 'note': f.get('confidence', '')})
    return sigs


def run_search(sigs, nb, npe, eb, epe):
    out = []
    for s in sigs:
        hits = search(nb, s['pat'], s['mask'])
        self_hits = search(eb, s['pat'], s['mask'], 2)
        cls = 'unsearchable' if hits is None else 'none' if not hits else 'unique' if len(hits) == 1 else 'multiple'
        out.append({'source': s['source'], 'name': s['name'], VA: s[VA], 'len': len(s['pat']),
                    'masked': s['mask'].count(False), f'{paths.REFERENCE}_unique': self_hits is not None and len(self_hits) == 1,
                    'class': cls, f'{paths.TARGET}_rva': [f'0x{off_to_rva(npe, h):x}' for h in (hits or [])[:MAX_HITS]]})
    claims = collections.defaultdict(set)   # target address -> the reference addresses whose unique hit it is
    for h in out:
        if h['class'] == 'unique':
            claims[h[RVA][0]].add(int(h[VA], 16) if h[VA] else h['name'])
    for h in out:
        if h['class'] == 'unique' and len(claims[h[RVA][0]]) > 1:
            h['class'] = 'shared'   # different reference code claims the same target address: not a candidate on its own
    return sorted(out, key=lambda x: (x['source'], x['name'], x[VA]))


def compare(ef, nf, hits):
    rows = []
    for k in ('bytes', 'time_date_stamp', 'size_of_image', 'image_base', 'large_address_aware', 'aslr', 'nx', 'has_relocs', 'strings_6plus'):
        rows.append(row(f'pe {k}', ef[k], nf[k], 'same' if ef[k] == nf[k] else 'adapter', '', 'detail.*_pe'))
    secs = lambda f: ' '.join(sorted(f['sections']))
    rows.append(row('pe sections', secs(ef), secs(nf), 'same' if secs(ef) == secs(nf) else 'adapter', 'sizes in detail', 'detail.*_pe.sections'))
    for dll in sorted(set(ef['_imports']) | set(nf['_imports'])):
        e, n = set(ef['_imports'].get(dll, [])), set(nf['_imports'].get(dll, []))
        v = 'gone' if not n else 'new' if not e else 'same' if e == n else 'adapter'
        rows.append(row(f'import {dll}', len(e) or '-', len(n) or '-', v,
                        (f'+{len(n - e)} -{len(e - n)} names' if v == 'adapter' else ''), 'detail.*_pe.imports'))
    by = collections.defaultdict(collections.Counter)
    for h in hits:
        by[h['source']][h['class']] += 1
    for src, c in sorted(by.items()):
        tot = sum(c.values())
        rows.append(row(f'signatures {src}', f'{tot} signatures', ', '.join(f'{c[k]} {k}' for k in ('unique', 'shared', 'multiple', 'none', 'unsearchable') if c[k]),
                        'adapter' if c['unique'] else 'new', 'unique hits are candidates for J9 (open facts), not engine sites', 'detail.signatures'))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--games', default=paths.adapter_file('games.json'))
    ap.add_argument('--out', default=paths.result_dir('diff', 'exe.json'))
    a = ap.parse_args(argv)
    g = json.load(open(a.games, encoding='utf-8'))
    eb = open(os.path.join(g[paths.REFERENCE]['root'], g[paths.REFERENCE]['exe']), 'rb').read()
    nb = open(os.path.join(g[paths.TARGET]['root'], g[paths.TARGET]['exe']), 'rb').read()
    epe, ef = pe_facts(eb)
    npe, nf = pe_facts(nb)
    pj = json.load(open(os.path.join(g[paths.REFERENCE]['repo'], 'rml_mod', 'data', 'exe_patches.json'), encoding='utf-8'))
    stock = pj['exe']['stock_sha1']
    hits = run_search(signatures(g[paths.REFERENCE]['repo'], eb, epe), nb, npe, eb, epe)
    rows = compare(ef, nf, hits)
    rows.append(row(f"{g[paths.REFERENCE]['exe']} on disk (signature source) vs exe_patches.json stock_sha1", f"on disk {ef['sha1']}, stock {stock}", '-',
                    'same' if stock == ef['sha1'] else 'adapter',
                    '' if stock == ef['sha1'] else f'{paths.titled(paths.REFERENCE)}-side check only: the on-disk build differs from stock, so window signatures may be off',
                    'exe_patches.json exe.stock_sha1'))
    for f in (ef, nf):
        del f['_imports']
    write(a.out, 'exe', rows, {f'{paths.REFERENCE}_pe': ef, f'{paths.TARGET}_pe': nf, 'signatures': hits,
                               'method': {'func_len': FUNC_LEN, 'window': WINDOW, 'max_hits': MAX_HITS}})
    c = collections.Counter((h['source'], h['class']) for h in hits)
    print(f'{a.out}: {len(rows)} rows; {len(hits)} signatures: ' + ', '.join(f'{s}/{k} {v}' for (s, k), v in sorted(c.items())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
