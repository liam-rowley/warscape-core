"""
Purpose: One search across every registry (tools, scenarios, assets, UI elements, engine sites, config keys, hotkeys, engine facts; plus the core's tools from a game repo), and the game's exe string index for exe-shaped words.
Usage: wsc find <words> [--in tools,scenarios,exe_strings] [--all] [--exe] [-n 20] [--json]
When: before writing a tool, probing the game or searching the repo: look it up first (reuse before you write); an exe-shaped word (gfx_hardware_shadows, CampaignUI) also searches the exe's strings.
Verb: find
"""
import json
import os
import re

from ..registry import core_tools, load_all
from ..search import format_hit, search

NAME = 'find'
HELP = 'search every registry (and the exe string index for exe-shaped words)'

EXE = 'exe_strings'
TABLE = 'exe_strings.tsv.gz'
_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_SHAPE = re.compile(r'[A-Za-z0-9]_[A-Za-z0-9]|[a-z][A-Z]')
NO_TABLE = ('exe strings: no index ({where}): build it on the PC with the RE venv (discovery/re_env.py): '
            '<re venv python> -I core/discovery/exe_strings.py build <exe> --out <adapter>/exe_strings.tsv.gz')


def exe_shaped(word):
    """An identifier of 4+ characters with an `_` between two letters or digits, or a lower-case letter then an upper-case one."""
    return len(word) >= 4 and bool(_IDENT.fullmatch(word)) and bool(_SHAPE.search(word))


def add_arguments(p):
    p.add_argument('words', nargs='+')
    p.add_argument('--in', dest='only', help=f'comma-separated registry names to search, {EXE} for the exe string index (default: all)')
    p.add_argument('--all', action='store_true', help='include superseded tools')
    p.add_argument('--exe', action='store_true', help='search the exe string index for every word, whatever its shape')
    p.add_argument('-n', type=int, default=20, help='maximum results (default 20)')
    p.add_argument('--json', action='store_true', help='print hits as JSON lines')


def exe_table(root):
    """(discovery exe_strings module, table path, repo-relative label) of the game's index, or (None, None, why) without one."""
    try:
        from .discovery import _core, _mod
        paths = _core(root)
        table = paths.adapter_file(TABLE)
        rel = os.path.relpath(table, root).replace(os.sep, '/')
        if not os.path.isfile(table):
            return None, None, f'no {rel}' if paths.NO_ADAPTER not in table else 'no [discovery] adapter in wsc.toml'
        return _mod('exe_strings'), table, rel
    except Exception as e:   # a broken adapter must not break the registry search
        return None, None, f'{type(e).__name__}: {e}'


def exe_search(args, root, words, forced):
    """Lines to print and the hit count (None: the table was not searched)."""
    mod, table, rel = exe_table(root)
    if mod is None:
        return ([NO_TABLE.format(where=rel)] if forced else []), None
    rx = re.compile('^' + ''.join(f'(?=.*{re.escape(w)})' for w in words), re.I | re.S)
    hits = mod.search(table, rx)
    if args.json:
        return [json.dumps({'registry': EXE, 'row': dict(zip(mod.HEADER, r))}, ensure_ascii=False) for r in hits[:args.n]], len(hits)
    out = [f'{EXE.replace("_", " ")} ({rel}): {len(hits)} hits'] + [mod.line(r) for r in hits[:args.n]]
    if len(hits) > args.n:
        out.append(f'... {len(hits) - args.n} more (wsc find --exe {" ".join(words)} -n {len(hits)})')
    return out, len(hits)


def run(args, ctx):
    only = [x.strip() for x in args.only.split(',')] if args.only else None
    want_regs = only is None or any(x != EXE for x in only)
    forced = args.exe or bool(only and EXE in only)
    typed = [w for a in args.words for w in a.split()]
    exe_words = typed if forced else [w for w in typed if exe_shaped(w)]
    exe_lines, exe_hits = exe_search(args, ctx.root, exe_words, forced) if exe_words and (only is None or EXE in only) else ([], None)
    hits, regs = [], []
    if want_regs:
        regs = list(load_all(ctx).values())
        ct = core_tools(ctx)
        if ct:
            regs.append(ct)
        hits, note = search(regs, ' '.join(args.words), only, args.all, args.n)
        for sc, label, row in hits:
            print(json.dumps({'registry': label, 'score': sc, 'row': row}, ensure_ascii=False) if args.json else format_hit(label, row))
        if note:
            print(f'({note})')
        if not hits and not exe_hits:
            print('no matches: try fewer or other words, --all, or --in <registry>; registries: ' + ', '.join(sorted({r.label for r in regs})))
    for x in exe_lines:
        print(x)
    return 0 if hits or exe_hits else 1
