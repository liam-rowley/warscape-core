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
    },
    'tests': {'dirs': ['tests'], 'timeout_s': 600},
    'gates': {'fast': [], 'skip': []},     # fast: empty = every gate except `tests`
    'cli': {'verb_dirs': []},              # repo-relative folders of extra verb modules
    'core': {'version': ''},               # the core version this repo pins (checked by the core_pin gate)
    # where a game's adapters are, for the proxy and harness tools (proxy/tools/layout.py, napoleon J12); empty = the one
    # proxy/*/adapter.cpp folder / the one harness/*/adapter.json in the repo
    'proxy': {'adapter': ''},              # repo-relative folder: adapter.cpp, identity.json, generated/, the config file, lua/
    'harness': {'adapter': ''},            # repo-relative file: the watcher's adapter.json (its profiles/ beside it)
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


def load_config(root):
    path = Path(root) / CONFIG_NAME
    try:
        with open(path, 'rb') as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f'{path}: {e}') from None
    cfg = _merge(DEFAULTS, raw)
    for name, spec in cfg['registries'].items():
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
            raise ConfigError(f'{CONFIG_NAME}: registry name {name!r} must match [a-z][a-z0-9_]*')
        if not isinstance(spec, str):
            raise ConfigError(f'{CONFIG_NAME}: registries.{name} must be a string ("core:<name>" or a schema path)')
    bad = [n for n in cfg['storage']['dir'] if n not in cfg['registries']]
    if not isinstance(cfg['storage']['dir'], list) or bad:
        raise ConfigError(f'{CONFIG_NAME}: storage.dir must list declared registries; not declared: {", ".join(map(str, bad))}')
    if not isinstance(cfg['views']['commit'], bool) or not isinstance(cfg['views']['dir'], str) or not cfg['views']['dir']:
        raise ConfigError(f'{CONFIG_NAME}: views.commit must be true or false and views.dir a repo-relative folder')
    return cfg


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
