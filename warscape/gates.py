"""The gate runner behind `wsc gates`: deterministic, no network, standard library only.

Every gate returns a Result. Level `error` fails the run; `warn` never does. `--fast` runs every gate except `tests`
(or the list in `wsc.toml` [gates] fast), and is what the pre-push hook runs: well under a minute, no network.
"""
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field

from . import checks, core_version, tools
from .registry import RegistryError, load_all, schema_path
from .schema import check_schema


@dataclass
class Result:
    name: str
    level: str          # ok | warn | error
    summary: str
    details: list = field(default_factory=list)
    seconds: float = 0.0


def _read(ctx, p):
    try:
        return (ctx.root / p).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None


def gate_schemas(ctx):
    """Every schema the repo declares, and every schema the core ships, is within the supported subset."""
    specs = {f'core:{p.name[:-len(".schema.json")]}' for p in (ctx.core_root / 'schemas').glob('*.schema.json')}
    specs |= set(ctx.config['registries'].values())
    errs = []
    for s in sorted(specs):
        sp = schema_path(s, ctx.root)
        try:
            doc = json.loads(sp.read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            errs.append(f'{s}: {e}')
            continue
        errs += [f'{s}: {e}' for e in check_schema(doc)]
    return Result('schemas', 'error' if errs else 'ok', f'{len(errs)} schema problems' if errs else f'{len(specs)} schemas within the supported subset', errs)


def gate_registries(ctx):
    """Rows: strict JSON, canonical form, unique ids, valid against the schema, x-unique clashes, x-ref ids, views current."""
    try:
        regs = load_all(ctx)
    except RegistryError as e:
        return Result('registries', 'error', 'a registry could not be loaded', str(e).split('\n'))
    errs = []
    for r in regs.values():
        errs += r.check(regs)
    n = sum(len(r.rows) for r in regs.values())
    return Result('registries', 'error' if errs else 'ok',
                  f'{len(errs)} registry problems' if errs else f'{len(regs)} registries, {n} rows, all valid and rendered', errs)


def gate_tools(ctx):
    """Every tool has a complete header (purpose, usage, when, verb or not-a-verb) and a registry row that matches it."""
    try:
        regs = load_all(ctx)
    except RegistryError as e:
        return Result('tools', 'error', 'registries could not be loaded', str(e).split('\n'))
    reg = regs.get('tools')
    if reg is None:
        return Result('tools', 'error', 'wsc.toml declares no `tools` registry (every repo has one)')
    errs, warns = tools.check(ctx, reg)
    n = len(tools.tool_files(ctx))
    if errs:
        return Result('tools', 'error', f'{len(errs)} tool problems', errs + warns)
    return Result('tools', 'warn' if warns else 'ok', f'{n} tools, each with a header and a matching row' + (f'; {len(warns)} retirement candidates' if warns else ''), warns)


def gate_json(ctx):
    files = [p for p in ctx.files() if p.endswith(('.json', '.jsonl'))]
    bad = []
    for p in files:
        t = _read(ctx, p)
        if t is None:
            continue
        e = checks.strict_json_error(t, jsonl=p.endswith('.jsonl'))
        if e:
            bad.append(f'{p}: {e[:160]}')
    return Result('json', 'error' if bad else 'ok', f'{len(bad)} of {len(files)} JSON files not strict' if bad else f'{len(files)} .json/.jsonl files parse strictly', bad)


def gate_windows_paths(ctx):
    errs = checks.windows_path_errors(ctx.files())
    return Result('windows_paths', 'error' if errs else 'ok', f'{len(errs)} paths Windows cannot create' if errs else f'{len(ctx.files())} paths Windows-safe', errs)


def _generated(ctx):
    d = ctx.config['registries_dir']
    return [f'{d}/{n}.md' for n in ctx.config['registries']]


def gate_doc_size(ctx):
    dc = ctx.config['docs']
    docs = checks.living_docs(ctx.files(), dc, _generated(ctx))
    over = checks.oversize({p: (ctx.root / p).stat().st_size for p in docs}, dc['max_kb'])
    det = [f'{p}: {n / 1024:.1f} KB (cap {dc["max_kb"]} KB): split it or move history to a dated record' for p, n in over]
    return Result('doc_size', 'error' if det else 'ok', f'{len(det)} living docs over {dc["max_kb"]} KB' if det else f'{len(docs)} living docs under {dc["max_kb"]} KB', det)


def gate_verified_dates(ctx):
    docs = checks.living_docs(ctx.files(), ctx.config['docs'], _generated(ctx))
    det = []
    for p in docs:
        t = _read(ctx, p)
        if t is not None:
            det += [f'{p}:{n}: "verified" with no date or run id' for n in checks.undated_verified(t.split('\n'))]
    return Result('verified_dates', 'error' if det else 'ok', f'{len(det)} undated "verified" claims' if det else f'{len(docs)} living docs: every "verified" carries a date or run id', det)


def gate_conflict_markers(ctx):
    bad = []
    for p in ctx.files():
        t = _read(ctx, p)
        if t is not None and '\0' not in t[:8000]:
            at = checks.has_conflict_trio(t)
            if at:
                bad.append(f'{p}:{at}')
    return Result('conflict_markers', 'error' if bad else 'ok', f'{len(bad)} files with a merge-conflict marker trio' if bad else 'no conflict markers', bad)


def gate_eol(ctx):
    det = checks.eol_problems(ctx.root)
    return Result('eol', 'warn' if det else 'ok', f'{len(det)} line-ending problems' if det else '.gitattributes present; no CR in indexed .py/.sh', det)


def gate_core_pin(ctx):
    want = ctx.config['core']['version']
    if ctx.is_core or not want:
        return Result('core_pin', 'ok', 'this is the core' if ctx.is_core else 'no [core] version pinned in wsc.toml (nothing to check)')
    have, det = core_version(), []
    if have != want.lstrip('v'):
        det.append(f'wsc.toml pins core {want} but the core checkout is {have}: update the submodule or the pin')
    try:
        dirty = subprocess.run(['git', '-C', str(ctx.core_root), 'status', '--porcelain'], capture_output=True, text=True, timeout=30).stdout.strip()
        if dirty:
            det.append('the core checkout has local changes (a game repo never patches the core in place: file the change against warscape-core)')
            det += ['  ' + l for l in dirty.splitlines()[:10]]
    except (OSError, subprocess.SubprocessError):
        pass
    return Result('core_pin', 'error' if det else 'ok', 'core pin broken' if det else f'core {have} as pinned, unmodified', det)


def gate_tests(ctx):
    tc = ctx.config['tests']
    dirs = [d for d in tc['dirs'] if (ctx.root / d).is_dir()]
    if not dirs:
        return Result('tests', 'ok', 'no test folders')
    det, total = [], 0
    for d in dirs:
        try:
            p = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', d, '-t', d, '-p', 'test_*.py'],
                               cwd=ctx.root, capture_output=True, text=True, timeout=tc['timeout_s'])
        except subprocess.TimeoutExpired:
            det.append(f'{d}: timed out after {tc["timeout_s"]} s')
            continue
        out = (p.stdout + p.stderr).strip().splitlines()
        ran = next((l for l in out if l.startswith('Ran ')), 'Ran ? tests')
        total += int(ran.split()[1]) if ran.split()[1].isdigit() else 0
        if p.returncode:
            det += [f'{d}: {ran}, FAILED'] + out[-40:]
    return Result('tests', 'error' if det else 'ok', 'host tests failed' if det else f'{total} host tests passed ({", ".join(dirs)})', det)


