"""The discovery gate (PLAN phase 2, J11): every registry populated, every result current, the gaps said out loud.

purpose: check that each registry is above its floor (<adapter>/gate.json), that the row shapes the later phases rely on hold, that every committed result is what its inputs give (recomputed offline, never a green someone else saw) and print the findings table with its ratchet
usage: python3 core/wsc.py discovery gate [--install] [--write] [--json OUT]   (this module is a library; the verb is warscape/verbs/discovery.py)
when: after any discovery pass or registry change; `wsc discovery check` includes it, and the tests gate runs it on this repo (discovery/tests/test_discovery_gate.py)
not-a-verb: a library module; `wsc discovery gate` is the verb action

Offline mode needs only committed files. `--install` also compares the pack fingerprints in discovery/assets/summary.json and the exe sha1
with the installed game (read-only; PC only). Floors, the ratchet and the pinned index sha256 live in <adapter>/gate.json; the
committed result is discovery/gate/summary.json (deterministic: no clock, no counts that change with routine work). Findings never fail the
gate; a finding that grows past its recorded number does.
"""
import gzip
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
from paths import layout  # noqa: E402

JSONL = ('assets', 'ui_elements', 'engine_sites', 'hotkeys', 'config_keys', 'scenarios')
DIRS = ('jobs', 'tools', 'engine_facts')
REGISTRIES = JSONL + DIRS
UI_DONE = ('atlas', 'contract', 'design', 'locked', 'built', 'verified')   # atlas or later: every status in the schema
OWNER = re.compile(r'\b(J\d+|liam)\b', re.I)


# ------------------------------------------------------------------ inputs
def load_config(root):
    return json.loads((paths.adapter_for(root) / 'gate.json').read_text(encoding='utf-8'))


def _jsonl(p):
    p = Path(p)
    return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()] if p.exists() else []


def load_rows(root):
    """{registry: [rows]} for all nine registries."""
    reg = Path(root) / 'registries'
    out = {n: _jsonl(reg / f'{n}.jsonl') for n in JSONL}
    for n in DIRS:
        out[n] = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((reg / n).glob('*.json'))]
    return out


def index_sha256(path):
    """sha256 of the inflated index text: the gzip bytes differ between zlib builds (tsvgz.problems), the text does not."""
    with open(path, 'rb') as f:
        return hashlib.sha256(gzip.decompress(f.read())).hexdigest()


# ------------------------------------------------------------------ populated
def floor_problems(rows, cfg):
    """A registry below its floor, an empty or low ui_elements context, or a registry the config has no floor for."""
    bad = []
    for n in REGISTRIES:
        floor = cfg['floors'].get(n)
        if floor is None:
            bad.append(f'{n}: no floor in gate.json')
        elif len(rows.get(n, [])) < floor:
            bad.append(f'{n}: {len(rows.get(n, []))} rows, below its floor {floor}')
    ctx = {}
    for r in rows.get('ui_elements', []):
        ctx[r['id'].split('.')[0]] = ctx.get(r['id'].split('.')[0], 0) + 1
    for c, floor in sorted(cfg['ui_context_floors'].items()):
        if ctx.get(c, 0) < floor:
            bad.append(f'ui_elements: context "{c}" has {ctx.get(c, 0)} rows, below its floor {floor}')
    for c in sorted(set(ctx) - set(cfg['ui_context_floors'])):
        bad.append(f'ui_elements: context "{c}" has no floor in gate.json')
    return bad


