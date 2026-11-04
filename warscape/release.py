"""Release tags by workflow (core W29, C27): the next version from the job rows done since the last tag, the release branch, the annotated tag.

The verb is warscape/verbs/release.py; the workflow is ci/release.yml.in. The pure part (`plan`, `bump`, `remote_tag_state`, ...) takes plain
inputs; the rest reads git and `gh` through an injectable `run` (subprocess.run's signature), so the host tests (tests/test_release.py) never
need a network, a token or a push.

- A row's level is its `semver` (patch|minor|major|none); a row without one counts as `patch` (the legacy rows below `[jobs] semver_from`).
  `none` releases nothing. The level of a release is the highest level of the rows that became `done` since the last tag (read with
  `git ls-tree`/`git cat-file` at the tag and at HEAD, never the working tree).
- Floor `minor`: any change under `schemas/`, a module added or removed under `warscape/verbs/`, or a `CORE_VERBS` edit between the tag and HEAD.
- While the major number is 0, `major` is applied as `minor` and the plan says so; 1.0.0 is cut only by the manual dispatch (`forced`).
- VERSION above the last tag with only legacy rows done since: that VERSION is tagged as it is (an in-flight job bumped it by hand).
  With new rows, VERSION must be what the rows and the floor give (an agent's own release/ branch cannot choose a version), or the
  plan is an error; a VERSION below it gets one more release step.
- A tag is never moved: an existing remote tag must be an annotated tag on this very commit (a no-op), anything else fails. No code here
  passes `-f` or a force option to git, and nothing here reads GITHUB_TOKEN: the token is the caller's `RELEASE_TOKEN` (docs/CONSUMING.md, Releases).
"""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from . import ci
from .repo import git_env

LEVELS = ('none', 'patch', 'minor', 'major')
SEMVER = re.compile(r'(\d+)\.(\d+)\.(\d+)')
TAG = re.compile(r'v(\d+)\.(\d+)\.(\d+)')
TOKEN_MISSING = 'RELEASE_TOKEN is not set: see docs/CONSUMING.md, Releases'
CORE_VERBS_RE = re.compile(r'^CORE_VERBS\s*=\s*\(([^)]*)\)', re.M)
GREEN = ('success', 'skipped')   # a skipped job counts as passed, as in branch protection


class ReleaseError(Exception):
    """A release that must not go on: the message names why (a red run, never a tag)."""


# ------------------------------------------------------------------ pure
def parse(v):
    m = SEMVER.fullmatch((v or '').strip())
    if not m:
        raise ReleaseError(f'{v!r} is not X.Y.Z')
    return tuple(int(x) for x in m.groups())


def fmt(t):
    return '.'.join(map(str, t))


def bump(t, level):
    """The version one `level` step above `t` (a tuple); `none` is `t` itself."""
    a, b, c = t
    return {'none': t, 'patch': (a, b, c + 1), 'minor': (a, b + 1, 0), 'major': (a + 1, 0, 0)}[level]


def steps(t):
    """The three versions one step above `t`."""
    return [bump(t, lv) for lv in ('patch', 'minor', 'major')]


def num(jid):
    m = re.fullmatch(r'[A-Z](\d+)', jid or '')
    return int(m.group(1)) if m else 0


def legacy(row, semver_from):
    """A row from before the semver rule: it bumped VERSION by hand. `semver_from` 0 means the rule is off (every row is legacy)."""
    return not semver_from or num(row.get('id')) < semver_from


def row_level(row):
    lv = row.get('semver') or 'patch'
    return lv if lv in LEVELS else 'patch'


def done_since(tag_rows, head_rows):
    """Rows `done` at HEAD that were not `done` at the last tag, in id order."""
    return [head_rows[k] for k in sorted(head_rows, key=lambda k: (k[:1], num(k)))
            if head_rows[k].get('status') == 'done' and (tag_rows.get(k) or {}).get('status') != 'done']


