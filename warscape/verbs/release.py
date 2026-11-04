"""Release tags by workflow (W29, C27): plan the next version from the done rows, check main is green, check the consumers' adapters, open the
release pull request, put the annotated tag on its merge commit.

purpose: `plan` prints what a release run would do at a commit (none, release, tag or error: the version, the level, the rows and why); `check-token` fails unless RELEASE_TOKEN is set; `check-green` passes only when every required check of a commit on main's tip concluded success or skipped; `check-consumers` compiles each `[release] consumers` adapter against this core with -fsyntax-only (one line each: ok, fails, skipped); `open` makes the release/vX.Y.Z branch (VERSION only), its pull request and auto-merge; `tag` puts the annotated tag vX.Y.Z on the commit and pushes it, never moving a tag
usage: wsc release plan [--json] [--ref REV] [--version X.Y.Z] | wsc release check-token | wsc release check-green --sha SHA [--repo owner/name] | wsc release check-consumers --candidate SHA [--json OUT] [--tag vX.Y.Z --repo owner/name] | wsc release open --sha SHA [--version X.Y.Z] | wsc release tag --sha SHA [--version X.Y.Z] [--consumers FILE]
when: automatic in the `release` workflow after `gates` passes on main (ci/release.yml.in); by hand `plan` (read-only) to see what the next run would do, and `check-green --sha` to see whether a commit counts as green; `--version` is the owner's manual dispatch only (docs/CONSUMING.md, Releases)
verb: release
"""
import json
import os
import sys
from pathlib import Path

from .. import release as R

NAME = 'release'
HELP = 'release tags by workflow (C27): plan, check-token, check-green, check-consumers, open, tag'


def add_arguments(p):
    p.add_argument('action', choices=['plan', 'check-token', 'check-green', 'check-consumers', 'open', 'tag'])
    p.add_argument('--json', nargs='?', const='-', help='plan: print the plan as JSON; check-consumers: also write the results to this file')
    p.add_argument('--ref', default='HEAD', help='plan: the commit to plan at (default %(default)s)')
    p.add_argument('--sha', help='check-green, open, tag: the commit on main')
    p.add_argument('--candidate', help='check-consumers: the core commit checked out here')
    p.add_argument('--version', default='', help="the owner's manual dispatch version X.Y.Z (decision 5); empty = computed from the rows")
    p.add_argument('--repo', default='', help='check-green, check-consumers: owner/name (default: $GITHUB_REPOSITORY)')
    p.add_argument('--tag', default='', help='check-consumers: open one issue per failing consumer for this tag')
    p.add_argument('--consumers', help='tag: the JSON file check-consumers wrote (its lines go in the tag message)')


def _out(**kv):
    """Step outputs for the workflow ($GITHUB_OUTPUT), when it is set."""
    f = os.environ.get('GITHUB_OUTPUT')
    if f:
        with open(f, 'a', encoding='utf-8') as h:
            h.writelines(f'{k}={v}\n' for k, v in kv.items())


def _summary(lines):
    f = os.environ.get('GITHUB_STEP_SUMMARY')
    if f:
        with open(f, 'a', encoding='utf-8') as h:
            h.write('\n'.join(lines) + '\n')


def _say(s, err=False):
    print(f'release: {s}', file=sys.stderr if err else sys.stdout)


def _plan_lines(p):
    yield f"action {p['action']}, version {p['version']}, level {p['level']}, last tag {p['last_tag'] or 'none'}" + (f" ({p['note']})" if p['note'] else '')
    for r in p['reasons']:
        yield f'  {r}'


def run(args, ctx):
    rel = ctx.config['release']
    repo = args.repo or os.environ.get('GITHUB_REPOSITORY', '')
    try:
        if args.action == 'plan':
            p = R.gather(ctx.root, ctx.config, args.ref, args.version or None)
            if args.json:
                print(json.dumps(p, indent=2))
            else:
                for line in _plan_lines(p):
                    _say(line)
            _out(action=p['action'], version=p['version'])
            return 1 if p['action'] == 'error' else 0
        if args.action == 'check-token':
            R.need_token()
            _say('RELEASE_TOKEN is set')
            return 0
        if args.action == 'check-green':
            if not args.sha or not repo:
                _say('check-green needs --sha and --repo (or $GITHUB_REPOSITORY)', True)
                return 2
            state, lines = R.check_green(ctx.config['ci']['required_checks'], args.sha, repo)
            for line in lines:
                _say(line)
            _out(go='true' if state == 'green' else 'false')
            _say(f"{args.sha[:12]}: {'green' if state == 'green' else 'stale: nothing to do' if state == 'stale' else 'not green: no release'}")
            return 1 if state == 'red' else 0
        if args.action == 'check-consumers':
            head = R.git(['rev-parse', 'HEAD'], ctx.root).strip()
            if args.candidate and not head.startswith(args.candidate):
                _say(f'this checkout is {head[:12]}, not the candidate {args.candidate}', True)
                return 2
            res = R.check_consumers(rel['consumers'], ctx.core_root)
            for c in res:
                _say(f"consumer {c['name']}: {c['state']}" + (f": {c['detail']}" if c['detail'] else ''))
            _summary(['### consumers', ''] + [f"- {c['name']}: {c['state']}" + (f": `{c['detail']}`" if c['detail'] else '') for c in res])
            if args.json and args.json != '-':
                Path(args.json).write_text(json.dumps(res, indent=2), encoding='utf-8')
            if args.tag and repo:
                for c in res:
                    if c['state'] == 'fails':
                        _say(f"consumer {c['name']}: {R.consumer_issue(c, args.tag, repo)}")
            fails = [c for c in res if c['state'] == 'fails']
            if fails and rel['consumer_check'] == 'block':
                _say('[release] consumer_check = "block": no tag while a consumer fails', True)
                return 1
            return 0
        if args.action in ('open', 'tag'):
            if not args.sha:
                _say(f'{args.action} needs --sha', True)
                return 2
            os.environ['GH_TOKEN'] = R.need_token()   # gh and the pushes use the release token, never GITHUB_TOKEN
            p = R.gather(ctx.root, ctx.config, args.sha, args.version or None)
            for line in _plan_lines(p):
                _say(line)
            want = 'release' if args.action == 'open' else 'tag'
            if p['action'] != want:
                _say(f"the plan at {args.sha[:12]} is `{p['action']}`, not `{want}`: refused (the version is re-derived, never taken from a branch)", True)
                return 1
            if args.action == 'open':
                if R.git(['rev-parse', 'HEAD'], ctx.root).strip() != R.git(['rev-parse', args.sha], ctx.root).strip():
                    _say(f'open: check out {args.sha[:12]} first (the release branch is cut from it)', True)
                    return 2
                _say(f'opened {R.open_release(ctx.root, p)} with auto-merge')
                _summary([f"### release v{p['version']}", '', f"- release pull request opened ({p['level']})"])
                return 0
            cons = json.loads(Path(args.consumers).read_text(encoding='utf-8')) if args.consumers and Path(args.consumers).is_file() else []
            msg = R.push_tag(ctx.root, p, args.sha, cons)
            _say(msg)
            _summary([f"### release v{p['version']}", '', f'- {msg}'])
            return 0
    except R.ReleaseError as e:
        _say(str(e), True)
        return 1
    return 2
