"""Host tests for proxy/tools/pc_deploy.py (manifest, stale-resend guard, install, byte-exact uninstall, config edits, closed check)
on a fake game folder. Runs in `wsc gates` (tests gate).

Ported from the first consumer's `tests/test_pc_deploy.py` at 6cbb9e9 (B17). The game repo is a temp copy of the null game
(proxy/tests/null_game) with the dev side a kit carries added (a `lua/` folder with wsp.lua, autostart.lua and wrappers.txt, and a
`kit_packs` builder that cannot read the game's packs, as on CI); the fake game folder takes its exe name, config file and mod folder from
the null identity (Game.exe, nullgame.ini, nullgame), and `pd.ROOT` points at the copy for every test."""
import atexit
import importlib.util
import hashlib
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pc_deploy', ROOT / 'proxy/tools/pc_deploy.py')
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)
sys.path.insert(0, str(ROOT / 'proxy' / 'tools'))
build_dev_pack = importlib.import_module('build_dev_pack')   # the module pd.build_kit imports by name; its ROOT is pointed at the fixture game too


def fixture_game():
    """A temp game repo: the null game plus the dev Lua and a fixed-sky pack builder that cannot read the game's packs (CI's case)."""
    tmp = Path(tempfile.mkdtemp(prefix='wsc_test_pc_deploy_'))
    atexit.register(shutil.rmtree, tmp, True)
    game = tmp / 'repo'
    shutil.copytree(ROOT / 'proxy' / 'tests' / 'null_game', game)
    lua = game / 'proxy' / 'null' / 'lua'
    lua.mkdir()
    (lua / 'wsp.lua').write_text('-- the Lua bridge (fixture)\nreturn {}\n', encoding='utf-8')
    (lua / 'autostart.lua').write_text('-- autostart (fixture)\n', encoding='utf-8')
    (lua / 'wrappers.txt').write_text('# entry | context\ndata/script/frontend.luac | frontend\n', encoding='utf-8')
    (game / 'tools').mkdir()
    (game / 'tools' / 'build_fixed_sky_pack.py').write_text(
        'def build(games):\n    raise SystemExit("the game packs are not readable here")\n', encoding='utf-8')
    had = game / 'harness' / 'null' / 'adapter.json'
    a = json.loads(had.read_text(encoding='utf-8'))
    a['kit_packs'] = [{'id': 'fixed_sky', 'module': 'tools/build_fixed_sky_pack.py', 'input': 'packs'}]
    had.write_text(json.dumps(a, indent=2) + '\n', encoding='utf-8')
    return game


GAME = fixture_game()


def use_fixture_game(test):
    """Point pc_deploy and build_dev_pack at the fixture game for one test; the env cannot pick another adapter."""
    for p in (mock.patch.object(pd, 'ROOT', GAME), mock.patch.object(build_dev_pack, 'ROOT', GAME),
              mock.patch.dict(os.environ)):
        p.start()
        test.addCleanup(p.stop)
    for k in ('WSP_GAME_ROOT', 'WSP_PROXY_ADAPTER', 'HARNESS_ADAPTER'):
        os.environ.pop(k, None)


class TasklistSaysRunning:
    """The lowest layer reports the game running (J57): pd sees os.name == 'nt' and `tasklist` printing Game.exe, whatever the host.
    Only pd's own `os` name is swapped (a stand-in that forwards everything else), so pathlib and the rest of the host are untouched."""
    CSV = '"System","4","Services","0","144 K"\n"Game.exe","1234","Console","1","900,000 K"\n'

    class _Nt:
        name = 'nt'
        def __getattr__(self, attr):
            return getattr(os, attr)

    def __enter__(self):
        real_run = subprocess.run
        def run(cmd, *a, **kw):
            if cmd and cmd[0] == 'tasklist':
                return subprocess.CompletedProcess(cmd, 0, stdout=self.CSV, stderr='')
            return real_run(cmd, *a, **kw)
        self.patches = [mock.patch.object(pd, 'os', self._Nt()), mock.patch.object(pd.subprocess, 'run', run)]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()


