"""The `core_pin` gate against throwaway git repositories (core W11: backlog B7, B11, B12; decisions C10, C12 and the W11 row).

A fake core is a temp git repository with a `VERSION`, commits and `vX.Y.Z` tags; a fake game pins it, either beside it (B7) or as a real
`core/` submodule (B11, B12). The gate runs in-process with `Ctx(root=game, core_root=fake core)`, so every case, the failing ones too, is seen.
`git` refuses the local-file protocol for submodules unless `-c protocol.file.allow=always`, which every call here passes itself.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _util  # noqa: F401  (puts the core on sys.path)
from warscape import gates
from warscape.repo import Ctx, git_env

GIT_C = ['-c', 'protocol.file.allow=always', '-c', 'user.name=wsc test', '-c', 'user.email=test@example.invalid',
         '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false', '-c', 'init.defaultBranch=main', '-c', 'core.autocrlf=false']


def git(cwd, *args):
    p = subprocess.run(['git', *GIT_C, *args], cwd=cwd, capture_output=True, text=True, timeout=60, env=git_env())
    if p.returncode:
        raise AssertionError(f'git {" ".join(args)} in {cwd} failed ({p.returncode}):\n{p.stdout}{p.stderr}')
    return p.stdout.strip()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())
    return path


def url(path):
    """A file:// URL, so `--depth` is honoured (git ignores it for a plain local path)."""
    return path.resolve().as_uri()


def run_gate(game, core, pin):
    return gates.gate_core_pin(Ctx(root=game, config={'core': {'version': pin}}, core_root=core))


class Tmp(unittest.TestCase):
    """`cls.tmp` holds what a class builds once in `setUpClass` (git is slow on Windows); `self.tmp` is each test's own folder."""
    @classmethod
    def setUpClass(cls):
        cls._ctd = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.ctmp = Path(cls._ctd.name).resolve()
        cls.addClassCleanup(cls._ctd.cleanup)

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._td.name).resolve()
        self.addCleanup(self._td.cleanup)

    @staticmethod
    def make_core(where, versions=('0.1.0',)):
        """A fake core in `where`: one commit per version, each tagged v<version>. Returns its path."""
        core = where / 'core-src'
        git(where, 'init', '-q', str(core))
        write(core / 'a.txt', 'a\n')
        for v in versions:
            write(core / 'VERSION', v + '\n')
            git(core, 'add', '-A')
            git(core, 'commit', '-q', '-m', f'release {v}')
            git(core, 'tag', f'v{v}')
        return core

    def assertLevel(self, r, level, *needles):
        self.assertEqual(r.level, level, f'{r.summary}\n' + '\n'.join(r.details))
        text = '\n'.join([r.summary, *r.details])
        for n in needles:
            self.assertIn(n, text)


class DirtyCore(Tmp):
    """B7: the gate reads VERSION from ctx.core_root, so a throwaway core is checked, and every failure is seen failing."""
    def setUp(self):
        super().setUp()
        self.core = self.make_core(self.tmp)
        self.game = self.tmp / 'game'
        self.game.mkdir()

    def test_clean_and_tagged(self):
        self.assertLevel(run_gate(self.game, self.core, 'v0.1.0'), 'ok', 'core 0.1.0 as pinned (tag v0.1.0), unmodified')

    def test_modified_tracked_file(self):
        write(self.core / 'a.txt', 'patched in place\n')
        self.assertLevel(run_gate(self.game, self.core, 'v0.1.0'), 'error', 'local changes', 'a.txt')

    def test_untracked_file(self):
        write(self.core / 'new.txt', 'x\n')
        self.assertLevel(run_gate(self.game, self.core, 'v0.1.0'), 'error', 'local changes', 'new.txt')

    def test_head_past_the_tag(self):
        write(self.core / 'a.txt', 'b\n')
        git(self.core, 'commit', '-q', '-am', 'past the tag')
        self.assertLevel(run_gate(self.game, self.core, 'v0.1.0'), 'error', 'untagged commit', 'not the pinned tag v0.1.0')

    def test_version_not_matching_the_pin(self):
        write(self.core / 'VERSION', '0.1.1\n')
        git(self.core, 'commit', '-q', '-am', 'VERSION says 0.1.1')
        git(self.core, 'tag', '-f', 'v0.1.0')
        self.assertLevel(run_gate(self.game, self.core, 'v0.1.0'), 'error', 'pins core v0.1.0 but the core checkout is 0.1.1')


