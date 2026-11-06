"""W139: the `tests` gate. Real `python -m unittest` children on throwaway folders: timings in the log, workers, the deadline, the headroom warning."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _util import CORE
from warscape import gates
from warscape.repo import DEFAULTS, ConfigError, load_config

PASS = 'import unittest\nclass A(unittest.TestCase):\n    def test_a(self):\n        pass\n    def test_b(self):\n        pass\n'
FAIL = 'import unittest\nclass B(unittest.TestCase):\n    def test_bad(self):\n        self.fail("broken on purpose")\n'
SKIP = 'import unittest\nclass {k}(unittest.TestCase):\n    def test_s(self):\n        self.skipTest("no toolchain")\n    def test_t(self):\n        pass\n    def test_u(self):\n        pass\n'
SLOW = 'import time, unittest\nclass C(unittest.TestCase):\n    def test_slow(self):\n        time.sleep(0.3)\n'


class Folder(unittest.TestCase):
    """A repo root with one test folder `t`, and the gate run on it."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 't').mkdir()

    def write(self, **modules):
        for name, text in modules.items():
            (self.root / 't' / f'{name}.py').write_text(text, encoding='utf-8')

    def gate(self, **keys):
        tc = {**DEFAULTS['tests'], 'dirs': ['t'], 'timeout_s': 120, **keys}
        return gates.gate_tests(SimpleNamespace(root=self.root, config={'tests': tc}))


class Timings(Folder):
    """Deliverable 1: the log says where the time went, on a green run too."""
    def test_a_green_run_names_its_slowest_modules_with_seconds(self):
        self.write(test_fast=PASS, test_slow=SLOW)
        r = self.gate()
        self.assertEqual((r.level, r.summary), ('ok', '3 host tests passed (t)'))
        line = next(d for d in r.details if d.startswith('t: slowest'))
        self.assertRegex(line, r'test_slow \d+\.\d s, test_fast \d+\.\d s')

    def test_the_worker_count_and_cpu_count_print_once(self):
        self.write(test_fast=PASS)
        (self.root / 'u').mkdir()
        (self.root / 'u' / 'test_other.py').write_text(PASS, encoding='utf-8')
        r = self.gate(dirs=['t', 'u'])
        self.assertEqual([d for d in r.details if 'cpu_count' in d], [f'timing: workers 1, cpu_count {os.cpu_count()}'])

    def test_a_failed_run_keeps_its_timings_and_its_tail_holds_no_durations(self):
        self.write(test_bad=FAIL, test_fast=PASS)
        r = self.gate()
        self.assertEqual((r.level, r.summary), ('error', 'host tests failed'))
        self.assertTrue(any(d.startswith('t: slowest') for d in r.details))
        self.assertTrue(any(d.startswith('t: Ran 3 tests in') and d.endswith(', FAILED') for d in r.details), r.details)
        self.assertIn('AssertionError: broken on purpose', r.details)
        self.assertFalse([d for d in r.details if 'Slowest test durations' in d or d.startswith('0.0')], r.details)

    def test_the_durations_block_comes_out_whole_and_nothing_else_does(self):
        lines = ['test_a (m.C.test_a) ... ok', '', 'Slowest test durations', '-' * 70, '1.250s     test_a (m.C.test_a)', '0.250s     test_b (m.C.test_b)',
                 '2.000s     test_c (p.n.D.test_c)', '', '-' * 70, 'Ran 3 tests in 3.500s', '', 'OK']
        rest, secs = gates.split_durations(lines)
        self.assertEqual(rest, ['test_a (m.C.test_a) ... ok', '', '-' * 70, 'Ran 3 tests in 3.500s', '', 'OK'])
        self.assertEqual(secs, {'m': 1.5, 'p.n': 2.0})

    def test_no_durations_block_changes_nothing(self):
        self.assertEqual(gates.split_durations(['Ran 0 tests in 0.000s']), (['Ran 0 tests in 0.000s'], {}))


