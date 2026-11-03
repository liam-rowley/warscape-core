"""Host tests for harness/job.sh (the agent helper): root from the adapter, atomic submit, blocking wait, exit codes (refused 2,
no answer 124), owner added to the request, lock take/refresh/release. A thread plays the watcher. Runs in `wsc gates` (tests gate) and
in CI's harness-windows job with a real Git Bash.

Ported from the first consumer's `tests/test_job_sh.py` at 6cbb9e9 (B17). The bash comes from `warscape.gitbash.bash_for_tests()`; the game
repo job.sh finds without --adapter (its harness adapter and its registered dev.ctl_dir default) is the null game (proxy/tests/null_game,
through $WSP_GAME_ROOT). job.sh reads JSON with python3, so every case skips where python3 is not on PATH (CI's gates job on Windows)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from warscape.gitbash import bash_for_tests  # noqa: E402

JOB = ROOT / 'harness' / 'job.sh'
NULL_GAME = ROOT / 'proxy' / 'tests' / 'null_game'
BASH, NO_BASH = bash_for_tests()   # Git Bash on Windows, never the WSL launcher on PATH (J22)
if not NO_BASH and not shutil.which('python3'):
    NO_BASH = 'job.sh calls python3, which is not on PATH here'


def job_env():
    """The test's environment for job.sh: no watcher root or adapter from the caller, the null game as the game repo."""
    e = {k: v for k, v in os.environ.items() if k not in ('WATCHER_ROOT', 'HARNESS_ADAPTER', 'WSP_PROXY_ADAPTER')}
    e['WSP_GAME_ROOT'] = str(NULL_GAME)
    return e


def bash_path(p):
    """How Git Bash names a Windows path (C:\\x\\y -> /c/x/y); a POSIX path is unchanged."""
    s = str(p).replace('\\', '/')
    return f'/{s[0].lower()}{s[2:]}' if len(s) > 1 and s[1] == ':' else s


def run(args, env, stdin=None, timeout=60):
    e = job_env()
    e.update(env)
    return subprocess.run([BASH, str(JOB), *args], input=stdin, capture_output=True, text=True, env=e, timeout=timeout)


class FakeWatcher(threading.Thread):
    """Answers each .request with a canned result; remembers the bodies it saw."""

    def __init__(self, jobs, result):
        super().__init__(daemon=True)
        self.jobs, self.result, self.seen, self.stop = jobs, result, [], False

    def run(self):
        while not self.stop:
            for p in sorted(self.jobs.glob('*.request')):
                body = p.read_text()
                jid = p.stem
                self.seen.append((jid, body))
                p.unlink()
                if self.result is None:
                    continue
                (self.jobs / f'{jid}.out').write_text(self.result.get('out', ''))
                d = {'id': jid, 'status': self.result['status'], 'exit': self.result['exit'], 'reason': self.result.get('reason', '')}
                (self.jobs / f'{jid}.done.tmp').write_text(json.dumps(d))
                os.replace(self.jobs / f'{jid}.done.tmp', self.jobs / f'{jid}.done')
            time.sleep(0.05)


