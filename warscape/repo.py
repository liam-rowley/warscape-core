"""Repo context: find the repo root, load `wsc.toml`, list files, match globs.

`wsc.toml` is the one file a repo (the core itself or a game) writes to declare its registries and gate settings.
Every value has a default here, so a minimal game config is just its `[registries]` table.
"""
import copy
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import CORE_ROOT

CONFIG_NAME = 'wsc.toml'

DEFAULTS = {
    'registries_dir': 'registries',
    'registries': {},                      # name = "core:<schema>" or a repo-relative schema path
    # how rows are stored (napoleon J55): names listed in `dir` keep one file per row in <registries_dir>/<name>/; the rest one JSONL
    'storage': {'dir': []},
    # generated Markdown views (napoleon J55): commit = true keeps <registries_dir>/<name>.md committed and checked for staleness;
    # false writes them to the git-ignored `dir` and only checks that they render (a committed copy is then an error)
    'views': {'commit': True, 'dir': '_scratch/registries'},
    'tools': {
        'extensions': ['py', 'sh', 'ps1', 'cmd', 'bat', 'lua', 'js', 'vbs'],
        'include': [],                     # extra globs for extensionless tools (git hooks, launchers)
        'library': [],                     # importable library code: no header or row needed
        'exempt': [],                      # history, generated files, tests
        'retire_after_days': 0,            # warn for live tools whose last_used is older; 0 (default) disables. Off until
                                           # something stamps last_used automatically (the job queue), or every tool warns at once
    },
    'docs': {
        'max_kb': 30,                      # living-doc size cap in KiB (1024 bytes)
        'living': ['**/*.md'],
        'records': ['**/records/**', '**/reports/**', '**/runs/**'],   # plus any file whose name carries a YYYY-MM-DD date
        'exempt': [],
        'path_ignore': [],                 # doc_paths gate (W28): backticked tokens (exact, or globs) that look like a path but are not one of this repo's
    },
    'tests': {'dirs': ['tests'], 'timeout_s': 600},
    # wsc agent-settings (W35, C35): the Claude Code command rules an agent may add to .claude/settings.json without asking, e.g.
    # "Bash(git status:*)"; a rule is added only when one of these covers it (itself, or extended by whole words without a write flag).
    # Empty (the default) = the verb is not configured. exact_only = true: only the patterns themselves.
    'agent_settings': {'safe': [], 'exact_only': False},
    'gates': {'fast': [], 'skip': [],      # fast: empty = every gate except `tests`; skip: "<gate>:<decision id>" (a [policy] decisions row; W28)
              'dirs': [],                  # repo-relative folders of game gate modules (warscape/gatemods.py)
              'run_refs_since': ''},       # YYYY-MM-DD: the `run_refs` gate skips run folders dated before it ('' = checks every run README; C23)
    'cli': {'verb_dirs': []},              # repo-relative folders of extra verb modules
    'core': {'version': ''},               # the core version this repo pins (checked by the core_pin gate)
    # where a game's adapters are, for the proxy and harness tools (proxy/tools/layout.py, napoleon J12); empty = the one
    # proxy/*/adapter.cpp folder / the one harness/*/adapter.json in the repo
    'proxy': {'adapter': '',               # repo-relative folder: adapter.cpp, identity.json, generated/, the config file, lua/
              'ui_pins': '',               # repo-relative pin file of the RmlUi host's sources (empty: viewer/pins.json; J30)
              'tests': ''},                # repo-relative folder of the game's own C++ host tests (empty: proxy/tests when it holds a test_*.cpp; W16)
    'harness': {'adapter': ''},            # repo-relative file: the watcher's adapter.json (its profiles/ beside it)
    # the discovery passes (discovery/, `wsc discovery`; napoleon J64): empty = the one discovery/*/games.json folder in the repo
    'discovery': {'adapter': ''},          # repo-relative folder: games.json (target, reference, install paths) and the rules the tools read
    # the job queue (napoleon J62; library: warscape/jobq.py; a game's own rules: gate modules, [gates] dirs). The defaults are a plain queue: ids J<n>,
    # sonnet|opus, no game rules, no references in the step texts.
    'jobs': {
        'id_prefix': 'J',                  # job ids are <prefix><n>; branches job/<id>, brief/<id>
        'dir': 'jobs',                     # jobs/<id>/brief.md, report.md, review.md
        'models': ['sonnet', 'opus'],      # the Model line of a brief; the first is the default, the others need a stated reason
        'legacy': '',                      # repo-relative JSON {"round_rules": [ids], "brief_hooks": [ids]}: jobs frozen before a rule existed
        'failed_results': '',              # glob (relative to a run folder a report cites) of ctl result JSONs: one with status "failed" must be named in ## Deviations ('' = off)
        'ledgers': '',                     # glob of audit ledgers whose `CL` rows name a job the brief must cover ('' = off)
        'pc_state': '',                    # the PC state folder ($VAR, ~ expanded): a needs_pc build is not ready where it is absent ('' = no gating; WSC_PC_STATE overrides, "" = no PC here; W26)
        'semver_from': 0,                  # W29 (C27): job numbers from this one on carry `semver` (from status queued) and a `Semver:` brief line,
                                           # and their job/ branches may not edit VERSION (the release workflow owns it); 0 = off
        'usage_from': 0,                   # W31: job numbers from this one on need a `Usage:` line in report.md, within 1.25 x the budget, with the row's model; 0 = off
        'usage_cmd': '',                   # W31: argv template ({id}; no shell) of the game's usage reader for `wsc jobs usage`: prints {"calls", "models", "sessions", "note"}
        'claim_hours': 4,                  # a review claim (refs/claims/<id>/round-<n>, core W27) older than this may be taken over
        'max_sessions': 0,                 # W41: no launch at this many background sessions with a process (`claude agents --json --all`); 0 = no cap
        'text': {                          # every repo-specific string in the step texts and messages
            'wsc': 'python3 core/wsc.py',  # the command prefix ('python3 wsc.py' inside the core itself)
            'policy': '{wsc} policy',      # the policy command, before ` --branch B --base REF`
            'plan_doc': 'docs/PLAN.md', 'review_doc': 'docs/REVIEW.md', 'ci_failures_doc': '', 'owner': 'the owner',
            'rules_ref': '', 'trailer_hint': '', 'plan_summary': '',
            'ref_models': '', 'ref_rounds': '', 'ref_merge': '', 'ref_brief_merge': '', 'ref_ready': '',
            'brief_model': '', 'brief_notes': '',
        },
    },
    # the pull-request policy (`wsc policy`; warscape/policy.py)
    'policy': {
        'decisions': '',                   # repo-relative append-only decisions file, or "registry:<name>", one file per row (core W43); '' = not checked
        'decisions_retired': '',           # the Markdown file a repo moved off: while it exists, the `registries` gate holds its rows to the row files and `policy` refuses a change to its table (core W43)
        'decision_prefix': 'D',            # its row ids: | D<n> | date | who | decision | yes/no |
        'session_trailer': 'Claude-Session',   # the commit trailer that names a session; '' switches the own-review rule off
        'commit_msg_hook': False,          # .githooks/commit-msg refuses a commit with no non-empty `session_trailer` trailer (C23); opt-in per repo
        'decisions_cite_job': False,       # a decisions row added on job/<id> must contain <id>, the brief that required it (core W27 rule F)
        'reviewer_code': 'warn',           # rule A (core W27, W40): reviewer code under a `merge` verdict warns, or with "error" refuses
        'workflow_paths': ['.github/workflows/**', 'ci/**'],   # a job's change to one of these that its brief on the base does not name warns (core W36); [] = off
        'bases': ['main'],                 # the branches a pull request may target, as origin/<name>; [] = any (core W36)
        'thin_merge_lines': 500,           # a `merge` on more changed lines than this outside jobs/ and the registries...
        'thin_merge_files': 20,            # ...or more files, whose newest round cites no evidence, is a warning (core W27 rule E)
        'plan': ['docs/*', 'docs/**', 'jobs/*/brief.md', 'registries/jobs/*', 'registries/proposals/*', 'README.md', 'CLAUDE.md'],     # what a plan/* branch may touch
        'meta': ['docs/*', 'docs/**', 'jobs/*/brief.md', 'registries/jobs/*', 'README.md', 'CLAUDE.md', '.github/**', 'tests/*',
                 'tests/**', 'wsc.toml', '.gitattributes', '.gitignore', '.gitmodules', 'registries/*'],   # what a meta/* branch may touch
        # Exact branch names exempt from the branch-kind rules (the decisions check and the repo's policy hooks still run). Only for the one pull
        # request that introduces the pipeline into a repo: it cannot be a job (no brief on the base, no independent review yet) and its files are
        # wider than any meta/ list. Remove the entry in the next change; an exemption that outlives its branch is inert but is a smell.
        'bootstrap': [],
    },
    # release tags by workflow (W29, C27; `wsc release`, warscape/release.py, ci/release.yml.in); used inside the core
    'release': {
        'consumers': [],                   # [{name, repo = "owner/name", adapter = "<repo-relative proxy adapter folder>", ref = "main"}]: compiled before a tag
        'consumer_check': 'warn',          # warn: a failing consumer is in the tag message and an issue; block: no tag while one fails
        'annotated_from': '',              # X.Y.Z: from this version on `core_pin` wants v<VERSION> to be an annotated tag ('' = any tag)
        'grace_minutes': 120,              # a missing v<VERSION> on main is a warning this long after the commit, then an error
    },
    # CI helpers (`wsc ci`; warscape/ci.py)
    'ci': {
        'inputs': {},                      # set name -> regex of the paths that make that slow job run (`wsc ci inputs`)
        'salt': '1',                       # bump to invalidate every CI pass marker
        'hints': {},                       # failed job name (or "job~step substring|substring") -> what `wsc ci notify` tells
        'artifacts': {},                   # set name -> workflow artifact of its build, named when its job is skipped
        'notice': 'A failed check leaves this pull request open; fix it on the branch and push.',
        'footer': '',                      # last line of the failure comment
        'core': 'core',                    # the core's submodule folder in this repo ('' inside the core itself)
        'token_secret': '',                # secret passed to checkout steps as `token:` ('' = none)
        'workflows': [],                   # workflow file names rendered from <template_dir>/<name>.in (`wsc ci render`, gate `ci_render`)
        'template_dir': 'ci',
        'policy_extra_steps': '',          # YAML steps inserted before the policy command in the rendered `policy` job
        'required_checks': [],             # checks main must require (`wsc ci check-settings`); [] = the workflows' job ids but changes, notify
    },
    # the pipeline measured (`wsc audit`, W44, C41; warscape/audit.py; each rule in docs/AUDIT_METRICS.md)
    'audit': {
        'dir': 'docs/audits',              # where --record writes AUDIT_<date>.json and .md
        'window_days': 7,                  # the default window: the last this many days
        'window_jobs': 20,                 # work_mix reads this many last merged jobs
        'hot_exempt': [],                  # hot_files: globs that do not count, beside the job folders and rows
        'hot_file_share': 0.25,            # hot_file: at least this share of the window's job merges...
        'hot_file_min': 5,                 # ...and at least this many of them
        'hot_file_high': 0.5,              # hot_file is high from this share
        'both_sides_min': 3,               # conflict_file: changed on both sides of at least this many branch merges
        'max_job_hours': 24,               # long_job: over this from the oldest commit to the merge
        'max_job_files': 60,               # wide_job: over this many files in the squash commit
        'branch_exposure_share': 0.5,      # branch_exposure: at least this share of jobs merged main into their branch
        'overhead_phases': [],             # work_mix: the phases that are pipeline work; [] = overhead_share is off
        'max_overhead_share': 0.4,         # overhead_share: over this share of the last window_jobs
        'pc_serial_min': 4,                # pc_serial: at least this many ready rows...
        'pc_serial_share': 0.75,           # ...at least this share of them needs_pc
        'chokepoint_fanout': 4,            # chokepoint: at least this many not-done rows wait on the row, directly or not
        'min_round1_merge': 0.5,           # review_churn: under this share of done jobs merged in round 1
        'max_brief_ratio': 1.5,            # brief_heavy: the median brief over this many median reports
        'startup_docs': [],                # startup_read: read at the start of a session, beside CLAUDE.md and README.md
        'max_startup_kb': 40,              # startup_heavy: over this many KiB
        'doc_cap_share': 0.9,              # doc_cap: a living doc at this share of [docs] max_kb or more
        'max_pin_lag': 5,                  # pin_lag: at least this many minor versions behind the newest core tag
        'slowdown_ratio': 0.5,             # slowdown: under this ratio of merges a day to the window before
        'ci_runs': 20,                     # ci_durations: this many last runs on main, per workflow
        'ci_check_default': 10,            # slow_check: a median over this many minutes, for a check not in ci_check_minutes
        'ci_check_minutes': {},            # check name -> its own limit (stays empty here: _merge refuses keys a non-empty default table lacks)
        'auto_apply': [],                  # proposal classes accepted at their recommendation with no question (C41); a tagged proposal never is
        'reraise_margin': 0.25,            # a declined finding returns, and an applied one has moved, past this share of its baseline
        'max_questions': 8,                # wsc proposals ask: at most this many rows
    },
}


