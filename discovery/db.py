#!/usr/bin/env python3
"""db pass: index every db table file and decode it byte-exact against the pinned RPFM schema (schemas, keys and refs only are committed).

purpose: write discovery/db/tables.json (per table: file, pack, version, rows, sha256, decoded or why not, fields with types, keys and refs); decoded rows go to /extract/<target>/db/; readme() renders discovery/db/README.md
usage: python3 discovery/db.py [--games <adapter>/games.json]   (or `wsc discovery db`; `wsc discovery render` writes the README)   |   from db import parse_header, decode_table
when: J7; re-run after a game update or a schema pin change (<adapter>/db_schema.json from discovery/ron2json.py); without the schema it still writes the index
not-a-verb: reads data.pack in place on the PC; `wsc discovery db` runs it

Ported from empire-remastered rml_mod/tools/db (its db reader). File layout: optional GUID marker FD FE FC FF (+ u16 length + UTF-16LE),
optional version marker FC FD FE FF + u32 version (none = version 0), a u8 1 and a u32 row count, then the rows. A table counts as
decoded only when its rows consume every byte; a schema of another version is tried only after the matching one.
"""
import argparse
import collections
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
REPO = paths.REPO
from packfs import PackFS, key  # noqa: E402

GAME = paths.TARGET
OUT = os.path.join(REPO, 'discovery', 'db')
TABLES = os.path.join(OUT, 'tables.json')
SCHEMA = paths.adapter_file('db_schema.json')
SCHEMA_REL = os.path.relpath(SCHEMA, REPO).replace(os.sep, '/')
ROWS = os.path.join(REPO, 'extract', GAME, 'db')
GUID_MARKER = b'\xfd\xfe\xfc\xff'
VERSION_MARKER = b'\xfc\xfd\xfe\xff'
UI_TABLES = ('units', 'buildings', 'factions', 'agents', 'technologies', 'ancillaries', 'traits')


class Reader:
    __slots__ = ('b', 'o')

    def __init__(self, b, o=0):
        self.b, self.o = b, o

    def take(self, fmt, n):
        v = struct.unpack_from(fmt, self.b, self.o)[0]
        self.o += n
        return v

    def string(self, wide):
        n = self.take('<H', 2) * (2 if wide else 1)
        if self.o + n > len(self.b):
            raise ValueError(f'string overrun at {self.o}')
        v = self.b[self.o:self.o + n].decode('utf-16-le' if wide else 'utf-8', 'replace')
        self.o += n
        return v

    def boolean(self):
        v = self.take('<B', 1)
        if v > 1:
            raise ValueError(f'bad bool {v} at {self.o - 1}')
        return bool(v)


SCALARS = {'I32': ('<i', 4), 'F32': ('<f', 4), 'I16': ('<h', 2), 'I64': ('<q', 8), 'F64': ('<d', 8), 'U32': ('<I', 4)}


def read_field(r, t):
    if t == 'Boolean':
        return r.boolean()
    if t in SCALARS:
        v = r.take(*SCALARS[t])
        return round(v, 6) if t == 'F32' else v
    if t in ('StringU8', 'StringU16'):
        return r.string(t == 'StringU16')
    if t in ('OptionalStringU8', 'OptionalStringU16'):
        return r.string(t.endswith('U16')) if r.boolean() else None
    raise ValueError(f'unsupported field type {t}')


def parse_header(b):
    """(guid or None, version, mark byte, declared rows, offset of the first row)."""
    o, guid = 0, None
    if b[:4] == GUID_MARKER:
        n = struct.unpack_from('<H', b, 4)[0]
        guid = b[6:6 + n * 2].decode('utf-16-le')
        o = 6 + n * 2
    version = 0
    if b[o:o + 4] == VERSION_MARKER:
        version = struct.unpack_from('<I', b, o + 4)[0]
        o += 8
    return guid, version, b[o], struct.unpack_from('<I', b, o + 1)[0], o + 5


