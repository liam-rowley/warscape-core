"""Measure the pipeline: metrics from git, the jobs registry and, online, `gh`, compared with `[audit]` thresholds, written as findings with stable ids.

purpose: Compute the pipeline's metrics at origin/main, compare them with the `[audit]` thresholds and write a record of findings with stable ids (W44, C41); no model computes a number; the rules are in docs/AUDIT_METRICS.md
usage: wsc audit [--since <YYYY-MM-DD|sha>] [--record] [--json PATH] [--offline] [--only <metric>,...]   (exit 0 measured, findings or not; 1 a metric could not be computed; 2 the repo cannot be read)
when: by the audit session on its cadence (W47) with --record; by hand to see where the pipeline stands; `wsc --root <clone> audit --offline --json <path outside it>` reads another repo and writes nothing there
verb: audit

Output: `_scratch/audits/AUDIT_<date>.json` and `.md`. `--record` writes `<[audit] dir>/AUDIT_<date>.json` and `.md` instead (a second record on one day
gets `_2`), to commit. `--json PATH` writes the JSON there and the Markdown beside it, and replaces the `_scratch` output, so the repo stays untouched.
Online it fetches main and the job/ and brief/ branches; `--offline` reads the local remote-tracking refs and leaves `ci_durations` out. Findings are
not failures. Metrics left out on purpose are in the record's `skipped`; ones that broke are in `failed`.
"""
from .. import audit as A

NAME = 'audit'
HELP = 'measure the pipeline against the [audit] thresholds and write findings with stable ids'


def add_arguments(p):
    p.add_argument('--since', metavar='DATE|SHA', help='start of the window: YYYY-MM-DD (UTC) or a commit (default: the last [audit] window_days days)')
    p.add_argument('--record', action='store_true', help='write the dated record to [audit] dir, to commit')
    p.add_argument('--json', metavar='PATH', help='write the JSON here and the Markdown beside it, instead of _scratch/audits/')
    p.add_argument('--offline', action='store_true', help='fetch nothing and skip ci_durations: local remote-tracking refs only')
    p.add_argument('--only', metavar='METRIC,...', help=f'just these metrics (the rest are named in skipped): {", ".join(A.METRICS)}')


def run(args, ctx):
    from pathlib import Path
    only = [m.strip() for m in args.only.split(',') if m.strip()] if args.only else None
    rec = A.record(ctx, since=args.since, only=only, offline=args.offline)
    written = []
    if args.json:
        written.append(A.write_pair(rec, Path(args.json)))
    if args.record:
        written.append(A.write_pair(rec, A.record_path(ctx.root / ctx.config['audit']['dir'], rec['date'])))
    if not written:
        written.append(A.write_pair(rec, ctx.root / '_scratch' / 'audits' / f'AUDIT_{rec["date"]}.json'))
    for f in rec['findings']:
        print(A.finding_line(f))
    for s in rec['failed']:
        print(f'failed {s["metric"]}: {s["reason"]}')
    w = rec['window']
    print(f'audit: {len(rec["findings"])} findings, {len(rec["metrics"])} metrics, {len(rec["skipped"])} skipped, {len(rec["failed"])} failed; '
          f'{w["job_merges"]} job merges {w["since"]} to {w["until"]}, main {rec["main"][:7]}; {", ".join(str(p) for p in written)}')
    return 1 if rec['failed'] else 0
