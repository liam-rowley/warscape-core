"""The pull-request policy as a verb: the branch name decides what a pull request may change (every change goes through the job queue).

purpose: Refuse a pull request whose branch is not a reviewed job, a brief, a planning change or an infrastructure change, and run the repo's `policy`-stage gate modules; the rules are in warscape/policy.py
usage: wsc policy --branch <head branch> [--base origin/main]   (CI runs it on every pull request)
when: automatic in CI (the `policy` job); locally before opening a pull request to see what CI will say; the job steps (`wsc jobs next|review|fix`) name it
verb: policy
"""
import sys

from .. import policy as P

NAME = 'policy'
HELP = 'the pull-request policy: what the branch kind may change, reviewed jobs only'


def add_arguments(p):
    p.add_argument('--branch', required=True, help='the pull request head branch name')
    p.add_argument('--base', default='origin/main', help='base ref to compare against (default %(default)s)')


def run(args, ctx):
    errs, changed = P.run_check(ctx, args.branch, args.base)
    for e in errs:
        print(f'policy: {e}', file=sys.stderr)
    print(f'policy: {args.branch}: {"REFUSED" if errs else "ok"} ({len(changed)} files changed)')
    return 1 if errs else 0
