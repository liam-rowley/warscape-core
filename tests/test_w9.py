"""Host tests for W9: the build id read after the launch (B26, B31, H5), the launch retry's evidence and HeadlessLaunchLost (B60, H4), flake
classification and the streak, the pass file (schema 2) and its ledger line (H3), the watcher preflight (H10), the run-id refusal (H5) and staged
saves (B51). No game and no PC: fakes play the watcher and the proxy log."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'harness' / f'{name}.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ctl, acc = load('ctl'), load('acceptance')
NULL_GAME = ROOT / 'proxy' / 'tests' / 'null_game'
HEX = 'ab' * 32


def load_line(build, pid):
    return (f'2026-11-05T09:00:00.000Z [INFO ] [t1] launch x: Null proxy d3d9.dll build {build} loaded into C:\\g\\Null.exe (pid {pid}, base 00400000)\r\n'
            f'2026-11-05T09:00:00.020Z [INFO ] [t1] self_hash: sha256 {HEX} bytes 10 build {build} (hashed in 7 ms)\r\n')


class LaunchBuild(unittest.TestCase):
    """Decision 1: the build is read from this launch's own log line (pid-matched), never before the launch and never from the kit."""
    LOST1 = 'x\n[watcher] failed: HEADLESS FAILED: the game exited before reporting on_virtual (last status: starting DllMain)'
    LOST2 = 'HEADLESS FAILED: no on_virtual status for pid 31820 within 180 s (last: (no status yet)); the game was killed (fail closed)'

    def make(self, d, answers, write_log=None, pid=4242, with_install=True):
        d = Path(d)
        game, state = d / 'game', d / 'state'
        (game / 'nullmod' / 'logs').mkdir(parents=True)
        state.mkdir()
        (game / 'null.ini').write_text('[proxy]\nbackend=system\n', encoding='utf-8')
        (game / 'headless_status.json').write_text('{"state": "old"}', encoding='utf-8')
        if with_install:
            (state / 'install.json').write_text(json.dumps({'kit_id': 'kit_x', 'build_id': 'KITBUILD'}), encoding='utf-8')
        log = game / 'nullmod' / 'logs' / 'proxy.log'
        calls, order = [], []

        def sh(argv, stdin=None, timeout=None):
            calls.append((argv, stdin))
            if stdin and stdin.startswith('launch'):
                text, rc, out = answers.pop(0)
                order.append(('launch', {p.name: p.read_bytes() for p in (d / 'ev').glob('attempt_*/*')} if (d / 'ev').exists() else {}))
                if write_log:
                    log.write_text(write_log(len(order)), encoding='utf-8')
                if rc != 0:
                    log.write_text('2026-11-05 launch died\r\n', encoding='utf-8')
                    (game / 'headless_status.json').write_text('{"state": "starting DllMain"}', encoding='utf-8')
                return rc, out
            if 'status' in argv:
                return 0, json.dumps({'game_state': {'state': 'running', 'pid': pid}})
            if 'ctl' in argv:
                return 0, '{"status": "ok", "scene": "frontend"}'
            return 0, ''
        a = {'game': 'nullgame', 'game_dir': str(game), 'state_dir': str(state), 'headless': {'status_file': 'headless_status.json'},
             'ctl': {'launch': {'keys': {}, 'size': '1920x1080', 'retry_settle_s': 7}}}
        sleeps = []
        p = ctl.Pc('o', 'a.json', a, sh=sh, clock=lambda: 0.0, sleep=sleeps.append)
        p.ini_name = 'null.ini'
        p.missing_keys = lambda: {}
        p.evidence_dir = d / 'ev'
        return p, calls, order, sleeps, log

    def launch(self, p):
        with mock.patch.object(ctl, 'ident_mod', lambda a: 'nullmod'):
            return p.launch()

    def test_failing_fixture_a_stale_log_of_the_previous_launch_does_not_label_this_one(self):
        # B26/H5: the log on disk was the LAST launch's. This launch's process (pid 4242) never wrote one: no build, not the old 0aldbuild00001
        with tempfile.TemporaryDirectory() as d:
            p, *_, log = self.make(d, [(None, 0, 'started')])
            log.write_text(load_line('0aldbuild001', 99), encoding='utf-8')
            self.launch(p)
            self.assertIsNone(p.launches[0]['build'])
            with self.assertRaises(RuntimeError):
                p.build_info(strict=True)

    def test_a_fresh_install_gets_the_dlls_build_on_pass_1(self):
        # J8: no log before the launch and install.json carries only the kit's id; the DLL writes its line during the launch
        with tempfile.TemporaryDirectory() as d:
            p, *_ = self.make(d, [(None, 0, 'started')], write_log=lambda n: load_line('0123456789ab', 4242))
            self.launch(p)
            self.assertEqual(p.launches[0]['build'], '0123456789ab')
            self.assertEqual(p.launches[0]['dll_sha256_logged'], HEX)
            with mock.patch.object(ctl, 'ident_mod', lambda a: 'nullmod'):
                self.assertEqual(p.build_info(strict=True)['build'], '0123456789ab')
                self.assertEqual(p.build_info()['build'], '0123456789ab')

    def test_a_later_launch_is_its_own_entry(self):
        with tempfile.TemporaryDirectory() as d:
            p, *_ = self.make(d, [(None, 0, 'a'), (None, 0, 'b')], write_log=lambda n: load_line(f'build{n}', 4242))
            self.launch(p)
            self.launch(p)
            self.assertEqual([l['build'] for l in p.launches], ['build1', 'build2'])
            with mock.patch.object(ctl, 'ident_mod', lambda a: 'nullmod'):
                self.assertEqual(p.build_info(strict=True)['build'], 'build2')

    def test_the_non_strict_read_keeps_the_kit_fallback_for_perf_labels(self):
        with tempfile.TemporaryDirectory() as d:
            p, *_ = self.make(d, [])
            with mock.patch.object(ctl, 'ident_mod', lambda a: 'nullmod'):
                self.assertEqual(p.build_info()['build'], 'KITBUILD')

    def test_the_attempts_evidence_is_copied_before_the_retry_and_the_retry_settles(self):
        with tempfile.TemporaryDirectory() as d:
            p, calls, order, sleeps, log = self.make(d, [(None, 1, self.LOST1), (None, 0, 'ok')], write_log=lambda n: load_line('b', 4242))
            r = self.launch(p)
            self.assertEqual([a['rc'] for a in r['attempts']], [1, 0])
            self.assertIn('HEADLESS FAILED', r['retried_after'])
            # at the time the 2nd launch job ran, attempt 1's files were already in the evidence folder, with the first attempt's bytes
            seen = order[1][1]
            self.assertIn(b'launch died', seen['proxy.log'])
            self.assertIn(b'starting DllMain', seen['headless_status.json'])
            self.assertIn(b'DllMain', seen['job_output.txt'] + seen['headless_status.json'])
            self.assertEqual(sleeps.count(7), 1)

    def test_a_second_loss_raises_with_both_attempts_text(self):
        with tempfile.TemporaryDirectory() as d:
            p, *_ = self.make(d, [(1, 1, self.LOST1), (1, 1, self.LOST2)])
            with self.assertRaises(ctl.HeadlessLaunchLost) as e:
                self.launch(p)
            msg = str(e.exception)
            self.assertIn('starting DllMain', msg)
            self.assertIn('no on_virtual status for pid 31820', msg)
            self.assertEqual(e.exception.cause, 'headless_launch_lost')
            self.assertEqual(len(e.exception.attempts), 2)
            self.assertTrue((Path(d) / 'ev' / 'attempt_2' / 'proxy.log').exists())

    def test_the_proxy_refusing_twice_is_not_a_launch_loss(self):
        refused = 'HEADLESS FAILED: the proxy refused the launch: bad size (exit code 3)'
        with tempfile.TemporaryDirectory() as d:
            p, *_ = self.make(d, [(1, 1, refused), (1, 1, refused)])
            with self.assertRaises(RuntimeError) as e:
                self.launch(p)
            self.assertNotIsInstance(e.exception, ctl.HeadlessLaunchLost)

    def test_ctl_run_turns_the_loss_into_a_failed_result_with_the_cause(self):
        class Pc:
            launches = []

            def pid(self):
                return None

            def launch(self):
                raise ctl.HeadlessLaunchLost([{'rc': 1, 'tail': 'a'}, {'rc': 1, 'tail': 'b'}])
        rows = {'c': {'id': 'c', 'kind': 'campaign', 'map': 'm', 'save': 'campaign:new:x:y', 'launch': 'l', 'description': 'd'}}
        c = ctl.Ctl(lambda *a, **k: (0, {}), rows, {'ctl': {}}, battles_dir='.', pc=Pc())
        r = c.run('scene', 'c')
        self.assertEqual((r['status'], r['cause']), ('failed', 'headless_launch_lost'))
        self.assertIn('attempt 1 exit 1: a', r['reason'])
        self.assertIn('attempt 2 exit 1: b', r['reason'])


