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
    'tools': {
        'extensions': ['py', 'sh', 'ps1', 'cmd', 'bat', 'lua', 'js', 'vbs'],
        'include': [],                     # extra globs for extensionless tools (git hooks, launchers)
        'library': [],                     # importable library code: no header or row needed
        'exempt': [],                      # history, generated files, tests
        'retire_after_days': 90,           # warn for live tools whose last_used is older; 0 disables
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
}


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
        out = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
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
