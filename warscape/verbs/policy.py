"""The pull-request policy as a verb: the branch name decides what a pull request may change (every change goes through the job queue).

purpose: Refuse a pull request whose branch is not a reviewed job, a brief, a planning change or an infrastructure change, judged with the base's rules (its core, wsc.toml and `policy`-stage gate modules, in a child process); the rules are in warscape/policy.py
usage: wsc policy --branch <head branch> [--base origin/main] [--head <rev>, default HEAD]   (CI: --head <the pull request head sha>, on pull_request_target); wsc policy --commit-msg <file>   (the commit-msg hook, C23)
when: automatic in CI (the `policy` job) and, with `[policy] commit_msg_hook = true`, in .githooks/commit-msg; locally (after `git fetch`) before opening a pull request to see what CI will say; the job steps (`wsc jobs next|review|fix`) name it
verb: policy

The judge (core W23, C24): `wsc policy` writes the base's rule inputs into a temporary folder and runs the base's own `wsc policy --judge` there,
so a local run and CI print the same lines for the same two shas (CI is the authority: its parent is the base's code, a local parent is your
checkout's). Internal flags of that child, hidden from --help: `--judge` (judge in this process: `--root` is the base tree, the rules are
its config and gate modules), `--repo <clone>` (where git reads the head; shas only), `--base-ref <name>` (the base's name in messages).
Their set is versioned by `JUDGE_API` in warscape/policy.py; the parent is warscape/policy_base.py.
"""
import argparse
import sys

from .. import policy as P

NAME = 'policy'
HELP = "the pull-request policy: what the branch kind may change, reviewed jobs only, judged with the base's rules"


def add_arguments(p):
    p.add_argument('--branch', help='the pull request head branch name')
    p.add_argument('--commit-msg', metavar='FILE', help='check a commit message file for the session trailer instead (what .githooks/commit-msg runs; '
                   'passes when [policy] commit_msg_hook is off)')
    p.add_argument('--base', default='origin/main', help="the base ref whose rules judge (default %(default)s; `git fetch` first)")
    p.add_argument('--head', default='HEAD', help='the commit to judge (default %(default)s; CI passes the pull request head sha)')
    p.add_argument('--judge', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--repo', help=argparse.SUPPRESS)
    p.add_argument('--base-ref', help=argparse.SUPPRESS)


def run(args, ctx):
    if args.commit_msg:
        from .. import trailer
        pol = ctx.config['policy']
        if not pol['commit_msg_hook'] or not pol['session_trailer']:
            return 0   # not opted in (or the trailer rule is off): the hook is silent
        with open(args.commit_msg, encoding='utf-8', errors='replace') as f:
            problem = trailer.message_problem(f.read(), pol['session_trailer'])
        if problem:
            print(f'commit-msg: {problem}', file=sys.stderr)
        return 1 if problem else 0
    if not args.branch:
        print('policy: --branch (or --commit-msg FILE) is required', file=sys.stderr)
        return 2
    if not args.judge:
        from ..policy_base import judge
        return judge(ctx, args.branch, args.base, args.head)
    if not args.repo:
        print('policy: --judge needs --repo', file=sys.stderr)
        return 2
    base_ref = args.base_ref or args.base
    try:
        errs, changed = P.run_check(ctx, args.branch, args.base, args.head, args.repo, base_ref=base_ref)
    except P.Refusal as e:
        errs, changed = [str(e)], []
    note = P.rule_input_note(ctx.config, changed, base_ref)
    if note:
        print(note)
    for e in errs:
        print(f'policy: {e}', file=sys.stderr)
    print(f'policy: {args.branch}: {"REFUSED" if errs else "ok"} ({len(changed)} files changed)')
    return 1 if errs else 0
