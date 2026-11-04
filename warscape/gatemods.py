"""Game gate modules: the one way a game repo adds its own checks to the core (core W13, C22; backlog B1, B46). They replace the five
hook names of C18 (`[jobs] hooks`, removed with no shim).

A repo lists folders in `wsc.toml` `[gates] dirs`. Every `*.py` in a listed folder whose name does not start with `_` is a gate module,
loaded by path in folder order, then file-name order (the rule of `cli._load_verbs`). A listed folder that does not exist is a load error.
A module defines:

    NAME     str, [a-z][a-z0-9_]*: the gate's name; never a core gate's name (warscape/gates.py NAMES) nor another module's
    run(ctx) -> warscape.gates.Result (`from warscape.gates import Result`: the module runs inside the `wsc` process)
    STAGES   optional tuple, default ('gates',): where the core runs it, any of
               gates   `wsc gates`, as its own line after the core gates. `[gates] fast`, `skip` and `--only` take its NAME
               jobs    the `jobs` gate and `wsc jobs check`. ctx.rows (the main rows), ctx.read(path) (text or None), ctx.briefs()
                       ((jid, row, text) for each row whose brief exists, skipping the legacy file's `brief_hooks` ids). An `error`
                       Result's details are queue problems; a `warn` Result's details print without failing; a non-empty summary is
                       appended to the `jobs check` line
               policy  `wsc policy` only, never `wsc gates`, run from the base tree (core W23, C24): ctx.root and ctx.config are the
                       base's rule inputs in a temporary folder (not a repository) and ctx.files() lists them. ctx.facts: branch,
                       kind, jid, changed, merge_base, base and head (shas), base_ref, repo (the clone's absolute path: run git there; a
                       game's submodule is <repo>/<[ci] core>) and any extra facts the caller passes. Read the head as data with
                       `warscape.policy.show(sha, path, cwd=repo)`; never 'HEAD', never git in ctx.root, never import or run the
                       head's files. An `error` Result's details are policy errors
               view    `wsc jobs view`. ctx.rows. Drawn at the top of the page: the Result's `html` as is when it is not empty,
                       else its escaped summary and details as a muted paragraph (an empty Result draws nothing)
             An unknown stage is a load error: a typo must never switch a rule off silently.
    FAST     optional bool, default True: a `gates`-stage module is in the `--fast` set (or when `[gates] fast` names it)

`run` gets the repo context plus `ctx.stage` and that stage's inputs; one signature for every stage. A crash is an `error` Result (the rule
of `gates.run`); an `error` Result with no details counts as one problem, its summary. A module that still defines one of the five old
hook names at top level is a load error naming the migration (docs/CONSUMING.md "Game gates"). Gate modules in a game are tools like
any script: a header with `not-a-verb: a gate module, run by wsc gates` and a row in the game's `tools` registry.
"""
import importlib.util
import re
import sys
import time
from typing import Callable, NamedTuple

from .repo import ConfigError

STAGES = ('gates', 'jobs', 'policy', 'view')
OLD_HOOKS = ('brief_problems', 'queue_problems', 'policy_problems', 'view_panel', 'summary')
_CACHE = {}


class GateMod(NamedTuple):
    name: str
    stages: tuple
    fast: bool
    run: Callable
    path: str          # repo-relative


def _files(ctx):
    out = []
    for d in ctx.config['gates']['dirs']:
        folder = ctx.root / d
        if not folder.is_dir():
            raise ConfigError(f'wsc.toml [gates] dirs: {d} does not exist')
        out += [f for f in sorted(folder.glob('*.py')) if not f.name.startswith('_')]
    return out


def _exec(f):
    spec = importlib.util.spec_from_file_location(f'wsc_gate_{f.stem}', f)
    m = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # no __pycache__ in the repo being checked (`git add -A` would commit it)
    try:
        spec.loader.exec_module(m)
    finally:
        sys.dont_write_bytecode = keep
    return m


