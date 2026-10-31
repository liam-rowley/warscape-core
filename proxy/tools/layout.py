#!/usr/bin/env python3
"""Where the game repo and its adapters are, for every proxy and harness tool (J12): one answer before and after the move to warscape-core.

purpose: print (or return) the game repo root, the core's own root, the proxy core sources, and the game's proxy and harness adapters
usage: python3 proxy/tools/layout.py [game-root|own-root|proxy-src|proxy-adapter|harness-adapter|all]   (default all: one `name<TAB>path` line each)
when: every core tool that needs a game path imports it (python) or runs it (bash: build.sh, job.sh, shot.sh); run it by hand to see what a tool will use
not-a-verb: a path resolver shared by the proxy and harness tools (bash and python), not a registry operation

A tool never finds the game by its own location or a game name. The rules, in order:
- own root: the nearest folder above this file with a wsc.toml (the game repo while the code lives under */core/, warscape-core after
  the move, where the game repo holds it as the `core` submodule).
- game root: $WSP_GAME_ROOT when set (inside the build container, which has no git), else the superproject of the own root (the game
  repo that pins the core), else the own root (before the move, and the core's own CI with its null adapter).
- proxy core sources: proxy/src under the own root, else proxy/core (before the move).
- adapters: the game root's wsc.toml `[proxy] adapter` / `[harness] adapter` (repo-relative) when it names one, else the one
  proxy/*/adapter.cpp folder / the one harness/*/adapter.json under the game root; none or several is an error that names them.
$WSP_PROXY_ADAPTER and $HARNESS_ADAPTER override the adapters (tests, the kit). Read-only: nothing here writes.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


class LayoutError(Exception):
    pass


def own_root(start=HERE):
    for d in (start, *start.parents):
        if (d / 'wsc.toml').is_file():
            return d
    raise LayoutError(f'layout: no wsc.toml above {start}')


def game_root(own=None):
    env = os.environ.get('WSP_GAME_ROOT')
    if env:
        return Path(env).resolve()
    own = own or own_root()
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}   # a hook's GIT_DIR would name another repository
    try:
        p = subprocess.run(['git', '-C', str(own), 'rev-parse', '--show-superproject-working-tree'], capture_output=True, text=True, env=env)
        sup = p.stdout.strip() if p.returncode == 0 else ''
    except OSError:
        sup = ''
    return Path(sup).resolve() if sup else own


def proxy_src(own=None):
    own = own or own_root()
    for rel in ('proxy/src', 'proxy/core'):
        if (own / rel).is_dir():
            return own / rel
    raise LayoutError(f'layout: no proxy/src or proxy/core under {own}')


def _config(game, section):
    f = game / 'wsc.toml'
    if not f.is_file():
        return None
    import tomllib
    with open(f, 'rb') as fh:
        v = tomllib.load(fh).get(section, {}).get('adapter')
    return game / v if v else None


def _one(game, section, pattern, kind):
    named = _config(game, section)
    if named:
        if not named.exists():
            raise LayoutError(f'layout: wsc.toml [{section}] adapter = {named} does not exist')
        return named
    hits = sorted(p for p in game.glob(pattern) if p.is_file())
    if len(hits) != 1:
        raise LayoutError(f'layout: {len(hits)} {kind} under {game} ({", ".join(h.relative_to(game).as_posix() for h in hits) or "none"}): '
                          f'name one in wsc.toml [{section}] adapter')
    return hits[0]


def proxy_adapter(game=None):
    """The game's proxy adapter folder (adapter.cpp, identity.json, the ini, generated/, lua/)."""
    env = os.environ.get('WSP_PROXY_ADAPTER')
    if env:
        return Path(env).resolve()
    p = _one(game or game_root(), 'proxy', 'proxy/*/adapter.cpp', 'proxy adapters (proxy/*/adapter.cpp)')
    return p.parent if p.is_file() else p


def harness_adapter(game=None):
    """The game's harness adapter file (adapter.json)."""
    env = os.environ.get('HARNESS_ADAPTER')
    if env:
        return Path(env).resolve()
    return _one(game or game_root(), 'harness', 'harness/*/adapter.json', 'harness adapters (harness/*/adapter.json)')


NAMES = {'own-root': lambda: own_root(), 'game-root': lambda: game_root(), 'proxy-src': lambda: proxy_src(),
         'proxy-adapter': lambda: proxy_adapter(), 'harness-adapter': lambda: harness_adapter()}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    what = argv[0] if argv else 'all'
    if what not in NAMES and what != 'all':
        print(__doc__.split('\n')[3], file=sys.stderr)
        return 64
    try:
        if what == 'all':
            for n, f in NAMES.items():
                try:
                    print(f'{n}\t{f().as_posix()}')
                except LayoutError as e:
                    print(f'{n}\t- ({e})')
        else:
            print(NAMES[what]().as_posix())
    except LayoutError as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
