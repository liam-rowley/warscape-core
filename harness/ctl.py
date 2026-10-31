#!/usr/bin/env python3
"""The control API: one call per verb, blocks until a checked result, always one JSON object (J4).

purpose: (every verb but order ran on the PC: scene, shot, reset, perf, state and cam read in J44 harness/runs/20261030_j44pc, cam, pause and speed in J43; order is refused until J28) name a scenario and a camera pose and get a settled, checked answer back (scene, cam, shot, order, pause, speed, reset, perf, state), over the proxy's ctl channel (job.sh ctl) and the watcher's shot job; game-agnostic, everything game-specific comes from the adapter's `ctl` block and the scenarios registry
usage: ctl.py [--owner O] [--adapter A] [--registry R] [--out DIR] [--no-pc] <verb> [args]   verbs: scene <id> [--deploy end] | cam <scenario:pose | x y z yaw pitch [fov] | read> | shot <name> | order <unit> move x z [facing] | halt | formation <f> | pause on|off | speed <x> | reset [<id>] | perf <seconds> | state | key|click|wait (probe only)
when: every time an agent needs a known game state or a frame (never type key taps or sleeps for it); the acceptance runner (acceptance.py) calls the same functions
not-a-verb: a host-side client over harness/core/job.sh and the proxy's ctl verbs, not a registry operation; a J12 core candidate

Result contract (every verb, tests/test_ctl.py): `status` ok | failed | refused, `reason`, the verb's fields, `settle` (what it waited for and how
long), `check` (what was compared: expected against got; ok is never returned without one), `evidence` (paths: shot, state, log) and
`start_utc` / `end_utc`. A failure names the step and keeps its evidence. Exit code 0 only for ok (failed 1, refused 2).
Settle (defined once, `Settle`): scene ready + N presented frames + the scene unchanged for T ms (the proxy has no shader-creation hook
yet: frame and scene stability stand in, the game repo's engine fact on the settle signal). N and T are adapter fields, never sleeps in callers.
PC binding (J44, `Pc`): `scene` launches through the watcher when no game runs (or its dev keys differ from the adapter's ctl.launch.keys, set
with pc_deploy set), warm-resets from a battle and relaunches from a campaign or a historical battle; the loaded scenario is kept per game pid
in <state>/ctl/_ctl_session.json, so a later call's `current_kind` uses the row. `shot` goes through shot.sh; `perf` adds VRAM (the Windows GPU
Process Memory counter for the game's pid, nvidia-smi for the device) and the DLL's build id from its load line in proxy.log.
Routes come from the adapter's `ctl.routes`, per verb and per kind (land, siege, naval, campaign: `current_kind`); one not `reachable` makes the
verb answer `refused` with its reason and fact. cam sets the pose with the route's `set` chunk, waits its `settle_ms`, reads the pose back with its
`read` chunk (harness/core/campose.py) and compares within its `tolerance`; pause and speed go through the battle root's RequestSpeed and check
the battle clock's rate against the windows clock over `measure_s` (J43).
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# the game repo and its adapters come from proxy/tools/layout.py (J12): the same answer before and after the move to warscape-core
_OWN = next(d for d in (HERE, *HERE.parents) if (d / 'wsc.toml').is_file())
sys.path.insert(0, str(_OWN / 'proxy' / 'tools'))
import layout  # noqa: E402
ROOT = layout.game_root(_OWN)
sys.path.insert(0, str(HERE))
import campose  # noqa: E402  (the camera readback's maths, J43)
BATTLE_SCENES = ('battle_deploy', 'battle', 'naval')   # the proxy's scene tracker: a naval battle is its own scene (devcore.h SceneTracker)
PROBE_ONLY = ('key', 'click', 'wait')   # rule 78: never part of a scenario row, a generated file or the acceptance script
VERBS = ('scene', 'cam', 'shot', 'order', 'pause', 'speed', 'reset', 'perf', 'state')
POSE_FIELDS = ('x', 'y', 'z', 'yaw', 'pitch', 'fov')


def bash():
    """The bash that runs job.sh and shot.sh: tools/verbs/setup.py git_bash() (J41, J22), so Windows gets Git Bash and never the WSL
    launcher on PATH. ctl.py runs from the repo (it is not in the watcher kit), so the finder is loaded by path; when it cannot be
    loaded or finds nothing, plain 'bash' as before (a missing bash then fails in the call, as it always did)."""
    global _BASH
    if _BASH is None:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location('setup_verb', ROOT / 'tools' / 'verbs' / 'setup.py')
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            _BASH = m.git_bash() or 'bash'
        except Exception:   # noqa: BLE001  (any failure to load the finder falls back to the old behaviour)
            _BASH = 'bash'
    return _BASH


_BASH = None


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


class Refused(Exception):
    pass


def make_result(verb, status, reason='', start=None, check=None, settle=None, evidence=None, **fields):
    """The one result shape. `ok` without a `check` is a bug (rule 77): it is turned into `failed` here, so no verb can return it."""
    r = {'verb': verb, 'status': status, 'reason': reason}
    r.update(fields)
    r['settle'] = settle or {}
    r['check'] = check or {}
    r['evidence'] = evidence or {}
    r['start_utc'] = start or utc()
    r['end_utc'] = utc()
    if status == 'ok' and not r['check']:
        r['status'], r['reason'] = 'failed', 'verb returned ok without a check (rule 77)'
    return r


def exit_code(result):
    return {'ok': 0, 'failed': 1, 'refused': 2}.get(result['status'], 1)


# ---- scenarios and poses ------------------------------------------------------------------------------------------------
def load_scenarios(path):
    rows = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r['id']] = r
    return rows


def resolve_scenario(rows, sid):
    if sid not in rows:
        raise Refused(f'unknown scenario {sid!r} (known: {", ".join(sorted(rows))})')
    return rows[sid]


def scenario_target(row, battles_dir):
    """The autostart target a scenario row loads through: a battle preset of the same id (generated from the row; a historical one has
    type=historic), a campaign row's `save` when it starts with an autostart target (`campaign:new:<c>:<f>`, `campaign:<save>`), else refused."""
    if row['kind'] in ('land', 'siege', 'naval', 'historical') and (Path(battles_dir) / f"{row['id']}.txt").exists():
        return f"battle:{row['id']}"
    if row['kind'] == 'campaign':
        first = str(row.get('save', '')).split(' ')[0]
        if first.startswith('campaign:'):
            return first
        raise Refused(f"campaign scenario {row['id']} names no autostart target at the start of its save field (campaign:new:<c>:<f> or campaign:<save>)")
    raise Refused(f"scenario {row['id']} has no battle preset file {row['id']}.txt: generate it from the row")


