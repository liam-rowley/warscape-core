"""The pull-request policy as a verb: the branch name decides what a pull request may change (every change goes through the job queue).

purpose: Refuse a pull request whose branch is not a reviewed job, a brief, a planning change or an infrastructure change, and run the repo's `policy`-stage gate modules; the rules are in warscape/policy.py
usage: wsc policy --branch <head branch> [--base origin/main]   (CI runs it on every pull request); wsc policy --commit-msg <file>   (the commit-msg hook, C23)
when: automatic in CI (the `policy` job) and, with `[policy] commit_msg_hook = true`, in .githooks/commit-msg; locally before opening a pull request to see what CI will say; the job steps (`wsc jobs next|review|fix`) name it
verb: policy
"""
import sys

from .. import policy as P

NAME = 'policy'
HELP = 'the pull-request policy: what the branch kind may change, reviewed jobs only'


def add_arguments(p):
    p.add_argument('--branch', help='the pull request head branch name')
    p.add_argument('--commit-msg', metavar='FILE', help='check a commit message file for the session trailer instead (what .githooks/commit-msg runs; '
                   'passes when [policy] commit_msg_hook is off)')
    p.add_argument('--base', default='origin/main', help='base ref to compare against (default %(default)s)')


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
    errs, changed = P.run_check(ctx, args.branch, args.base)
    for e in errs:
        print(f'policy: {e}', file=sys.stderr)
    print(f'policy: {args.branch}: {"REFUSED" if errs else "ok"} ({len(changed)} files changed)')
    return 1 if errs else 0