class Workers(Folder):
    """Deliverable 2: modules from a queue, each in its own process. Nothing fails or disappears quietly."""
    def test_the_total_is_the_sum_of_the_modules_and_matches_one_process(self):
        self.write(test_one=PASS, test_two=PASS, test_three=SLOW)
        one, four = self.gate(workers=1), self.gate(workers=4)
        self.assertEqual((one.level, one.summary), ('ok', '5 host tests passed (t)'))
        self.assertEqual((four.level, four.summary), (one.level, one.summary))

    def test_two_modules_really_run_at_once(self):
        wait = ('import pathlib, time, unittest\nclass R(unittest.TestCase):\n    def test_meet(self):\n        d = pathlib.Path(__file__).parent\n'
                '        (d / "{me}.seen").touch()\n        end = time.time() + 20\n'
                '        while time.time() < end and not (d / "{other}.seen").exists():\n            time.sleep(0.02)\n'
                '        self.assertTrue((d / "{other}.seen").exists())\n')
        self.write(test_a=wait.format(me='a', other='b'), test_b=wait.format(me='b', other='a'))
        self.assertEqual(self.gate(workers=2).level, 'ok')

    def test_a_failing_module_fails_the_gate_named_with_its_tail(self):
        self.write(test_good=PASS, test_bad=FAIL)
        r = self.gate(workers=2)
        self.assertEqual((r.level, r.summary), ('error', 'host tests failed: test_bad'))
        self.assertTrue(any(d.startswith('t: test_bad: Ran 1 test in') and d.endswith(', FAILED') for d in r.details), r.details)
        self.assertIn('AssertionError: broken on purpose', r.details)

    def test_an_import_error_fails_the_gate(self):
        self.write(test_good=PASS, test_boom='raise RuntimeError("boom at import")\n')
        r = self.gate(workers=2)
        self.assertEqual((r.level, r.summary), ('error', 'host tests failed: test_boom'))
        self.assertTrue(any('boom at import' in d for d in r.details), r.details)

    def test_a_module_that_dies_mid_run_never_passes(self):
        for code in (0, 3):      # exit 0 with no result is the silent zero the gate must not count
            with self.subTest(code=code):
                self.write(test_good=PASS, **{f'test_dies{code}': f'import os, unittest\nclass E(unittest.TestCase):\n    def test_die(self):\n        os._exit({code})\n'})
                r = self.gate(workers=2)
                self.assertEqual((r.level, r.summary), ('error', f'host tests failed: test_dies{code}'))
                self.assertIn(f't: test_dies{code}: no test result, exit {code}', r.details)
                (self.root / 't' / f'test_dies{code}.py').unlink()

    def test_a_result_printed_by_a_test_is_not_the_modules_result(self):
        self.write(test_liar='import os, unittest\nclass L(unittest.TestCase):\n    def test_lie(self):\n'
                             '        print("Ran 99 tests in 0.1s", flush=True)\n        os._exit(0)\n')
        r = self.gate(workers=2)
        self.assertEqual(r.level, 'error')
        self.assertIn('t: test_liar: no test result, exit 0', r.details)

    def test_a_module_with_no_tests_is_named_not_counted_as_nothing(self):
        self.write(test_good=PASS, test_empty='HELPER = 1\n')
        r = self.gate(workers=2)
        self.assertEqual((r.level, r.summary), ('error', 'host tests failed: test_empty'))

    def test_a_folder_with_no_modules_fails_as_one_process_does(self):
        self.assertEqual(self.gate(workers=1).level, 'error')
        self.assertEqual(self.gate(workers=2).level, 'error')

    def test_a_child_that_cannot_start_is_a_failed_module(self):
        self.write(test_good=PASS)
        with mock.patch.object(gates.subprocess, 'Popen', side_effect=OSError('no such interpreter')):
            r = self.gate(workers=2)
        self.assertEqual((r.level, r.summary), ('error', 'host tests failed: test_good'))
        self.assertTrue(any('no such interpreter' in d for d in r.details), r.details)

    def test_skips_reach_the_gate_from_every_module(self):
        self.write(test_s1=SKIP.format(k='S1'), test_s2=SKIP.format(k='S2'), test_good=PASS)
        r = self.gate(workers=3)
        self.assertEqual((r.level, r.summary), ('warn', '8 host tests passed (t); 2 skipped'))
        self.assertIn('t: skipped S1.test_s: no toolchain', r.details)
        self.assertIn('t: skipped S2.test_s: no toolchain', r.details)

    def test_every_failed_module_is_named_however_long_the_tails(self):
        self.write(**{f'test_bad{i}': FAIL for i in range(9)})
        r = self.gate(workers=4)
        self.assertEqual(r.summary, 'host tests failed: ' + ', '.join(f'test_bad{i}' for i in range(9)))

    def test_long_modules_start_first_and_the_rest_in_name_order(self):
        self.assertEqual(gates.module_order(['test_a', 'test_b', 'test_c', 'test_d'], ['test_c', 'test_gone', 'test_a']), ['test_c', 'test_a', 'test_b', 'test_d'])

    def test_only_what_discover_finds_is_queued(self):
        self.write(test_a=PASS, helper=PASS)
        (self.root / 't' / 'test-not-a-module.py').write_text(PASS, encoding='utf-8')
        (self.root / 't' / 'plain').mkdir()
        (self.root / 't' / 'plain' / 'test_hidden.py').write_text(PASS, encoding='utf-8')
        (self.root / 't' / 'pkg').mkdir()
        (self.root / 't' / 'pkg' / '__init__.py').write_text('', encoding='utf-8')
        (self.root / 't' / 'pkg' / 'test_inner.py').write_text(PASS, encoding='utf-8')
        self.assertEqual(gates.test_modules(self.root / 't'), ['test_a', 'test_inner'])
        one, four = self.gate(workers=1), self.gate(workers=4)
        self.assertEqual(one.summary, '4 host tests passed (t)')
        self.assertEqual(four.summary, one.summary)

    def test_this_repo_queues_exactly_what_one_discover_loads(self):
        """A module `test_modules` missed would drop its tests silently; one with no tests would fail the gate."""
        code = ('import sys, unittest\ndef walk(s):\n    for t in s:\n        if isinstance(t, unittest.TestSuite):\n            yield from walk(t)\n        else:\n            yield t\n'
                'print(*sorted({type(t).__module__.rsplit(".", 1)[-1] for t in walk(unittest.TestLoader().discover(sys.argv[1], "test_*.py", sys.argv[1]))}))')
        for d in ('tests', 'discovery/tests'):
            p = subprocess.run([sys.executable, '-c', code, d], cwd=CORE, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr[-800:])
            self.assertEqual(p.stdout.split(), gates.test_modules(CORE / d))


