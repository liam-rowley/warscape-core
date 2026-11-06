"""Host tests for harness/acceptance.py (J4): the baseline schema (rule 74), the comparisons, the ledger streak (rule 79), one pass against
fakes (stops at the first failure, fails on a refused verb, checks the exe pin and the settings files), and the refusal to run without a baseline.

Ported from the first consumer's `tests/test_acceptance.py` at 6cbb9e9 (B17); only the paths changed: `main` finds its harness adapter in
the null game (proxy/tests/null_game). No game: fakes play ctl and the PC."""
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('acceptance', ROOT / 'harness' / 'acceptance.py')
acc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acc)
NULL_GAME = ROOT / 'proxy' / 'tests' / 'null_game'   # main() reads its harness adapter


def baseline():
    steps = [{'scenario': f'{k}_x', 'kind': k, 'pose': 'wide', 'load_time_s': 20.0, 'load_tolerance_pct': 50, 'shot': f'{k}.jpg', 'shot_threshold': 4.0,
              'deterministic': True} for k in acc.KINDS]
    return {'schema': 1, 'date': '2026-10-30', 'build_id': 'abc', 'fresh_boot': True, 'size': '1920x1080', 'exe_sha1': 'pin', 'steps': steps,
            'settings_files': ['prefs', 'keys']}


SHOT = os.path.join(tempfile.gettempdir(), 'wsc_test_acceptance_shot.jpg')   # a real file: run_pass hashes the shot where it lies (W9)
with open(SHOT, 'wb') as _f:
    _f.write(b'JPEG')


class FakeCtl:
    def __init__(self, fail=None, load_s=20.0):
        self.fail, self.load_s, self.calls = fail, load_s, []

    def run(self, verb, *args):
        self.calls.append((verb, args))
        if self.fail == verb:
            return {'status': 'refused', 'reason': f'{verb} refused', 'check': {}}
        return {'status': 'ok', 'reason': '', 'check': {'k': 1}, 'load_s': self.load_s, **({'shot': SHOT} if verb == 'shot' else {})}


def env(ctl, exe='pin', settings_after=None):
    seq = [{'prefs': 'a', 'keys': 'b'}, settings_after or {'prefs': 'a', 'keys': 'b'}]
    log = []
    return {'exe_sha1': lambda: exe, 'settings': lambda: seq.pop(0), 'launch': lambda s: log.append(('launch', s)), 'exit': lambda: log.append('exit'),
            'relaunch': lambda s: log.append(('relaunch', s)), 'ctl': ctl, 'shot_diff': lambda s, r: 1.0, 'log': log}