class Deploy(unittest.TestCase):
    def setUp(self):
        # J57: install/uninstall ask require_closed -> running_check -> windows_images -> `tasklist` about the REAL Game.exe, so the
        # tests failed on the PC whenever the game ran. The process list reports nothing running; require_closed and running_check stay
        # real (test_the_guard_still_refuses_a_running_game_without_this_patch, test_running_check).
        self.real_windows_images = pd.windows_images
        patch = mock.patch.object(pd, 'windows_images', lambda: set())
        patch.start()
        self.addCleanup(patch.stop)
        use_fixture_game(self)
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.game, self.state, self.kits, self.src = t / 'game', t / 'state', t / 'kits', t / 'src'
        (self.game / 'data').mkdir(parents=True)
        (self.game / 'Game.exe').write_bytes(b'MZ' + os.urandom(4000))
        (self.game / 'data' / 'big.pack').write_bytes(os.urandom(3000))
        (self.game / 'empty_dir').mkdir()
        self.src.mkdir()
        (self.src / 'd3d9.dll').write_bytes(b'MZproxy' + os.urandom(100))
        (self.src / 'd3d9_dxvk.dll').write_bytes(b'MZdxvk' + os.urandom(100))
        (self.src / 'LICENSE.dxvk.txt').write_text('zlib')
        # a fixture identity for the fake exe, passed in (J18: never the real sha)
        self.ident = t / 'identity.json'
        ident = json.loads((GAME / 'proxy/null/identity.json').read_text(encoding='utf-8'))
        ident['sha1'] = hashlib.sha1((self.game / 'Game.exe').read_bytes()).hexdigest()
        self.ident.write_text(json.dumps(ident), encoding='utf-8')
        self.kit = pd.build_kit(self.kits, dll=self.src / 'd3d9.dll', dxvk_dir=self.src, build_id='test', identity=self.ident)

    def tearDown(self):
        self.tmp.cleanup()

    def test_kit_manifest(self):
        man, bad = pd.verify_kit(self.kit)
        self.assertEqual(bad, [])
        paths = {e['path'] for e in man['files']}
        self.assertTrue({'d3d9.dll', 'nullgame.ini', 'nullgame/dxvk/d3d9_dxvk.dll', 'nullgame/LICENSE.dxvk.txt'} <= paths)
        # the dev side (J3): the wrapper pack and the bridge's Lua, all inside the owned mod folder
        self.assertIn('nullgame/packs/zz_nullgame_dev.pack', paths)
        self.assertIn('nullgame/lua/wsp.lua', paths)
        self.assertTrue(all(p in ('d3d9.dll', 'nullgame.ini') or p.startswith('nullgame/') for p in paths))
        for e in man['files']:
            self.assertTrue(e['staged'].startswith(e['sha256'][:12] + '__'))   # unique per content
        self.assertTrue((self.kit / 'pc_deploy.py').exists())

    def sky_kit(self, build):
        """A kit whose fixed-sky step runs `build` instead of reading the game's packs (J45)."""
        import sys
        import types
        fake = types.SimpleNamespace(build=build)
        with mock.patch.dict(sys.modules, {'build_fixed_sky_pack': fake}):
            return pd.build_kit(self.kits, dll=self.src / 'd3d9.dll', dxvk_dir=self.src, build_id=f'sky{time.time_ns()}', identity=self.ident)

    def test_failing_fixture_a_kit_without_the_sky_pack_says_so_in_its_manifest(self):
        # J44 review 3: the kit only printed a warning; the launch then ran with a rule naming a pack that was not there
        def no_packs(games):
            raise SystemExit('the game packs are not readable here')
        kit = self.sky_kit(no_packs)
        man = json.loads((kit / 'manifest.json').read_text())
        self.assertEqual(man['packs']['fixed_sky'], {'present': False, 'reason': 'the game packs are not readable here'})
        self.assertFalse(any(e['path'].endswith('fixed_sky.pack') for e in man['files']))
        pd.install(kit, self.game, self.state, assume_closed=True)
        rec = json.loads((self.state / 'install.json').read_text())
        self.assertEqual(rec['packs']['fixed_sky']['present'], False)   # ctl.py Pc.launch reads it from the install record

    def test_a_kit_with_the_sky_pack_records_its_sha(self):
        pack = self.src / 'zz_nullgame_fixed_sky.pack'
        pack.write_bytes(b'PFH4sky')
        kit = self.sky_kit(lambda games: (pack, None))
        man = json.loads((kit / 'manifest.json').read_text())
        self.assertEqual(man['packs']['fixed_sky'], {'present': True, 'path': 'nullgame/packs/zz_nullgame_fixed_sky.pack',
                                            'sha256': hashlib.sha256(b'PFH4sky').hexdigest()})
        self.assertIn(man['packs']['fixed_sky']['path'], {e['path'] for e in man['files']})

    def test_stale_resend_refused(self):
        man = json.loads((self.kit / 'manifest.json').read_text())
        (self.kit / man['files'][0]['staged']).write_bytes(b'old cached copy')
        with self.assertRaises(SystemExit) as e:
            pd.install(self.kit, self.game, self.state, assume_closed=True)
        self.assertIn('stale or partial', str(e.exception))
        self.assertFalse((self.game / 'd3d9.dll').exists())   # nothing installed

    def test_install_uninstall_byte_exact(self):
        before = pd.snapshot(self.game)
        pd.install(self.kit, self.game, self.state)
        self.assertEqual(pd.status(self.game, self.state), 0)
        # what the DLL and DXVK write at runtime, all inside the owned paths
        (self.game / 'nullgame' / 'logs').mkdir(parents=True)
        (self.game / 'nullgame' / 'logs' / 'proxy.log').write_text('... process detach (process exit)\n')
        (self.game / 'nullgame' / 'dxvk' / 'Game_d3d9.log').write_text('dxvk')
        self.assertEqual(pd.set_keys(self.game, ['proxy.backend=system'], 'nullgame.ini', self.state), 0)
        self.assertTrue(pd.uninstall(self.game, self.state))
        self.assertEqual(pd.diff_snapshots(before, pd.snapshot(self.game)), [])
        moved = list((self.state / '_to_delete').rglob('proxy.log'))
        self.assertEqual(len(moved), 1)   # moved, never deleted
        self.assertFalse((self.state / 'install.json').exists())

    def test_foreign_file_backed_up_and_restored(self):
        (self.game / 'd3d9.dll').write_bytes(b'someone else\'s d3d9 wrapper')
        before = pd.snapshot(self.game)
        pd.install(self.kit, self.game, self.state)
        self.assertNotEqual((self.game / 'd3d9.dll').read_bytes(), b'someone else\'s d3d9 wrapper')
        self.assertTrue(pd.uninstall(self.game, self.state))
        self.assertEqual((self.game / 'd3d9.dll').read_bytes(), b'someone else\'s d3d9 wrapper')
        self.assertEqual(pd.diff_snapshots(before, pd.snapshot(self.game)), [])

    def test_sync_lua_changes_only_what_differs_and_uninstalls_byte_exact(self):
        """J4: sync-lua copies a changed dev Lua file with a unique staged name and a sha check, records it, and the uninstall still restores everything."""
        before = pd.snapshot(self.game)
        pd.install(self.kit, self.game, self.state)
        self.assertEqual(pd.sync_lua(self.game, self.state, assume_closed=True), [])   # nothing differs right after an install
        victim = self.game / 'nullgame' / 'lua' / 'autostart.lua'
        victim.write_bytes(b'-- edited on the PC')
        self.assertEqual(pd.sync_lua(self.game, self.state, assume_closed=True, dry_run=True), ['nullgame/lua/autostart.lua'])
        self.assertEqual(victim.read_bytes(), b'-- edited on the PC')   # a dry run changes nothing
        self.assertEqual(pd.sync_lua(self.game, self.state, assume_closed=True), ['nullgame/lua/autostart.lua'])
        self.assertEqual(hashlib.sha256(victim.read_bytes()).hexdigest(), pd.sha256_file(pd.ROOT / 'proxy' / 'null' / 'lua' / 'autostart.lua'))
        self.assertEqual(list(victim.parent.glob('*.tmp')), [])   # no staged leftovers
        rec = json.loads((self.state / 'install.json').read_text())
        self.assertEqual([h['action'] for h in rec['history'][-2:]], ['sync-lua', 'sync-lua exe check'])
        self.assertEqual(rec['history'][-1]['exe_verdict'], 'vanilla')
        self.assertEqual(pd.status(self.game, self.state), 0)
        self.assertTrue(pd.uninstall(self.game, self.state))
        self.assertEqual(pd.diff_snapshots(before, pd.snapshot(self.game)), [])

    def test_sync_lua_needs_an_install(self):
        with self.assertRaises(SystemExit):
            pd.sync_lua(self.game, self.state, assume_closed=True)

    def test_reinstall_then_uninstall(self):
        before = pd.snapshot(self.game)
        pd.install(self.kit, self.game, self.state)
        (self.src / 'd3d9.dll').write_bytes(b'MZproxy v2')
        kit2 = pd.build_kit(self.kits, dll=self.src / 'd3d9.dll', dxvk_dir=self.src, build_id='test2', identity=self.ident)
        pd.install(kit2, self.game, self.state)
        self.assertEqual((self.game / 'd3d9.dll').read_bytes(), b'MZproxy v2')
        self.assertTrue(pd.uninstall(self.game, self.state))
        self.assertEqual(pd.diff_snapshots(before, pd.snapshot(self.game)), [])

    def test_failed_install_still_uninstalls(self):
        """A copy failing half-way (disk full, file locked) must leave a record the uninstall can restore from (review of J1)."""
        (self.game / 'd3d9.dll').write_bytes(b'someone else\'s d3d9 wrapper')
        before = pd.snapshot(self.game)
        real, calls = pd.shutil.copyfile, []
        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError('disk full')
            return real(src, dst)
        pd.shutil.copyfile = flaky
        try:
            with self.assertRaises(OSError):
                pd.install(self.kit, self.game, self.state)
        finally:
            pd.shutil.copyfile = real
        self.assertTrue((self.state / 'install.json').exists())
        self.assertTrue(pd.uninstall(self.game, self.state))
        self.assertEqual((self.game / 'd3d9.dll').read_bytes(), b'someone else\'s d3d9 wrapper')
        self.assertEqual(pd.diff_snapshots(before, pd.snapshot(self.game)), [])

    def test_stray_file_reported(self):
        pd.install(self.kit, self.game, self.state)
        (self.game / 'Game_d3d9.log').write_text('dxvk wrote into the game folder')   # what the env redirect prevents
        self.assertFalse(pd.uninstall(self.game, self.state))
        self.assertTrue((self.game / 'Game_d3d9.log').exists())   # not ours: reported, never touched

    # ---- J18: the exe stays vanilla (row 28), no .git in a game folder (row 32), nothing foreign in the game folder (row 31) ----------
    def test_kit_carries_the_identity_copy(self):
        self.assertEqual((self.kit / 'exe_identity.json').read_bytes(), self.ident.read_bytes())
        man, bad = pd.verify_kit(self.kit)
        self.assertEqual(bad, [])
        (self.kit / 'exe_identity.json').write_text('{"sha1": "0"}')
        self.assertTrue(any('exe_identity.json' in b for b in pd.verify_kit(self.kit)[1]))

    def test_a_mismatched_exe_refuses_the_install_and_changes_nothing(self):
        before = pd.snapshot(self.game)
        (self.game / 'Game.exe').write_bytes(b'MZ patched by someone')
        before = pd.snapshot(self.game)
        with self.assertRaises(SystemExit) as e:
            pd.install(self.kit, self.game, self.state)
        msg = str(e.exception)
        for want in ('MISMATCH', 'not the vanilla build', 'nothing was installed', 'exe_info.py'):
            self.assertIn(want, msg)
        self.assertEqual(pd.diff_snapshots(before, pd.snapshot(self.game)), [])
        self.assertFalse((self.state / 'install.json').exists())

    def test_install_records_the_exe_verdict(self):
        rec = pd.install(self.kit, self.game, self.state)
        chk = [h for h in rec['history'] if h['action'] == 'install exe check']
        self.assertEqual(chk[-1]['exe_verdict'], 'vanilla')
        self.assertEqual(chk[-1]['exe_sha1'], json.loads(self.ident.read_text())['sha1'])

    def test_set_and_uninstall_never_refuse_but_fail_loudly_on_a_changed_exe(self):
        pd.install(self.kit, self.game, self.state)
        (self.game / 'Game.exe').write_bytes(b'MZ changed after the install')
        self.assertEqual(pd.set_keys(self.game, ['proxy.backend=system'], 'nullgame.ini', self.state), 1)
        self.assertEqual(pd.status(self.game, self.state), 1)
        self.assertFalse(pd.uninstall(self.game, self.state))   # still uninstalled, reported as a failure
        self.assertFalse((self.game / 'd3d9.dll').exists())
        hist = json.loads(next((self.state / 'history').glob('install_*.json')).read_text())['history']
        self.assertEqual([h['exe_verdict'] for h in hist if h['action'].endswith('exe check')], ['vanilla', 'MISMATCH', 'MISMATCH'])

    def test_sync_lua_checks_the_exe_after_and_fails_loudly(self):
        """J18 review: row 28 says after every install or sync; sync-lua writes into the game folder too."""
        pd.install(self.kit, self.game, self.state)
        (self.game / 'Game.exe').write_bytes(b'MZ changed after the install')
        with self.assertRaises(SystemExit) as e:
            pd.sync_lua(self.game, self.state, assume_closed=True)
        self.assertIn('not vanilla', str(e.exception))
        rec = json.loads((self.state / 'install.json').read_text())
        self.assertEqual(rec['history'][-1]['action'], 'sync-lua exe check')
        self.assertEqual(rec['history'][-1]['exe_verdict'], 'MISMATCH')

    def test_a_foreign_file_fails_status_and_config_files_do_not(self):
        pd.install(self.kit, self.game, self.state)
        (self.game / 'dxvk.conf').write_text('d3d9.maxFrameRate = 60')            # a game-anchored config file: a profile writes it
        (self.game / 'nullgame' / 'logs').mkdir(parents=True)
        (self.game / 'nullgame' / 'logs' / 'proxy.log').write_text('x')   # inside the owned set
        self.assertEqual(pd.status(self.game, self.state), 0)
        (self.game / 'data' / 'big.pack').write_bytes(b'changed by hand')
        (self.game / 'notes.txt').write_text('an experiment outside _scratch')
        fails, lines = pd.pc_rules(self.game, self.state, json.loads(self.ident.read_text()))
        self.assertEqual(fails, 1)
        text = '\n'.join(lines)
        self.assertIn('foreign: 2 file(s)', text)
        self.assertIn('added   notes.txt', text)
        self.assertIn('changed data/big.pack', text)
        self.assertEqual(pd.status(self.game, self.state), 1)

    def test_a_git_folder_in_a_parent_fails_status(self):
        pd.install(self.kit, self.game, self.state)
        self.assertEqual(pd.status(self.game, self.state), 0)
        (self.game.parent / '.git').mkdir()
        self.assertEqual(pd.git_dirs(self.game), [str(self.game.resolve().parent / '.git')])
        self.assertEqual(pd.status(self.game, self.state), 1)
        (self.game.parent / '.git').rmdir()
        (self.game / 'data' / '.git').mkdir()   # below the game folder is the snapshot's business: a foreign file, not this check
        self.assertEqual(pd.git_dirs(self.game), [])

    def test_status_without_an_install_still_checks_the_exe(self):
        with mock.patch.object(pd, 'default_identity', return_value=json.loads(self.ident.read_text())):
            self.assertEqual(pd.status(self.game, self.state), 0)
            (self.game / 'Game.exe').write_bytes(b'MZ other')
            self.assertEqual(pd.status(self.game, self.state), 1)
        with mock.patch.object(pd, 'default_identity', return_value=None):
            self.assertEqual(pd.status(self.game, self.state), 1)   # cannot check is not a pass

    def test_running_check(self):
        # the log fallback (no watcher, no process list) on every OS: the provider is injected, not taken from the host (J22)
        log = self.game / 'nullgame' / 'logs' / 'proxy.log'
        log.parent.mkdir(parents=True)
        log.write_text('2026-10-28T20:00:00.000Z [INFO ] [t1] init done\n')
        none = lambda: None
        self.assertIn('may be running', pd.running_check(self.game, 'nullgame', 'Game.exe', images=none))
        self.assertEqual(pd.running_check(self.game, 'nullgame', 'Game.exe', now=time.time() + 3600, images=none), '')
        log.write_text('x\n2026-10-28T20:00:00.000Z [INFO ] [t1] process detach (process exit)\n')
        self.assertEqual(pd.running_check(self.game, 'nullgame', 'Game.exe', images=none), '')
        log.write_text('init done\n')
        with mock.patch.object(pd, 'windows_images', none):   # install() calls running_check with the default provider
            with self.assertRaises(SystemExit):
                pd.install(self.kit, self.game, self.state)
        # with a process list the log is not read: tasklist decides
        self.assertEqual(pd.running_check(self.game, 'nullgame', 'Game.exe', images=lambda: {'explorer.exe'}), '')
        self.assertEqual(pd.running_check(self.game, 'nullgame', 'Game.exe', images=lambda: {'game.exe'}),
                         'tasklist: Game.exe is running')

    def test_install_ignores_a_running_game_with_the_setup_patch_in_force(self):
        """J57: the real game being open (simulated at the lowest layer) cannot fail the Deploy tests."""
        with TasklistSaysRunning():
            pd.install(self.kit, self.game, self.state)
            self.assertEqual(pd.status(self.game, self.state), 0)
            pd.uninstall(self.game, self.state)

    def test_the_guard_still_refuses_a_running_game_without_this_patch(self):
        with mock.patch.object(pd, 'windows_images', self.real_windows_images), TasklistSaysRunning():
            with self.assertRaisesRegex(SystemExit, r'refusing: tasklist: Game\.exe is running'):
                pd.install(self.kit, self.game, self.state)
        self.assertFalse((self.game / 'd3d9.dll').exists())   # refused before anything was installed

    def test_edit_ini(self):
        t = '; c\r\n[proxy]\r\n; d\r\nbackend=dxvk\r\nenabled=1\r\n'
        o = pd.edit_ini(t, {'proxy.backend': 'system', 'proxy.exe_guard_force_mismatch': '1', 'other.x': '2'})
        self.assertEqual(o, '; c\r\n[proxy]\r\nexe_guard_force_mismatch=1\r\n; d\r\nbackend=system\r\nenabled=1\r\n\r\n[other]\r\nx=2\r\n')

    def test_resolve_bare_keys(self):
        t = '[proxy]\nbackend=dxvk\nenabled=1\n[other]\nenabled=0\n'
        self.assertEqual(pd.resolve_keys(t, {'backend': 'system', 'other.enabled': '1'}),
                         {'proxy.backend': 'system', 'other.enabled': '1'})
        with self.assertRaisesRegex(SystemExit, 'ambiguous'):
            pd.resolve_keys(t, {'enabled': '1'})
        with self.assertRaisesRegex(SystemExit, 'not in the file'):
            pd.resolve_keys(t, {'nope': '1'})

    def test_snapshot_big_files_by_mtime(self):
        a = pd.snapshot(self.game, big=1000)
        self.assertIsNone(a['data/big.pack']['sha256'])
        os.utime(self.game / 'data' / 'big.pack', ns=(0, 10**18))
        self.assertEqual(pd.diff_snapshots(a, pd.snapshot(self.game, big=1000)), ['touched data/big.pack (large file: same size, other mtime)'])


