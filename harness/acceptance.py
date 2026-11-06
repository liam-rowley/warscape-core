#!/usr/bin/env python3
"""The acceptance gate: one pass proves the harness, the DLL and the control API hold; 20 in a row pass the phase 1 gate (J4, rules 28, 74, 79).

purpose: run N acceptance passes in the background against the committed baseline file (rule 74), stop at the first failure with its evidence, and append one line per pass to the committed ledger; also the pure checks the policy gate reuses (consecutive passes for a build, a pass file and its ledger line)
usage: acceptance.py run --passes N --run RUN_ID [--owner O] [--session S] [--baseline F] [--ledger F] [--max-flakes N] | measure --run RUN_ID [--owner O] [--session S] | check-baseline [--baseline F] | streak --build ID --watcher V [--watcher-sha SHA] [--max-flakes N] [--ledger F] | check-pass FILE... [--ledger F]
when: after every change to proxy/ or harness/ (rule 79: a job branch that changes them needs 20 consecutive ledger passes on its final DLL and watcher build); `check-baseline` and the helpers run in the tests gate
not-a-verb: orchestrates PC sessions through harness/ctl.py and job.sh (game-agnostic: the scenario list is the baseline's, the settings files and exe pin come from the adapter); a J12 core candidate

One pass: exe sha1 equals the adapter pin (rule 28); launch headless at the baseline's size; `scene` every baseline step; one `cam` pose and one
`shot` each; `perf 10` once; a warm reset; a relaunch; exit. Each step is compared with the baseline: load time within its tolerance, the shot
against the baseline shot (mean absolute pixel difference within the step's threshold), every settings file byte-identical after the exit.
A step's verb that is refused or failed fails the pass (nothing is skipped silently). Camera moves are never key or click (rule 78).
A step whose `pose` is null (the campaign: its camera route is open, the game repo's engine fact campaign.camera_route) is shot at the default view.
PC binding (J44, `PcEnv`): each pass takes the game lock, launches through the watcher with the adapter's keys (ctl.py `Pc`), and after the exit
releases the lock and waits for the watcher's byte-for-byte restore before the settings are compared, so the check is the end state Liam sees.
Shots stay on the PC (<state>/acceptance/<run>/pass_NN/); each attempt commits harness/runs/<run>/pass_NN.json (schema 2, schemas/acceptance_pass.schema.json:
results, the shot sha256s, and the evidence block: exe, baseline, kit, DLL and watcher shas, the launches with the build of each from its own proxy.log line),
and its ledger line names the run and that file and carries its sha256 (rule 79 refuses a line whose evidence is not committed). A lost headless start that
survived the retry, before the build ran, is a `flake` (classify), not a fail; the adapter's acceptance.max_flakes (default 1, at most 3) are allowed per run
and a flake never counts as a pass. A run id with evidence is refused, and the installed watcher must equal the core's watcher.ps1 byte for byte. `measure` makes the baseline from two
passes: the first's load times and shots, the second's shot difference sets each step's threshold (a step above `NONDET_DIFF` is marked not
deterministic, with why).
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# the game repo and its adapters come from proxy/tools/layout.py (J12): the same answer before and after the move to warscape-core
_OWN = next(d for d in (HERE, *HERE.parents) if (d / 'wsc.toml').is_file())
sys.path.insert(0, str(_OWN / 'proxy' / 'tools'))
import layout  # noqa: E402
ROOT = layout.game_root(_OWN)
BASELINE = ROOT / 'harness' / 'acceptance' / 'baseline.json'
LEDGER = ROOT / 'harness' / 'acceptance' / 'ledger.jsonl'
NEEDED = 20   # rule 79
LOAD_TOLERANCE_PCT = 150   # absolute load times vary with the PC's state (J3: 18.2 s and 3.4 s on one morning); the limit is 2.5 x the baseline
MIN_THRESHOLD, NONDET_DIFF = 4.0, 8.0   # mean abs pixel difference: land without the fixed-sky pack 9.6-11.0, with it 2.6-2.7 (run 20261030_j44pc)
KINDS = ('land', 'siege', 'naval', 'historical', 'campaign')


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha(path, algo='sha256'):
    h = hashlib.new(algo)
    h.update(Path(path).read_bytes())
    return h.hexdigest()


# ---- the baseline file (rule 74) -------------------------------------------------------------------------------------------
def baseline_problems(b):
    """Schema check of the baseline: what a pass is compared with. Returns a list of problems (empty = valid)."""
    errs = []
    for k in ('schema', 'date', 'build_id', 'fresh_boot', 'size', 'exe_sha1', 'steps', 'settings_files'):
        if k not in b:
            errs.append(f'baseline lacks "{k}"')
    if errs:
        return errs
    if b['schema'] != 1:
        errs.append('baseline schema must be 1')
    if not isinstance(b['fresh_boot'], bool):
        errs.append('fresh_boot is true or false (load times vary with the PC state: J3)')
    if not str(b['size']).count('x') == 1:
        errs.append('size is WxH')
    if not isinstance(b['steps'], list) or not b['steps']:
        errs.append('steps is a non-empty list')
        return errs
    seen = set()
    for i, s in enumerate(b['steps']):
        w = f'steps[{i}]'
        for k in ('scenario', 'kind', 'pose', 'load_time_s', 'load_tolerance_pct', 'shot', 'shot_threshold', 'deterministic'):
            if k not in s:
                errs.append(f'{w} lacks "{k}"')
        if s.get('kind') not in KINDS:
            errs.append(f'{w}.kind is one of {", ".join(KINDS)}')
        if s.get('scenario') in seen:
            errs.append(f'{w}: scenario {s.get("scenario")} twice')
        seen.add(s.get('scenario'))
        if s.get('deterministic') is False and not s.get('why_not'):
            errs.append(f'{w}: a non-deterministic scenario says why (never silent)')
    missing = [k for k in KINDS if k not in {s.get('kind') for s in b['steps']}]
    if missing:
        errs.append('the baseline covers every kind; missing: ' + ', '.join(missing))
    return errs


def load_baseline(path):
    p = Path(path)
    if not p.exists():
        raise SystemExit(f'acceptance: no baseline file at {p}: acceptance refuses to run without one (rule 74)')
    b = json.loads(p.read_text(encoding='utf-8'))
    errs = baseline_problems(b)
    if errs:
        raise SystemExit('acceptance: the baseline is invalid:\n  ' + '\n  '.join(errs))
    return b


# ---- comparisons -------------------------------------------------------------------------------------------------------------
def load_time_ok(baseline_s, got_s, tolerance_pct):
    lim = baseline_s * (1 + tolerance_pct / 100.0)
    return got_s <= lim, {'compared': 'load time', 'baseline_s': baseline_s, 'got_s': got_s, 'limit_s': round(lim, 2)}


def mean_abs_diff(a_bytes, b_bytes):
    """Mean absolute per-channel difference (0-255) between two images, at the smaller size. Needs Pillow."""
    import io
    from PIL import Image
    a, b = Image.open(io.BytesIO(a_bytes)).convert('RGB'), Image.open(io.BytesIO(b_bytes)).convert('RGB')
    w, h = min(a.width, b.width), min(a.height, b.height)
    a, b = a.resize((w, h)), b.resize((w, h))
    pa, pb = a.tobytes(), b.tobytes()
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)


def shot_ok(diff, threshold):
    return diff <= threshold, {'compared': 'shot against the baseline shot', 'mean_abs_diff': round(diff, 3), 'threshold': threshold}


def settings_unchanged(before, after):
    """Both are {file id: sha256 or None (absent)}. Byte-identical means the same map."""
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    return not changed, {'compared': 'settings files after the exit', 'changed': changed}


def exe_pin_ok(exe_sha1, pin):
    return exe_sha1 == pin, {'compared': 'the game exe sha1 against the pin (rule 28)', 'expected': pin, 'got': exe_sha1}


# ---- the ledger (rule 79) ----------------------------------------------------------------------------------------------------
def read_ledger(text):
    return [json.loads(line) for line in (text or '').splitlines() if line.strip()]


MAX_FLAKES_CAP = 3   # W9: no adapter can allow more flakes than this per run (a larger number would hide a launch rate worth fixing)
SCHEMA = 2           # the pass file's and the ledger line's shape (W9)
FLAKE_CAUSE = 'headless_launch_lost'


def ledger_line(n, build_id, watcher, kit, passed, steps, branch='', run='', evidence='', result=None, doc=None, file_sha=None, flakes_allowed=None):
    """One attempt. `run` is the harness/runs/<run> folder, `evidence` the committed pass file in it (rule 79 checks it exists: J4 review 7).
    With `doc` (the pass file's content) and `file_sha` (sha256 of its bytes) the line also carries the schema-2 facts (W9, H3)."""
    ln = {'pass': n, 'utc': utc(), 'build_id': build_id, 'watcher': watcher, 'kit': kit, 'branch': branch, 'run': run, 'evidence': evidence,
          'result': result or ('pass' if passed else 'fail'), 'steps': steps}
    if doc is not None:
        ev = doc.get('evidence') or {}
        ln.update(schema=SCHEMA, watcher_sha=ev.get('watcher_sha256'), dll_sha256=ev.get('dll_sha256'), kit_sha256=ev.get('kit_sha256'),
                  evidence_sha256=file_sha, flakes_allowed=flakes_allowed)
    return ln


def streak(lines, build_id, watcher, max_flakes=0, watcher_sha=None):
    """Passes in a row at the end of the ledger on this build and watcher: a fail, or a line of another build or watcher, ends the run.
    A `flake` line (W9) of this build or of build null is skipped without counting, up to max_flakes of them; one more ends the run. With
    watcher_sha, a line whose watcher_sha differs (or is absent) ends it: the watcher is its bytes, not its $Version."""
    n = flakes = 0
    for ln in reversed(lines):
        if ln.get('watcher') != watcher or (watcher_sha is not None and ln.get('watcher_sha') != watcher_sha):
            break
        if ln.get('result') == 'pass' and ln.get('build_id') == build_id:
            n += 1
        elif ln.get('result') == 'flake' and ln.get('build_id') in (build_id, None):
            flakes += 1
            if flakes > max_flakes:
                break
        else:
            break
    return n


def classify(passed, steps):
    """pass | fail | flake. A flake is a lost headless launch (cause headless_launch_lost: two attempts ended before on_virtual) as the FIRST failed
    step (the cleanup is a step too), with the exe_sha1 step passed. Everything else that fails is a fail: the build under test must have run to be judged (W9, decision 4)."""
    if passed:
        return 'pass'
    first = next((v for v in steps.values() if not v.get('ok')), {})
    return 'flake' if first.get('cause') == FLAKE_CAUSE and (steps.get('exe_sha1') or {}).get('ok') is True else 'fail'


def build_checks(launches, dll_file_sha):
    """[(step, ok, detail)] over the pass's launches (ctl.Pc.launches): the first names the build, a later launch on another build fails
    (build_stable), and a DLL self-hash logged by a launch must equal the installed file's (dll_hash: the file changed under the run)."""
    builds = [l.get('build') for l in launches]
    out = []
    ok = bool(builds) and builds[0] is not None and all(b in (None, builds[0]) for b in builds) and None not in builds
    out.append(('build_stable', ok, {'compared': 'the build each launch logged in proxy.log (pid-matched), all equal and present', 'launches': builds}))
    logged = sorted({l['dll_sha256_logged'] for l in launches if l.get('dll_sha256_logged')})
    ok = all(h == dll_file_sha for h in logged)
    out.append(('dll_hash', ok, {'compared': 'the DLL sha256 the launches logged against the installed d3d9.dll', 'file': dll_file_sha, 'logged': logged}))
    return out


def ledger_line_matches(line, doc, file_sha):
    """Problems (empty = the line and the pass file agree) between a schema-2 ledger line and its pass file (H3)."""
    ev = doc.get('evidence') or {}
    want = {'pass': doc.get('pass'), 'build_id': doc.get('build_id'), 'watcher': doc.get('watcher'), 'kit': doc.get('kit'), 'result': doc.get('result'),
            'schema': doc.get('schema'), 'watcher_sha': ev.get('watcher_sha256'), 'dll_sha256': ev.get('dll_sha256'), 'kit_sha256': ev.get('kit_sha256'),
            'evidence_sha256': file_sha, 'steps': {k: v.get('ok') for k, v in (doc.get('steps') or {}).items()}}
    return [f'ledger {k} is {line.get(k)!r}, the pass file says {v!r}' for k, v in want.items() if line.get(k) != v]


PASS_REQUIRED = ('schema', 'pass', 'start_utc', 'end_utc', 'result', 'passed', 'build_id', 'build_source', 'watcher', 'kit', 'steps', 'evidence')
EVIDENCE_REQUIRED = ('exe_sha1', 'baseline_sha256', 'shots', 'kit_sha256', 'dll_sha256', 'dll_sha256_logged', 'watcher_sha256', 'watcher_kit_sha256', 'launches')


def pass_problems(doc):
    """Problems (empty = valid schema-2 evidence) of a pass file's content. A file without `schema` is legacy and is reported as such (also schemas/acceptance_pass.schema.json)."""
    if not isinstance(doc, dict) or 'schema' not in doc:
        return ['legacy pass file (no schema field, schema 1): not evidence of a streak since W9']
    out = [f'lacks "{k}"' for k in PASS_REQUIRED if k not in doc]
    if doc.get('schema') != SCHEMA:
        out.append(f'schema must be {SCHEMA}')
    if doc.get('result') not in ('pass', 'fail', 'flake'):
        out.append('result is pass, fail or flake')
    if doc.get('build_source') != 'proxy.log':
        out.append('build_source is proxy.log')
    if doc.get('result') == 'pass' and not doc.get('build_id'):
        out.append('a pass names its build_id (a launch that never logged one cannot pass)')
    ev = doc.get('evidence')
    if isinstance(ev, dict):
        out += [f'evidence lacks "{k}"' for k in EVIDENCE_REQUIRED if k not in ev]
        for k, v in (ev.get('shots') or {}).items():
            if not (isinstance(v, dict) and len(str(v.get('sha256', ''))) == 64 and isinstance(v.get('bytes'), int)):
                out.append(f'evidence.shots.{k} needs sha256 and bytes')
    elif 'evidence' in doc:
        out.append('evidence is an object')
    return out


# ---- one pass ----------------------------------------------------------------------------------------------------------------
def run_pass(baseline, env):
    """env supplies: exe_sha1(), settings(), launch(size), exit(), relaunch(), ctl (a harness Ctl), shot_diff(step, shot result) -> float, pin; optional
    (W9) launches() -> ctl.Pc.launches and dll_sha256() -> the installed DLL's sha256, which add the build_stable and dll_hash steps.
    Returns (passed, steps) where steps maps a step name to {ok, check or reason}; stops at the first failed step."""
    steps, passed = {}, True

    def record(name, ok, detail):
        nonlocal passed
        steps[name] = {'ok': bool(ok), **detail}
        passed = passed and bool(ok)
        return bool(ok)

    def start(name, size):   # a launch that the retry could not save carries its cause (ctl.HeadlessLaunchLost.cause), so classify can call it a flake
        try:
            env[name](size)
            return True
        except Exception as e:
            if getattr(e, 'cause', None) != FLAKE_CAUSE:
                raise
            return record(name, False, {'reason': f'{type(e).__name__}: {e}', 'cause': e.cause})

    def failed(name, r):
        return record(name, False, {'reason': r['reason'], **({'cause': r['cause']} if r.get('cause') else {})})

    before = env['settings']()
    ok, d = exe_pin_ok(env['exe_sha1'](), baseline['exe_sha1'])
    if not record('exe_sha1', ok, d):
        return False, steps
    if not start('launch', baseline['size']):
        return False, steps
    for s in baseline['steps']:
        sid = s['scenario']
        r = env['ctl'].run('scene', sid)
        if r['status'] != 'ok':
            failed(f'{sid}:scene', r)
            return False, steps
        ok, d = load_time_ok(s['load_time_s'], r.get('load_s') or 0, s['load_tolerance_pct'])
        d['path'] = r.get('path')   # launch, relaunch or reset, and a recorded launch retry (ctl.Pc.launch)
        if not record(f'{sid}:load', ok, d):
            return False, steps
        if s['pose'] is not None:
            r = env['ctl'].run('cam', f"{sid}:{s['pose']}")
            if not record(f'{sid}:cam', r['status'] == 'ok', {'reason': r['reason'], 'check': r['check']}):
                return False, steps
        r = env['ctl'].run('shot', f'{sid}_{s["pose"] or "default"}')
        hashed = {}
        if r.get('shot') and Path(r['shot']).is_file():   # W9 (H3): the file ctl wrote, hashed where it lies
            b = Path(r['shot']).read_bytes()
            hashed = {'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}
        if not record(f'{sid}:shot', r['status'] == 'ok', {'reason': r['reason'], 'check': r['check'], 'shot': r.get('shot'), **hashed}):
            return False, steps
        if s['deterministic']:
            ok, d = shot_ok(env['shot_diff'](s, r), s['shot_threshold'])
            if not record(f'{sid}:shot_match', ok, d):
                return False, steps
    r = env['ctl'].run('perf', '10')
    if not record('perf', r['status'] == 'ok', {'reason': r['reason'], 'check': r['check']}):
        return False, steps
    r = env['ctl'].run('reset', baseline['steps'][0]['scenario'])
    if not record('warm_reset', r['status'] == 'ok', {'reason': r['reason'], 'check': r['check']}):
        return False, steps
    env['exit']()
    if not start('relaunch', baseline['size']):
        return False, steps
    env['exit']()
    if 'launches' in env:
        for name, ok, d in build_checks(env['launches'](), env['dll_sha256']()):
            if not record(name, ok, d):
                return False, steps
    ok, d = settings_unchanged(before, env['settings']())
    record('settings_identical', ok, d)
    return passed, steps


# ---- the PC binding (J44) ---------------------------------------------------------------------------------------------------
def load_ctl():
    import importlib.util
    spec = importlib.util.spec_from_file_location('ctl', HERE / 'ctl.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class PcEnv:
    """run_pass's env on the PC: the lock per pass, launch and exit through ctl.Pc, the settings after the watcher's restore, shots on the PC."""
    def __init__(self, owner, session, adapter_path, out_dir, baseline_dir=None, sleep=None):
        import time
        self.ctlmod = load_ctl()
        self.adapter_path = str(adapter_path)
        self.a = json.loads(Path(adapter_path).read_text(encoding='utf-8'))
        self.owner, self.session, self.out_dir, self.baseline_dir = owner, session, Path(out_dir), Path(baseline_dir or BASELINE.parent)
        self.sleep = sleep or time.sleep
        self.pc = self.ctlmod.Pc(owner, adapter_path, self.a)
        self.pc.evidence_dir = self.out_dir / 'launch_evidence'   # W9 (B60): a failed first launch attempt's logs, before the retry recreates them
        rows = self.ctlmod.load_scenarios(ROOT / 'registries' / 'scenarios.jsonl')
        state = Path(self.a['state_dir'])
        self.ctl = self.ctlmod.Ctl(self.ctlmod.job_sh_transport(owner, adapter_path), rows, self.a, shotter=lambda n: self.pc.shot(n, self.out_dir),
                                   pc=self.pc, session=self.ctlmod.Session(state / 'ctl' / '_ctl_session.json'))
        self.locked = False

    def sh(self, *args):
        import subprocess
        p = subprocess.run([self.ctlmod.bash(), str(HERE / 'job.sh'), '--adapter', self.adapter_path, *args], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def lock(self):
        if not self.locked:
            rc, out = self.sh('lock', self.owner, self.session, 'acceptance pass')
            if rc != 0:
                raise RuntimeError(f'acceptance: cannot take the game lock: {out.strip()}')
            self.locked = True
        else:
            self.touch()

    def touch(self):
        self.sh('touch', self.owner)   # W10: touch refreshes only the holder's lock; a bare touch is refused

    def release(self):
        """Release the lock and wait until the watcher has restored every profile (byte for byte) with the game closed."""
        if not self.locked:
            return
        self.sh('unlock', self.owner)
        self.locked = False
        for _ in range(120):
            st = self.pc.status()
            if st.get('profile_active') is None and st.get('lock') is None:
                return
            self.sleep(1)
        raise RuntimeError('acceptance: the watcher did not restore the profile within 120 s of the lock release')

    def config_paths(self):
        out = {}
        for c in self.a['config_files']:
            base = os.path.expandvars(self.a['appdata_dir']) if c['anchor'] == 'appdata' else self.a['game_dir']
            out[c['id']] = Path(base) / c['path']
        return out

    def settings(self):
        if self.locked and self.pc.pid() is None:
            self.release()
        return {k: (sha(p) if p.exists() else None) for k, p in self.config_paths().items()}

    def exe_sha1(self):
        return sha(Path(self.a['game_dir']) / self.a['game_image'], 'sha1')

    def launch(self, size):
        self.lock()
        return self.pc.launch(size)

    def exit(self):
        self.touch()
        return self.pc.exit()

    relaunch = launch

    def shot_diff(self, step, r):
        return mean_abs_diff(Path(r['shot']).read_bytes(), (self.baseline_dir / step['shot']).read_bytes())

    def as_env(self):
        class TouchingCtl:   # every verb refreshes the lock first: a pass is longer than the lock's 20 minutes without a touch
            def __init__(s, env):
                s.env = env

            def run(s, verb, *args):
                s.env.touch()
                return s.env.ctl.run(verb, *args)
        return {'exe_sha1': self.exe_sha1, 'settings': self.settings, 'launch': self.launch, 'exit': self.exit, 'relaunch': self.relaunch,
                'ctl': TouchingCtl(self), 'shot_diff': self.shot_diff, 'launches': lambda: self.pc.launches, 'dll_sha256': self.dll_sha256}

    def identity(self, strict=False):
        """(build, watcher version, kit). strict (W9): the build comes from this run's own launches (proxy.log, pid-matched) and is None when none logged one;
        not strict (measure) keeps the older read."""
        st = self.pc.status()
        if strict:
            try:
                b = self.pc.build_info(strict=True)
            except RuntimeError:
                b = {'build': None, 'kit': self.pc.build_info().get('kit')}
        else:
            b = self.pc.build_info()
        return b.get('build'), st.get('version'), b.get('kit')

    # -- the pass's evidence (W9, H3): the shas that tie a pass to the exact files it ran on
    def state(self):
        return Path(self.a['state_dir'])

    def install_record(self):
        p = self.state() / 'install.json'
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}

    def dll_path(self):
        for f in self.install_record().get('files', []):
            if f.get('path', '').replace('\\', '/').rsplit('/', 1)[-1].lower() == 'd3d9.dll':
                return Path(self.a['game_dir']) / f['path'].replace('\\', '/')
        return Path(self.a['game_dir']) / 'd3d9.dll'

    def dll_sha256(self):
        p = self.dll_path()
        return sha(p) if p.exists() else None

    def evidence(self, baseline_path, baseline_sha):
        kit = self.install_record().get('kit_id')
        mf = self.state() / 'kits' / str(kit) / 'manifest.json'
        inst, kitb = installed_watcher_bytes(self.a), kit_watcher_bytes()
        return {'exe_sha1': self.exe_sha1(), 'baseline_sha256': baseline_sha, 'kit_sha256': sha(mf) if mf.exists() else None,
                'dll_sha256': self.dll_sha256(), 'dll_sha256_logged': next((l['dll_sha256_logged'] for l in self.pc.launches if l.get('dll_sha256_logged')), None),
                'watcher_sha256': hashlib.sha256(inst).hexdigest() if inst else None, 'watcher_kit_sha256': hashlib.sha256(kitb).hexdigest() if kitb else None,
                'launches': list(self.pc.launches)}


def installed_watcher_bytes(adapter):
    """The installed watcher.ps1, opened read-only (W9, decision 9); None when missing. Nothing here writes, renames or locks it."""
    p = Path(adapter['state_dir']) / adapter.get('watcher_subdir', 'watcher') / 'src' / 'watcher.ps1'
    try:
        with open(p, 'rb') as f:
            return f.read()
    except OSError:
        return None


def kit_watcher_bytes():
    """harness/watcher.ps1 as committed at the core's HEAD (in a game repo: the pinned commit), so a dirty working copy is irrelevant; None if git cannot say."""
    r = subprocess.run(['git', '-C', str(HERE), 'show', 'HEAD:./watcher.ps1'], capture_output=True)
    return r.stdout if r.returncode == 0 and r.stdout else None


VERSION_RX = re.compile(rb"\$Version\s*=\s*['\"]([^'\"]+)['\"]")
KIT_FIX = 'send a harness kit (pc_deploy.py kit --what harness, send) and run job.sh update kit=<id>, then start the run'


def watcher_problems(installed, kit, status):
    """The watcher is its bytes (H10): the installed watcher.ps1 must equal the core's, and the running watcher must be the installed one. Problems as text."""
    if installed is None:
        return [f'the installed watcher.ps1 cannot be read (not installed under <state_dir>/<watcher_subdir>/src): {KIT_FIX}']
    if kit is None:
        return ['harness/watcher.ps1 cannot be read from the core at git HEAD (git show failed): the watcher cannot be compared']
    out = []
    a, b = hashlib.sha256(installed).hexdigest(), hashlib.sha256(kit).hexdigest()
    if a != b:
        out.append(f'the installed watcher.ps1 (sha256 {a[:12]}) is not the core\'s harness/watcher.ps1 (sha256 {b[:12]}): {KIT_FIX}')
    m = VERSION_RX.search(installed)
    running = (status or {}).get('version')
    if m and running and m.group(1).decode() != running:
        out.append(f'the running watcher reports version {running} but the installed file says {m.group(1).decode()}: it was updated on disk and never restarted; restart it ({KIT_FIX})')
    return out


def run_id_problems(run, ledger_text, runs_dir, state):
    """A --run id that already has evidence is refused (W9, H5): a pass file in the repo, a ledger line, or a pass folder on the PC."""
    out = []
    if list(Path(runs_dir, run).glob('pass_*.json')):
        out.append(f'run {run} already has pass files under {Path(runs_dir, run)}: use a fresh --run id (evidence is never overwritten)')
    if any(str(ln.get('run', '')).rsplit('/', 1)[-1] == run for ln in read_ledger(ledger_text)):
        out.append(f'the ledger already has lines for run {run}: use a fresh --run id')
    if list((Path(state) / 'acceptance' / run).glob('pass_*')):
        out.append(f'{Path(state) / "acceptance" / run} already has pass folders: use a fresh --run id')
    return out


def pass_file(run, n):
    return ROOT / 'harness' / 'runs' / run / f'pass_{n:02d}.json'


def run_problems(a, branch_of=None, has_pil=None, watcher_status=None, watcher_files=None):
    """Checks before pass 1, so a run cannot spend a ledger line on its setup (J45 run 20261031_j45acc: pass 1 failed on a missing
    Pillow in the interpreter, and its line carried no branch, which rule 79 never counts). Fills a.branch from git when not given."""
    if not a.branch:
        if branch_of is None:
            r = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True)
            branch_of = lambda: r.stdout.strip() if r.returncode == 0 else ''
        a.branch = branch_of()
    out = []
    if not a.branch or a.branch == 'HEAD':
        out.append('no branch: pass --branch job/J<n> (rule 79 counts a pass only for the branch it names)')
    if has_pil is None:
        has_pil = importlib.util.find_spec('PIL') is not None
    if not has_pil:
        out.append(f'Pillow is not installed for {sys.executable} (the shot comparison needs it): run with the python that has it, '
                   f'or `{Path(sys.executable).name} -m pip install pillow`')
    # J12 run 20261031_j12acc: pass 1 began under a sitting's own lock and active headless overlay (same owner), so its "before" settings
    # held the overlay and the release restored the older files: settings_identical failed with every game step passing. A run starts
    # only with no lock and no active profile, so pass 1 compares against the files Liam has.
    st = watcher_status if watcher_status is not None else {}
    if st.get('lock'):
        out.append(f"the game lock is held ({st['lock'].get('owner', '?') if isinstance(st['lock'], dict) else st['lock']}): release it "
                   '(job.sh unlock <owner>) and let the watcher restore, then start the run; each pass takes and releases its own lock')
    if st.get('profile_active'):
        out.append(f"a profile is active ({st['profile_active']}): release the lock that applied it and wait for the restore before the run")
    if watcher_files is not None:   # (installed bytes, the core's bytes): W9, decision 9
        out += watcher_problems(*watcher_files, st)
    return out


def who(a):
    """W10 (H2): the lock owner is the session. --owner and --session default to the session id ($WSC_SESSION_ID, then the id Claude Code
    exports); with none the run is refused and the message names the fix. False on a refusal."""
    a.owner, a.session, why = load_ctl().resolve_identity(a.owner, a.session)
    if why:
        print(f'acceptance {a.cmd}: refused: {why}', file=sys.stderr)
    return not why


def max_flakes_of(ad, cli):
    """The flakes allowed per run: the adapter's acceptance.max_flakes (default 1), --max-flakes may only lower it, never above MAX_FLAKES_CAP. (value, problem)."""
    n = (ad.get('acceptance') or {}).get('max_flakes', 1)
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= MAX_FLAKES_CAP:
        return None, f'acceptance.max_flakes is {n!r}: a whole number from 0 to {MAX_FLAKES_CAP}'
    if cli is not None and not 0 <= cli <= n:
        return None, f'--max-flakes {cli} may only lower the adapter\'s {n} (and is at most {MAX_FLAKES_CAP})'
    return n if cli is None else cli, None


def cmd_run(a):
    baseline = load_baseline(a.baseline)   # refuses without a valid baseline (rule 74)
    ad = json.loads(Path(a.adapter).read_text(encoding='utf-8'))
    allowed, why = max_flakes_of(ad, a.max_flakes)
    if why:
        print(f'acceptance run: refused: {why}', file=sys.stderr)
        return 2
    try:   # the watcher's own status file (rewritten every 2 s); unreadable = nothing known, the passes then find out
        st = json.loads(Path(ad['state_dir'], ad.get('watcher_subdir', 'watcher'), 'watcher.status').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, KeyError):
        st = {}
    state = Path(ad['state_dir'])
    led = Path(a.ledger)
    bad = run_problems(a, watcher_status=st, watcher_files=(installed_watcher_bytes(ad), kit_watcher_bytes()))
    bad += run_id_problems(a.run, led.read_text(encoding='utf-8') if led.exists() else '', ROOT / 'harness' / 'runs', state)
    if bad:
        for b in bad:
            print(f'acceptance run: refused: {b}', file=sys.stderr)
        return 2
    if not who(a):
        return 2
    base_sha = sha(a.baseline)
    # J12 run 20261031_j12acc2: ctl.py writes the launch keys into the mod ini before its launch, outside any snapshot, so on a fresh
    # install pass 1 read its "before" without them and failed settings_identical. The keys are the run's setup: applied once here,
    # before pass 1 reads the settings (every earlier run had them in the ini already).
    pre = PcEnv(a.owner, a.session, a.adapter, state / 'acceptance' / a.run / 'setup', Path(a.baseline).parent)
    miss = pre.pc.missing_keys()
    if miss:
        pre.pc.set_keys(miss)
        print(f"acceptance: launch keys applied before pass 1: {', '.join(sorted(miss))}")
    done = flakes = attempt = 0
    while done < a.passes:   # an attempt is a pass file and a ledger line; a flake is one that does not count and does not stop the run (W9)
        attempt += 1
        n = attempt
        env = PcEnv(a.owner, a.session, a.adapter, state / 'acceptance' / a.run / f'pass_{n:02d}', Path(a.baseline).parent)
        t0 = utc()
        try:
            passed, steps = run_pass(baseline, env.as_env())
        except Exception as e:   # a harness failure is a failed pass with its reason, never a traceback that loses the ledger line
            passed, steps = False, {'harness': {'ok': False, 'reason': f'{type(e).__name__}: {e}'}}
        finally:
            try:
                env.exit()
                env.release()
            except Exception as e:
                passed, steps = False, dict(steps, cleanup={'ok': False, 'reason': f'{type(e).__name__}: {e}',
                                                            **({'cause': e.cause} if getattr(e, 'cause', None) else {})})
        result = classify(passed, steps)
        build, watcher, kit = env.identity(strict=True)
        if build is None:
            passed, result = False, ('fail' if result == 'pass' else result)
            steps.setdefault('build_id', {'ok': False, 'reason': 'no launch of this pass logged its build in proxy.log: a pass cannot be labelled'})
        evidence = dict(env.evidence(a.baseline, base_sha), shots=shots_evidence(steps, baseline, Path(a.baseline).parent))
        doc = {'schema': SCHEMA, 'pass': n, 'start_utc': t0, 'end_utc': utc(), 'result': result, 'passed': passed, 'build_id': build, 'build_source': 'proxy.log',
               'watcher': watcher, 'kit': kit, 'steps': steps, 'evidence': evidence}
        pf = pass_file(a.run, n)
        pf.parent.mkdir(parents=True, exist_ok=True)
        rel = pf.relative_to(ROOT).as_posix()
        with open(pf, 'x', encoding='utf-8', newline='\n') as f:   # 'x': a race can never overwrite earlier evidence
            f.write(json.dumps(doc, indent=1) + '\n')
        line = ledger_line(n, build, watcher, kit, passed, {k: v['ok'] for k, v in steps.items()}, a.branch, f'harness/runs/{a.run}', rel,
                           result=result, doc=doc, file_sha=sha(pf), flakes_allowed=allowed)
        with open(led, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(line) + '\n')
        print(f'acceptance pass {n}: {result.upper() if result != "pass" else "pass"} ({rel})', flush=True)
        bad = next((k for k, v in steps.items() if not v['ok']), '?')
        if result == 'pass':
            done += 1
            continue
        if result == 'flake':
            flakes += 1
            print(f'acceptance: flake {flakes} of {allowed} allowed (the headless start was lost twice before the build ran): {bad}: {steps.get(bad)}', flush=True)
            if flakes <= allowed:
                continue
            print('acceptance: stopped: the flake allowance is spent', flush=True)
            return 1
        print(f'acceptance: stopped at the first failure: {bad}: {steps.get(bad)}', flush=True)
        return 1
    return 0


def shots_evidence(steps, baseline, baseline_dir):
    """{step: {sha256, bytes, baseline_sha256?}} for every shot step the pass reached (the baseline shot's sha256 where the step is compared)."""
    out = {}
    for s in baseline['steps']:
        v = steps.get(f"{s['scenario']}:shot")
        if v and v.get('sha256'):
            out[s['scenario']] = {'sha256': v['sha256'], 'bytes': v['bytes']}
            bp = Path(baseline_dir) / s['shot']
            if s['deterministic'] and bp.is_file():
                out[s['scenario']]['baseline_sha256'] = sha(bp)
    return out


def cmd_check_pass(a):
    """Each FILE must be valid schema-2 evidence; with --ledger the ledger line naming it must agree (and exist)."""
    lines = read_ledger(Path(a.ledger).read_text(encoding='utf-8')) if a.ledger and Path(a.ledger).exists() else None
    bad = 0
    for f in a.files:
        p = Path(f)
        probs = []
        try:
            doc = json.loads(p.read_text(encoding='utf-8'))
            probs = pass_problems(doc)
        except (OSError, ValueError) as e:
            doc, probs = None, [f'unreadable: {e}']
        if lines is not None and doc is not None and not probs:
            try:
                rel = p.resolve().relative_to(ROOT).as_posix()
            except ValueError:
                rel = p.as_posix()
            mine = [ln for ln in lines if ln.get('evidence') == rel or str(ln.get('evidence', '')).endswith(p.name) and p.as_posix().endswith(str(ln.get('evidence')))]
            if len(mine) != 1:
                probs.append(f'{len(mine)} ledger lines name this file (need exactly 1)')
            else:
                probs += ledger_line_matches(mine[0], doc, sha(p))
        print(f'{f}: ' + ('ok' if not probs else 'PROBLEMS: ' + '; '.join(probs)))
        bad += bool(probs)
    return 1 if bad else 0


def cmd_measure(a):
    """Two passes over the adapter's acceptance order: pass 1 finds the poses (`cam read` = the engine's deployment view, then that view turned
    60 degrees) and takes the baseline shots; pass 2 sets the same pose and its shot difference sets the threshold. Writes baseline.json, the
    shots and poses.json (for the scenario rows); a person never writes them by hand."""
    if not who(a):
        return 2
    ad = json.loads(Path(a.adapter).read_text(encoding='utf-8'))
    order = ad['acceptance']['order']
    state = Path(ad['state_dir'])
    shots_dir = BASELINE.parent / 'shots'
    shots_dir.mkdir(parents=True, exist_ok=True)
    rec, poses = {}, {}
    for k in (1, 2):
        env = PcEnv(a.owner, a.session, a.adapter, state / 'acceptance' / a.run / f'measure_{k}')
        c = env.ctl
        try:
            env.lock()
            build, watcher, kit = env.identity()
            for sid in order:
                row = c.rows[sid]
                r = c.run('scene', sid)
                if r['status'] != 'ok':
                    raise SystemExit(f'measure {k}: scene {sid}: {r["reason"]}')
                e = rec.setdefault(sid, {'kind': row['kind'], 'loads': [], 'diff': None})
                e['loads'].append(r.get('load_s') or 0)
                if row['kind'] != 'campaign':
                    if k == 1:
                        g = c.run('cam', 'read')
                        if g['status'] != 'ok':
                            raise SystemExit(f'measure: cam read {sid}: {g["reason"]}')
                        p1 = {f: round(g['got'][f], 2) for f in ('x', 'y', 'z', 'yaw', 'pitch')}
                        p2 = dict(p1, yaw=round(((p1['yaw'] + 60 + 180) % 360) - 180, 2))
                        for pid, pz in (('turned', p2), ('deploy', p1)):
                            r = c.run('cam', *[str(pz[f]) for f in ('x', 'y', 'z', 'yaw', 'pitch')])
                            if r['status'] != 'ok':
                                raise SystemExit(f'measure: cam {sid} {pid}: {r["reason"]}')
                        poses[sid] = {'deploy': p1, 'turned': p2}
                    else:
                        p1 = poses[sid]['deploy']
                        r = c.run('cam', *[str(p1[f]) for f in ('x', 'y', 'z', 'yaw', 'pitch')])
                        if r['status'] != 'ok':
                            raise SystemExit(f'measure: cam {sid} deploy (pass 2): {r["reason"]}')
                r = c.run('shot', f'{sid}_measure{k}')
                if r['status'] != 'ok':
                    raise SystemExit(f'measure: shot {sid}: {r["reason"]}')
                if k == 1:
                    (shots_dir / f'{sid}.jpg').write_bytes(Path(r['shot']).read_bytes())
                else:
                    e['diff'] = round(mean_abs_diff(Path(r['shot']).read_bytes(), (shots_dir / f'{sid}.jpg').read_bytes()), 3)
            if k == 1:
                r = c.run('perf', '10')
                rec['_perf'] = {kk: r.get(kk) for kk in ('frame_ms', 'frames', 'mem', 'vram', 'build', 'size')}
        finally:
            env.exit()
            env.release()
    steps = []
    for sid in order:
        e = rec[sid]
        det = e['diff'] is not None and e['diff'] <= NONDET_DIFF
        st = {'scenario': sid, 'kind': e['kind'], 'pose': None if e['kind'] == 'campaign' else 'deploy', 'load_time_s': max(e['loads']),
              'load_tolerance_pct': LOAD_TOLERANCE_PCT, 'shot': f'shots/{sid}.jpg', 'shot_threshold': round(max(MIN_THRESHOLD, 2 * (e['diff'] or 0)), 2),
              'deterministic': det, 'measured_diff': e['diff']}
        if not det:
            st['why_not'] = f"two launches differ by {e['diff']} (mean abs diff > {NONDET_DIFF}): load and readback still count, the shot is not compared"
        steps.append(st)
    b = {'schema': 1, 'date': utc()[:10], 'build_id': build, 'watcher': watcher, 'kit': kit, 'fresh_boot': False, 'size': ad['ctl']['launch']['size'],
         'exe_sha1': json.loads((layout.proxy_adapter(ROOT) / 'identity.json').read_text(encoding='utf-8'))['sha1'], 'run': f'harness/runs/{a.run}',
         'steps': steps, 'settings_files': [c['id'] for c in ad['config_files']], 'perf': rec.get('_perf')}
    errs = baseline_problems(b)
    if errs:
        raise SystemExit('measure: the measured baseline is invalid: ' + '; '.join(errs))
    BASELINE.write_text(json.dumps(b, indent=1) + '\n', encoding='utf-8', newline='\n')
    out = ROOT / 'harness' / 'runs' / a.run / 'poses.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(poses, indent=1) + '\n', encoding='utf-8', newline='\n')
    print(f'measure: {BASELINE.relative_to(ROOT)} ({len(steps)} steps), poses in {out.relative_to(ROOT)}')
    for st in steps:
        print(f"  {st['scenario']:22} {st['kind']:10} load {st['load_time_s']} s  diff {st['measured_diff']}  deterministic {st['deterministic']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='acceptance gate')
    sub = ap.add_subparsers(dest='cmd', required=True)
    adapter = str(layout.harness_adapter(ROOT))
    r = sub.add_parser('run'); r.add_argument('--passes', type=int, default=NEEDED); r.add_argument('--owner', default=None)
    r.add_argument('--baseline', default=str(BASELINE)); r.add_argument('--ledger', default=str(LEDGER)); r.add_argument('--run', required=True)
    r.add_argument('--session', default=None); r.add_argument('--adapter', default=adapter); r.add_argument('--branch', default='')
    r.add_argument('--max-flakes', type=int, default=None, dest='max_flakes')
    m = sub.add_parser('measure'); m.add_argument('--run', required=True); m.add_argument('--owner', default=None)
    m.add_argument('--session', default=None); m.add_argument('--adapter', default=adapter)
    c = sub.add_parser('check-baseline'); c.add_argument('--baseline', default=str(BASELINE))
    s = sub.add_parser('streak'); s.add_argument('--build', required=True); s.add_argument('--watcher', required=True); s.add_argument('--ledger', default=str(LEDGER))
    s.add_argument('--watcher-sha', default=None); s.add_argument('--max-flakes', type=int, default=0)
    k = sub.add_parser('check-pass'); k.add_argument('files', nargs='+'); k.add_argument('--ledger', default=None)
    a = ap.parse_args(argv)
    if a.cmd == 'check-baseline':
        load_baseline(a.baseline)
        print('baseline ok')
        return 0
    if a.cmd == 'streak':
        lp = Path(a.ledger)
        n = streak(read_ledger(lp.read_text(encoding='utf-8') if lp.exists() else ''), a.build, a.watcher, min(a.max_flakes, MAX_FLAKES_CAP), a.watcher_sha)
        print(f'{n} consecutive passes on build {a.build}, watcher {a.watcher} (need {NEEDED})')
        return 0 if n >= NEEDED else 1
    if a.cmd == 'check-pass':
        return cmd_check_pass(a)
    if a.cmd == 'measure':
        return cmd_measure(a)
    return cmd_run(a)


if __name__ == '__main__':
    sys.exit(main())
