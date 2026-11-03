"""The gate runner behind `wsc gates`: deterministic, no network, standard library only.

Every gate returns a Result. Level `error` fails the run; `warn` never does. `--fast` runs every gate except `tests`
(or the list in `wsc.toml` [gates] fast), and is what the pre-push hook runs: well under a minute, no network.
"""
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import checks, core_version, tools
from .registry import RegistryError, load_all, load_schema
from .repo import git_env
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
        try:
            doc = load_schema(s, ctx.root)    # x-extends resolved: the merged document is the one checked
        except RegistryError as e:
            errs.append(str(e))
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


PIN = re.compile(r'v\d+\.\d+\.\d+')


def _git(cwd, *args):
    """stdout lines of a git command, or None when git cannot answer (no git, not a checkout)."""
    try:
        p = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, timeout=30, env=git_env())
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.split() if p.returncode == 0 else None


def pin_check(pin_commit, shallow, any_tags):
    """How a game's pin is checked against the core checkout (C10 as amended by core W11): `tag` when the pinned tag is in the checkout
    (its commit must be HEAD), `shallow` when it is not and the checkout is shallow (VERSION only: a depth-1 CI submodule brings the core
    tip's tag, not an older pinned one), `missing` when it is not in a full checkout that has other tags (an error: fetch the tags), `none`
    when the checkout has no tags at all (VERSION only)."""
    if pin_commit:
        return 'tag'
    if shallow:
        return 'shallow'
    return 'missing' if any_tags else 'none'


def pin_problems(want, version, pin_commit, head, shallow, any_tags, head_tags=(), core_dir='core'):
    """Problems with a game repo's core pin, from plain values. `want`: wsc.toml [core] version; `version`: the core checkout's VERSION;
    `pin_commit`: the commit of the tag named exactly `want` in the checkout, or None; `head`: HEAD's commit; `shallow`: the checkout is
    shallow; `any_tags`: it has any tag; `head_tags`: tag names on HEAD (for the message); `core_dir`: the checkout as the fix names it.
    Tags are `vX.Y.Z`, lower-case v, and case matters (backlog B5); `pin_check` says what is compared when."""
    det = []
    if not PIN.fullmatch(want):
        det.append(f'wsc.toml pins core {want!r}: a pin is a release tag `vX.Y.Z` (lower-case v)')
    if version != want[1:] if want[:1] == 'v' else version != want:
        det.append(f'wsc.toml pins core {want} but the core checkout is {version}: update the submodule or the pin')
    how = pin_check(pin_commit, shallow, any_tags)
    if how == 'tag' and pin_commit != head:
        on = f'tag(s) {", ".join(head_tags)}' if head_tags else 'an untagged commit'
        det.append(f'the core checkout is at {on}, not the pinned tag {want} (check out the tag; tags are case-sensitive)')
    elif how == 'missing':
        det.append(f'the pinned tag {want} is not in the core checkout, which has other tags: `git -C {core_dir} fetch --tags`, then check '
                   f'out {want} (tags are case-sensitive)')
    return det


def core_tag_problems(version, head_tags):
    """The core itself: VERSION is X.Y.Z and every tag on HEAD is exactly `v` + VERSION (CLAUDE.md: tags are vX.Y.Z)."""
    det = [] if re.fullmatch(r'\d+\.\d+\.\d+', version) else [f'VERSION {version!r} is not X.Y.Z']
    det += [f'tag {t!r} on HEAD is not v{version} (tags are `vX.Y.Z` with a lower-case v and match VERSION)'
            for t in head_tags if t != f'v{version}']
    return det


def gate_core_pin(ctx):
    want, have = ctx.config['core']['version'], core_version(ctx.core_root)   # the checkout being checked, not the running core (B7)
    if ctx.is_core:
        det = core_tag_problems(have, _git(ctx.root, 'tag', '--points-at', 'HEAD') or [])
        return Result('core_pin', 'error' if det else 'ok', 'core VERSION or tag malformed' if det else f'this is the core ({have})', det)
    if not want:
        return Result('core_pin', 'ok', 'no [core] version pinned in wsc.toml (nothing to check)')
    core = ctx.core_root
    tags = _git(core, 'tag', '--list') or []
    pin_commit = (_git(core, 'rev-parse', '-q', '--verify', f'refs/tags/{want}^{{commit}}') or [None])[0] if want in tags else None
    head = (_git(core, 'rev-parse', '-q', '--verify', 'HEAD') or [None])[0]
    shallow = (_git(core, 'rev-parse', '--is-shallow-repository') or [''])[0] == 'true'
    try:
        core_dir = Path(core).resolve().relative_to(Path(ctx.root).resolve()).as_posix()
    except ValueError:
        core_dir = str(core)
    det = pin_problems(want, have, pin_commit, head, shallow, bool(tags), _git(core, 'tag', '--points-at', 'HEAD') or [], core_dir)
    try:
        dirty = subprocess.run(['git', '-C', str(ctx.core_root), 'status', '--porcelain'], capture_output=True, text=True, timeout=30, env=git_env()).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        dirty = ''
    if dirty:
        det.append('the core checkout has local changes (a game repo never patches the core in place: file the change against warscape-core)')
        det += ['  ' + l for l in dirty.splitlines()[:10]]
    tagnote = {'tag': f'tag {want}', 'shallow': f'pinned tag {want} not in this shallow checkout: VERSION only',
               'none': 'VERSION only: no tags in this checkout'}.get(pin_check(pin_commit, shallow, bool(tags)), '')
    return Result('core_pin', 'error' if det else 'ok', 'core pin broken' if det else f'core {have} as pinned ({tagnote}), unmodified', det)


