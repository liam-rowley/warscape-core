#!/usr/bin/env python3
"""Build the engine Lua API surface table from the api_surface.lua probe lines of a run, and check it against J6's static diff.

purpose: read the "api <state> <owner> <name>:<type> ..." lines that proxy/<game>/lua/probes/api_surface.lua logs and the "sample ..." lines of the getter probe (in the runs' committed proxy logs), merge them per name (owner, kind, C or Lua, the states where it exists, observed type, getter samples), merge the static binding map <adapter>/lua_cfuncs.json (address and argument counts per C function) and answer the open questions of J6's static Lua API diff (discovery/diff/lua_api.json: are its new and gone names there at runtime, which argument-count drifts are real); writes <adapter>/engine_api.json
usage: python3 discovery/engine_api.py build --run harness/runs/<id> [--run ...] [--out <adapter>/engine_api.json] [--check] | probe-safe [--lua <file>] [--check]
when: after a PC run of the api_surface probe (J9; again after a game update); --check in review rebuilds the table from the committed logs
not-a-verb: a discovery pass over committed run evidence, writing one discovery table; outside the wsc registry operations

Owners: `S` = the pumping script's own environment, `G` = the globals it falls back to (its metatable __index chain and _G: the engine
tables live there); `G.<table>` / `S.<table>` = one level into a table (CampaignUI, BattleUI, FrontEnd, ...); `<owner>#mt` and
`<owner>#index` = a table's or userdata's metatable and its __index table; `R.<key>` = a string-keyed table of the Lua registry (Lunar classes and their
method tables, no object needed). Kind: `event` for an On* name, `method` for a registry class entry, `function` for a function in a
global table, `global` otherwise. `impl`: `C` when the static map gives the binding's address, `Lua` for a function in the script
environment (`S`, `S.<table>`); unset otherwise. The surface probe calls nothing; getter samples come from the separate getter probe,
which calls only the committed probe-safe list (`probe-safe`: C bindings that read no argument, named as getters, no action verb).
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
REPO = paths.REPO
OUT = paths.adapter_file('engine_api.json')
DIFF = os.path.join(REPO, 'discovery', 'diff', 'lua_api.json')
CFUNCS = paths.adapter_file('lua_cfuncs.json')
CFUNCS_REL = os.path.relpath(CFUNCS, REPO).replace(os.sep, '/')   # as the committed outputs name it   # J9 static RE: binding addresses and argument counts
LINE = re.compile(r'\] lua: api (\S+) (\S+) (.*)$')
END = re.compile(r'\] lua: api (\S+) __end total=(\d+)')
SAMPLE = re.compile(r'\] lua: sample (\S+) (\S+) (\S+) (\S+) ?(.*)$')   # state owner name type|error value
SAFE = paths.adapter_file('probe_safe.json')
SAFE_TABLES = ('CampaignUI', 'BattleUI', 'FrontEnd')
SAFE_PREFIX = ('Get', 'Is', 'Has', 'Can', 'Current', 'Player', 'Num', 'Number', 'Count', 'Total', 'Max', 'Min', 'Local', 'Screen',
               'Retrieve', 'Faction', 'Battle', 'Campaign', 'Turn', 'Season', 'Year', 'Date', 'Game', 'Version', 'Selected', 'Camera')
UNSAFE = ('Set', 'Start', 'End', 'Exit', 'Quit', 'Save', 'Load', 'Show', 'Hide', 'Toggle', 'Trigger', 'Send', 'Open', 'Close',
          'Cancel', 'Accept', 'Decline', 'Kick', 'Join', 'Host', 'Create', 'Delete', 'Destroy', 'Play', 'Stop', 'Pause', 'Request',
          'Issue', 'Order', 'Select', 'Enable', 'Disable', 'Clear', 'Reset', 'Restart', 'Continue', 'Notify', 'Inform', 'Move',
          'Zoom', 'Attach', 'Steam', 'MP', 'Multiplayer', 'Chat', 'Voice', 'Invite', 'Swap', 'Add', 'Remove', 'Dismiss', 'Abort',
          'Apply', 'Build', 'Recruit', 'Disband', 'Merge', 'Promote', 'Fire', 'Appoint', 'Release', 'Lock', 'Unlock', 'Debug',
          'Cheat', 'Console', 'Execute', 'Run', 'Call', 'Simulate', 'Generate', 'Autoresolve', 'Auto', 'Next', 'Previous', 'Write',
          'Friend', 'Friends', 'Online', 'Editor', 'Unpause', 'Replay')
DOC_UNSAFE = ('update', 'moves', 'invoke', 'notify', 'sets ', 'fire', 'trigger', 'start', 'open', 'close', 'kill')
# a state whose label says more than the launch reached: the note goes into its `states` entry so a reader of the table is not misled
# (J9 review round 2: ShowPrestige() errored, so the block labelled campaign_show_prestige is not the prestige panel)
STATE_NOTES = {
    'campaign_show_prestige': 'not the prestige panel: ShowPrestige() errored in Huds.lua:51 (it needs the arguments its menu button '
                              'passes), so this is the surface with the technology and missions panels still up (run 20261101_j9fix README)',
}
# names the static diff caught from a non-game (build-system) script; they are not engine API
BUILD_SYSTEM = {'buildcommands', 'project', 'solution', 'configuration', 'configurations', 'files', 'includedirs', 'links', 'kind',
                'language', 'location', 'targetdir', 'objdir', 'defines', 'flags', 'buildoptions', 'linkoptions', 'libdirs'}


def parse_logs(paths):
    """{state: {owner: {name: type}}}, {state: probe total}, [dropped blocks]. A probe run is one block of lines ended by its __end line;
    when a state has several blocks (a stale request from a killed client can run in the next launch, in another context: J9 chain 4),
    only the last complete block counts and the others are listed as dropped"""
    blocks = {}
    for p in sorted(paths):
        cur = {}
        with open(p, encoding='utf-8', errors='replace') as f:
            for line in f:
                m = END.search(line)
                if m:
                    state = m.group(1)
                    blocks.setdefault(state.split('@')[0], []).append((state, os.path.basename(p), int(m.group(2)), cur.pop(state, {})))
                    continue
                m = LINE.search(line)
                if not m:
                    continue
                state, owner, rest = m.groups()
                d = cur.setdefault(state, {}).setdefault(owner, {})
                for item in rest.split(' '):
                    name, _, typ = item.rpartition(':')
                    if name:
                        d[name] = typ
    seen, totals, dropped = {}, {}, []
    for state, bl in blocks.items():
        for label, log, total, owners in bl[:-1]:
            dropped.append({'state': label, 'log': log, 'probe_total': total})
        label, log, total, owners = bl[-1]
        seen[state], totals[state] = owners, total
    return seen, totals, dropped


def kind(owner, name, typ):
    if name.startswith('On') and name[2:3].isupper():
        return 'event'
    if owner.startswith('R.'):
        return 'method' if typ == 'function' else 'field'
    if owner[:2] in ('G.', 'S.') and typ == 'function':
        return 'function'
    return 'global'


def merge(seen):
    names = {}
    for state, owners in seen.items():
        for owner, d in owners.items():
            for name, typ in d.items():
                key = f'{owner}:{name}'
                e = names.setdefault(key, {'owner': owner, 'name': name, 'kind': kind(owner, name, typ), 'types': {}, 'states': []})
                e['types'][state] = typ
                if state not in e['states']:
                    e['states'].append(state)
    for e in names.values():
        e['states'].sort()
        types = set(e['types'].values())
        e['type'] = types.pop() if len(types) == 1 else 'varies'
        if e['type'] != 'varies':
            del e['types']
    return names


def j6_answers(names, diff_path=DIFF):
    """J6's static names (new / gone against the reference game) against the runtime surface: which exist in any probed state"""
    if not os.path.exists(diff_path):
        return {}
    with open(diff_path, encoding='utf-8') as f:
        d = json.load(f)['detail']['names']
    runtime = {}
    for e in names.values():
        if e['owner'][:2] in ('G.', 'S.') and '#' not in e['owner']:
            runtime.setdefault(f"{e['owner'][2:]}.{e['name']}", e['states'])
    methods = {e['name'] for e in names.values() if e['owner'].startswith('R.') or '#' in e['owner']}
    out = {}
    for group in ('CampaignUI.*', 'BattleUI.*', 'FrontEnd.*'):
        g = d.get(group, {})
        res = {}
        for status in ('new', 'gone'):
            want = sorted(n for n, s in g.items() if s == status)
            res[status] = {'static': len(want), 'at_runtime': [n for n in want if n in runtime],
                           'not_at_runtime': [n for n in want if n not in runtime]}
        out[group] = res
    comp = d.get('component methods', {})
    new_methods = sorted(n.split('.')[-1] for n, s in comp.items() if s == 'new')
    out['component methods'] = {'new_static': len(new_methods), 'found': [m for m in new_methods if m in methods],
                                'not_found': [m for m in new_methods if m not in methods]}
    out['build_system_names_dropped'] = sorted(BUILD_SYSTEM)
    return out


