#!/usr/bin/env python3
"""Index every string of a 32-bit Warscape exe with the code and data that reference it, and search the committed index.

purpose: list each ASCII and UTF-16LE string (4+ printable characters, NUL-terminated) in the exe's non-executable sections with its RVA, section, the code sites whose relocated operand points at it (count and first four instruction RVAs) and the data dwords that point at it (count and first two: name tables, Lua registration tables), into a sorted deterministic tsv.gz; `find` searches that table without the RE venv
usage: <re venv python> -I discovery/exe_strings.py build <exe> [--out <adapter>/exe_strings.tsv.gz] [--check]; python3 discovery/exe_strings.py find <regex> [--table ...] [--refs] [-n 50]; or wsc find <word> (exe-shaped words, as literals)
when: J9 and every later RE session on the exe: `find` a tweaker, Lua or prefs name first, then x86re.py on the code RVAs it lists; build again (and --check in review) after a game update
not-a-verb: reads a game exe in place (read only) and writes one discovery table; outside the wsc registry operations

RVAs are offsets from the image base (the proxy's engine_sites rva); VA = 0x400000 + RVA at the preferred base. A code reference is
the instruction holding a relocated dword equal to the string's VA (push imm, mov reg/mem imm, lea): the image has a full relocation
table, so every absolute use is found. Strings embedded in a longer string (a tail of another) are not listed separately, and a tail
reference (pointer into the middle of a string) counts for no row. `build` needs capstone and pefile (discovery/re_env.py).
"""
import argparse
import bisect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tsvgz  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
TABLE = paths.adapter_file('exe_strings.tsv.gz')
HEADER = ['rva', 'section', 'enc', 'chars', 'code_refs', 'code_first', 'data_refs', 'data_first', 'text']
ASCII = re.compile(rb'[\x20-\x7e\t]{4,}(?=\x00)')
UTF16 = re.compile(rb'(?:[\x20-\x7e\t]\x00){4,}(?=\x00\x00)')
EXEC = 0x20000000   # IMAGE_SCN_MEM_EXECUTE


def scan(im):
    """[(va, section, enc, text)] for every string in a file-backed, non-executable section"""
    out = []
    for s in im.pe.sections:
        if s.Characteristics & EXEC:
            continue
        name = s.Name.rstrip(b'\0').decode()
        start = im.base + s.VirtualAddress
        data = bytes(im.img[s.VirtualAddress: s.VirtualAddress + min(s.SizeOfRawData, s.Misc_VirtualSize)])
        for m in ASCII.finditer(data):
            if m.start() and 0x20 <= data[m.start() - 1] <= 0x7e:
                continue    # a tail of a longer run the regex already took (cannot happen with finditer, kept as a guard)
            out.append((start + m.start(), name, 'a', m.group().decode('latin1')))
        for m in UTF16.finditer(data):
            if m.start() % 2:
                continue    # UTF-16 strings are 2-aligned; an odd hit is an ASCII run read as wide characters
            out.append((start + m.start(), name, 'u', m.group().decode('utf-16-le')))
    return out


def ref_index(im):
    """{dword value: ([code reloc locations], [data reloc locations])} over every HIGHLOW relocation"""
    tx0, txsz = im.text[1], im.text[2]
    idx = {}
    for loc in im.relocs():
        v = im.u32(loc)
        idx.setdefault(v, ([], []))[0 if tx0 <= loc < tx0 + txsz else 1].append(loc)
    return idx


def build(exe):
    import x86re
    im = x86re.Image(exe)
    idx = ref_index(im)
    rows = []
    for va, sec, enc, text in scan(im):
        code, data = idx.get(va, ([], []))
        first = []
        for loc in code[:4]:
            i = im.insn_containing(loc)
            first.append(f'0x{(i.address if i else loc) - im.base:07x}')
        rows.append((f'0x{va - im.base:07x}', sec, enc, len(text), len(code), ' '.join(first), len(data),
                     ' '.join(f'0x{d - im.base:07x}' for d in data[:2]), text))
    return rows


def search(table, pattern, refs_only=False):
    """The rows of the table whose string text matches `pattern` (a regex string or compiled); `refs_only`: only referenced strings.
    `wsc find` calls it for exe-shaped words."""
    _, rows = tsvgz.read(table)
    rx = re.compile(pattern) if isinstance(pattern, str) else pattern
    return [r for r in rows if rx.search(r[8]) and (not refs_only or r[4] != '0' or r[6] != '0')]


def line(r):
    """One printed hit: RVA, section, encoding, code and data references, the string."""
    code = f'code {r[4]}' + (f' [{r[5]}]' if r[5] else '')
    data = f'data {r[6]}' + (f' [{r[7]}]' if r[7] else '')
    return f'{r[0]} {r[1]:<6} {r[2]} {code:<52} {data:<30} {r[8]!r}'


def find(table, pattern, refs_only=False, limit=50):
    hits = search(table, pattern, refs_only)
    for r in hits[:limit]:
        print(line(r))
    if len(hits) > limit:
        print(f'... {len(hits) - limit} more (-n to show more)')
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('exe')
    b.add_argument('--out', default=TABLE)
    b.add_argument('--check', action='store_true', help='rebuild in memory and compare with --out (rows, not gzip bytes); exit 1 if it differs')
    f = sub.add_parser('find')
    f.add_argument('pattern', help='Python regex, searched in the string text')
    f.add_argument('--table', default=TABLE)
    f.add_argument('--refs', action='store_true', help='only strings that code or data reference')
    f.add_argument('-n', type=int, default=50)
    a = ap.parse_args(argv)
    if a.cmd == 'find':
        return 0 if find(a.table, a.pattern, a.refs, a.n) else 1
    rows = build(a.exe)
    data = tsvgz.dumps(HEADER, [tuple(tsvgz.cell(v) for v in r) for r in rows])
    n_code = sum(1 for r in rows if r[4])
    summary = f'{len(rows)} strings ({sum(r[2] == "u" for r in rows)} UTF-16), {n_code} referenced by code, {len(data) / 1e6:.2f} MB'
    if a.check:   # inflated text, not the gzip bytes: zlib and zlib-ng deflate the same text differently (tsvgz.problems)
        same = not tsvgz.problems(a.out, HEADER) and tsvgz.read(a.out)[1] == sorted(tuple(tsvgz.cell(v) for v in r) for r in rows)
        print(f'exe_strings --check: {"ok" if same else "DIFFERS"} - {summary}')
        return 0 if same else 1
    with open(a.out, 'wb') as fh:
        fh.write(data)
    print(f'wrote {a.out}: {summary}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
