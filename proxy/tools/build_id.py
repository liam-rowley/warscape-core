#!/usr/bin/env python3
"""The proxy DLL's build id: a hash of the DLL inputs' content at a commit, the one implementation (J45).

purpose: print the 12-hex build id of the DLL inputs (their git object ids at a revision, each under a fixed role name), plus -dirty when an input differs from HEAD
usage: python3 proxy/tools/build_id.py [--root <game repo>] [--rev HEAD] [--no-dirty] [--inputs]   (--inputs: print each role, path and object id instead; default root: proxy/tools/layout.py game-root)
when: build.sh calls it for every DLL build; tools/pr_policy.py imports it for rule 79; run it by hand to see which id a DLL or a ledger line should carry
not-a-verb: a build helper shared by build.sh and the policy check, not a registry operation

Why content and not a commit: the id used to be the last commit that touched the inputs (J1 review finding 2: not HEAD, so a report
commit does not change the binary). A reword, rebase or cherry-pick then gave a new id over identical code and rule 79 refused a
branch whose 20 acceptance passes ran on that code (J44 review finding 2). Object ids follow content only, so the id survives any
history edit that leaves the inputs alone, and a shallow clone computes the same id as a full one. Role names, not paths, go into
the hash, so the id depends on nothing but the inputs' content. Old ledger lines keep their commit-hash ids as a record.

Where an input lives (J12): each role names its places, looked up in order at the revision: in the game repo itself (before the move
to warscape-core), then inside each submodule at the commit the revision's gitlink pins (after the move: the core's proxy/src and
proxy/tools, read with `git -C <submodule> rev-parse <gitlink>:<path>`, since `git rev-parse HEAD:core/...` does not reach into a
submodule). The proxy/core tree moves to proxy/src unchanged, so the core role keeps its object id and the DLL its build id.
"""
import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout  # noqa: E402

ADAPTER = None   # the role 'adapter' is the game's proxy adapter folder (layout.proxy_adapter: wsc.toml [proxy] or proxy/*/adapter.cpp)
# The DLL inputs (rule 79's scope): role -> the places it may live, in lookup order. A change to any of them is a new DLL.
INPUTS = [('core', ('proxy/core', 'proxy/src')), ('adapter', (ADAPTER,)), ('build_sh', ('proxy/tools/build.sh',)),
          ('fetch_lua', ('proxy/tools/fetch_lua.py',)), ('build_id', ('proxy/tools/build_id.py',))]


def _git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, env=env)


def _oid(root, spec):
    p = _git(root, 'rev-parse', '--verify', '--quiet', spec)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def _submodules(root):
    p = _git(root, 'config', '-f', '.gitmodules', '--get-regexp', r'^submodule\..*\.path$')
    return [l.split(None, 1)[1].strip() for l in p.stdout.splitlines() if ' ' in l] if p.returncode == 0 else []


def _adapter_rel(root):
    return layout.proxy_adapter(Path(root)).resolve().relative_to(Path(root).resolve()).as_posix()


def locate(root, rev='HEAD'):
    """[(role, display path, object id, (repo, commit-ish, path))] at `rev`; ValueError names an input found nowhere (no silent fallback)."""
    root = Path(root)
    try:
        adapter = _adapter_rel(root)
    except layout.LayoutError as e:
        raise ValueError(f'build_id: {e}') from None
    subs = [(s, _oid(root, f'{rev}:{s}')) for s in _submodules(root)]
    out = []
    for role, places in INPUTS:
        hit = None
        for path in (adapter if p is None else p for p in places):
            oid = _oid(root, f'{rev}:{path}')
            if oid:
                hit = (role, path, oid, (root, rev, path)); break
            for sub, commit in subs:
                oid = commit and (root / sub).is_dir() and _oid(root / sub, f'{commit}:{path}')
                if oid:
                    hit = (role, f'{sub}/{path}', oid, (root / sub, commit, path)); break
            if hit:
                break
        if not hit:
            raise ValueError(f'build_id: {" or ".join(adapter if p is None else p for p in places)} ({role}) is not tracked at {rev}')
        out.append(hit)
    return out


def object_ids(root=None, rev='HEAD'):
    """[(role, path, object id)] at `rev`; raises ValueError naming an input that is not tracked there (never a silent fallback)."""
    return [(role, path, oid) for role, path, oid, _ in locate(root or layout.game_root(), rev)]


def content_id(oids):
    """12 hex of sha256 over 'role oid' lines in INPUTS order."""
    return hashlib.sha256(''.join(f'{role} {oid}\n' for role, _, oid in oids).encode()).hexdigest()[:12]


def build_id(root=None, rev='HEAD', dirty=True):
    """The build id at `rev`; 'nogit' outside a git checkout; '-dirty' appended when `dirty` and an input's working copy differs
    from HEAD (for an input in a submodule: from the commit HEAD's gitlink pins, so a submodule checked out elsewhere is dirty too)."""
    root = root or layout.game_root()
    if _git(root, 'rev-parse', '--git-dir').returncode != 0:
        return 'nogit'
    found = locate(root, rev)
    bid = content_id([(role, path, oid) for role, path, oid, _ in found])
    if dirty:
        for repo, commit, path in {w for *_, w in locate(root, 'HEAD')}:
            if _git(repo, 'diff', '--quiet', commit, '--', path).returncode != 0:
                bid += '-dirty'; break
    return bid


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', help='the game repo checkout (default: proxy/tools/layout.py game-root)')
    ap.add_argument('--rev', default='HEAD', help='the revision whose inputs are hashed')
    ap.add_argument('--no-dirty', action='store_true', help='never append -dirty (the committed id only)')
    ap.add_argument('--inputs', action='store_true', help='print role, path and object id per input')
    a = ap.parse_args(argv)
    try:
        if a.inputs:
            for role, path, oid in object_ids(a.root, a.rev):
                print(f'{role}\t{path}\t{oid}')
        else:
            print(build_id(a.root, a.rev, dirty=not a.no_dirty))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
