"""The gate runner behind `wsc gates`: deterministic, no network, standard library only.

Every gate returns a Result. Level `error` fails the run; `warn` never does. `--fast` runs every gate except `tests`
(or the list in `wsc.toml` [gates] fast), and is what the pre-push hook runs: well under a minute, no network.
A game's own gates (`[gates] dirs`, warscape/gatemods.py) run after the core gates, each as its own line.
"""
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import checks, core_version, tools
from .registry import RegistryError, id_to_file, load_all, load_schema
from .repo import decisions_registry, git_env
from .schema import check_schema


@dataclass
class Result:
    name: str
    level: str          # ok | warn | error
    summary: str
    details: list = field(default_factory=list)
    seconds: float = 0.0
    html: str = ''      # a `view`-stage game gate's HTML for the status page, drawn as is (warscape/gatemods.py); every other reader ignores it
    cards: dict = field(default_factory=dict)   # W31, same stage: {job id: text (escaped) or {'html': drawn as is}}, one line on that job's card


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
    retired, dreg = ctx.config['policy']['decisions_retired'], decisions_registry(ctx.config)
    if retired and dreg in regs and (text := _read(ctx, retired)) is not None:   # W43: a stale branch's Markdown row fails here, never vanishes
        errs += regs[dreg].md_problems(text, retired)
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


def _vt(v):
    return tuple(int(x) for x in v.split('.'))


def release_tag_problem(version, on_main, tags, tag_type, age_min, annotated_from, grace_min):
    """(level, why) for the core on main (W29, C27): v<VERSION> exists, annotated from `annotated_from` on; missing is a warning for
    `grace_min` minutes after the commit (the release workflow is pending), then an error. A checkout with no tags is VERSION only (C21)."""
    if not on_main:
        return 'ok', ''
    if not tags:
        return 'ok', 'VERSION only: no tags in this checkout'
    tag = f'v{version}'
    if tag not in tags:
        if age_min is not None and age_min > grace_min:
            return 'error', (f'{tag} does not exist {int(age_min)} min after main reached VERSION {version}: the release workflow did not tag '
                             '(read its last run: `gh run list --workflow release.yml`; docs/CONSUMING.md, Releases)')
        return 'warn', f'{tag} does not exist yet: release workflow pending'
    if annotated_from and _vt(version) >= _vt(annotated_from) and tag_type != 'tag':
        return 'error', f'{tag} is a lightweight tag: from {annotated_from} on the release workflow makes annotated tags (C27); nobody tags by hand'
    return 'ok', f'tag {tag}' + (' (annotated)' if tag_type == 'tag' else '')


def core_release_tag(ctx, version):
    import os
    on_main = os.environ.get('GITHUB_REF') == 'refs/heads/main'
    if not on_main and _git(ctx.root, 'rev-parse', '-q', '--verify', 'refs/remotes/origin/main'):
        on_main = subprocess.run(['git', '-C', str(ctx.root), 'merge-base', '--is-ancestor', 'HEAD', 'refs/remotes/origin/main'],
                                 capture_output=True, timeout=30, env=git_env()).returncode == 0
    tags = _git(ctx.root, 'tag', '--list', 'v*') or []
    tag_type = (_git(ctx.root, 'cat-file', '-t', f'refs/tags/v{version}') or [''])[0] if f'v{version}' in tags else ''
    ct = (_git(ctx.root, 'log', '-1', '--format=%ct', 'HEAD', '--', 'VERSION') or [''])[0]
    age = (time.time() - int(ct)) / 60 if ct.isdigit() else None
    rel = ctx.config.get('release') or {}
    return release_tag_problem(version, on_main, tags, tag_type, age, rel.get('annotated_from', ''), rel.get('grace_minutes', 120))


def gate_core_pin(ctx):
    want, have = ctx.config['core']['version'], core_version(ctx.core_root)   # the checkout being checked, not the running core (B7)
    if ctx.is_core:
        det = core_tag_problems(have, _git(ctx.root, 'tag', '--points-at', 'HEAD') or [])
        if det:
            return Result('core_pin', 'error', 'core VERSION or tag malformed', det)
        level, why = core_release_tag(ctx, have)
        return Result('core_pin', level, why if level != 'ok' else f'this is the core ({have}{"; " + why if why else ""})', [why] if level != 'ok' else [])
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
    """The job queue (`wsc jobs check`): rows against jobs/, brief shape, review rounds and the repo's `jobs`-stage gate modules. Skipped when the repo declares no jobs registry."""
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
    errs, warns, _ = jobq.check(ctx, rows, read, folders)
    if errs:
        return Result('jobs', 'error', f'{len(errs)} queue problems', errs + warns)
    return Result('jobs', 'warn' if warns else 'ok', f'{len(rows)} jobs rows, queue ok' + (f'; {len(warns)} warnings' if warns else ''), warns)


