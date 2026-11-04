"""Shared helpers for the host tests: put the core on sys.path, build throwaway repos, run the CLI in-process."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from warscape.cli import main  # noqa: E402


def git(cwd, *args, check=True):
    """git in a throwaway repo: a fixed identity, no hooks, no signing, LF as written, local file:// submodules allowed."""
    env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
    return subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
                           '-c', 'protocol.file.allow=always', '-c', 'init.defaultBranch=main', *args],
                          cwd=cwd, env=env, check=check, capture_output=True, text=True)


_CORE_SOURCE = []


def core_source():
    """A throwaway core repo, made once per test process (W23): every file `repo.list_files` lists in this checkout, committed as `main`.
    Tests clone it (the core judging itself) or add it as a game's `core` submodule; none changes it."""
    if not _CORE_SOURCE:
        from warscape.repo import list_files
        td = tempfile.TemporaryDirectory()
        src = Path(td.name).resolve() / 'core'
        for rel in list_files(CORE):
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CORE / rel, src / rel)
        git(src, 'init', '-q', '-b', 'main')
        git(src, 'add', '-A')
        git(src, 'commit', '-q', '-m', 'core')
        _CORE_SOURCE[:] = [td, src]
    return _CORE_SOURCE[1]


FIXTURE = CORE / 'tests' / 'fixture_game'
FIXTURE_REPORT = ('# F1 report: Fixture first job\n\n## What exists\nNothing; a fixture.\n\n## Deviations from the brief, and why\nNone.\n\n'
                  '## Open questions\nNone.\n')


def fixture_game(dest):
    """tests/fixture_game as a throwaway git repo at `dest`: its F1 report written (the file the fixture cannot ship as a report.md), its
    workflows rendered, the throwaway core added as its `core` submodule (W23: `policy` judges with the core commit the base pins), all
    committed as `main`, and `origin/main` pointing there."""
    shutil.copytree(FIXTURE, dest)
    (dest / 'jobs' / 'F1' / 'report.md').write_text(FIXTURE_REPORT, encoding='utf-8', newline='\n')
    subprocess.run([sys.executable, str(CORE / 'wsc.py'), '--root', str(dest), 'ci', 'render'], capture_output=True, check=True, timeout=120)
    git(dest, 'init', '-q', '-b', 'main')
    git(dest, 'submodule', 'add', '-q', str(core_source()), 'core')
    git(dest, 'add', '-A')
    git(dest, 'commit', '-q', '-m', 'fixture')
    git(dest, 'update-ref', 'refs/remotes/origin/main', 'HEAD')

MINIMAL_TOML = '''
registries_dir = "registries"
[registries]
tools = "core:tools"
scenarios = "core:scenarios"
hotkeys = "core:hotkeys"
engine_facts = "core:engine_facts"
config_keys = "core:config_keys"
engine_sites = "core:engine_sites"
ui_elements = "core:ui_elements"
assets = "core:assets"
[tests]
dirs = []
'''

TOOL_PY = '''#!/usr/bin/env python3
# purpose: Do a thing for the tests.
# usage: python3 {name}
# when: in tests only.
# not-a-verb: a test fixture.
print("hi")
'''


class TempRepo:
    """A git-initialised temp folder with a wsc.toml; `files` maps relative path -> text."""

    def __init__(self, files=None, toml=MINIMAL_TOML):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.write('wsc.toml', textwrap.dedent(toml))
        for k, v in (files or {}).items():
            self.write(k, v)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        return p

    def read(self, rel):
        return (self.root / rel).read_text(encoding='utf-8')

    def wsc(self, *args):
        """(exit code, stdout + stderr) of `wsc --root <repo> args...`, run in-process."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                rc = main(['--root', str(self.root), *args])
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue()

    def close(self):
        self._td.cleanup()
