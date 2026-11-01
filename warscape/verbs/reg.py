"""
Purpose: Change, check and render registries (rows + JSON Schema + generated Markdown view): add a row, set fields, check everything, re-render views, move a registry between JSONL and one-file-per-row storage.
Usage: wsc reg add <reg> key=value key:=<json> ... | wsc reg add tools <path>... [--id ID] [--status S] [--missing] | wsc reg set <reg> <id> key=value key:=null ... | wsc reg check [<reg>...] | wsc reg render [<reg>...] [--out DIR] | wsc reg migrate <reg> --to dir|jsonl
When: whenever a registry fact changes (a new tool, scenario, asset, engine site, fact ...); `check` runs in the gates; `render` after a hand edit of a row file or a merge; `migrate` once, to switch a registry's storage.
Verb: reg
"""
import json
import re

from .. import tools
from ..registry import RegistryError, load_all, load_from_config
from ..repo import CONFIG_NAME

NAME = 'reg'
HELP = 'add, set, check or render registry rows'


def add_arguments(p):
    sub = p.add_subparsers(dest='action', required=True, metavar='{add,set,check,render,migrate}')
    a = sub.add_parser('add', help='add a row (key=value for strings, key:=<json> for anything else); for tools, give file paths')
    a.add_argument('registry')
    a.add_argument('items', nargs='*', help='key=value / key:=json pairs, or (tools) file paths')
    a.add_argument('--json', help='the whole row as one JSON object')
    a.add_argument('--id', help='tools: row id (default: wsc.<verb> or the path slug)')
    a.add_argument('--status', help='tools: status (live, or superseded:<id>)')
    a.add_argument('--missing', action='store_true', help='tools: add a row for every tool file without one')
    s = sub.add_parser('set', help='change fields of one row (key:=null removes a field)')
    s.add_argument('registry')
    s.add_argument('id')
    s.add_argument('items', nargs='+')
    c = sub.add_parser('check', help='check registries (default: all)')
    c.add_argument('registries', nargs='*')
    r = sub.add_parser('render', help='rewrite the rows in canonical form and regenerate the Markdown views (default: all)')
    r.add_argument('registries', nargs='*')
    r.add_argument('--out', metavar='DIR', help='write the views to DIR instead of their configured place (wsc.toml [views])')
    m = sub.add_parser('migrate', help='move a registry to the other storage (one JSONL, or one file per row) and update wsc.toml [storage] dir')
    m.add_argument('registry')
    m.add_argument('--to', required=True, choices=('dir', 'jsonl'))


def parse_items(items):
    out = {}
    for it in items:
        if ':=' in it and ('=' not in it or it.index(':=') < it.index('=')):
            k, v = it.split(':=', 1)
            try:
                out[k] = json.loads(v)
            except ValueError as e:
                raise RegistryError(f'{k}:= needs JSON ({e}); use {k}=<text> for a string') from None
        elif '=' in it:
            k, v = it.split('=', 1)
            out[k] = v
        else:
            raise RegistryError(f'{it!r} is not key=value or key:=json')
        if not k:
            raise RegistryError(f'{it!r}: empty field name')
    return out


def _pick(regs, names):
    bad = [n for n in names if n not in regs]
    if bad:
        raise RegistryError(f'unknown registry {", ".join(bad)}; this repo declares: {", ".join(regs)}')
    return [regs[n] for n in (names or regs)]


def set_storage_dir(text, names):
    """wsc.toml text with `[storage] dir = [names]` (the table or the line added when absent). A multi-line `dir` array is refused."""
    line = 'dir = [' + ', '.join(f'"{n}"' for n in names) + ']'
    m = re.search(r'(?m)^\[storage\][ \t]*(?:#.*)?$', text)
    if not m:
        return text.rstrip('\n') + f'\n\n[storage]\n{line}   # one file per row (wsc reg migrate)\n'
    nxt = re.search(r'(?m)^\[', text[m.end():])
    end = m.end() + (nxt.start() if nxt else len(text) - m.end())
    body = text[m.end():end]
    d = re.search(r'(?m)^dir[ \t]*=.*$', body)
    if d and not re.fullmatch(r'dir[ \t]*=[ \t]*\[[^\]]*\][ \t]*(#.*)?', d.group(0)):
        raise RegistryError(f'{CONFIG_NAME}: [storage] dir spans lines: set it by hand to {line}')
    if d:
        body = body[:d.start()] + line + body[d.end():]
    else:
        body = '\n' + line + body
    return text[:m.end()] + body + text[end:]


