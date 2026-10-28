"""
Purpose: One search across every registry (tools, scenarios, assets, UI elements, engine sites, config keys, hotkeys, engine facts; plus the core's tools from a game repo).
Usage: wsc find <words> [--in tools,scenarios] [--all] [-n 20] [--json]
When: before writing a tool, probing the game or searching the repo: look it up first (reuse before you write).
Verb: find
"""
import json

from ..registry import core_tools, load_all
from ..search import format_hit, search

NAME = 'find'
HELP = 'search every registry'


def add_arguments(p):
    p.add_argument('words', nargs='+')
    p.add_argument('--in', dest='only', help='comma-separated registry names to search (default: all)')
    p.add_argument('--all', action='store_true', help='include superseded tools')
    p.add_argument('-n', type=int, default=20, help='maximum results (default 20)')
    p.add_argument('--json', action='store_true', help='print hits as JSON lines')


def run(args, ctx):
    regs = list(load_all(ctx).values())
    ct = core_tools(ctx)
    if ct:
        regs.append(ct)
    only = [x.strip() for x in args.only.split(',')] if args.only else None
    hits, note = search(regs, ' '.join(args.words), only, args.all, args.n)
    for sc, label, row in hits:
        print(json.dumps({'registry': label, 'score': sc, 'row': row}, ensure_ascii=False) if args.json else format_hit(label, row))
    if note:
        print(f'({note})')
    if not hits:
        print('no matches: try fewer or other words, --all, or --in <registry>; registries: ' + ', '.join(sorted({r.label for r in regs})))
        return 1
    return 0
