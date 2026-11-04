"""Host tests for `wsc agent-settings` (W35): one allowed command rule added to `.claude/settings.json` only when it is a configured safe
pattern (or narrower), not under a deny rule and not broader than its pattern; key order and indentation kept; an atomic replace; the
old file kept as settings.json.bak once per run; `remove`; deny entries and hooks never touched; unconfigured repos refused. Temporary
folders only: no test reads or writes a real settings file."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from warscape.cli import main  # noqa: E402
from warscape.verbs import agent_settings  # noqa: E402

TOML = '''registries_dir = "registries"

[agent_settings]
safe = ["Bash(git status:*)", "Bash(git diff:*)", "Bash(python3 wsc.py find:*)", "Bash(git push --dry-run:*)", "PowerShell(git log:*)"]
'''
SETTINGS = {'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'python3 tools/hook.py'}]}]},
            'permissions': {'deny': ['Bash(git push:*)', 'Edit(//c/game/**)'], 'allow': ['Bash(git log:*)']},
            'zeta': 1}


class AgentSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        (self.t / 'wsc.toml').write_text(TOML)
        (self.t / '.claude').mkdir()
        self.f = self.t / '.claude' / 'settings.json'
        self.write(SETTINGS)
        self.real_replace = agent_settings._replace

    def tearDown(self):
        agent_settings._replace = self.real_replace
        self.tmp.cleanup()

    def write(self, d, indent=2):
        self.f.write_text(json.dumps(d, indent=indent) + '\n', encoding='utf-8')

    def wsc(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(['--root', str(self.t), 'agent-settings', *args])
        return rc, out.getvalue(), err.getvalue()

    def test_allows_a_safe_rule_and_keeps_order_indent_and_a_bak(self):
        before = self.f.read_text()
        rc, out, err = self.wsc('allow', 'Bash(git status:*)')
        self.assertEqual(rc, 0, out + err)
        d = json.loads(self.f.read_text())
        self.assertEqual(list(d), ['hooks', 'permissions', 'zeta'])
        self.assertEqual(list(d['permissions']), ['deny', 'allow'])
        self.assertEqual(d['permissions']['allow'], ['Bash(git log:*)', 'Bash(git status:*)'])
        self.assertEqual(d['hooks'], SETTINGS['hooks'])
        self.assertEqual(d['permissions']['deny'], SETTINGS['permissions']['deny'])
        self.assertEqual(self.f.read_text(), json.dumps(d, indent=2) + '\n')
        self.assertEqual((self.t / '.claude' / 'settings.json.bak').read_text(), before)

    def test_a_narrower_rule_and_an_exact_command(self):
        self.assertEqual(self.wsc('allow', 'Bash(git diff --stat:*)')[0], 0)
        self.assertEqual(self.wsc('allow', 'Bash(git diff HEAD)')[0], 0)
        self.assertIn('Bash(git diff HEAD)', json.loads(self.f.read_text())['permissions']['allow'])

    def test_indentation_four_is_kept(self):
        self.write(SETTINGS, indent=4)
        self.assertEqual(self.wsc('allow', 'Bash(git status:*)')[0], 0)
        self.assertEqual(self.f.read_text(), json.dumps(json.loads(self.f.read_text()), indent=4) + '\n')

    def test_broad_and_unsafe_rules_refuse_and_say_liam_decides(self):
        before = self.f.read_text()
        for rule in ('Bash(*)', 'Bash(git:*)', 'PowerShell(*)', 'Bash', 'Bash(git status; rm -rf /:*)', 'Bash(git st*)',
                     'Bash(rm -rf:*)', 'Edit(**)', 'Bash(git status && curl x:*)'):
            rc, _, err = self.wsc('allow', rule)
            self.assertEqual(rc, 2, rule)
            self.assertIn('Liam decides', err, rule)
        self.assertEqual(self.f.read_text(), before)
        self.assertFalse((self.t / '.claude' / 'settings.json.bak').exists())

    def test_a_rule_under_a_deny_refuses(self):
        rc, _, err = self.wsc('allow', 'Bash(git push --dry-run:*)')
        self.assertEqual(rc, 2)
        self.assertIn('Bash(git push:*)', err)

    def test_an_unconfigured_repo_does_nothing(self):
        (self.t / 'wsc.toml').write_text('registries_dir = "registries"\n')
        before = self.f.read_text()
        rc, _, err = self.wsc('allow', 'Bash(git status:*)')
        self.assertEqual(rc, 2)
        self.assertIn('not configured', err)
        self.assertEqual(self.f.read_text(), before)

    def test_a_failing_write_leaves_the_file(self):
        before = self.f.read_text()

        def boom(a, b):
            raise OSError('disk full')
        agent_settings._replace = boom
        rc, _, err = self.wsc('allow', 'Bash(git status:*)')
        self.assertEqual(rc, 1)
        self.assertIn('disk full', err)
        self.assertEqual(self.f.read_text(), before)
        self.assertEqual(sorted(p.name for p in (self.t / '.claude').iterdir() if not p.name.endswith('.bak')), ['settings.json'])

    def test_bak_is_written_once_per_run(self):
        before = self.f.read_text()
        rc, _, _ = self.wsc('allow', 'Bash(git status:*)', 'Bash(git diff:*)')
        self.assertEqual(rc, 0)
        self.assertEqual((self.t / '.claude' / 'settings.json.bak').read_text(), before)
        self.assertEqual(json.loads(self.f.read_text())['permissions']['allow'], ['Bash(git log:*)', 'Bash(git status:*)', 'Bash(git diff:*)'])

    def test_one_refused_rule_refuses_the_run(self):
        before = self.f.read_text()
        rc, _, _ = self.wsc('allow', 'Bash(git status:*)', 'Bash(*)')
        self.assertEqual(rc, 2)
        self.assertEqual(self.f.read_text(), before)

    def test_already_allowed_is_a_no_op(self):
        before = self.f.read_text()
        self.assertEqual(self.wsc('allow', 'PowerShell(git log:*)')[0], 0)
        mid = self.f.read_text()
        self.assertNotEqual(mid, before)
        rc, out, _ = self.wsc('allow', 'PowerShell(git log:*)')
        self.assertEqual(rc, 0)
        self.assertIn('already', out)
        self.assertEqual(self.f.read_text(), mid)

    def test_remove(self):
        rc, _, _ = self.wsc('remove', 'Bash(git log:*)')
        self.assertEqual(rc, 0)
        d = json.loads(self.f.read_text())
        self.assertEqual(d['permissions']['allow'], [])
        self.assertEqual(d['permissions']['deny'], SETTINGS['permissions']['deny'])

    def test_remove_never_touches_deny(self):
        before = self.f.read_text()
        rc, _, err = self.wsc('remove', 'Bash(git push:*)')
        self.assertEqual(rc, 2)
        self.assertIn('deny', err)
        self.assertEqual(self.f.read_text(), before)

    def test_never_outside_dot_claude_or_into_a_bad_file(self):
        other = self.t / 'settings.json'
        other.write_text(json.dumps(SETTINGS))
        rc, _, err = self.wsc('allow', 'Bash(git status:*)', '--file', str(other))
        self.assertEqual(rc, 2)
        self.assertIn('.claude', err)
        self.f.write_text('{not json')
        rc, _, err = self.wsc('allow', 'Bash(git status:*)')
        self.assertEqual(rc, 2)
        self.assertIn('not valid JSON', err)

    # Review round 1 (W35): each refusal the review reproduced, proved before the fix.
    def assertRefused(self, *args, contains=''):
        before = self.f.read_bytes() if self.f.exists() else None
        rc, out, err = self.wsc(*args)
        self.assertEqual(rc, 2, f'{args}: {out}{err}')
        self.assertIn('Liam decides', err)
        self.assertIn(contains, err, args)
        if before is not None:
            self.assertEqual(self.f.read_bytes(), before, args)
        return err

    def test_a_prefix_covers_whole_words_only(self):
        for rule in ('Bash(git diffx:*)', 'Bash(git diffx)', 'Bash(git statusfoo)', 'Bash(python3 wsc.py findx:*)'):
            self.assertRefused('allow', rule, contains='whole words')
        self.assertEqual(self.wsc('allow', 'Bash(git diff --cached:*)')[0], 0)

    def test_a_write_or_run_flag_in_the_added_words_refuses(self):
        for rule in ('Bash(git diff --output=C:/x/y:*)', 'Bash(git diff --output /tmp/y)', 'Bash(git diff --ext-diff:*)',
                     'Bash(git diff --textconv:*)', 'Bash(git diff -c core.pager=x:*)', 'Bash(git diff -ccore.pager=x)',
                     'Bash(git diff --stat -o out.txt)', 'PowerShell(git log --output=x:*)', 'Bash(git diff --config-env=a=b:*)'):
            self.assertRefused('allow', rule, contains='writes a file or runs a program')
        self.assertFalse((self.t / '.claude' / 'settings.json.bak').exists())

    def test_exact_only_allows_only_the_patterns_themselves(self):
        (self.t / 'wsc.toml').write_text(TOML + 'exact_only = true\n')
        self.assertRefused('allow', 'Bash(git status --short:*)', contains='exact_only')
        self.assertEqual(self.wsc('allow', 'Bash(git status:*)')[0], 0)
        (self.t / 'wsc.toml').write_text(TOML + 'exact_only = "yes"\n')
        self.assertRefused('allow', 'Bash(git diff:*)', contains='true or false')

    def test_a_deny_with_a_wildcard_inside_is_read_broadly(self):
        d = json.loads(json.dumps(SETTINGS))
        d['permissions']['deny'].append('Bash(git * --force)')
        self.write(d)
        self.assertRefused('allow', 'Bash(git status:*)', contains='wildcard inside a deny')
        self.assertRefused('allow', 'Bash(git diff HEAD)', contains='Bash(git * --force)')
        self.assertEqual(self.wsc('allow', 'Bash(python3 wsc.py find:*)')[0], 0)   # another command: the deny does not reach it

    def test_a_dot_claude_outside_the_root_refuses(self):
        other = self.t / 'elsewhere' / '.claude'
        other.mkdir(parents=True)
        (other / 'settings.json').write_text(json.dumps(SETTINGS))
        before = (other / 'settings.json').read_bytes()
        self.assertRefused('allow', 'Bash(git status:*)', '--file', str(other / 'settings.json'), contains="repo's own .claude")
        self.assertRefused('allow', 'Bash(git status:*)', '--file', 'elsewhere/.claude/settings.json', contains="repo's own .claude")
        self.assertEqual((other / 'settings.json').read_bytes(), before)
        self.assertFalse((other / 'settings.json.bak').exists())

    def _dir_link(self, target, link):
        """A junction on Windows (no privilege needed, so this test always runs there), a symlink elsewhere."""
        if sys.platform == 'win32':
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        self.addCleanup(lambda: os.path.lexists(link) and (os.rmdir(link) if sys.platform == 'win32' else os.unlink(link)))

    def test_a_dot_claude_junction_or_symlink_refuses(self):
        out = self.t / 'out'
        out.mkdir()
        (out / 'settings.json').write_text(json.dumps(SETTINGS))
        before = (out / 'settings.json').read_bytes()
        for p in (self.t / '.claude').iterdir():
            p.unlink()
        (self.t / '.claude').rmdir()
        self._dir_link(out, self.t / '.claude')
        self.assertRefused('allow', 'Bash(git status:*)', contains='a link')
        self.assertEqual((out / 'settings.json').read_bytes(), before)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['settings.json'])

    def _symlink(self, target, link):
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as e:
            self.skipTest(f'no symlinks here ({e}); the junction and hard-link tests cover the realpath check')

    def test_a_symlinked_settings_file_refuses(self):
        out = self.t / 'out.json'
        out.write_text(json.dumps(SETTINGS))
        before = out.read_bytes()
        self.f.unlink()
        self._symlink(out, self.f)
        self.assertRefused('allow', 'Bash(git status:*)', contains='is a link')
        self.assertEqual(out.read_bytes(), before)

    def test_a_link_at_bak_refuses(self):
        out = self.t / 'victim.txt'
        out.write_text('keep me')
        self._symlink(out, self.t / '.claude' / 'settings.json.bak')
        self.assertRefused('allow', 'Bash(git status:*)', contains='settings.json.bak is a link')
        self.assertEqual(out.read_text(), 'keep me')

    def test_hard_links_refuse(self):
        out = self.t / 'twin.json'
        os.link(self.f, out)
        self.assertRefused('allow', 'Bash(git status:*)', contains='hard links')
        out.unlink()
        victim = self.t / 'victim.txt'
        victim.write_text('keep me')
        os.link(victim, self.t / '.claude' / 'settings.json.bak')
        self.assertRefused('allow', 'Bash(git status:*)', contains='settings.json.bak has 2 hard links')
        self.assertEqual(victim.read_text(), 'keep me')

    def test_crlf_is_kept_and_bak_holds_the_bytes(self):
        raw = (json.dumps(SETTINGS, indent=2) + '\n').replace('\n', '\r\n').encode()
        self.f.write_bytes(raw)
        self.assertEqual(self.wsc('allow', 'Bash(git status:*)')[0], 0)
        new = self.f.read_bytes()
        self.assertIn(b'\r\n', new)
        self.assertNotIn(b'\n', new.replace(b'\r\n', b''))
        self.assertEqual((self.t / '.claude' / 'settings.json.bak').read_bytes(), raw)

    def test_a_missing_file_is_created_with_the_rule(self):
        self.f.unlink()
        rc, _, _ = self.wsc('allow', 'Bash(git status:*)')
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(self.f.read_text()), {'permissions': {'allow': ['Bash(git status:*)']}})


if __name__ == '__main__':
    unittest.main()