def gate_hooks(ctx):
    """The pre-push hook is wired in this clone (`git config core.hooksPath`); warning only, and skipped in CI."""
    import os
    if os.environ.get('CI'):
        return Result('hooks', 'ok', 'CI: no hook needed')
    want = '.githooks' if ctx.is_core else 'core/.githooks'
    have = (_git(ctx.root, 'config', '--get', 'core.hooksPath') or [''])[0]
    if have.replace('\\', '/').rstrip('/') == want:
        return Result('hooks', 'ok', f'pre-push hook wired ({want})')
    return Result('hooks', 'warn', f'pre-push hook not wired: run `git config core.hooksPath {want}` once in this clone',
                  [f'core.hooksPath is {have!r}, want {want!r}'])


def gate_jobs(ctx):
    """The job queue (`wsc jobs check`): rows against jobs/, brief shape, review rounds and the repo's own queue hooks. Skipped when the repo declares no jobs registry."""
    if 'jobs' not in ctx.config['registries']:
        return Result('jobs', 'ok', 'no jobs registry declared')
    from . import jobq
    jobq.configure(ctx)
    rows = jobq.main_rows(ctx)

    def read(p):
        f = ctx.root / p
        return f.read_text(encoding='utf-8') if f.is_file() else None

    jd = ctx.root / jobq.S.jobs_dir
    folders = [d.name for d in jd.iterdir() if d.is_dir()] if jd.is_dir() else []
    errs = jobq.problems(rows, read, folders, ctx) + jobq.call_hooks('queue_problems', ctx, rows, ctx.files())
    return Result('jobs', 'error' if errs else 'ok', f'{len(errs)} queue problems' if errs else f'{len(rows)} jobs rows, queue ok', errs)


def gate_ci_render(ctx):
    """Every workflow listed in `[ci] workflows` equals its render from `<template_dir>/<name>.in` (`wsc ci render`). Skipped when none are listed."""
    if not ctx.config['ci']['workflows']:
        return Result('ci_render', 'ok', 'no rendered workflows')
    from . import ci_render
    errs = ci_render.problems(ctx)
    return Result('ci_render', 'error' if errs else 'ok', f'{len(errs)} workflows differ from their render' if errs else
                  f"{len(ctx.config['ci']['workflows'])} workflows match their render", errs)


SKIPPED = re.compile(r"^(.*?) \.\.\. skipped '(.*)'$")
TEST_ID = re.compile(r'^(\S+) \(([\w.]+?)(?:\.\1)?\)$')   # `test_x (mod.Class.test_x)` (3.11+) or `test_x (mod.Class)`


def unittest_skips(lines):
    """`<Class.test>: <reason>` for each test `unittest -v` reports as skipped (a skip is visible, never a silent pass). A test with a
    docstring prints its id on the line before `<docstring> ... skipped`."""
    out = []
    for i, line in enumerate(lines):
        m = SKIPPED.match(line)
        if not m:
            continue
        t = TEST_ID.match(m.group(1)) or (TEST_ID.match(lines[i - 1]) if i else None)
        out.append(f'{t.group(2).rsplit(".", 1)[-1]}.{t.group(1)}: {m.group(2)}' if t else f'{m.group(1)}: {m.group(2)}')
    return out


def gate_tests(ctx):
    tc = ctx.config['tests']
    dirs = [d for d in tc['dirs'] if (ctx.root / d).is_dir()]
    if not dirs:
        return Result('tests', 'ok', 'no test folders')
    det, skips, total = [], [], 0
    for d in dirs:
        try:
            p = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-v', '-s', d, '-t', d, '-p', 'test_*.py'],
                               cwd=ctx.root, capture_output=True, text=True, timeout=tc['timeout_s'])
        except subprocess.TimeoutExpired:
            det.append(f'{d}: timed out after {tc["timeout_s"]} s')
            continue
        out = (p.stdout + p.stderr).strip().splitlines()
        ran = next((l for l in out if l.startswith('Ran ')), 'Ran ? tests')
        total += int(ran.split()[1]) if ran.split()[1].isdigit() else 0
        skips += [f'{d}: skipped {s}' for s in unittest_skips(out)]
        if p.returncode:
            det += [f'{d}: {ran}, FAILED'] + out[-40:]
    if det:
        return Result('tests', 'error', 'host tests failed', det + skips)
    msg = f'{total} host tests passed ({", ".join(dirs)})'
    # a skip is a warn, never an error: the run still passes, but what did not run is on screen with its reason
    return Result('tests', 'warn', f'{msg}; {len(skips)} skipped', skips) if skips else Result('tests', 'ok', msg)


GATES = [
    ('schemas', gate_schemas), ('registries', gate_registries), ('tools', gate_tools), ('json', gate_json),
    ('windows_paths', gate_windows_paths), ('doc_size', gate_doc_size), ('verified_dates', gate_verified_dates),
    ('conflict_markers', gate_conflict_markers), ('eol', gate_eol), ('core_pin', gate_core_pin), ('hooks', gate_hooks),
    ('jobs', gate_jobs), ('ci_render', gate_ci_render), ('tests', gate_tests),
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