def shape_problems(rows, cfg, exe_sha1):
    """The row shapes later phases rely on (brief "Decisions"): each message names the registry and the row."""
    bad = []
    for r in rows.get('ui_elements', []):
        i, src = r['id'], r.get('vanilla_source') or {}
        if r.get('status') not in UI_DONE:
            bad.append(f'ui_elements {i}: status {r.get("status")!r} is not atlas or later')
        if i.startswith('engine.'):
            if not r.get('description', '').startswith('route:'):
                bad.append(f'ui_elements {i}: an engine.* row starts its description with "route:" (D39)')
            continue
        if not (src.get('layout') or src.get('script')):
            bad.append(f'ui_elements {i}: no layout or script in vanilla_source')
        if not r.get('interactions'):
            bad.append(f'ui_elements {i}: no interactions entry (use "none: display only")')
    for r in rows.get('engine_sites', []):
        v = r.get('verified') or {}
        if not (v.get('date') and v.get('run')):
            bad.append(f'engine_sites {r["id"]}: no verified date and run')
        if r.get('exe') != f'sha1:{exe_sha1}':
            bad.append(f'engine_sites {r["id"]}: exe {r.get("exe")} is not the pinned identity sha1:{exe_sha1} (stale by definition)')
    jobs = {j['id'] for j in rows.get('jobs', [])}
    ok_owner = set(cfg.get('config_key_owners', []))
    for r in rows.get('config_keys', []):
        o = r.get('owner')
        if o not in jobs and o != 'liam' and o not in ok_owner:
            bad.append(f'config_keys {r["id"]}: owner {o!r} is not a jobs row, "liam" or a component named in gate.json config_key_owners')
    for r in rows.get('scenarios', []):
        if not r.get('launch'):
            bad.append(f'scenarios {r["id"]}: no launch recipe')
    for r in rows.get('engine_facts', []):
        if r.get('state') == 'open':
            owners = {m.upper() if m[0] in 'jJ' else m.lower() for m in OWNER.findall(r.get('claim', '') + ' ' + r.get('notes', ''))}
            if not (owners & (jobs | {'liam'})):
                bad.append(f'engine_facts {r["id"]}: open, and neither its claim nor its notes name a jobs row or liam as owner')
    return bad


# ------------------------------------------------------------------ current
def index_problems(index_path, summary, cfg):
    """Offline: the committed index is the one gate.json pins, summary.json describes it, and the fingerprints in it are the index's own."""
    import assets
    import tsvgz
    bad = []
    sha = index_sha256(index_path)
    pin = cfg['index']
    if sha != pin['sha256']:
        bad.append(f'discovery/assets/index.tsv.gz: sha256 {sha[:12]} is not the pinned {pin["sha256"][:12]} (built {pin["built"]}); the registries and the atlas '
                   f'were built from the older index. Re-run the passes on the PC, then update gate.json "index" in a commit that says why')
        return bad
    _, rows = tsvgz.read(index_path)
    if len(rows) != pin['rows'] or summary.get('index_rows') != len(rows):
        bad.append(f'index has {len(rows)} rows; gate.json says {pin["rows"]}, assets/summary.json says {summary.get("index_rows")}')
    idx = [dict(zip(assets.COLUMNS, r)) for r in rows]
    want = assets.pack_fingerprints(idx)
    have = summary.get('pack_fingerprint')
    if have is None:
        bad.append('discovery/assets/summary.json has no pack_fingerprint (the next assets pass writes it)')
    elif have != want:
        bad.append('discovery/assets/summary.json pack_fingerprint is not what the committed index gives')
    return bad


def install_problems(summary, game_root, data_dir, exe_name, identity_sha1, read_index):
    """PC mode: the installed packs' entry counts and sizes against the recorded fingerprint, the pack order, and the exe sha1 against the pinned identity.
    `read_index(pack path) -> (header, [entries with 'size'])` is core/proxy/tools/pack_list.read_index; read-only."""
    bad = []
    root = Path(game_root)
    exe = root / exe_name
    if not exe.is_file():
        return [f'install: {exe} not found']
    sha = hashlib.sha1(exe.read_bytes()).hexdigest()
    if sha != identity_sha1:
        bad.append(f'install: {exe_name} sha1 {sha} is not the pinned identity {identity_sha1}')
    present = sorted(p.name for p in (root / data_dir).glob('*.pack'))
    want = summary.get('pack_fingerprint', {})
    for name in summary.get('pack_order', []):
        if name not in present:
            bad.append(f'install: pack {name} (in pack_order) is not installed')
    for name in sorted(want):
        p = root / data_dir / name
        if not p.is_file():
            continue
        _, entries = read_index(str(p))
        got = {'entries': len(entries), 'bytes': sum(e['size'] for e in entries)}
        if got != want[name]:
            bad.append(f'install: {name} has {got["entries"]} entries / {got["bytes"]} bytes, the index was built from {want[name]["entries"]} / {want[name]["bytes"]}')
    extra = sorted(set(present) - set(want))
    if extra:
        bad.append(f'install: packs {", ".join(extra)} are not in the index (a mod pack or a game update)')
    return bad