def _tracked(ctx):
    """Tracked repo paths, submodule files included (`git ls-files --cached --recurse-submodules`), and the submodule folders. Untracked files do not count:
    a path a run README names must be committed."""
    try:
        out = subprocess.run(['git', '-C', str(ctx.root), 'ls-files', '-z', '--cached', '--recurse-submodules'], env=git_env(), capture_output=True,
                             check=True).stdout.decode('utf-8', 'replace')
        subs = subprocess.run(['git', '-C', str(ctx.root), 'ls-files', '-s'], env=git_env(), capture_output=True, check=True).stdout.decode('utf-8', 'replace')
    except (OSError, subprocess.CalledProcessError):
        return list(ctx.files()), []
    return [p for p in out.split('\0') if p], [l.split('\t', 1)[1] for l in subs.splitlines() if l.startswith('160000') and '\t' in l]


def gate_run_refs(ctx):
    """Every repo path a tracked `**/runs/**/README.md` names exists (B13): a link target or a backticked path (`warscape/checks.py` run_ref_tokens). Found
    from the root, from the README's folder, as the tail of any tracked path, in a submodule, or git-ignored on purpose. `[gates] run_refs_since` skips older run folders."""
    tracked, subs = _tracked(ctx)
    readmes = {p: t for p in checks.run_readmes(tracked) if (t := _read(ctx, p)) is not None}
    if not readmes:
        return Result('run_refs', 'ok', 'no run READMEs')
    index = checks.run_ref_index(tracked)
    cache = {}

    def ignored(path):
        if any(path == s or path.startswith(s + '/') for s in subs):
            return (ctx.root / path).exists()   # git check-ignore refuses a path inside a submodule: the file on disk is the proof
        if path not in cache:
            cache[path] = subprocess.run(['git', '-C', str(ctx.root), 'check-ignore', '-q', '--', path], env=git_env(), capture_output=True).returncode == 0
        return cache[path]
    since = ctx.config['gates']['run_refs_since']
    errs, checked, skipped = checks.run_ref_problems(readmes, index, since, ignored)
    tail = f'{len(readmes) - skipped} run READMEs, {checked} references' + (f'; {skipped} before {since} skipped' if skipped else '')
    return Result('run_refs', 'error' if errs else 'ok', f'{len(errs)} run README references not found ({tail})' if errs else f'every run README reference exists ({tail})', errs)


def gate_doc_paths(ctx):
    """Every backticked repo path in a living doc exists (W28, R11; `warscape/checks.py` stale_doc_paths): a tracked file or a folder above one, from
    the root, the doc's folder or across the `core/` boundary, or git-ignored on purpose. Not checked: the job folders at any depth (a fixture game's
    too) and the decisions file (records of their day; the decisions file is append only), fenced blocks, a line with `(was <path>)` or `(moved)`, a
    `../` path, and `[docs] path_ignore`. An error (Liam, plan PR #87): a doc that names another repo's paths on purpose lists them in
    `[docs] path_ignore`, prefix globs (`rml_mod/**`) where it can."""
    tracked, subs = _tracked(ctx)
    paths = checks.run_ref_index(tracked)[0]
    skip = {ctx.config['policy']['decisions'], ctx.config['policy']['decisions_retired']}
    jdir = ctx.config['jobs']['dir'].rstrip('/') + '/'
    docs = {p: t for p in checks.living_docs(ctx.files(), ctx.config['docs'], _generated(ctx))
            if p not in skip and not p.startswith(jdir) and f'/{jdir}' not in p and (t := _read(ctx, p)) is not None}
    errs = checks.stale_doc_paths(docs, paths, ctx.config['docs']['path_ignore'])
    tok = lambda e: e.rsplit(': ', 1)[1].rstrip('/')
    errs = [e for e in errs if tok(e) != '..' and not tok(e).startswith('../')]   # outside the repo: one such name makes git check-ignore exit 128 for the whole batch
    toks = sorted({tok(e) for e in errs})
    try:   # one git call for every miss: build output and _scratch/ are git-ignored on purpose
        p = subprocess.run(['git', '-C', str(ctx.root), 'check-ignore', '--stdin', '-z'], input='\0'.join(toks).encode('utf-8') + b'\0', env=git_env(),
                           capture_output=True) if toks else None   # bytes, NUL-separated: text mode on Windows would send each name with a CR
    except OSError as e:
        return Result('doc_paths', 'error', f'git check-ignore could not run: {e}')
    if p is not None and p.returncode not in (0, 1):   # 0: some ignored, 1: none; anything else is a failure, never "nothing is ignored" (W28 review 1)
        return Result('doc_paths', 'error', f'git check-ignore exited {p.returncode}: {p.stderr.decode("utf-8", "replace").strip()[:300]}')
    ignored = set(p.stdout.decode('utf-8', 'replace').split('\0')) if p is not None else set()
    errs = [e for e in errs if tok(e) not in ignored]
    return Result('doc_paths', 'error' if errs else 'ok', f'{len(errs)} backticked paths in living docs not found ({len(docs)} docs)' if errs
                  else f'{len(docs)} living docs: every backticked path exists', errs)


