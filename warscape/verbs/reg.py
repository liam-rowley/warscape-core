"""
Purpose: Change, check and render registries (JSONL + JSON Schema + generated Markdown view): add a row, set fields, check everything, re-render views.
Usage: wsc reg add <reg> key=value key:=<json> ... | wsc reg add tools <path>... [--id ID] [--status S] [--missing] | wsc reg set <reg> <id> key=value key:=null ... | wsc reg check [<reg>...] | wsc reg render [<reg>...]
When: whenever a registry fact changes (a new tool, scenario, asset, engine site, fact ...); `check` runs in the gates; `render` after a hand edit of a JSONL or a merge.
Verb: reg
"""
import json

from .. import tools
from ..registry import RegistryError, load_all

NAME = 'reg'
HELP = 'add, set, check or render registry rows'


def add_arguments(p):
    sub = p.add_subparsers(dest='action', required=True, metavar='{add,set,check,render}')
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
    r = sub.add_parser('render', help='rewrite JSONL in canonical form and regenerate the Markdown views (default: all)')
    r.add_argument('registries', nargs='*')


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


def run(args, ctx):
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
            r.write_view()
            print(f'rendered {r.rel_view} ({len(r.rows)} rows)')
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