# ------------------------------------------------------------------ findings
def gaps(rows, ui_summary, assets_summary, brief_gaps, target=None):
    """The findings table: [{registry, gap, count, owner}] in a fixed order. Never red by themselves."""
    target = target or paths.TARGET
    unref = sum(assets_summary.get('unreferenced', {}).values())
    open_facts = [f['id'] for f in rows.get('engine_facts', []) if f.get('state') == 'open']
    c = ui_summary.get('counts', {})
    return [
        {'registry': 'ui_elements', 'gap': 'data fields with no source (parameter, upvalue, text key, dynamic text)', 'count': c.get('data_fields_unresolved', 0),
         'owner': 'the panel jobs (J35 and the build jobs read them per screen)', 'key': 'ui_elements.data_fields_unresolved'},
        {'registry': 'ui_elements', 'gap': 'scripts named by a layout but not shipped in the packs', 'count': len(c.get('scripts_missing', [])),
         'owner': 'the panel jobs (J10 recorded them per unit)', 'key': 'ui_elements.scripts_missing'},
        {'registry': 'assets', 'gap': 'rows no file names as a string (db-key driven art)', 'count': unref,
         'owner': 'the panel jobs (J10 art_keys.json maps the db-driven roles)', 'key': 'assets.unreferenced'},
        {'registry': 'engine_facts', 'gap': 'open facts', 'count': len(open_facts), 'owner': 'each names its job or liam (shape check)', 'key': 'engine_facts.open'},
        {'registry': 'engine_facts', 'gap': f'{target}.files.loose_override still open (a pack entry versus a loose file)',
         'count': int(f'{target}.files.loose_override' in open_facts), 'owner': 'J9 and J7 follow-up', 'key': 'engine_facts.loose_override_open'},
        {'registry': 'briefs', 'gap': 'paths a brief lists under "## Registry gaps" (no registry row yet)', 'count': len(brief_gaps),
         'owner': 'the owner each bullet names', 'key': 'briefs.registry_gaps'},
    ]


def ratchet_problems(found, cfg):
    """(failures, notes): a finding above its recorded number fails; below it is a note to lower gate.json."""
    bad, notes = [], []
    for g in found:
        top = cfg['ratchet'].get(g['key'])
        if top is None:
            bad.append(f'{g["key"]}: no ratchet number in gate.json')
        elif g['count'] > top:
            bad.append(f'{g["key"]}: {g["count"]} is above the recorded {top} (a gap may only shrink)')
        elif g['count'] < top:
            notes.append(f'{g["key"]}: {g["count"]} is below the recorded {top}; lower it in gate.json')
    return bad, notes


# ------------------------------------------------------------------ the result
def summary_doc(root, cfg, ui_summary, assets_summary):
    """discovery/gate/summary.json: deterministic and stable under routine work (no registry counts, no dates)."""
    root = Path(root)
    return {
        'schema': 1,
        'assets_summary_sha256': hashlib.sha256((root / 'discovery' / 'assets' / 'summary.json').read_bytes()).hexdigest(),
        'index': dict(cfg['index']),
        'pack_fingerprint': assets_summary.get('pack_fingerprint'),
        'gaps': [{k: g[k] for k in ('registry', 'gap', 'count', 'owner')}
                 for g in gaps({}, ui_summary, assets_summary, []) if g['key'].startswith(('ui_elements', 'assets'))],
    }


def summary_text(doc):
    return json.dumps(doc, indent=1, sort_keys=True) + '\n'


def summary_problems(root, doc):
    p = Path(root) / 'discovery' / 'gate' / 'summary.json'
    if not p.exists() or p.read_text(encoding='utf-8') != summary_text(doc):
        return [f'{p}: missing or stale; run `wsc discovery gate --write`']
    return []