def add_cfuncs(names, path=CFUNCS):
    """merge the static binding map (address, argument counts read by the C function) into the runtime names; J6's drift verdicts out"""
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        cf = json.load(f)
    by = {(t, e['name']): e for t, v in cf.get('tables', {}).items() for e in v.get('entries', [])}
    for e in names.values():
        table = e['owner'].split('.', 1)[1].split('#')[0] if '.' in e['owner'] else None
        hit = by.get((table, e['name']))
        if hit:
            for k in ('va', 'static_args', 'static_args_min', 'checks_gettop'):
                if hit.get(k) is not None:
                    e[k] = hit[k]
    return cf.get('j6_arg_drift', [])


def _has_probe(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return any(LINE.search(line) or END.search(line) or SAMPLE.search(line) for line in f)


def parse_samples(paths):
    """{(owner, name): {state: {'type': t, 'value': v} | {'error': msg}}} from the getter probe's lines; the last line per state wins"""
    out = {}
    for p in sorted(paths):
        with open(p, encoding='utf-8', errors='replace') as f:
            for line in f:
                m = SAMPLE.search(line)
                if m:
                    state, owner, name, typ, value = m.groups()
                    rec = {'error': value} if typ == 'error' else {'type': typ, 'value': value}
                    out.setdefault((owner, name), {})[state.split('@')[0]] = rec
    return out


def add_impl_and_samples(names, samples):
    """`impl` C for a mapped binding, Lua for a function of the script environment; getter samples per state"""
    for e in names.values():
        if 'va' in e:
            e['impl'] = 'C'
        elif (e['owner'] == 'S' or e['owner'].startswith('S.')) and e.get('type') == 'function':
            e['impl'] = 'Lua'
        smp = samples.get((e['owner'], e['name']))
        if smp:
            e['samples'] = dict(sorted(smp.items()))


def probe_safe(cf_path=CFUNCS):
    """the committed list the getter probe may call: C bindings of CampaignUI / BattleUI / FrontEnd that read no argument (static
    count 0, minimum 0), whose names start like a getter and contain no action verb"""
    with open(cf_path, encoding='utf-8') as f:
        cf = json.load(f)
    rows = []
    for t in SAFE_TABLES:
        for e in cf['tables'].get(t, {}).get('entries', []):
            n = e['name']
            if e.get('static_args') != 0 or e.get('static_args_min') not in (0, None):
                continue
            doc = (e.get('doc') or '').lower()
            words = {w.lower() for w in re.findall(r'[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+', n)}   # camel-case words: MP, Can, Sack
            if '_' in n or not n.startswith(SAFE_PREFIX) or words & {w.lower() for w in UNSAFE} or any(w in doc for w in DOC_UNSAFE):
                continue
            rows.append({'table': t, 'name': n, 'va': e.get('va'), 'doc': (e.get('doc') or '')[:120]})
    rows.sort(key=lambda r: (r['table'], r['name']))
    return {'generator': 'discovery/core/engine_api.py probe-safe', 'source': CFUNCS_REL,
            'rule': 'C bindings of ' + ', '.join(SAFE_TABLES) + ' with static_args 0 and static_args_min 0, name starting with one of '
                    + ' '.join(SAFE_PREFIX) + ', containing none of ' + ' '.join(UNSAFE) + ' (as a camel-case word), no underscore (order commands such as Current_Selection_Halt), doc without '
                    + ' / '.join(DOC_UNSAFE), 'getters': rows}


def safe_lua(doc):
    """the list as a Lua chunk returning { {table, name}, ... } for the getter probe"""
    items = ',\n'.join('  { "%s", "%s" }' % (r['table'], r['name']) for r in doc['getters'])
    return ('-- generated by discovery/core/engine_api.py probe-safe from ' + CFUNCS_REL + ': do not edit\n'
            'return {\n' + items + '\n}\n')


def _rel(p):
    """A path relative to REPO as the committed outputs name it; a path on another drive (Windows) stays absolute."""
    try:
        return os.path.relpath(p, REPO).replace(os.sep, '/')
    except ValueError:
        return os.path.abspath(p).replace(os.sep, '/')


def build(runs):
    logs = [p for run in runs for p in glob.glob(os.path.join(run, 'raw', '*_proxy.log'))]
    seen, totals, dropped = parse_logs(logs)
    samples = parse_samples(logs)
    # list only the logs that carry probe lines: a run folder also holds proof launches without the probe, and adding one must not
    # make the committed table stale (J9 review round 1)
    logs = [p for p in logs if _has_probe(p)]
    names = merge(seen)
    drift = add_cfuncs(names)
    add_impl_and_samples(names, samples)
    rows = sorted(names.values(), key=lambda e: (e['owner'], e['name']))
    per_state = {s: {'names': sum(len(d) for d in o.values()), 'probe_total': totals.get(s),
                     'owners': len(o), **({'note': STATE_NOTES[s]} if s in STATE_NOTES else {})} for s, o in sorted(seen.items())}
    return {'generator': 'discovery/core/engine_api.py', 'runs': [r.replace('\\', '/') for r in runs],
            'logs': sorted(_rel(p) for p in logs),
            'states': per_state, 'dropped_blocks': dropped, 'j6': j6_answers(names), 'j6_arg_drift': drift, 'names': rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--run', required=True, action='append', help='a run folder with raw/*_proxy.log; repeat for several runs')
    b.add_argument('--out', default=OUT)
    b.add_argument('--check', action='store_true')
    ps = sub.add_parser('probe-safe')
    ps.add_argument('--out', default=SAFE)
    ps.add_argument('--lua', help='also write the list as a Lua chunk (the getter probe loads it)')
    ps.add_argument('--check', action='store_true')
    a = ap.parse_args(argv)
    if a.cmd == 'probe-safe':
        doc = probe_safe()
        text = json.dumps(doc, indent=1, ensure_ascii=False) + '\n'
        if a.check:
            with open(a.out, encoding='utf-8') if os.path.exists(a.out) else open(os.devnull, encoding='utf-8') as f:
                same = f.read() == text
            print(f'engine_api probe-safe --check: {"ok" if same else "DIFFERS"} - {len(doc["getters"])} getters')
            return 0 if same else 1
        with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        if a.lua:
            with open(a.lua, 'w', encoding='utf-8', newline='\n') as f:
                f.write(safe_lua(doc))
        print(f'wrote {a.out}: {len(doc["getters"])} probe-safe getters' + (f' and {a.lua}' if a.lua else ''))
        return 0
    doc = build([os.path.relpath(os.path.abspath(r), REPO) for r in a.run])
    text = json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + '\n'
    summary = ', '.join(f"{s} {v['names']}" for s, v in doc['states'].items())
    if a.check:
        with open(a.out, encoding='utf-8') if os.path.exists(a.out) else open(os.devnull, encoding='utf-8') as f:
            same = f.read() == text
        print(f'engine_api --check: {"ok" if same else "DIFFERS"} - {summary}')
        return 0 if same else 1
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print(f'wrote {a.out}: {len(doc["names"])} names; {summary}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