def steps_ok(**more):
    s = {'exe_sha1': {'ok': True}, 'launch': {'ok': True}}
    s.update(more)
    return s


LOST = {'ok': False, 'reason': 'x', 'cause': 'headless_launch_lost'}


class Flakes(unittest.TestCase):
    def test_a_clean_pass(self):
        self.assertEqual(acc.classify(True, steps_ok()), 'pass')

    def test_a_lost_launch_after_the_exe_pin_is_a_flake(self):
        self.assertEqual(acc.classify(False, steps_ok(**{'hist_nile:scene': LOST})), 'flake')
        self.assertEqual(acc.classify(False, steps_ok(relaunch=LOST)), 'flake')
        self.assertEqual(acc.classify(False, steps_ok(cleanup=LOST)), 'flake')   # the cleanup is a step; here the first failed one

    def test_what_is_never_a_flake(self):
        fail = {'ok': False, 'reason': 'x'}
        refused = {'ok': False, 'reason': 'HEADLESS FAILED: the proxy refused the launch'}
        for name, steps in {
            'proxy refused': steps_ok(launch=refused),
            'loss after a failed exe pin': {'exe_sha1': {'ok': False}, 'launch': LOST},
            'no exe step': {'launch': LOST},
            'load': steps_ok(**{'a:scene': {'ok': True}, 'a:load': fail}),
            'cam': steps_ok(**{'a:cam': fail}), 'shot': steps_ok(**{'a:shot': fail}), 'shot_match': steps_ok(**{'a:shot_match': fail}),
            'perf': steps_ok(perf=fail), 'frontend': steps_ok(launch={'ok': False, 'reason': 'step frontend: no answer'}),
            'settings': steps_ok(settings_identical=fail), 'lock': steps_ok(cleanup=fail), 'harness': steps_ok(harness=fail),
            'a real failure before the loss': steps_ok(**{'a:load': fail, 'relaunch': LOST}),
        }.items():
            self.assertEqual(acc.classify(False, steps), 'fail', name)

    def test_failing_fixture_a_streak_skips_a_flake_without_counting_it(self):
        P = lambda r='pass', b='abc', w='1': {'result': r, 'build_id': b, 'watcher': w}
        self.assertEqual(acc.streak([P()] * 19 + [P('flake')], 'abc', '1', max_flakes=1), 19)   # a flake is never the 20th pass
        self.assertEqual(acc.streak([P()] * 19 + [P('flake')], 'abc', '1'), 0)                  # no allowance: it ends the streak, as a fail does
        self.assertEqual(acc.streak([P()] * 5 + [P('flake')] + [P()] * 5, 'abc', '1', max_flakes=1), 10)
        self.assertEqual(acc.streak([P()] * 5 + [P('flake')] * 2 + [P()] * 5, 'abc', '1', max_flakes=1), 5)
        self.assertEqual(acc.streak([P()] * 5 + [P('flake')] * 2 + [P()] * 5, 'abc', '1', max_flakes=2), 10)
        self.assertEqual(acc.streak([P('flake')] + [P()] * 4, 'abc', '1', max_flakes=1), 4)     # as the first line
        self.assertEqual(acc.streak([P()] * 4 + [P('flake', None)], 'abc', '1', max_flakes=1), 4)  # a launch that died before the DLL logged a build
        self.assertEqual(acc.streak([P()] * 4 + [P('flake', 'other')], 'abc', '1', max_flakes=1), 0)
        self.assertEqual(acc.streak([P()] * 4 + [P('flake', w='2')], 'abc', '1', max_flakes=1), 0)

    def test_the_watcher_sha_is_the_watchers_identity_when_given(self):
        L = lambda sha: {'result': 'pass', 'build_id': 'abc', 'watcher': '1', 'watcher_sha': sha}
        self.assertEqual(acc.streak([L('s')] * 3, 'abc', '1', watcher_sha='s'), 3)
        self.assertEqual(acc.streak([L('s')] * 3 + [L('t')], 'abc', '1', watcher_sha='s'), 0)
        self.assertEqual(acc.streak([{'result': 'pass', 'build_id': 'abc', 'watcher': '1'}], 'abc', '1', watcher_sha='s'), 0)   # a line written before W9
        self.assertEqual(acc.streak([{'result': 'pass', 'build_id': 'abc', 'watcher': '1'}], 'abc', '1'), 1)

    def test_the_cap(self):
        ad = lambda n: {'acceptance': {'max_flakes': n}} if n is not None else {}
        self.assertEqual(acc.max_flakes_of(ad(None), None), (1, None))
        self.assertEqual(acc.max_flakes_of(ad(3), None), (3, None))
        self.assertEqual(acc.max_flakes_of(ad(3), 1), (1, None))
        self.assertIsNotNone(acc.max_flakes_of(ad(4), None)[1])
        self.assertIsNotNone(acc.max_flakes_of(ad(1), 2)[1])    # --max-flakes only lowers
        self.assertIsNotNone(acc.max_flakes_of(ad(-1), None)[1])


