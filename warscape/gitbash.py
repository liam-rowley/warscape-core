"""The Git Bash finder: which bash runs the core's and a game's shell scripts (`harness/job.sh`, `shot.sh`, the host tests).

On Windows `bash` on PATH may be the WSL launcher (System32 or WindowsApps), which runs a WSL distro with other paths and another
python3; the scripts need Git for Windows' bash.exe, found explicitly. Off Windows the bash on PATH is the answer. `harness/ctl.py`
`bash()` and the host tests use this module, and a game's setup verb imports it (`from warscape.gitbash import git_bash, bash_kind,
bash_for_tests`; verbs run with the core on `sys.path`) instead of keeping its own (B18, ported from the first consumer's
`tools/verbs/setup.py`, J41 and J22). Every probe is an injectable parameter so the host tests (`tests/test_gitbash.py`) run anywhere.
Standard library only.
"""
import os
import shutil
import subprocess


def bash_kind(path, nt=os.name == 'nt'):
    """'git' for Git for Windows' bash, 'wsl' for the System32/WindowsApps launcher (a WSL distro: other paths, other python3), 'other'
    for any other Windows bash, 'posix' off Windows, None when there is none. Windows needs 'git'."""
    if not path:
        return None
    if not nt:
        return 'posix'
    p = str(path).replace('\\', '/').lower()
    if '/windows/system32/' in p or '/windowsapps/' in p:
        return 'wsl'
    return 'git' if '/git/' in p else 'other'


def _git_exec_path():
    """`git --exec-path` (e.g. C:/Program Files/Git/mingw64/libexec/git-core), or '' when git cannot say."""
    try:
        r = subprocess.run(['git', '--exec-path'], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ''
    return r.stdout.strip() if r.returncode == 0 else ''


def roots(git_exec_path, environ=None):
    """The Git install folders to probe, in order: the one `git --exec-path` names, then `%ProgramFiles%/Git`, `%ProgramW6432%/Git` and
    `%LOCALAPPDATA%/Programs/Git` (a per-user install). `%LOCALAPPDATA%/Git` is not an install folder and is never probed."""
    env = os.environ if environ is None else environ
    out = []
    p = (git_exec_path or '').strip().replace('\\', '/')
    i = p.lower().find('/mingw')
    if i > 0:
        out.append(p[:i])
    out += [f'{env[v]}/Git' for v in ('ProgramFiles', 'ProgramW6432') if env.get(v)]
    if env.get('LOCALAPPDATA'):
        out.append(f'{env["LOCALAPPDATA"]}/Programs/Git')
    return out


def git_bash(nt=os.name == 'nt', which=shutil.which, git_exec_path=None, isfile=os.path.isfile, environ=None):
    """The bash to run shell scripts with: off Windows the bash on PATH; on Windows Git for Windows' bash.exe, found explicitly. Order:
    `bash` on PATH when it is Git's, the Git install that `git --exec-path` names, the install folders of `roots()`. None when there is
    none (never the WSL launcher)."""
    b = which('bash')
    if not nt:
        return b
    if bash_kind(b, nt=True) == 'git':
        return b
    if git_exec_path is None:
        git_exec_path = _git_exec_path()
    for r in roots(git_exec_path, environ):
        for sub in ('bin/bash.exe', 'usr/bin/bash.exe'):   # bin/bash.exe sets up the MSYS PATH itself
            c = f'{r}/{sub}'.replace('/', '\\')
            if isfile(c):
                return c
    return None


def bash_for_tests(nt=os.name == 'nt', find=None, environ=None):
    """(bash, None) or (None, reason) for a host test that runs a shell script. On Windows git_bash() or a skip reason, never the WSL
    `bash` on PATH; off Windows git_bash() or plain 'bash', so a missing bash fails as before instead of skipping."""
    b = (find or git_bash)(nt=nt)
    if b or not nt:
        return b or 'bash', None
    looked = ['bash on PATH (when it is Git\'s)', 'git --exec-path'] + [f'{r}/bin/bash.exe' for r in roots('', environ)]
    return None, f'no Git Bash found (looked in: {", ".join(looked)}); the WSL bash on PATH is never used'


REQUIRE_ENV = 'WSC_REQUIRE_BASH'


def bash_or_skip(test, python3=True, found=None, which=shutil.which, environ=None):
    """The bash for a unittest case that runs a shell script; without one (or without python3 on PATH when the script reads JSON with it,
    as harness/job.sh does) the case is skipped with the reason. With $WSC_REQUIRE_BASH set (CI's harness-windows job) it fails instead,
    so a job that must run the scripts cannot pass on a skip. `found` is a (bash, reason) pair, default bash_for_tests()."""
    env = os.environ if environ is None else environ
    bash, why = found or bash_for_tests()
    if not why and python3 and not which('python3'):
        why = 'the script calls python3, which is not on PATH here'
    if why:
        if env.get(REQUIRE_ENV):
            test.fail(f'${REQUIRE_ENV} is set: {why}')
        test.skipTest(why)
    return bash