class LinkedWorktree(Tmp):
    """B11: pushed from a linked worktree of a game repo, the pre-push hook's GIT_* environment must not make the gate read the
    superproject. The environment is recorded from a real pre-push hook in that worktree, then the gate runs under it. Built once;
    a test that edits a file restores it."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        core = cls.make_core(cls.ctmp)
        cls.sup = cls.ctmp / 'game'
        git(cls.ctmp, 'init', '-q', str(cls.sup))
        write(cls.sup / 'g.txt', 'game\n')
        git(cls.sup, 'submodule', 'add', '-q', url(core), 'core')
        git(cls.sup, 'add', '-A')
        git(cls.sup, 'commit', '-q', '-m', 'game pins core v0.1.0')
        cls.wt = cls.ctmp / 'game-wt'
        git(cls.sup, 'worktree', 'add', '-q', '-b', 'wt', str(cls.wt))
        git(cls.wt, 'submodule', 'update', '--init', '-q')
        cls.hook_env = cls.record_pre_push_env()

    @classmethod
    def record_pre_push_env(cls):
        out = cls.ctmp / 'hook-env.txt'
        hooks = cls.ctmp / 'hooks'
        hook = write(hooks / 'pre-push', f'#!/bin/sh\nenv > "{out.as_posix()}"\n')
        hook.chmod(0o755)
        remote = cls.ctmp / 'remote.git'
        git(cls.ctmp, 'init', '-q', '--bare', str(remote))
        git(cls.wt, '-c', f'core.hooksPath={hooks.as_posix()}', 'push', '-q', url(remote), 'wt')
        lines = out.read_text(encoding='utf-8').splitlines()
        return dict(l.split('=', 1) for l in lines if l.startswith('GIT_') and '=' in l)

    def edit(self, path, text):
        old = path.read_bytes()
        self.addCleanup(path.write_bytes, old)
        write(path, text)

    def gate_in_hook(self):
        """The gate as the worktree's pre-push hook runs it: cwd the worktree, the hook's GIT_* variables set."""
        cwd = os.getcwd()
        os.chdir(self.wt)
        try:
            with mock.patch.dict(os.environ, self.hook_env):
                return run_gate(self.wt, self.wt / 'core', 'v0.1.0')
        finally:
            os.chdir(cwd)

    def test_hook_environment_selects_the_superproject(self):
        # what git exports to a pre-push hook in a linked worktree (recorded in the W11 report); without C12's git_env the gate reads it
        self.assertIn('GIT_DIR', self.hook_env, self.hook_env)
        with mock.patch.object(gates, 'git_env', lambda: dict(os.environ)):
            self.assertLevel(self.gate_in_hook(), 'error')

    def test_clean_core_is_ok(self):
        self.assertLevel(self.gate_in_hook(), 'ok', 'tag v0.1.0')

    def test_modified_core_in_the_worktree_fails(self):
        self.edit(self.wt / 'core' / 'a.txt', 'patched in place\n')
        self.assertLevel(self.gate_in_hook(), 'error', 'local changes', 'a.txt')

    def test_modified_superproject_is_not_the_core(self):
        self.edit(self.wt / 'g.txt', 'changed\n')
        self.edit(self.sup / 'g.txt', 'changed\n')
        self.assertLevel(self.gate_in_hook(), 'ok')


class ShallowSubmodule(Tmp):
    """B12: a depth-1 submodule (as CI checks it out) of a core with a newer tag brings that tag but not the pinned one."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        core = cls.make_core(cls.ctmp, ('0.1.0', '0.2.0'))
        cls.sup = cls.ctmp / 'game-src'
        git(cls.ctmp, 'init', '-q', str(cls.sup))
        git(cls.sup, 'submodule', 'add', '-q', url(core), 'core')
        git(cls.sup / 'core', 'checkout', '-q', 'v0.1.0')
        git(cls.sup, 'add', '-A')
        git(cls.sup, 'commit', '-q', '-m', 'game pins core v0.1.0')

    def setUp(self):
        super().setUp()
        self.game = self.tmp / 'game'
        git(self.tmp, 'clone', '-q', url(self.sup), str(self.game))
        git(self.game, 'submodule', 'update', '--init', '--depth', '1', '-q')
        self.core = self.game / 'core'

    def test_missing_pinned_tag_is_version_only(self):
        # the checkout napoleon's CI got (J41 review): shallow, HEAD at v0.1.0's commit, only the tip's tag v0.2.0 fetched
        self.assertEqual(git(self.core, 'rev-parse', '--is-shallow-repository'), 'true')
        self.assertEqual(git(self.core, 'tag', '--list').split(), ['v0.2.0'])
        self.assertEqual((self.core / 'VERSION').read_text().strip(), '0.1.0')
        self.assertLevel(run_gate(self.game, self.core, 'v0.1.0'), 'ok', 'pinned tag v0.1.0 not in this shallow checkout: VERSION only')
        self.assertLevel(run_gate(self.game, self.core, 'v0.2.0'), 'error', 'the core checkout is 0.1.0')   # VERSION is still compared

    def test_fetched_tag_is_checked_against_head(self):
        git(self.core, 'fetch', '-q', '--depth', '1', 'origin', 'tag', 'v0.1.0')
        self.assertLevel(run_gate(self.game, self.core, 'v0.1.0'), 'ok', 'tag v0.1.0')
        write(self.core / 'a.txt', 'b\n')
        git(self.core, 'commit', '-q', '-am', 'past the tag')
        self.assertLevel(run_gate(self.game, self.core, 'v0.1.0'), 'error', 'untagged commit')

    def test_full_clone_missing_the_pinned_tag_names_the_fix(self):
        git(self.core, 'fetch', '-q', '--unshallow')
        if 'v0.1.0' in git(self.core, 'tag', '--list').split():   # an unshallow fetch may follow the tag in
            git(self.core, 'tag', '-d', 'v0.1.0')
        self.assertEqual(git(self.core, 'rev-parse', '--is-shallow-repository'), 'false')
        self.assertLevel(run_gate(self.game, self.core, 'v0.1.0'), 'error', 'git -C core fetch --tags')


if __name__ == '__main__':
    unittest.main()