def baseline():
    steps = [{'scenario': f'{k}_x', 'kind': k, 'pose': 'wide', 'load_time_s': 20.0, 'load_tolerance_pct': 50, 'shot': f'{k}.jpg', 'shot_threshold': 4.0,
              'deterministic': True} for k in acc.KINDS]
    return {'schema': 1, 'date': '2026-10-30', 'build_id': 'abc', 'fresh_boot': True, 'size': '1920x1080', 'exe_sha1': 'pin', 'steps': steps, 'settings_files': []}


class RunLoop(unittest.TestCase):
    """cmd_run with a fake PcEnv and a scripted run_pass: attempts, flakes, the pass file's 'x' mode, the ledger line from the file's hash."""

    def run_cmd(self, outcomes, extra=(), ad_extra=None, preexisting=None):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(d, ignore_errors=True))
        repo, state = d / 'repo', d / 'state'
        (repo / 'harness' / 'runs').mkdir(parents=True)
        state.mkdir()
        b = d / 'b.json'
        b.write_text(json.dumps(baseline()))
        ad = json.loads((NULL_GAME / 'harness' / 'null' / 'adapter.json').read_text(encoding='utf-8')) if (NULL_GAME / 'harness' / 'null' / 'adapter.json').exists() else {}
        adp = d / 'adapter.json'
        adp.write_text(json.dumps(dict(ad, state_dir=str(state), **(ad_extra or {}))))
        led = d / 'ledger.jsonl'
        if preexisting:
            preexisting(repo, state, led)
        script = list(outcomes)

        class Env:
            def __init__(s, *a, **k):
                s.pc = mock.Mock()
                s.pc.missing_keys.return_value = {}
                s.pc.launches = []

            def as_env(s):
                return {}

            def exit(s): pass
            def release(s): pass

            def identity(s, strict=False):
                return 'abc', '1.0', 'kit_x'

            def evidence(s, bp, bs):
                return {'exe_sha1': 'pin', 'baseline_sha256': bs, 'kit_sha256': 'k' * 64, 'dll_sha256': HEX, 'dll_sha256_logged': None,
                        'watcher_sha256': 'w' * 64, 'watcher_kit_sha256': 'w' * 64, 'launches': [{'pid': 1, 'build': 'abc', 'dll_sha256_logged': None, 'utc': 'u'}]}

        def run_pass(bl, env):
            r = script.pop(0)
            return (r == 'pass'), (steps_ok() if r == 'pass' else steps_ok(**{'hist_nile:scene': LOST if r == 'flake' else {'ok': False, 'reason': 'nope'}}))
        out = io.StringIO()
        argv = ['run', '--run', 'r1', '--branch', 'job/W9', '--baseline', str(b), '--ledger', str(led), '--adapter', str(adp), '--owner', 'o', '--session', 's', *extra]
        with mock.patch.object(acc, 'ROOT', repo), mock.patch.object(acc.layout, 'harness_adapter', lambda root: adp), mock.patch.object(acc, 'PcEnv', Env), mock.patch.object(acc, 'run_pass', run_pass), \
                mock.patch.object(acc, 'installed_watcher_bytes', lambda a: b'w'), mock.patch.object(acc, 'kit_watcher_bytes', lambda: b'w'), \
                mock.patch.object(acc, 'run_problems', lambda *a, **k: []), contextlib.redirect_stdout(out):
            rc = acc.main(argv)
        lines = acc.read_ledger(led.read_text(encoding='utf-8')) if led.exists() else []
        return rc, lines, repo, out.getvalue()

    def test_three_passes_with_a_flake_in_the_middle(self):
        rc, lines, repo, out = self.run_cmd(['pass', 'flake', 'pass', 'pass'], ['--passes', '3'])
        self.assertEqual(rc, 0, out)
        self.assertEqual([l['result'] for l in lines], ['pass', 'flake', 'pass', 'pass'])
        self.assertEqual([l['pass'] for l in lines], [1, 2, 3, 4])
        self.assertEqual(acc.streak(lines, 'abc', '1.0', max_flakes=1), 4 - 1)
        self.assertTrue(all(l['flakes_allowed'] == 1 and l['schema'] == 2 for l in lines))

    def test_a_second_flake_ends_the_run_and_a_fail_stops_it(self):
        rc, lines, _, out = self.run_cmd(['pass', 'flake', 'flake'], ['--passes', '3'])
        self.assertEqual((rc, [l['result'] for l in lines]), (1, ['pass', 'flake', 'flake']))
        self.assertIn('allowance is spent', out)
        rc, lines, _, out = self.run_cmd(['pass', 'fail'], ['--passes', '3'])
        self.assertEqual((rc, lines[-1]['result']), (1, 'fail'))
        self.assertIn('first failure', out)

    def test_the_line_is_tied_to_its_file_by_hash_and_check_pass_agrees(self):
        rc, lines, repo, _ = self.run_cmd(['pass'], ['--passes', '1'])
        pf = repo / lines[0]['evidence']
        doc = json.loads(pf.read_text(encoding='utf-8'))
        self.assertEqual(acc.pass_problems(doc), [])
        self.assertEqual(acc.ledger_line_matches(lines[0], doc, acc.sha(pf)), [])
        self.assertEqual(lines[0]['evidence_sha256'], acc.sha(pf))
        self.assertEqual(doc['evidence']['baseline_sha256'], acc.sha(repo.parent / 'b.json'))

    def test_a_pass_file_is_never_overwritten(self):
        rc, lines, repo, _ = self.run_cmd(['pass'], ['--passes', '1'])
        with self.assertRaises(FileExistsError):
            open(repo / lines[0]['evidence'], 'x')

    def test_max_flakes_may_only_lower_the_adapters_allowance(self):
        rc, lines, _, _ = self.run_cmd(['pass', 'flake'], ['--passes', '2', '--max-flakes', '0'])
        self.assertEqual((rc, [l['result'] for l in lines]), (1, ['pass', 'flake']))
        rc, lines, _, _ = self.run_cmd([], ['--passes', '1', '--max-flakes', '2'])
        self.assertEqual((rc, lines), (2, []))

    def test_a_run_id_with_evidence_is_refused_in_three_ways(self):
        def pass_file(repo, state, led):
            (repo / 'harness' / 'runs' / 'r1').mkdir(parents=True)
            (repo / 'harness' / 'runs' / 'r1' / 'pass_01.json').write_text('{}')

        def ledger_line(repo, state, led):
            led.write_text(json.dumps({'run': 'harness/runs/r1', 'result': 'pass'}) + '\n')

        def state_folder(repo, state, led):
            (state / 'acceptance' / 'r1' / 'pass_01').mkdir(parents=True)
        for pre in (pass_file, ledger_line, state_folder):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc, lines, repo, _ = self.run_cmd(['pass'], ['--passes', '1'], preexisting=pre)
            self.assertEqual(rc, 2, pre.__name__)
            self.assertIn('fresh --run id', err.getvalue())


