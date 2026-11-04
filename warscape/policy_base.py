"""The parent of `wsc policy` (core W23, C24): the base's rule inputs into a temporary folder, the base's code in a child process.

Split from warscape/policy.py (the rules and the in-process judge `run_check`) when that file passed the 350 lines W23's brief allowed it.
`judge` resolves the base and the head, reads the base's wsc.toml from git, finds the core commit that judges (inside the core the base commit
itself; in a game the commit the base's gitlink pins at `[ci] core`, from the submodule's object store), and reads its `JUDGE_API` line
(warscape/policy.py). With the line it writes the base tree with `git archive` (read by `tarfile`, filter 'data') into `tempfile.mkdtemp`,
outside every repository and never a git worktree, runs `<python> -I -X utf8 <tmp>/<core>/wsc.py --root <tmp> policy --judge ...` with
GIT_CEILING_DIRECTORIES above the folder (git inside it finds no repository, even under a `.git` that encloses the temp dir), relays its
lines and deletes the folder. Without the line the base predates W23: it is judged in-process with this checkout's code, with a note.
Exit 0 is ok only with the child's `ok` line and exit 1 is refused only with its `REFUSED` line; anything else is a refusal naming the exit.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

from .policy import Refusal, diff_base, git, resolve, run_check, show
from .repo import DEFAULTS, git_env

JUDGE_API_RE = re.compile(r'^JUDGE_API = (\d+)\r?$', re.M)
JUDGE_TIMEOUT_S = 240   # under the CI job's 5 minutes: a hang is a refusal with a message


def git_bytes(*args, cwd=None):
    return subprocess.run(['git', *args], capture_output=True, check=True, cwd=cwd, env=git_env()).stdout


def base_rules(repo, b, base_ref):
    """(core folder, git cwd of the core commit, core sha, paths to copy from the base beside the core) for the base commit `b`. Raises Refusal."""
    where = f'{base_ref} at {b[:12]}'
    text = show(b, 'wsc.toml', repo)
    try:
        raw = tomllib.loads(text) if text is not None else None
    except tomllib.TOMLDecodeError as e:
        raise Refusal(f"the base's wsc.toml ({where}) does not parse: {e}; fix it on {base_ref} first") from None
    if raw is None:
        raise Refusal(f'the base ({where}) has no wsc.toml: judge against a branch that runs the job pipeline')

    def key(table, name, kind):
        t = raw.get(table, {})
        v = t.get(name, DEFAULTS[table][name]) if isinstance(t, dict) else None
        if not isinstance(v, kind) or (kind is list and not all(isinstance(x, str) and x for x in v)):
            raise Refusal(f"the base's wsc.toml ({where}): [{table}] {name} is not a {kind.__name__}; fix it on {base_ref} first")
        return v
    core, dirs, legacy = key('ci', 'core', str).strip('/'), key('gates', 'dirs', list), key('jobs', 'legacy', str)
    extra = ['wsc.toml', *dirs, *([legacy] if legacy else [])]
    if not core:
        return '', repo, b, extra
    entry = git('ls-tree', '-z', b, '--', core, cwd=repo).split('\0')[0].split(None, 3)
    if len(entry) < 4 or entry[0] != '160000' or entry[3] != core:
        raise Refusal(f'the base ({where}) has no core gitlink at {core} (wsc.toml [ci] core): a game pins the core as a submodule there; '
                      'inside the core itself set [ci] core = ""')
    pin, cwd = entry[2], os.path.join(repo, core)
    try:
        top = git('rev-parse', '--show-toplevel', cwd=cwd).strip()
    except (subprocess.CalledProcessError, OSError):
        top = ''
    if not top or Path(top).resolve() != Path(cwd).resolve():   # an empty core/ would find the game repo above it
        raise Refusal(f'the core submodule at {core} is not initialised: `git submodule update --init {core}`')
    if resolve(pin, cwd) != pin:
        raise Refusal(f'the base ({where}) pins core {pin} and the submodule lacks it: `git -C {core} fetch origin {pin}`')
    return core, cwd, pin, extra


def _untar(data, dest):
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(dest, filter='data')


def write_base_tree(tmp, repo, b, core, cwd, pin, extra):
    """The base's rule inputs under `tmp`: the core commit's tree (at `core`), and in a game the base's `extra` paths that exist."""
    try:
        _untar(git_bytes('archive', '--format=tar', pin, cwd=cwd), Path(tmp) / core)
        if core:
            have = [p for p in git('ls-tree', '-z', '--name-only', b, '--', *extra, cwd=repo).split('\0') if p]
            if have:
                _untar(git_bytes('archive', '--format=tar', b, '--', *have, cwd=repo), Path(tmp))
    except (subprocess.CalledProcessError, tarfile.TarError, OSError) as e:
        detail = e.stderr.decode('utf-8', 'replace').strip() if isinstance(getattr(e, 'stderr', None), bytes) else str(e)
        raise Refusal(f"the base's rules could not be written to a temporary folder: {detail}") from None