def decode_rows(b, start, count, fields):
    r = Reader(b, start)
    types = [f['type'] for f in fields]
    return [[read_field(r, t) for t in types] for _ in range(count)], r.o


def decode_table(b, versions):
    """{version, rows_declared, status (decoded | decoded_with_vN | empty | failed | no_schema), ...}; byte-exact or not decoded."""
    guid, version, mark, count, start = parse_header(b)
    res = {'version': version, 'rows_declared': count, 'guid': guid is not None}
    errors = []
    for how, group in (('exact', [v for v in versions if v['version'] == version]),
                       ('other', [v for v in versions if v['version'] != version])):
        for v in group:
            try:
                rows, end = decode_rows(b, start, count, v['fields'])
            except (ValueError, struct.error, IndexError) as e:
                errors.append(f"v{v['version']}: {e}")
                continue
            if end != len(b):
                errors.append(f"v{v['version']}: consumed {end} of {len(b)} bytes")
                continue
            res.update(status='decoded' if how == 'exact' else f"decoded_with_v{v['version']}", schema_version=v['version'],
                       fields=v['fields'], rows=rows)
            return res
    if count == 0 and start == len(b):
        res['status'] = 'empty'
    else:
        res.update(status='failed' if versions else 'no_schema', errors=errors[:4])
    return res


def table_name(path):
    parts = key(path).split('\\')
    folder = parts[1] if len(parts) > 2 else parts[-1]
    return folder[:-7] if folder.endswith('_tables') else folder


def with_inherited(fields, versions):
    """The decoded version's fields; a field the schema leaves without key or ref takes them from the newest other version
    with a field of the same name, marked inherited_from (RPFM marks keys and refs mostly on newer versions)."""
    out = []
    for f in fields:
        d = {k: f[k] for k in ('name', 'type', 'key', 'ref') if k in f}
        if not d['key'] or 'ref' not in d:
            for v in sorted(versions, key=lambda v: -v['version']):
                g = next((g for g in v['fields'] if g['name'] == f['name']), None)
                if g and ((g['key'] and not d['key']) or (g.get('ref') and 'ref' not in d)):
                    if g['key'] and not d['key']:
                        d['key'] = True
                    if g.get('ref') and 'ref' not in d:
                        d['ref'] = g['ref']
                    d['inherited_from'] = v['version']
                    break
        out.append(d)
    return out