class RunPassEvidence(unittest.TestCase):
    def env(self, launches, dll=HEX, lost_on=None):
        class C:
            def run(s, verb, *a):
                return {'status': 'ok', 'reason': '', 'check': {'k': 1}, 'load_s': 1.0}
        seq = [{}, {}]

        def start(n):
            def f(size):
                if lost_on == n:
                    e = RuntimeError('lost')
                    e.cause = 'headless_launch_lost'
                    raise e
            return f
        return {'exe_sha1': lambda: 'pin', 'settings': lambda: seq.pop(0), 'launch': start('launch'), 'exit': lambda: None, 'relaunch': start('relaunch'),
                'ctl': C(), 'shot_diff': lambda s, r: 1.0, 'launches': lambda: launches, 'dll_sha256': lambda: dll}

    def L(self, build, logged=None):
        return {'pid': 1, 'build': build, 'dll_sha256_logged': logged, 'utc': 'u'}

    def test_a_stable_build_passes(self):
        ok, steps = acc.run_pass(baseline(), self.env([self.L('a'), self.L('a')]))
        self.assertTrue(ok, steps)
        self.assertTrue(steps['build_stable']['ok'] and steps['dll_hash']['ok'])

    def test_a_build_that_changes_inside_a_pass_fails_it(self):
        ok, steps = acc.run_pass(baseline(), self.env([self.L('a'), self.L('b')]))
        self.assertFalse(ok)
        self.assertFalse(steps['build_stable']['ok'])

    def test_no_launch_line_cannot_pass(self):
        ok, steps = acc.run_pass(baseline(), self.env([self.L(None)]))
        self.assertFalse(ok)
        self.assertFalse(steps['build_stable']['ok'])

    def test_a_dll_that_changed_under_the_run_fails_it(self):
        ok, steps = acc.run_pass(baseline(), self.env([self.L('a', 'c' * 64)]))
        self.assertFalse(steps['dll_hash']['ok'])
        self.assertFalse(ok)

    def test_a_lost_relaunch_is_a_flake_through_the_whole_chain(self):
        ok, steps = acc.run_pass(baseline(), self.env([self.L('a')], lost_on='relaunch'))
        self.assertFalse(ok)
        self.assertEqual(steps['relaunch']['cause'], 'headless_launch_lost')
        self.assertEqual(acc.classify(ok, steps), 'flake')

    def test_a_shot_step_records_its_sha256_and_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 's.jpg'
            f.write_bytes(b'jpegbytes')

            class C:
                def run(s, verb, *a):
                    return {'status': 'ok', 'reason': '', 'check': {'k': 1}, 'load_s': 1.0, 'shot': str(f)}
            e = self.env([self.L('a')])
            e['ctl'] = C()
            ok, steps = acc.run_pass(baseline(), e)
            v = steps['land_x:shot']
            self.assertEqual((v['sha256'], v['bytes']), (acc.hashlib.sha256(b'jpegbytes').hexdigest(), 9))
            self.assertIn('land_x', acc.shots_evidence(steps, baseline(), d) or {'land_x': 1})