def core_verbs(cli_text):
    """The CORE_VERBS names in warscape/cli.py text (read as text, never imported), or None."""
    m = CORE_VERBS_RE.search(cli_text or '')
    return tuple(a or b for a, b in re.findall(r"'([^']+)'|\"([^\"]+)\"", m.group(1))) if m else None


def floor_reasons(changed, verbs_tag, verbs_head):
    """Why the release is at least `minor`: [(reason)] from `changed` [(status, path)] (git diff --name-status --no-renames) and the CORE_VERBS."""
    out = []
    sch = sorted(p for _, p in changed if p.startswith('schemas/'))
    if sch:
        out.append(f'schemas changed ({", ".join(sch[:5])})')
    verbs = sorted(f'{s} {p}' for s, p in changed if s in ('A', 'D') and re.fullmatch(r'warscape/verbs/[^/_][^/]*\.py', p))
    if verbs:
        out.append(f'verb modules added or removed ({", ".join(verbs[:5])})')
    if verbs_tag is not None and verbs_head is not None and tuple(verbs_tag) != tuple(verbs_head):
        out.append(f'CORE_VERBS changed ({", ".join(verbs_tag)} -> {", ".join(verbs_head)})')
    return out


def plan(last_tag, version, tag_rows, head_rows, changed=(), verbs_tag=None, verbs_head=None, semver_from=0, forced=None):
    """{action: none|release|tag|error, version, level, rows, reasons, note}. `last_tag` 'vX.Y.Z' or '' (no tag yet), `version` main's VERSION,
    `forced` the manual dispatch's version (decision 5) or None."""
    T = parse(last_tag[1:]) if last_tag else (0, 0, 0)
    V = parse(version)
    rows = done_since(tag_rows, head_rows)
    counted = [r for r in rows if row_level(r) != 'none']
    lvl = max((row_level(r) for r in counted), key=LEVELS.index, default='none')
    reasons = [f"{r['id']} {row_level(r)}" + ('' if r.get('semver') else ' (no semver: patch)') for r in rows]
    fl = floor_reasons(changed, verbs_tag, verbs_head)
    if fl and LEVELS.index(lvl) < LEVELS.index('minor'):
        lvl = 'minor'
        reasons += [f'floor minor: {f}' for f in fl]
    note = ''
    if lvl == 'major' and T[0] == 0:
        lvl, note = 'minor', 'major applied as minor while the major number is 0 (1.0.0 is cut by hand: the manual dispatch)'
    shown = [{'id': r['id'], 'title': r.get('title', ''), 'semver': r.get('semver') or ''} for r in rows]
    out = {'action': 'none', 'version': fmt(V), 'level': lvl, 'rows': shown, 'reasons': reasons, 'note': note, 'last_tag': last_tag}

    def err(msg):
        return {**out, 'action': 'error', 'reasons': reasons + [msg]}
    if forced:
        F = parse(forced)
        if F <= T:
            return err(f'the manual version {fmt(F)} is not greater than the last tag {last_tag}')
        if F == V:
            return {**out, 'action': 'tag', 'version': fmt(F), 'note': f'manual release {fmt(F)}'}
        if F not in steps(V):
            return err(f'the manual version {fmt(F)} is not one step above VERSION {fmt(V)} (the release branch changes one step only)')
        return {**out, 'action': 'release', 'version': fmt(F), 'note': f'manual release {fmt(F)}'}
    computed = bump(T, lvl)
    new = [r for r in rows if not legacy(r, semver_from)]
    old = [r for r in rows if legacy(r, semver_from)]
    if V > T:
        if not rows:   # no row explains the new VERSION: a hand-made release/ branch must not choose a version
            return err(f'VERSION {fmt(V)} on main is above {last_tag or "no tag"} but no job row became done since: nothing to release (the manual dispatch can cut a version)')
        if not new:
            return {**out, 'action': 'tag', 'reasons': reasons + [f'VERSION {fmt(V)} was bumped by hand above {last_tag or "no tag"}: tagged as it is']}
        if V == computed or (old and V > computed):
            return {**out, 'action': 'tag'}
        if V < computed:
            return {**out, 'action': 'release', 'version': fmt(computed)}
        return err(f'VERSION {fmt(V)} on main is not {fmt(computed)}, what the rows and the floor give since {last_tag or "the start"} '
                   '(a release branch cannot choose its version: the manual dispatch can)')
    if lvl == 'none':
        return {**out, 'reasons': reasons + ['nothing to release']}
    return {**out, 'action': 'release', 'version': fmt(bump(max(T, V), lvl))}