# Variables git exports to hooks (GIT_DIR in a worktree, GIT_INDEX_FILE, ...). Inherited by `git -C <other repo>`, they make it
# read the wrong repository: a pre-push hook in a worktree saw the game repo's index as "local changes" in core/ (napoleon J5).
GIT_LOCAL_VARS = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
                  'GIT_COMMON_DIR', 'GIT_PREFIX', 'GIT_NAMESPACE')


def git_env():
    """The environment for every git subprocess the core runs: os.environ without the repository-selecting GIT_* variables."""
    return {k: v for k, v in os.environ.items() if k not in GIT_LOCAL_VARS}


class ConfigError(Exception):
    pass


# Keys removed from wsc.toml, with what replaced them: a message written for the key, not the generic "unknown key".
REMOVED = {
    ('jobs', 'hooks'): '[jobs] hooks was replaced by [gates] dirs in 0.20.0 (C22): move each hook into a gate module; docs/CONSUMING.md "Game gates"',
}


def _merge(base, over, where=''):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k not in base:
            raise ConfigError(f"{CONFIG_NAME}: unknown key '{where}{k}'")
        if isinstance(base[k], dict) and base[k] and not isinstance(v, dict):
            raise ConfigError(f'{CONFIG_NAME}: {where}{k} must be a table')
        if isinstance(base[k], dict) and base[k]:
            out[k] = _merge(base[k], v, f'{where}{k}.')
        else:
            out[k] = v
    return out


