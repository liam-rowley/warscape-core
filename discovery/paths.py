"""Where the game and its discovery adapter are, and what the two games are called, for every discovery pass (W4).

purpose: give the discovery modules the game repo root (REPO), the discovery adapter folder (ADAPTER) and the two game names (TARGET, REFERENCE) from layout.py and the adapter's games.json
usage: from paths import REPO, ADAPTER, TARGET, REFERENCE, adapter_file   (library); `configure(root)` re-resolves them for another repo
when: every discovery module imports it instead of finding the game by its own location; names are data: games.json "target" and "reference" (the game the tools run on, the game it is compared with)
not-a-verb: a path and name resolver imported by the discovery modules, like proxy/tools/layout.py which it uses

No module finds the game by its own location. REPO is layout.game_root() ($WSP_GAME_ROOT, else the superproject, else the core itself) and
ADAPTER is layout.discovery_adapter() (`wsc.toml` `[discovery] adapter`, else the one discovery/*/games.json folder). Without an adapter
ADAPTER is a path that names the fix, so the first file read fails with that message; the pure functions of the modules need no adapter.
TARGET and REFERENCE come from ADAPTER/games.json and read 'target' and 'reference' when the file is missing.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'proxy', 'tools'))
import layout  # noqa: E402

NO_ADAPTER = '(no [discovery] adapter in wsc.toml: name the folder that holds games.json)'
REPO = ADAPTER = TARGET = REFERENCE = ''


def _names(adapter):
    try:
        with open(os.path.join(adapter, 'games.json'), encoding='utf-8') as f:
            g = json.load(f)
        return g.get('target') or 'target', g.get('reference') or 'reference'
    except (OSError, ValueError):
        return 'target', 'reference'


def configure(root=None):
    """Resolve REPO, ADAPTER, TARGET and REFERENCE (for `root`, else from the environment and this file's place). Returns REPO."""
    global REPO, ADAPTER, TARGET, REFERENCE
    from pathlib import Path
    try:
        REPO = os.path.normpath(str(layout.game_root() if root is None else Path(root).resolve()))
    except layout.LayoutError:
        REPO = os.getcwd()
    try:
        ADAPTER = os.path.normpath(str(layout.discovery_adapter(Path(REPO))))
    except layout.LayoutError:
        ADAPTER = os.path.join(REPO, 'discovery', NO_ADAPTER)
    TARGET, REFERENCE = _names(ADAPTER)
    return REPO


def adapter_file(*parts):
    """A file of the adapter folder (games.json, asset_roles.json, ...)."""
    return os.path.join(ADAPTER, *parts)


def result_dir(*parts):
    """A committed result folder of the game repo (discovery/<area>/), beside the adapter folder."""
    return os.path.join(REPO, 'discovery', *parts)


def titled(name):
    """A game name as the generated READMEs print it: 'alpha' to 'Alpha'."""
    return name[:1].upper() + name[1:]


configure()


def adapter_for(root):
    """The adapter folder of the game repo at `root` (for the functions that take a root, like the gate)."""
    from pathlib import Path
    return Path(layout.discovery_adapter(Path(root)))


def adapter_rel(root=None):
    """The adapter folder as a repo-relative POSIX path (the committed READMEs name it)."""
    base = REPO if root is None else str(root)
    ad = ADAPTER if root is None else str(adapter_for(root))
    return os.path.relpath(ad, base).replace(os.sep, '/')
