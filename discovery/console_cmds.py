#!/usr/bin/env python3
"""Extract a Warscape exe's console command dictionary (name, usage, help, handler, retail status) into a TSV, and diff it with the reference game's.

purpose: find every static initialiser that registers a console command (four string ctors, a handler push, a call to the dictionary's register function, found from one seed command name), classify each handler statically (no_op: a bare ret; parse_only: only reads its arguments or the selection; prints_only: only formats output the retail console never shows; acts: calls other engine code) and write the table; optional diff against empire-remastered's campaign_commands.tsv
usage: <re venv python> -I discovery/console_cmds.py <exe> --seed teleport_to --out <tsv> [--reference <the reference game's campaign_commands.tsv> --diff-out <tsv>] [--profile <adapter>/console.json]
when: J15 (the campaign dictionary behind `console`), and again after a game update; the proxy's no-op refusal list is generated from the TSV (proxy/tools/gen_console_table.py)
not-a-verb: reads a game exe in place (read only), outside the wsc registry operations

Static only: `acts` means the handler calls engine code, not that it does anything visible in game (PC runs decide that).
The helper sets (argument readers, string helpers, output writers) come from the profile JSON, so another build only needs new addresses.
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
from x86re import Image  # noqa: E402


def find_register(im, seed):
    """the register function: the first call after the seed name's push in its initialiser"""
    for s in im.find_str(seed):
        for r in im.refs(s):
            ins = im.dis(r - 1, 30)
            if not ins or ins[0].mnemonic != 'push':
                continue
            for i in ins[1:]:
                if i.mnemonic == 'call' and i.op_str.startswith('0x'):
                    t = int(i.op_str, 16)
                    if t != string_ctor_of(ins):
                        return t
    sys.exit(f'no initialiser found for seed {seed!r}')


def string_ctor_of(ins):
    for i in ins[1:]:
        if i.mnemonic == 'call':
            return int(i.op_str, 16)
    return None


def initialiser_start(im, call):
    """walk back from the register call to the initialiser's int3/ret boundary"""
    p = call
    while p > call - 0x100:
        if im.img[p - 1 - im.base] in (0xcc, 0xc3) and im.bytes_at(p, 3) == b'\x83\xec\x30':
            return p
        p -= 1
    return None


def records(im, reg):
    out = []
    for call in im.callers(reg):
        start = initialiser_start(im, call)
        if start is None:
            out.append({'call': call, 'error': 'no initialiser prologue'})
            continue
        strs, handler, ctor, record = [], None, None, None
        prev = None
        for i in im.dis(start, 60):
            if i.address >= call:
                break
            if i.mnemonic == 'push' and i.op_str.startswith('0x'):
                v = int(i.op_str, 16)
                if im.in_text(v):
                    handler = v
                else:
                    prev = v
            elif i.mnemonic == 'call' and prev is not None:
                ctor = int(i.op_str, 16) if i.op_str.startswith('0x') else ctor
                strs.append(im.cstr(prev))
                prev = None
            elif i.mnemonic == 'mov' and i.op_str.startswith('ecx, 0x'):
                record = int(i.op_str.split(',')[1], 16)
        if len(strs) != 4 or handler is None:
            out.append({'call': call, 'error': f'pattern: {len(strs)} strings, handler {handler}'})
            continue
        help_, usage, category, name = strs
        out.append({'call': call, 'name': name, 'usage': usage, 'help': help_, 'category': category,
                    'handler': handler, 'record': record})
    return out


def selection_call(im, at, prof):
    """an indirect call through the selection object: `mov ecx, [reg + <selection offset>]` in the 3 instructions before"""
    off = prof['selection_offset']
    for i in im.dis(at - 12, 8):
        if i.address >= at:
            break
        if i.mnemonic == 'mov' and i.op_str.startswith('ecx, dword ptr [') and i.op_str.endswith(f' + {off}]'):
            return True
    return False