def remote_tag_state(ls_remote, tag, sha):
    """'absent' | 'same' (an annotated tag on `sha`: a no-op) | 'lightweight' | 'other' (another commit), from `git ls-remote` output."""
    refs = {}
    for line in (ls_remote or '').splitlines():
        parts = line.split()
        if len(parts) == 2:
            refs[parts[1]] = parts[0]
    ref = f'refs/tags/{tag}'
    if ref not in refs:
        return 'absent'
    peeled = refs.get(ref + '^{}')
    if peeled is None:
        return 'lightweight' if refs[ref] == sha else 'other'
    return 'same' if peeled == sha else 'other'


def tag_message(p, consumers=()):
    lines = [f"warscape-core v{p['version']}", '', f"level: {p['level']}" + (f" ({p['note']})" if p['note'] else ''), '']
    lines += ['rows:'] + ([f"- {r['id']} {r['title']} ({r['semver'] or 'patch'})" for r in p['rows']] or ['- none'])
    extra = [r for r in p['reasons'] if not re.match(r'[A-Z]\d+ ', r)]
    if extra:
        lines += ['', 'reasons:'] + [f'- {r}' for r in extra]
    lines += ['', 'consumers:'] + ([f"- {c['name']}: {c['state']}" + (f": {c['detail']}" if c.get('detail') else '') for c in consumers] or ['- none checked'])
    return '\n'.join(lines) + '\n'


def green_problems(required, check_runs):
    """[(check, why)] for every required check except `policy` that is not concluded success or skipped. `check_runs`: the API's list."""
    out = []
    for name in required:
        if name == 'policy':   # produced only by pull requests, never by a push to main
            continue
        got = [c for c in check_runs if c.get('name') == name]
        if not got:
            out.append((name, 'missing'))
            continue
        last = max(got, key=lambda c: (c.get('started_at') or '', c.get('id') or 0))
        if last.get('status') != 'completed':
            out.append((name, last.get('status') or 'in progress'))
        elif last.get('conclusion') not in GREEN:
            out.append((name, last.get('conclusion') or 'no conclusion'))
    return out


# ------------------------------------------------------------------ git and gh
def git(args, root, run=subprocess.run, check=True):
    p = run(['git', *args], cwd=str(root), capture_output=True, text=True, env=git_env())
    if check and p.returncode:
        raise ReleaseError(f"git {' '.join(args[:3])} failed: {(p.stderr or p.stdout or '').strip()}")
    return p.stdout if check else p


def last_tag(root, ref='HEAD', run=subprocess.run):
    """The greatest `vX.Y.Z` tag merged into `ref`, or ''."""
    tags = [t.strip() for t in git(['tag', '--merged', ref, '--list', 'v*'], root, run).splitlines()]
    tags = [t for t in tags if TAG.fullmatch(t)]
    return max(tags, key=lambda t: parse(t[1:])) if tags else ''


