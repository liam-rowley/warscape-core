#!/usr/bin/env python3
"""Generate the proxy adapter's C++ tables (exe identity, engine sites, config keys) and its default config file from the registries.

purpose: turn the game repo's registries/engine_sites.jsonl, registries/config_keys.jsonl and its proxy adapter's identity.json into <adapter>/generated/tables.h and the shipped default config file, validating every site (hex, lengths, overlaps, config key, exe pin; value_key rows: the key's explicit int/float type, default 0, a max, 4 stock bytes that round-trip) and every key (type, default, release value, min/max range); docs/PROXY_SITES.md
usage: python3 proxy/tools/gen_tables.py [--adapter <repo-relative adapter folder>] [--check]   (default adapter: proxy/tools/layout.py)
when: after any change to the engine_sites or config_keys registry or identity.json (then rebuild the DLL); --check runs in the gates (tests/test_proxy_tables.py) and fails when the generated files are stale or a site is invalid
not-a-verb: games cannot add wsc verbs for the proxy yet (wsc.toml verb_dirs is empty and the generator moves to warscape-core with proxy/core at the end of phase 1); the gates reach it through tests/
"""
import argparse
import json
import math
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout  # noqa: E402  (the game repo and its adapter, before and after the move to warscape-core)

ROOT = layout.game_root()
MAX_BYTES = 32   # patch_engine.h kMaxSiteBytes
HEX = re.compile(r'^[0-9a-f]{2}( [0-9a-f]{2})*$')


def jsonl(path):
    p = ROOT / path
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]


def hexbytes(s):
    return [int(x, 16) for x in s.split()]


