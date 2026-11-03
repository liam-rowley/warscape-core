"""Host tests for the Git Bash finder (`warscape/gitbash.py`, B18) and `harness/ctl.py` `bash()`, which uses it instead of loading a game's verb.

Ported from the first consumer's `tests/test_setup.py` (`test_bash_kind`, `test_bash_for_tests`) and `tests/test_proxy_host.py` (`GitBash`) at
6cbb9e9; the skip reason and the probed folders changed with the move (no game command in the reason, no `%LOCALAPPDATA%/Git` probe)."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from warscape import gitbash as gb  # noqa: E402

GIT = r'C:\Program Files\Git\usr\bin\bash.exe'
WSL = r'C:\Windows\System32\bash.exe'


def which_of(path):
    return lambda name: path if name == 'bash' else None


def load_ctl():
    spec = importlib.util.spec_from_file_location('ctl_for_gitbash_tests', ROOT / 'harness' / 'ctl.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class BashKind(unittest.TestCase):
    def test_bash_kind(self):
        self.assertEqual(gb.bash_kind(r'C:\Program Files\Git\usr\bin\bash.EXE', nt=True), 'git')
        self.assertEqual(gb.bash_kind(WSL, nt=True), 'wsl')
        self.assertEqual(gb.bash_kind(r'C:\Users\x\AppData\Local\Microsoft\WindowsApps\bash.exe', nt=True), 'wsl')
        self.assertEqual(gb.bash_kind(r'C:\msys64\usr\bin\bash.exe', nt=True), 'other')
        self.assertEqual(gb.bash_kind('/usr/bin/bash', nt=False), 'posix')
        self.assertIsNone(gb.bash_kind(None))


class GitBash(unittest.TestCase):
    def test_off_windows_is_bash_on_path(self):
        self.assertEqual(gb.git_bash(nt=False, which=which_of('/usr/bin/bash')), '/usr/bin/bash')

    def test_windows_git_bash_on_path(self):
        self.assertEqual(gb.git_bash(nt=True, which=which_of(GIT), git_exec_path=''), GIT)

    def test_windows_wsl_on_path_is_skipped_for_the_git_install(self):
        found = gb.git_bash(nt=True, which=which_of(WSL), git_exec_path='D:/Tools/Git/mingw64/libexec/git-core',
                            isfile=lambda p: p == r'D:\Tools\Git\bin\bash.exe', environ={})
        self.assertEqual(found, r'D:\Tools\Git\bin\bash.exe')

    def test_the_install_folders_and_never_localappdata_git(self):
        env = {'ProgramFiles': 'C:/PF', 'LOCALAPPDATA': 'C:/U/AppData/Local'}
        self.assertEqual(gb.roots('', env), ['C:/PF/Git', 'C:/U/AppData/Local/Programs/Git'])
        probed = []
        def isfile(p):
            probed.append(p)
            return p == r'C:\U\AppData\Local\Programs\Git\bin\bash.exe'
        self.assertEqual(gb.git_bash(nt=True, which=which_of(WSL), git_exec_path='', isfile=isfile, environ=env),
                         r'C:\U\AppData\Local\Programs\Git\bin\bash.exe')
        self.assertFalse([p for p in probed if p.startswith('C:\\U\\AppData\\Local\\Git\\')], probed)   # not an install folder
        self.assertEqual(gb.roots('', {}), [])   # no variables set: nothing relative is probed

    def test_windows_none(self):
        self.assertIsNone(gb.git_bash(nt=True, which=lambda n: None, git_exec_path='', isfile=lambda p: False, environ={}))
        self.assertIsNone(gb.git_bash(nt=True, which=which_of(WSL), git_exec_path='', isfile=lambda p: False, environ={}))   # never WSL

    def test_this_host(self):
        b = gb.git_bash()
        if os.name == 'nt' and b:
            self.assertEqual(gb.bash_kind(b), 'git', b)


class BashForTests(unittest.TestCase):
    def test_bash_for_tests(self):
        git = r'C:\Program Files\Git\bin\bash.exe'
        self.assertEqual(gb.bash_for_tests(nt=True, find=lambda nt: git), (git, None))
        b, why = gb.bash_for_tests(nt=True, find=lambda nt: None, environ={'ProgramFiles': 'C:/PF'})   # Windows, no Git Bash: a skip reason
        self.assertIsNone(b)
        self.assertIn('no Git Bash found (looked in: ', why)
        self.assertIn('C:/PF/Git/bin/bash.exe', why)
        self.assertIn('the WSL bash on PATH is never used', why)
        self.assertNotIn('wsc.py', why)   # names no game command
        self.assertEqual(gb.bash_for_tests(nt=False, find=lambda nt: None), ('bash', None))   # off Windows a missing bash fails later
        self.assertEqual(gb.bash_for_tests(nt=False, find=lambda nt: '/usr/bin/bash'), ('/usr/bin/bash', None))


class BashOrSkip(unittest.TestCase):
    class Case:
        def skipTest(self, why):
            raise unittest.SkipTest(why)

        def fail(self, why):
            raise AssertionError(why)

    def test_a_found_bash_is_returned(self):
        self.assertEqual(gb.bash_or_skip(self.Case(), found=('b', None), which=lambda n: 'py', environ={}), 'b')

    def test_no_bash_or_no_python3_skips(self):
        with self.assertRaisesRegex(unittest.SkipTest, 'no Git Bash'):
            gb.bash_or_skip(self.Case(), found=(None, 'no Git Bash found'), environ={})
        with self.assertRaisesRegex(unittest.SkipTest, 'python3'):
            gb.bash_or_skip(self.Case(), found=('b', None), which=lambda n: None, environ={})
        self.assertEqual(gb.bash_or_skip(self.Case(), python3=False, found=('b', None), which=lambda n: None, environ={}), 'b')

    def test_failing_fixture_the_required_bash_fails_instead_of_skipping(self):
        with self.assertRaisesRegex(AssertionError, 'WSC_REQUIRE_BASH is set: .*python3'):
            gb.bash_or_skip(self.Case(), found=('b', None), which=lambda n: None, environ={'WSC_REQUIRE_BASH': '1'})


class CtlBash(unittest.TestCase):
    """`ctl.bash()` takes the core's finder and opens nothing under the game root (B18: it loaded the game's tools/verbs/setup.py)."""
    def setUp(self):
        self.ctl = load_ctl()
        self.tmp = tempfile.TemporaryDirectory()
        self.game = Path(self.tmp.name) / 'game'
        self.game.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_failing_fixture_a_game_root_without_tools_still_gets_the_finders_bash(self):
        with mock.patch.object(self.ctl, 'ROOT', self.game), mock.patch.object(self.ctl, '_BASH', None), \
                mock.patch.object(gb, 'git_bash', lambda: 'found-bash'):
            self.assertEqual(self.ctl.bash(), 'found-bash')
        self.assertEqual(list(self.game.iterdir()), [])

    def test_a_games_setup_verb_is_never_loaded(self):
        marker = self.game / 'loaded'
        verb = self.game / 'tools' / 'verbs' / 'setup.py'
        verb.parent.mkdir(parents=True)
        verb.write_text(f'open({str(marker)!r}, "w").close()\ndef git_bash():\n    return "game-bash"\n')
        with mock.patch.object(self.ctl, 'ROOT', self.game), mock.patch.object(self.ctl, '_BASH', None), \
                mock.patch.object(gb, 'git_bash', lambda: 'found-bash'):
            self.assertEqual(self.ctl.bash(), 'found-bash')
        self.assertFalse(marker.exists())

    def test_nothing_found_is_plain_bash_and_the_answer_is_cached(self):
        calls = []
        def none():
            calls.append(1)
            return None
        with mock.patch.object(self.ctl, '_BASH', None), mock.patch.object(gb, 'git_bash', none):
            self.assertEqual(self.ctl.bash(), 'bash')
            self.assertEqual(self.ctl.bash(), 'bash')
        self.assertEqual(calls, [1])


if __name__ == '__main__':
    unittest.main()