def migrate(ctx, name, to):
    cfg = ctx.config
    if name not in cfg['registries']:
        raise RegistryError(f'unknown registry {name}; this repo declares: {", ".join(cfg["registries"])}')
    frm = 'dir' if name in cfg['storage']['dir'] else 'jsonl'
    if frm == to:
        raise RegistryError(f'{name} is already stored as {to}')
    old = load_from_config(cfg, ctx.root, only=name, storage=frm)[name]
    new = load_from_config(cfg, ctx.root, only=name, storage=to)[name]
    if old.parse_errors:
        raise RegistryError('fix these first:\n' + '\n'.join(old.parse_errors))
    if new.rows or new.parse_errors:
        raise RegistryError(f'{new.rel_path} already holds rows: delete it or merge it by hand first')
    dup = sorted({str(r.get('id')) for r in old.rows if [x.get('id') for x in old.rows].count(r.get('id')) > 1})
    if dup:
        raise RegistryError(f'{name}: duplicate ids {", ".join(dup)}: keep one row each, then migrate')
    new.rows = old.rows
    if to == 'dir':
        new.canonical_files()          # raises on an id that cannot name a file
    new.save()
    old.remove_storage()
    names = [n for n in cfg['storage']['dir'] if n != name] + ([name] if to == 'dir' else [])
    p = ctx.root / CONFIG_NAME
    text = set_storage_dir(p.read_text(encoding='utf-8'), names)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    cfg['storage']['dir'] = names
    load_all(ctx)[name].write_view()
    return f'migrated {name}: {len(new.rows)} rows from {old.rel_path} to {new.rel_path}; {CONFIG_NAME} [storage] dir = {names}'


def run(args, ctx):
    if args.action == 'migrate':
        print(migrate(ctx, args.registry, args.to))
        return 0
    regs = load_all(ctx)
    if args.action in ('add', 'set'):
        reg = _pick(regs, [args.registry])[0]
        if args.action == 'add' and reg.schema.get('x-source') == 'tool-headers':
            paths = tools.missing(ctx, reg) if args.missing else args.items
            if not paths:
                print('nothing to add' if args.missing else 'give tool file paths (or --missing)')
                return 0 if args.missing else 2
            try:
                msgs = tools.add_paths(ctx, reg, paths, args.id, args.status)
            except ValueError as e:
                raise RegistryError(str(e)) from None
            print('\n'.join(msgs))
        elif args.action == 'add':
            row = json.loads(args.json) if args.json else {}
            row.update(parse_items(args.items))
            reg.add(row)
            print(f'added {reg.name}:{row["id"]}')
        else:
            ch = parse_items(args.items)
            if reg.schema.get('x-source') == 'tool-headers':
                fixed = [k for k in ch if k in tools.HEADER_FIELDS]
                if fixed:
                    raise RegistryError(f'{", ".join(fixed)} come from the file header: edit the header, then `wsc reg add tools <path>`')
            reg.set(args.id, ch)
            print(f'set {reg.name}:{args.id} ' + ', '.join(ch))
        reg.save()
        reg.write_view()
        return 0
    targets = _pick(regs, args.registries)
    if args.action == 'render':
        for r in targets:
            if r.parse_errors:
                raise RegistryError('\n'.join(r.parse_errors))
            r.save()
            p = r.write_view(args.out)
            print(f'rendered {p.relative_to(ctx.root).as_posix() if p.is_relative_to(ctx.root) else p} ({len(r.rows)} rows)')
        return 0
    bad = 0
    for r in targets:
        errs = r.check(regs)
        warns = []
        if r.schema.get('x-source') == 'tool-headers':
            e2, warns = tools.check(ctx, r)
            errs += e2
        print(f'{"FAIL" if errs else "ok  "} {r.name}: {len(r.rows)} rows' + (f', {len(errs)} problems' if errs else ''))
        for e in errs + [f'warning: {w}' for w in warns]:
            print(f'        {e}')
        bad += bool(errs)
    return 1 if bad else 0
