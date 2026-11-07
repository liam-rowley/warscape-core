#!/usr/bin/env python3
"""Vanilla UI atlas (J10): every layout, template and compiled UI script read statically, then one ui_elements row per pipeline unit.

purpose: write the static UI atlas (discovery/ui/<context>.json.gz, scripts.json.gz, summary.json) from the layouts, uied.templates records and compiled UI scripts, and generate the ui_elements rows (status atlas) from it
usage: python3 discovery/ui_atlas.py [atlas|rows|live|art|all] [--games <adapter>/games.json] [--run harness/runs/<run id>]   (or `wsc discovery ui`; needs the extract: discovery/README.md)
when: J10; re-run after a codec change, a game update or a change to the unit plan (UNITS, PIECES); the contract stage of every screen reads the atlas file named in the row's vanilla_source
not-a-verb: reads extracted game files; `wsc discovery ui` runs it and `wsc discovery check` checks its results

Static and best-effort. Field sources are traced by the symbolic walk of ui_walk.py; a field no engine call explains stays out of the
rows and is listed under `unresolved` with the reason. Loc text is never written (keys and lengths only), as in the loc pass.
"""
import argparse
import collections
import gzip
import hashlib
import io
import json
import os
import posixpath
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
ROOT = os.path.abspath(paths.REPO)
import tpl  # noqa: E402
import uic  # noqa: E402
import ui_walk  # noqa: E402
from extracted import effective, load_games  # noqa: E402
from tsvgz import read as tsv_read  # noqa: E402

OUT = os.path.join(ROOT, 'discovery', 'ui')
API = paths.adapter_file('engine_api.json')
PROBE_SAFE = paths.adapter_file('probe_safe.json')
LOC = os.path.join(ROOT, 'discovery', 'loc', 'keys.tsv.gz')
ASSETS = os.path.join(ROOT, 'registries', 'assets.jsonl')
HOTKEYS = os.path.join(ROOT, 'registries', 'hotkeys.jsonl')
ROWS = os.path.join(ROOT, 'registries', 'ui_elements.jsonl')

CONTEXTS = {'frontend ui': 'frontend', 'campaign ui': 'campaign', 'battle ui': 'battle', 'common ui': 'common', 'templates': 'template'}
NOT_ENGINE = {'__wsp_lua', 't', 'defined'}       # globals in engine_api.json that the proxy or the scripts made
# layouts whose id is not their file name, and the HUD layouts that are several pipeline units (pieces by component path prefix)
NAMES = {'battle ui\\layout': 'hud', 'campaign ui\\layout': 'hud', 'frontend ui\\layout': 'root_layout',
         'campaign ui\\enlist_commander_scripts\\enlist_commander_entry': 'enlist_commander_entry'}
PIECES = {
    'battle ui\\layout': [('radar', 'root/veneer_DY/radar_group'), ('balance_of_power', 'root/veneer_DY/kill_ratio_PH'),
                          ('timer', 'root/veneer_DY/stopwatch'), ('card_strip', 'root/veneer_DY/cards_panel'), ('frame', 'root')],
    'battle ui\\minimised_hud': [('radar', 'root/veneer_DY/radar_group'), ('balance_of_power', 'root/veneer_DY/kill_ratio_PH'),
                                 ('timer', 'root/veneer_DY/stopwatch'), ('card_strip', 'root/veneer_DY/review_DY'), ('frame', 'root')],
    'campaign ui\\layout': [('radar', 'root/veneer_DY/frame/hud_left/radar'),
                            ('theatres', 'root/veneer_DY/frame/hud_left/world_theatres_ButtonGroup'),
                            ('card_strip', 'root/veneer_DY/frame/hud_center'), ('orders', 'root/veneer_DY/frame/hud_right'), ('frame', 'root')],
}
EVENT = re.compile(r'^On[A-Z]\w*$')
DYNAMIC = re.compile(r'(^dy_|_dy$|_DY$|^DY_|^dy[A-Z])')


