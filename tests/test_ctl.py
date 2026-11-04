"""Host tests for harness/ctl.py (J4): the result contract, scenario and pose resolution, tolerance checks, settle, the refusals, and the
rules turned into tests: row 77 (no verb returns ok without a check) and row 78 (no key or click camera moves in scenario rows, generated
files or the acceptance script). No game: a fake transport plays the proxy, and the scenario rows and battle presets are neutral fixtures
in a temp folder.

Ported from the first consumer's `tests/test_ctl.py` at 6cbb9e9 (B17). Scenario ids, map names and the adapter are neutral; Rule78 runs its
rule over fixture rows and presets and over the core's acceptance script, while the scan of a game's own scenario rows and battle presets
stays in the game repo."""
import atexit
import importlib.util
import json
import math
import re
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ctl', ROOT / 'harness' / 'ctl.py')
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)

# the battle presets ctl.scenario_target looks for: land_small has one, hist has none (a historical row without a preset is refused)
_TMP = Path(tempfile.mkdtemp(prefix='wsc_test_ctl_'))
atexit.register(shutil.rmtree, _TMP, True)
BATTLES = _TMP / 'battles'
BATTLES.mkdir()
(BATTLES / 'land_small.txt').write_text('-- generated battle preset for land_small (fixture)\nmap NULL_MP_Flatlands\n', encoding='utf-8')

ROWS = {
    'land_small': {'id': 'land_small', 'kind': 'land', 'map': 'NULL_MP_Flatlands', 'camera_poses': {'wide': {'x': 1, 'y': 2, 'z': 3, 'yaw': 90, 'pitch': -30}}},
    'hist': {'id': 'hist', 'kind': 'historical', 'map': 'x'},
    'camp': {'id': 'camp', 'kind': 'campaign', 'map': 'null_campaign', 'save': 's'},
}
ADAPTER = {'game': 'nullgame', 'ctl': {'settle': {'frames': 3, 'quiet_ms': 1000, 'timeout_s': 5, 'ready_scenes': ['battle_deploy']},
                                        'routes': {'camera': {'status': 'unreachable', 'why': 'no api', 'fact': 'f.x'}}}}


class FakeGame:
    """Answers ctl lines; the frame counter advances 2 per state call."""
    def __init__(self, scene='battle_deploy', fail=None, here='frontend'):
        self.frame, self.scene, self.fail, self.lines, self.here = 0, scene, fail, [], here   # here: the scene until an autostart or reset

    def __call__(self, line, wait=0):
        self.lines.append(line)
        if line == 'state':
            self.frame += 2
            return 0, {'status': 'ok', 'state': {'scene': self.here or self.scene, 'frame': self.frame, 'scene_s': 5.0}}
        if self.fail and line.startswith(self.fail):
            return 1, {'status': 'failed', 'reason': 'engine said no'}
        if line.startswith('autostart'):
            self.here = None
            return 0, {'status': 'ok', 'map': 'NULL_MP_Flatlands', 'load_s': 3.0}
        if line.startswith('reset'):
            self.here = None if 'frontend' not in line else 'frontend'
            return 0, {'status': 'ok', 'autostart': {'map': 'NULL_MP_Flatlands', 'load_s': 2.5}}
        if line.startswith('perf'):
            return 0, {'status': 'ok', 'frames': 600, 'frame_ms': {'p50': 16.6, 'p99': 20.0, 'max': 30.0}, 'mem': {'va_used_mb': 1700}}
        return 1, None


def make(game=None, **kw):
    clock = [0.0]
    def now():
        clock[0] += 0.5
        return clock[0]
    return ctl.Ctl(game or FakeGame(), ROWS, ADAPTER, battles_dir=BATTLES, clock=now, sleep=lambda s: None, **kw)


class Contract(unittest.TestCase):
    def test_every_result_has_the_contract_fields(self):
        r = make().run('state')
        for k in ('status', 'reason', 'settle', 'check', 'evidence', 'start_utc', 'end_utc'):
            self.assertIn(k, r)
        self.assertEqual(ctl.exit_code(r), 0)

    def test_row77_ok_without_a_check_becomes_failed(self):
        r = ctl.make_result('x', 'ok')
        self.assertEqual(r['status'], 'failed')
        self.assertIn('rule 77', r['reason'])

    def test_row77_no_verb_returns_ok_without_a_check(self):
        """Every verb that can answer ok in the fake game carries a non-empty check; the verbs that cannot are refused with a reason."""
        c = make(shotter=lambda name: (f'/tmp/{name}.jpg', 1000))
        answers = [c.run('state'), c.run('scene', 'land_small'), c.run('shot', 'a'), c.run('reset'), c.run('reset', 'land_small'), c.run('perf', '10'),
                   c.run('cam', 'land_small:wide'), c.run('order', 'u', 'halt'), c.run('pause', 'on'), c.run('speed', '2')]
        for r in answers:
            if r['status'] == 'ok':
                self.assertTrue(r['check'], r['verb'])
            else:
                self.assertTrue(r['reason'], r['verb'])
        self.assertEqual([r['status'] for r in answers[:6]], ['ok'] * 6)

    def test_exit_codes(self):
        self.assertEqual([ctl.exit_code({'status': s}) for s in ('ok', 'failed', 'refused')], [0, 1, 2])