class Deadline(Folder):
    """A hung module cannot hang the gate: one deadline per folder, real children, a real grandchild holding the output open."""
    HANG = ('import pathlib, subprocess, sys, time, unittest\nclass H(unittest.TestCase):\n    def test_hang(self):\n'
            '        beat = pathlib.Path(__file__).parent / "{name}.beat"\n'
            '        loop = "import sys, time\\nwhile True:\\n    open(sys.argv[1], \'a\').write(\'x\')\\n    time.sleep(0.1)\\n"\n'
            '        subprocess.Popen([sys.executable, "-c", loop, str(beat)])\n'
            '        time.sleep(300)\n')

    def beats_stopped(self, *beats):
        self.assertTrue(all(b.is_file() and b.stat().st_size for b in beats), 'the grandchildren never started: this test proved nothing')
        before = [b.stat().st_size for b in beats]
        time.sleep(1.5)
        self.assertEqual([b.stat().st_size for b in beats], before, 'a grandchild outlived the gate')

    def test_the_tree_is_killed_and_the_gate_says_what_did_not_finish(self):
        self.write(test_a_hang=self.HANG.format(name='a'), test_b_hang=self.HANG.format(name='b'), test_c_late=PASS, test_d_late=PASS)
        t0 = time.monotonic()
        r = self.gate(workers=2, timeout_s=4, warn_at=0)
        self.assertLess(time.monotonic() - t0, 34, 'the gate must return within 30 s of the deadline')
        self.assertEqual((r.level, r.summary), ('error', 'host tests failed: test_a_hang, test_b_hang, test_c_late, test_d_late'))
        self.assertEqual(r.details[2:5], ['t: timed out after 4 s', 't: not finished: test_a_hang, test_b_hang', 't: never started: test_c_late, test_d_late'])
        self.beats_stopped(self.root / 't' / 'a.beat', self.root / 't' / 'b.beat')

    def test_a_finished_modules_result_still_counts_on_a_timeout(self):
        self.write(test_a_hang=self.HANG.format(name='a'), test_bad=FAIL)
        r = self.gate(workers=2, timeout_s=4, first=['test_a_hang'])
        self.assertEqual(r.level, 'error')
        self.assertIn('t: not finished: test_a_hang', r.details)
        self.assertTrue(any(d.startswith('t: test_bad: Ran 1 test') for d in r.details), r.details)

    def test_an_interrupted_gate_leaves_nothing_running(self):
        self.write(test_a_hang=self.HANG.format(name='a'))
        beat = self.root / 't' / 'a.beat'

        def interrupted(threads):
            end = time.monotonic() + 30
            while time.monotonic() < end and not (beat.is_file() and beat.stat().st_size):
                time.sleep(0.05)
            raise KeyboardInterrupt

        with mock.patch.object(gates, '_join', interrupted), self.assertRaises(KeyboardInterrupt):
            self.gate(workers=2, timeout_s=60)
        self.beats_stopped(beat)


