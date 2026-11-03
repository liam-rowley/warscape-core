#!/usr/bin/env python3
"""Retry the proxy's source fetchers on network flakes, and give CI a cache of their raw downloads (W21, backlog B45b).

purpose: `prefetch` runs fetch_lua.py and fetch_ui.py (the outputs build.sh uses) inside a retry on transient network errors; `ci-cache` prints the cache key (the pins) and the raw download paths for $GITHUB_OUTPUT; `retry()` is imported by fetch_dxvk.py
usage: python3 proxy/tools/netfetch.py prefetch | ci-cache   (game root: proxy/tools/layout.py game-root; ci-cache paths are relative to the working directory)
when: CI's proxy job runs both before `build.sh all` (the `{{wsc fetch_cache}}` render block); by hand: `prefetch` before an offline build
not-a-verb: needs network and writes build output, like the fetchers it wraps

Why a wrapper and not a retry inside fetch_lua.py and fetch_ui.py: both are DLL build-id inputs (build_id.py INPUTS), so editing them
gives every consumer a new build id for identical DLL bytes (and a consumer's acceptance passes at its pin bump). The fetchers are idempotent:
they skip what is present and sha-checked, so retrying a whole call equals retrying its failed request, and build.sh then finds
everything in place and makes no network call. The sha256 checks stay in the fetchers; every mismatch and every failed patch raises
SystemExit there, which is never retried (a wrong byte is never a flake).
The one place a fetcher is not idempotent: a git fetch that failed after `git init`, or a checkout restored only in part, leaves a
folder fetch_ui.py trusts or cannot read (it checks only that HEAD is the pinned commit). Before each try `prefetch` removes a
checkout whose HEAD cannot be read or whose working tree differs from HEAD, so fetch_ui.py fetches it again.
The CI cache holds only raw downloads (tarballs, git checkouts), never the patched trees (build/lua/src, build/ui/src/lua): their
stamps hold only the tarball's sha256, not the patch list, so a cached patched tree could survive a patch change.
"""
import hashlib
import http.client
import json
import os
import random
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout  # noqa: E402

TRIES = 4
DELAYS = (5, 15, 45)
EOF_MARK = 'NETFETCH_EOF'


def transient(e):
    """True for an error a retry can cure: the network (OSError covers URLError, TimeoutError, ConnectionError, ssl.SSLError), an
    HTTP protocol fault, a failed git command, and HTTP 408, 429 and 5xx. Any other HTTP status is an answer, not a flake."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code in (408, 429) or 500 <= e.code <= 599
    return isinstance(e, (OSError, http.client.HTTPException, subprocess.CalledProcessError))


def _say(e):
    text = f'{type(e).__name__}: {e}'
    if isinstance(e, subprocess.CalledProcessError) and e.stderr:
        text += f' ({str(e.stderr).strip()[:200]})'
    return text


def retry(fn, what, tries=TRIES, delays=DELAYS, sleep=time.sleep, jitter=random.uniform):
    """fn() with up to `tries` calls; a transient error waits delay x uniform(0.8, 1.2) and tries again, one line each.
    SystemExit and non-transient errors pass through at once; the last try's error is raised."""
    for n in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:
            if n == tries or not transient(e):
                raise
            wait = delays[min(n - 1, len(delays) - 1)] * jitter(0.8, 1.2)
            print(f'netfetch: {what}: {_say(e)}; retry {n + 1} of {tries} in {round(wait)} s', flush=True)
            sleep(wait)


def _force_remove(func, path, exc):
    """shutil.rmtree onexc: git makes its objects read-only, which Windows refuses to delete."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _git_ok(d):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    base = ['git', '-c', 'safe.directory=*', '-C', str(d)]
    try:
        head = subprocess.run([*base, 'rev-parse', '--verify', '--quiet', 'HEAD'], capture_output=True, text=True, env=env)
        if head.returncode != 0:
            return False
        st = subprocess.run([*base, 'status', '--porcelain', '--untracked-files=no'], capture_output=True, text=True, env=env)
        return st.returncode == 0 and not st.stdout.strip()
    except OSError:
        return False


def clean_checkouts(src):
    """Remove each git checkout under `src` (rmlui, freetype) that fetch_ui.py would trust or fail on but cannot be complete."""
    for name in ('rmlui', 'freetype'):
        d = Path(src) / name
        if (d / '.git').exists() and not _git_ok(d):
            shutil.rmtree(d, onexc=_force_remove)
            print(f'netfetch: {name}: removed {d} (unreadable HEAD or a working tree that differs from it); fetching again', flush=True)


def prefetch(root=None, sleep=time.sleep):
    """Fetch every source build.sh compiles, each fetcher inside retry(); the outputs are the ones build.sh passes."""
    import fetch_lua
    import fetch_ui
    root = Path(root) if root else layout.game_root()
    ui = root / 'build' / 'ui' / 'src'
    retry(lambda: fetch_lua.fetch(root / 'build' / 'lua'), 'fetch_lua', sleep=sleep)

    def ui_once():
        clean_checkouts(ui)
        if fetch_ui.main(['--out', str(ui)]) != 0:
            raise SystemExit('netfetch: fetch_ui failed')

    retry(ui_once, 'fetch_ui', sleep=sleep)
    print(f'netfetch: prefetch done under {root / "build"}', flush=True)


def ci_cache(root=None, cwd=None):
    """The $GITHUB_OUTPUT text: `key=` sha256 of the three pins (fetch_lua.PIN, the UI pin file's bytes, fetch_dxvk.PIN) and the
    multi-line `paths` of the raw downloads, relative to `cwd` (default: the working directory)."""
    import fetch_dxvk
    import fetch_lua
    root = Path(root) if root else layout.game_root()
    pins = layout.ui_pins(root)
    h = hashlib.sha256(b'netfetch 1\n')
    h.update(json.dumps(fetch_lua.PIN, sort_keys=True).encode() + b'\n')
    h.update(pins.read_bytes() if pins.is_file() else b'no ui pin file\n')
    h.update(b'\n' + json.dumps(fetch_dxvk.PIN, sort_keys=True).encode() + b'\n')
    here = Path(cwd) if cwd else Path.cwd()
    paths = [root / 'build' / 'downloads', root / 'build' / 'ui' / 'src' / 'downloads', root / 'build' / 'ui' / 'src' / 'rmlui',
             root / 'build' / 'ui' / 'src' / 'freetype']
    rel = [Path(os.path.relpath(p.resolve(), here.resolve())).as_posix() for p in paths]
    return '\n'.join([f'key={h.hexdigest()}', f'paths<<{EOF_MARK}', *rel, EOF_MARK]) + '\n'


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ['prefetch']:
        prefetch()
        return 0
    if argv == ['ci-cache']:
        sys.stdout.write(ci_cache())
        return 0
    print(__doc__.split('\n')[3], file=sys.stderr)
    return 64


if __name__ == '__main__':
    sys.exit(main())