def load_schema(path=SCHEMA):
    try:
        d = json.load(open(path, encoding='utf-8'))
        return d['source'], d['tables']
    except (OSError, ValueError, KeyError):
        return None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--games', default=paths.adapter_file('games.json'))
    a = ap.parse_args(argv)
    fs = PackFS.from_games(json.load(open(a.games, encoding='utf-8')), GAME)
    source, schema = load_schema()
    os.makedirs(ROWS, exist_ok=True)
    out = []
    for c in fs.list(under='db\\'):
        b = fs.read(c)
        t = table_name(c.path)
        e = {'name': t, 'file': c.path, 'pack': c.source, 'bytes': c.size, 'sha256': hashlib.sha256(b).hexdigest()}
        try:
            d = decode_table(b, (schema or {}).get(t + '_tables', []))
        except (ValueError, struct.error, IndexError) as ex:
            out.append({**e, 'version': None, 'rows': None, 'guid': None, 'decoded': False, 'reason': f'header: {ex}'})
            continue
        e.update(version=d['version'], rows=d['rows_declared'], guid=d['guid'])
        if schema is None:
            e.update(decoded=None, reason=f'no schema committed ({SCHEMA_REL})')
        elif d['status'].startswith('decoded'):
            e.update(decoded=True, schema_version=d['schema_version'],
                     fields=with_inherited(d['fields'], schema.get(t + '_tables', [])))
            if d['status'] != 'decoded':
                e['reason'] = f"file version {d['version']}, decoded with schema v{d['schema_version']}"
            with open(os.path.join(ROWS, key(c.path).replace('\\', '__') + '.json'), 'w', encoding='utf-8', newline='\n') as f:
                json.dump({'fields': [x['name'] for x in d['fields']], 'rows': d['rows']}, f, ensure_ascii=False)
        elif d['status'] == 'empty':
            e.update(decoded=True, reason='0 rows')
        else:
            e.update(decoded=False, reason=d['status'] + (': ' + '; '.join(d['errors']) if d.get('errors') else ''))
        out.append(e)
    doc = {'schema': 1, 'schema_source': source, 'tables': sorted(out, key=lambda x: x['file'].lower())}
    os.makedirs(OUT, exist_ok=True)
    with open(TABLES, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write('\n')
    ok = sum(1 for x in out if x['decoded'])
    print(f'{TABLES}: {len(out)} table files, {ok} decoded' + ('' if schema else ' (no schema: index only)'))
    return 0


def inbound(tables):
    """{table: number of fields in other tables that reference it}."""
    c = collections.Counter()
    for t in tables:
        for f in t.get('fields', []):
            if f.get('ref') and f['ref']['table'] != t['name']:
                c[f['ref']['table']] += 1
    return c


def readme(doc):
    ts = doc['tables']
    src = doc.get('schema_source')
    ok = [t for t in ts if t['decoded']]
    bad = [t for t in ts if t['decoded'] is False]
    out = [f'# {paths.titled(paths.TARGET)} db tables (J7)', '',
           'Generated by `python3 core/wsc.py discovery render` from `tables.json` (written by `discovery/core/db.py`). Do not edit.',
           f'Row values are never committed: decoded rows go to `/extract/{paths.TARGET}/db/`.', '']
    if src:
        out += [f"Schema: `{src['url']}` at `{src['commit'][:12]}` (sha256 `{src['file_sha256'][:16]}…`, {src['licence']}).", '']
    else:
        out += ['Schema: **none committed yet**, so this is the index only (names, versions, row counts, hashes). '
                f'Decode: `{SCHEMA_REL}` from `discovery/core/ron2json.py`, then `wsc discovery db`.', '']
    vers = collections.Counter(t['version'] for t in ts)
    out += ['| Table files | Decoded byte-exact | Not decoded | Versions |', '|---|---|---|---|',
            f"| {len(ts)} | {len(ok) if src else '-'} | {len(bad) if src else '-'} | "
            + ', '.join(f'v{v}: {n}' for v, n in sorted(vers.items(), key=lambda x: (x[0] is None, x[0] or 0))) + ' |', '']
    if bad:
        out += ['## Not decoded', '', '| Table | Version | Rows | Reason |', '|---|---|---|---|']
        out += [f"| {t['name']} | {t['version']} | {t['rows']} | {t['reason'][:110].replace('|', '/')} |" for t in bad]
        out.append('')
    if ok and src:
        inb = inbound(ts)
        out += ['## Reference graph of the tables UI work reads most', '',
                'Most referenced tables first (count of fields elsewhere that point at them), then what each one points at. RPFM marks',
                f'keys and refs mostly on newer table versions than {paths.titled(paths.TARGET)} ships, so a key or ref the decoded version lacks is taken from',
                f"the newest version with that field name (`inherited_from` in `tables.json`: "
                f"{sum(1 for t in ts for f in t.get('fields', []) if 'inherited_from' in f)} fields).", '',
                '| Table | Referenced by (fields) | Key | Refers to |', '|---|---|---|---|']
        by = {t['name']: t for t in ts}
        pick = {t for t, _ in inb.most_common(12)} | {t for t in UI_TABLES if t in by}
        for name in sorted(pick, key=lambda t: (-inb[t], t)):
            t = by.get(name, {})
            keys = ', '.join(f['name'] for f in t.get('fields', []) if f.get('key')) or '-'
            refs = sorted({f"{f['ref']['table']}.{f['ref']['column']}" for f in t.get('fields', []) if f.get('ref')})
            out.append(f"| {name} | {inb[name]} | {keys} | {', '.join(refs)[:160] or '-'} |")
        out.append('')
    return '\n'.join(out)


if __name__ == '__main__':
    sys.exit(main())
