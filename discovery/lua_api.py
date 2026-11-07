#!/usr/bin/env python3
"""Lua API pass of the reference-to-target-game diff: engine globals, table APIs, component methods, event names, loose entry points.

purpose: run the ported API inventory over a game's compiled UI scripts and diff the engine API names against the reference game's engine_api.json (same | adapter | new | gone per family)
usage: python3 discovery/lua_api.py [--games <adapter>/games.json] [--out discovery/diff/lua_api.json]
when: J6 Lua API area; re-run after a game update (deterministic output, so a git diff shows what changed); J9 starts its per-screen API surface from the name lists
not-a-verb: reads extracted game scripts (git-ignored /extract/) and the reference game's engine_api.json read-only, outside the wsc registry operations

Inputs: extract/<game>/<pack>/ui/**/*.luac via extracted.effective (patch-pack precedence), the reference game's rml_mod/docs/engine_api.json
(games.json <reference>.repo), the target game's plain Lua libraries (extract/<target>/data/*.lua) and the loose all_scripted.lua / battle_scripted.lua.
Names only are committed (no bytecode). The names are static: a call seen in bytecode may never run, and a name absent here may still exist
in the engine (J9 probes per screen).
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import luachunk  # noqa: E402
from api_inventory import Inventory  # noqa: E402
from diffout import row, write  # noqa: E402
import paths  # noqa: E402
from extracted import REPO, effective, load_games  # noqa: E402

BACKSLASH = chr(92)
ENGINE_API = 'rml_mod/docs/engine_api.json'


def inventory(files):
    """Run Inventory over {entry path: file}; returns (Inventory.to_json() dict, {script: counts}, [failed])."""
    inv, per_file, failed = Inventory(), {}, []
    for path, fp in files.items():
        with open(fp, 'rb') as fh:
            data = fh.read()
        rel = path.replace(BACKSLASH, '/')
        try:
            main = luachunk.parse(data).main
            one = Inventory()
            one.walk(rel, main)
            inv.walk(rel, main)
        except Exception as e:  # keep going: one bad script must not hide the rest
            failed.append([rel, repr(e)[:80]])
            continue
        j = one.to_json()
        per_file[rel] = {'calls': len(j['calls']), 'methods': len(j['methods']), 'events': len(j['events'])}
    return inv.to_json(), per_file, failed


def families(j):
    """Split an inventory JSON (api_inventory schema) into name sets by family, the way api_inventory.main does."""
    defined = set(j['defined'])
    engine = {k for k in j['calls'] if k.split('.')[0] not in defined}
    tables = collections.defaultdict(set)
    for k in engine:
        if '.' in k:
            tables[k.split('.')[0]].add(k)
    reads = {k for k in j['global_reads'] if k not in j['calls'] and k not in defined and k not in tables}
    return {
        'engine globals': {k for k in engine if '.' not in k},
        'component methods': set(j['methods']),
        'event names': set(j['events']),
        'engine globals read, not called': reads,
    }, dict(tables)


def arities(j):
    """{(kind, name): set of argument counts seen} for calls and methods (shared-name signature drift)."""
    out = {}
    for kind in ('calls', 'methods'):
        for k, v in j[kind].items():
            out[(kind, k)] = {0 if s == '()' else s.count(',') + 1 for s in v['sigs']}
    return out


def classify(emp, nap):
    """(verdict, adapter note) for two name sets."""
    emp, nap = set(emp), set(nap)
    if emp == nap:
        return 'same', ''
    if not nap:
        return 'gone', ''
    if not emp:
        return 'new', ''
    if not (emp & nap):
        return 'adapter', 'no shared names'
    return 'adapter', f'{len(nap - emp)} new, {len(emp - nap)} gone, {len(emp & nap)} shared'


def status(emp, nap):
    """{name: same | new | gone} over the union."""
    return {n: ('same' if n in emp and n in nap else 'new' if n in nap else 'gone') for n in sorted(set(emp) | set(nap))}


def lua_entry_points(text):
    """Names a plain Lua entry-point file touches: required modules, global function definitions, global assignments."""
    text = re.sub(r'--\[(=*)\[.*?\]\1\]', '', text, flags=re.S)
    text = re.sub(r'--[^\n]*', '', text)
    return {
        'require': sorted(set(re.findall(r'require\s*\(?\s*["\']([\w.]+)["\']', text))),
        'functions': sorted(set(re.findall(r'^\s*function\s+([\w.:]+)', text, flags=re.M))),
        'globals': sorted(set(re.findall(r'^([A-Za-z_]\w*)\s*=', text, flags=re.M))),
    }


def read_loose(root):
    out = {}
    d = os.path.join(root, 'data')
    for n in ('all_scripted.lua', 'battle_scripted.lua'):
        p = os.path.join(d, n)
        out[n] = None
        if os.path.isfile(p):
            with open(p, encoding='latin1') as fh:
                out[n] = lua_entry_points(fh.read())
    return out


def flat(loose):
    return {f'{n}:{k}:{x}' for n, v in loose.items() if v for k, xs in v.items() for x in xs}


def build(ref_json, nap_files, nap_lua, nap_loose, emp_loose):
    nj, per_file, failed = inventory(nap_files)
    ej = ref_json
    ef, et = families(ej)
    nf, nt = families(nj)
    ev = 'discovery/diff/lua_api.json (names); ' + ENGINE_API
    rows, names = [], {}

    def add(item, emp, nap, evidence=ev):
        v, note = classify(emp, nap)
        rows.append(row(item, f'{len(emp)} names', f'{len(nap)} names', v, note, evidence))
        names[item] = status(emp, nap)

    for fam in sorted(ef):
        add(fam, ef[fam], nf[fam])
    for t in sorted(set(et) | set(nt)):
        add(f'{t}.*', et.get(t, set()), nt.get(t, set()))
    # shared names whose argument counts differ (a call-shape change the name diff cannot see)
    ea, na = arities(ej), arities(nj)
    drift = sorted(f'{k[0]}:{k[1]}' for k in set(ea) & set(na) if ea[k] != na[k])
    rows.append(row('call argument counts (shared names)', f'{len(set(ea) & set(na))} shared names', f'{len(drift)} with other arg counts',
                    'same' if not drift else 'adapter', 'static: arg counts seen in bytecode, not signatures' if drift else '', ev))
    names['call argument counts (shared names)'] = {n: 'drift' for n in drift}
    add('loose entry points', flat(emp_loose), flat(nap_loose), 'data\\all_scripted.lua and battle_scripted.lua of both installs, read in place')
    rows.append(row('campaign Lua libraries (data pack root)', 'not extracted', f'{len(nap_lua)} files', 'new' if nap_lua else 'gone',
                    f'{paths.titled(paths.REFERENCE)} side not in the extract; J9 compares', f'extract/{paths.TARGET}/data/*.lua'))
    ok = len(nap_files) - len(failed)
    rows.append(row('inventory tool (api_inventory.py + luachunk.py)', f'runs on {paths.titled(paths.REFERENCE)} scripts', f'{ok}/{len(nap_files)} scripts parsed',
                    'same' if not failed else 'adapter', 'ported unchanged: same Lua 5.1 header (4-byte int and float)' if not failed else f'{len(failed)} scripts failed',
                    'discovery/core/api_inventory.py'))
    detail = {
        'names': names,
        'loose_entry_points': {n: {paths.REFERENCE: emp_loose.get(n), paths.TARGET: nap_loose.get(n)} for n in sorted(set(nap_loose) | set(emp_loose))},
        f'{paths.TARGET}_lua_libraries': nap_lua,
        f'{paths.TARGET}_scripts': {'count': len(nap_files), 'failed': failed, 'per_file': dict(sorted(per_file.items()))},
        f'{paths.REFERENCE}_scripts': {'count': len({s for v in ej['calls'].values() for s in v['scripts']}), 'source': ENGINE_API},
        'script_defined_globals': {paths.REFERENCE: len(ej['defined']), paths.TARGET: len(nj['defined'])},
        'note': 'static bytecode walk: names seen in calls, not proof of behaviour; J9 owns the per-screen API surface',
    }
    return rows, detail


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--games', default=None)
    ap.add_argument('--out', default=paths.result_dir('diff', 'lua_api.json'))
    a = ap.parse_args(argv)
    games = load_games(a.games)
    with open(os.path.join(games[paths.REFERENCE]['repo'], *ENGINE_API.split('/')), encoding='utf-8') as fh:
        ej = json.load(fh)
    nap_files = effective(games, paths.TARGET, exts={'.luac'}, under='ui' + BACKSLASH)
    nap_lua = sorted(p for p in effective(games, paths.TARGET, exts={'.lua'}) if BACKSLASH not in p)
    rows, detail = build(ej, nap_files, nap_lua, read_loose(games[paths.TARGET]['root']), read_loose(games[paths.REFERENCE]['root']))
    write(a.out, 'lua_api', rows, detail)
    for r in rows:
        print(f"{r['item']:45} {r[paths.REFERENCE]:>22} {r[paths.TARGET]:>22} {r['verdict']:8} {r['adapter']}")


if __name__ == '__main__':
    main()