def readme(doc):
    out = ['# Discovery gate (J11)', '',
           'Generated by `python3 core/wsc.py discovery render` from `summary.json` (written by `wsc discovery gate --write`). Do not edit.', '',
           'The gate is PLAN phase 2 as code: every registry above its floor, the row shapes later phases rely on, every committed result',
           'recomputed from its inputs, and the gaps said out loud. Run `python3 core/wsc.py discovery gate` (exit 1 on a failure);',
           '`--install` adds the PC comparison with the installed packs and exe; `--json OUT` writes the report for CI.', '',
           f'- Floors, the ratchet and the pinned index sha256: `{paths.adapter_rel()}/gate.json` (hand-edited; a floor moves only in a commit that says why).',
           '- Code: `discovery/core/gate.py`; the brief rule it sits beside: `discovery/core/briefpaths.py` (run by `wsc jobs check`).',
           '- Reading a finding: a line `FAIL` is red and names the registry and row; a gap is a warning with an owner, and fails only when it grows past its ratchet number.', '',
           f'Index pinned: sha256 `{doc["index"]["sha256"][:16]}...`, {doc["index"]["rows"]} rows, built {doc["index"]["built"]}.', '',
           '## Gaps the next jobs inherit', '', '| Registry | Gap | Count | Owner |', '|---|---|---|---|']
    out += [f'| {g["registry"]} | {g["gap"]} | {g["count"]} | {g["owner"]} |' for g in doc['gaps']]
    out += ['', '## Pack fingerprints (compared by `--install`)', '', '| Pack | Entries | Bytes |', '|---|---|---|']
    out += [f'| {n} | {f["entries"]} | {f["bytes"]} |' for n, f in sorted((doc.get('pack_fingerprint') or {}).items())]
    return '\n'.join(out) + '\n'


# ------------------------------------------------------------------ run
def run_gate(root, currency, brief_gaps=(), install=None, write=False):
    """Run every check. `currency`: {label: callable -> [problems]} supplied by the verb (the existing recomputations);
    `install`: callable -> [problems] for --install, or None (offline: 'install not compared' is a warning, never ok).
    Returns (lines, failures, doc)."""
    root = Path(root)
    cfg = load_config(root)
    rows = load_rows(root)
    ident = json.loads((Path(layout.proxy_adapter(root)) / 'identity.json').read_text(encoding='utf-8'))
    ui_summary = json.loads((root / 'discovery' / 'ui' / 'summary.json').read_text(encoding='utf-8'))
    a_path = root / 'discovery' / 'assets' / 'summary.json'
    a_summary = json.loads(a_path.read_text(encoding='utf-8'))
    lines, fails = [], []

    def stage(label, problems):
        lines.append(f'{"ok  " if not problems else "FAIL"} {label}')
        fails.extend(f'{label}: {p}' for p in problems)

    for n in REGISTRIES:
        lines.append(f'rows {n}: {len(rows[n])} (floor {cfg["floors"].get(n)})')
    stage('floors', floor_problems(rows, cfg))
    stage('row shapes', shape_problems(rows, cfg, ident['sha1']))
    stage('index pin and fingerprints', index_problems(str(root / 'discovery' / 'assets' / 'index.tsv.gz'), a_summary, cfg))
    for label, fn in currency.items():
        stage(label, fn())
    found = gaps(rows, ui_summary, a_summary, brief_gaps, paths._names(paths.adapter_for(root))[0])
    rbad, notes = ratchet_problems(found, cfg)
    stage('ratchet', rbad)
    doc = summary_doc(root, cfg, ui_summary, a_summary)
    if write:
        p = root / 'discovery' / 'gate' / 'summary.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(summary_text(doc), encoding='utf-8', newline='\n')
    stage('gate summary', summary_problems(root, doc))
    if install is None:
        lines.append('warn install not compared (offline): run `wsc discovery gate --install` on the PC to compare the packs and the exe sha1')
    else:
        stage('install', install())
    lines += [f'warn {n}' for n in notes]
    lines.append('findings:')
    lines += [f'  {g["registry"]:<13}{g["count"]:>7}  {g["gap"]} -> {g["owner"]}' for g in found]
    return lines, fails, doc