def find_root(start=None):
    p = Path(start or os.getcwd()).resolve()
    for d in (p, *p.parents):
        if (d / CONFIG_NAME).is_file():
            return d
    raise ConfigError(f'no {CONFIG_NAME} found in {p} or any parent (run from a repo that declares its registries, or pass --root)')


def decisions_registry(cfg):
    """The registry `[policy] decisions` names (`registry:<name>`, core W43), or '' for a Markdown path or none."""
    v = cfg['policy']['decisions']
    return v[len('registry:'):] if v.startswith('registry:') else ''


def load_config(root):
    path = Path(root) / CONFIG_NAME
    try:
        with open(path, 'rb') as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f'{path}: {e}') from None
    for (table, key), why in REMOVED.items():
        if isinstance(raw.get(table), dict) and key in raw[table]:
            raise ConfigError(f'{CONFIG_NAME}: {why}')
    cfg = _merge(DEFAULTS, raw)
    for name, spec in cfg['registries'].items():
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
            raise ConfigError(f'{CONFIG_NAME}: registry name {name!r} must match [a-z][a-z0-9_]*')
        if not isinstance(spec, str):
            raise ConfigError(f'{CONFIG_NAME}: registries.{name} must be a string ("core:<name>" or a schema path)')
    bad = [n for n in cfg['storage']['dir'] if n not in cfg['registries']]
    if not isinstance(cfg['storage']['dir'], list) or bad:
        raise ConfigError(f'{CONFIG_NAME}: storage.dir must list declared registries; not declared: {", ".join(map(str, bad))}')
    if not isinstance(cfg['gates']['dirs'], list) or not all(isinstance(d, str) and d for d in cfg['gates']['dirs']):
        raise ConfigError(f'{CONFIG_NAME}: gates.dirs must list repo-relative folders of gate modules')
    since = cfg['gates']['run_refs_since']
    if not isinstance(since, str) or (since and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', since)):
        raise ConfigError(f'{CONFIG_NAME}: gates.run_refs_since must be "" or a date YYYY-MM-DD')
    if not isinstance(cfg['policy']['commit_msg_hook'], bool):
        raise ConfigError(f'{CONFIG_NAME}: policy.commit_msg_hook must be true or false')
    rel, sf = cfg['release'], cfg['jobs']['semver_from']
    if not isinstance(sf, int) or isinstance(sf, bool) or sf < 0:
        raise ConfigError(f'{CONFIG_NAME}: jobs.semver_from must be a job number (0 = off)')
    uf = cfg['jobs']['usage_from']
    if not isinstance(uf, int) or isinstance(uf, bool) or uf < 0:
        raise ConfigError(f'{CONFIG_NAME}: jobs.usage_from must be a job number (0 = off)')
    if not isinstance(cfg['jobs']['usage_cmd'], str):
        raise ConfigError(f'{CONFIG_NAME}: jobs.usage_cmd must be one command line as a string ("" = none)')
    if '\\' in cfg['jobs']['usage_cmd']:
        raise ConfigError(f'{CONFIG_NAME}: jobs.usage_cmd has a backslash, which POSIX splitting drops: write its paths with forward slashes')
    if rel['consumer_check'] not in ('warn', 'block'):
        raise ConfigError(f'{CONFIG_NAME}: release.consumer_check must be "warn" or "block"')
    if not isinstance(rel['annotated_from'], str) or (rel['annotated_from'] and not re.fullmatch(r'\d+\.\d+\.\d+', rel['annotated_from'])):
        raise ConfigError(f'{CONFIG_NAME}: release.annotated_from must be "" or X.Y.Z')
    if not isinstance(rel['consumers'], list) or not all(isinstance(c, dict) and set(c) <= {'name', 'repo', 'adapter', 'ref'} for c in rel['consumers']):
        raise ConfigError(f'{CONFIG_NAME}: release.consumers must list tables with name, repo, adapter and ref')
    dreg = decisions_registry(cfg)
    if dreg and dreg not in cfg['registries']:
        raise ConfigError(f'{CONFIG_NAME}: policy.decisions names registry {dreg}: declare it in [registries]')
    if dreg and dreg not in cfg['storage']['dir']:
        raise ConfigError(f'{CONFIG_NAME}: policy.decisions names registry {dreg}: list it in [storage] dir (one file per row)')
    if 'proposals' in cfg['registries'] and 'proposals' not in cfg['storage']['dir']:
        raise ConfigError(f'{CONFIG_NAME}: registry proposals: list it in [storage] dir (one file per row): the guard on who answers reads only that folder (C41)')
    if not isinstance(cfg['policy']['decisions_cite_job'], bool):
        raise ConfigError(f'{CONFIG_NAME}: policy.decisions_cite_job must be true or false')
    if cfg['policy']['reviewer_code'] not in ('warn', 'error'):
        raise ConfigError(f'{CONFIG_NAME}: policy.reviewer_code must be "warn" or "error"')
    for k in ('workflow_paths', 'bases'):
        if not isinstance(cfg['policy'][k], list) or not all(isinstance(x, str) and x for x in cfg['policy'][k]):
            raise ConfigError(f'{CONFIG_NAME}: policy.{k} must be a list of non-empty strings')
    for t, k in (('policy', 'thin_merge_lines'), ('policy', 'thin_merge_files'), ('jobs', 'claim_hours')):
        if isinstance(cfg[t][k], bool) or not isinstance(cfg[t][k], (int, float)) or cfg[t][k] < 0:
            raise ConfigError(f'{CONFIG_NAME}: {t}.{k} must be a number of at least 0')
    ms = cfg['jobs']['max_sessions']
    if isinstance(ms, bool) or not isinstance(ms, int) or ms < 0:
        raise ConfigError(f'{CONFIG_NAME}: jobs.max_sessions must be a whole number of at least 0')
    if not isinstance(cfg['views']['commit'], bool) or not isinstance(cfg['views']['dir'], str) or not cfg['views']['dir']:
        raise ConfigError(f'{CONFIG_NAME}: views.commit must be true or false and views.dir a repo-relative folder')
    audit_problem(cfg['audit'])
    return cfg


def audit_problem(au):
    """Raise ConfigError on an `[audit]` value of the wrong type: each default's type is the rule, and a window or a run count is at least 1."""
    for k, default in DEFAULTS['audit'].items():
        v = au[k]
        if isinstance(default, str):
            good = isinstance(v, str) and v
        elif isinstance(default, list):
            good = isinstance(v, list) and all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in v)
        elif isinstance(default, dict):
            good = isinstance(v, dict) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v.values())
        else:
            good = isinstance(v, (int, float)) and not isinstance(v, bool) and v >= (1 if k in ('window_days', 'window_jobs', 'ci_runs', 'max_questions') else 0)
        if not good:
            raise ConfigError(f'{CONFIG_NAME}: audit.{k} has the wrong type or range (default: {default!r})')


