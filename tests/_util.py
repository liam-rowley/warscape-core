"""Shared helpers for the host tests: put the core on sys.path, build throwaway repos, run the CLI in-process."""
import contextlib
import io
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from warscape.cli import main  # noqa: E402

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