GATES = [
    ('schemas', gate_schemas), ('registries', gate_registries), ('tools', gate_tools), ('json', gate_json),
    ('windows_paths', gate_windows_paths), ('doc_size', gate_doc_size), ('verified_dates', gate_verified_dates),
    ('conflict_markers', gate_conflict_markers), ('eol', gate_eol), ('core_pin', gate_core_pin), ('tests', gate_tests),
]
NAMES = [n for n, _ in GATES]


def selected(ctx, fast=False, only=None):
    gc = ctx.config['gates']
    unknown = [n for n in (only or []) + gc['fast'] + gc['skip'] if n not in NAMES]
    if unknown:
        raise ValueError(f'unknown gate(s) {", ".join(unknown)}; gates are: {", ".join(NAMES)}')
    names = only or [n for n in NAMES if n not in gc['skip']]
    if fast and not only:
        names = [n for n in names if n in gc['fast']] if gc['fast'] else [n for n in names if n != 'tests']
    return names


def run(ctx, fast=False, only=None):
    out = []
    for name in selected(ctx, fast, only):
        t0 = time.time()
        try:
            r = dict(GATES)[name](ctx)
        except Exception as e:   # a crashing gate is a failed gate, never a pass
            r = Result(name, 'error', f'gate crashed: {type(e).__name__}: {e}')
        r.seconds = round(time.time() - t0, 2)
        out.append(r)
    return out