def gate_ci_render(ctx):
    """Every workflow listed in `[ci] workflows` equals its render from `<template_dir>/<name>.in` (`wsc ci render`). Skipped when none are listed."""
    if not ctx.config['ci']['workflows']:
        return Result('ci_render', 'ok', 'no rendered workflows')
    from . import ci_render
    errs = ci_render.problems(ctx)
    if errs:
        return Result('ci_render', 'error', f'{len(errs)} workflow problems (render or guard)', errs)
    warns = ci_render.guards(ctx)[1]   # W23: a bootstrap pull_request trigger left beside pull_request_target
    return Result('ci_render', 'warn' if warns else 'ok', f"{len(ctx.config['ci']['workflows'])} workflows match their render"
                  + (f'; {len(warns)} warnings' if warns else ''), warns)


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
    ('windows_paths', gate_windows_paths), ('doc_size', gate_doc_size), ('verified_dates', gate_verified_dates), ('doc_paths', gate_doc_paths),
    ('conflict_markers', gate_conflict_markers), ('eol', gate_eol), ('core_pin', gate_core_pin), ('hooks', gate_hooks),
    ('jobs', gate_jobs), ('ci_render', gate_ci_render), ('run_refs', gate_run_refs), ('tests', gate_tests),
]
NAMES = [n for n, _ in GATES]


def skips(ctx):
    """`{gate: decision id}` from `[gates] skip` (W28): each entry is `"<gate>:<decision id>"`, and the id is a row of the `[policy] decisions`
    file, so a skip is never silent and always says why. A bare name, an empty id or an id the file lacks is a ValueError that names the fix."""
    entries, out, errs = ctx.config['gates']['skip'], {}, []
    path, dreg = ctx.config['policy']['decisions'], decisions_registry(ctx.config)
    text = _read(ctx, path) if path and not dreg else None
    folder = ctx.root / ctx.config['registries_dir'] / dreg
    for e in entries:
        gate, _, did = str(e).partition(':')
        gate, did = gate.strip(), did.strip()
        if not did:
            errs.append(f'"{e}" has no decision id: write "{gate}:<decision id>", the {path or "[policy] decisions"} row that says why it is skipped')
        elif dreg:
            if (folder / id_to_file(did)).is_file():
                out[gate] = did
            else:
                errs.append(f'"{e}": {did} is not a row of {path} (add the decision first, then skip under its id)')
        elif text is None:
            errs.append(f'"{e}": no decisions file to find {did} in (set [policy] decisions in wsc.toml)' if not path else f'"{e}": {path} is missing')
        elif not re.search(rf'^\|\s*{re.escape(did)}\s*\|', text, re.M):
            errs.append(f'"{e}": {did} is not a row of {path} (add the decision first, then skip under its id)')
        else:
            out[gate] = did
    if errs:
        raise ValueError('[gates] skip: ' + '; '.join(errs))
    return out


def selected(ctx, fast=False, only=None, skipped=None):
    """The gate names to run, core gates first, then the repo's `gates`-stage modules in load order. `--fast`: the core gates of
    `[gates] fast` (default: all but `tests`) plus every game gate whose FAST is true or that `[gates] fast` names. `[gates] skip`
    (`skips`) drops a gate unless `--only` names it; `skipped`, a list, gets `(gate, decision id)` for each gate the skip dropped."""
    from . import gatemods
    gc = ctx.config['gates']
    mods = {m.name: m for m in gatemods.load(ctx) if 'gates' in m.stages}
    every = NAMES + list(mods)
    skip = skips(ctx)
    unknown = [n for n in (only or []) + gc['fast'] + list(skip) if n not in every]
    if unknown:
        raise ValueError(f'unknown gate(s) {", ".join(unknown)}; gates are: {", ".join(every)}')
    names = only or list(every)
    if fast and not only:
        core_fast = (lambda n: n in gc['fast']) if gc['fast'] else (lambda n: n != 'tests')
        names = [n for n in names if ((mods[n].fast or n in gc['fast']) if n in mods else core_fast(n))]
    if not only:
        if skipped is not None:
            skipped += [(n, skip[n]) for n in names if n in skip]
        names = [n for n in names if n not in skip]
    return names


def run(ctx, fast=False, only=None):
    from . import gatemods
    mods = {m.name: m for m in gatemods.load(ctx)}
    out, skipped = [], []
    names = selected(ctx, fast, only, skipped)
    # a skip is a warn line, never silent (W28): the gate, and the decision that skips it
    out += [Result(n, 'warn', f'skipped {n}: {did}') for n, did in skipped]
    for name in names:
        if name in mods:
            out.append(gatemods.call(mods[name], gatemods.StageCtx(ctx, 'gates', {})))
            continue
        t0 = time.time()
        try:
            r = dict(GATES)[name](ctx)
        except Exception as e:   # a crashing gate is a failed gate, never a pass
            r = Result(name, 'error', f'gate crashed: {type(e).__name__}: {e}')
        r.seconds = round(time.time() - t0, 2)
        out.append(r)
    return out
