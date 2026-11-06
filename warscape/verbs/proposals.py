"""Turn audit findings into questions, and the owner's one message into rows (W45, C41; docs/PROPOSALS.md).

purpose: Draft a proposal per new finding, check the rows, print the question table, write the owner's answers on a decide/ branch and close what a record re-measured (W45, C41).
usage: wsc proposals draft [--record PATH] | check | ask [--max N] | answer --answers FILE --quote FILE [--date D] | answer --auto [--date D] | close [--record PATH]
when: by the audit session after `wsc audit --record` (close, draft, fill, answer --auto); `ask` when the owner sits down to answer; `answer` on decide/<date> with the owner's message.
verb: proposals

`answer` commits nothing, and prints the push and the pull request without auto-merge: only the owner merges a decide/ branch (C41). `--answers` is JSON, {"<id>": "<option key>"} with
"recommended" as a value; rows not named stay open. `--quote` is the owner's message, verbatim. Exit 0, 1 on a refusal or a problem found by `check`.
"""
import json
import subprocess
from pathlib import Path

from .. import proposals as P
from ..repo import git_env

NAME = 'proposals'
HELP = 'draft proposals from audit findings, ask the owner, and apply the answers on a decide/ branch'


def add_arguments(p):
    s = p.add_subparsers(dest='action', required=True)
    d = s.add_parser('draft', help='a skeleton per finding of the newest record that has no live row')
    d.add_argument('--record', metavar='PATH', help='this record, not the newest in [audit] dir')
    s.add_parser('check', help='what the jobs gate runs: an open row has options and a recommendation, an answer names what exists')
    a = s.add_parser('ask', help='the question table, highest severity first')
    a.add_argument('--max', type=int, metavar='N', help='at most this many rows (default: [audit] max_questions)')
    w = s.add_parser('answer', help='write the answers on a decide/ branch, or with --auto the auto_apply classes on a plan/ branch')
    w.add_argument('--answers', metavar='FILE', help='JSON: {"<id>": "<option key>"}, "recommended" allowed')
    w.add_argument('--quote', metavar='FILE', help="the owner's message, verbatim")
    w.add_argument('--auto', action='store_true', help='accept the open untagged rows of [audit] auto_apply at their recommendation')
    w.add_argument('--date', metavar='YYYY-MM-DD', help='the date of the answers (default: today, UTC)')
    c = s.add_parser('close', help="apply a record's re-measuring: close moved and gone rows, re-raise not_moved ones")
    c.add_argument('--record', metavar='PATH', help='this record, not the newest in [audit] dir')


def branch_of(ctx):
    return subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True, check=True, cwd=ctx.root, env=git_env()).stdout.strip()


def taken_jobs(ctx):
    """Job ids on every remote plan/, brief/ and decide/ branch this clone has: a row on none of them yet would otherwise be drawn twice."""
    run = lambda *a: subprocess.run(['git', *a], capture_output=True, text=True, check=True, cwd=ctx.root, env=git_env()).stdout
    refs = run('for-each-ref', '--format=%(refname)', 'refs/remotes/origin/plan', 'refs/remotes/origin/brief', 'refs/remotes/origin/decide').split()
    folder, out = f'{ctx.config["registries_dir"]}/jobs', set()
    for ref in refs:
        try:
            out |= {Path(n).stem for n in run('ls-tree', '--name-only', f'{ref}:{folder}').split()}
        except subprocess.CalledProcessError:   # an old branch from before per-row storage: its ids are behind main's
            continue
    return out


def run(args, ctx):
    try:
        return act(args, ctx)
    except (ValueError, OSError) as e:
        print(f'proposals: {e}')
        return 1


def act(args, ctx):
    if args.action != 'check' and not P.declared(ctx):
        raise ValueError(f'no proposals registry: declare it (`[registries] proposals = "core:proposals"`, and in `[storage] dir`)')
    if args.action == 'check':
        errs = P.check(ctx)
        print('\n'.join(errs) if errs else 'proposals check: ok')
        return 1 if errs else 0
    if args.action == 'draft':
        made = P.draft(ctx, args.record)
        print('\n'.join(made + [f'proposals: {len(made)} drafted; fill each, then `wsc proposals check`']))
    elif args.action == 'ask':
        print(P.ask(ctx, args.max if args.max is not None else ctx.config['audit']['max_questions']))
    elif args.action == 'close':
        rec, rel = P.read_record(ctx, args.record)
        out = P.close(ctx, rec, rel)
        print(f'proposals: {len(out["closed"])} closed, {len(out["drafted"])} re-raised' + ''.join(f'\n  {i}: fill it' for i in out['drafted']))
    elif args.auto:
        got = P.answer_auto(ctx, branch_of(ctx), today=args.date, taken=taken_jobs(ctx))
        print(f'proposals: {len(got)} accepted by auto_apply' + ''.join(f'\n  {i}' for i in got))
    else:
        if not args.answers or not args.quote:
            raise ValueError('answer needs --answers and --quote, or --auto')
        answers = json.loads(Path(args.answers).read_text(encoding='utf-8'))
        branch = branch_of(ctx)
        record = P.answer(ctx, answers, Path(args.quote).read_text(encoding='utf-8'), branch, today=args.date, taken=taken_jobs(ctx))
        print(f'proposals: {len(answers)} answered, {record}\nCommit, then: git push -u origin {branch}\n'
              f'gh pr create --base main --head {branch} --title "decide: answers of {branch.split("/", 1)[1]}"\n'
              f'Only {ctx.config["jobs"]["text"].get("owner") or "the owner"} merges it (C41): no auto-merge.')
    return 0