def c_str(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def c_wstr(s):
    return 'L' + c_str(s)


def c_bytes(b):
    return '{ ' + ', '.join(f'0x{x:02x}' for x in b) + (' }' if b else '0 }')


VALUE_TYPES = {'float': ('<f', 'kValueF32'), 'int': ('<i', 'kValueI32')}


def is_value_row(s):
    return s.get('value_key') is not None


def value_row_errors(s, keys):
    """A value row (W7, docs/PROXY_SITES.md): its bytes come from a numeric config key. Each message names the row and the fix."""
    sid, errs = s['id'], []
    vk = s.get('value_key')
    if vk is None:
        return [f'{sid}: value_scale and value_floor_stock belong to value_key rows: add a value_key or drop them']
    if s['kind'] != 'patch':
        errs.append(f'{sid}: value_key is for patch rows, not {s["kind"]} rows')
    if 'patch_bytes' in s:
        errs.append(f'{sid}: both patch_bytes and value_key: a value row takes its bytes from the key, drop patch_bytes')
    if s.get('config_key'):
        errs.append(f'{sid}: both config_key and value_key: the value key at 0 is the off switch, drop config_key')
    sc = s.get('value_scale', 1)
    if isinstance(sc, bool) or not isinstance(sc, (int, float)) or not math.isfinite(sc) or sc <= 0:
        errs.append(f'{sid}: value_scale {sc!r} must be a number above 0')
    if not isinstance(s.get('value_floor_stock', False), bool):
        errs.append(f'{sid}: value_floor_stock must be true or false')
    k = next((k for k in keys if k['id'] == vk), None)
    if k is None:
        return errs + [f'{sid}: value_key {vk} is not in the config_keys registry: add the key (type, default 0, max)']
    if validate_key(k):
        return errs + [f'{sid}: value_key {vk} is an invalid config key (its own errors say why)']
    t = k.get('type')
    if t is None:
        return errs + [f'{sid}: value_key {vk} has no explicit type: add "type": "float" or "int" to its config_keys row (JSON 0 is an int)']
    if t not in VALUE_TYPES:
        return errs + [f'{sid}: value_key {vk} is a {t} key: a value row needs an int or float key']
    d = k.get('default')
    if isinstance(d, bool) or d != 0:
        errs.append(f'{sid}: value_key {vk} has default {d!r}: it must be 0 (0 means stock)')
    if 'max' not in k:
        errs.append(f'{sid}: value_key {vk} has no max: add the tested ceiling, so an ini can never ask for an untested value')
    if k.get('min', 0) > 0 or k.get('max', 0) < 0:
        errs.append(f'{sid}: value_key {vk} range [{k.get("min")}, {k.get("max")}] must contain 0 (0 means stock)')
    st = hexbytes(s['stock_bytes'])
    if len(st) != 4:
        return errs + [f'{sid}: a value row needs 4 stock bytes (a float32 or int32), it has {len(st)}']
    fmt = VALUE_TYPES[t][0]
    v = struct.unpack(fmt, bytes(st))[0]
    if t == 'float' and not math.isfinite(v):
        return errs + [f'{sid}: stock_bytes {s["stock_bytes"]} are not a finite float32: is the key\'s type right?']
    if list(struct.pack(fmt, v)) != st:   # the round trip: decode the stock, encode it back, the same bytes
        errs.append(f'{sid}: stock_bytes {s["stock_bytes"]} do not round-trip through {t} ({v!r}): is the key\'s type right?')
    return errs


def validate_sites(sites, keys, ident):
    errs = []
    key_ids = {k['id'] for k in keys}
    spans = []
    for s in sites:
        sid = s['id']
        fixed = s['kind'] == 'patch' and not is_value_row(s)
        for f in ('anchor_bytes', 'stock_bytes') + (('patch_bytes',) if fixed else ()):
            if f not in s or not HEX.match(s[f]):
                errs.append(f'{sid}: {f} missing or not lowercase hex pairs (or give a value_key)' if f == 'patch_bytes' else
                            f'{sid}: {f} missing or not lowercase hex pairs')
        if errs and errs[-1].startswith(sid):
            continue
        a, st = hexbytes(s['anchor_bytes']), hexbytes(s['stock_bytes'])
        if len(a) > MAX_BYTES or len(st) > MAX_BYTES:
            errs.append(f'{sid}: anchor or stock longer than {MAX_BYTES} bytes')
        if is_value_row(s) or 'value_scale' in s or 'value_floor_stock' in s:
            errs += value_row_errors(s, keys)
        elif s['kind'] == 'patch':
            p = hexbytes(s['patch_bytes'])
            if len(p) != len(st):
                errs.append(f'{sid}: patch_bytes has {len(p)} bytes, stock_bytes {len(st)} (a patch replaces exactly the stock bytes)')
            if p == st:
                errs.append(f'{sid}: patch_bytes equal stock_bytes (nothing to patch)')
        if s['kind'] == 'hook' and len(st) < 5:
            errs.append(f'{sid}: a hook needs at least 5 stock bytes (a rel32 jmp)')
        if s.get('config_key') and s['config_key'] not in key_ids:
            errs.append(f"{sid}: config_key {s['config_key']} is not in the config_keys registry")
        if s.get('config_key'):
            k = next((k for k in keys if k['id'] == s['config_key']), None)
            if k and key_kind_or_none(k) != 'bool':
                errs.append(f"{sid}: config_key {s['config_key']} must be a boolean key (it switches the site on or off)")
        if s.get('exe') and s['exe'] != 'sha1:' + ident['sha1']:
            errs.append(f"{sid}: exe {s['exe']} is not the pinned identity sha1:{ident['sha1']}")
        rva = int(s['rva'], 16)
        spans.append((rva, rva + len(a) + len(st), sid))
    spans.sort()
    for (lo1, hi1, a1), (lo2, hi2, a2) in zip(spans, spans[1:]):
        if lo2 < hi1:
            errs.append(f'{a1} and {a2} overlap (RVA 0x{lo1:x}-0x{hi1:x} and 0x{lo2:x}-0x{hi2:x})')
    return errs


KEY_TYPES = {'bool': 'kBool', 'int': 'kInt', 'string': 'kStr', 'float': 'kFloat'}
FLT_MAX = struct.unpack('<f', bytes.fromhex('ffff7f7f'))[0]


def key_kind(k):
    """The key's type: its explicit `type`, else inferred from `default` as before W7 (a float default needs an explicit type)."""
    if k.get('type') is not None:
        if k['type'] not in KEY_TYPES:
            raise ValueError(f"type {k['type']!r}: one of {', '.join(KEY_TYPES)}")
        return k['type']
    v = k.get('default')
    if isinstance(v, bool):
        return 'bool'
    if isinstance(v, int):
        return 'int'
    if isinstance(v, str):
        return 'string'
    raise ValueError(f'default {v!r}: only bool, int and string defaults infer a type (give "type": "float" for a float key)')


def key_kind_or_none(k):
    try:
        return key_kind(k)
    except ValueError:
        return None   # the key's own refusal names it (validate_key)


def value_text(kind, v):
    """The text of value v for a key of this kind (the table's default and the ini); ValueError when v is not that kind."""
    if kind == 'bool' and isinstance(v, bool):
        return '1' if v else '0'
    if kind == 'int' and isinstance(v, int) and not isinstance(v, bool):
        if not -2**31 <= v < 2**31:
            raise ValueError(f'{v!r} does not fit int32')
        return str(v)
    if kind == 'float' and isinstance(v, (int, float)) and not isinstance(v, bool):
        if not math.isfinite(v) or abs(v) > FLT_MAX:
            raise ValueError(f'{v!r} is not a finite float32')
        return repr(float(v))
    if kind == 'string' and isinstance(v, str):
        return v
    raise ValueError(f'{v!r} is not a valid {kind}')


def key_type(k):
    """(KeyType enumerator, default text) of a config_keys row."""
    kind = key_kind(k)
    return KEY_TYPES[kind], value_text(kind, k['default'])


def validate_key(k):
    """Every refusal for one config_keys row (type, default, release_value, range)."""
    errs, kid = [], k['id']
    if '.' not in kid:
        errs.append(f'config key {kid}: ids are <section>.<key> (the INI section and key)')
    try:
        kind = key_kind(k)
    except ValueError as e:
        return errs + [f'config key {kid}: {e}']
    for f in ('default', 'release_value'):
        if f in k:
            try:
                value_text(kind, k[f])
            except ValueError as e:
                errs.append(f'config key {kid}: {f} {e}')
    rng = {f: k[f] for f in ('min', 'max') if f in k}
    if rng and kind not in ('int', 'float'):
        return errs + [f'config key {kid}: min and max are for int and float keys, not {kind}']
    for f, v in rng.items():
        try:
            value_text(kind, v)
        except ValueError as e:
            errs.append(f'config key {kid}: {f} {e}')
    if errs:
        return errs
    lo, hi = rng.get('min'), rng.get('max')
    if lo is not None and hi is not None and lo > hi:
        errs.append(f'config key {kid}: min {lo} is above max {hi}')
    for f in ('default', 'release_value'):
        if f in k and ((lo is not None and k[f] < lo) or (hi is not None and k[f] > hi)):
            errs.append(f'config key {kid}: {f} {k[f]} is outside [min {lo}, max {hi}]')
    return errs


def render_header(ident, sites, keys, adapter):
    out = [f'// GENERATED by proxy/tools/gen_tables.py from {adapter}/identity.json and registries/engine_sites.jsonl,',
           '// registries/config_keys.jsonl. Do not edit: change the registry, run the generator, rebuild.',
           '#pragma once', '#include "adapter.h"   // the core contract (build.sh puts the core sources on the include path)', '', 'namespace wsp { namespace gen {', '',
           f"static const char* const kGameName = {c_str(ident['game'])};",
           f"static const wchar_t* const kConfigFile = {c_wstr(ident['config_file'])};",
           f"static const wchar_t* const kModDir = {c_wstr(ident['mod_dir'])};",
           f"static const wchar_t* const kInstanceMutex = {c_wstr(ident['instance_mutex'])};",
           f"static const Identity kIdentity = {{ {c_str(ident['exe_name'])}, {c_str(ident['sha1'])}, {ident['time_date_stamp']}u, {ident['size_of_image']}u }};",
           '']
    out.append(f'static const size_t kSiteCount = {len(sites)};')
    values = any(is_value_row(s) for s in sites)   # the value fields are emitted on value rows only: other tables stay byte-identical
    out.append('static const SiteDef kSites[kSiteCount + 1] = {   // id, kind, rva, anchorLen, anchor, len, stock, patch, configKey' +
               (' [, valueKey, valueType, valueFloorStock, valueScale]' if values else ''))
    kinds = {k['id']: key_kind_or_none(k) for k in keys}
    for s in sites:
        a, st = hexbytes(s['anchor_bytes']), hexbytes(s['stock_bytes'])
        p = hexbytes(s['patch_bytes']) if s['kind'] == 'patch' and not is_value_row(s) else []
        ck = c_str(s['config_key']) if s.get('config_key') else 'nullptr'
        v = ''
        if is_value_row(s):
            v = (f", {c_str(s['value_key'])}, {VALUE_TYPES[kinds[s['value_key']]][1]}, {1 if s.get('value_floor_stock') else 0},"
                 f" {float(s.get('value_scale', 1))!r}")
        out.append(f"    {{ {c_str(s['id'])}, {'kPatch' if s['kind'] == 'patch' else 'kHook'}, {s['rva']}u, {len(a)}, {c_bytes(a)}, {len(st)}, {c_bytes(st)}, {c_bytes(p)}, {ck}{v} }},")
    out.append('    { nullptr, 0, 0, 0, { 0 }, 0, { 0 }, { 0 }, nullptr }   // sentinel (keeps the array non-empty)')
    out.append('};')
    out.append('')
    out.append(f'static const size_t kKeyCount = {len(keys)};')
    out.append('static const KeySpec kKeys[kKeyCount + 1] = {')
    for k in keys:
        t, d = key_type(k)
        kind = key_kind(k)
        rng = ''   # min/max only on rows that have them, so the others stay byte-identical
        if 'min' in k or 'max' in k:
            rng = ''.join(', ' + (c_str(value_text(kind, k[f])) if f in k else 'nullptr') for f in ('min', 'max'))
        out.append(f"    {{ {c_str(k['id'])}, {t}, {c_str(d)}{rng} }},")
    out.append('    { nullptr, 0, nullptr }')
    out.append('};')
    out += ['', '} } // namespace wsp::gen', '']
    return '\n'.join(out)


def render_ini(ident, keys):
    lines = [f"; {ident['config_file']} - {ident['game']} Remastered proxy settings. GENERATED from registries/config_keys.jsonl",
             '; (proxy/tools/gen_tables.py): every key the proxy reads, at its release value. Unknown keys are logged and ignored.']
    sections = {}
    for k in keys:
        sec, name = k['id'].split('.', 1)
        sections.setdefault(sec, []).append((name, k))
    for sec, items in sections.items():
        lines += ['', f'[{sec}]']
        for name, k in items:
            kind = key_kind(k)
            txt = value_text(kind, k.get('release_value', k['default']))
            lines.append(f"; {k['description']} (default {value_text(kind, k['default'])})")
            lines.append(f'{name}={txt}')
    return '\r\n'.join(lines) + '\r\n'


def render_console(adapter_rel, src):
    """console_table.h from the command TSVs named in <adapter>/console_sources.json (discovery/core/console_cmds.py output):
    the campaign commands that are no-ops in retail (refused by the console verb) and the system dictionary's names (path label)"""
    def rows(rel):
        lines = (ROOT / rel).read_text(encoding='utf-8').splitlines()
        head = lines[0].split('\t')
        return [dict(zip(head, ln.split('\t'))) for ln in lines[1:] if ln.strip()]
    camp, syst = rows(src['campaign']), rows(src['system'])
    noop = sorted(r['name'] for r in camp if r['status'] in ('no_op', 'parse_only', 'prints_only'))
    out = [f"// GENERATED by proxy/tools/gen_tables.py from {src['campaign']} and {src['system']}",
           '// (discovery/core/console_cmds.py). Do not edit: re-run the extractor, then the generator.', '#pragma once', '',
           'namespace wsp { namespace gen {', '',
           f'// {len(noop)} of {len(camp)} campaign commands do nothing in retail (no_op / parse_only / prints_only): the console verb refuses them',
           'static const char* const kConsoleNoOps[] = {']
    out += [f'    {c_str(n)},' for n in noop] + ['    nullptr', '};', '',
            f'// the system dictionary ({len(syst)} names): a line whose first word is one of these never reaches the campaign forwarder',
            'static const char* const kConsoleSystem[] = {']
    out += [f"    {c_str(r['name'])}," for r in sorted(syst, key=lambda r: r['name'])] + ['    nullptr', '};', '', '} } // namespace wsp::gen', '']
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description='generate the proxy tables from the registries')
    ap.add_argument('--adapter', help='the adapter folder, relative to the game repo (default: proxy/tools/layout.py proxy-adapter)')
    ap.add_argument('--check', action='store_true', help='fail when a generated file is stale or a row is invalid; write nothing')
    a = ap.parse_args()
    if not a.adapter:
        try:
            a.adapter = layout.proxy_adapter(ROOT).relative_to(ROOT).as_posix()
        except layout.LayoutError as e:
            print(f'gen_tables: {e}')
            return 2
    adapter = ROOT / a.adapter
    ident = json.loads((adapter / 'identity.json').read_text(encoding='utf-8'))
    sites = sorted(jsonl('registries/engine_sites.jsonl'), key=lambda s: int(s['rva'], 16))
    keys = sorted(jsonl('registries/config_keys.jsonl'), key=lambda k: k['id'])
    errs = validate_sites(sites, keys, ident)
    for k in keys:
        errs += validate_key(k)
    if errs:
        print('gen_tables: INVALID\n  ' + '\n  '.join(errs))
        return 1
    want = {adapter / 'generated' / 'tables.h': render_header(ident, sites, keys, a.adapter),
            adapter / ident['config_file']: render_ini(ident, keys)}
    if (adapter / 'console_sources.json').exists():
        src = json.loads((adapter / 'console_sources.json').read_text(encoding='utf-8'))
        want[adapter / 'generated' / 'console_table.h'] = render_console(a.adapter, src)
    stale = []
    for p, text in want.items():
        cur = p.read_bytes().decode('utf-8') if p.exists() else None
        if cur != text:
            stale.append(str(p.relative_to(ROOT)))
            if not a.check:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(text.encode('utf-8'))
    if a.check:
        if stale:
            print('gen_tables: STALE (run python3 proxy/tools/gen_tables.py): ' + ', '.join(stale))
            return 1
        print(f'gen_tables: ok - {len(sites)} engine sites, {len(keys)} config keys, generated files current')
        return 0
    print(f"gen_tables: {len(sites)} engine sites, {len(keys)} config keys; {'wrote ' + ', '.join(stale) if stale else 'nothing changed'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