def parse_pose(text):
    """'x y z yaw pitch [fov]' -> dict. Raises Refused on a wrong count or a non-number."""
    parts = text.replace(',', ' ').split()
    if len(parts) not in (5, 6):
        raise Refused(f'a pose is x y z yaw pitch [fov]: got {len(parts)} values')
    try:
        vals = [float(p) for p in parts]
    except ValueError as e:
        raise Refused(f'a pose has only numbers: {e}')
    return dict(zip(POSE_FIELDS, vals))


def resolve_pose(rows, ref):
    """`<scenario>:<pose>` from the row's camera_poses, or literal numbers."""
    if re.match(r'^[a-z0-9][a-z0-9_.-]*:[a-z0-9][a-z0-9_.-]*$', ref):
        sid, pid = ref.split(':', 1)
        poses = resolve_scenario(rows, sid).get('camera_poses', {})
        if pid not in poses:
            raise Refused(f'scenario {sid} has no pose {pid!r} (has: {", ".join(sorted(poses)) or "none"})')
        return dict(poses[pid])
    return parse_pose(ref)


def pose_check(expected, got, tol):
    """Compare a pose with the one read back. Each field within tol[field] (default tol['default']). Returns (ok, check dict)."""
    detail, ok = {}, True
    for f in POSE_FIELDS:
        if f not in expected:
            continue
        t = tol.get(f, tol.get('default', 0.5))
        g = got.get(f)
        d = None if g is None else abs(g - expected[f])
        if f in ('yaw', 'pitch') and d is not None:
            d = min(d, 360 - d) if d <= 360 else d
        within = d is not None and d <= t
        ok = ok and within
        detail[f] = {'expected': expected[f], 'got': g, 'tolerance': t, 'within': within}
    return ok, detail


# ---- settle ---------------------------------------------------------------------------------------------------------------
class Settle:
    """scene ready + N presented frames + the scene unchanged for T ms. `state` is a callable returning the proxy's state dict; `clock`
    and `sleep` are injectable so the tests need no game."""
    def __init__(self, frames, quiet_ms, timeout_s, ready_scenes, state, clock=time.monotonic, sleep=time.sleep, poll_s=0.5):
        self.frames, self.quiet_ms, self.timeout_s, self.ready = frames, quiet_ms, timeout_s, set(ready_scenes)
        self.state, self.clock, self.sleep, self.poll_s = state, clock, sleep, poll_s

    def wait(self):
        t0 = self.clock()
        first_frame = None
        last = None
        while True:
            s = self.state()
            last = s
            if s.get('scene') in self.ready:
                f = s.get('frame', 0)
                first_frame = f if first_frame is None else first_frame
                if f - first_frame >= self.frames and s.get('scene_s', 0) * 1000 >= self.quiet_ms:
                    return {'waited_for': f'scene in {sorted(self.ready)} + {self.frames} frames + {self.quiet_ms} ms stable',
                            'waited_s': round(self.clock() - t0, 2), 'frames': f - first_frame, 'scene': s['scene'], 'settled': True}
            else:
                first_frame = None
            if self.clock() - t0 > self.timeout_s:
                return {'waited_for': f'scene in {sorted(self.ready)} + {self.frames} frames + {self.quiet_ms} ms stable',
                        'waited_s': round(self.clock() - t0, 2), 'scene': (last or {}).get('scene'), 'settled': False}
            self.sleep(self.poll_s)


# ---- the PC binding ---------------------------------------------------------------------------------------------------------
def win_to_posix(p):
    """C:\\x\\y -> /c/x/y (job.sh and shot.sh take either; the Git Bash form keeps spaces out of quoting trouble)."""
    m = re.match(r'^([A-Za-z]):[\\/](.*)$', str(p))
    return f'/{m.group(1).lower()}/' + m.group(2).replace('\\', '/') if m else str(p)


def ini_values(text):
    """{'section.key': value} from an ini text (the proxy's config file)."""
    out, sec = {}, ''
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in ';#':
            continue
        if s.startswith('[') and s.endswith(']'):
            sec = s[1:-1].strip()
        elif '=' in s:
            k, v = s.split('=', 1)
            out[f'{sec}.{k.strip()}' if sec else k.strip()] = v.strip()
    return out


