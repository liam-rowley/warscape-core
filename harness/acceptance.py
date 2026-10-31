#!/usr/bin/env python3
"""The acceptance gate: one pass proves the harness, the DLL and the control API hold; 20 in a row pass the phase 1 gate (J4, rules 28, 74, 79).

purpose: run N acceptance passes in the background against the committed baseline file (rule 74), stop at the first failure with its evidence, and append one line per pass to the committed ledger; also the pure checks the policy gate reuses (consecutive passes for a build)
usage: acceptance.py run --passes N --run RUN_ID [--owner O] [--baseline F] [--ledger F] | measure --run RUN_ID [--owner O] | check-baseline [--baseline F] | streak --build ID --watcher V [--ledger F]
when: after every change to proxy/ or harness/ (rule 79: a job branch that changes them needs 20 consecutive ledger passes on its final DLL and watcher build); `check-baseline` and the helpers run in the tests gate
not-a-verb: orchestrates PC sessions through harness/core/ctl.py and job.sh (game-agnostic: the scenario list is the baseline's, the settings files and exe pin come from the adapter); a J12 core candidate

One pass: exe sha1 equals the adapter pin (rule 28); launch headless at the baseline's size; `scene` every baseline step; one `cam` pose and one
`shot` each; `perf 10` once; a warm reset; a relaunch; exit. Each step is compared with the baseline: load time within its tolerance, the shot
against the baseline shot (mean absolute pixel difference within the step's threshold), every settings file byte-identical after the exit.
A step's verb that is refused or failed fails the pass (nothing is skipped silently). Camera moves are never key or click (rule 78).
A step whose `pose` is null (the campaign: its camera route is open, the game repo's engine fact campaign.camera_route) is shot at the default view.
PC binding (J44, `PcEnv`): each pass takes the game lock, launches through the watcher with the adapter's keys (ctl.py `Pc`), and after the exit
releases the lock and waits for the watcher's byte-for-byte restore before the settings are compared, so the check is the end state Liam sees.
Shots stay on the PC (<state>/acceptance/<run>/pass_NN/); each pass commits harness/runs/<run>/pass_NN.json (results, shot sha256 and diffs),
and its ledger line names the run and that file (rule 79 refuses a line whose evidence is not committed). `measure` makes the baseline from two
passes: the first's load times and shots, the second's shot difference sets each step's threshold (a step above `NONDET_DIFF` is marked not
deterministic, with why).
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
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


def ledger_line(n, build_id, watcher, kit, passed, steps, branch='', run='', evidence=''):
    """One pass. `run` is the harness/runs/<run> folder, `evidence` the committed pass file in it (rule 79 checks it exists: J4 review 7)."""
    return {'pass': n, 'utc': utc(), 'build_id': build_id, 'watcher': watcher, 'kit': kit, 'branch': branch, 'run': run, 'evidence': evidence,
            'result': 'pass' if passed else 'fail', 'steps': steps}


def streak(lines, build_id, watcher):
    """Passes in a row at the end of the ledger on this build and watcher: a fail, or a line of another build or watcher, ends the run."""
    n = 0
    for ln in reversed(lines):
        if ln.get('result') == 'pass' and ln.get('build_id') == build_id and ln.get('watcher') == watcher:
            n += 1
        else:
            break
    return n


# ---- one pass ----------------------------------------------------------------------------------------------------------------
def run_pass(baseline, env):
    """env supplies: exe_sha1(), settings(), launch(size), exit(), relaunch(), ctl (a harness Ctl), shot_diff(step, shot result) -> float, pin.
    Returns (passed, steps) where steps maps a step name to {ok, check or reason}; stops at the first failed step."""
    steps, passed = {}, True

    def record(name, ok, detail):
        nonlocal passed
        steps[name] = {'ok': bool(ok), **detail}
        passed = passed and bool(ok)
        return bool(ok)

    before = env['settings']()
    ok, d = exe_pin_ok(env['exe_sha1'](), baseline['exe_sha1'])
    if not record('exe_sha1', ok, d):
        return False, steps
    env['launch'](baseline['size'])
    for s in baseline['steps']:
        sid = s['scenario']
        r = env['ctl'].run('scene', sid)
        if r['status'] != 'ok':
            record(f'{sid}:scene', False, {'reason': r['reason']})
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
        if not record(f'{sid}:shot', r['status'] == 'ok', {'reason': r['reason'], 'check': r['check'], 'shot': r.get('shot')}):
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
    env['relaunch'](baseline['size'])
    env['exit']()
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
            self.sh('touch')

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
        self.sh('touch')
        return self.pc.exit()

    relaunch = launch

    def shot_diff(self, step, r):
        return mean_abs_diff(Path(r['shot']).read_bytes(), (self.baseline_dir / step['shot']).read_bytes())

    def as_env(self):
        class TouchingCtl:   # every verb refreshes the lock first: a pass is longer than the lock's 20 minutes without a touch
            def __init__(s, env):
                s.env = env

            def run(s, verb, *args):
                s.env.sh('touch')
                return s.env.ctl.run(verb, *args)
        return {'exe_sha1': self.exe_sha1, 'settings': self.settings, 'launch': self.launch, 'exit': self.exit, 'relaunch': self.relaunch,
                'ctl': TouchingCtl(self), 'shot_diff': self.shot_diff}

    def identity(self):
        st = self.pc.status()
        b = self.pc.build_info()
        return b.get('build'), st.get('version'), b.get('kit')


def pass_file(run, n):
    return ROOT / 'harness' / 'runs' / run / f'pass_{n:02d}.json'


def run_problems(a, branch_of=None, has_pil=None, watcher_status=None):
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
    return out


def cmd_run(a):
    baseline = load_baseline(a.baseline)   # refuses without a valid baseline (rule 74)
    ad = json.loads(Path(a.adapter).read_text(encoding='utf-8'))
    try:   # the watcher's own status file (rewritten every 2 s); unreadable = nothing known, the passes then find out
        st = json.loads(Path(ad['state_dir'], ad.get('watcher_subdir', 'watcher'), 'watcher.status').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, KeyError):
        st = {}
    bad = run_problems(a, watcher_status=st)
    if bad:
        for b in bad:
            print(f'acceptance run: refused: {b}', file=sys.stderr)
        return 2
    state = Path(json.loads(Path(a.adapter).read_text(encoding='utf-8'))['state_dir'])
    led = Path(a.ledger)
    # J12 run 20261031_j12acc2: ctl.py writes the launch keys into the mod ini before its launch, outside any snapshot, so on a fresh
    # install pass 1 read its "before" without them and failed settings_identical. The keys are the run's setup: applied once here,
    # before pass 1 reads the settings (every earlier run had them in the ini already).
    pre = PcEnv(a.owner, a.session, a.adapter, state / 'acceptance' / a.run / 'setup', Path(a.baseline).parent)
    miss = pre.pc.missing_keys()
    if miss:
        pre.pc.set_keys(miss)
        print(f"acceptance: launch keys applied before pass 1: {', '.join(sorted(miss))}")
    for n in range(1, a.passes + 1):
        env = PcEnv(a.owner, a.session, a.adapter, state / 'acceptance' / a.run / f'pass_{n:02d}', Path(a.baseline).parent)
        build, watcher, kit = env.identity()
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
                steps = dict(steps, cleanup={'ok': False, 'reason': f'{type(e).__name__}: {e}'})
        pf = pass_file(a.run, n)
        pf.parent.mkdir(parents=True, exist_ok=True)
        rel = pf.relative_to(ROOT).as_posix()
        pf.write_text(json.dumps({'pass': n, 'start_utc': t0, 'end_utc': utc(), 'build_id': build, 'watcher': watcher, 'kit': kit, 'passed': passed,
                                  'steps': steps}, indent=1) + '\n', encoding='utf-8', newline='\n')
        line = ledger_line(n, build, watcher, kit, passed, {k: v['ok'] for k, v in steps.items()}, a.branch, f'harness/runs/{a.run}', rel)
        with open(led, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(line) + '\n')
        print(f'acceptance pass {n}: {"pass" if passed else "FAIL"} ({rel})', flush=True)
        if not passed:
            bad = next((k for k, v in steps.items() if not v['ok']), '?')
            print(f'acceptance: stopped at the first failure: {bad}: {steps.get(bad)}', flush=True)
            return 1
    return 0


def cmd_measure(a):
    """Two passes over the adapter's acceptance order: pass 1 finds the poses (`cam read` = the engine's deployment view, then that view turned
    60 degrees) and takes the baseline shots; pass 2 sets the same pose and its shot difference sets the threshold. Writes baseline.json, the
    shots and poses.json (for the scenario rows); a person never writes them by hand."""
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
    r = sub.add_parser('run'); r.add_argument('--passes', type=int, default=NEEDED); r.add_argument('--owner', default='claude-acceptance')
    r.add_argument('--baseline', default=str(BASELINE)); r.add_argument('--ledger', default=str(LEDGER)); r.add_argument('--run', required=True)
    r.add_argument('--session', default='acceptance'); r.add_argument('--adapter', default=adapter); r.add_argument('--branch', default='')
    m = sub.add_parser('measure'); m.add_argument('--run', required=True); m.add_argument('--owner', default='claude-acceptance')
    m.add_argument('--session', default='acceptance'); m.add_argument('--adapter', default=adapter)
    c = sub.add_parser('check-baseline'); c.add_argument('--baseline', default=str(BASELINE))
    s = sub.add_parser('streak'); s.add_argument('--build', required=True); s.add_argument('--watcher', required=True); s.add_argument('--ledger', default=str(LEDGER))
    a = ap.parse_args(argv)
    if a.cmd == 'check-baseline':
        load_baseline(a.baseline)
        print('baseline ok')
        return 0
    if a.cmd == 'streak':
        lp = Path(a.ledger)
        n = streak(read_ledger(lp.read_text(encoding='utf-8') if lp.exists() else ''), a.build, a.watcher)
        print(f'{n} consecutive passes on build {a.build}, watcher {a.watcher} (need {NEEDED})')
        return 0 if n >= NEEDED else 1
    if a.cmd == 'measure':
        return cmd_measure(a)
    return cmd_run(a)


if __name__ == '__main__':
    sys.exit(main())
