"""End to end: a throwaway game repo driven through `wsc`, the core's own gates, and the pre-push hook."""
import json
import os
import shutil
import subprocess
import sys
import unittest

from _util import CORE, TOOL_PY, TempRepo


class GameRepo(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo({'README.md': '# A game\n', 'adapter/sync.py': TOOL_PY.format(name='adapter/sync.py')})

    def tearDown(self):
        self.repo.close()

    def ready(self):
        self.assertEqual(self.repo.wsc('reg', 'render')[0], 0)
        self.assertEqual(self.repo.wsc('reg', 'add', 'tools', '--missing')[0], 0)

    def test_fresh_repo_fails_then_passes_the_fast_gates(self):
        rc, out = self.repo.wsc('gates', '--fast')
        self.assertEqual(rc, 1)
        self.assertIn('FAIL registries', out)
        self.assertIn('FAIL tools', out)
        self.ready()
        rc, out = self.repo.wsc('gates', '--fast')
        self.assertEqual(rc, 0, out)
        self.assertNotIn(' tests ', out)    # the fast set leaves out host tests

    def test_reg_add_set_check_find(self):
        self.ready()
        rc, out = self.repo.wsc('reg', 'add', 'scenarios', 'id=land.small', 'description=Small land battle, 4 v 4', 'kind=land',
                                'map=landmap_hills', 'launch=scenarios/land_small.cmd', 'time_of_day=noon', 'weather=clear',
                                'good_for:=["controls", "frame time"]')
        self.assertEqual(rc, 0, out)
        rc, out = self.repo.wsc('reg', 'add', 'scenarios', 'id=bad', 'description=x', 'kind=lunar', 'map=m', 'launch=x')
        self.assertEqual(rc, 2)
        self.assertIn('not one of', out)
        rc, out = self.repo.wsc('reg', 'set', 'scenarios', 'land.small', 'load_time_s:={"seconds": 41.5, "date": "2026-10-28", "run": "20261028_lt"}')
        self.assertEqual(rc, 0, out)
        row = json.loads(self.repo.read('registries/scenarios.jsonl'))
        self.assertEqual(row['load_time_s']['seconds'], 41.5)
        self.assertIn('land.small', self.repo.read('registries/scenarios.md'))
        self.assertEqual(self.repo.wsc('reg', 'check')[0], 0)
        rc, out = self.repo.wsc('find', 'small', 'battle')
        self.assertEqual(rc, 0)
        self.assertIn('scenarios', out)
        self.assertIn('land.small', out)
        rc, out = self.repo.wsc('find', 'gates')       # the core's verbs are found from a game repo
        self.assertIn('core:tools', out)
        self.assertIn('wsc.gates', out)
        self.assertEqual(self.repo.wsc('find', 'zzzz')[0], 1)
        self.assertEqual(self.repo.wsc('reg', 'check', 'nope')[0], 2)

    def test_doc_gates_use_the_configured_cap(self):
        self.ready()
        self.repo.write('wsc.toml', self.repo.read('wsc.toml') + '\n[docs]\nmax_kb = 1\n')
        self.repo.write('docs/PLAN.md', 'x' * 1100 + '\n')
        self.repo.write('docs/2026-10-28_retro.md', 'x' * 5000 + '\nverified.\n')    # a dated record: exempt from both
        rc, out = self.repo.wsc('gates', '--only', 'doc_size,verified_dates')
        self.assertEqual(rc, 1)
        self.assertIn('docs/PLAN.md: 1.1 KB (cap 1 KB)', out)
        self.assertNotIn('retro', out)
        self.repo.write('docs/PLAN.md', 'The shadow fit was verified in game.\n')
        rc, out = self.repo.wsc('gates', '--only', 'doc_size,verified_dates')
        self.assertIn('docs/PLAN.md:1: "verified" with no date or run id', out)
        self.repo.write('docs/PLAN.md', 'The shadow fit was verified in game 2026-10-28 (run 20261028_a).\n')
        self.assertEqual(self.repo.wsc('gates', '--only', 'doc_size,verified_dates')[0], 0)

    def test_json_and_windows_gates(self):
        self.ready()
        self.repo.write('data/x.json', '{"a": NaN}')
        self.repo.write('aux.md', 'reserved\n')
        rc, out = self.repo.wsc('gates', '--only', 'json,windows_paths')
        self.assertEqual(rc, 1)
        self.assertIn('data/x.json', out)
        self.assertIn('invalid on Windows: aux.md', out)

    def test_core_pin(self):
        self.ready()
        self.repo.write('wsc.toml', self.repo.read('wsc.toml') + '\n[core]\nversion = "v9.9.9"\n')
        rc, out = self.repo.wsc('gates', '--only', 'core_pin')
        self.assertEqual(rc, 1)
        self.assertIn('pins core v9.9.9', out)
        ver = (CORE / 'VERSION').read_text(encoding='utf-8').strip()
        self.repo.write('wsc.toml', self.repo.read('wsc.toml').replace('v9.9.9', 'v' + ver))
        rc, out = self.repo.wsc('gates', '--only', 'core_pin')
        self.assertNotIn('pins core', out)
        if rc:   # the core checkout running this test is being edited, or is a branch commit without the release tag
            self.assertTrue('local changes' in out or 'not the pinned tag' in out, out)
        self.repo.write('wsc.toml', self.repo.read('wsc.toml').replace('v' + ver, 'V' + ver))
        rc, out = self.repo.wsc('gates', '--only', 'core_pin')
        self.assertEqual(rc, 1)
        self.assertIn('lower-case v', out)

    def test_hook_variables_do_not_leak_into_core_checks(self):
        # git exports GIT_DIR / GIT_INDEX_FILE to hooks; a gate that inherits them reads the wrong repo (napoleon J5, worktree push)
        self.ready()
        other = TempRepo({'x.txt': 'x'})
        try:
            saved = {k: os.environ.get(k) for k in ('GIT_DIR', 'GIT_INDEX_FILE')}
            os.environ['GIT_DIR'] = str(other.root / '.git')
            os.environ['GIT_INDEX_FILE'] = str(other.root / '.git' / 'index')
            rc, out = self.repo.wsc('gates', '--only', 'json,windows_paths')
            self.assertEqual(rc, 0, out)
            self.assertNotIn('x.txt', out)
            self.assertIn('wsc.toml', ' '.join(__import__('warscape.repo', fromlist=['x']).list_files(self.repo.root)))
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            other.close()

    def test_hooks_gate_warns_until_wired(self):
        self.ready()
        env = os.environ.pop('CI', None)
        try:
            rc, out = self.repo.wsc('gates', '--only', 'hooks')
            self.assertEqual(rc, 0, out)                  # a warning never fails the run
            self.assertIn('git config core.hooksPath core/.githooks', out)
            subprocess.run(['git', '-C', str(self.repo.root), 'config', 'core.hooksPath', 'core/.githooks'], check=True)
            rc, out = self.repo.wsc('gates', '--only', 'hooks')
            self.assertIn('pre-push hook wired', out)
        finally:
            if env is not None:
                os.environ['CI'] = env

    def test_repo_verbs_and_bad_config(self):
        self.repo.write('adapter/verbs/hello.py', '"""\nPurpose: say hello.\nUsage: wsc hello\nWhen: tests.\nVerb: hello\n"""\nNAME = "hello"\nHELP = "say hello"\n'
                        'def add_arguments(p):\n    p.add_argument("who")\n'
                        'def run(args, ctx):\n    print("hello " + args.who)\n    return 0\n')
        self.repo.write('wsc.toml', self.repo.read('wsc.toml') + '\n[cli]\nverb_dirs = ["adapter/verbs"]\n')
        self.ready()
        rc, out = self.repo.wsc('hello', 'liam')
        self.assertEqual((rc, out.strip()), (0, 'hello liam'))
        self.assertEqual(self.repo.wsc('gates', '--only', 'tools')[0], 0)
        self.repo.write('wsc.toml', self.repo.read('wsc.toml') + '\n[docs]\nmax_kbb = 3\n')
        rc, out = self.repo.wsc('gates')
        self.assertEqual(rc, 2)
        self.assertIn("unknown key 'docs.max_kbb'", out)

    def test_unknown_gate_name(self):
        self.ready()
        rc, out = self.repo.wsc('gates', '--only', 'nope')
        self.assertEqual(rc, 2)
        self.assertIn('unknown gate', out)


class CoreRepo(unittest.TestCase):
    def test_the_cores_own_fast_gates_pass(self):
        p = subprocess.run([sys.executable, str(CORE / 'wsc.py'), '--root', str(CORE), 'gates', '--fast', '--only',
                            'schemas,registries,tools,json,windows_paths,doc_size,verified_dates,conflict_markers'],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


@unittest.skipIf(os.name == 'nt' or not shutil.which('sh'), 'the hook test needs a POSIX sh and symlinks')
class PrePush(unittest.TestCase):
    def test_hook_runs_the_fast_gates_from_a_game_repo(self):
        repo = TempRepo({'adapter/sync.py': TOOL_PY.format(name='adapter/sync.py')})
        try:
            os.symlink(CORE, repo.root / 'core')
            repo.wsc('reg', 'render')
            repo.wsc('reg', 'add', 'tools', '--missing')
            hook = str(CORE / '.githooks' / 'pre-push')
            p = subprocess.run(['sh', hook], cwd=repo.root, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            repo.write('bad.json', '{')
            p = subprocess.run(['sh', hook], cwd=repo.root, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
            self.assertEqual(p.returncode, 1)
            self.assertIn('push refused', p.stderr)
            self.assertIn('bad.json', p.stdout)
        finally:
            repo.close()


if __name__ == '__main__':
    unittest.main()
