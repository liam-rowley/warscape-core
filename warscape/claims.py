"""Review claims (core W27, audit R7): two reviewers never start the same round of a job at once.

A claim is the remote ref `refs/claims/<id>/round-<n>` on origin. It points at a commit made for the claim (the job branch head's tree, the
head as its parent, the claimer's session and the time in its message), so two claimers push two different commits and git refuses the
second creator of the ref (non-fast-forward, no force): the push is the lock. Read by `jobq` for `wsc jobs review` and the autopilot's
`JobServer.start()`. A claim older than `[jobs] claim_hours` is stale and is taken over (deleted with a lease on its sha, then claimed); a
claim for a round the branch already has, or for a job whose branch is gone, is released by the next `jobs next|review` run. Every read and
write fails closed (ClaimError): a claim that cannot be proved is not held. `.githooks/pre-push` skips its gates for a push of claim refs only.
"""
import getpass
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from typing import NamedTuple

from .repo import git_env

NS = 'refs/claims'
REF = re.compile(r'^refs/claims/([A-Za-z]+[1-9]\d*)/round-([1-9]\d*)$')
IDENTITY = {'GIT_AUTHOR_NAME': 'wsc jobs', 'GIT_AUTHOR_EMAIL': 'wsc-jobs@localhost', 'GIT_COMMITTER_NAME': 'wsc jobs',
            'GIT_COMMITTER_EMAIL': 'wsc-jobs@localhost'}


class ClaimError(Exception):
    """origin cannot be read or written, so the claim cannot be proved: refuse (the message names the git error)."""


class Claim(NamedTuple):
    jid: str
    round: int
    sha: str
    session: str
    when: int   # epoch seconds of the claim commit (0: unknown)


def ref(jid, n):
    return f'{NS}/{jid}/round-{n}'


def session_name(given=None):
    """Who claims: `--session`, then $WSC_SESSION_ID, then $CLAUDE_CODE_SESSION_ID, then user@host."""
    try:
        user = getpass.getuser()
    except Exception:
        user = 'someone'
    return given or os.environ.get('WSC_SESSION_ID') or os.environ.get('CLAUDE_CODE_SESSION_ID') or f'{user}@{socket.gethostname()}'


def _git(root, *args, env=None):
    try:
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=120, env={**git_env(), **(env or {})})
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ClaimError(f'git {args[0]} failed: {e}') from None


def read(root, remote='origin'):
    """Every claim on `remote`, oldest round first: one `ls-remote`, and one fetch of the claim commits when there are any."""
    p = _git(root, 'ls-remote', remote, f'{NS}/*')
    if p.returncode:
        raise ClaimError(f'git ls-remote {remote} failed: {(p.stderr or "").strip()[:200]}')
    refs = []
    for line in p.stdout.splitlines():
        sha, _, name = line.partition('\t')
        m = REF.match(name.strip())
        if m:
            refs.append((m.group(1), int(m.group(2)), sha.strip()))
    if not refs:
        return []
    f = _git(root, 'fetch', '-q', '--no-tags', remote, f'+{NS}/*:{NS}/*')
    if f.returncode:
        raise ClaimError(f'git fetch of the claims failed: {(f.stderr or "").strip()[:200]}')
    out = _git(root, 'log', '--no-walk=unsorted', '--format=%H%x1f%ct%x1f%B%x1e', *{s for _, _, s in refs}).stdout
    info = {}
    for rec in out.split('\x1e'):
        parts = rec.strip('\n').split('\x1f')
        if len(parts) == 3:
            m = re.search(r'^session: (.+)$', parts[2], re.M)
            info[parts[0]] = (int(parts[1]) if parts[1].isdigit() else 0, m.group(1).strip() if m else 'unknown')
    return sorted((Claim(j, n, s, info.get(s, (0, 'unknown'))[1], info.get(s, (0, ''))[0]) for j, n, s in refs),
                  key=lambda c: (c.jid, c.round))


def _push(root, remote, *refspec, lease=None):
    """(True, '') when the push landed, (False, the git line) when the remote refused this ref; raises ClaimError on anything else."""
    p = _git(root, 'push', '--porcelain', *([f'--force-with-lease={lease[0]}:{lease[1]}'] if lease else []), remote, *refspec)
    bad = [l for l in p.stdout.splitlines() if l.startswith('!')]
    if bad:
        return False, bad[0]
    if p.returncode:
        raise ClaimError(f'git push {remote} failed: {(p.stderr or p.stdout).strip()[:200]}')
    return True, ''


def take(root, jid, n, head, session, hours=4, now=None, remote='origin'):
    """(True, the claim) when `session` now holds round `n` of `jid` (or already did); (False, the holder's claim) when another live session
    holds it. A claim older than `hours` is deleted (with a lease on its sha) and taken. Raises ClaimError."""
    now = int(now if now is not None else time.time())
    name = ref(jid, n)
    for c in read(root, remote):
        if (c.jid, c.round) != (jid, n):
            continue
        if c.session == session:
            return True, c
        if c.when and now - c.when < hours * 3600:
            return False, c
        gone, line = _push(root, remote, f':{name}', lease=(name, c.sha))
        if not gone:
            raise ClaimError(f'the stale claim {name} of {c.session} changed while it was taken over: {line}')
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    msg = f'review claim: {jid} round {n}\n\nsession: {session}\ntime: {stamp}\n'
    c = _git(root, 'commit-tree', f'{head}^{{tree}}', '-p', head, '-m', msg,
             env={**IDENTITY, 'GIT_AUTHOR_DATE': f'{now} +0000', 'GIT_COMMITTER_DATE': f'{now} +0000'})
    if c.returncode:
        raise ClaimError(f'cannot make the claim commit on {head[:12]}: {(c.stderr or "").strip()[:200]} (fetch the job branch first)')
    sha = c.stdout.strip()
    ok, line = _push(root, remote, f'{sha}:{name}')
    if ok:
        return True, Claim(jid, n, sha, session, now)
    holder = next((x for x in read(root, remote) if (x.jid, x.round) == (jid, n)), None)
    if holder is None:
        raise ClaimError(f'origin refused {name} ({line}) but holds no such claim')
    return (holder.session == session), holder


def release(root, claims, rounds, branches, remote='origin'):
    """Delete each claim whose round the job branch already has (`rounds`: {id: rounds in its review.md}) or whose job/<id> branch is gone;
    the claims released. A refused or failed delete is left for the next run."""
    gone = []
    for c in claims:
        if f'job/{c.jid}' in branches and rounds.get(c.jid, 0) < c.round:
            continue
        try:
            ok, _ = _push(root, remote, f':{ref(c.jid, c.round)}', lease=(ref(c.jid, c.round), c.sha))
        except ClaimError:
            ok = False
        if ok:
            gone.append(c)
    return gone


def age(c, now=None):
    """'12 min' / '3 h' since the claim, or 'unknown'."""
    if not c.when:
        return 'unknown'
    s = max(0, int(now if now is not None else time.time()) - c.when)
    return f'{s // 60} min' if s < 3600 else f'{s // 3600} h'