@dataclass
class Ctx:
    root: Path
    config: dict
    core_root: Path = CORE_ROOT
    _files: list = field(default=None, repr=False)

    @classmethod
    def load(cls, root=None):
        r = Path(root).resolve() if root else find_root()
        return cls(root=r, config=load_config(r))

    @property
    def is_core(self):
        return self.root == self.core_root.resolve()

    def files(self):
        """Repo-relative POSIX paths of tracked and untracked-but-not-ignored files that exist (so a new tool is checked before its first commit)."""
        if self._files is None:
            self._files = list_files(self.root)
        return self._files


def list_files(root):
    root = Path(root)
    try:
        out = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], env=git_env(),
                             capture_output=True, check=True).stdout.decode('utf-8', 'replace')
        names = sorted({p for p in out.split('\0') if p})
    except (OSError, subprocess.CalledProcessError):
        names = []
        for d, dirs, fs in os.walk(root):
            dirs[:] = [x for x in dirs if x != '.git']
            names += [os.path.relpath(os.path.join(d, f), root).replace(os.sep, '/') for f in fs]
        names.sort()
    return [p for p in names if (root / p).is_file()]   # drops deleted files and submodule gitlinks


_GLOB_CACHE = {}


def glob_to_re(pat):
    """`**` spans folders, `*` and `?` stay inside one path segment (fnmatch lets `*` cross `/`, which is wrong for repo paths)."""
    if pat not in _GLOB_CACHE:
        i, out = 0, ''
        while i < len(pat):
            c = pat[i]
            if pat.startswith('**/', i):
                out += '(?:.*/)?'; i += 3; continue
            if pat.startswith('**', i):
                out += '.*'; i += 2; continue
            out += '[^/]*' if c == '*' else '[^/]' if c == '?' else re.escape(c)
            i += 1
        _GLOB_CACHE[pat] = re.compile(out + r'\Z')
    return _GLOB_CACHE[pat]


def matches(path, patterns):
    return any(glob_to_re(p).match(path) for p in patterns)
