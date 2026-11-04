"""Stale worktrees and a `.git` above the repository (core W26): what a game's `wsc setup` warns about, what `wsc jobs worktrees` prints and
what the autopilot's tick prunes. Library code (not a tool); git runs through `subprocess` with `git_env()` (C12), and every function takes
an injectable `run`.

- `registered(root)`: the worktrees git knows, from `git worktree list --porcelain` (git itself marks a `prunable` one).
- `stale(root, rows, branches)`: (gone, merged). `gone`: registrations whose folder does not exist (what `git worktree prune` removes).
  `merged`: worktrees other than the main one whose branch is `job/<id>` with the row done, `brief/<id>` with the row past needs_brief,
  an ancestor of `origin/main`, or whose remote branch is gone (`[gone]` upstream after a fetch --prune, or a job/ or brief/ branch not in
  `branches`). Merged worktrees are reported, never removed: one can hold unpushed work.
- `stray_git(root)`: the first folder above the main worktree's root that holds a `.git` (folder or file); a linked worktree's own
  repository does not count, nor does the superproject of a submodule.
- `report(root, rows, branches)`: the warning lines; `prune(root)`: `git worktree prune`, as (registrations removed, error or None).
"""
import subprocess
from pathlib import Path

from .repo import git_env

MAX_NAMED = 5


def _git(root, *args, run=subprocess.run):
    return run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=120, env=git_env())


def registered(root, run=subprocess.run):
    """[(path, branch or None, prunable reason or None)], the main worktree first. Raises ValueError when git cannot list them."""
    p = _git(root, 'worktree', 'list', '--porcelain', run=run)
    if p.returncode != 0:
        raise ValueError((p.stderr or p.stdout).strip()[:200] or f'git worktree list exited {p.returncode}')
    out, cur = [], None
    for line in (p.stdout or '').replace('\r\n', '\n').split('\n'):
        key, _, val = line.partition(' ')
        if key == 'worktree':
            cur = [val, None, None]
            out.append(cur)
        elif cur is not None and key == 'branch':
            cur[1] = val[len('refs/heads/'):] if val.startswith('refs/heads/') else val
        elif cur is not None and key == 'prunable':
            cur[2] = val or 'prunable'
    return [tuple(x) for x in out]


def _upstream_gone(root, run):
    p = _git(root, 'for-each-ref', '--format=%(refname:short)%09%(upstream:track)', 'refs/heads/', run=run)
    return {l.split('\t', 1)[0] for l in (p.stdout or '').splitlines() if l.endswith('[gone]')} if p.returncode == 0 else set()


def _merged(root, branch, by, branches, gone_upstream, run):
    kind, _, jid = branch.partition('/')
    st = by.get(jid, {}).get('status')
    if kind == 'job' and st == 'done':
        return True
    if kind == 'brief' and st not in (None, 'needs_brief'):
        return True
    if branch in gone_upstream:
        return True
    if kind in ('job', 'brief') and branches is not None and branch not in branches:
        return True
    return _git(root, 'merge-base', '--is-ancestor', f'refs/heads/{branch}', 'refs/remotes/origin/main', run=run).returncode == 0


def stale(root, rows, branches, run=subprocess.run):
    """(gone, merged): lists of worktree paths as git prints them (see the module doc). `branches`: origin's branch names, or None."""
    reg = registered(root, run)
    by = {r['id']: r for r in rows}
    gone_upstream = _upstream_gone(root, run)
    gone, merged = [], []
    for i, (path, branch, _) in enumerate(reg):
        if i == 0:
            continue   # the main worktree is never stale
        if not Path(path).is_dir():
            gone.append(path)
        elif branch and _merged(root, branch, by, branches, gone_upstream, run):
            merged.append(path)
    return gone, merged


def _rev_parse(root, *args, run):
    p = _git(root, 'rev-parse', *args, run=run)
    return p.stdout.strip() if p.returncode == 0 else ''


def main_root(root, run=subprocess.run):
    """The main worktree's root: the parent of the common `.git` (a linked worktree shares it); a submodule's own top level."""
    common = _rev_parse(root, '--path-format=absolute', '--git-common-dir', run=run)
    if common and Path(common).name == '.git':
        return Path(common).parent
    top = _rev_parse(root, '--show-toplevel', run=run)
    return Path(top) if top else Path(root)


def stray_git(root, ceiling=None, run=subprocess.run):
    """The first folder above the main worktree's root that holds a `.git`, or None; the walk stops at the filesystem root (a `.git` in a
    drive root counts) or at `ceiling` (inclusive; the tests' temp folder). A submodule's superproject is expected, not stray."""
    base = main_root(root, run).resolve()
    sup = _rev_parse(root, '--show-superproject-working-tree', run=run)
    sup = Path(sup).resolve() if sup else None
    stop = Path(ceiling).resolve() if ceiling is not None else None
    for p in base.parents:
        if (p / '.git').exists() and p != sup:
            return p
        if stop is not None and p == stop:
            break
    return None


def report(root, rows, branches, ceiling=None, run=subprocess.run):
    """The warning lines for a game's `wsc setup` and `wsc jobs worktrees` ([] when there is nothing to say)."""
    lines = []
    try:
        gone, merged = stale(root, rows, branches, run)
    except ValueError as x:
        return [f'cannot list the worktrees: {x}']
    if gone:
        lines.append(f'{len(gone)} registered worktrees have no folder: git worktree prune removes them')
    if merged:
        more = f' (and {len(merged) - MAX_NAMED} more)' if len(merged) > MAX_NAMED else ''
        lines.append(f"{len(merged)} worktrees' branches are merged: {', '.join(merged[:MAX_NAMED])}{more}, "
                     'remove them with git worktree remove <path>')
    stray = stray_git(root, ceiling, run)
    if stray is not None:
        lines.append(f'a .git sits above this repository at {(stray / ".git").as_posix()}: git commands run from '
                     f'{Path(root).resolve().as_posix()} may act on that repository; delete it or move the clones')
    return lines


def prune(root, run=subprocess.run):
    """`git worktree prune` in `root`: (registrations removed, None) or (0, the reason it failed); never an exception."""
    try:
        before = len(registered(root, run))
        p = _git(root, 'worktree', 'prune', run=run)
        if p.returncode != 0:
            return 0, (p.stderr or p.stdout).strip()[:200] or f'git worktree prune exited {p.returncode}'
        return max(0, before - len(registered(root, run))), None
    except (ValueError, OSError, subprocess.SubprocessError) as x:
        return 0, str(x) or type(x).__name__