def identity(adapter=None):
    """The game's proxy identity.json (exe, mod folder, config file names), from the proxy adapter layout.py finds; {} when none."""
    try:
        return json.loads((layout.proxy_adapter(ROOT) / 'identity.json').read_text(encoding='utf-8'))
    except (layout.LayoutError, OSError, ValueError):
        return {}


def ident_mod(adapter):
    mod = identity(adapter).get('mod_dir')
    if not mod:
        raise RuntimeError('no proxy adapter identity.json (proxy/tools/layout.py proxy-adapter): the mod folder is unknown')
    return mod


class Pc:
    """The game on the PC: the watcher (job.sh: status, launch, kill), the proxy's installed config (pc_deploy set) and the ctl channel.
    Everything waits inside one call. `sh(argv, stdin, timeout)` -> (exit code, stdout) is injectable for the tests."""
    def __init__(self, owner, adapter_path, adapter, sh=None, clock=time.monotonic, sleep=time.sleep):
        self.owner, self.adapter_path, self.a = owner, str(adapter_path), adapter
        self.launch_cfg = adapter.get('ctl', {}).get('launch', {})
        self.sh, self.clock, self.sleep = sh or self._sh, clock, sleep
        self.ini_name = identity(adapter).get('config_file') or next(
            (c['path'] for c in adapter.get('config_files', []) if c.get('id') == 'mod_ini'), None)

    @staticmethod
    def _sh(argv, stdin=None, timeout=None):
        p = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr

    def job(self, body, timeout_s):
        return self.sh([bash(), str(HERE / 'job.sh'), '--adapter', self.adapter_path, self.owner, '-', str(timeout_s)], body, timeout_s + 30)

    def status(self, tries=10):
        """The watcher's status. It replaces watcher.status every 2 s and the file can be missing for an instant (run 20261030_j44acc2
        pass 3 failed on one such read): retry for about 5 s before calling it unreadable."""
        for i in range(tries):
            rc, out = self.sh([bash(), str(HERE / 'job.sh'), '--adapter', self.adapter_path, 'status'], None, 30)
            try:
                return json.loads(out[out.index('{'):out.rindex('}') + 1])
            except ValueError:
                if i == tries - 1:
                    raise RuntimeError(f'watcher status unreadable after {tries} reads (exit {rc}): {out[-300:]}')
                self.sleep(0.5)

    def pid(self):
        g = self.status().get('game_state') or {}
        return g.get('pid') if g.get('state') not in (None, 'not_running') else None

    def ini_path(self):
        return Path(self.a['game_dir']) / self.ini_name

    def keys(self):
        """The dev keys every ctl launch needs (adapter ctl.launch.keys), never chosen by callers (J44)."""
        return dict(self.launch_cfg.get('keys', {}))

    def missing_keys(self):
        p = self.ini_path()
        if not p.exists():
            raise Refused(f'{p} is missing: install the proxy kit first (pc_deploy.py install)')
        have = ini_values(p.read_text(encoding='utf-8'))
        return {k: v for k, v in self.keys().items() if have.get(k) != v}

    def set_keys(self, keys):
        argv = ['python3', str(_OWN / 'proxy' / 'tools' / 'pc_deploy.py'), 'set', '--game', self.a['game_dir'], '--config-file', self.ini_name]
        rc, out = self.sh(argv + [f'{k}={v}' for k, v in keys.items()], None, 60)
        if rc != 0:
            raise RuntimeError(f'step keys: pc_deploy set failed: {out[-300:]}')

    def file_rule_problems(self):
        """The launch's dev.file_rules file and every `add` rule's source must be installed by the kit (install.json `files`), or the
        game starts without them: a kit built without a game pack (the fixed sky) launched with the vanilla sky, and the first sign was a land
        shot_match failure that looked like a lighting regression (J44 review 3, J45). Problems as text; [] when there is nothing missing."""
        rules = self.keys().get('dev.file_rules')
        if not rules:
            return []
        inst = Path(self.a['state_dir']) / 'install.json'
        rec = json.loads(inst.read_text(encoding='utf-8')) if inst.exists() else {}
        kit = rec.get('kit_id') or 'none installed'
        have = {f['path'].replace('\\', '/').lower() for f in rec.get('files', [])}
        absent = [f"no {k} pack, {v.get('reason')}" for k, v in sorted((rec.get('packs') or {}).items()) if v.get('present') is False]
        why = f" (the kit says: {'; '.join(absent)})" if absent else ''
        split = lambda p: [s for s in re.split(r'[\\/]', p) if s]   # rule paths use backslashes; a host Path would not split them
        def installed(rel):
            return '/'.join(split(rel)).lower() in have and Path(self.a['game_dir'], *split(rel)).is_file()
        absolute = re.match(r'^([A-Za-z]:)?[\\/]', rules)   # an absolute rule file is the developer's own, not the kit's
        path = Path(rules) if absolute else Path(self.a['game_dir'], *split(rules))
        if not (path.is_file() if absolute else installed(rules)):
            return [f'dev.file_rules names {rules}, which kit {kit} did not install: build and install a kit with it (pc_deploy.py kit, install)']
        text = path.read_text(encoding='utf-8', errors='replace')
        out = []
        for line in text.splitlines():
            m = re.match(r'^\s*add\s+.+?->\s*(\S.*?)\s*$', line, re.I)
            if m and not installed(m.group(1)):
                out.append(f'rule "{line.strip()}" in {rules}: {m.group(1)} is not in kit {kit}{why}: rebuild the kit where the pack builds (the PC)')
        return out

    def launch(self, size=None):
        """Apply the launch keys, launch headless through the watcher and wait for the front end. The watcher moves stray VirtualStore
        copies aside before every launch (adapter virtualstore_guard, J12 fix 1g); its "virtualstore:" lines come back here.
        Refused before anything starts when a file rule names a source the installed kit lacks (file_rule_problems).
        Returns {size, keys_set, launch_s} (+ virtualstore_cleared, retried_after when they happened)."""
        t0 = self.clock()
        bad = self.file_rule_problems()
        if bad:
            raise Refused('launch refused: ' + '; '.join(bad))
        miss = self.missing_keys()
        if miss:
            self.set_keys(miss)
        size = size or self.launch_cfg.get('size', '1920x1080')
        rc, out = self.job(f'launch size={size}', 300)
        retried = None
        if rc != 0 and 'HEADLESS FAILED' in out:
            # one retry, recorded: the headless start was lost twice on 2026-10-30 with the game itself fine (a heap corruption 10 ms after
            # init, and an on_virtual status logged by the proxy that never reached headless_status.json; run 20261030_j44pc, J16's code)
            retried = out.strip().splitlines()[-1][-300:]
            rc, out = self.job(f'launch size={size}', 300)
        if rc != 0:
            raise RuntimeError(f'step launch: exit {rc}: {out[-400:]}')
        vs = [l.strip() for l in out.splitlines() if l.strip().startswith('virtualstore:')]
        ok, r = self.ctl(f"waitfor frontend {self.launch_cfg.get('frontend_wait_s', 180)}", self.launch_cfg.get('frontend_wait_s', 180) + 20)
        if not ok:
            raise RuntimeError(f'step frontend: {(r or {}).get("reason", "no answer")}')
        return {'size': size, 'keys_set': sorted(miss), 'launch_s': round(self.clock() - t0, 1), **({'retried_after': retried} if retried else {}),
                **({'virtualstore_cleared': vs} if vs else {})}

    def ctl(self, line, wait_s):
        rc, out = self.sh([bash(), str(HERE / 'job.sh'), '--adapter', self.adapter_path, 'ctl', self.owner, line, str(wait_s)], None, wait_s + 30)
        try:
            r = json.loads(out[out.index('{'):out.rindex('}') + 1])
        except ValueError:
            r = None
        return rc == 0, r

    def exit(self, wait_s=90):
        """ctl exit, then wait until the watcher sees no game; a kill job when it does not go. Returns how it ended."""
        if self.pid() is None:
            return 'not running'
        self.ctl('exit', 20)
        end = self.clock() + wait_s
        while self.clock() < end:
            if self.pid() is None:
                return 'exit'
            self.sleep(1)
        rc, out = self.job('kill', 120)
        if rc != 0:
            raise RuntimeError(f'step exit: the game did not exit and the kill job failed: {out[-300:]}')
        return 'killed'

    def build_info(self):
        """build (pc_deploy's install.json), backend and size (the installed ini) of the running game: what a perf number belongs to."""
        inst = Path(self.a['state_dir']) / 'install.json'
        rec = json.loads(inst.read_text(encoding='utf-8')) if inst.exists() else {}
        ini = ini_values(self.ini_path().read_text(encoding='utf-8')) if self.ini_path().exists() else {}
        # the DLL's own build id (a hash of its inputs' content, proxy/tools/build_id.py: what rule 79 compares), from its load line; the kit id names HEAD at kit time
        log = self.ini_path().parent / ident_mod(self.a) / 'logs' / 'proxy.log'
        m = re.search(r'd3d9\.dll build (\S+) loaded', log.read_text(encoding='utf-8', errors='replace')) if log.exists() else None
        return {'build': m.group(1) if m else rec.get('build_id'), 'kit': rec.get('kit_id'), 'backend': ini.get('proxy.backend'),
                'size': ini.get('headless.size') if ini.get('headless.enabled') == '1' else 'windowed'}

    def shot(self, name, out_dir):
        """shot.sh into out_dir/<name>.jpg: (path, bytes)."""
        out = Path(out_dir) / f'{name}.jpg'
        out.parent.mkdir(parents=True, exist_ok=True)
        rc, txt = self.sh([bash(), str(HERE / 'shot.sh'), self.owner, win_to_posix(out)], None, 150)
        if rc != 0 or not out.exists():
            raise RuntimeError(f'step shot: {txt[-300:]}')
        return str(out), out.stat().st_size

    def vram(self, pid):
        """Read-only, host side: the game's dedicated GPU memory (Windows counter GPU Process Memory, per process) and the device total (nvidia-smi)."""
        res = {'source': 'Windows counter \\GPU Process Memory(pid_<pid>_*)\\Dedicated Usage (per process) + nvidia-smi memory.used (device)'}
        ps = (f"$s = (Get-Counter '\\GPU Process Memory(pid_{int(pid)}_*)\\Dedicated Usage' -ErrorAction Stop).CounterSamples; "
              "[math]::Round((($s | Measure-Object CookedValue -Sum).Sum)/1MB, 1)")
        rc, out = self.sh(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', ps], None, 60)
        try:
            res['process_dedicated_mb'] = float(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            res['process_error'] = out.strip()[-200:]
        rc, out = self.sh(['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'], None, 30)
        try:
            used, total = [float(x) for x in out.strip().splitlines()[0].split(',')]
            res['device_used_mb'], res['device_total_mb'] = used, total
        except (ValueError, IndexError):
            res['device_error'] = out.strip()[-200:]
        return res


class Session:
    """What one game process has loaded, kept between CLI calls (<state>/ctl/_ctl_session.json): the scenario id is valid only for the pid
    that loaded it, so `current_kind` never reads a stale row after a relaunch."""
    def __init__(self, path):
        self.path = Path(path) if path else None

    def get(self, pid):
        if not self.path or not self.path.exists() or pid is None:
            return {}
        try:
            d = json.loads(self.path.read_text(encoding='utf-8'))
        except ValueError:
            return {}
        return d if d.get('pid') == pid else {}

    def put(self, pid, **kw):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'pid': pid, 'utc': utc(), **kw}), encoding='utf-8')
            tmp.replace(self.path)