class Scenes(unittest.TestCase):
    def test_unknown_scenario_is_refused_with_the_known_ids(self):
        r = make().run('scene', 'nope')
        self.assertEqual(r['status'], 'refused')
        self.assertIn('land_small', r['reason'])

    def test_scene_resolves_a_preset_and_settles(self):
        g = FakeGame()
        r = make(g).run('scene', 'land_small')
        self.assertEqual(r['status'], 'ok')
        self.assertIn('autostart battle:land_small 240', g.lines)
        self.assertTrue(r['settle']['settled'])
        self.assertEqual(r['check']['expected'], {'map': 'NULL_MP_Flatlands', 'deployment': 'running'})

    def test_historical_without_a_preset_and_campaign_without_a_target_are_refused(self):
        self.assertIn('no battle preset', make().run('scene', 'hist')['reason'])
        self.assertIn('names no autostart target', make().run('scene', 'camp')['reason'])

    def test_a_naval_scene_is_a_battle_for_scene_and_kind(self):
        g = FakeGame(scene='naval', here='naval')
        c = make(g)
        self.assertEqual(c.current_kind(), 'naval')
        c.cfg = dict(c.cfg, settle=dict(c.cfg['settle'], ready_scenes=['naval']))
        r = c.run('scene', 'land_small')
        self.assertEqual(r['path']['via'], 'reset')
        self.assertTrue(r['settle']['settled'])

    def test_campaign_target_comes_from_the_save_field(self):
        self.assertEqual(ctl.scenario_target({'id': 'c', 'kind': 'campaign', 'save': 'campaign:new:null_campaign:faction_a (a new campaign)'}, '.'),
                         'campaign:new:null_campaign:faction_a')

    def test_autostart_failure_names_the_step_and_keeps_evidence(self):
        r = make(FakeGame(fail='autostart')).run('scene', 'land_small')
        self.assertEqual(r['status'], 'failed')
        self.assertIn('step autostart battle:land_small', r['reason'])
        self.assertIn('ctl', r['evidence'])

    def test_settle_times_out_when_the_scene_never_becomes_ready(self):
        r = make(FakeGame(scene='loading')).run('scene', 'land_small')
        self.assertEqual(r['status'], 'failed')
        self.assertIn('step settle', r['reason'])
        self.assertFalse(r['settle']['settled'])


class Poses(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(ctl.parse_pose('1 2 3 90 -30'), {'x': 1, 'y': 2, 'z': 3, 'yaw': 90, 'pitch': -30})
        self.assertEqual(ctl.parse_pose('1,2,3,90,-30,45')['fov'], 45)
        for bad in ('1 2 3', '1 2 3 a b', ''):
            with self.assertRaises(ctl.Refused):
                ctl.parse_pose(bad)

    def test_resolve_by_id_and_errors(self):
        self.assertEqual(ctl.resolve_pose(ROWS, 'land_small:wide')['yaw'], 90)
        with self.assertRaises(ctl.Refused):
            ctl.resolve_pose(ROWS, 'land_small:nope')
        with self.assertRaises(ctl.Refused):
            ctl.resolve_pose(ROWS, 'ghost:wide')

    def test_tolerance(self):
        exp = {'x': 10, 'y': 5, 'z': 0, 'yaw': 359, 'pitch': -30}
        ok, d = ctl.pose_check(exp, {'x': 10.2, 'y': 5, 'z': 0, 'yaw': 1, 'pitch': -30.1}, {'default': 0.5, 'yaw': 3})
        self.assertTrue(ok, d)   # yaw wraps: 359 against 1 is 2 degrees
        ok, d = ctl.pose_check(exp, {'x': 12, 'y': 5, 'z': 0, 'yaw': 359, 'pitch': -30}, {'default': 0.5})
        self.assertFalse(ok)
        self.assertFalse(d['x']['within'])
        ok, _ = ctl.pose_check(exp, {'x': 10}, {'default': 0.5})
        self.assertFalse(ok)   # a missing readback fails

    def test_yaw_wrap_any_representation(self):
        def yaw(exp, got, t=0.5):
            return ctl.pose_check({'yaw': exp}, {'yaw': got}, {'default': t})[0]
        self.assertTrue(yaw(270, -90.00001))
        self.assertTrue(yaw(0, 359.9999))
        self.assertTrue(yaw(180, -180))
        self.assertFalse(yaw(90, -90))
        self.assertTrue(yaw(359, 1, 3))
        self.assertFalse(yaw(359, 1, 1))
        self.assertAlmostEqual(ctl.angle_diff(0, 359.9999), 0.0001, places=6)
        self.assertEqual(ctl.angle_diff(180, -180), 0)

    def test_pitch_does_not_wrap(self):
        self.assertFalse(ctl.pose_check({'pitch': 80}, {'pitch': -100}, {'default': 0.5})[0])
        self.assertTrue(ctl.pose_check({'pitch': 80}, {'pitch': 80.2}, {'default': 0.5})[0])


class Refusals(unittest.TestCase):
    def test_unreachable_routes_refuse_with_reason_and_fact(self):
        r = make().run('cam', 'land_small:wide')
        self.assertEqual(r['status'], 'refused')
        self.assertIn('no api', r['reason'])
        self.assertIn('f.x', r['reason'])
        self.assertEqual(make().run('order', 'u', 'halt')['status'], 'refused')

    def test_bad_arguments_are_refused(self):
        self.assertEqual(make().run('pause', 'maybe')['status'], 'refused')
        self.assertEqual(make().run('speed', 'fast')['status'], 'refused')
        self.assertEqual(make(shotter=lambda n: ('p', 1)).run('shot', '../x')['status'], 'refused')

    def test_perf_checks_its_numbers(self):
        r = make().run('perf', '10')
        self.assertEqual(r['frame_ms']['p50'], 16.6)
        self.assertEqual(r['frames'], 600)

    def test_main_refuses_probe_verbs_and_unknown_verbs(self):
        for v in ctl.PROBE_ONLY + ('bogus',):
            self.assertEqual(ctl.main([v]), 2)


class Rule78(unittest.TestCase):
    """Camera poses are stored by id, never as key-tap scripts: scenario rows, generated files and the acceptance script carry no key/click moves.
    Here over fixture rows and presets (a game scans its own) and the core's acceptance script."""
    BAD = re.compile(r'(\bctl\b.*[\'"]\s*(key|click)\s|\bjob\.sh\s+ctl\b.*\b(key|click)\b|[\'"](key|click)\s+\S)')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rows = Path(self.tmp.name) / 'scenarios.jsonl'
        self.rows.write_text(''.join(json.dumps(r) + '\n' for r in ROWS.values()), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def files(self, battles=BATTLES):
        return [self.rows] + sorted(Path(battles).glob('*.txt')) + [ROOT / 'harness' / 'acceptance.py']

    def violations(self, files):
        return [f'{p.name}:{n}' for p in files for n, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1) if self.BAD.search(line)]

    def test_no_key_or_click_in_scenario_rows_generated_files_or_acceptance(self):
        self.assertTrue((ROOT / 'harness' / 'acceptance.py').is_file())
        self.assertEqual(self.violations(self.files()), [], 'moves the camera with key or click: store a pose by id (rule 78)')

    def test_failing_fixture_a_key_move_in_a_row_or_a_preset_is_found(self):
        bad = Path(self.tmp.name) / 'battles'
        bad.mkdir()
        (bad / 'land_small.txt').write_text('ctl "key w"\n', encoding='utf-8')
        with self.rows.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'id': 'x', 'kind': 'land', 'opener': ['click 10 20']}) + '\n')
        self.assertEqual(self.violations(self.files(bad)), ['scenarios.jsonl:4', 'land_small.txt:1'])

    def test_the_rule_catches_a_violation(self):
        self.assertIsNotNone(self.BAD.search('job.sh ctl me "key w"'))
        self.assertIsNotNone(self.BAD.search('"click 10 20"'))
        self.assertIsNone(self.BAD.search('"scene land_small"'))


