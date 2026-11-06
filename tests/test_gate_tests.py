"""W139: the `tests` gate. Real `python -m unittest` children on throwaway folders: timings in the log, workers, the deadline, the headroom warning."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from _util import CORE  # noqa: F401  (puts the core on sys.path)
from warscape import gates
from warscape.repo import DEFAULTS

PASS = 'import unittest\nclass A(unittest.TestCase):\n    def test_a(self):\n        pass\n    def test_b(self):\n        pass\n'
FAIL = 'import unittest\nclass B(unittest.TestCase):\n    def test_bad(self):\n        self.fail("broken on purpose")\n'
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


if __name__ == '__main__':
    unittest.main()