class HarnessKit(unittest.TestCase):
    """The watcher kit (J2): unique ids, sha-checked manifest, CRLF/ASCII guard for PC scripts, and the install-time game check that
    asks the watcher (else tasklist) which processes run."""

    def setUp(self):
        use_fixture_game(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_kit_manifest_and_stale_guard(self):
        kit = pd.build_harness_kit(self.t / 'kits', build_id='test')
        man, bad = pd.verify_harness_kit(kit)
        self.assertEqual(bad, [])
        self.assertEqual(man['kind'], 'harness')
        self.assertTrue(man['kit_id'].startswith('harness_'))
        paths = {e['path'] for e in man['files']}
        for want in ('src/watcher.ps1', 'src/watch.cmd', 'src/update.ps1', 'src/adapter.json', 'profiles/vanilla/profile.json',
                     'profiles/vanilla/mod_ini.absent', 'profiles/proxy-dxvk/mod_ini.set'):
            self.assertIn(want, paths)
        self.assertEqual({k['name'] for k in man['kit_files']}, {'install.ps1', 'Install watcher.cmd', 'Uninstall watcher.cmd', 'job.sh', 'adapter.json'})
        self.assertRegex(man['watcher_version'], r'^\d+\.\d+\.\d+')
        self.assertTrue(man['watcher_root'].endswith('\\watcher'))
        for e in man['files']:
            self.assertTrue(e['staged'].startswith(e['sha256'][:12] + '__'))
        # every Windows script in the kit is CRLF and ASCII, whatever the checkout had
        for e in man['files']:
            if e['path'].endswith(('.ps1', '.cmd')):
                b = (kit / e['staged']).read_bytes()
                self.assertNotIn(b'\n', b.replace(b'\r\n', b''), e['path'])
                b.decode('ascii')
        # a stale resend of one staged file is caught
        (kit / man['files'][0]['staged']).write_bytes(b'old cached copy')
        self.assertTrue(pd.verify_harness_kit(kit)[1])
        (kit / 'install.ps1').write_bytes(b'old installer')
        self.assertTrue(any('install.ps1' in x for x in pd.verify_harness_kit(kit)[1]))

    def test_harness_kit_carries_the_identity_copy(self):
        kit = pd.build_harness_kit(self.t / 'kits', build_id='test')
        man, bad = pd.verify_harness_kit(kit)
        self.assertEqual(bad, [])
        e = next(e for e in man['files'] if e['path'] == 'src/exe_identity.json')
        self.assertEqual((kit / e['staged']).read_bytes(), (GAME / 'proxy/null/identity.json').read_bytes())

    def test_new_id_every_time(self):
        a = pd.build_harness_kit(self.t / 'kits', build_id='a')
        b = pd.build_harness_kit(self.t / 'kits', build_id='b')
        self.assertNotEqual(a.name, b.name)

    def test_norm_for_pc(self):
        self.assertEqual(pd.norm_for_pc('x.cmd', b'a\nb\r\nc\n'), b'a\r\nb\r\nc\r\n')
        self.assertEqual(pd.norm_for_pc('x.json', b'a\nb\n'), b'a\nb\n')
        with self.assertRaises(SystemExit) as e:
            pd.norm_for_pc('x.ps1', 'caf\u00e9'.encode('utf-8'))
        self.assertIn('non-ASCII', str(e.exception))

    def _status(self, procs, age=1.0, alive=True):
        w = self.t / 'state' / 'watcher'
        w.mkdir(parents=True, exist_ok=True)
        (w / 'watcher.status').write_text(json.dumps({'processes': procs}), encoding='utf-8')
        if alive:
            (w / 'watcher.alive').write_text('x')
            os.utime(w / 'watcher.alive', (time.time() - age, time.time() - age))
        return self.t / 'state'

    def test_running_check_asks_the_watcher_for_both_titles(self):
        game = self.t / 'game'
        game.mkdir()
        st = self._status([{'image': 'Other.exe', 'pid': 42}])
        why = pd.running_check(game, 'nullgame', 'Game.exe', state=st, other_exes=['Other.exe'])
        self.assertIn('Other.exe (pid 42)', why)
        st = self._status([{'image': 'Game.exe', 'pid': 7}])
        self.assertIn('Game.exe (pid 7)', pd.running_check(game, 'nullgame', 'Game.exe', state=st, other_exes=['Other.exe']))
        st = self._status([])
        self.assertEqual(pd.running_check(game, 'nullgame', 'Game.exe', state=st, other_exes=['Other.exe']), '')

    def test_stale_watcher_cannot_vouch_and_no_watcher_falls_back(self):
        game = self.t / 'game'
        game.mkdir()
        st = self._status([], age=120)
        self.assertIn('heartbeat is', pd.running_check(game, 'm', 'Game.exe', state=st))
        # the status file says nothing was running but nobody is watching: refuse rather than guess
        with mock.patch.object(pd, 'windows_images', lambda: None):   # off Windows: the log heuristic
            self.assertEqual(pd.running_check(game, 'm', 'Game.exe', state=self.t / 'nowatcher'), '')
            log = game / 'm' / 'logs' / 'proxy.log'
            log.parent.mkdir(parents=True)
            log.write_text('launch x\nstarted\n')
            self.assertIn('may be running', pd.running_check(game, 'm', 'Game.exe', state=self.t / 'nowatcher'))

    def test_no_watcher_on_windows_asks_tasklist(self):
        game = self.t / 'game'
        game.mkdir()
        with mock.patch.object(pd, 'windows_images', lambda: {'explorer.exe', 'other.exe'}):
            self.assertEqual(pd.running_check(game, 'm', 'Game.exe', state=self.t / 'nowatcher', other_exes=['Other.exe']),
                             'tasklist: Other.exe is running')
        with mock.patch.object(pd, 'windows_images', lambda: {'explorer.exe'}):
            self.assertEqual(pd.running_check(game, 'm', 'Game.exe', state=self.t / 'nowatcher'), '')
        def boom():
            raise OSError('no tasklist')
        with mock.patch.object(pd, 'windows_images', boom):
            self.assertIn('tasklist failed', pd.running_check(game, 'm', 'Game.exe', state=self.t / 'nowatcher'))
        if os.name == 'nt':   # the real one parses: this test process is in it
            self.assertTrue(any(i.startswith('python') for i in pd.windows_images()))

    def test_send_copies_sha_checked_and_refuses_a_reused_id(self):
        kit = pd.build_harness_kit(self.t / 'kits', build_id='test')
        state = self.t / 'state'
        dest = pd.send_kit(kit, state)
        self.assertEqual(dest, state / 'kits' / kit.name)
        self.assertEqual(pd.verify_harness_kit(dest)[1], [])
        self.assertEqual(sorted(p.name for p in dest.iterdir()), sorted(p.name for p in kit.iterdir()))
        self.assertEqual([p.name for p in (state / 'kits').iterdir()], [kit.name])   # no .partial left behind
        with self.assertRaisesRegex(SystemExit, 'never reused'):
            pd.send_kit(kit, state)
        staged = next(p for p in kit.iterdir() if '__src__' in p.name)
        staged.write_bytes(b'stale')
        with self.assertRaisesRegex(SystemExit, 'does not verify'):
            pd.send_kit(kit, self.t / 'state2')
        self.assertFalse((self.t / 'state2' / 'kits').exists())


class SetWaitsForRestore(unittest.TestCase):
    """B39 (W10): `pc_deploy set` waits for, or refuses on, the watcher's pending profile restore (profiles/_active.json), because a restore
    that runs after the set puts the old keys back (napoleon J9, run 20261101_j9pc)."""

    def setUp(self):
        use_fixture_game(self)
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.game, self.state = t / 'game', t / 'state'
        self.game.mkdir()
        self.ini = self.game / 'nullgame.ini'
        self.ini.write_bytes(b'[proxy]
backend=dxvk
')
        self.w = self.state / 'watcher'
        (self.w / 'profiles').mkdir(parents=True)
        (self.w / 'watcher.status').write_text(json.dumps({'processes': [], 'lock': {'owner': 'o1'}}), encoding='utf-8')
        (self.w / 'watcher.alive').write_text('x')
        self.active = self.w / 'profiles' / '_active.json'
        self.active.write_text(json.dumps({'name': 'j9-prof', 'owner': 'o1'}), encoding='utf-8')
        self.before = self.ini.read_bytes()

    def tearDown(self):
        self.tmp.cleanup()

    def set(self, **kw):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = pd.set_keys(self.game, ['proxy.backend=system'], 'nullgame.ini', kw.pop('state', self.state), **kw)
        return rc, out.getvalue()

    def test_a_pending_restore_refuses_and_leaves_the_ini_alone(self):
        sleeps = []
        with self.assertRaises(SystemExit) as e:
            self.set(wait_restore=3, sleep=sleeps.append)
        msg = str(e.exception)
        self.assertIn('j9-prof', msg)
        self.assertIn('owner o1', msg)
        self.assertIn('held by o1', msg)
        self.assertIn('not running', msg)
        self.assertEqual(sleeps, [1, 1, 1])   # polled once a second for the whole wait
        self.assertEqual(self.ini.read_bytes(), self.before)

    def test_wait_restore_zero_refuses_at_once(self):
        sleeps = []
        with self.assertRaises(SystemExit):
            self.set(wait_restore=0, sleep=sleeps.append)
        self.assertEqual(sleeps, [])
        self.assertEqual(self.ini.read_bytes(), self.before)

    def test_a_restore_that_finishes_during_the_wait_lets_set_write(self):
        threading.Timer(1.0, lambda: self.active.unlink()).start()
        t0 = time.time()
        rc, out = self.set(wait_restore=20)
        self.assertEqual(rc, 0)
        self.assertLess(time.time() - t0, 10)
        self.assertIn(b'backend=system', self.ini.read_bytes())

    def test_no_state_writes_and_says_it_cannot_see_a_restore(self):
        rc, out = self.set(state=None)
        self.assertEqual(rc, 0)
        self.assertIn('cannot be seen', out)
        self.assertIn(b'backend=system', self.ini.read_bytes())

    def test_a_state_without_a_watcher_folder_writes_and_says_so(self):
        rc, out = self.set(state=Path(self.tmp.name) / 'nowatcher')
        self.assertEqual(rc, 0)
        self.assertIn('cannot be seen', out)
        self.assertIn(b'backend=system', self.ini.read_bytes())

    def test_no_pending_restore_writes_as_before(self):
        self.active.unlink()
        rc, out = self.set()
        self.assertEqual(rc, 0)
        self.assertIn(b'backend=system', self.ini.read_bytes())

    def test_the_cli_has_wait_restore(self):
        r = subprocess.run([sys.executable, str(ROOT / 'proxy/tools/pc_deploy.py'), 'set', '--game', str(self.game), '--state', str(self.state),
                            '--config-file', 'nullgame.ini', '--wait-restore', '0', 'proxy.backend=system'],
                           capture_output=True, text=True, env={**os.environ, 'WSP_GAME_ROOT': str(pd.ROOT)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('j9-prof', r.stderr)
        self.assertEqual(self.ini.read_bytes(), self.before)


if __name__ == '__main__':
    unittest.main()