class Baseline(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(acc, 'ROOT', NULL_GAME)
        p.start()
        self.addCleanup(p.stop)

    def test_valid(self):
        self.assertEqual(acc.baseline_problems(baseline()), [])

    def test_rule74_missing_pieces_are_named(self):
        b = baseline(); del b['exe_sha1']
        self.assertIn('baseline lacks "exe_sha1"', acc.baseline_problems(b))
        b = baseline(); b['steps'] = [s for s in b['steps'] if s['kind'] != 'naval']
        self.assertTrue(any('missing: naval' in e for e in acc.baseline_problems(b)))
        b = baseline(); b['fresh_boot'] = 'yes'
        self.assertTrue(any('fresh_boot' in e for e in acc.baseline_problems(b)))

    def test_a_non_deterministic_step_says_why(self):
        b = baseline(); b['steps'][0]['deterministic'] = False
        self.assertTrue(any('says why' in e for e in acc.baseline_problems(b)))
        b['steps'][0]['why_not'] = 'random rain'
        self.assertEqual(acc.baseline_problems(b), [])

    def test_rule74_run_refuses_without_a_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as e:
                acc.main(['run', '--run', 't', '--baseline', str(Path(d) / 'none.json'), '--ledger', str(Path(d) / 'l.jsonl')])
            self.assertIn('rule 74', str(e.exception))

    def test_run_refuses_an_invalid_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'b.json'; p.write_text('{"schema": 1}')
            with self.assertRaises(SystemExit) as e:
                acc.main(['run', '--run', 't', '--baseline', str(p)])
            self.assertIn('invalid', str(e.exception))


class RunPreflight(unittest.TestCase):
    """J45: a run checks its setup before pass 1 instead of spending a failed ledger line on it (run 20261031_j45acc)."""
    def a(self, branch=''):
        import types
        return types.SimpleNamespace(branch=branch)

    def test_failing_fixture_a_missing_pillow_is_refused_before_pass_1(self):
        bad = acc.run_problems(self.a('job/J9'), has_pil=False)
        self.assertEqual(len(bad), 1)
        self.assertIn('Pillow', bad[0])

    def test_failing_fixture_no_branch_is_refused(self):
        self.assertIn('no branch', acc.run_problems(self.a(), branch_of=lambda: 'HEAD', has_pil=True)[0])

    def test_the_branch_defaults_to_the_checkout(self):
        a = self.a()
        self.assertEqual(acc.run_problems(a, branch_of=lambda: 'job/J9', has_pil=True), [])
        self.assertEqual(a.branch, 'job/J9')
        self.assertEqual(acc.run_problems(self.a('job/J7'), branch_of=lambda: 'job/J9', has_pil=True), [])

    def test_failing_fixture_a_run_does_not_start_under_a_held_lock_or_an_active_profile(self):
        # J12 run 20261031_j12acc: pass 1 began under the sitting's own lock and headless overlay and failed settings_identical
        bad = acc.run_problems(self.a('job/J9'), has_pil=True, watcher_status={'lock': {'owner': 'j12'}, 'profile_active': 'headless'})
        self.assertEqual(len(bad), 2); self.assertIn('lock is held (j12)', bad[0]); self.assertIn('profile is active (headless)', bad[1])
        self.assertEqual(acc.run_problems(self.a('job/J9'), has_pil=True, watcher_status={'lock': None, 'profile_active': None}), [])


class Compare(unittest.TestCase):
    def test_load_time_tolerance(self):
        self.assertTrue(acc.load_time_ok(20, 29.9, 50)[0])
        self.assertFalse(acc.load_time_ok(20, 30.1, 50)[0])

    def test_settings_and_exe(self):
        self.assertTrue(acc.settings_unchanged({'a': 'x', 'b': None}, {'a': 'x', 'b': None})[0])
        ok, d = acc.settings_unchanged({'a': 'x'}, {'a': 'y', 'b': 'z'})
        self.assertFalse(ok); self.assertEqual(d['changed'], ['a', 'b'])
        self.assertFalse(acc.exe_pin_ok('aa', 'bb')[0])

    def test_shot_threshold(self):
        self.assertTrue(acc.shot_ok(3.9, 4.0)[0]); self.assertFalse(acc.shot_ok(4.1, 4.0)[0])


class Ledger(unittest.TestCase):
    def test_streak_ends_at_a_fail_or_another_build(self):
        L = lambda r, b='abc', w='1': {'result': r, 'build_id': b, 'watcher': w}
        self.assertEqual(acc.streak([L('pass')] * 3, 'abc', '1'), 3)
        self.assertEqual(acc.streak([L('pass'), L('fail'), L('pass'), L('pass')], 'abc', '1'), 2)
        self.assertEqual(acc.streak([L('pass')] * 5 + [L('pass', 'old')], 'abc', '1'), 0)
        self.assertEqual(acc.streak([], 'abc', '1'), 0)

    def test_line_shape(self):
        ln = acc.ledger_line(3, 'abc', '1.0.1', 'kit_x', True, {'a': 1}, 'job/J4')
        self.assertEqual((ln['pass'], ln['result'], ln['build_id']), (3, 'pass', 'abc'))
        self.assertEqual(json.loads(json.dumps(ln)), ln)


class OnePass(unittest.TestCase):
    def test_a_clean_pass(self):
        e = env(FakeCtl())
        ok, steps = acc.run_pass(baseline(), e)
        self.assertTrue(ok, steps)
        self.assertEqual(steps['settings_identical']['ok'], True)
        self.assertEqual([c[0] for c in e['ctl'].calls].count('scene'), 5)
        self.assertIn(('relaunch', '1920x1080'), e['log'])

    def test_a_wrong_exe_stops_before_launching(self):
        e = env(FakeCtl(), exe='other')
        ok, steps = acc.run_pass(baseline(), e)
        self.assertFalse(ok); self.assertEqual(list(steps), ['exe_sha1']); self.assertEqual(e['log'], [])

    def test_a_refused_camera_fails_the_pass_with_its_reason(self):
        e = env(FakeCtl(fail='cam'))
        ok, steps = acc.run_pass(baseline(), e)
        self.assertFalse(ok)
        self.assertEqual(steps[list(steps)[-1]]['reason'], 'cam refused')   # stopped at the first failure

    def test_a_slow_load_fails(self):
        ok, steps = acc.run_pass(baseline(), env(FakeCtl(load_s=40.0)))
        self.assertFalse(ok); self.assertFalse(steps['land_x:load']['ok'])

    def test_changed_settings_fail_the_pass(self):
        ok, steps = acc.run_pass(baseline(), env(FakeCtl(), settings_after={'prefs': 'CHANGED', 'keys': 'b'}))
        self.assertFalse(ok); self.assertEqual(steps['settings_identical']['changed'], ['prefs'])


class Identity(unittest.TestCase):
    """W10 (H2): the lock owner is the session. run/measure default --owner and --session to the session id and refuse without one, naming
    the fix; an explicit --owner still works; PcEnv passes the owner to `touch` (a bare touch is refused by job.sh)."""

    def run_main(self, argv, env):
        import os
        import contextlib
        import io
        seen = []

        class Stop(Exception):
            pass

        def pcenv(owner, session, *a, **k):
            seen.append((owner, session))
            raise Stop

        d = tempfile.mkdtemp()
        b = Path(d) / 'b.json'
        b.write_text(json.dumps(baseline()))
        err = io.StringIO()
        with mock.patch.dict(os.environ, dict(env, WSP_GAME_ROOT=str(NULL_GAME))), mock.patch.object(acc, 'ROOT', NULL_GAME), mock.patch.object(acc, 'run_problems', return_value=[]), mock.patch.object(acc, 'PcEnv', pcenv), \
                contextlib.redirect_stderr(err):
            for k in ('WSC_SESSION_ID', 'CLAUDE_CODE_SESSION_ID'):
                if k not in env:
                    os.environ.pop(k, None)
            try:
                rc = acc.main(['run', '--run', 't', '--branch', 'job/J9', '--baseline', str(b), '--ledger', str(Path(d) / 'l.jsonl'), *argv])
            except Stop:
                rc = 'started'
        return rc, seen, err.getvalue()

    def test_no_session_refuses_with_exit_2_and_names_the_fix(self):
        rc, seen, err = self.run_main([], {})
        self.assertEqual(rc, 2)
        self.assertEqual(seen, [])
        for word in ('--session', 'WSC_SESSION_ID', '--owner'):
            self.assertIn(word, err)

    def test_the_owner_and_session_default_to_the_session_id(self):
        self.assertEqual(self.run_main([], {'WSC_SESSION_ID': 'sess-a'})[:2], ('started', [('sess-a', 'sess-a')]))
        self.assertEqual(self.run_main(['--session', 'sess-b'], {})[:2], ('started', [('sess-b', 'sess-b')]))

    def test_an_explicit_owner_still_works(self):
        self.assertEqual(self.run_main(['--owner', 'claude-acceptance'], {'WSC_SESSION_ID': 'sess-a'})[:2], ('started', [('claude-acceptance', 'sess-a')]))
        self.assertEqual(self.run_main(['--owner', 'claude-acceptance'], {})[:2], ('started', [('claude-acceptance', 'claude-acceptance')]))

    def test_the_measure_command_refuses_without_a_session_too(self):
        import contextlib
        import io
        import os
        err = io.StringIO()
        with mock.patch.dict(os.environ, {'WSP_GAME_ROOT': str(NULL_GAME)}), mock.patch.object(acc, 'ROOT', NULL_GAME), contextlib.redirect_stderr(err):
            for k in ('WSC_SESSION_ID', 'CLAUDE_CODE_SESSION_ID'):
                os.environ.pop(k, None)
            self.assertEqual(acc.main(['measure', '--run', 't']), 2)
        self.assertIn('WSC_SESSION_ID', err.getvalue())

    def test_pcenv_passes_the_owner_to_touch_and_unlock(self):
        calls = []
        e = object.__new__(acc.PcEnv)
        e.owner, e.session, e.locked, e.sleep = 'o1', 's1', False, lambda s: None
        e.sh = lambda *a: (calls.append(a), (0, 'ok'))[1]
        e.pc = mock.Mock()
        e.pc.status.return_value = {'profile_active': None, 'lock': None}
        e.lock()
        e.lock()
        e.release()
        self.assertEqual(calls, [('lock', 'o1', 's1', 'acceptance pass'), ('touch', 'o1'), ('unlock', 'o1')])


if __name__ == '__main__':
    unittest.main()
