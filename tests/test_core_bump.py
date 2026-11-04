"""W29 (B9, C27): `wsc core bump <tag>` in a consumer: one commit holds the gitlink, wsc.toml and the rendered workflows, with the trailer.

A throwaway core (tests/_util.py `core_source`) is cloned and given release tags; the fixture game pins the clone as its `core` submodule over
file:// (`-c protocol.file.allow=always`, set by `_util.git`), and the game's own core/wsc.py runs the verb, as a consumer would.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _util import core_source, fixture_game, git


class CoreBump(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addClassCleanup(cls._td.cleanup)
        t = Path(cls._td.name).resolve()
        cls.src = t / 'core-src'
        git(t, 'clone', '-q', str(core_source()), str(cls.src))
        (cls.src / 'NEW.txt').write_text('a release\n')
        git(cls.src, 'add', '-A')
        git(cls.src, 'commit', '-q', '-m', 'a release')
        git(cls.src, 'tag', '-a', 'v0.31.0', '-m', 'v0.31.0')
        git(cls.src, 'tag', 'v0.35.0')              # lightweight, at or above [release] annotated_from: not a release
        git(cls.src, 'tag', '-a', 'v0.0.1', '-m', 'old', 'HEAD~1')
        cls.base = t / 'game-base'
        fixture_game(cls.base)
        git(cls.base / 'core', 'remote', 'set-url', 'origin', cls.src.as_uri())

    def setUp(self):
        self._t = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._t.cleanup)
        self.game = Path(self._t.name).resolve() / 'game'
        git(Path(self._t.name), 'clone', '-q', '--recurse-submodules', str(self.base), str(self.game))
        git(self.game / 'core', 'remote', 'set-url', 'origin', self.src.as_uri())

    def bump(self, *args, session='sess-1'):
        env = {k: v for k, v in os.environ.items() if k not in ('WSC_SESSION_ID', 'CLAUDE_CODE_SESSION_ID')}
        env.update({'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t',
                    'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'protocol.file.allow', 'GIT_CONFIG_VALUE_0': 'always',
                    'GIT_CONFIG_KEY_1': 'core.hooksPath', 'GIT_CONFIG_VALUE_1': os.devnull})
        if session:
            env['WSC_SESSION_ID'] = session
        p = subprocess.run([sys.executable, str(self.game / 'core' / 'wsc.py'), '--root', str(self.game), 'core', 'bump', *args],
                           capture_output=True, text=True, env=env, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def test_one_commit_holds_gitlink_toml_and_trailer(self):
        rc, out = self.bump('v0.31.0')
        self.assertEqual(rc, 0, out)
        files = git(self.game, 'show', '--name-only', '--format=', 'HEAD').stdout.split()
        self.assertIn('core', files)
        self.assertIn('wsc.toml', files)
        self.assertIn('version = "v0.31.0"', (self.game / 'wsc.toml').read_text(encoding='utf-8'))
        # the fixture's [policy] session_trailer
        self.assertIn('Agent-Session: sess-1', git(self.game, 'log', '-1', '--format=%B').stdout)
        pin = git(self.game, 'ls-tree', 'HEAD', 'core').stdout.split()[2]
        self.assertEqual(pin, git(self.src, 'rev-parse', 'v0.31.0^{commit}').stdout.strip())
        self.assertEqual(git(self.game, 'status', '--porcelain', '--untracked-files=no').stdout.strip(), '')

    def test_no_commit_leaves_it_staged(self):
        rc, out = self.bump('v0.31.0', '--no-commit')
        self.assertEqual(rc, 0, out)
        staged = git(self.game, 'diff', '--cached', '--name-only').stdout.split()
        self.assertEqual(sorted(set(staged) & {'core', 'wsc.toml'}), ['core', 'wsc.toml'])

    def test_refusals(self):
        for args, want in ((('0.31.0',), 'not a release tag'), (('V0.31.0',), 'not a release tag'), (('v9.9.9',), 'not in the core'),
                           (('v0.35.0',), 'lightweight tag')):
            rc, out = self.bump(*args)
            self.assertNotEqual(rc, 0, out)
            self.assertIn(want, out, args)
        rc, out = self.bump('v0.31.0', session='')
        self.assertIn('no session id', out)
        (self.game / 'wsc.toml').write_text((self.game / 'wsc.toml').read_text(encoding='utf-8') + '\n# local\n', encoding='utf-8')
        rc, out = self.bump('v0.31.0')
        self.assertIn('local changes', out)
        self.assertEqual(git(self.game, 'log', '-1', '--format=%s').stdout.strip(), 'fixture')


if __name__ == '__main__':
    unittest.main()