def gather(root, config, ref='HEAD', forced=None, run=subprocess.run):
    """plan() for the repository at `root` at `ref`, read from git objects only."""
    from .policy import rows_at, settings, show
    cfg = settings(config)
    tag = last_tag(root, ref, run)
    version = show(ref, 'VERSION', str(root))
    if version is None:
        raise ReleaseError(f'no VERSION at {ref}')
    head_rows = rows_at(ref, cfg, str(root))
    tag_rows = rows_at(tag, cfg, str(root)) if tag else {}
    changed = []
    if tag:
        parts = [x for x in git(['diff', '--name-status', '--no-renames', '-z', tag, ref], root, run).split('\0') if x]
        changed = list(zip(parts[0::2], parts[1::2]))
    vt = core_verbs(show(tag, 'warscape/cli.py', str(root))) if tag else None
    vh = core_verbs(show(ref, 'warscape/cli.py', str(root)))
    return plan(tag, version.strip(), tag_rows, head_rows, changed, vt, vh, config['jobs'].get('semver_from', 0), forced)


def need_token(env=None):
    """The release token from the environment; ReleaseError with the named message when it is empty. Never GITHUB_TOKEN."""
    tok = (env if env is not None else os.environ).get('RELEASE_TOKEN', '').strip()
    if not tok:
        raise ReleaseError(TOKEN_MISSING)
    return tok


def check_green(required, sha, repo, run=subprocess.run):
    """('stale'|'green'|'red', lines). Stale: `sha` is no longer main's tip (the newer run decides)."""
    api = f'repos/{repo}'
    tip = json.loads(ci.gh(['api', f'{api}/commits/main', '--jq', '{sha: .sha}'], run))['sha']
    if tip != sha:
        return 'stale', [f'main moved to {tip[:12]}; the newer run decides (nothing done for {sha[:12]})']
    runs = json.loads(ci.gh(['api', f'{api}/commits/{sha}/check-runs?per_page=100'], run)).get('check_runs', [])
    bad = green_problems(required, runs)
    if bad:
        return 'red', [f'{n}: {why}' for n, why in bad]
    return 'green', [f'{n}: green' for n in required if n != 'policy']


def check_consumers(consumers, core_root, run=subprocess.run, workdir=None):
    """[{name, state: ok|fails|skipped, detail, adapter}] for each `[release] consumers` entry: a shallow checkout (gh, the release token in
    GH_TOKEN), then proxy/tools/adapter_syntax.py on its adapter folder with this core's sources."""
    out = []
    tmp = Path(workdir or tempfile.mkdtemp(prefix='wsc-consumers-'))
    for c in consumers:
        name, repo, adapter, ref = c.get('name', '?'), c.get('repo', ''), c.get('adapter', ''), c.get('ref', 'main')
        if not repo or not adapter:
            out.append({'name': name, 'state': 'skipped', 'detail': 'no repo or adapter in [release] consumers', 'adapter': adapter})
            continue
        dest = tmp / re.sub(r'[^A-Za-z0-9_.-]', '_', name)
        p = run(['gh', 'repo', 'clone', repo, str(dest), '--', '--depth', '1', '--branch', ref], capture_output=True, text=True)
        if p.returncode:
            first = ((p.stderr or p.stdout or '').strip().splitlines() or ['no output'])[0]
            out.append({'name': name, 'state': 'skipped', 'detail': f'{repo}@{ref} unreachable: {first}', 'adapter': adapter})
            continue
        if not (dest / adapter / 'adapter.cpp').is_file():
            out.append({'name': name, 'state': 'skipped', 'detail': f'{adapter}/adapter.cpp not in {repo}@{ref}', 'adapter': adapter})
            continue
        p = run(['python3', str(Path(core_root) / 'proxy' / 'tools' / 'adapter_syntax.py'), '--adapter', str(dest / adapter)],
                capture_output=True, text=True)
        text = (p.stdout or '') + (p.stderr or '')
        if p.returncode == 0:
            out.append({'name': name, 'state': 'ok', 'detail': '', 'adapter': adapter})
        elif p.returncode == 2:
            out.append({'name': name, 'state': 'skipped', 'detail': (text.strip().splitlines() or ['no compiler'])[-1], 'adapter': adapter})
        else:
            first = next((l.strip() for l in text.splitlines() if 'error' in l), (text.strip().splitlines() or ['no output'])[0])
            out.append({'name': name, 'state': 'fails', 'detail': first, 'adapter': adapter})
    return out