# ---- J43: cam, pause and speed through per-kind routes, against a game that projects a real pinhole camera ----------------------------
campose = ctl.campose
CAM = {'status': 'reachable', 'why': 'w', 'fact': 'f.cam', 'set': 'S.lua', 'read': 'R.lua', 'settle_ms': 200, 'max_rms_px': 0.05,
       'tolerance': {'x': 0.05, 'y': 0.05, 'z': 0.05, 'yaw': 0.05, 'pitch': 0.05, 'fov': 0.05},
       'clamps': {'pitch': [-45, 45], 'height_above_terrain': [2.5, 44.556]}}
CLOCK = {'status': 'reachable', 'why': 'w', 'fact': 'f.speed', 'chunk': 'C.lua', 'lead_s': 0.5, 'measure_s': 4}
ROUTES = {'camera': {'land': CAM, 'naval': {'status': 'unknown', 'why': 'not probed at sea', 'fact': 'f.naval'}},
          'speed': {'land': dict(CLOCK, rates={'0.5': 'slow', '1': 'play', '2': 'fwd', '4': 'ffwd'}, measured={'slow': 0.43}, tolerance=0.1)},
          'pause': {'land': dict(CLOCK, tolerance=0.02, min_running_rate=0.25)}}
ADAPTER2 = {'game': 'nullgame', 'ctl': {'settle': ADAPTER['ctl']['settle'], 'routes': ROUTES}}


def cam_read_text(pose, w=1920, h=1080, fov=70.0):
    """What ctl/cam_read.lua returns for a camera at `pose`: C, S and a 3x3x3 cluster 100 m ahead (as the chunk builds it)."""
    c = [pose['x'], pose['y'], pose['z']]
    yaw, pitch = math.radians(pose['yaw']), math.radians(pose['pitch'])
    f = (h / 2) / math.tan(math.radians(fov / 2))
    fw = (math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch))
    pts = []
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            for oz in (-1, 0, 1):
                p = [c[k] + 100 * fw[k] + 20 * o for k, o in enumerate((ox, oy, oz))]
                sx, sy = campose.project(c, yaw, pitch, f, p, w, h)
                pts.append(f'{p[0]:.3f},{p[1]:.3f},{p[2]:.3f},{sx:.4f},{sy:.4f},0.99,{math.dist(p, c):.4f}')
    return f'cam C={c[0]:.4f},{c[1]:.4f},{c[2]:.4f} S={w},{h} P=' + ';'.join(pts)