def judge_args(api, repo, branch, b, h, base_ref):
    """The child's arguments for a base whose core speaks JUDGE_API `api` (1: these; a later number may only add optional ones)."""
    return ['policy', '--judge', f'--repo={repo}', f'--branch={branch}', f'--base={b}', f'--head={h}', f'--base-ref={base_ref}']


def _child(tmp, core, args):
    """(exit code or None, how it ended, stdout, stderr) of the base's code run on the base tree."""
    env = {**git_env(), 'GIT_CEILING_DIRECTORIES': os.path.dirname(os.path.realpath(tmp))}   # git in the base tree finds no repository
    cmd = [sys.executable, '-I', '-X', 'utf8', str(Path(tmp) / core / 'wsc.py'), '--root', tmp, *args]
    try:
        p = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, timeout=JUDGE_TIMEOUT_S)
        rc, how, out, err = p.returncode, f'exit {p.returncode}', p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        rc, how, out, err = None, f'timed out after {JUDGE_TIMEOUT_S} s', e.stdout or b'', e.stderr or b''
    return rc, how, out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')


def judge(ctx, branch, base='origin/main', head='HEAD'):
    """`wsc policy --branch B --base REF --head REV`: judge B at REV with the rules of REF. Prints the lines and returns the exit code:
    0 ok, 1 refused. The repo is the clone at ctx.root; ctx's own config and gate modules are used only by the pre-W23 fallback."""
    repo, n = str(Path(ctx.root).resolve()), None

    def refuse(msg):
        print(f'policy: {msg}', file=sys.stderr)
        print(f'policy: {branch}: REFUSED ({n} files changed)' if n is not None else f'policy: {branch}: REFUSED (not judged)')
        return 1
    try:
        b, h, mb, changed = diff_base(base, head, repo)
        n = len(changed)
        core, cwd, pin, extra = base_rules(repo, b, base)
        m = JUDGE_API_RE.search(show(pin, 'warscape/policy.py', cwd) or '')
        if not m:
            print(f"policy: note: the base's core predates base-judged policy (no JUDGE_API at {pin[:12]}): judged with this checkout's rules, as before W23")
            errs, changed = run_check(ctx, branch, b, h, repo, base_ref=base)
            for e in errs:
                print(f'policy: {e}', file=sys.stderr)
            print(f'policy: {branch}: {"REFUSED" if errs else "ok"} ({len(changed)} files changed)')
            return 1 if errs else 0
        tmp = tempfile.mkdtemp(prefix='wsc-policy-')
        try:
            write_base_tree(tmp, repo, b, core, cwd, pin, extra)
            vf = Path(tmp) / core / 'VERSION'
            print(f"policy: judged with the rules of {base} at {b[:12]} (core {vf.read_text(encoding='utf-8').strip() if vf.is_file() else 'unknown'})", flush=True)
            rc, how, out, err = _child(tmp, core, judge_args(int(m.group(1)), repo, branch, b, h, base))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sys.stdout.write(out)
        sys.stdout.flush()
        sys.stderr.write(err)
        got = re.findall(rf'^policy: {re.escape(branch)}: (ok|REFUSED) \(\d+ files changed\)\r?$', out, re.M)
        if (rc, got) in ((0, ['ok']), (1, ['REFUSED'])):
            return rc
        return refuse(f"the base's rules gave no verdict ({how}): {(err.strip().splitlines() or ['no error output'])[-1]}")
    except Refusal as e:
        return refuse(str(e))
    except subprocess.CalledProcessError as e:   # a git read failed: never a pass
        detail = e.stderr if isinstance(e.stderr, str) else (e.stderr or b'').decode('utf-8', 'replace')
        return refuse(f'git failed while judging ({" ".join(map(str, e.cmd[:3]))}): {detail.strip()}')
