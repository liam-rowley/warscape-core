"""CI helpers as a verb: which slow checks a diff needs, the failure comment on a pull request, the generated workflows, the settings check.

purpose: `inputs` prints which slow CI jobs a diff needs and each input set's tree hash (the CI pass-marker key); `check-settings` reads (never changes) the repository settings the pipeline needs (required checks, auto-merge, review rules) and says what is missing; `notify` posts one comment on the open pull request of a branch whose CI run failed, naming each failed job and step with the configured hint; `render` writes the repo's workflows from their templates (`--check`: fail when a committed workflow differs)
usage: wsc ci inputs (--base <sha or ''> | --local) [--head REF] | wsc ci check-settings [--repo owner/name] [--branch main] | wsc ci notify --run-id <id> --attempt <n> --branch <head branch> [--repo owner/name] [--dry-run] | wsc ci render [--check]
when: automatic in CI (the `changes` and `notify` jobs, and the `ci_render` gate); by hand: `inputs` to see whether a branch will run a slow job, `notify --dry-run` to see the comment a run would get, `render` after a change to wsc.toml [ci] or a workflow template; `check-settings` at start-up or after a change to the workflows or the repository settings
verb: ci
"""
import sys

from .. import ci as C
from .. import ci_render as R
from .. import ci_settings as S

NAME = 'ci'
HELP = 'CI helpers: input sets and tree hashes, the failure comment, the rendered workflows, the repository settings check'


def add_arguments(p):
    p.add_argument('action', choices=['inputs', 'notify', 'render', 'check-settings'])
    p.add_argument('--base', help="inputs: the commit to diff HEAD against; '' or an unknown commit means everything changed")
    p.add_argument('--local', action='store_true', help='inputs: merge base with origin/main plus uncommitted and untracked files')
    p.add_argument('--head', default='HEAD', help='inputs: diff and hash this ref instead of HEAD (default %(default)s)')
    p.add_argument('--run-id', type=int, help='notify: the workflow run id')
    p.add_argument('--attempt', type=int, default=1, help='notify: the run attempt')
    p.add_argument('--branch', help='notify: the pull request head branch; check-settings: the protected branch (default main)')
    p.add_argument('--repo', default='', help='notify, check-settings: owner/name (check-settings default: gh repo view)')
    p.add_argument('--dry-run', action='store_true', help='notify: print the comment instead of posting it')
    p.add_argument('--check', action='store_true', help='render: write nothing; exit 1 when a committed workflow differs from its render')


def run(args, ctx):
    cfg = ctx.config['ci']
    if args.action == 'inputs':
        if args.local == (args.base is not None):
            print('ci inputs: pass exactly one of --base and --local', file=sys.stderr)
            return 2
        sets = C.input_sets(cfg)
        if args.local:
            base, files = C.local_changes(ctx.root)
        else:
            base, files = args.base, C.changed_files(ctx.root, args.base, args.head)
        if files is None:
            print(f"base unknown ('{base or ''}'): running everything", file=sys.stderr)
        else:
            print('\n'.join(files), file=sys.stderr)
        for k, v in C.classify(files, sets).items():
            print(f'{k}={str(v).lower()}')
        for k, v in C.tree_hashes(C.tree_entries(ctx.root, args.head), sets, cfg['salt']).items():
            print(f'{k}_tree={v}')
        print(f'tree_salt={cfg["salt"]}')
        return 0
    if args.action == 'notify':
        if not args.run_id or not args.branch:
            print('ci notify: --run-id and --branch are required', file=sys.stderr)
            return 2
        return C.notify(cfg, args.run_id, args.attempt, args.branch, args.repo, args.dry_run)
    if args.action == 'check-settings':
        return S.check(cfg, ctx.root, args.repo, args.branch or 'main')
    return R.run(ctx, args.check)