def classify(im, handler, prof):
    w = im.walk(handler)
    if w.get('first', '').startswith('ret'):
        return 'no_op', 'handler is a bare ret'
    calls = {t for _, t in w['calls']}
    parse = set(int(x, 16) for x in prof['arg_readers'] + prof['string_helpers'] + prof.get('pure_getters', []))
    prints = set(int(x, 16) for x in prof['output_writers'])
    other = calls - parse - prints
    if w['tail']:
        other |= {t for _, t in w['tail']}
    other_icalls = [at for at in w['icalls'] + w['itail'] if not selection_call(im, at, prof)]   # an indirect tail jmp acts like an icall
    if not other and not other_icalls:
        if calls & prints:
            return 'prints_only', 'only formats output (the retail console shows none)'
        return 'parse_only', 'only reads its arguments or the selection'
    if not other:
        return 'acts', f'{len(other_icalls)} indirect calls or tail jumps (virtual or through a global)'
    return 'acts', f'calls {len(other)} engine functions'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('exe')
    ap.add_argument('--seed', default='teleport_to')
    ap.add_argument('--category', help='keep only this category (default: the seed command\'s)')
    ap.add_argument('--profile', default=paths.adapter_file('console.json'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--reference', help="the reference game's command TSV (columns name, retail_status)")
    ap.add_argument('--diff-out')
    a = ap.parse_args()
    prof = json.load(open(a.profile, encoding='utf-8'))
    im = Image(a.exe)
    reg = find_register(im, a.seed)
    recs = records(im, reg)
    errs = [r for r in recs if 'error' in r]
    good = [r for r in recs if 'error' not in r]
    seed = next(r for r in good if r['name'] == a.seed)
    cat = seed['category']
    rows = []
    for r in sorted(good, key=lambda r: r['name']):
        st, why = classify(im, r['handler'], prof)
        rows.append({'name': r['name'], 'status': st, 'category': r['category'], 'why': why, 'usage': r['usage'], 'help': r['help'],
                     'handler_rva': hex(r['handler'] - im.base), 'handler_va': hex(r['handler'])})
    names = [r['name'] for r in rows]
    dups = sorted({n for n in names if names.count(n) > 1})
    with open(a.out, 'w', newline='', encoding='utf-8') as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter='\t', lineterminator='\n')
        wr.writeheader()
        wr.writerows(rows)
    counts = {}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    print(f'register {hex(reg)}; {len(recs)} registrations, {len(errs)} unparsed; seed category {cat!r}; {len(rows)} commands {counts}'
          + (f'; duplicate names {dups}' if dups else ''))
    for e in errs:
        print(f'  unparsed at {hex(e["call"])}: {e["error"]}')
    for r in rows:
        if r['category'] != cat:
            print(f'  same dictionary, other category {r["category"]!r}: {r["name"]}')
    if a.reference:
        emp = {r['name']: r for r in csv.DictReader(open(a.reference, encoding='utf-8'), delimiter='\t')}
        nap = {r['name']: r for r in rows}

        def estat(s):
            return 'no_op' if s.startswith('NO-OP') else 'acts'

        def nstat(s):
            return 'no_op' if s in ('no_op', 'parse_only', 'prints_only') else 'acts'
        diff = []
        for n in sorted(set(emp) | set(nap)):
            if n not in emp:
                diff.append({'name': n, 'change': 'new', paths.REFERENCE: '', paths.TARGET: nap[n]['status']})
            elif n not in nap:
                diff.append({'name': n, 'change': 'gone', paths.REFERENCE: estat(emp[n]['retail_status']), paths.TARGET: ''})
            elif estat(emp[n]['retail_status']) != nstat(nap[n]['status']):
                diff.append({'name': n, 'change': 'status', paths.REFERENCE: estat(emp[n]['retail_status']), paths.TARGET: nap[n]['status']})
        if a.diff_out:
            with open(a.diff_out, 'w', newline='', encoding='utf-8') as f:
                wr = csv.DictWriter(f, fieldnames=['name', 'change', paths.REFERENCE, paths.TARGET], delimiter='\t', lineterminator='\n')
                wr.writeheader()
                wr.writerows(diff)
        c = {k: sum(1 for d in diff if d['change'] == k) for k in ('new', 'gone', 'status')}
        print(f'vs {paths.titled(paths.REFERENCE)} ({len(emp)} commands, {sum(1 for r in emp.values() if estat(r["retail_status"]) == "no_op")} no-ops): {c}')


if __name__ == '__main__':
    main()
