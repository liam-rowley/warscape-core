"""The session-trailer rule (warscape/trailer.py), moved from napoleon-remastered tests/test_claude_hook.py (napoleon J62)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from warscape.trailer import commit_lacks_trailer, message_problem  # noqa: E402

SID = 'bc89f81a-9222-45d4-9010-6ec5f16df11f'


class Trailer(unittest.TestCase):
    def test_a_commit_without_the_flag_lacks_it(self):
        self.assertTrue(commit_lacks_trailer('git commit -m x', SID))
        self.assertTrue(commit_lacks_trailer('git -C /r commit -m x && git push', SID))
        self.assertTrue(commit_lacks_trailer('git -c core.hooksPath=/dev/null commit -q -m x', SID))

    def test_only_the_trailer_flag_counts_not_a_line_in_the_message(self):
        self.assertTrue(commit_lacks_trailer(f'git commit -m "x\n\nClaude-Session: {SID}"', SID))
        self.assertFalse(commit_lacks_trailer(f'git commit -m x --trailer "Claude-Session: {SID}"', SID))
        self.assertFalse(commit_lacks_trailer(f"git commit -m x --trailer 'Claude-Session: {SID}' --trailer 'Co-Authored-By: c'", SID))
        self.assertFalse(commit_lacks_trailer(f'git commit -m x --trailer=Claude-Session:{SID}', SID))

    def test_another_sessions_id_does_not_count(self):
        self.assertTrue(commit_lacks_trailer('git commit -m x --trailer "Claude-Session: other"', SID))
        self.assertTrue(commit_lacks_trailer(f'git commit -m x --trailer "Claude-Session: {SID}-2"', SID))

    def test_not_a_commit_no_session_or_the_rule_off(self):
        self.assertFalse(commit_lacks_trailer('git status', SID))
        self.assertFalse(commit_lacks_trailer('git commit-tree abc', SID))
        self.assertFalse(commit_lacks_trailer('echo git commit', ''))
        self.assertFalse(commit_lacks_trailer('git commit -m x', SID, ''))

    def test_a_game_may_name_its_own_trailer(self):
        self.assertFalse(commit_lacks_trailer(f'git commit -m x --trailer "Agent-Session: {SID}"', SID, 'Agent-Session'))
        self.assertTrue(commit_lacks_trailer(f'git commit -m x --trailer "Claude-Session: {SID}"', SID, 'Agent-Session'))


class GlobalOptions(unittest.TestCase):
    """W36 decision 2: a game's hook asks with the command as typed; git's global options and an alias defined in the command are seen."""
    OPTIONS = ('-c k=v', '-c "k=v w"', "-c 'k=v w'", '-C dir', '-C "a dir"', "-C 'a dir'", '-C $(pwd)', '--git-dir=p', '--git-dir="a p"', '--git-dir p',
               '--git-dir "a p"', '--work-tree=p', "--work-tree='a p'", '--work-tree p', '--namespace=n', '--namespace n', '--exec-path', '--exec-path=p',
               '--super-prefix=p', '--config-env=k=ENV', '--config-env k=ENV', '-p', '-P', '--paginate', '--no-pager', '--no-replace-objects', '--bare',
               '--literal-pathspecs', '--glob-pathspecs', '--noglob-pathspecs', '--icase-pathspecs', '--no-optional-locks')
    ALIASES = ('-c alias.ci=commit ci', '-c "alias.ci=commit -q" ci', '-c alias.ci="commit -q" ci', "-c 'alias.ci=commit --amend' ci", '-c alias.CI=commit ci',
               '-c alias.a=ci -c alias.ci=commit a', '-c "alias.ci=!git commit" ci', '-c "alias.ci=!cd x && git --no-pager commit" ci',
               '-c "alias.ci=--no-pager commit" ci', '--no-pager -c alias.ci=commit -C d ci')
    NOT_COMMITS = ('git status', 'git commit-tree abc', 'git commit-graph write', 'echo git commit', 'echo git --no-pager commit', 'git log --grep commit',
                   'git --no-pager log --grep commit', 'git -c alias.ci=status ci', 'git -c "alias.ci=status -s" ci', 'git -c alias.ci=commit status',
                   'git -c alias.a=b -c alias.b=a a', 'git config alias.ci commit', 'git help commit', 'git --help commit', 'git -C commit status',
                   'git --git-dir commit status', 'git -c x=y; commit -m x', 'git\ncommit -m x', 'agit commit', 'git-commit', './git commit', 'ls git commit',
                   'grep -r "git commit" docs', 'git log --grep "git commit"')

    def test_every_global_option_in_front_of_commit(self):
        for opt in self.OPTIONS:
            with self.subTest(opt):
                self.assertTrue(commit_lacks_trailer(f'git {opt} commit -m x', SID))
                self.assertTrue(commit_lacks_trailer(f'git.exe {opt} commit -m x', SID))
                self.assertFalse(commit_lacks_trailer(f'git {opt} commit -m x --trailer "Claude-Session: {SID}"', SID))
                self.assertFalse(commit_lacks_trailer(f'git {opt} status', SID))

    def test_several_options_together(self):
        self.assertTrue(commit_lacks_trailer('git --no-pager -c a=b -C "x y" --git-dir=.git -P commit -m x', SID))

    def test_an_alias_defined_in_the_command_is_a_commit(self):
        for cmd in self.ALIASES:
            with self.subTest(cmd):
                self.assertTrue(commit_lacks_trailer(f'git {cmd} -m x', SID))
                self.assertFalse(commit_lacks_trailer(f'git {cmd} -m x --trailer "Claude-Session: {SID}"', SID))

    def test_no_false_positives_with_a_real_session_id(self):
        for cmd in self.NOT_COMMITS:
            with self.subTest(cmd):
                self.assertFalse(commit_lacks_trailer(cmd, SID))

    def test_a_gitconfig_alias_cannot_be_known_from_the_command(self):
        self.assertFalse(commit_lacks_trailer('git ci -m x', SID))

    def test_git_at_the_start_of_any_command_in_the_line(self):
        for cmd in ('cd x && git commit -m y', 'cd x; git commit -m y', 'a || git commit', 'a | git commit', '(git commit -m y)', '$(git commit -m y)', '`git commit`',
                    '{ git commit; }', 'a\ngit commit', 'if git commit; then b; fi', 'while true; do git commit; done', 'A=1 git commit', 'A="b c" B=2 git commit',
                    'sudo git commit', 'env git commit', 'command git commit', 'exec git commit', 'time git commit', 'nohup git commit', '! git commit',
                    '& git commit -m y', 'git status && git --no-pager commit -m y', 'git commit&&git push', 'C:\\Git\\cmd\\git.exe commit -m y'):
            with self.subTest(cmd):
                self.assertTrue(commit_lacks_trailer(cmd, SID))

    def test_a_shell_started_with_a_command_string(self):
        for cmd in ('bash -c "git commit -m y"', "sh -c 'git --no-pager commit -m y'", 'bash -lc "cd x && git commit"', 'cmd /c git commit -m y', 'eval "git commit"',
                    'powershell -Command "git commit -m y"', 'pwsh -c "git -C d commit"'):
            with self.subTest(cmd):
                self.assertTrue(commit_lacks_trailer(cmd, SID))


if __name__ == '__main__':
    unittest.main()


CO = 'Co-Authored-By: Claude <noreply@anthropic.com>'


class MessageRule(unittest.TestCase):
    """B10: the commit-msg rule, a message read as git reads it (`git interpret-trailers --parse`)."""

    def test_the_trailer_in_the_last_paragraph_passes(self):
        self.assertIsNone(message_problem(f'subject\n\nbody\n\nClaude-Session: {SID}\n{CO}\n'))
        self.assertIsNone(message_problem(f'subject\n\nClaude-Session: {SID}\n'))
        self.assertIsNone(message_problem(f'subject\n\nclaude-session: {SID}\n'))   # a trailer key is case-insensitive, as in the policy

    def test_napoleon_j44s_shape_is_refused(self):
        """The session line one paragraph above Co-Authored-By: git reads no Claude-Session trailer there."""
        p = message_problem(f'subject\n\nClaude-Session: {SID}\n\n{CO}\n')
        self.assertIn('`Claude-Session:`', p)
        self.assertIn('last paragraph', p)
        self.assertIn('git commit --trailer "Claude-Session: <session id>"', p)
        self.assertIn('--no-verify', p)

    def test_a_missing_or_empty_value_is_refused(self):
        self.assertIsNotNone(message_problem('subject\n'))
        self.assertIsNotNone(message_problem(f'subject\n\n{CO}\n'))
        self.assertIn('value is empty', message_problem(f'subject\n\nClaude-Session:\n{CO}\n'))
        self.assertIsNotNone(message_problem('subject\n\nClaude-Session:   \n'))

    def test_editor_comment_lines_do_not_hide_or_make_a_trailer(self):
        tail = "\n# Please enter the commit message for your changes. Lines starting\n# with '#' will be ignored.\n#\n# On branch x\n"
        self.assertIsNone(message_problem(f'subject\n\nClaude-Session: {SID}\n{CO}\n{tail}'))
        self.assertIsNotNone(message_problem(f'subject\n\n{CO}\n{tail}'))
        self.assertIsNotNone(message_problem(f'subject\n\n# Claude-Session: {SID}\n'))   # a commented line is no trailer

    def test_no_trailer_name_switches_the_rule_off(self):
        self.assertIsNone(message_problem('subject\n', ''))

    def test_it_agrees_with_the_policys_reading_of_the_commit(self):
        """Kill criterion of W12: the hook may never accept what `policy` refuses or the reverse. The policy reads `%(trailers:key=...)` of the commit."""
        msgs = [f'a\n\nClaude-Session: {SID}\n{CO}\n', f'a\n\nClaude-Session: {SID}\n\n{CO}\n', f'a\n\n{CO}\n', 'a\n',
                'a\n\nClaude-Session:\n', f'a\n\nbody Claude-Session: {SID}\n', f'a\n\nClaude-Session: {SID}\nnot a trailer line\n',
                f'a\n\nclaude-session: {SID}\n', f'a: b\n\nClaude-Session: {SID}', f'Claude-Session: {SID}\n', f'a\n\n  Claude-Session: {SID}\n']
        with tempfile.TemporaryDirectory() as t:
            env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
            g = lambda *a, **k: subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', t, *a], env=env, capture_output=True, text=True, check=True, **k)
            g('init', '-q')
            for m in msgs:
                g('commit', '-q', '--allow-empty', '--cleanup=verbatim', '-F', '-', input=m)
                seen = g('log', '-1', '--format=%(trailers:key=Claude-Session,valueonly,separator=%x1f)').stdout.strip()
                self.assertEqual(message_problem(m) is None, bool(seen), m)


@unittest.skipUnless(shutil.which('sh'), 'no sh on PATH to run the git hook')
class Hook(unittest.TestCase):
    """The hook end to end: a throwaway repo whose core.hooksPath is this repo's .githooks."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls._tmp.name) / 'r'
        cls.d.mkdir()
        (cls.d / 'wsc.py').write_text(f"import runpy, sys\nsys.argv[0] = {str(ROOT / 'wsc.py')!r}\nrunpy.run_path(sys.argv[0], run_name='__main__')\n", encoding='utf-8')
        cls.env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
        cls.git('init', '-q', '-b', 'main')
        cls.git('config', 'core.hooksPath', (ROOT / '.githooks').as_posix())
        cls.git('config', 'commit.gpgsign', 'false')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def git(cls, *a, check=True):
        return subprocess.run(['git', '-C', str(cls.d), *a], env=cls.env, capture_output=True, text=True, check=check)

    def toml(self, body):
        (self.d / 'wsc.toml').write_text(body, encoding='utf-8', newline='\n')

    def test_opt_in_refuses_then_a_trailer_passes_and_a_merge_is_exempt(self):
        self.toml('[policy]\ncommit_msg_hook = true\n')
        before = self.git('rev-parse', '-q', '--verify', 'HEAD', check=False).stdout
        p = self.git('commit', '--allow-empty', '-m', 'x', check=False)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn('no `Claude-Session:` trailer', p.stderr)
        self.assertEqual(self.git('rev-parse', '-q', '--verify', 'HEAD', check=False).stdout, before)   # nothing was committed
        self.git('commit', '--allow-empty', '-m', 'x', '--trailer', 'Claude-Session: t')
        self.git('checkout', '-q', '-b', 'side')
        self.git('commit', '--allow-empty', '-m', 'side', '--trailer', 'Claude-Session: t')
        self.git('checkout', '-q', 'main')
        self.git('commit', '--allow-empty', '-m', 'main', '--trailer', 'Claude-Session: t')
        m = self.git('merge', '--no-ff', '-m', 'Merge side', 'side', check=False)   # git's own message, no trailer
        self.assertEqual(m.returncode, 0, m.stdout + m.stderr)

    def test_no_opt_in_and_an_empty_trailer_name_pass_silently(self):
        self.toml('[policy]\ncommit_msg_hook = false\n')
        self.git('commit', '-q', '--allow-empty', '-m', 'no opt-in')
        self.toml('[policy]\ncommit_msg_hook = true\nsession_trailer = ""\n')
        self.git('commit', '-q', '--allow-empty', '-m', 'rule off')
        self.toml('[policy]\ncommit_msg_hook = true\n')
        self.assertEqual(self.git('commit', '-q', '--allow-empty', '-m', 'bypass', '--no-verify', check=False).returncode, 0)
