"""A consumer's core bump as one commit (W29, C27, backlog B9): the submodule at the release tag, `[core] version` and the rendered workflows.

purpose: `bump <tag>` in a game repo: fetch the core's tags, refuse a dirty tree, a malformed or missing tag, a lightweight tag where the new core wants annotated ones and the core itself; check the tag out in the submodule, write `[core] version` in wsc.toml (a text edit that keeps its comments), re-render the workflows when the repo has `[ci] core`, and make one commit of the gitlink, wsc.toml and the workflows with the session trailer; name every game verb whose NAME the new core now owns (it deletes nothing)
usage: python3 core/wsc.py core bump vX.Y.Z [--no-commit] [--session ID]   (session: --session, $WSC_SESSION_ID or $CLAUDE_CODE_SESSION_ID; none is a refusal)
when: in a game repo, after the core's release workflow tagged a new version (docs/CONSUMING.md, "Upgrading and releasing"); never inside the core
verb: core
"""
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from .. import release as R
from ..repo import git_env

NAME = 'core'
HELP = "a consumer's core bump: submodule, [core] version and rendered workflows in one commit (B9), colliding verbs named"
TAG = re.compile(r'v\d+\.\d+\.\d+')
NAME_RE = re.compile(r'''^NAME\s*=\s*['"]([^'"]+)['"]''', re.M)


def add_arguments(p):
    p.add_argument('action', choices=['bump'])
    p.add_argument('tag', help='the release tag vX.Y.Z')
    p.add_argument('--no-commit', action='store_true', help='leave the changes staged, no commit')
    p.add_argument('--session', default='', help='the Claude-Session trailer value (default $WSC_SESSION_ID, then $CLAUDE_CODE_SESSION_ID)')


def _git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, env=git_env())


def set_core_version(text, tag):
    """wsc.toml text with `[core] version = "<tag>"`, comments and order kept; a `[core]` table is appended when there is none."""
    m = re.search(r'^\[core\][^\n]*\n', text, re.M)
    if not m:
        return text.rstrip('\n') + f'\n\n[core]\nversion = "{tag}"\n'
    end = re.search(r'^\[', text[m.end():], re.M)
    body_end = m.end() + (end.start() if end else len(text) - m.end())
    body = text[m.end():body_end]
    line = re.compile(r'''^(\s*version\s*=\s*)(["'])[^"'\n]*\2''', re.M)
    body = line.sub(lambda x: f'{x.group(1)}"{tag}"', body, count=1) if line.search(body) else f'version = "{tag}"\n' + body
    return text[:m.end()] + body + text[body_end:]


def collisions(root, verb_dirs, core_verbs):
    """[(path, name)] of the repo's verb modules whose NAME the core's CORE_VERBS now holds (read as text, never imported)."""
    out = []
    for d in verb_dirs:
        for f in sorted((Path(root) / d).glob('*.py')):
            if f.name.startswith('_'):
                continue
            m = NAME_RE.search(f.read_text(encoding='utf-8', errors='replace'))
            if m and m.group(1) in core_verbs:
                out.append((f.relative_to(root).as_posix(), m.group(1)))
    return out


def run(args, ctx):
    def no(msg, code=1):
        print(f'core bump: {msg}', file=sys.stderr)
        return code
    if ctx.is_core:
        return no('this is the core itself: `core bump` runs in a game repo that pins the core as a submodule')
    tag = args.tag
    if not TAG.fullmatch(tag):
        return no(f'{tag!r} is not a release tag vX.Y.Z (lower-case v)', 2)
    session = args.session or os.environ.get('WSC_SESSION_ID', '') or os.environ.get('CLAUDE_CODE_SESSION_ID', '')
    if not session.strip():
        return no('no session id: pass --session, or set $WSC_SESSION_ID or $CLAUDE_CODE_SESSION_ID (every commit carries a Claude-Session trailer, C26)')
    root, core_rel = Path(ctx.root), (ctx.config['ci']['core'] or 'core').strip('/')
    core = root / core_rel
    dirty = _git(root, 'status', '--porcelain', '--untracked-files=no').stdout.strip()
    if dirty:
        return no('the tree has local changes: commit or stash them first\n' + '\n'.join('  ' + l for l in dirty.splitlines()[:10]))
    if not (core / '.git').exists():
        return no(f'{core_rel} is not an initialised submodule: `git submodule update --init {core_rel}`')
    f = _git(core, 'fetch', '-q', '--tags', 'origin')
    if f.returncode:
        return no(f'`git -C {core_rel} fetch --tags origin` failed: {f.stderr.strip()}')
    sha = _git(core, 'rev-parse', '-q', '--verify', f'refs/tags/{tag}^{{commit}}').stdout.strip()
    if not sha:
        return no(f'tag {tag} is not in the core after `git -C {core_rel} fetch --tags` (tags are case-sensitive)')
    kind = _git(core, 'cat-file', '-t', f'refs/tags/{tag}').stdout.strip()
    try:
        new_cfg = tomllib.loads(_git(core, 'show', f'{sha}:wsc.toml').stdout or '')
    except tomllib.TOMLDecodeError:
        new_cfg = {}
    af = (new_cfg.get('release') or {}).get('annotated_from', '')
    if kind != 'tag' and af and R.parse(tag[1:]) >= R.parse(af):
        return no(f'{tag} is a lightweight tag, and the core makes annotated release tags from {af} on (C27): not a release; ask the core owner')
    verbs = R.core_verbs(_git(core, 'show', f'{sha}:warscape/cli.py').stdout) or ()
    hits = collisions(root, ctx.config['cli']['verb_dirs'], verbs)
    co = _git(core, 'checkout', '-q', sha)
    if co.returncode:
        return no(f'`git -C {core_rel} checkout {tag}` failed: {co.stderr.strip()}')
    toml = root / 'wsc.toml'
    toml.write_text(set_core_version(toml.read_text(encoding='utf-8'), tag), encoding='utf-8', newline='\n')
    for path, name in hits:
        print(f'core bump: verb collision: {path} defines `{name}`, which the core now has: delete it; the core\'s verb replaces it')
    add = [core_rel, 'wsc.toml']
    if ctx.config['ci']['core'] and ctx.config['ci']['workflows']:
        r = subprocess.run([sys.executable, str(core / 'wsc.py'), '--root', str(root), 'ci', 'render'], capture_output=True, text=True, timeout=300)
        if r.returncode:
            _git(root, 'add', *add)
            return no(f'`ci render` with the new core failed ({(r.stderr or r.stdout).strip()}): the changes so far are staged; fix that '
                      '(a colliding verb named above?), run `python3 core/wsc.py ci render`, `git add .github/workflows` and commit')
        add.append('.github/workflows')
    a = _git(root, 'add', *add)
    if a.returncode:
        return no(f'git add failed: {a.stderr.strip()}')
    if args.no_commit:
        print(f'core bump: {tag} ({sha[:12]}) staged: {", ".join(add)} (--no-commit)')
        return 0
    c = _git(root, 'commit', '-q', '-m', f'core: bump to {tag}', '--trailer', f'{ctx.config["policy"]["session_trailer"] or "Claude-Session"}: {session}')
    if c.returncode:
        return no(f'git commit failed: {(c.stderr or c.stdout).strip()}')
    print(f'core bump: {tag} ({sha[:12]}): one commit holds {", ".join(add)}' + (f'; {len(hits)} colliding verb(s) above' if hits else ''))
    return 0