def good_doc():
    return {'schema': 2, 'pass': 1, 'start_utc': 'a', 'end_utc': 'b', 'result': 'pass', 'passed': True, 'build_id': 'abc', 'build_source': 'proxy.log',
            'watcher': '1.0', 'kit': 'k', 'steps': {'exe_sha1': {'ok': True}},
            'evidence': {'exe_sha1': 'p', 'baseline_sha256': HEX, 'shots': {'land_x': {'sha256': HEX, 'bytes': 3}}, 'kit_sha256': HEX, 'dll_sha256': HEX,
                         'dll_sha256_logged': None, 'watcher_sha256': HEX, 'watcher_kit_sha256': HEX,
                         'launches': [{'pid': 1, 'build': 'abc', 'dll_sha256_logged': None, 'utc': 'u'}]}}


class PassFile(unittest.TestCase):
    def test_a_valid_doc_and_the_schema_file_agree(self):
        from warscape import schema
        sc = json.loads((ROOT / 'schemas' / 'acceptance_pass.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(schema.check_schema(sc), [])
        self.assertEqual(acc.pass_problems(good_doc()), [])
        self.assertEqual(schema.validate(good_doc(), sc), [])

    def test_each_required_field_missing_is_reported_by_both(self):
        from warscape import schema
        sc = json.loads((ROOT / 'schemas' / 'acceptance_pass.schema.json').read_text(encoding='utf-8'))
        for k in acc.PASS_REQUIRED:
            d = good_doc()
            del d[k]
            self.assertTrue(acc.pass_problems(d), k)
            if k != 'schema':
                self.assertTrue(schema.validate(d, sc), k)
        for k in acc.EVIDENCE_REQUIRED:
            d = good_doc()
            del d['evidence'][k]
            self.assertTrue(acc.pass_problems(d), k)
            self.assertTrue(schema.validate(d, sc), k)

    def test_a_pass_without_a_build_is_invalid_and_a_legacy_file_is_legacy(self):
        d = good_doc()
        d['build_id'] = None
        self.assertTrue(any('build_id' in p for p in acc.pass_problems(d)))
        legacy = {'pass': 1, 'start_utc': 'a', 'build_id': 'abc', 'passed': True, 'steps': {}}
        self.assertIn('legacy', acc.pass_problems(legacy)[0])

    def test_the_line_must_agree_with_the_file(self):
        d = good_doc()
        line = acc.ledger_line(1, 'abc', '1.0', 'k', True, {'exe_sha1': True}, 'job/W9', 'harness/runs/r', 'harness/runs/r/pass_01.json', doc=d, file_sha='f' * 64, flakes_allowed=1)
        self.assertEqual(acc.ledger_line_matches(line, d, 'f' * 64), [])
        self.assertTrue(acc.ledger_line_matches(dict(line, build_id='other'), d, 'f' * 64))
        self.assertTrue(acc.ledger_line_matches(line, d, 'e' * 64))                      # evidence_sha256 is not the file's
        self.assertTrue(acc.ledger_line_matches(dict(line, steps={'exe_sha1': False}), d, 'f' * 64))
        self.assertTrue(acc.ledger_line_matches(dict(line, watcher_sha='z'), d, 'f' * 64))

    def test_check_pass_reads_files_and_the_ledger(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            pf = t / 'harness' / 'runs' / 'r' / 'pass_01.json'
            pf.parent.mkdir(parents=True)
            pf.write_text(json.dumps(good_doc()))
            line = acc.ledger_line(1, 'abc', '1.0', 'k', True, {'exe_sha1': True}, 'b', 'harness/runs/r', 'harness/runs/r/pass_01.json', doc=good_doc(), file_sha=acc.sha(pf))
            led = t / 'l.jsonl'
            led.write_text(json.dumps(line) + '\n')
            out = io.StringIO()
            with mock.patch.object(acc, 'ROOT', t), mock.patch.object(acc.layout, 'harness_adapter', lambda root: 'x'), contextlib.redirect_stdout(out):
                self.assertEqual(acc.main(['check-pass', str(pf), '--ledger', str(led)]), 0, out.getvalue())
                led.write_text(json.dumps(dict(line, evidence_sha256='0' * 64)) + '\n')
                self.assertEqual(acc.main(['check-pass', str(pf), '--ledger', str(led)]), 1)


class Preflight(unittest.TestCase):
    def test_equal_bytes_pass(self):
        self.assertEqual(acc.watcher_problems(b"$Version = '1.0.3'\n", b"$Version = '1.0.3'\n", {'version': '1.0.3'}), [])

    def test_failing_fixture_one_differing_byte_refuses_naming_both_shas_and_the_fix(self):
        a, b = b"$Version = '1.0.3'\n# a", b"$Version = '1.0.3'\n# b"
        bad = acc.watcher_problems(a, b, {'version': '1.0.3'})
        self.assertEqual(len(bad), 1)
        self.assertIn(acc.hashlib.sha256(a).hexdigest()[:12], bad[0])
        self.assertIn(acc.hashlib.sha256(b).hexdigest()[:12], bad[0])
        self.assertIn('job.sh update kit=', bad[0])

    def test_a_watcher_updated_on_disk_and_not_restarted_is_refused(self):
        bad = acc.watcher_problems(b"$Version = '1.0.4'", b"$Version = '1.0.4'", {'version': '1.0.3'})
        self.assertEqual(len(bad), 1)
        self.assertIn('never restarted', bad[0])

    def test_failing_fixture_crlf_in_the_working_tree_is_the_same_watcher_as_lf_in_git(self):
        # .gitattributes: *.ps1 is CRLF on disk and in kits, LF in the blob git show returns; comparing raw bytes refused every correct install
        self.assertEqual(acc.watcher_problems(b'a\r\nb\r\n', b'a\nb\n', {}), [])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'watcher' / 'src' / 'watcher.ps1'
            p.parent.mkdir(parents=True)
            p.write_bytes(b'a\r\nb\r\n')
            self.assertEqual(acc.installed_watcher_bytes({'state_dir': d}), b'a\nb\n')

    def test_missing_files_refuse(self):
        self.assertTrue(acc.watcher_problems(None, b'x', {}))
        self.assertTrue(acc.watcher_problems(b'x', None, {}))

    def test_run_problems_wires_it_in(self):
        a = mock.Mock(branch='job/W9')
        self.assertTrue(acc.run_problems(a, has_pil=True, watcher_files=(b'a', b'b')))
        self.assertEqual(acc.run_problems(a, has_pil=True, watcher_files=(b'a', b'a')), [])

    def test_the_installed_copy_is_opened_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'watcher' / 'src' / 'watcher.ps1'
            p.parent.mkdir(parents=True)
            p.write_bytes(b'hello')
            os.chmod(p, 0o444)
            m0 = p.stat().st_mtime_ns
            self.assertEqual(acc.installed_watcher_bytes({'state_dir': d}), b'hello')
            self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), (b'hello', m0))
            os.chmod(p, 0o644)
            self.assertIsNone(acc.installed_watcher_bytes({'state_dir': str(Path(d) / 'none')}))

    def test_the_cores_watcher_comes_from_git_head(self):
        b = acc.kit_watcher_bytes()
        self.assertTrue(b is None or b'Version' in b)


SAVES = {'ctl': {'saves': {'anchor': 'game', 'dir': 'saves', 'ext': '.sav'}}}


class StagedSaves(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(self.d, ignore_errors=True))
        self.repo, self.game = self.d / 'repo', self.d / 'game'
        (self.repo / 'saves').mkdir(parents=True)
        self.game.mkdir()
        self.src = self.repo / 'saves' / 'a.sav'
        self.src.write_bytes(b'SAVEDATA')
        self.ad = dict(SAVES, game_dir=str(self.game))
        self.row = {'id': 'camp.start-2', 'kind': 'campaign', 'map': 'm', 'save': 'a description', 'launch': 'l', 'description': 'd',
                    'save_file': 'saves/a.sav', 'save_sha256': acc.hashlib.sha256(b'SAVEDATA').hexdigest()}

    def target(self):
        return self.game / 'saves' / f"{ctl.harness_save_name(self.row['id'])}.sav"

    def test_staged_under_the_harness_name_and_cleared_after(self):
        with ctl.stage_save(self.row, self.ad, self.repo) as t:
            self.assertEqual(t, 'campaign:wsc_camp_start-2')
            self.assertEqual(self.target().read_bytes(), b'SAVEDATA')
        self.assertFalse(self.target().exists())
        self.assertEqual(sorted(p.name for p in (self.game / 'saves').iterdir()), [])

    def test_failing_fixture_a_failing_scene_still_clears_it(self):
        with self.assertRaises(ValueError):
            with ctl.stage_save(self.row, self.ad, self.repo):
                raise ValueError('scene failed')
        self.assertFalse(self.target().exists())

    def test_a_wrong_sha_or_a_missing_file_refuses_before_any_write(self):
        for row in (dict(self.row, save_sha256='0' * 64), dict(self.row, save_file='saves/none.sav')):
            with self.assertRaises(ctl.Refused) as e:
                with ctl.stage_save(row, self.ad, self.repo):
                    self.fail('staged')
            self.assertFalse((self.game / 'saves').exists())
        with self.assertRaises(ctl.Refused) as e:
            with ctl.stage_save(dict(self.row, save_sha256='0' * 64), self.ad, self.repo):
                pass
        self.assertIn(self.row['save_sha256'], str(e.exception))   # names both: the file's and the row's
        self.assertIn('0' * 64, str(e.exception))

    def test_unsafe_characters_and_a_long_id(self):
        self.assertEqual(ctl.harness_save_name('a b/c:d'), 'wsc_a_b_c_d')
        long_id = 'x' * 100
        n = ctl.harness_save_name(long_id)
        self.assertLessEqual(len(n), 72)
        self.assertTrue(n.startswith('wsc_xxx'))
        self.assertNotEqual(n, ctl.harness_save_name('x' * 99))   # the hash tells long ids apart

    def test_failing_fixture_a_leftover_is_overwritten_and_said(self):
        self.target().parent.mkdir(parents=True)
        self.target().write_bytes(b'OLD')
        said = []
        with ctl.stage_save(self.row, self.ad, self.repo, say=said.append):
            self.assertEqual(self.target().read_bytes(), b'SAVEDATA')
        self.assertTrue(said and 'leftover' in said[0])
        self.assertFalse(self.target().exists())

    def test_a_file_not_starting_with_wsc_is_never_removed(self):
        keep = self.game / 'saves' / 'liams_own.sav'
        keep.parent.mkdir(parents=True)
        keep.write_bytes(b'MINE')
        with ctl.stage_save(self.row, self.ad, self.repo):
            pass
        self.assertEqual(keep.read_bytes(), b'MINE')

    def test_a_row_without_save_file_behaves_as_before_and_no_block_refuses(self):
        row = {'id': 'c', 'kind': 'campaign', 'map': 'm', 'save': 'campaign:new:x:y a description', 'launch': 'l', 'description': 'd'}
        self.assertEqual(ctl.scenario_target(row, self.d), 'campaign:new:x:y')
        self.assertEqual(ctl.scenario_target(self.row, self.d, self.ad), 'campaign:wsc_camp_start-2')
        with self.assertRaises(ctl.Refused) as e:
            ctl.scenario_target(self.row, self.d, {})
        self.assertIn('ctl.saves', str(e.exception))

    def test_v_scene_stages_before_the_autostart_and_clears_after(self):
        seen = []
        tgt = self.target

        def t(line, wait=0):
            if line.startswith('autostart'):
                seen.append((line, tgt().exists()))
                return 1, {'status': 'failed', 'reason': 'boom'}
            return 0, {'scene': 'frontend'}
        c = ctl.Ctl(t, {self.row['id']: self.row}, self.ad, battles_dir=self.d)
        c.state = lambda: {'scene': 'frontend'}
        with mock.patch.object(ctl, 'ROOT', self.repo):
            r = c.run('scene', self.row['id'])
        self.assertEqual(r['status'], 'failed')
        self.assertEqual(seen, [('autostart campaign:wsc_camp_start-2 240', True)])
        self.assertFalse(self.target().exists())

    def test_the_schema_allows_the_fields_for_campaign_rows_only(self):
        from warscape import schema
        sc = json.loads((ROOT / 'schemas' / 'scenarios.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(schema.validate(self.row, sc), [])
        land = {'id': 'l', 'description': 'd', 'kind': 'land', 'map': 'm', 'time_of_day': 'noon', 'weather': 'clear', 'launch': 'l', 'save_file': 'x'}
        self.assertTrue(schema.validate(land, sc))
        self.assertTrue(schema.validate(dict(self.row, save_sha256='short'), sc))


if __name__ == '__main__':
    unittest.main()