# ---- the client -------------------------------------------------------------------------------------------------------------
def job_sh_transport(owner, adapter=None):
    """(line, wait_s) -> (exit code, parsed result or None) over `job.sh ctl`."""
    def send(line, wait_s=170):
        cmd = [bash(), str(HERE / 'job.sh')] + (['--adapter', str(adapter)] if adapter else []) + ['ctl', owner, line, str(wait_s)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return p.returncode, json.loads(p.stdout)
        except ValueError:
            return p.returncode, None
    return send


class Ctl:
    def __init__(self, transport, scenarios, adapter, battles_dir=None, shotter=None, clock=time.monotonic, sleep=time.sleep, pc=None, session=None):
        self.t, self.rows, self.cfg = transport, scenarios, adapter.get('ctl', {})
        self.battles_dir = battles_dir or layout.proxy_adapter(ROOT) / 'lua' / 'battles'
        self.shotter, self.clock, self.sleep = shotter, clock, sleep
        self.pc, self.session = pc, session or Session(None)   # pc: the game binding (launch, keys, exit, vram); None = a game already running
        self.scene_id = None
        if pc is not None:
            try:
                self.scene_id = self.session.get(pc.pid()).get('scene_id')
            except RuntimeError:
                pass

    # -- plumbing
    def state(self):
        rc, r = self.t('state', 20)
        if rc != 0 or not r:
            raise RuntimeError(f'ctl state failed (exit {rc}): is the game running with dev.ctl=1?')
        return r['state']

    def settle(self):
        s = self.cfg.get('settle', {})
        return Settle(s.get('frames', 30), s.get('quiet_ms', 2000), s.get('timeout_s', 120), s.get('ready_scenes', list(BATTLE_SCENES) + ['campaign']),
                      self.state, self.clock, self.sleep).wait()

    def current_kind(self):
        """land | siege | naval | campaign | <scene>: the loaded scenario row's kind, else the proxy's scene and naval probe."""
        if self.scene_id and self.rows.get(self.scene_id, {}).get('kind') in ('land', 'siege', 'naval', 'campaign'):
            return self.rows[self.scene_id]['kind']
        s = self.state()
        if s.get('scene') == 'campaign':
            return 'campaign'
        if s.get('scene') in BATTLE_SCENES:
            return 'naval' if s.get('scene') == 'naval' or (s.get('battle') or {}).get('naval') == 1 else 'land'
        return s.get('scene') or 'unknown'

    def route(self, name, kind=None):
        """The adapter's route for a verb: flat ({status, why, fact}) or per kind ({land: {...}, naval: {...}}). Refused unless reachable."""
        rt = self.cfg.get('routes', {}).get(name, {})
        if 'status' not in rt:
            kind = kind or self.current_kind()
            rt = dict(rt.get(kind, {'status': 'unknown', 'why': f'no {name} route for {kind}'}), kind=kind)
        if rt.get('status', 'unknown') != 'reachable':
            label = f"{name} ({rt['kind']})" if rt.get('kind') else name
            raise Refused(f"route {label} is {rt.get('status', 'unknown')}: {rt.get('why', 'not probed')} (fact {rt.get('fact', '?')})")
        return rt

    def lua(self, path, args=None, wait_s=20):
        """One `ctl lua` chunk: (ok, text, raw result)."""
        line = f'lua {path} {wait_s}' + (f' -- {args}' if args else '')
        rc, r = self.t(line, wait_s + 10)
        if rc != 0 or not r or r.get('status') != 'ok':
            return False, (r or {}).get('reason') or (r or {}).get('chunk') or f'no result (exit {rc})', r
        return True, r.get('chunk', ''), r

    def battle_clock(self, rt, arg):
        ok, text, _ = self.lua(rt['chunk'], arg)
        if not ok or not text.startswith('speed ') or text.startswith(('speed refused', 'speed none')):
            raise RuntimeError(f'step {arg}: {text}')
        f = dict(tok.split('=', 1) for tok in text.split(' ')[1:] if '=' in tok)
        try:
            return {'ebt': float(f['ebt']), 'wt': float(f['wt']), 'tick': f.get('tick'), 'conflict': f.get('conflict') == 'true', 'raw': text}
        except (KeyError, ValueError):
            raise RuntimeError(f'step {arg}: unreadable clock {text!r}')

    def rate(self, rt, set_arg):
        """Set (RequestSpeed) and measure the battle clock against the windows clock: (rate, first reading, last reading)."""
        if not self.battle_clock(rt, 'read')['conflict']:   # read first: a refusal changes nothing
            raise Refused(f"the battle is in deployment: its clock does not run until deployment ends (lua {rt['chunk']} -- start)")
        self.battle_clock(rt, set_arg)
        self.sleep(rt.get('lead_s', 0.5))
        b = self.battle_clock(rt, 'read')
        self.sleep(rt.get('measure_s', 4))
        c = self.battle_clock(rt, 'read')
        dw = c['wt'] - b['wt']
        if dw <= 0:
            raise RuntimeError(f"the windows clock did not advance ({b['wt']} -> {c['wt']})")
        return (c['ebt'] - b['ebt']) / dw, b, c

    def run(self, verb, *args):
        start = utc()
        try:
            fn = getattr(self, 'v_' + verb)
            return fn(start, *args)
        except Refused as e:
            return make_result(verb, 'refused', str(e), start)
        except Exception as e:   # a failure names its step and keeps going to the caller as data, never a traceback
            return make_result(verb, 'failed', f'{type(e).__name__}: {e}', start)

    # -- verbs
    def v_state(self, start):
        s = self.state()
        return make_result('state', 'ok', start=start, state=s, check={'compared': 'state.json readable', 'expected': 'a scene and a frame', 'got': {'scene': s.get('scene'), 'frame': s.get('frame')}})

    def v_scene(self, start, sid, *opts):
        """Load a scenario from any state: launch (with the adapter's dev keys) when no game runs or its keys are wrong, autostart from the
        front end, warm reset from a battle, relaunch from a campaign (no quit flow: the game repo's engine fact campaign.quit_to_menu); settle; then
        `--deploy end` ends deployment (the row's launch command names it) so pause, speed and battle-time shots work."""
        row = resolve_scenario(self.rows, sid)
        deploy = 'end' if ('--deploy' in opts and 'end' in opts) or 'deploy=end' in opts else 'running'
        target = scenario_target(row, self.battles_dir)
        path = {'launch': None}
        if self.pc is not None:
            pid = self.pc.pid()
            if pid is not None and self.pc.missing_keys():
                path['exit_for_keys'] = self.pc.exit()
                pid = None
            if pid is None:
                path['launch'] = self.pc.launch()
        here = self.state().get('scene', '')
        # a campaign has no quit flow (the game repo's engine fact campaign.quit_to_menu), and the warm reset stops at a historical battle's post-battle
        # screen (mp_postbattle; run 20261030_j44pc): both leave by a relaunch
        was = self.rows.get(self.scene_id or '', {}).get('kind')
        if here == 'campaign' or (here in BATTLE_SCENES and was == 'historical'):
            if self.pc is None:
                raise Refused(f'leaving a {was or here} needs a relaunch: scene needs the PC binding')
            path['relaunch'] = {'exit': self.pc.exit(), **self.pc.launch()}
            here = 'frontend'
        verb = 'reset' if here in BATTLE_SCENES else 'autostart'
        path['via'] = verb
        rc, r = self.t(f'{verb} {target} 240', 260)
        a = (r or {}).get('autostart', r or {}) if verb == 'reset' else (r or {})
        if rc != 0 or not r:
            return make_result('scene', 'failed', f"step {verb} {target}: {(r or {}).get('reason', 'no result')}", start, scenario=sid, path=path, evidence={'ctl': r})
        settle = self.settle()
        if not settle['settled']:
            return make_result('scene', 'failed', 'step settle: ' + json.dumps(settle), start, scenario=sid, path=path, settle=settle, evidence={'ctl': r})
        self.scene_id = sid
        if self.pc is not None:
            self.session.put(self.pc.pid(), scene_id=sid)
        got = {'map': a.get('map'), 'scene': settle['scene']}
        want = {'map': row['map'].split(' ')[0] if row['kind'] == 'campaign' else row['map']}
        ok = row['kind'] in ('campaign', 'historical') or str(got['map']).lower() == want['map'].lower()
        if ok and deploy == 'end':
            got['deployment'] = self.end_deployment(row)
            ok = got['deployment'] == 'ended'
        check = {'compared': 'preset map against the row' + (', deployment ended' if deploy == 'end' else ''), 'expected': {**want, 'deployment': deploy}, 'got': got, 'ok': ok}
        reason = '' if ok else ('WRONG MAP' if 'deployment' not in got else f"step deploy: {got['deployment']}")
        return make_result('scene', 'ok' if ok else 'failed', reason, start, scenario=sid, kind=row['kind'], target=target, load_s=a.get('load_s'),
                           path=path, settle=settle, check=check, evidence={'ctl': r})

    def end_deployment(self, row):
        """The start button's call (speed.lua start), then the battle clock must run (IsConflict) within the route's deploy_wait_s."""
        rt = self.route('speed', row['kind'])
        self.battle_clock(rt, 'start')
        end = self.clock() + rt.get('deploy_wait_s', 15)
        while self.clock() < end:
            if self.battle_clock(rt, 'read')['conflict']:
                return 'ended'
            self.sleep(1)
        return 'still deploying after the start call'

    def v_cam(self, start, *ref):
        if list(ref) == ['read']:
            return self.cam_read(start)
        pose = resolve_pose(self.rows, ' '.join(ref))
        rt = self.route('camera')
        cl = rt.get('clamps', {})
        lo, hi = cl.get('pitch', [-89, 89])
        if not lo <= pose['pitch'] <= hi:
            raise Refused(f"pitch {pose['pitch']} is outside the camera's clamp [{lo}, {hi}] ({rt.get('kind')})")
        ok, text, r = self.lua(rt['set'], ','.join(repr(float(pose[k])) for k in ('x', 'y', 'z', 'yaw', 'pitch')))
        if not ok or text.strip() != 'cam_set ok':
            return make_result('cam', 'failed', f'step set: {text}', start, pose=pose, evidence={'set': r})
        wait_s = rt.get('settle_ms', 500) / 1000
        self.sleep(wait_s)
        settle = {'waited_for': f"the route's settle_ms after the set", 'waited_s': wait_s, 'settled': True}
        ok, text, r2 = self.lua(rt['read'])
        try:
            if not ok:
                raise campose.PoseError(text)
            got = campose.solve(campose.parse(text))
        except campose.PoseError as e:
            return make_result('cam', 'failed', f'step read: {e}', start, pose=pose, settle=settle, evidence={'set': r, 'read': r2})
        within, detail = pose_check(pose, got, rt.get('tolerance', {}))
        max_rms = rt.get('max_rms_px', 0.05)
        fit_ok = got['rms_px'] <= max_rms
        check = {'compared': 'the pose asked against the pose read back (BackProjectPosition fit)', 'fields': detail,
                 'fit': {'rms_px': got['rms_px'], 'max_rms_px': max_rms, 'points': got['points']}, 'ok': within and fit_ok}
        reason = ''
        if not fit_ok:
            reason = 'readback fit too loose'
        elif not within:
            reason = 'readback outside tolerance'
            if not detail.get('y', {}).get('within', True):
                reason += f" (the engine clamps height above terrain to {cl.get('height_above_terrain')} m)"
        return make_result('cam', 'ok' if check['ok'] else 'failed', reason, start, pose=pose, kind=rt.get('kind'),
                           got={k: round(v, 4) if isinstance(v, float) else v for k, v in got.items()}, settle=settle, check=check,
                           evidence={'set': r, 'read': r2})

    def cam_read(self, start):
        """`cam read`: the pose as it is (no set), checked only by the fit; how a scenario's poses are found before they are stored (J44)."""
        rt = self.route('camera')
        ok, text, r = self.lua(rt['read'])
        try:
            if not ok:
                raise campose.PoseError(text)
            got = campose.solve(campose.parse(text))
        except campose.PoseError as e:
            return make_result('cam', 'failed', f'step read: {e}', start, evidence={'read': r})
        fit_ok = got['rms_px'] <= rt.get('max_rms_px', 0.05)
        check = {'compared': 'readback fit', 'expected': f"rms_px <= {rt.get('max_rms_px', 0.05)}", 'got': got['rms_px'], 'ok': fit_ok}
        return make_result('cam', 'ok' if fit_ok else 'failed', '' if fit_ok else 'readback fit too loose', start, kind=rt.get('kind'),
                           got={k: round(v, 4) if isinstance(v, float) else v for k, v in got.items()}, check=check, evidence={'read': r})

    def v_order(self, start, *args):
        self.route('orders')
        raise Refused('order route is reachable but not implemented (J28)')

    def v_pause(self, start, mode):
        if mode not in ('on', 'off'):
            raise Refused('pause takes on or off')
        rt = self.route('pause')
        rate, b, c = self.rate(rt, 'pause' if mode == 'on' else 'resume')
        if mode == 'on':
            want, ok = f"<= {rt.get('tolerance', 0.02)}", rate <= rt.get('tolerance', 0.02)
        else:
            want, ok = f">= {rt.get('min_running_rate', 0.25)}", rate >= rt.get('min_running_rate', 0.25)
        check = {'compared': 'battle clock seconds per windows second after the request', 'expected': want, 'got': round(rate, 4), 'tick': c['tick'], 'ok': ok}
        return make_result('pause', 'ok' if ok else 'failed', '' if ok else 'battle clock rate not as asked', start, mode=mode, kind=rt.get('kind'),
                           settle={'waited_for': f"lead {rt.get('lead_s', 0.5)} s + measure {rt.get('measure_s', 4)} s", 'settled': True}, check=check,
                           evidence={'from': b['raw'], 'to': c['raw']})

    def v_speed(self, start, x):
        try:
            want = float(x)
        except ValueError:
            raise Refused('speed takes a number')
        rt = self.route('speed')
        names = {float(k): v for k, v in rt.get('rates', {}).items()}
        if want not in names:
            raise Refused(f"speed {x} is not one the engine offers: {sorted(names)} (pause on|off for 0)")
        expect = rt.get('measured', {}).get(names[want], want)   # the engine's own rate for that setting (slow is not 0.5)
        rate, b, c = self.rate(rt, names[want])
        tol = rt.get('tolerance', 0.1) * expect
        ok = abs(rate - expect) <= tol and c['tick'] == names[want]
        check = {'compared': 'battle clock seconds per windows second, and the tick period', 'expected': {'rate': expect, 'tolerance': round(tol, 4), 'tick': names[want]},
                 'got': {'rate': round(rate, 4), 'tick': c['tick']}, 'ok': ok}
        return make_result('speed', 'ok' if ok else 'failed', '' if ok else 'battle clock rate not as asked', start, speed=want, kind=rt.get('kind'),
                           settle={'waited_for': f"lead {rt.get('lead_s', 0.5)} s + measure {rt.get('measure_s', 4)} s", 'settled': True}, check=check,
                           evidence={'from': b['raw'], 'to': c['raw']})

    def v_shot(self, start, name):
        if not re.match(r'^[A-Za-z0-9_.-]+$', name):
            raise Refused('a shot name is letters, digits, . _ -')
        if self.shotter is None:
            raise Refused('no shot helper configured')
        settle = self.settle()
        if not settle['settled']:
            return make_result('shot', 'failed', 'step settle: ' + json.dumps(settle), start, settle=settle)
        path, size = self.shotter(name)
        ok = bool(path) and size > 0
        return make_result('shot', 'ok' if ok else 'failed', '' if ok else 'empty shot', start, settle=settle, shot=path,
                           check={'compared': 'shot file written', 'expected': 'size > 0', 'got': size, 'ok': ok}, evidence={'shot': path})

    def v_reset(self, start, sid=None):
        row = resolve_scenario(self.rows, sid) if sid else None
        target = scenario_target(row, self.battles_dir) if row else 'frontend'
        rc, r = self.t(f'reset {target} 240', 260)
        if rc != 0 or not r:
            return make_result('reset', 'failed', f"step reset {target}: {(r or {}).get('reason', 'no result')}", start, evidence={'ctl': r})
        settle = self.settle() if row else {'waited_for': 'frontend', 'settled': True}
        ok = settle['settled']
        return make_result('reset', 'ok' if ok else 'failed', '' if ok else 'step settle', start, path='warm', settle=settle,
                           check={'compared': 'scene after reset', 'expected': target, 'got': settle.get('scene', 'frontend'), 'ok': ok}, evidence={'ctl': r})

    def v_perf(self, start, secs):
        rc, r = self.t(f'perf {int(secs)}', int(secs) + 30)
        if rc != 0 or not r:
            return make_result('perf', 'failed', f"step perf: {(r or {}).get('reason', 'no result (dev.perf off?)')}", start, evidence={'ctl': r})
        cfg = self.cfg.get('perf', {})
        sane = r.get('frames', 0) > 0 and r.get('frame_ms', {}).get('p50', 0) > 0
        check = {'compared': 'frames recorded and a positive median', 'expected': 'frames > 0, p50 > 0', 'got': {'frames': r.get('frames'), 'p50': r.get('frame_ms', {}).get('p50')}, 'ok': sane}
        vram = {'source': cfg.get('vram_source', 'not read: no PC binding')}
        if self.pc is not None:
            vram = self.pc.vram(self.pc.pid())
            check['vram'] = {'expected': 'the game process has dedicated GPU memory', 'got': vram.get('process_dedicated_mb')}
            sane = sane and (vram.get('process_dedicated_mb') or 0) > 0
            check['ok'] = sane
        return make_result('perf', 'ok' if sane else 'failed', '' if sane else 'no usable frames or no VRAM reading', start, check=check,
                           frame_ms=r.get('frame_ms'), frames=r.get('frames'), mem=r.get('mem'), vram=vram, **(self.pc.build_info() if self.pc else {}),
                           evidence={'ctl': r})


def main(argv=None):
    ap = argparse.ArgumentParser(description='control API: one checked JSON result per verb')
    ap.add_argument('--owner', default='claude-ctl')
    ap.add_argument('--adapter', default=None, help='the harness adapter (default: proxy/tools/layout.py harness-adapter)')
    ap.add_argument('--registry', default=str(ROOT / 'registries' / 'scenarios.jsonl'))
    ap.add_argument('--out', help='folder for shots (default <state>/ctl/shots)')
    ap.add_argument('--no-pc', action='store_true', help='no watcher binding: never launch, no shots, no VRAM (a game someone else launched)')
    ap.add_argument('verb')
    ap.add_argument('args', nargs='*')
    a = ap.parse_args(argv)
    if a.verb in PROBE_ONLY:
        print(json.dumps(make_result(a.verb, 'refused', f'{a.verb} is a probe verb: use job.sh ctl directly; scenarios and scripts never use it (rule 78)')))
        return 2
    if a.verb not in VERBS:
        print(json.dumps(make_result(a.verb, 'refused', f'unknown verb; verbs: {", ".join(VERBS)}')))
        return 2
    a.adapter = a.adapter or str(layout.harness_adapter(ROOT))
    adapter = json.loads(Path(a.adapter).read_text(encoding='utf-8'))
    pc = None if a.no_pc else Pc(a.owner, a.adapter, adapter)
    state_dir = Path(adapter.get('state_dir', '.'))
    out_dir = Path(a.out) if a.out else state_dir / 'ctl' / 'shots'
    shotter = (lambda name: pc.shot(name, out_dir)) if pc else None
    ctl = Ctl(job_sh_transport(a.owner, a.adapter), load_scenarios(a.registry), adapter, shotter=shotter, pc=pc,
              session=Session(state_dir / 'ctl' / '_ctl_session.json'))
    res = ctl.run(a.verb, *a.args)
    print(json.dumps(res, indent=2))
    return exit_code(res)


if __name__ == '__main__':
    sys.exit(main())