class CamGame(FakeGame):
    """A battle: cam_set moves the camera (height clamped like the engine), speed.lua runs a battle clock against a windows clock."""
    def __init__(self, naval=0, conflict=True, ground=15.0, rates=None):
        super().__init__(scene='battle')
        self.naval, self.conflict, self.ground = naval, conflict, ground
        self.pose = {'x': 0, 'y': 59, 'z': 446, 'yaw': 180, 'pitch': -25}
        self.wt, self.ebt, self.tick, self.paused = 1000.0, 50.0, 'play', False
        self.rates = rates or {'slow': 0.43, 'play': 1.0, 'fwd': 2.0, 'ffwd': 4.0}

    def advance(self, s):
        self.wt += s
        if self.conflict and not self.paused:
            self.ebt += s * self.rates[self.tick]

    def __call__(self, line, wait=0):
        if line == 'state':
            self.lines.append(line)
            self.frame += 2
            return 0, {'status': 'ok', 'state': {'scene': self.scene, 'frame': self.frame, 'scene_s': 5.0, 'battle': {'naval': self.naval}}}
        if not line.startswith('lua '):
            return super().__call__(line, wait)
        self.lines.append(line)
        args = line.split(' -- ', 1)[1] if ' -- ' in line else ''
        if line.startswith('lua S.lua'):
            x, y, z, yaw, pitch = (float(v) for v in args.split(','))
            y = min(max(y, self.ground + 2.5), self.ground + 44.556)
            self.pose = {'x': x, 'y': y, 'z': z, 'yaw': yaw, 'pitch': max(-45, min(45, pitch))}
            return 0, {'status': 'ok', 'chunk': 'cam_set ok'}
        if line.startswith('lua R.lua'):
            return 0, {'status': 'ok', 'chunk': cam_read_text(self.pose)}
        if line.startswith('lua C.lua'):
            said = ''
            if args == 'pause':
                self.paused, said = True, 'set=pause '
            elif args == 'resume':
                self.paused, said = False, 'set=resume '
            elif args in self.rates:
                self.tick, self.paused, said = args, False, f'set={args} '
            self.advance(0.1)
            tick = 'pause' if self.paused else self.tick
            return 0, {'status': 'ok', 'chunk': f'speed {said}ebt={self.ebt} wt={self.wt} tick={tick} conflict={"true" if self.conflict else "false"}'}
        return 1, None


def make2(game):
    return ctl.Ctl(game, ROWS, ADAPTER2, battles_dir=BATTLES, clock=lambda: 0.0, sleep=game.advance)


class CamPose(unittest.TestCase):
    def test_the_solver_returns_the_pose_it_was_given(self):
        for pose in ({'x': 10, 'y': 50, 'z': 300, 'yaw': 90, 'pitch': -30}, {'x': -150, 'y': 45, 'z': 50, 'yaw': -45, 'pitch': 10},
                     {'x': 0, 'y': 59.02, 'z': 446.14, 'yaw': 180, 'pitch': -25}):
            got = campose.solve(campose.parse(cam_read_text(pose)))
            for k in ('x', 'y', 'z', 'pitch'):
                self.assertAlmostEqual(got[k], pose[k], delta=0.01)
            self.assertAlmostEqual(min(abs(got['yaw'] - pose['yaw']), 360 - abs(got['yaw'] - pose['yaw'])), 0, delta=0.01)
            self.assertAlmostEqual(got['fov'], 70.0, delta=0.01)
            self.assertLess(got['rms_px'], 0.01)

    def test_unreadable_and_empty_results_raise(self):
        for text in ('', 'cam none: no BattleUI.BackProjectPosition (not a battle?)', 'cam C=1,2 S=1920,1080 P='):
            with self.assertRaises(campose.PoseError):
                campose.solve(campose.parse(text))


class CamVerb(unittest.TestCase):
    def test_a_pose_is_set_read_back_and_checked(self):
        g = CamGame()
        r = make2(g).run('cam', '10', '30', '300', '90', '-30')
        self.assertEqual(r['status'], 'ok', r['reason'])
        self.assertTrue(r['check']['ok'])
        self.assertEqual(r['kind'], 'land')
        self.assertTrue(all(f['within'] for f in r['check']['fields'].values()))
        self.assertTrue(any(l.startswith('lua S.lua 20 -- 10.0,30.0,300.0,90.0,-30.0') for l in g.lines))

    def test_cam_read_returns_the_pose_without_setting_it(self):
        g = CamGame()
        c = make2(g)
        c.run('cam', '10', '30', '300', '90', '-30')
        n = len([l for l in g.lines if l.startswith('lua S.lua')])
        r = c.run('cam', 'read')
        self.assertEqual(r['status'], 'ok', r['reason'])
        self.assertEqual(len([l for l in g.lines if l.startswith('lua S.lua')]), n)   # no set
        self.assertAlmostEqual(r['got']['yaw'], 90, places=2)
        self.assertTrue(r['check']['ok'])

    def test_a_named_pose_resolves_from_the_scenario_row(self):
        g = CamGame()
        g.ground = -10   # the row's pose (y 2) is 12 m above this ground: inside the clamp
        r = make2(g).run('cam', 'land_small:wide')
        self.assertEqual(r['status'], 'ok', r['reason'])

    def test_a_clamped_height_fails_and_names_the_clamp(self):
        r = make2(CamGame()).run('cam', '10', '200', '300', '90', '-30')
        self.assertEqual(r['status'], 'failed')
        self.assertIn('height above terrain', r['reason'])
        self.assertFalse(r['check']['fields']['y']['within'])

    def test_a_pitch_outside_the_clamp_is_refused_before_any_set(self):
        g = CamGame()
        r = make2(g).run('cam', '10', '30', '300', '90', '-60')
        self.assertEqual(r['status'], 'refused')
        self.assertFalse(any(l.startswith('lua S.lua') for l in g.lines))

    def test_the_route_is_chosen_per_kind(self):
        r = make2(CamGame(naval=1)).run('cam', '10', '30', '300', '90', '-30')
        self.assertEqual(r['status'], 'refused')
        self.assertIn('camera (naval)', r['reason'])
        self.assertIn('f.naval', r['reason'])

    def test_a_refused_set_fails_the_verb(self):
        class NoCam(CamGame):
            def __call__(self, line, wait=0):
                if line.startswith('lua S.lua'):
                    return 0, {'status': 'ok', 'chunk': 'cam_set refused: dev.camera=0'}
                return super().__call__(line, wait)
        r = make2(NoCam()).run('cam', '10', '30', '300', '90', '-30')
        self.assertEqual(r['status'], 'failed')
        self.assertIn('dev.camera=0', r['reason'])


