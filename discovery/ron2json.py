#!/usr/bin/env python3
"""Convert an RPFM schema_<game>.ron (Frodo45127/rpfm-schemas) into the compact db schema JSON the db pass reads.

purpose: parse an RPFM .ron db schema and write {source: {url, commit, file_sha256, licence}, tables: {name_tables: [{version, fields: [{name, type, key, ref}]}]}}
usage: python3 -I discovery/ron2json.py SCHEMA.ron OUT.json --url URL --commit SHA --licence MIT   (run with -I: the .ron is downloaded, untrusted data)
when: J7 db schema (<adapter>/db_schema.json); again when the schema pin moves; ported from empire-remastered rml_mod/tools/db/ron2json.py
not-a-verb: a one-off converter for a downloaded file, run when the schema pin changes
"""
import argparse
import hashlib
import json
import re
import sys

NAME = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*:')
NUM = re.compile(r'-?[0-9][0-9.eE+-]*')
WORD = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
ESC = {'n': '\n', 't': '\t', '"': '"', '\\': '\\', "'": "'"}


class Ron:
    def __init__(self, src):
        self.s, self.i, self.n = src, 0, len(src)

    def ws(self):
        s = self.s
        while self.i < self.n:
            if s[self.i] in ' \t\r\n':
                self.i += 1
            elif s.startswith('//', self.i):
                self.i = s.index('\n', self.i)
            else:
                break

    def val(self):
        self.ws()
        s, c = self.s, self.s[self.i]
        if c in '([':
            close = ')' if c == '(' else ']'
            self.i += 1
            out, lst = {}, []
            while True:
                self.ws()
                if s[self.i] == close:
                    self.i += 1
                    break
                m = NAME.match(s, self.i) if c == '(' else None
                if m and not s.startswith('::', m.end() - 1):
                    self.i = m.end()
                    out[m.group(1)] = self.val()
                else:
                    lst.append(self.val())
                self.ws()
                if s[self.i] == ',':
                    self.i += 1
            return out if out else lst
        if c == '{':
            self.i += 1
            d = {}
            while True:
                self.ws()
                if s[self.i] == '}':
                    self.i += 1
                    break
                k = self.val()
                self.ws()
                if s[self.i] != ':':
                    raise ValueError(f'expected : at {self.i}')
                self.i += 1
                d[k] = self.val()
                self.ws()
                if s[self.i] == ',':
                    self.i += 1
            return d
        if c == '"':
            j, out = self.i + 1, []
            while s[j] != '"':
                if s[j] == '\\':
                    j += 1
                    out.append(ESC.get(s[j], s[j]))
                else:
                    out.append(s[j])
                j += 1
            self.i = j + 1
            return ''.join(out)
        m = NUM.match(s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            return float(t) if any(ch in t for ch in '.eE') else int(t)
        m = WORD.match(s, self.i)
        self.i = m.end()
        w = m.group(0)
        self.ws()
        if w in ('None', 'true', 'false'):
            return {'None': None, 'true': True, 'false': False}[w]
        if self.i < self.n and s[self.i] == '(':
            inner = self.val()
            return {w: inner[0] if isinstance(inner, list) and len(inner) == 1 else inner}
        return w


def ref_of(r):
    if isinstance(r, dict):
        r = r.get('Some')
    if isinstance(r, list) and len(r) == 2:
        return {'table': r[0], 'column': r[1]}
    return None


def convert(root):
    out = {}
    for t, vers in root['definitions'].items():
        vl = []
        for v in vers:
            fl = []
            for f in v['fields']:
                ft = f['field_type']
                d = {'name': f['name'], 'type': ft if isinstance(ft, str) else json.dumps(ft, sort_keys=True), 'key': bool(f['is_key'])}
                r = ref_of(f.get('is_reference'))
                if r:
                    d['ref'] = r
                fl.append(d)
            vl.append({'version': v['version'], 'fields': fl})
        out[t] = sorted(vl, key=lambda v: v['version'])
    return dict(sorted(out.items()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('ron')
    ap.add_argument('out')
    ap.add_argument('--url', required=True)
    ap.add_argument('--commit', required=True)
    ap.add_argument('--licence', required=True)
    a = ap.parse_args(argv)
    raw = open(a.ron, 'rb').read()
    tables = convert(Ron(raw.decode('utf-8')).val())
    doc = {'source': {'url': a.url, 'commit': a.commit, 'file_sha256': hashlib.sha256(raw).hexdigest(), 'licence': a.licence,
                      'converted_by': 'discovery/core/ron2json.py'}, 'tables': tables}
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, indent=0, sort_keys=True)
        f.write('\n')
    print(f'{a.out}: {len(tables)} tables, {sum(len(v) for v in tables.values())} versions', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