class JobSh(unittest.TestCase):
    def setUp(self):
        if NO_BASH:
            self.skipTest(NO_BASH)
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.state = t / 'nullgame_pc'
        self.root = self.state / 'watcher'
        (self.root / 'jobs').mkdir(parents=True)
        self.adapter = t / 'adapter.json'
        self.game = t / 'game'
        self.game.mkdir()
        # dev.ctl_dir comes from the game's mod ini (fix 1c): this fixture's ini points it at <state>/ctl
        (self.game / 'mod.ini').write_text(f'[proxy]\nbackend=system\n[dev]\nctl={1}\nctl_dir={self.state / "ctl"}\n')
        self.adapter.write_text(json.dumps({'state_dir': str(self.state), 'watcher_subdir': 'watcher', 'game_dir': str(self.game),
                                            'config_files': [{'id': 'mod_ini', 'anchor': 'game', 'path': 'mod.ini', 'style': 'ini'}]}))
        self.env = {}
        self.w = None

    def tearDown(self):
        if self.w:
            self.w.stop = True
        self.tmp.cleanup()

    def watcher(self, result):
        self.w = FakeWatcher(self.root / 'jobs', result)
        self.w.start()

    def test_scratch_creates_the_owner_folder_and_refuses_bad_owners(self):
        # J18 (J5 ledger row 31): <state>/_scratch/<owner>/, owner like the job ids J2 to J6 used (j2, j3s2, j6)
        for owner in ('j18', 'j3s2', 'a', 'x_y-z', 'a' * 32):
            r = run(['--adapter', str(self.adapter), 'scratch', owner], self.env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), bash_path(self.state / '_scratch' / owner))
            self.assertTrue((self.state / '_scratch' / owner).is_dir())
        for owner in ('', 'J18', '-x', '_x', 'a b', '../x', 'a/b', 'a' * 33, 'x.y'):
            r = run(['--adapter', str(self.adapter), 'scratch', owner], self.env)
            self.assertEqual(r.returncode, 64, owner)
            self.assertIn('must match', r.stderr)
        self.assertEqual(sorted(p.name for p in (self.state / '_scratch').iterdir()), sorted(['j18', 'j3s2', 'a', 'x_y-z', 'a' * 32]))

    def test_root_comes_from_the_adapter_not_a_default(self):
        r = run(['--adapter', str(self.adapter), 'root'], self.env)
        self.assertEqual(r.stdout.strip(), bash_path(self.root))
        self.adapter.write_text(json.dumps({'state_dir': str(self.state / 'elsewhere'), 'watcher_subdir': 'watcher'}))
        r = run(['--adapter', str(self.adapter), 'root'], self.env)
        self.assertEqual(r.returncode, 64)
        self.assertIn('does not exist', r.stderr)

    def test_default_adapter_root_is_the_state_dir_as_a_bash_path(self):
        # no --adapter: the repo layout finds the null game's harness/null/adapter.json (state_dir C:\nullgame_pc); no adapter env var
        r = run(['root'], self.env)
        if r.returncode == 0:   # a PC where the folder exists
            self.assertEqual(r.stdout.strip(), '/c/nullgame_pc/watcher')
        else:                   # anywhere else: the folder does not exist, and the error names the converted path
            self.assertEqual(r.returncode, 64)
            self.assertIn('/c/nullgame_pc/watcher does not exist', r.stderr)

    def test_ok_prints_output_and_returns_zero(self):
        self.watcher({'status': 'ok', 'exit': 0, 'out': 'hello from the PC\n'})
        r = run(['--adapter', str(self.adapter), 'me', '-', '20'], self.env, stdin='#ps1\nWrite-Output hi\n')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('hello from the PC', r.stdout)
        jid, body = self.w.seen[0]
        self.assertRegex(jid, r'^me-\d{8}T\d{6}Z-\d+$')
        self.assertTrue(body.startswith('#job owner=me\n#ps1'), body)

    def test_exit_codes(self):
        self.watcher({'status': 'failed', 'exit': 3, 'out': ''})
        self.assertEqual(run(['--adapter', str(self.adapter), 'me', '-', '20'], self.env, stdin='exit /b 3\n').returncode, 3)
        self.w.result = {'status': 'refused', 'exit': -2, 'out': 'REFUSED', 'reason': 'no lock'}
        r = run(['--adapter', str(self.adapter), 'me', '-', '20'], self.env, stdin='launch\n')
        self.assertEqual(r.returncode, 2)
        self.assertIn('no lock', r.stderr)
        self.w.result = {'status': 'timeout', 'exit': -1, 'out': ''}
        self.assertEqual(run(['--adapter', str(self.adapter), 'me', '-', '20'], self.env, stdin='x\n').returncode, 124)

    def test_no_answer_is_124_and_the_request_stays_queued(self):
        t0 = time.time()
        r = run(['--adapter', str(self.adapter), 'me', '-', '2'], self.env, stdin='noop\n')
        self.assertEqual(r.returncode, 124)
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(len(list((self.root / 'jobs').glob('*.request'))), 1)
        self.assertEqual(len(list((self.root / 'jobs').glob('*.tmp'))), 0)      # submitted atomically: no half-written .tmp left behind

    def test_ctl_ok_and_exit_codes(self):
        ctl = self.state / 'ctl'
        answers = iter(['ok', 'failed', 'timeout', 'refused'])

        def proxy():   # plays the proxy: take the .cmd by rename, answer with .done
            n = 0
            while n < 4:
                for p in sorted(ctl.glob('*.cmd')) if ctl.is_dir() else []:
                    taken = p.with_name(p.name + '.taken'); os.replace(p, taken)
                    (ctl / (p.stem + '.done')).write_text(json.dumps({'id': p.stem, 'status': next(answers)}))
                    n += 1
                time.sleep(0.05)
        t = threading.Thread(target=proxy, daemon=True); t.start()
        codes = [run(['--adapter', str(self.adapter), 'ctl', 'me', 'ping', '20'], self.env).returncode for _ in range(4)]
        self.assertEqual(codes, [0, 1, 3, 2])

    def test_ctl_dir_comes_from_the_mod_ini_not_the_watcher_root(self):
        # J3 review 5: a changed dev.ctl_dir used to time out every call; now the requests go where the proxy reads them
        elsewhere = Path(self.tmp.name) / 'ctl_elsewhere'
        (self.game / 'mod.ini').write_text(f'[dev]\nctl_dir={elsewhere}\n')
        r = run(['--adapter', str(self.adapter), 'ctl', 'me', 'ping', '1'], self.env)
        self.assertEqual(r.returncode, 124)
        self.assertEqual(len(list(elsewhere.glob('*.cmd.expired'))), 1)
        self.assertFalse((self.state / 'ctl').exists())

    def test_ctl_without_an_ini_uses_the_registered_default(self):
        # the game repo's registered default (registries/config_keys.jsonl), here a fixture repo whose default is a temp folder: the null
        # game's own default is a drive path (C:\nullgame_pc\ctl) that a run on a PC would create and leave behind
        repo = Path(self.tmp.name) / 'repo'
        default = Path(self.tmp.name) / 'default_ctl'
        (repo / 'registries').mkdir(parents=True)
        (repo / 'registries' / 'config_keys.jsonl').write_text(json.dumps({'id': 'dev.ctl_dir', 'default': str(default)}) + '\n')
        (self.game / 'mod.ini').unlink()
        r = run(['--adapter', str(self.adapter), 'ctl', 'me', 'ping', '1'], dict(self.env, WSP_GAME_ROOT=str(repo)))
        self.assertIn(bash_path(default), r.stderr)
        self.assertEqual(r.returncode, 124)   # the request waited in the default folder (no answer)
        self.assertEqual(len(list(default.glob('*.cmd.expired'))), 1)

    def test_ctl_no_answer_withdraws_the_request(self):
        # a request nobody answered must not stay as .cmd: the proxy would run it on its next launch (a stale exit or reset)
        r = run(['--adapter', str(self.adapter), 'ctl', 'me', 'exit', '1'], self.env)
        self.assertEqual(r.returncode, 124)
        self.assertIn('withdrawn', r.stderr)
        ctl = self.state / 'ctl'
        self.assertEqual(list(ctl.glob('*.cmd')), [])
        self.assertEqual(len(list(ctl.glob('*.cmd.expired'))), 1)

    def test_owner_is_added_to_control_jobs_only_when_missing(self):
        self.watcher({'status': 'ok', 'exit': 0})
        run(['--adapter', str(self.adapter), 'me', '-', '20'], self.env, stdin='launch\n')
        run(['--adapter', str(self.adapter), 'me', '-', '20'], self.env, stdin='profile proxy-dxvk owner=other\n')
        run(['--adapter', str(self.adapter), 'me', '-', '20'], self.env, stdin='noop\n')
        bodies = [b for _, b in self.w.seen]
        self.assertEqual(bodies[0].strip(), 'launch owner=me')
        self.assertEqual(bodies[1].strip(), 'profile proxy-dxvk owner=other')
        self.assertEqual(bodies[2].strip(), 'noop')

    def test_lock_take_refresh_release(self):
        a = ['--adapter', str(self.adapter)]
        r = run(a + ['lock', 'me', 'sess1', 'load a battle', '30'], self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        line = (self.root / 'game.lock').read_text().strip()
        self.assertRegex(line, r'^owner=me session=sess1 purpose=load a battle started=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ hang_s=30$')
        self.assertEqual(run(a + ['lock', 'other', 's', 'p'], self.env).returncode, 2)         # held, fresh: refused
        os.utime(self.root / 'game.lock', (time.time() - 1300, time.time() - 1300))
        self.assertEqual(run(a + ['lock', 'other', 's', 'p'], self.env).returncode, 0)         # stale: may be taken over
        self.assertEqual(run(a + ['unlock', 'me'], self.env).returncode, 2)                      # not the owner
        self.assertEqual(run(a + ['touch'], self.env).returncode, 0)
        self.assertEqual(run(a + ['unlock', 'other'], self.env).returncode, 0)
        self.assertFalse((self.root / 'game.lock').exists())
        self.assertEqual(len(list((self.root / '_to_delete').glob('game.lock.released_other_*'))), 1)

    def test_lock_is_an_exclusive_create(self):
        # J2 L3: of agents racing for a free lock, exactly one wins; the losers are refused, never silently overwritten
        a = ['--adapter', str(self.adapter)]
        for rnd in range(3):
            procs = [subprocess.Popen([BASH, str(JOB), *a, 'lock', f'r{rnd}a{i}', 's', 'p'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, env=job_env())
                     for i in range(4)]
            codes = [p.communicate(timeout=60) and p.returncode for p in procs]   # communicate closes the pipes
            self.assertEqual(sorted(codes), [0, 2, 2, 2], codes)
            winner = f'r{rnd}a{codes.index(0)}'
            self.assertIn(f'owner={winner} ', (self.root / 'game.lock').read_text())
            self.assertEqual(run(a + ['unlock', winner], self.env).returncode, 0)

    def test_a_stale_lock_is_moved_aside_before_it_is_taken(self):
        a = ['--adapter', str(self.adapter)]
        self.assertEqual(run(a + ['lock', 'old', 's', 'p'], self.env).returncode, 0)
        os.utime(self.root / 'game.lock', (time.time() - 1300, time.time() - 1300))
        self.assertEqual(run(a + ['lock', 'new', 's', 'p'], self.env).returncode, 0)
        self.assertIn('owner=new ', (self.root / 'game.lock').read_text())
        self.assertEqual(len(list((self.root / '_to_delete').glob('game.lock.stale_old_*'))), 1)
        self.assertEqual(run(a + ['lock', 'new', 's2', 'refresh'], self.env).returncode, 0)   # its own lock: rewritten in place
        self.assertIn('session=s2 ', (self.root / 'game.lock').read_text())

    def test_status_reads_heartbeat(self):
        a = ['--adapter', str(self.adapter)]
        (self.root / 'watcher.status').write_text('{"version":"1"}')
        (self.root / 'watcher.alive').write_text('x')
        self.assertEqual(run(a + ['status'], self.env).returncode, 0)
        os.utime(self.root / 'watcher.alive', (time.time() - 100, time.time() - 100))
        r = run(a + ['status'], self.env)
        self.assertEqual(r.returncode, 1)
        self.assertIn('not running', r.stderr)


if __name__ == '__main__':
    unittest.main()