# ---------------------------------------------------------------- inputs
def jdump(path, obj, gz=False):
    data = (json.dumps(obj, indent=None if gz else 1, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')
    if gz:
        buf = io.BytesIO()
        with gzip.GzipFile(filename='', mode='wb', fileobj=buf, mtime=0, compresslevel=9) as g:
            g.write(data)
        data = buf.getvalue()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return hashlib.sha256(data if not gz else gzip.decompress(data)).hexdigest()


def jload(path):
    raw = open(path, 'rb').read()
    return json.loads(gzip.decompress(raw) if path.endswith('.gz') else raw)


def engine_api():
    api = json.load(open(API, encoding='utf-8'))
    tables = sorted({x['owner'][2:] for x in api['names'] if x['owner'].startswith('G.') and '#' not in x['owner']} - NOT_ENGINE
                    | {'Component'})
    names = collections.defaultdict(set)          # 'CampaignUI.Fn' -> states
    for x in api['names']:
        if x['owner'].startswith('G.') and '#' not in x['owner']:
            names[f"{x['owner'][2:]}.{x['name']}"] |= set(x['states'])
    return tables, names, sorted(api['states'])


def getter_rule():
    """The probe-safe naming rule (<adapter>/probe_safe.json): (prefixes, forbidden words)."""
    rule = json.load(open(PROBE_SAFE, encoding='utf-8'))['rule']
    pre = re.search(r'starting with one of ([A-Za-z ]+?),', rule).group(1).split()
    bad = re.search(r'containing none of ([A-Za-z ]+)', rule).group(1).split()
    return tuple(pre), tuple(bad)


def is_getter(fn, rule):
    pre, bad = rule
    return fn.startswith(pre) and not any(b in fn for b in bad)


def ctx_states(ctx, states):
    if ctx == 'campaign':
        return {s for s in states if s.startswith('campaign')}
    if ctx == 'battle':
        return {'land', 'naval', 'siege'}
    if ctx == 'frontend':
        return {s for s in states if s.startswith('frontend')}
    return set(states)


def loc_keys():
    _, rows = tsv_read(LOC)
    return {r[1]: (r[0], int(r[2])) for r in rows}


def asset_ids():
    out = {}
    for line in open(ASSETS, encoding='utf-8'):
        r = json.loads(line)
        out.setdefault(r['path'].lower(), r['id'])
    return out


def hotkeys():
    return [json.loads(x) for x in open(HOTKEYS, encoding='utf-8')]


# ---------------------------------------------------------------- reading
def norm(p):
    return p.replace('\\', '/').lower()


def read_layouts(games):
    out = {}
    for p, f in sorted(effective(games, paths.TARGET, exts={''}, under='ui\\').items()):
        b = open(f, 'rb').read()
        if b.startswith(b'Version'):
            out[p[3:]] = uic.parse(b, p)          # 'campaign ui\\region_details'
    return out


def read_templates(games):
    g = games[paths.TARGET]
    recs = tpl.split(open(os.path.join(g['root'], g['data'], 'ui', 'templates', 'uied.templates'), 'rb').read())
    out = {}
    for r in recs:
        try:
            if r['legacy']:
                raise ValueError('legacy first record')
            out[r['name']] = dict(version=r['ver'], doc=tpl.parse_record(r))
        except Exception as e:  # noqa: BLE001 (an unread record is a result: layout_unread)
            out[r['name']] = dict(version=r['ver'], error=f'{type(e).__name__}: {e}'[:200])
    return out


def read_scripts(games, tables):
    g = games[paths.TARGET]
    base = os.path.join(g['root'], g['data'], 'ui')
    files = effective(games, paths.TARGET, exts={'.luac'}, under='ui\\')
    out, fails = {}, {}
    for p, f in sorted(files.items()):
        rel = norm(p[3:])
        try:
            out[rel] = ui_walk.walk_chunk(open(f, 'rb').read(), tables)
        except Exception as e:  # noqa: BLE001
            fails[rel] = f'{type(e).__name__}: {e}'[:200]
    return out, fails, base


# ---------------------------------------------------------------- one surface (a layout or a template record)
def resolve_script(layout_rel, script, scripts):
    """A component's script name is relative to <layout>_scripts/ ('../x.lua' for a shared one) and compiled to .luac."""
    if not script:
        return None
    s = norm(script)
    s = s[:-4] + '.luac' if s.endswith('.lua') else s + ('' if s.endswith('.luac') else '.luac')
    lay = norm(layout_rel)
    d = posixpath.dirname(lay)
    for cand in (posixpath.join(lay + '_scripts', s), posixpath.join(d, s), posixpath.join('templates', posixpath.basename(s)),
                 posixpath.basename(s)):
        c = posixpath.normpath(cand)
        if c in scripts:
            return c
    return None


def art_id(p, assets):
    """A layout image path -> assets id. Paths may carry 'data\\' or a UI-editor absolute prefix (c:\\<editor folder>\\...)."""
    k = norm(p)
    i = k.find('ui/')
    if k.startswith('data/'):
        k = k[5:]
    elif i > 0 and k[i - 1] == '/':
        k = k[i:]
    hit = assets.get(k.replace('/', '\\'))
    if hit:
        return hit
    return ('editor_path:' if re.match(r'^[a-z]:', k) or k.startswith('//') else 'unresolved:') + p


def state_rec(st, by_id, assets, loc):
    imgs = []
    for u in st['uses']:
        p = by_id.get(u['img'], '')
        if p:
            imgs.append(art_id(p, assets))
    r = dict(name=st['name'], w=st['w'], h=st['h'], font=st.get('font') or '', colour=f"{st.get('font_colour', 0):08x}", images=imgs)
    for k, kk in (('text', 'text_label'), ('tooltip', 'text_label2')):
        txt, key = st.get('text' if k == 'text' else 'text2') or '', st.get(kk) or ''
        if txt:
            r[k + '_len'] = len(txt)
        if key:
            r[k + '_key'] = key
            r[k + '_key_ok'] = key in loc
    if st.get('transitions'):
        r['transitions'] = [[t[0], t[1], t[2]] if len(t) > 2 else [t[0], t[1]] for t in st['transitions']]
    return r


def components(doc_root, layout_rel, scripts, assets, loc):
    comps = []

    def rec(c, path, parent):
        by_id = {im['id']: im['path'] for im in c['images']}
        ids = {st['id']: st['name'] for st in c['states']}
        ev = c['events']
        pairs = [(ev[i], ev[i + 1]) for i in range(0, len(ev), 2)]
        r = dict(path=path, name=c['name'], parent=parent, x=c['x'], y=c['y'], flags=c['flags'].hex(),
                 w=c['states'][0]['w'] if c['states'] else 0, h=c['states'][0]['h'] if c['states'] else 0,
                 states=[state_rec(st, by_id, assets, loc) for st in c['states']],
                 events=[[a, b] for a, b in pairs if EVENT.match(a)],
                 props={a: b for a, b in pairs if not EVENT.match(a)})
        for k in ('template',):
            if c.get(k):
                r['source'] = c[k]
        if c.get('state_ref'):
            r['default_state'] = ids.get(c['state_ref'], f"{c['state_ref']:#x}")
        if c.get('tooltip_label'):
            r['tooltip_key'] = c['tooltip_label']
            r['tooltip_key_ok'] = c['tooltip_label'] in loc
        if c.get('tooltip'):
            r['tooltip_len'] = len(c['tooltip'])
        if c.get('script'):     # missing: the game ships no compiled script of that name (vanilla template.button_standard.lua and others)
            r['script'] = resolve_script(layout_rel, c['script'], scripts) or 'missing:' + c['script']
        if c.get('inline_script'):
            r['inline'] = c['inline_script']
        if c.get('anims'):
            r['anims'] = [dict(name=a['name'], frames=len(a['frames']),
                               state_changes=[k[3] for k in a['frames'] if not isinstance(k, bytes)]) for a in c['anims']]
        if c.get('textures'):
            r['textures'] = [t['path'] for t in c['textures']]
        comps.append(r)
        for ch in c['children']:
            rec(ch, path + '/' + ch['name'], path)
    rec(doc_root, doc_root['name'] if doc_root['name'] != 'root' else 'root', None)
    comps[0]['path'] = 'root'
    for c in comps[1:]:
        c['path'] = 'root/' + c['path'].split('/', 1)[1]
        c['parent'] = 'root' + c['parent'][len(c['parent'].split('/')[0]):]
    return comps


def handler_owner(comp, comps_by_path, handler, scripts, inline_defs, layout_scripts, live=None):
    """Where a handler is defined: the component's own script or inline source, then its ancestors' (nearest first); else why not."""
    if handler.startswith('call '):
        return 'engine command'                 # e.g. 'call Root.LuaCall,TransitionBack': the engine parses it, no Lua function
    p, missing = comp['path'], None
    while p:
        c = comps_by_path[p]
        s = c.get('script', '')
        if s.startswith('missing:'):
            missing = missing or s
        elif s and handler in scripts[s]['defines']:
            return s
        if c.get('inline') and handler in inline_defs.get(p, ()):
            return f'inline:{p}'
        p = c['parent']
    for s in layout_scripts:
        if handler in scripts[s]['defines']:
            return s
    if missing:
        return f'not found ({missing} is not shipped)'
    shared = sorted(s for s in scripts if posixpath.dirname(s) in ('', 'templates') and handler in scripts[s]['defines'])
    if shared:
        return f'global: {shared[0]}'           # a shared module defines it (the engine's global lookup)
    owners = (live or {}).get(handler, [])      # J9's live surface: a script-environment global or an engine function
    eng = sorted(o[2:] for o in owners if o.startswith('G.') and '#' not in o)
    if eng:
        return f'engine: {eng[0]}.{handler}'
    if 'S' in owners:
        return 'live script environment (engine_api.json owner S; defining script not found statically)'
    return 'not found'


# ---------------------------------------------------------------- the atlas
class Atlas:
    def __init__(s, games):
        s.tables, s.api, s.states = engine_api()
        s.live = collections.defaultdict(list)       # name -> owners in J9's live surface
        for x in json.load(open(API, encoding='utf-8'))['names']:
            s.live[x['name']].append(x['owner'])
        s.rule = getter_rule()
        s.loc, s.assets, s.hot = loc_keys(), asset_ids(), hotkeys()
        s.layouts = read_layouts(games)
        s.templates = read_templates(games)
        s.scripts, s.script_fails, _ = read_scripts(games, s.tables)
        s.panels = s.panel_table()
        s.openers = s.open_index()
        s.links = collections.defaultdict(list)     # (function, argument index) -> [(caller script, label)]
        for rel in sorted(s.scripts):
            for _, _, f, j, lab in s.scripts[rel]['links']:
                s.links[(f, j)].append((rel, lab))
        s.memo = {}

    def panel_table(s):
        """panelmanager.luac: panel id -> layout path, from its constant table (OpenPanel ids name layouts or their aliases)."""
        out = {}
        for rel, r in s.scripts.items():
            for _, last, _, vals in r['capt']:
                if last == 'OpenPanel' and vals and isinstance(vals[0], str):
                    out.setdefault(vals[0], None)
        paths = [x for x in s.scripts.get('panelmanager.luac', {}).get('strings', []) if x.lower().startswith('data/ui/')]
        s.registered = {norm(p)[len('data/ui/'):] for p in paths}    # layouts panelmanager.luac knows: opened through OpenPanel
        for pid in out:
            for p in paths:
                if posixpath.basename(p).lower() == pid.lower():
                    out[pid] = norm(p)[len('data/ui/'):]
        for alias, layout in (('UnitInfoPopup', 'common ui/unit_information'), ('BuildingInfoPopup', 'campaign ui/building_information'),
                              ('CharacterInfoPopup', 'campaign ui/character_information')):
            if alias in out:
                out[alias] = layout
        return dict(sorted(out.items()))

    def open_index(s):
        """layout path (lower, '/') -> [how it opens]: CreateFromLayout paths, OpenPanel ids, CreateComponentFromTemplate names."""
        idx = collections.defaultdict(set)
        for rel, r in sorted(s.scripts.items()):
            for fn, last, full, vals in r['capt']:
                a0 = vals[0] if vals and isinstance(vals[0], str) else None
                if not a0:
                    continue
                if last == 'CreateFromLayout':
                    key = norm(a0)
                    key = key[len('data/ui/'):] if key.startswith('data/ui/') else key[len('ui/'):] if key.startswith('ui/') else key
                    idx[key].add(f'{full}("{a0}") in {rel} {fn}')
                elif last == 'OpenPanel':
                    lay = s.panels.get(a0)
                    if lay:
                        idx[lay].add(f'panel_manager.OpenPanel("{a0}") in {rel} {fn}')
                elif last == 'CreateComponentFromTemplate':
                    idx['template:' + a0.lower()].add(f'CreateComponentFromTemplate("{a0}") in {rel} {fn}')
                elif last == 'TransitionTo':                 # a front-end page: entered from the root by name
                    idx['frontend ui/' + a0.lower()].add(f'{full}("{a0}") in {rel} {fn}')
            for fn, last, full, vals in r['capt']:           # Component.Call/LuaCall("TransitionTo", page) forms
                if last in ('Call', 'LuaCall') and len(vals) > 1 and vals[0] == 'TransitionTo' and isinstance(vals[1], str):
                    idx['frontend ui/' + vals[1].lower()].add(f'{full}("TransitionTo", "{vals[1]}") in {rel} {fn}')
        return {k: sorted(v) for k, v in idx.items()}

    def surface(s, rel, ctx, root, kind):
        comps = components(root, rel, s.scripts, s.assets, s.loc)
        by_path = {c['path']: c for c in comps}
        inline = {c['path']: ui_walk.inline_facts(c['inline'], s.tables) for c in comps if c.get('inline')}
        inline_defs = {p: set(f['defines']) for p, f in inline.items()}
        folder = norm(rel) + '_scripts/'
        attached = sorted({c['script'] for c in comps if c.get('script', '').endswith('.luac') and ':' not in c['script']})
        own = sorted(x for x in s.scripts if x.startswith(folder) and posixpath.dirname(x) + '/' == folder)
        handlers = []
        for c in comps:
            for ev, h in c['events']:
                if not h:
                    continue
                owner = handler_owner(c, by_path, h, s.scripts, inline_defs, sorted(set(attached) | set(own)), s.live)
                calls = []
                if owner in s.scripts:
                    calls = s.scripts[owner]['func_calls'].get(h, [])
                elif owner.startswith('inline:'):
                    calls = sorted(inline[owner[7:]]['calls'])
                handlers.append(dict(component=c['path'], event=ev, handler=h, defined_in=owner, engine_calls=calls))
        rec = dict(kind=kind, path=rel, context=ctx, version=None, base=[comps[0]['w'], comps[0]['h']], components=comps,
                   scripts_attached=attached, scripts_folder=own, handlers=handlers,
                   inline={p: {k: v for k, v in f.items() if v} for p, f in sorted(inline.items())},
                   opened_by=s.openers.get(norm(rel), []) + s.openers.get('template:' + posixpath.basename(norm(rel)), [])
                   + (['panel_manager registry (panelmanager.luac): opened through panel_manager.OpenPanel, or by the engine through a root function'
                       ] if norm(rel) in s.registered else []))
        if rel in NAMES and NAMES[rel] in ('hud', 'root_layout'):
            rec['opened_by'].append('engine: the root layout of its game mode, loaded with the front end, campaign or battle')
        if not rec['opened_by']:                    # weaker evidence: a script names the layout as a string
            base = posixpath.basename(norm(rel))
            named = sorted(x for x, r in s.scripts.items() if any(t.lower() == base or t.lower().endswith('/' + base) for t in r['strings']))
            rec['opened_by'] += [f'named as a string in {x} (static, not a call)' for x in named[:5]]
        rec['fonts'] = sorted({st['font'] for c in comps for st in c['states'] if st['font']})
        rec['art'] = sorted({i for c in comps for st in c['states'] for i in st['images']})
        rec['templates_used'] = s.templates_used(comps, attached + own)
        rec['frame_groups'] = frame_groups(comps)
        return rec

    def templates_used(s, comps, scripts):
        out = set()
        for c in comps:
            sc = c.get('script', '')
            if posixpath.basename(sc).startswith('template.'):
                out.add('script:' + posixpath.basename(sc)[len('template.'):-len('.luac')])
        for rel in scripts:
            for _, last, _, vals in s.scripts[rel]['capt']:
                if last == 'CreateComponentFromTemplate' and vals and isinstance(vals[0], str):
                    out.add('template:' + vals[0])
                if last == 'CreateFromLayout' and vals and isinstance(vals[0], str):
                    out.add('layout:' + norm(vals[0]).split('ui/', 1)[-1])
        return sorted(out)

    # ---------------- script facts per unit
    def facts(s, scripts, ctx, inline_calls=()):
        """Data fields (sourced and unresolved), engine calls (getters checked against engine_api.json) for a set of scripts."""
        states = ctx_states(ctx, s.states)
        calls = collections.Counter()
        for rel in scripts:
            for n, c in s.scripts[rel]['calls'].items():
                calls[n] += c['n']
        calls.update(inline_calls)
        sourced, unresolved = {}, []
        scope = frozenset(scripts)
        for rel in scripts:
            r = s.scripts[rel]
            for root, paths in r['fields'].items():
                label, kind, reason = s.resolve(root, r, scope=scope)
                if kind == 'code':
                    continue                     # a module table or a component method: code, not data the unit shows
                for p in paths:
                    if label:
                        sourced[f'getter:{label}{p}'] = rel
                    else:
                        unresolved.append(dict(field=f'{root}{p}', script=rel, kind=kind, reason=reason))
        for n in calls:
            owner, fn = n.split('.', 1)
            if owner != 'Component' and is_getter(fn, s.rule):
                sourced.setdefault(f'getter:{n}', 'call')
        locs = set()
        for rel in scripts:
            for _, last, _, vals in s.scripts[rel]['capt']:
                if last in ('LocalisationString', 'UILocalisationString') and vals and isinstance(vals[0], str):
                    locs.add(vals[0])
        missing = sorted(n for n in calls if n.split('.')[0] not in ('Component',) and n in s.api and not (s.api[n] & states))
        unknown = sorted(n for n in calls if n.split('.')[0] not in ('Component',) and n not in s.api)
        return dict(sourced=dict(sorted(sourced.items())), unresolved=sorted(unresolved, key=lambda x: (x['field'], x['script'])),
                    calls=dict(sorted(calls.items())), loc_calls=sorted(locs), not_in_state=missing, not_in_api=unknown)

    @staticmethod
    def split_label(label):
        """'CampaignUI.X().a' -> ('CampaignUI.X()', '.a'); 'Init#arg1.a' -> ('Init#arg1', '.a'); '^v.a' -> ('^v', '.a')."""
        if '()' in label:
            i = label.index('()') + 2
            return label[:i], label[i:]
        m = re.match(r'^(\^?[\w]+(?:#arg\d+)?)(.*)$', label)
        return (m.group(1), m.group(2)) if m else (label, '')

    def resolve(s, root, r, depth=0, scope=frozenset()):
        """(label, kind, reason): label 'Owner.Fn[.path]' when the root traces to an engine call (directly, through aliases,
        or a parameter filled from one engine call: by the callers inside the unit's own scripts first, else by every caller);
        kind 'code' for module tables (upvalues the script calls functions on) and component methods."""
        if depth > 8:
            return None, 'loop', f'{root}: alias chain too deep'
        if root.endswith(')') and '()' not in root and root.startswith(':'):
            return None, 'code', ''
        base, rest = s.split_label(root)
        if base.endswith('()'):
            n = base[:-2]
            if n.startswith(':'):
                return None, 'code', ''
            if n.split('.')[0] in s.tables:
                return n + rest, 'engine', ''
            return None, 'code', ''                           # require(), a module function: code
        name = base[1:] if base.startswith('^') else base
        if base.startswith('^') and any(k.startswith(f'^{name}.') for k in r['other_calls']):
            return None, 'code', ''                           # a module the script calls functions on (utils, utilities)
        alias = r['aliases'].get(name)
        if alias and alias != root:
            lab, kind, why = s.resolve(alias, r, depth + 1, scope)
            return (lab + rest if lab else None), kind, why or f'{root}: alias of {alias}'
        m = re.match(r'^(\w+)#arg(\d+)$', base)
        if m:                                                 # a parameter: the callers that pass something must agree
            key = (base, scope)
            if key not in s.memo:
                s.memo[key] = None                            # a cycle through this parameter resolves to nothing
                fn, i = m.group(1), int(m.group(2)) - 1
                callers = s.links.get((fn, i), [])
                inside = [c for c in callers if c[0] in scope]
                s.memo[key] = {s.resolve(lab, s.scripts[rel], depth + 1, scope)[0] for rel, lab in (inside or callers)}
            found = s.memo[key] or set()
            hits = {x for x in found if x}
            if len(hits) == 1 and None not in found:
                return hits.pop() + rest, 'engine', ''
            if len(hits) > 1:
                return None, 'parameter', f'parameter {base}: callers pass different engine results ({", ".join(sorted(hits)[:3])})'
            return None, 'parameter', f'parameter {base}: no caller passes an engine result into it'
        if base.startswith('^'):
            return None, 'upvalue', f'upvalue {base}: not set from an engine call or a traced parameter'
        return None, 'code', ''                               # a global or module table (utils, out, panel_manager): code


def frame_groups(comps):
    """9-slice and 3-slice frames: siblings named frame_TL..frame_BR (or tl..br / L,R,fill) grouped with their art and insets."""
    out = []
    kids = collections.defaultdict(list)
    for c in comps:
        if c['parent']:
            kids[c['parent']].append(c)
    nine = {'TL', 'T', 'TR', 'L', 'R', 'BL', 'B', 'BR'}
    for parent, cs in sorted(kids.items()):
        tag = {}
        for c in cs:
            m = re.match(r'^(?:frame_|corner_?)?(TL|TR|BL|BR|T|B|L|R)$', c['name'], re.I)
            if m:
                tag[m.group(1).upper()] = c
        if nine <= set(tag):
            tl = tag['TL']
            out.append(dict(parent=parent, kind='9-slice', pieces={k: (tag[k]['states'][0]['images'] if tag[k]['states'] else [])
                                                                   for k in sorted(tag)},
                            insets=[tl['w'], tl['h'], tag['BR']['w'], tag['BR']['h']]))
    return out


# ---------------------------------------------------------------- units
def unit_id(ctx, name):
    return f"{ctx}.{name.lower().replace(' ', '_').replace('-', '_')}"


def build_units(at):
    """Pipeline units: one per layout (pieces for the HUD layouts), one per template layout, one per shared widget script."""
    units, surfaces = [], collections.defaultdict(dict)
    for rel, doc in sorted(at.layouts.items()):
        folder = rel.split('\\')[0]
        ctx = CONTEXTS.get(folder, 'common')
        name = NAMES.get(rel, rel.split('\\')[-1])
        rec = at.surface(rel, ctx, doc['root'], 'layout')
        rec['version'] = doc['version']
        surfaces[ctx][rel.replace('\\', '/')] = rec
        sid = unit_id(ctx, name)
        if rel in PIECES:
            taken = set()
            for piece, prefix in PIECES[rel]:
                cs = [c for c in rec['components'] if (c['path'] == prefix or c['path'].startswith(prefix + '/')) and c['path'] not in taken]
                if not cs:
                    raise ValueError(f'PIECES: {rel} piece {piece} names {prefix}, which is no component of the layout')
                taken |= {c['path'] for c in cs}
                units.append(dict(id=f'{sid}.{piece}', screen=sid, ctx=ctx, surface=rel, comps={c['path'] for c in cs}, piece=prefix))
        else:
            units.append(dict(id=sid, screen=sid, ctx=ctx, surface=rel, comps=None))
    for name, t in sorted(at.templates.items()):
        rel = 'uied.templates/' + name
        if 'doc' in t:
            rec = at.surface(rel, 'template', t['doc']['root'], 'uied_template')
            rec['version'] = t['version']
            rec['record_textures'] = [x['path'] for x in t['doc']['textures']]
        else:
            rec = dict(kind='uied_template', path=rel, context='template', version=t['version'], layout_unread=t['error'],
                       opened_by=at.openers.get('template:' + name.lower(), []))
        surfaces['template'][rel] = rec
    # runtime templates named by CreateComponentFromTemplate that a uied record (not a layout) provides
    layout_names = {r.split('\\')[-1].lower() for r in at.layouts if r.startswith('templates\\')}
    used = {k[len('template:'):] for k in at.openers if k.startswith('template:')}
    for name in sorted(at.templates, key=str.lower):
        if name.lower() in used and name.lower() not in layout_names:
            units.append(dict(id=unit_id('template', name), screen=unit_id('template', name), ctx='template',
                              surface='uied.templates/' + name, comps=None))
    # shared widget scripts attached in two or more layouts
    widget = collections.defaultdict(set)
    for ctx, ss in surfaces.items():
        for rel, rec in ss.items():
            for c in rec.get('components', []):
                b = posixpath.basename(c.get('script', ''))
                if b.startswith('template.') and rec['kind'] == 'layout':
                    widget[b[len('template.'):-len('.luac')].lower()].add(rel)
    have = {u['id'] for u in units}
    for w, rels in sorted(widget.items()):
        uid = unit_id('template', w)
        if len(rels) >= 2 and uid not in have:
            units.append(dict(id=uid, screen=uid, ctx='template', surface=None, widget=w, used_in=sorted(rels), comps=None))
    return units, surfaces


def unit_record(at, u, surfaces):
    """Everything the row and the summary need for one unit."""
    if u.get('widget'):
        rels = u['used_in']
        scripts = sorted({c['script'] for r in rels for ss in surfaces.values() if r in ss for c in ss[r]['components']
                          if posixpath.basename(c.get('script', '')).lower() == f"template.{u['widget']}.luac"})
        comps, rec = [], None
        f = at.facts(scripts, 'template')
        inter = []
        for s in scripts:
            for h in at.scripts[s]['handlers']:
                inter.append(f"{h} -> Lua {h} ({s})" + (f" -> {', '.join(at.scripts[s]['func_calls'].get(h, []))}" if at.scripts[s]['func_calls'].get(h) else ''))
        return dict(scripts=scripts, comps=comps, facts=f, interactions=sorted(set(inter)), rec=None)
    rec = surfaces[u['ctx']][u['surface'].replace('\\', '/')]
    if 'components' not in rec:
        return dict(scripts=[], comps=[], facts=at.facts([], u['ctx']), interactions=[], rec=rec)
    comps = [c for c in rec['components'] if u['comps'] is None or c['path'] in u['comps']]
    if u['comps'] is None:
        scripts = sorted(set(rec['scripts_attached']) | set(rec['scripts_folder']))
    else:
        scripts = sorted({c['script'] for c in comps if c.get('script', '').endswith('.luac') and ':' not in c['script']})
    inline_calls = collections.Counter()
    for p, f in rec['inline'].items():
        if u['comps'] is None or p in u['comps']:
            inline_calls.update(f.get('calls', {}))
    f = at.facts(scripts, u['ctx'], inline_calls)
    # static text keys: sourced as loc when the loc tables hold them; an editor placeholder key the tables lack is unresolved
    keyed = set()
    for c in comps:
        ks = [(st[k], st.get(k + '_ok'), f"{c['path']}#{st['name']}") for st in c['states'] for k in ('text_key', 'tooltip_key') if st.get(k)]
        if c.get('tooltip_key'):
            ks.append((c['tooltip_key'], c.get('tooltip_key_ok'), c['path']))
        for key, ok, where in ks:
            if ok:
                f['sourced'].setdefault(f'loc:{key}', where)
                keyed.add(c['path'])
            else:
                f['unresolved'].append(dict(field=where, script='', kind='text_key',
                                            reason=f'text key {key} is not in the loc tables (editor placeholder; the text is set at runtime)'))
    for key in f['loc_calls']:
        f['sourced'].setdefault(f'loc:{key}', 'LocalisationString')
    # dynamic text components with no key: unresolved unless a script names them
    named = {n for s in scripts for n in at.scripts[s]['comp']} | {n for s in scripts for x in at.scripts[s]['capt'] if x[1] in ('Find', 'SequentialFind') for n in x[3][:1] if isinstance(n, str)}
    for c in comps:
        if DYNAMIC.search(c['name']) and c['path'] not in keyed and not any(st.get('text_key') for st in c['states']):
            reason = (f"dynamic text: {c['name']} is found by a script but its text source is not traced" if c['name'] in named
                      else f"dynamic text: no script of this unit names {c['name']} (set by the engine or a parent script)")
            f['unresolved'].append(dict(field=c['path'], script='', kind='dynamic_text', reason=reason))
    inter = []
    for h in rec['handlers']:
        if u['comps'] is not None and h['component'] not in u['comps']:
            continue
        where = h['defined_in'] if not h['defined_in'].startswith('not found') else 'handler ' + h['defined_in']
        tail = f" -> {', '.join(h['engine_calls'])}" if h['engine_calls'] else ''
        inter.append(f"{h['component'].split('/')[-1]} {h['event']} -> Lua {h['handler']} ({where}){tail}")
    return dict(scripts=scripts, comps=comps, facts=f, interactions=sorted(set(inter)), rec=rec)


def complexity(ur, reached=None):
    f = ur['facts']
    return dict(components=len(ur['comps']), states=sum(len(c['states']) for c in ur['comps']),
                text_keys=sum(1 for k in f['sourced'] if k.startswith('loc:')),
                art=len({i for c in ur['comps'] for st in c['states'] for i in st['images']}),
                getters=len({k.split('.')[0] + '.' + k.split('.')[1] for k in f['sourced'] if k.startswith('getter:')}),
                interactions=len(ur['interactions']), scripts=len(ur['scripts']),
                templates=len((ur['rec'] or {}).get('templates_used', [])), reached=reached)


def describe(at, u, ur, users=()):
    rec = ur['rec'] or {}
    if u.get('widget'):
        return (f"Shared widget: the template.{u['widget']} script, attached to components in {len(u['used_in'])} layouts "
                f"({', '.join(r.split('/')[-1] for r in u['used_in'][:8])}{', ...' if len(u['used_in']) > 8 else ''}).")
    kind = 'uied.templates record' if rec.get('kind') == 'uied_template' else 'layout'
    what = f"{u['surface']} ({kind}" + (f", piece {u['piece']}" if u.get('piece') else '') + ')'
    opened = rec.get('opened_by') or []
    ent = f"Opened by {opened[0]}" + (f' and {len(opened) - 1} more' if len(opened) > 1 else '') if opened else 'Opener not found statically (engine-created or a parent layout)'
    if users:
        ent += f". Used by: {', '.join(users[:8])}" + (f' and {len(users) - 8} more' if len(users) > 8 else '')
    return f"Vanilla {what}. {ent}. Atlas: discovery/ui/{u['ctx']}.json.gz."


def reach_note(rr):
    if not rr:
        return ''
    if rr['reach'] == 'reached':
        return f" Live: reached in run {rr['run']} (state {rr['state']}, static-vs-live agreement {round(rr['agreement'] * 100)} %)."
    return f" Live: static_only ({rr['reason']})."


def template_users(units, surfaces):
    """template unit id -> the screens that use it: the screens whose templates_used names it (script:, template:, layout:), and the screens
    that own the script that creates it (opened_by names the script: CreateComponentFromTemplate in construction.luac)."""
    screens = collections.defaultdict(set)              # surface path ('/') -> screen ids
    for u in units:
        if u.get('surface') and u['ctx'] != 'template':
            screens[u['surface'].replace('\\', '/')].add(u['screen'])
    owner = collections.defaultdict(set)                # script rel -> screen ids
    users = collections.defaultdict(set)
    for ctx, ss in surfaces.items():
        for rel, rec in ss.items():
            if rec.get('kind') != 'layout' or rel not in screens:
                continue
            for x in rec.get('scripts_attached', []) + rec.get('scripts_folder', []):
                owner[x].update(screens[rel])
            for t in rec.get('templates_used', []):
                kind, _, name = t.partition(':')
                name = posixpath.splitext(posixpath.basename(name))[0] if kind == 'layout' else name
                users[unit_id('template', name)].update(screens[rel])
    by_surface = {k.lower(): v for k, v in screens.items()}

    def script_screens(rel):
        """the screens a script belongs to: the folder of a layout's scripts, a layout's own script (layout.root.luac, x.x.luac),
        or the screens that use the template the script is attached to (templates/template.<name>.luac)"""
        if owner.get(rel):
            return set(owner[rel]), None
        d, _, base = rel.rpartition('/')
        g = d[:-len('_scripts')] if d.endswith('_scripts') else f"{d}/{base.split('.')[0]}"
        if g.lower() in by_surface:
            return set(by_surface[g.lower()]), None
        if d == 'templates' and base.startswith('template.'):
            return set(users.get(unit_id('template', base[len('template.'):-len('.luac')]), ())), None
        return set(), rel

    loose = collections.defaultdict(set)                # template unit id -> context-wide scripts that create it
    for _ in range(3):                                  # a template created by a template's script resolves on the next pass
        for ss in surfaces.values():
            for rel, rec in ss.items():
                for how in rec.get('opened_by', []):
                    m = re.match(r'CreateComponentFromTemplate\("([^"]+)"\) in (.+?\.luac) ', how)
                    named = re.match(r'named as a string in (.+?\.luac) ', how)      # weaker evidence, still the script's screens
                    if m or named:
                        uid = unit_id('template', m.group(1) if m else rel.split('/')[-1])
                        got, none = script_screens((m or named).group(2 if m else 1))
                        users[uid].update(got)
                        if none:
                            loose[uid].add(none)
    return {k: sorted(users[k]) + [f"{x} (a script shared by the whole context)" for x in sorted(loose.get(k, ()))]
            for k in set(users) | set(loose)}


def rows(at, units, surfaces, reach=None):
    out, recs = [], {}
    tusers = template_users(units, surfaces)
    for u in units:
        ur = unit_record(at, u, surfaces)
        recs[u['id']] = ur
        rr = (reach or {}).get('units_reach', {}).get(u['id'])
        r = dict(id=u['id'], description=describe(at, u, ur, tusers.get(u['id'], ())) + reach_note(rr), screen=u['screen'], status='atlas')
        vs = {}
        if u.get('surface'):
            vs['layout'] = u['surface'] if not u['surface'].startswith('uied.templates/') else 'data\\ui\\templates\\uied.templates#' + u['surface'].split('/', 1)[1]
        if ur['scripts']:
            vs['script'] = ', '.join(ur['scripts'])
        if vs:
            r['vanilla_source'] = vs
        df = [dict(name=k.split(':', 1)[1], source=k) for k in ur['facts']['sourced']]
        if df:
            r['data_fields'] = df
        r['interactions'] = [dict(name=x) for x in ur['interactions']] or [dict(name='none: display only')]
        out.append(r)
    return sorted(out, key=lambda r: r['id']), recs


# ---------------------------------------------------------------- engine-drawn items (not layout components)
# Each evidence item is checked by engine_drawn(): exe:<string> (exe_strings.tsv.gz), call:<Owner.Fn> (a script calls it),
# layout:<surface>#<component name>, anatomy:<text> (frame_anatomy.md), role:<asset role> (registries/assets.jsonl).
# Routes are proposals (D39: the default for J35 and J37, reviewed when J35 is briefed). `observed` run ids are added by the live pass.
ENGINE = [
    dict(id='engine.battle_radar', name='Battle radar picture (land and naval)', route='render_target',
         why='the engine generates the terrain texture (RADAR_GENERATOR) and draws unit pips as sprites each frame; an RmlUi rebuild would need '
             'every unit position at 10 Hz plus the terrain image, so show the engine texture in an RmlUi element and keep the frame and buttons in RmlUi',
         cost='host: expose the radar render target and its rect; input: forward clicks and drags on the element to BattleUI (Move_Selection_To_Rader_Location, ResizeMinimap)',
         owner='J35 (panel host), then the battle HUD job', data=['call:BattleUI.ResizeMinimap', 'call:BattleUI.ToggleMinimisedRadar'],
         interactions=['radar OnUpdatePulse -> Lua Update_Radar (battle ui/layout_scripts/battle_hud_radar.luac)',
                       'radar click -> BattleUI.Move_Selection_To_Rader_Location', 'button_enlarge / button_decrease -> BattleUI.ResizeMinimap'],
         evidence=['exe:RADAR_GENERATOR::generate_radar_texture', 'exe:RC_BATTLE_RADAR', 'exe:CustomSprites/land_radar_pip_inf',
                   'exe:CustomSprites/naval_radar_sea', 'exe:CustomSprites/radar_camera', 'layout:battle ui/layout#radar',
                   'call:BattleUI.Move_Selection_To_Rader_Location']),
    dict(id='engine.campaign_radar', name='Campaign minimap (theatre radar view)', route='render_target',
         why='CampaignUI.AttachRadarView attaches an engine view to the radar component and UpdateRadarView refreshes it; the picture is the engine\'s',
         cost='host: the attached view as a texture in an RmlUi element; theatre buttons and arrows stay RmlUi (campaign.hud.radar, campaign.hud.theatres)',
         owner='J35 (panel host), then the campaign HUD job', data=['call:CampaignUI.UpdateRadarView'],
         interactions=['theatre buttons -> SetRadarTheatreAndPosition (exe)', 'radar arrows L/R'],
         evidence=['call:CampaignUI.AttachRadarView', 'call:CampaignUI.UpdateRadarView', 'exe:SetRadarTheatreAndPosition',
                   'exe:In: Theatre id, Out: Table containing paths to map, overlay and radar images', 'layout:campaign ui/layout#radar']),
    dict(id='engine.battle_unit_banners', name='Battle unit banners and flags over units', route='engine_drawn',
         why='placed in 3D by the engine each frame (BannerPosition) from the lb_unit_id / nb_unit_id / battle_hud_flags layouts; ' + paths.titled(paths.REFERENCE) + ' kept them native',
         cost='none for the host; art upscaled through the layouts\' assets; text, if any, through the .cuf route (D7, J37)',
         owner='J37 (engine-drawn text and fonts)', data=[], interactions=['click a banner selects the unit (engine)'],
         evidence=['exe:BannerPosition', 'layout:battle ui/lb_unit_id#LB_unit_ID', 'layout:battle ui/nb_unit_id#NB_unit_ID',
                   'layout:battle ui/battle_hud_flags#flag_L_DY', 'anatomy:Drawing sneaky sprites']),
    dict(id='engine.campaign_map_labels', name='Campaign map labels, settlement info bars, faction flags and army strength bars', route='engine_drawn',
         why='3D-anchored on the campaign map (city_info_bar, faction_hud_flags layouts; campaignflag and strengthbar shaders in the frame)',
         cost='art through the layouts\' assets; label text through the .cuf route (J37)', owner='J37 (engine-drawn text and fonts)',
         data=['call:CampaignUI.ShouldShowLabelBottomRow'], interactions=['CampaignUI.ToggleLabels, CampaignUI.ToggleFlagDisplay (menu buttons)'],
         evidence=['call:CampaignUI.ToggleLabels', 'call:CampaignUI.ToggleFlagDisplay', 'layout:campaign ui/city_info_bar#city_info_bar',
                   'layout:campaign ui/faction_hud_flags#faction_hud_flags', 'anatomy:campaignflag', 'anatomy:strengthbar']),
    dict(id='engine.campaign_map', name='The campaign map itself', route='engine_drawn',
         why='the world render (terrain, overlays, trees), not UI; listed so no screen claims it', cost='none', owner='none (world rendering)',
         data=[], interactions=['map clicks select and order (engine)'],
         evidence=['anatomy:campaignoverlay', 'anatomy:supertexturetile', 'exe:Campaign Marker Display']),
    dict(id='engine.selection_and_order_markers', name='Selection markers, move and attack markers, path markers', route='engine_drawn',
         why='3D world decals drawn by the marker manager under units and on paths', cost='art upscale only', owner='none (world rendering)',
         data=[], interactions=['none: display only'],
         evidence=['exe:Show the selection markers under the units', 'exe:MARKER_MANAGER', 'exe:Indicators/ship_group_path_marker_diffuse']),
    dict(id='engine.selection_box', name='Drag selection box', route='rml',
         why='already a UI template (uied.templates box_selection, created by a script), so it is a layout component, not engine drawing',
         cost='an RmlUi element the host sizes from the drag rectangle', owner='the battle HUD job', data=[], interactions=['mouse drag (engine)'],
         evidence=['layout:uied.templates/box_selection#box_selection']),
    dict(id='engine.cursors', name='Mouse cursors (179 cursor assets)', route='engine_drawn',
         why='Windows cursors loaded from .cur/.ani files (LoadCursorFromFileA); RmlUi does not draw them', cost='upscaled cursor files at the OS cursor sizes',
         owner='a later art job', data=[], interactions=['none: display only'],
         evidence=['exe:%s.cur', 'exe:LoadCursorFromFileA', 'exe:WARSCAPE_SETCURSOR', 'role:cursor']),
    dict(id='engine.movies', name='Movies (intro, front-end background, event movies, historical battle intros)', route='render_target',
         why='Bink movies the engine plays into a component (PlayMovieInComponent, AttachMovieToComponent); the frame around them is layout',
         cost='host: the movie surface as a texture in an RmlUi element, or leave the engine drawing into the element rect', owner='J35 (panel host)',
         data=['call:FrontEnd.MoviePlaying'], interactions=['click or key dismisses (MovieDismissed)'],
         evidence=['exe:NTW_Intro.bik', 'exe:Frontend2.bik', 'call:FrontEnd.PlayMovieInComponent', 'call:CampaignUI.AttachMovieToComponent',
                   'layout:campaign ui/event_movie_panel#movie_window', 'layout:frontend ui/layout#movie_bg']),
    dict(id='engine.subtitles', name='Movie subtitles', route='engine_drawn', why='drawn with the movie when the subtitle option is on',
         cost='text through the .cuf route', owner='J37 (engine-drawn text and fonts)', data=[], interactions=['none: display only'],
         evidence=['exe:Display subtitles during movies']),
    dict(id='engine.loading_screen', name='Loading screens', route='engine_drawn',
         why='drawn while the Lua UI does not pump (RC_LOADING_SCREEN); no layout', cost='art upscaled (loading_screen role); tips text through the .cuf route',
         owner='J37 (text), a later art job', data=[], interactions=['none: display only'],
         evidence=['exe:RC_LOADING_SCREEN', 'exe:UI/FrontEnd UI/LoadingScreen/loading_screen_heading.tga', 'role:loading_screen']),
    dict(id='engine.unit_3d_preview', name='3D unit and building previews (rotating model in information panels)', route='render_target',
         why='the engine renders the model (Stop_Rotating_Rendering; Rotate_Left/Right handlers in the unit information layout)',
         cost='host: the preview render target as a texture in an RmlUi element; rotate buttons stay RmlUi', owner='J35 (panel host)',
         data=[], interactions=['Rotate_Left / Rotate_Right hold -> engine rotation'],
         evidence=['call:BattleUI.Stop_Rotating_Rendering', 'exe:CPREVIEW_LIST_ITEM_HANDLER']),
    dict(id='engine.escape_menu_background', name='Escape menu background', route='engine_drawn',
         why='the esc_menu layouts have no background component: the paused 3D view shows through; a dim layer is a design choice (rml)',
         cost='none', owner='the escape menu contract', data=[], interactions=['none: display only'],
         evidence=['layout:battle ui/esc_menu_battle#esc_menu_battle', 'layout:campaign ui/esc_menu_campaign#esc_menu_campaign']),
    dict(id='engine.tooltips', name='Tooltips (engine-placed tooltip components)', route='rml',
         why='layout-based (templates tooltip, special_tooltip, unitcard_tooltip...) but created and placed by the engine on hover (RegisterTooltipObject)',
         cost='host: hover events and the anchor rect, so RmlUi places its own tooltip', owner='J35 (panel host)',
         data=[], interactions=['hover (engine timing)'],
         evidence=['exe:RegisterTooltipObject', 'exe:SetTooltipText', 'layout:templates/tooltip#Tooltip', 'layout:battle ui/special_tooltip#special_tooltip']),
]


def engine_drawn(at, surfaces):
    """Check every evidence item of ENGINE; returns (items with `checked`, [problems])."""
    exe_p = paths.adapter_file('exe_strings.tsv.gz')
    exe = {r[-1] for r in tsv_read(exe_p)[1]} if os.path.exists(exe_p) else set()
    anatomy = open(paths.adapter_file('frame_anatomy.md'), encoding='utf-8').read()
    calls = {n for r in at.scripts.values() for n in r['calls']}
    roles = {json.loads(x)['role'] for x in open(ASSETS, encoding='utf-8')}
    names = {f"{rel}#{c['name']}".lower() for ss in surfaces.values() for rel, r in ss.items() for c in r.get('components', [])}
    out, bad = [], []
    for e in ENGINE:
        ok = []
        for ev in e['evidence'] + e['data']:
            kind, val = ev.split(':', 1)
            hit = {'exe': lambda v: v in exe, 'call': lambda v: v in calls, 'anatomy': lambda v: v in anatomy,
                   'role': lambda v: v in roles, 'layout': lambda v: v.lower() in names}[kind](val)
            (ok if hit else bad).append(ev if hit else f"{e['id']}: evidence not found: {ev}")
        out.append(dict(e, checked=sorted(ok)))
    return out, bad


def engine_rows(items):
    rows = []
    for e in items:
        desc = (f"route: {e['route']}. {e['name']}: {e['why']}. Cost: {e['cost']}. Owner: {e['owner']}. "
                f"Evidence (read): {', '.join(e['evidence'])}. Detail: discovery/ui/engine_drawn.json.")
        r = dict(id=e['id'], description=desc, screen=e['id'], status='atlas')
        df = [dict(name=d.split(':', 1)[1], source='getter:' + d.split(':', 1)[1]) for d in e['data'] if d.startswith('call:')]
        if df:
            r['data_fields'] = df
        r['interactions'] = [dict(name=x) for x in e['interactions']]
        rows.append(r)
    return rows


# ---------------------------------------------------------------- art named at runtime from db keys (J10 item 6)
KEY_ROLES = ('flag', 'unit_card', 'portrait', 'unit_info_picture', 'building_info_picture', 'building_icon', 'event_picture',
             'technology_icon', 'achievement_icon', 'loading_screen')
SUFFIXES = ('', '_icon', '_info', '_lvl1', '_small', '_large')
# components whose name shows the role (weaker evidence than a script naming the folder: the engine fills these by getter)
ROLE_COMPONENTS = {'flag': r'(?i)flag', 'unit_card': r'(?i)unitcard|unit_card|recruitmentcard|card_image', 'portrait': r'(?i)portrait',
                   'unit_info_picture': r'(?i)unit_info|unit_pic|^picture$', 'building_info_picture': r'(?i)building_pic|building_info|^picture$',
                   'building_icon': r'(?i)building_icon|^building$', 'event_picture': r'(?i)event_?pic', 'technology_icon': r'(?i)tech_icon|technology_icon',
                   'achievement_icon': r'(?i)achievement', 'loading_screen': r'(?i)loading'}
DB_ROWS = os.path.join(ROOT, 'extract', paths.TARGET, 'db')


def art_keys(at, recs):
    """Per key-named role: the db field whose values name the role's art, the path pattern, the resolve rate and the misses, the scripts
    that name the folder (else the engine assembles the path), and the units that draw the role. Reads the decoded rows (wsc discovery db)."""
    reg = [json.loads(x) for x in open(ASSETS, encoding='utf-8')]
    tables = {}
    for fn in sorted(os.listdir(DB_ROWS)) if os.path.isdir(DB_ROWS) else []:
        d = json.load(open(os.path.join(DB_ROWS, fn), encoding='utf-8'))
        name = fn[:-5].split('_tables__')[-1] if '_tables__' in fn else fn[:-5]
        for i, f in enumerate(d['fields']):
            vals = {str(r[i]).lower() for r in d['rows'] if i < len(r) and isinstance(r[i], str) and r[i]}
            if vals:
                tables[(name, f)] = vals
    out = {}
    for role in KEY_ROLES:
        paths = sorted(r['path'].lower() for r in reg if r['role'] == role)
        if not paths:
            continue
        ids = {r['path'].lower(): r['id'] for r in reg if r['role'] == role}
        folders = collections.Counter(os.path.dirname(p) for p in paths)
        base = os.path.commonpath([os.path.dirname(p) for p in paths])
        if base.count('\\') < 1:                    # too shallow (loading_screen spans ui\frontend ui\... and ui\loading_screen_pictures)
            base = folders.most_common(1)[0][0]
            paths = [p for p in paths if p.startswith(base + '\\')]
        # a key names either a file stem in the role folder or a sub-folder (flags: ui\flags\<faction>\...)
        stems = collections.defaultdict(set)
        for p in paths:
            rel = p[len(base) + 1:]
            parts = rel.split('\\')
            stems[os.path.splitext(parts[-1])[0]].add(p)
            if len(parts) > 1:
                stems[parts[0]].add(p)
        best = None
        def strip(v):                                # a value may be a path under the role folder (factions.flags_path: data\ui\flags\austria)
            v = v.replace('/', '\\')
            v = v[5:] if v.startswith('data\\') else v
            return v[len(base) + 1:] if v.startswith(base + '\\') else v
        for (t, f), vals in tables.items():
            vals = {strip(v) for v in vals if len(v) >= 3}
            for suf in SUFFIXES:
                hit = {v for v in vals if v + suf in stems}
                if len(hit) < 3 or len(hit) / len(vals) < 0.6:
                    continue
                covered = len({p for v in hit for p in stems[v + suf]})
                score = (covered, len(hit) / len(vals))   # most of the role's art first, then the field whose values all resolve
                if best is None or score > best[0]:
                    best = (score, t, f, suf, hit, vals)
        folder_strs = sorted({base.replace('\\', '/')} | {fo.replace('\\', '/') for fo in folders if folders[fo] > 5})
        named_in = sorted(rel for rel, r in at.scripts.items() if any(any(fs in s.lower().replace('\\', '/') for fs in folder_strs) for s in r['strings']))
        idset = {ids[p] for p in paths}
        by_art = {uid for uid, ur in recs.items() if any(i in idset for c in ur['comps'] for st in c['states'] for i in st['images'])}
        by_script = {uid for uid, ur in recs.items() if any(s in named_in for s in ur['scripts'])}
        rx = re.compile(ROLE_COMPONENTS[role])
        by_name = {uid for uid, ur in recs.items() if any(rx.search(c['name']) for c in ur['comps'])}
        rec = dict(folder=base, assets=len(paths), named_in_scripts=named_in or 'none: the engine assembles the path (a getter returns it)',
                   units=sorted(by_art | by_script | by_name),
                   units_evidence=dict(static_art=sorted(by_art), script_names_folder=sorted(by_script), component_name=sorted(by_name - by_art - by_script)))
        if best:
            (n, rate), t, f, suf, hit, vals = best
            covered = sorted({p for v in hit for p in stems[v + suf]})
            v0 = sorted(hit)[0] + suf
            as_file = any(os.path.splitext(os.path.basename(p))[0] == v0 for p in stems[v0])
            exts = sorted({os.path.splitext(p)[1] for p in covered})
            rec.update(table=t, field=f, pattern=base + ('\\{value}' + suf + '.' + '|'.join(e[1:] for e in exts) if as_file else '\\{value}\\...'),
                       values=len(vals), resolved=len(hit), resolve_rate=round(rate, 3), assets_covered=len(covered),
                       misses=sorted(vals - hit)[:25], asset_ids=[ids[p] for p in covered])
        else:
            rec.update(table=None, reason='no db field names this role\'s files (assembled from several fields or not db-driven)')
        out[role] = rec
    return out


# ---------------------------------------------------------------- the live pass (J10 item 5): trees from the proxy log against the atlas
TREE = re.compile(r'j10tree (\S+) (\d+): (.*)$')
# units a probe cannot open (the brief: static_only is allowed and must say why), by id pattern
STATIC_ONLY = [
    (r'^frontend\.(mp_|multiplayer_|lobby_|host_campaign|password_entry|quickbattle|session_chat|friends_list)', 'needs a multiplayer lobby or Steam session'),
    (r'^(campaign|common)\.(mp_|multiplayer_|panel_dropin|waiting_for_players|friends_list)', 'needs a multiplayer campaign'),
    (r'^campaign\.layout_', 'needs a campaign event (the event message picks the layout)'),
    (r'^campaign\.(popup_pre_battle|popup_battle_results|settlement_captured|campaign_result|duel_challenge_received|agent_action|unit_exchange|enlist_commander|royal_family|travel_destinations|move_options|agent_options|layout_ally_attacked)', 'needs a campaign event or an order (destructive to open: it would change the campaign)'),
    (r'^battle\.(mp_postbattle|in_battle_results_popup|sp_victory_options|countdown_win_timer|victory_tickets)', 'needs a battle ending or a multiplayer battle'),
    (r'^(battle|campaign)\.esc_menu|^(battle|campaign|common)\.options', 'no proven safe route (opened by the Escape key or the escape menu; probes send no input)'),
    (r'^common\.(dialog|dialogue|mp_dialogue|mp_message)', 'opened by a script on demand (a confirmation): no safe route'),
    (r'^frontend\.credits', 'entering the credits page stops the front-end Lua pump (run 20261102_j10pc), so no probe can read it'),
]


class StaticOnlyConflict(Exception):
    """A STATIC_ONLY pattern matches a unit whose own head the live run found under its own name (J65): the pattern is too broad."""


def _tree_lines(path):
    """The log lines of one raw file: a *_proxy.log line by line, or a job.sh ctl result (*.txt, JSON) by its "log" list, which holds the
    lines the call logged. The proxy log is rewritten on every launch, so a sitting that relaunches keeps only its last launch there."""
    with open(path, encoding='utf-8', errors='replace') as fh:
        text = fh.read()
    if path.endswith('_proxy.log'):
        return text.splitlines()
    try:
        d = json.loads(text)
    except ValueError:
        return []
    return [str(x) for x in d.get('log', [])] if isinstance(d, dict) else []


def parse_trees(run_dir):
    """{label: [(path, visible, x, y, w, h, state)]} from run_dir/raw: every *_proxy.log, then every ctl result *.txt (chunks joined in
    part order). A label in a later file (logs first, then results, each in name order) replaces the whole label of an earlier one: a
    re-run sitting supersedes it, its parts never mix."""
    parts = {}
    raw = os.path.join(run_dir, 'raw')
    names = sorted(os.listdir(raw))
    for fn in [n for n in names if n.endswith('_proxy.log')] + [n for n in names if n.endswith('.txt')]:
        mine = collections.defaultdict(dict)
        for line in _tree_lines(os.path.join(raw, fn)):
            m = TREE.search(line.rstrip('\n'))
            if m:
                mine[m.group(1)][int(m.group(2))] = m.group(3)
        parts.update(mine)
    out = {}
    for label, ps in parts.items():
        text = ''.join(ps[k] for k in sorted(ps))
        nodes = []
        for item in text.split(';'):
            f = item.split('|')
            if len(f) == 5:
                xy, wh = f[2].split(','), f[3].split(',')
                num = lambda v: float(v) if re.match(r'^-?[\d.]+$', v) else None
                nodes.append((f[0], f[1] == '1', num(xy[0]), num(xy[-1]), num(wh[0]), num(wh[-1]), f[4]))
        out[label] = nodes
    return out


def live(at, units, surfaces, run_dir):
    run = os.path.basename(os.path.normpath(run_dir))
    trees = parse_trees(run_dir)
    shots = set()
    for fn in os.listdir(os.path.join(run_dir, 'raw')):
        if fn.startswith('shots_'):
            with open(os.path.join(run_dir, 'raw', fn), encoding='utf-8') as fh:
                shots |= {x.strip() for x in fh if x.strip()}
    # every live node's subtree names, by (label, path)
    sub = {}
    for label, nodes in trees.items():
        for p, *_ in nodes:
            sub.setdefault((label, p), set())
        for p, *_ in nodes:
            parts = p.split('/')
            for i in range(1, len(parts)):
                sub.setdefault((label, '/'.join(parts[:i])), set()).add(parts[-1])
    by_name = collections.defaultdict(list)
    for label, p in sub:
        by_name[p.split('/')[-1]].append((label, p))
    res, scale = {}, []
    for u in units:
        if u.get('widget') or not u.get('surface'):
            continue
        rec = surfaces[u['ctx']][u['surface'].replace('\\', '/')]
        comps = rec.get('components', [])
        if u.get('piece'):
            # the anchor is the component the piece is named by, else its shallowest one (the frame piece is what the others left)
            own = [c for c in comps if c['path'] in u['comps']]
            anchor = next((c for c in own if c['path'] == u['piece']), None) or min(own, key=lambda c: (c['path'].count('/'), c['path']), default=None)
            if anchor is None:
                res[u['id']] = dict(reach='static_only', reason='the piece has no components of its own', best_match=None)
                continue
            mine = [c for c in own if c['path'] != anchor['path']]
            heads = [anchor]
        else:
            heads = [c for c in comps if c['parent'] == 'root'] or comps[:1]
            mine = [c for c in comps if c['path'] != 'root' and c not in heads]
        static = {c['name'] for c in mine}
        known = next(((rx, w) for rx, w in STATIC_ONLY if re.search(rx, u['id'])), None)
        best = None
        for h in heads:
            cands = by_name.get(h['name'], [])
            if not cands:
                # attached under another name: the engine loads land_battle_orders into the HUD's "orders" placeholder, which keeps
                # the placeholder's name (run 20261102_j10pc), so the head is found as the live parent of its children
                kids = {c['name'] for c in comps if c['parent'] == h['path']}
                cands = sorted({(label, p.rsplit('/', 1)[0]) for k in kids for label, p in by_name.get(k, []) if '/' in p})
            for label, p in cands:
                livenames = sub[(label, p)]
                matched = static & livenames
                score = len(matched) / len(static) if static else 1.0
                if best is None or score > best[0]:
                    best = (score, label, p, len(static), len(livenames), len(matched), h)
        if known:
            # a unit with a known reason (a multiplayer lobby, an event) is never matched by names: another page can hold the same
            # component names (the options page holds password_entry's), and the reason is the true one. The guard (J65): when the
            # unit's own head is found under its own name as a top-level live node at agreement 0.75 or more, the run reached it and
            # the pattern is wrong, so the step fails (a nested match is another page's node and is no conflict)
            if best and best[0] >= 0.75 and best[6]['name'] == best[2].split('/')[-1] and '/' not in best[2]:
                raise StaticOnlyConflict(f"STATIC_ONLY pattern {known[0]!r} ({known[1]}) matches {u['id']}, but run {run} reached it: "
                                         f"live path {best[2]} in state {best[1]}, agreement {best[0]:.3f}. Narrow the pattern.")
            res[u['id']] = dict(reach='static_only', reason=known[1], best_match=None)
            continue
        if best and best[3] < 3 and not (u.get('piece') and best[6]['name'] == best[2].split('/')[-1]):
            # a generic head name (Banner, CharacterAttribute) with one or two parts below it says nothing: too small to tell from a tree
            # (a HUD piece found by its own anchor, cards_panel, is named specifically enough)
            res[u['id']] = dict(reach='static_only', reason='fewer than 3 components: a tree match by name is no evidence',
                                best_match=dict(state=best[1], live_path=best[2], agreement=round(best[0], 3)))
        elif best and best[0] >= 0.75:
            score, label, p, ns, nl, nm, h = best
            node = next(n for n in trees[label] if n[0] == p)
            res[u['id']] = dict(reach='reached', run=run, state=label, live_path=p, static_components=ns, live_components=nl,
                                matched=nm, agreement=round(score, 3), visible=node[1], shot=f'j10_{label}.jpg' if f'j10_{label}.jpg' in shots else None,
                                _scale=(node[4] / h['w'] if h['w'] and node[4] else None), _named=h['name'] == p.split('/')[-1])
        else:
            why = f'not reached in run {run}: no proven safe route opened it'
            res[u['id']] = dict(reach='static_only', reason=why, best_match=(dict(state=best[1], live_path=best[2], agreement=round(best[0], 3)) if best else None))
    # one live node explains one unit: the mp_ front-end pages are copies of the sp_ ones and the options tabs sit inside the options page,
    # so the best match (agreement, matched count, the head named as the node) keeps the node and the others are static_only
    claims = collections.defaultdict(list)
    for uid, r in res.items():
        if r['reach'] == 'reached':
            claims[(r['state'], r['live_path'])].append(uid)
    for (label, p), uids in claims.items():
        uids.sort(key=lambda x: (-res[x]['agreement'], -res[x]['matched'], not res[x]['_named'], x))
        for uid in uids[1:]:
            r = res[uid]
            res[uid] = dict(reach='static_only', reason=f'its best live match ({label} {p}) is {uids[0]}\'s', best_match=dict(state=label, live_path=p, agreement=r['agreement']))
    for r in res.values():
        if r['reach'] == 'reached':
            if r['_scale']:
                scale.append(r['_scale'])
            del r['_scale'], r['_named']
    reached = [r for r in res.values() if r['reach'] == 'reached']
    per_ctx = collections.defaultdict(lambda: [0, 0])
    for uid, r in res.items():
        per_ctx[uid.split('.')[0]][1] += 1
        per_ctx[uid.split('.')[0]][0] += r['reach'] == 'reached'
    scale.sort()
    med = scale[len(scale) // 2] if scale else None
    return dict(run=run, states={k: dict(nodes=len(v), visible_top=[n[0] for n in v if '/' not in n[0]],
                                          shot=f'j10_{k}.jpg' if f'j10_{k}.jpg' in shots else None) for k, v in sorted(trees.items())},
                reached=len(reached), units=len(res), reached_by_context={k: f'{a} of {b}' for k, (a, b) in sorted(per_ctx.items())},
                agreement=dict(matched=sum(r['matched'] for r in reached), static=sum(r['static_components'] for r in reached),
                               mean=round(sum(r['agreement'] for r in reached) / len(reached), 3) if reached else None),
                width_scale=dict(median=round(med, 4) if med else None, n=len(scale),
                                 note='live width / static width of the matched head components; 1080/960 = 1.125, 1080/1024 = 1.0547'),
                units_reach=dict(sorted(res.items())))


# ---------------------------------------------------------------- outputs
def write_atlas(at, units, surfaces, recs, engine=(), reach=None, keyed=None):
    shas = {}
    for ctx, ss in sorted(surfaces.items()):
        shas[f'{ctx}.json.gz'] = jdump(os.path.join(OUT, f'{ctx}.json.gz'), dict(context=ctx, surfaces=ss), gz=True)
    shas['scripts.json.gz'] = jdump(os.path.join(OUT, 'scripts.json.gz'), dict(scripts=at.scripts, fails=at.script_fails, panels=at.panels), gz=True)
    units_out, detail = {}, {}
    for u in units:
        ur = recs[u['id']]
        f = ur['facts']
        rr = ((reach or {}).get('units_reach') or {}).get(u['id'])   # widgets have no reach: None
        units_out[u['id']] = dict(screen=u['screen'], surface=u.get('surface'), piece=u.get('piece'),
                                  complexity=complexity(ur, rr['reach'] == 'reached' if rr else None),
                                  hotkeys=hotkeys_for(at, ur['scripts']))
        detail[u['id']] = dict(scripts=ur['scripts'], unresolved=f['unresolved'], not_in_state=f['not_in_state'], not_in_api=f['not_in_api'],
                               engine_calls=f['calls'], interactions=ur['interactions'])
    for e in engine:
        units_out[e['id']] = dict(screen=e['id'], surface=None, piece=None, route=e['route'], complexity=None, hotkeys=[])
    shas['units.json.gz'] = jdump(os.path.join(OUT, 'units.json.gz'), dict(units=detail), gz=True)
    if engine:
        jdump(os.path.join(OUT, 'engine_drawn.json'), dict(generator='discovery/core/ui_atlas.py (ENGINE)', items=list(engine)))
    lay = [r for ss in surfaces.values() for r in ss.values() if r['kind'] == 'layout']
    tpls = [r for r in surfaces['template'].values() if r['kind'] == 'uied_template']
    comps = [c for ss in surfaces.values() for r in ss.values() for c in r.get('components', [])]
    keys = [st.get(k) for c in comps for st in c['states'] for k in ('text_key', 'tooltip_key') if st.get(k)] + [c['tooltip_key'] for c in comps if c.get('tooltip_key')]
    imgs = [i for c in comps for st in c['states'] for i in st['images']]
    fields = sum(len(recs[u]['facts']['sourced']) for u in recs)
    unres = collections.Counter(x['kind'] for u in recs for x in recs[u]['facts']['unresolved'])
    summary = dict(
        generator='discovery/core/ui_atlas.py',
        counts=dict(layouts=len(lay), layouts_read=sum(1 for r in lay if r.get('components')), uied_records=len(tpls),
                    uied_records_read=sum(1 for r in tpls if 'components' in r), scripts=len(at.scripts) + len(at.script_fails),
                    scripts_walked=len(at.scripts), components=len(comps), units=len(units) + len(engine),
                    units_by_context=dict(sorted((collections.Counter(u['ctx'] for u in units) + collections.Counter(engine=len(engine))).items())),
                    engine_drawn=len(engine), engine_routes=dict(sorted(collections.Counter(e['route'] for e in engine).items())),
                    text_keys=len(keys), text_keys_resolved=sum(1 for k in keys if k in at.loc),
                    art_uses=len(imgs), art_resolved=sum(1 for i in imgs if ':' not in i),
                    data_fields_sourced=fields, data_fields_unresolved=sum(len(recs[u]['facts']['unresolved']) for u in recs),
                    unresolved_by_reason=dict(sorted(unres.items())),
                    interactions=sum(len(recs[u]['interactions']) for u in recs),
                    handlers_not_found=sum(1 for ss in surfaces.values() for r in ss.values() for h in r.get('handlers', []) if h['defined_in'].startswith('not found')),
                    handlers_in_missing_scripts=sum(1 for ss in surfaces.values() for r in ss.values() for h in r.get('handlers', []) if 'not shipped' in h['defined_in']),
                    engine_command_handlers=sum(1 for ss in surfaces.values() for r in ss.values() for h in r.get('handlers', []) if h['defined_in'] == 'engine command'),
                    scripts_missing=sorted({c['script'][8:] for ss in surfaces.values() for r in ss.values() for c in r.get('components', []) if c.get('script', '').startswith('missing:')}),
                    art_editor_paths=sum(1 for i in imgs if i.startswith('editor_path:')),
                    getters_not_in_state=sorted({g for u in detail.values() for g in u['not_in_state']}),
                    calls_not_in_api=sorted({g for u in detail.values() for g in u['not_in_api']}),
                    frame_groups=sum(len(r.get('frame_groups', [])) for ss in surfaces.values() for r in ss.values())),
        layout_bases=dict(sorted(collections.Counter(f"{r['base'][0]}x{r['base'][1]}" for r in lay).items())),
        panels=at.panels, panels_without_layout=sorted(k for k, v in at.panels.items() if v and v.replace('/', '\\') not in at.layouts),
        unread=sorted(r['path'] for r in tpls if 'layout_unread' in r),
        scripts_unattached=sorted(set(at.scripts) - {s for u in recs.values() for s in u['scripts']}),
        engine_items=[[e['id'], e['route'], e['owner']] for e in engine],
        reach=(f"{reach['reached']} of {reach['units']} layout and template units reached live in run {reach['run']} "
               f"({', '.join(f'{k} {v}' for k, v in reach['reached_by_context'].items())}); static-vs-live agreement "
               f"{reach['agreement']['matched']} of {reach['agreement']['static']} components (mean {reach['agreement']['mean']}); "
               f"the rest static_only with the reason (`reach.json`)." if reach else None),
        art_keys=('; '.join(f"{k} {v['table']}.{v['field']} -> {v['pattern']} ({round(v['resolve_rate'] * 100)} % of values resolve, "
                            f"{v['assets_covered']} of {v['assets']} files)" if v.get('table') else f"{k}: no db rule ({v['reason']})"
                            for k, v in sorted(keyed.items())) + ' (`art_keys.json`).') if keyed else None,
        units=dict(sorted(units_out.items())), sha256=dict(sorted(shas.items())))
    jdump(os.path.join(OUT, 'summary.json'), summary)
    return summary


def hotkeys_for(at, scripts):
    strs = {x for s in scripts if 'OnShortcut' in at.scripts[s]['defines'] for x in at.scripts[s]['strings']}
    return sorted(h['id'] for h in at.hot if h.get('action') in strs)


ORDER = ('id', 'description', 'screen', 'vanilla_source', 'data_fields', 'interactions', 'status', 'review_link')   # schema order
ATLAS_FILES = ('battle.json.gz', 'campaign.json.gz', 'common.json.gz', 'frontend.json.gz', 'template.json.gz', 'scripts.json.gz',
               'units.json.gz')


def problems(out_dir, rows_path):
    """What `wsc discovery check` needs without the game files: each atlas file as summary.json records it (sha256 of the
    inflated JSON), a gzip header with no name and mtime 0, and the ui_elements rows naming exactly the summary's units."""
    bad = []
    with open(os.path.join(out_dir, 'summary.json'), encoding='utf-8') as fh:
        s = json.load(fh)
    for f in ATLAS_FILES:
        p = os.path.join(out_dir, f)
        if not os.path.exists(p):
            bad.append(f'{p}: missing; run `wsc discovery ui`')
            continue
        with open(p, 'rb') as fh:
            raw = fh.read()
        if raw[3] != 0 or raw[4:8] != b'\0\0\0\0':
            bad.append(f'{p}: gzip header has a name or mtime (want flags 0, mtime 0)')
        if hashlib.sha256(gzip.decompress(raw)).hexdigest() != s['sha256'].get(f):
            bad.append(f'{p}: not the file summary.json records; run `wsc discovery ui`')
    with open(rows_path, encoding='utf-8') as fh:
        rows = [json.loads(x) for x in fh]
    ids = [r['id'] for r in rows]
    if set(ids) != set(s['units']) or len(ids) != len(set(ids)):
        bad.append(f'{rows_path}: ids differ from discovery/ui/summary.json units; run `wsc discovery ui`')
    for r in rows:
        if r.get('status') == 'atlas' and r['id'] in s['units'] and r.get('screen') != s['units'][r['id']]['screen']:
            bad.append(f"{rows_path}: {r['id']}: screen differs from the atlas")
    assets_path = os.path.join(os.path.dirname(rows_path), 'assets.jsonl')
    if os.path.exists(assets_path):
        bad += used_by_problems(out_dir, s, set(ids), assets_path)
    return bad


def committed_art_users(out_dir, s):
    """art_users from the committed atlas alone: what write_used_by would set. Units come from summary.json, a piece's components by the rule of build_units."""
    surfaces = {}
    for f in ATLAS_FILES:
        if f not in ('scripts.json.gz', 'units.json.gz') and os.path.exists(os.path.join(out_dir, f)):
            with gzip.open(os.path.join(out_dir, f)) as fh:
                surfaces.update(json.load(fh).get('surfaces', {}))
    recs = {}
    for uid, u in s['units'].items():
        if u.get('surface') and u.get('piece') is None:
            recs[uid] = dict(comps=surfaces.get(u['surface'].replace('\\', '/'), {}).get('components', []))
    by_prefix = {(u['surface'], u['piece']): uid for uid, u in s['units'].items() if u.get('piece') is not None}
    for rel, pieces in PIECES.items():
        taken = set()
        for _, prefix in pieces:
            cs = [c for c in surfaces.get(rel.replace('\\', '/'), {}).get('components', [])
                  if (c['path'] == prefix or c['path'].startswith(prefix + '/')) and c['path'] not in taken]
            taken |= {c['path'] for c in cs}
            if (rel, prefix) in by_prefix:
                recs[by_prefix[rel, prefix]] = dict(comps=cs)
    extra = collections.defaultdict(set)
    keys_path = os.path.join(out_dir, 'art_keys.json')
    if os.path.exists(keys_path):
        with open(keys_path, encoding='utf-8') as fh:
            for role in json.load(fh)['roles'].values():
                for aid in role.get('asset_ids', []):
                    extra[aid] |= set(role['units'])
    return art_users(recs, extra)


def used_by_problems(out_dir, s, ids, assets_path, limit=10):
    """used_by on the assets rows: every id is a ui_elements row, and each row says what write_used_by would set now."""
    users = committed_art_users(out_dir, s)
    with open(assets_path, encoding='utf-8') as fh:
        assets = [json.loads(x) for x in fh]
    bad = []
    for r in assets:
        have = r.get('used_by')
        dangling = sorted(set(have or []) - ids)
        if dangling:
            bad.append(f"{assets_path}: {r['id']}: used_by names no ui_elements row: {', '.join(dangling)}")
        elif have != users.get(r['id']):
            bad.append(f"{assets_path}: {r['id']}: used_by differs from the atlas; run `wsc discovery ui`")
    return bad[:limit] + ([f'{assets_path}: {len(bad) - limit} more used_by problems'] if len(bad) > limit else [])


def readme(s):
    c = s['counts']
    ctx = ', '.join(f'{k} {v}' for k, v in c['units_by_context'].items())
    lines = [
        '# Vanilla UI atlas (J10)', '',
        'Generated by `python3 core/wsc.py discovery render` from `summary.json` (written by `discovery/core/ui_atlas.py`). Do not edit.',
        'Re-run: `python3 core/wsc.py discovery ui` on the PC (needs the extract, `discovery/README.md`); `wsc discovery check` checks the files.', '',
        '## Files', '',
        '- `<context>.json.gz` (battle, campaign, common, frontend, template): every layout and uied.templates record: components (path, rect, '
        'flags, states with art as `assets` ids, text and tooltip keys and lengths, fonts, transitions, animations), events with their handler and '
        "where it is defined, scripts attached, who opens it, templates used, frame groups. Loc text is never written, only keys.",
        '- `scripts.json.gz`: the symbolic walk of every compiled UI script (`discovery/core/ui_walk.py`): engine calls, fields read off engine results, '
        'handlers, data passed in, panel ids.',
        '- `summary.json`: counts and per unit the complexity record and hotkeys; `units.json.gz`: per unit the scripts, engine calls, '
        'interactions, unresolved fields with the reason, getters not in the state they run in.',
        '- `registries/ui_elements.jsonl`: one row per pipeline unit at status `atlas`, generated from the same records.', '',
        '## Counts', '',
        '| Item | Count |', '|---|---|',
        f"| layouts read | {c['layouts_read']} of {c['layouts']} |",
        f"| uied.templates records read | {c['uied_records_read']} of {c['uied_records']} (unread: {', '.join(s['unread'])}) |",
        f"| compiled scripts walked | {c['scripts_walked']} of {c['scripts']} |",
        f"| components | {c['components']} |",
        f"| units (rows) | {c['units']} ({ctx}) |",
        f"| text keys in the loc tables | {c['text_keys_resolved']} of {c['text_keys']} |",
        f"| art uses resolved to `assets` ids | {c['art_resolved']} of {c['art_uses']} ({c['art_editor_paths']} UI-editor paths) |",
        f"| data fields sourced | {c['data_fields_sourced']} |",
        f"| fields unresolved (reason in summary.json) | {c['data_fields_unresolved']} ({', '.join(f'{k} {v}' for k, v in c['unresolved_by_reason'].items())}) |",
        f"| interactions | {c['interactions']} |",
        f"| handlers not found / in unshipped scripts / engine commands | {c['handlers_not_found']} / {c['handlers_in_missing_scripts']} / {c['engine_command_handlers']} |",
        f"| script names components give that the game does not ship | {len(c['scripts_missing'])} |",
        f"| 9-slice frame groups | {c['frame_groups']} |", '',
        'Layout bases (root size): ' + ', '.join(f'{k} {v}' for k, v in s['layout_bases'].items()) + '.']
    if s.get('engine_items'):
        lines += ['', '## Engine-drawn items (`engine_drawn.json`, rows `engine.*`; routes are proposals, D39)', '',
                  '| Item | Route | Owner |', '|---|---|---|'] + [f'| `{i}` | {r} | {o} |' for i, r, o in s['engine_items']]
    for k in ('reach', 'art_keys'):
        if s.get(k):
            lines += ['', f"{k.replace('_', ' ').capitalize()}: {s[k]}"]
    return '\n'.join(lines) + '\n'


def write_rows(rs):
    with open(ROWS, 'w', encoding='utf-8', newline='\n') as f:
        for r in sorted(rs, key=lambda r: r['id']):
            f.write(json.dumps({k: r[k] for k in ORDER if k in r}, ensure_ascii=False) + '\n')


def art_users(recs, extra=None):
    """assets id -> sorted ui_elements ids that draw it (layout art per unit; `extra` adds the key-named art of art_keys.json)."""
    out = collections.defaultdict(set)
    for uid, ur in recs.items():
        for c in ur['comps']:
            for st in c['states']:
                for i in st['images']:
                    if ':' not in i:
                        out[i].add(uid)
    for aid, uids in (extra or {}).items():
        out[aid] |= set(uids)
    return {k: sorted(v) for k, v in out.items()}


def write_used_by(users):
    """Set used_by on the assets registry (J7 keeps it on a re-run, assets.py KEEP); rows keep the schema's key order."""
    import assets
    schema = json.load(open(os.path.join(paths.layout.own_root(), 'schemas', 'assets.schema.json'), encoding='utf-8'))
    order = list(schema['properties'])
    rows = assets.read_registry(ASSETS)
    n = 0
    for r in rows:
        r.pop('used_by', None)
        if r['id'] in users:
            r['used_by'] = users[r['id']]
            n += 1
    assets.write_registry([{k: r[k] for k in order if k in r} for r in rows], ASSETS)
    return n


def extract_problem(games, step):
    """Why this step cannot run, or None: without the extract every step reads nothing and would write empty results without an error."""
    root = os.path.join(ROOT, games['extract'], paths.TARGET)
    if not [d for d in (os.listdir(root) if os.path.isdir(root) else []) if d != 'db']:
        return f'{root} is absent or empty: build it with `python3 core/proxy/tools/pack_list.py --extract`'
    if step in ('art', 'all') and not (os.path.isdir(DB_ROWS) and os.listdir(DB_ROWS)):
        return f'{DB_ROWS} is absent or empty: build it with `python3 core/wsc.py discovery db`'
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('step', nargs='?', default='all', choices=('atlas', 'rows', 'live', 'art', 'all'))
    ap.add_argument('--games')
    ap.add_argument('--run', help='live: the run folder whose raw/*_proxy.log hold the j10tree lines (writes discovery/ui/reach.json)')
    a = ap.parse_args(argv)
    games = load_games(a.games)
    missing = extract_problem(games, a.step)
    if missing:
        print(f'ui_atlas: {missing}; nothing written', file=sys.stderr)
        return 1
    at = Atlas(games)
    units, surfaces = build_units(at)
    reach_path = os.path.join(OUT, 'reach.json')
    if a.step == 'all' and not a.run and os.path.exists(reach_path):
        # the live pass follows the atlas: re-match the committed run against the units just built (a stale reach.json kept
        # units static_only after the atlas changed)
        with open(reach_path, encoding='utf-8') as fh:
            a.run = 'harness/runs/' + json.load(fh)['run']
        a.step = 'live'
    if a.step == 'live':
        r = live(at, units, surfaces, os.path.join(ROOT, a.run) if not os.path.isabs(a.run) else a.run)
        jdump(reach_path, r)
        print(json.dumps({k: v for k, v in r.items() if k not in ('units_reach', 'states')}, indent=1))
        a.step = 'all'
    reach = json.load(open(reach_path, encoding='utf-8')) if os.path.exists(reach_path) else None
    rs, recs = rows(at, units, surfaces, reach)
    keys_path = os.path.join(OUT, 'art_keys.json')
    if a.step in ('art', 'all'):
        # `all` (what `wsc discovery ui` runs) rewrites the art rules too, so a re-run checks them like every other file
        ak = art_keys(at, recs)
        jdump(keys_path, dict(generator='discovery/core/ui_atlas.py art', roles=ak))
        for k, v in ak.items():
            print(k, v.get('table'), v.get('field'), v.get('pattern'), v.get('resolve_rate'), v.get('assets_covered'), '/', v['assets'], len(v['units']), 'units')
        a.step = 'all'
    keyed = json.load(open(keys_path, encoding='utf-8'))['roles'] if os.path.exists(keys_path) else {}
    extra = collections.defaultdict(set)
    for role in keyed.values():
        for aid in role.get('asset_ids', []):
            extra[aid] |= set(role['units'])
    engine, bad = engine_drawn(at, surfaces)
    if bad:
        print('\n'.join(bad))
        return 1
    rs += engine_rows(engine)
    if a.step in ('atlas', 'all'):
        s = write_atlas(at, units, surfaces, recs, engine, reach, keyed)
        print(json.dumps(s['counts'], indent=1))
    if a.step in ('rows', 'all'):
        write_rows(rs)
        n = write_used_by(art_users(recs, extra))
        print(f'{ROWS}: {len(rs)} rows; {n} assets rows with used_by')
    return 0


if __name__ == '__main__':
    sys.exit(main())