def load(ctx):
    """The repo's gate modules, in load order. Cached per repo root while no module file changes, so `jobs check` and the `jobs` gate
    do not load twice in one process. Raises ConfigError for every load error."""
    from .gates import NAMES as CORE
    files = _files(ctx)
    key = (str(ctx.root), tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files))
    if key in _CACHE:
        return _CACHE[key]
    mods, by = [], {}
    for f in files:
        rel = f.relative_to(ctx.root).as_posix()
        m = _exec(f)
        old = [n for n in OLD_HOOKS if n in vars(m)]
        if old:
            raise ConfigError(f'{rel} defines {", ".join(old)}: the hook names of [jobs] hooks were replaced by gate modules in core W13 (C22). '
                              'Rename or make them private and give the module NAME, STAGES and run(ctx) (docs/CONSUMING.md "Game gates", the migration steps)')
        for a in ('NAME', 'run'):
            if a not in vars(m):
                raise ConfigError(f'{rel}: a gate module needs {a} (NAME, run(ctx) -> Result; optional STAGES, FAST: warscape/gatemods.py)')
        name = m.NAME
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', name):
            raise ConfigError(f'{rel}: NAME {name!r} must match [a-z][a-z0-9_]*')
        if name in CORE:
            raise ConfigError(f'{rel}: NAME {name!r} is a core gate')
        if name in by:
            raise ConfigError(f"{rel}: NAME {name!r} is already {by[name]}'s")
        stages = getattr(m, 'STAGES', ('gates',))
        if isinstance(stages, str) or not isinstance(stages, (tuple, list)):
            raise ConfigError(f'{rel}: STAGES must be a tuple of stages ({", ".join(STAGES)})')
        bad = [s for s in stages if s not in STAGES]
        if bad:
            raise ConfigError(f'{rel}: unknown stage {bad[0]!r} (stages: {", ".join(STAGES)})')
        fast = getattr(m, 'FAST', True)
        if not isinstance(fast, bool):
            raise ConfigError(f'{rel}: FAST must be True or False')
        by[name] = rel
        mods.append(GateMod(name, tuple(stages), fast, m.run, rel))
    _CACHE[key] = mods
    return mods


def gate_names(ctx):
    """The names of the `gates`-stage modules: what `[gates] fast`, `skip` and `--only` accept beside the core gates."""
    return [m.name for m in load(ctx) if 'gates' in m.stages]


class StageCtx:
    """What `run` gets: every attribute of the repo Ctx, plus `stage` and the stage's inputs."""

    def __init__(self, ctx, stage, inputs):
        self._ctx = ctx
        self.stage = stage
        self.__dict__.update(inputs)

    def __getattr__(self, name):
        return getattr(self._ctx, name)


def call(mod, ctx):
    """One module's Result under the crash rule of `gates.run`, timed. A return that is not a Result of a known level is an error."""
    from .gates import Result
    t0 = time.time()
    try:
        r = mod.run(ctx)
        if not isinstance(r, Result) or r.level not in ('ok', 'warn', 'error'):
            r = Result(mod.name, 'error', f'gate returned {r!r:.80}, not a Result with level ok, warn or error')
    except Exception as e:   # a crashing gate is a failed gate, never a pass
        r = Result(mod.name, 'error', f'gate crashed: {type(e).__name__}: {e}')
    r.name = mod.name
    r.seconds = round(time.time() - t0, 2)
    return r


def run_stage(ctx, stage, **inputs):
    """The Results of every module that lists `stage`, in load order."""
    if stage not in STAGES:
        raise ValueError(f'unknown stage {stage!r}')
    return [call(m, StageCtx(ctx, stage, inputs)) for m in load(ctx) if stage in m.stages]


def problems(results, level='error'):
    """The details of the Results at `level`; an `error` Result without details counts as one problem, `<name>: <summary>`."""
    out = []
    for r in results:
        if r.level == level:
            out += list(r.details) or ([f'{r.name}: {r.summary}'] if level == 'error' else [])
    return out