class SpeedAndPause(unittest.TestCase):
    def test_each_offered_speed_is_set_and_measured(self):
        for x, tick in (('2', 'fwd'), ('4', 'ffwd'), ('1', 'play'), ('0.5', 'slow')):
            r = make2(CamGame()).run('speed', x)
            self.assertEqual(r['status'], 'ok', (x, r['reason'], r['check']))
            self.assertEqual(r['check']['got']['tick'], tick)

    def test_slow_is_checked_against_its_measured_rate(self):
        r = make2(CamGame(rates={'slow': 0.5, 'play': 1.0, 'fwd': 2.0, 'ffwd': 4.0})).run('speed', '0.5')
        self.assertEqual(r['status'], 'failed')   # the engine's slow is 0.43, a clock at 0.5 is not it

    def test_a_speed_the_engine_does_not_offer_is_refused(self):
        self.assertEqual(make2(CamGame()).run('speed', '3')['status'], 'refused')

    def test_deployment_is_refused_and_nothing_is_set(self):
        g = CamGame(conflict=False)
        r = make2(g).run('speed', '2')
        self.assertEqual(r['status'], 'refused')
        self.assertIn('deployment', r['reason'])
        self.assertFalse(any(l.endswith('-- fwd') for l in g.lines))
        self.assertEqual(g.tick, 'play')

    def test_pause_on_stops_the_clock_and_off_resumes_it(self):
        g = CamGame()
        c = make2(g)
        r = c.run('pause', 'on')
        self.assertEqual(r['status'], 'ok', r['check'])
        self.assertEqual(r['check']['got'], 0.0)
        r = c.run('pause', 'off')
        self.assertEqual(r['status'], 'ok', r['check'])
        self.assertGreater(r['check']['got'], 0.9)

    def test_a_clock_that_does_not_stop_fails_pause(self):
        class NoPause(CamGame):
            def __call__(self, line, wait=0):
                return super().__call__(line.replace('-- pause', '-- read'), wait)
        self.assertEqual(make2(NoPause()).run('pause', 'on')['status'], 'failed')


