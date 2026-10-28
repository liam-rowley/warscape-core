"""
Purpose: Run the repo gates: schemas, registries, tool headers and rows, strict JSON, Windows-safe paths, doc size cap, undated "verified", conflict markers, line endings, core pin, host tests.
Usage: wsc gates [--fast] [--only name,name] [--json OUT] [-q]   (exit 1 when any gate fails; warnings never fail)
When: before every push (the pre-push hook runs --fast), in CI on every push and PR (full set), and after any change to a registry, tool or doc.
Verb: gates
"""
import json
import time

from .. import gates as G

NAME = 'gates'
HELP = 'run the gates (CI runs the full set, pre-push runs --fast)'


def add_arguments(p):
    p.add_argument('--fast', action='store_true', help='the fast set: everything except host tests (or [gates] fast in wsc.toml)')
    p.add_argument('--only', help='comma-separated gate names: ' + ', '.join(G.NAMES))
    p.add_argument('--json', help='also write the results to this file')
    p.add_argument('-q', action='store_true', help='print failures and warnings only')


def run(args, ctx):
    t0 = time.time()
    only = [x.strip() for x in args.only.split(',')] if args.only else None
    res = G.run(ctx, args.fast, only)
    tag = {'ok': 'ok  ', 'warn': 'WARN', 'error': 'FAIL'}
    for r in res:
        if args.q and r.level == 'ok':
            continue
        print(f'{tag[r.level]} {r.name:<17} {r.summary}  ({r.seconds:.1f} s)')
        for d in r.details[:60]:
            print(f'        {d}')
        if len(r.details) > 60:
            print(f'        ... {len(r.details) - 60} more')
    c = {k: sum(r.level == k for r in res) for k in ('ok', 'warn', 'error')}
    print(f'gates{" --fast" if args.fast else ""}: {c["ok"]} ok, {c["warn"]} warn, {c["error"]} failed in {time.time() - t0:.1f} s ({ctx.root.name})')
    if args.json:
        with open(args.json, 'w', encoding='utf-8', newline='\n') as f:
            json.dump([r.__dict__ for r in res], f, indent=1)
    return 1 if c['error'] else 0
