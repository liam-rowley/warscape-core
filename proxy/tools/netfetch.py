#!/usr/bin/env python3
"""The network retry the proxy's source fetchers call, and CI's cache of their raw downloads (W21, backlog B45b; W24, B62).

purpose: `retry()` (and `transient()`) wrap each download and git fetch of fetch_lua.py, fetch_ui.py and fetch_dxvk.py on transient network errors, one stderr line per retry; `ci-cache` prints the cache key (the pins) and the raw download paths for $GITHUB_OUTPUT
usage: python3 proxy/tools/netfetch.py ci-cache   (game root: proxy/tools/layout.py game-root; paths relative to the working directory); the fetchers import retry, transient, _git_ok and _force_remove
when: CI's proxy job runs `ci-cache` before `build.sh all` (the `{{wsc fetch_cache}}` render block); the fetchers call retry() wherever they run (build.sh, --docker, CI, the PC)
not-a-verb: a library of the fetchers plus CI's cache key, not a registry operation

The retry lives inside the fetchers since W24 (B62): W21 kept it in a CI-only wrapper (`prefetch`) because the fetchers are DLL build-id
inputs, and W24 changes the DLL inputs anyway, so the PC route (`build.sh --docker`) retries too. This module is imported by the fetchers
but is not a DLL input (build_id.py INPUTS): it changes whether a download succeeds, never a byte (layout.py is the precedent). The sha256
checks and the patch checks stay in the fetchers, outside the retried call, and raise SystemExit, which is never retried (a wrong byte is
never a flake). Retry lines go to stderr: build.sh discards the fetchers' stdout.
The CI cache holds only raw downloads (tarballs, git checkouts), never the patched trees (build/lua/src, build/ui/src/lua): their
stamps hold only the tarball's sha256, not the patch list, so a cached patched tree could survive a patch change. fetch_ui.py trusts a
restored checkout only when HEAD is the pin and the working tree equals HEAD (`_git_ok`); anything else it removes and fetches again.
"""
import hashlib
import http.client
import json
import os
import random
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
FETCHED = ('repo', 'commit', 'url', 'sha256')   # the fields of a UI pin fetch_ui.py reads


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


def retry(fn, what, tries=TRIES, delays=DELAYS, sleep=None, jitter=random.uniform):
    """fn() with up to `tries` calls; a transient error waits delay x uniform(0.8, 1.2) and tries again, one line each.
    SystemExit and non-transient errors pass through at once; the last try's error is raised."""
    for n in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:
            if n == tries or not transient(e):
                raise
            wait = delays[min(n - 1, len(delays) - 1)] * jitter(0.8, 1.2)
            print(f'netfetch: {what}: {_say(e)}; retry {n + 1} of {tries} in {round(wait)} s', file=sys.stderr, flush=True)
            (sleep or time.sleep)(wait)


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


def fetched_pins(raw):
    """The bytes of a UI pin file that decide what fetch_ui.py downloads (W42, B99): the FETCHED fields of its KEYS, so a key or a note no fetcher
    reads leaves the cache warm. A file that is not the expected shape gives its own bytes: the key still moves, and the fetcher reports the fault."""
    import fetch_ui
    try:
        pins = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(pins, dict) or not all(isinstance(pins.get(k, {}), dict) for k in fetch_ui.KEYS):
        return raw
    return json.dumps({k: {f: pins[k][f] for f in FETCHED if f in pins[k]} if k in pins else None for k in fetch_ui.KEYS}, sort_keys=True).encode()


def ci_cache(root=None, cwd=None):
    """The $GITHUB_OUTPUT text: `key=` sha256 of the three pins (fetch_lua.PIN, fetched_pins of the UI pin file, fetch_dxvk.PIN) and the
    multi-line `paths` of the raw downloads, relative to `cwd` (default: the working directory)."""
    import fetch_dxvk
    import fetch_lua
    root = Path(root) if root else layout.game_root()
    pins = layout.ui_pins(root)
    h = hashlib.sha256(b'netfetch 2\n')
    h.update(json.dumps(fetch_lua.PIN, sort_keys=True).encode() + b'\n')
    h.update(fetched_pins(pins.read_bytes()) if pins.is_file() else b'no ui pin file\n')
    h.update(b'\n' + json.dumps(fetch_dxvk.PIN, sort_keys=True).encode() + b'\n')
    here = Path(cwd) if cwd else Path.cwd()
    paths = [root / 'build' / 'downloads', root / 'build' / 'ui' / 'src' / 'downloads', root / 'build' / 'ui' / 'src' / 'rmlui',
             root / 'build' / 'ui' / 'src' / 'freetype']
    rel = [Path(os.path.relpath(p.resolve(), here.resolve())).as_posix() for p in paths]
    return '\n'.join([f'key={h.hexdigest()}', f'paths<<{EOF_MARK}', *rel, EOF_MARK]) + '\n'


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ['ci-cache']:
        sys.stdout.write(ci_cache())
        return 0
    print(__doc__.split('\n')[3], file=sys.stderr)
    return 64


if __name__ == '__main__':
    sys.exit(main())