class PcLaunch(unittest.TestCase):
    """J44: Pc.launch applies the adapter's keys, retries a lost headless start once and says so, and fails on a second loss."""
    def pc(self, answers):
        calls = []
        def sh(argv, stdin=None, timeout=None):
            calls.append((argv, stdin))
            if 'set' in argv:
                return 0, 'set'
            if stdin and stdin.startswith('launch'):
                return answers.pop(0)
            if 'ctl' in argv:
                return 0, '{"status": "ok", "scene": "frontend"}'
            return 0, ''
        a = {'game': 'nullgame', 'game_dir': '.', 'state_dir': '.', 'ctl': {'launch': {'keys': {}, 'size': '1920x1080'}}}
        p = ctl.Pc('o', 'a.json', a, sh=sh, clock=lambda: 0.0, sleep=lambda s: None)
        p.missing_keys = lambda: {}
        return p, calls

    RULE = r'add data\zz_nullgame_fixed_sky.pack -> nullgame\packs\zz_nullgame_fixed_sky.pack'

    def sky_pc(self, d, with_pack, rules_installed=True):
        """J45: a PC whose launch keys point dev.file_rules at the fixed-sky rules, and an installed kit with or without the pack."""
        game, state = d / 'game', d / 'state'
        (game / 'nullgame' / 'lua').mkdir(parents=True)
        (game / 'nullgame' / 'packs').mkdir()
        state.mkdir()
        files = []
        if rules_installed:
            (game / 'nullgame' / 'lua' / 'fixed_sky_rules.txt').write_text('# fixed sky\n' + self.RULE + '\n')
            files.append({'path': 'nullgame/lua/fixed_sky_rules.txt'})
        if with_pack:
            (game / 'nullgame' / 'packs' / 'zz_nullgame_fixed_sky.pack').write_bytes(b'PFH4')
            files.append({'path': 'nullgame/packs/zz_nullgame_fixed_sky.pack'})
        sky = {'present': True} if with_pack else {'present': False, 'reason': 'the game packs are not readable here'}
        (state / 'install.json').write_text(json.dumps({'kit_id': 'kit_20261031T000000Z_abc', 'files': files, 'packs': {'fixed_sky': sky}}))
        p, calls = self.pc([(0, 'ok')])
        p.a.update(game_dir=str(game), state_dir=str(state))
        p.launch_cfg = dict(p.launch_cfg, keys={'dev.file_rules': r'nullgame\lua\fixed_sky_rules.txt'})
        return p, calls

    def test_failing_fixture_a_kit_without_the_sky_pack_is_refused_before_launch(self):
        # J44 review 3: this launched with the vanilla sky and failed later as a land shot_match "lighting regression"
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p, calls = self.sky_pc(Path(d), with_pack=False)
            with self.assertRaises(ctl.Refused) as e:
                p.launch()
            msg = str(e.exception)
            for part in (self.RULE, r'nullgame\packs\zz_nullgame_fixed_sky.pack', 'kit_20261031T000000Z_abc',
                         'the game packs are not readable here'):
                self.assertIn(part, msg)
            self.assertFalse([c for c in calls if c[1] and c[1].startswith('launch')], 'nothing may launch')

    def test_a_missing_rules_file_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p, calls = self.sky_pc(Path(d), with_pack=True, rules_installed=False)
            with self.assertRaises(ctl.Refused) as e:
                p.launch()
            self.assertIn('fixed_sky_rules.txt', str(e.exception))
            self.assertFalse([c for c in calls if c[1] and c[1].startswith('launch')])

    def test_a_kit_with_the_sky_pack_launches_as_before(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p, calls = self.sky_pc(Path(d), with_pack=True)
            self.assertEqual(p.file_rule_problems(), [])
            self.assertEqual(p.launch()['size'], '1920x1080')
            self.assertTrue([c for c in calls if c[1] and c[1].startswith('launch')])

    def test_a_lost_headless_start_is_retried_once_and_recorded(self):
        p, calls = self.pc([(1, 'x\n[watcher] failed: HEADLESS FAILED: no on_virtual status'), (0, 'ok')])
        r = p.launch()
        self.assertIn('HEADLESS FAILED', r['retried_after'])

    def test_a_second_loss_fails(self):
        p, _ = self.pc([(1, 'HEADLESS FAILED: a'), (1, 'HEADLESS FAILED: b')])
        with self.assertRaises(RuntimeError):
            p.launch()

    def test_the_watchers_virtualstore_lines_are_recorded(self):
        # the watcher moves the copies aside before every launch (fix 1g, harness/tests/Test-Integration.ps1); ctl records what it says
        line = r'virtualstore: moved 1 stale file(s) of mod aside to C:\s\_to_delete\virtualstore_x: headless_status.json'
        p, _ = self.pc([(0, 'started\n' + line + '\n')])
        self.assertEqual(p.launch()['virtualstore_cleared'], [line])
        p, _ = self.pc([(0, 'started\n')])
        self.assertNotIn('virtualstore_cleared', p.launch())

    def test_status_survives_a_moment_without_the_file(self):
        answers = ['cat: watcher.status: No such file or directory', '{"version": "1.0.1", "game_state": {"state": "not_running"}}']
        p = ctl.Pc('o', 'a.json', {'game': 'nullgame', 'game_dir': '.', 'state_dir': '.'}, sh=lambda *a, **k: (0, answers.pop(0)),
                   sleep=lambda s: None)
        self.assertEqual(p.status()['version'], '1.0.1')
        p2 = ctl.Pc('o', 'a.json', {'game': 'nullgame', 'game_dir': '.', 'state_dir': '.'}, sh=lambda *a, **k: (1, 'gone'), sleep=lambda s: None)
        with self.assertRaises(RuntimeError):
            p2.status()

    def test_other_launch_failures_are_not_retried(self):
        p, calls = self.pc([(2, 'refused: lock')])
        with self.assertRaises(RuntimeError):
            p.launch()
        self.assertEqual(len([c for c in calls if c[1] and c[1].startswith('launch')]), 1)


ORDERS = {'status': 'reachable', 'why': 'wsp.order_move', 'fact': 'f.o', 'chunk': 'ctl/orders.lua',
          'tolerance': {'pos_m': 1.0, 'facing_deg': 1.0, 'width_m': 0.5, 'centre_lateral_m': 1.5, 'centre_ahead_m': [-1.0, 30.0]},
          'settle': {'poll_s': 1.0, 'rest_reads': 3, 'eps_m': 0.1, 'eps_deg': 0.2, 'min_wait_s': 3, 'base_s': 60, 'min_speed_mps': 0.6, 'max_s': 400},
          'commands': {'halt': {'cmd': 7, 'check': 'stops'}, 'square': {'cmd': 34, 'check': 'shape'}}}


class OrdersGame(FakeGame):
    """Plays ctl/orders.lua the way the engine behaved on the PC (run harness/runs/20261102_j28pc): a move stores the destination front
    centre at once and the centre walks there 2 m per read, staying `ahead` metres behind it; a blocked unit keeps the destination and never
    moves; a torn-down unit and an engine-refused unit answer as the proxy does."""
    def __init__(self, blocked=(), gone=(), refused=(), **kw):
        super().__init__(here='battle', **kw)
        self.u = {1: dict(x=0.0, z=0.0, facing=180.0, width=30.0, ahead=1.8), 2: dict(x=50.0, z=0.0, facing=180.0, width=40.0, ahead=1.5)}
        for u in self.u.values():
            u.update(fx=u['x'], fz=u['z'] - u['ahead'], tx=None, moving=0)
        self.blocked, self.gone, self.refused, self.pushed = set(blocked), set(gone), set(refused), []

    def ref(self, s):
        return int(s, 16) - 0x1000 if s.startswith('0x') else int(s)

    def line(self, i):
        u = self.u[i]
        return (f"unit id={i} ptr=0x{0x1000 + i:08x} x={u['x']:.4f} y=15 z={u['z']:.4f} facing={u['facing']:.4f} raw=0 men=120 queued=1 moving={u['moving']} "
                f"fx={u['fx']:.4f} fy=15 fz={u['fz']:.4f} width={u['width']:.4f} army=0x1")

    def step(self):
        for i, u in self.u.items():
            if u['tx'] is None or i in self.blocked:
                u['moving'] = 0
                continue
            cx, cz = u['tx'], u['tz'] + u['ahead']   # facing 180: the centre is ahead metres behind the front, at +z
            d = math.hypot(cx - u['x'], cz - u['z'])
            k = min(1.0, 2.0 / d) if d else 1.0
            u['x'] += (cx - u['x']) * k
            u['z'] += (cz - u['z']) * k
            u['moving'] = 1 if d > 2.0 else 0

    def __call__(self, line, wait=0):
        if not line.startswith('lua ctl/orders.lua'):
            return super().__call__(line, wait)
        self.lines.append(line)
        a = line.split(' -- ', 1)[1].split()
        if a[0] == 'state':
            self.step()
            out = []
            for r in a[1].split(','):
                i = self.ref(r)
                out.append(f"orders refused: {r}: the unit is not in its army's list (not a UNIT, or torn down)" if i in self.gone or i not in self.u else self.line(i))
            return 0, {'status': 'ok', 'chunk': '\n'.join(out)}
        i = self.ref(a[1])
        if i in self.refused:
            return 0, {'status': 'ok', 'chunk': 'orders refused: the engine refused the unit (AddUnit took 0: routing, dead or withdrawing)'}
        u = self.u[i]
        if a[0] == 'move':
            if a[5] != '-' and float(a[5]) <= 0.5:
                return 0, {'status': 'ok', 'chunk': 'orders refused: width must be in (0.5, 1000] metres'}
            u.update(tx=float(a[2]), tz=float(a[3]), fx=float(a[2]), fz=float(a[3]), moving=1)
            if a[4] != '-':
                u['facing'] = float(a[4]) % 360
            if a[5] != '-':
                u['width'] = float(a[5])
            self.pushed.append(i)
            return 0, {'status': 'ok', 'chunk': f'pushed order #{len(self.pushed)} unit {a[1]}\n' + self.line(i)}
        if a[0] == 'command':
            if a[2] == '7':
                u.update(tx=None, moving=0)
            elif a[2] == '34':
                u['ahead'] += 4.0
                u['fz'] = u['z'] - u['ahead']
            self.pushed.append(i)
            return 0, {'status': 'ok', 'chunk': f'pushed command #{len(self.pushed)} unit {a[1]} cmd {a[2]} dispatched'}
        return 0, {'status': 'ok', 'chunk': 'orders refused: unknown verb'}


def make_orders(game):
    c = make(game)
    c.cfg = dict(c.cfg, routes=dict(c.cfg['routes'], orders={'land': ORDERS}))
    return c


class Orders(unittest.TestCase):
    """The order verb (J28): every move is read back at rest and compared; the fixtures the brief names fail or refuse with evidence."""
    def test_a_move_arrives_and_is_checked_field_by_field(self):
        g = OrdersGame()
        r = make_orders(g).run('order', '1', 'move', '0', '-20', '180', '30')
        self.assertEqual(r['status'], 'ok', r['reason'])
        f = r['check']['fields']
        self.assertEqual(set(f), {'position_m', 'facing_deg', 'width_m', 'centre_lateral_m', 'centre_ahead_m'})
        self.assertTrue(all(v['within'] for v in f.values()))
        self.assertTrue(r['settle']['settled'] and r['settle']['moved'])
        self.assertEqual(r['ptr'], '0x00001001')   # the number is pinned to its pointer for the whole call

    def test_a_unit_that_never_moves_fails_although_the_destination_reads_back(self):
        """The engine stores the destination at the push even when it finds no path (siege_small g2, run 20261102_j28pc)."""
        r = make_orders(OrdersGame(blocked={1})).run('order', '1', 'move', '0', '-20', '180', '30')
        self.assertEqual(r['status'], 'failed')
        self.assertIn('never moved', r['reason'])
        self.assertTrue(r['check']['fields']['position_m']['within'])   # the stored destination alone would have passed
        self.assertFalse(r['check']['moved']['ok'])

    def test_a_torn_down_unit_is_refused_and_nothing_is_pushed(self):
        g = OrdersGame(gone={1})
        r = make_orders(g).run('order', '1', 'move', '0', '-20')
        self.assertEqual(r['status'], 'refused')
        self.assertIn('not in its army', r['reason'])
        self.assertEqual(g.pushed, [])

    def test_a_unit_the_engine_refuses_is_refused(self):
        r = make_orders(OrdersGame(refused={1})).run('order', '1', 'move', '0', '-20')
        self.assertEqual(r['status'], 'refused')
        self.assertIn('AddUnit took 0', r['reason'])

    def test_a_unit_lost_during_the_wait_fails_the_settle_step(self):
        """Off the map: the push is taken, the unit walks off and leaves its army (f1, run 20261102_j28pc)."""
        g = OrdersGame()
        c = make_orders(g)
        orig = g.step
        def step():
            orig()
            if g.pushed:
                g.gone.add(1)
        g.step = step
        r = c.run('order', '1', 'move', '0', '-2500')
        self.assertEqual(r['status'], 'failed')
        self.assertIn('step settle', r['reason'])

    def test_bad_arguments_are_refused(self):
        self.assertEqual(make_orders(OrdersGame()).run('order', '1', 'move', '0', '-20', '180', '0.2')['status'], 'refused')
        self.assertEqual(make_orders(OrdersGame()).run('order', '1', 'move', 'x', '-20')['status'], 'refused')
        self.assertEqual(make_orders(OrdersGame()).run('order', '1', 'fly')['status'], 'refused')

    def test_several_units_are_pushed_back_to_back_and_each_checked(self):
        g = OrdersGame(blocked={2})
        r = make_orders(g).run('order', '1,2', 'move', '0,50', '-20', '180', '30,40')
        self.assertEqual(g.pushed, [1, 2])
        self.assertEqual([u['status'] for u in r['units']], ['ok', 'failed'])
        self.assertEqual(r['status'], 'failed')
        self.assertIn('units 2', r['reason'])

    def test_halt_and_a_formation_are_checked_by_their_effect(self):
        g = OrdersGame()
        c = make_orders(g)
        g.u[1].update(tx=0.0, tz=-200.0, fx=0.0, fz=-200.0, moving=1)
        r = c.run('order', '1', 'halt')
        self.assertEqual(r['status'], 'ok', r['reason'])
        self.assertEqual(r['units'][0]['check']['fields']['moving']['got'], 0)
        r = c.run('order', '1', 'square')
        self.assertEqual(r['status'], 'ok', r['reason'])
        self.assertGreater(r['units'][0]['check']['fields']['shape_change_m']['got'], 3.0)
        g2 = OrdersGame()   # a formation the engine ignores (wedge on infantry, i5) reads back no change: failed
        c2 = make_orders(g2)
        c2.cfg['routes']['orders']['land'] = dict(ORDERS, commands={'wedge': {'cmd': 36, 'check': 'shape'}})
        self.assertEqual(c2.run('order', '1', 'wedge')['status'], 'failed')

    def test_list_is_checked(self):
        g = OrdersGame()
        orig = g.__call__
        def call(line, wait=0):
            if line.endswith('-- list'):
                return 0, {'status': 'ok', 'chunk': g.line(1) + '\n' + g.line(2)}
            return orig(line, wait)
        r = make_orders(call).run('order', 'list')
        self.assertEqual(r['status'], 'ok')
        self.assertEqual([u['id'] for u in r['units']], [1, 2])


class Identity(unittest.TestCase):
    """W10 (H2): the lock owner is the session. ctl.py's owner defaults to the session id (--session, $WSC_SESSION_ID, then the variable
    Claude Code exports); with none it refuses and names the fix; an explicit --owner still works."""
    NONE = {}

    def test_the_session_comes_from_the_flag_then_wsc_session_id_then_claude_code(self):
        self.assertEqual(ctl.resolve_identity(None, 'S-1', {'WSC_SESSION_ID': 'b', 'CLAUDE_CODE_SESSION_ID': 'c'}), ('s-1', 's-1', None))
        self.assertEqual(ctl.resolve_identity(None, None, {'WSC_SESSION_ID': 'b', 'CLAUDE_CODE_SESSION_ID': 'c'}), ('b', 'b', None))
        sid = '3815a970-03f3-4397-abff-a5c927662efa'
        self.assertEqual(ctl.resolve_identity(None, None, {'CLAUDE_CODE_SESSION_ID': sid}), (sid, sid, None))

    def test_no_session_refuses_and_names_the_fix(self):
        o, s, why = ctl.resolve_identity(None, None, self.NONE)
        self.assertIsNone(o)
        for word in ('--session', 'WSC_SESSION_ID', '--owner'):
            self.assertIn(word, why)

    def test_an_explicit_owner_still_works_and_is_validated(self):
        self.assertEqual(ctl.resolve_identity('claude-ctl', None, self.NONE), ('claude-ctl', 'claude-ctl', None))
        self.assertEqual(ctl.resolve_identity('claude-ctl', 'sess9', self.NONE), ('claude-ctl', 'sess9', None))
        self.assertIn('must match', ctl.resolve_identity('Claude-Ctl', None, self.NONE)[2])

    def test_main_refuses_without_a_session_or_owner(self):
        import contextlib
        import io
        import os
        from unittest import mock
        out = io.StringIO()
        with mock.patch.dict(os.environ), contextlib.redirect_stdout(out):
            for k in ('WSC_SESSION_ID', 'CLAUDE_CODE_SESSION_ID'):
                os.environ.pop(k, None)
            rc = ctl.main(['state'])
        self.assertEqual(rc, 2)
        r = json.loads(out.getvalue())
        self.assertEqual(r['status'], 'refused')
        self.assertIn('WSC_SESSION_ID', r['reason'])

    def test_main_uses_the_session_as_the_owner_unless_one_is_named(self):
        import contextlib
        import io
        import os
        from unittest import mock
        seen = []

        class Stop(Exception):
            pass

        def transport(owner, adapter=None):
            seen.append(owner)
            raise Stop

        adapter = _TMP / 'adapter_identity.json'
        adapter.write_text(json.dumps({'state_dir': str(_TMP), 'game': 'g'}), encoding='utf-8')
        for argv, env, want in ((['state'], {'WSC_SESSION_ID': 'sess-a'}, 'sess-a'),
                                (['--owner', 'claude-ctl', 'state'], {'WSC_SESSION_ID': 'sess-a'}, 'claude-ctl'),
                                (['--session', 'sess-b', 'state'], {}, 'sess-b')):
            with mock.patch.dict(os.environ, env), mock.patch.object(ctl, 'job_sh_transport', transport), \
                    mock.patch.object(ctl, 'Pc', lambda *a, **k: None), contextlib.redirect_stdout(io.StringIO()):
                if 'WSC_SESSION_ID' not in env:
                    os.environ.pop('WSC_SESSION_ID', None)
                    os.environ.pop('CLAUDE_CODE_SESSION_ID', None)
                with self.assertRaises(Stop):
                    ctl.main(['--adapter', str(adapter), '--no-pc', *argv])
            self.assertEqual(seen[-1], want)


if __name__ == '__main__':
    unittest.main()