class Headroom(Folder):
    """Deliverable 4: closeness to `timeout_s` is a warn, never a failure."""
    def test_a_folder_over_warn_at_warns_and_passes(self):
        self.write(test_slow=SLOW)
        for workers in (1, 2):
            with self.subTest(workers=workers):
                r = self.gate(workers=workers, timeout_s=60, warn_at=0.001)
                self.assertEqual((r.level, r.summary), ('warn', '1 host tests passed (t); near the time limit'))
                self.assertTrue(any(d.startswith('t: took ') and 'of timeout_s 60' in d for d in r.details), r.details)

    def test_zero_is_off_and_under_the_line_is_quiet(self):
        self.write(test_fast=PASS)
        self.assertEqual(self.gate(timeout_s=60, warn_at=0).level, 'ok')
        self.assertEqual(self.gate(timeout_s=600, warn_at=0.75).level, 'ok')

    def test_skips_and_headroom_say_both(self):
        self.write(test_s=SKIP.format(k='S'))
        self.assertEqual(self.gate(timeout_s=60, warn_at=0.0001).summary, '3 host tests passed (t); 1 skipped; near the time limit')


class Config(unittest.TestCase):
    """Deliverable 3: the keys default to today's behaviour, and a bad value is refused by name."""
    def load(self, body):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'wsc.toml').write_text(f'[tests]\n{body}\n', encoding='utf-8')
            return load_config(Path(d))

    def test_defaults_are_todays_behaviour(self):
        self.assertEqual({k: DEFAULTS['tests'][k] for k in ('workers', 'first', 'warn_at')}, {'workers': 1, 'first': [], 'warn_at': 0.75})

    def test_good_values_load(self):
        t = self.load('workers = 4\nfirst = ["test_a"]\nwarn_at = 0')['tests']
        self.assertEqual((t['workers'], t['first'], t['warn_at']), (4, ['test_a'], 0))

    def test_bad_values_are_refused_by_name(self):
        for body in ('workers = 0', 'workers = true', 'workers = "4"', 'workers = 1.5', 'first = "test_a"', 'first = [1]', 'first = [""]',
                     'warn_at = -0.1', 'warn_at = 1.5', 'warn_at = "x"', 'warn_at = true'):
            with self.subTest(body=body), self.assertRaisesRegex(ConfigError, 'tests.' + body.split()[0]):
                self.load(body)


if __name__ == '__main__':
    unittest.main()