CONSUMER_MARK = '<!-- release consumer {name} {tag} -->'


def consumer_issue(c, tag, repo, run=subprocess.run):
    """One open issue per failing consumer and tag (found by its hidden mark, as `ci main-health` finds its own): opened once, never duplicated."""
    mark = CONSUMER_MARK.format(name=c['name'], tag=tag)
    issues = json.loads(ci.gh(['issue', 'list', '--repo', repo, '--state', 'open', '--limit', '200', '--json', 'number,body'], run) or '[]')
    hit = [i for i in issues if (i.get('body') or '').lstrip().startswith(mark)]
    if hit:
        return f"issue #{min(i['number'] for i in hit)} already open"
    body = '\n'.join([mark, f"**{c['name']}'s adapter does not compile against warscape-core {tag}.**", '',
                      f"Adapter: `{c['adapter']}/adapter.cpp`. First error:", '', f"    {c['detail']}", '',
                      f"The consumer fixes its adapter in the commit that bumps to {tag} (`python3 core/wsc.py core bump {tag}`)."])
    ci.gh(['issue', 'create', '--repo', repo, '--title', f"{c['name']} adapter fails against {tag}", '--body', body], run)
    return 'issue opened'


def open_release(root, p, run=subprocess.run, base='main'):
    """The release branch `release/vX.Y.Z` (VERSION only, trailer Release-By: workflow), pushed, its pull request, auto-merge (squash)."""
    v = p['version']
    br = f'release/v{v}'
    ident = ['-c', 'user.name=warscape-release', '-c', 'user.email=release@users.noreply.github.com']
    remote = git(['ls-remote', 'origin', f'refs/heads/{br}'], root, run).strip()
    if not remote:
        git(['switch', '-c', br], root, run)
        (Path(root) / 'VERSION').write_text(v + '\n', encoding='utf-8', newline='\n')
        git(['add', 'VERSION'], root, run)
        rows = ', '.join(r['id'] for r in p['rows']) or 'no rows'
        git([*ident, 'commit', '-q', '-m', f'release v{v} ({p["level"]}): {rows}', '--trailer', 'Release-By: workflow'], root, run)
        git(['push', 'origin', f'refs/heads/{br}:refs/heads/{br}'], root, run)
    view = run(['gh', 'pr', 'view', br, '--json', 'number,state'], cwd=str(root), capture_output=True, text=True)
    state = json.loads(view.stdout).get('state') if view.returncode == 0 and view.stdout.strip() else None
    if state != 'OPEN':
        body = tag_message(p).replace('\n', '\n\n', 1)
        ci.gh(['pr', 'create', '--base', base, '--head', br, '--title', f'release v{v}', '--body', body], run)
    ci.gh(['pr', 'merge', br, '--auto', '--squash'], run)
    return br


def push_tag(root, p, sha, consumers=(), run=subprocess.run):
    """Put the annotated tag vX.Y.Z on `sha` and push it, or confirm it is already there. Never moves a tag."""
    tag = f"v{p['version']}"
    state = remote_tag_state(git(['ls-remote', 'origin', f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}'], root, run), tag, sha)
    if state == 'same':
        return f'{tag} already on {sha[:12]} (annotated): nothing to do'
    if state != 'absent':
        raise ReleaseError(f'{tag} already exists on the remote ({state}): a tag is never moved (C27); find out who made it')
    ident = ['-c', 'user.name=warscape-release', '-c', 'user.email=release@users.noreply.github.com']
    git([*ident, 'tag', '-a', tag, '-m', tag_message(p, consumers), sha], root, run)
    git(['push', 'origin', f'refs/tags/{tag}'], root, run)
    return f'{tag} pushed on {sha[:12]} (annotated)'
