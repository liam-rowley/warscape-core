#!/usr/bin/env python3
"""Fetch the RmlUi host's pinned sources (RmlUi and FreeType by commit; Lua 5.1.1, stb_image and stb_image_write by sha256), Lua patched to float numbers.

purpose: fetch RmlUi, FreeType, Lua and the stb headers at the commits and sha256 of the game's UI pin file into <game>/build/ui/src, check each, patch luaconf.h to float
usage: python3 proxy/tools/fetch_ui.py [--pins FILE] [--out DIR] [--check]   (defaults: proxy/tools/layout.py ui-pins, <game root>/build/ui/src; --check: validate the pin file against schemas/ui_pins.schema.json only, no network)
when: build.sh runs it before compiling the DLL or the UI host tests; the review viewer's build runs it too (one fetcher, one pin file); --check in a game's tests or by hand after editing the pin file; never commit the output
not-a-verb: needs network and writes build output, not a registry operation; build.sh calls it

Promoted from the first consumer's viewer/core/fetch_sources.py (J31, J30): the review viewer and the in-game RmlUi host must
build from the same sources (the consumer's decision D37), so both read one pin file (the game's viewer/pins.json, layout.py ui-pins) through this
fetcher. The Lua copy is the viewer's: float lua_Number (the engine's number type) and nothing else; the proxy's engine-patched core
(fetch_lua.py: the engine's dummynode, no GC step) is a different copy for the engine's own lua_State. The host links this one with
its symbols made local (build.sh), so the two never meet.
The pin file is validated against schemas/ui_pins.schema.json (warscape/schema.py) before anything is fetched, and every problem is
named (W16, B52): a bad commit or sha256 shape is found here, not by the network. Needs git (RmlUi, FreeType) and network; downloads are cached under the output folder. Each download and git fetch is retried on a
network flake (netfetch.retry, W24, B62; one stderr line per retry), never a sha mismatch or a failed patch. A checkout is trusted only
when HEAD is the pinned commit and the working tree equals HEAD; anything else (a fetch that failed after `git init`, a cache restored in
part, another pin) is removed and fetched again.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout  # noqa: E402
import netfetch  # noqa: E402  (not a DLL input: it changes whether a download succeeds, never a byte)

CORE = Path(__file__).resolve().parents[2]   # the core's root (proxy/tools/ -> the repo that holds them), found from this file as layout.py is
if str(CORE) not in sys.path:
    sys.path.append(str(CORE))
from warscape.schema import validate  # noqa: E402  (the subset validator, standard library only)

SCHEMA = CORE / 'schemas' / 'ui_pins.schema.json'

LUACONF = [
    ('#define LUA_NUMBER_DOUBLE\n#define LUA_NUMBER\tdouble', '#define LUA_NUMBER\tfloat   /* Warscape engine build */'),
    ('#define LUA_NUMBER_SCAN\t\t"%lf"', '#define LUA_NUMBER_SCAN\t\t"%f"'),
    ('#define LUA_NUMBER_FMT\t\t"%.14g"', '#define LUA_NUMBER_FMT\t\t"%.7g"'),
    ('#define lua_str2number(s,p)\tstrtod((s), (p))', '#define lua_str2number(s,p)\t((float)strtod((s), (p)))'),
]


def git(*args, cwd):
    return subprocess.run(['git', '-c', 'safe.directory=*', '-c', 'advice.detachedHead=false', *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _head(d):
    try:
        return git('rev-parse', '--verify', '--quiet', 'HEAD', cwd=d)
    except subprocess.CalledProcessError:
        return None


def fetch_git(name, pin, out):
    d = out / name
    if (d / '.git').exists():
        if _head(d) == pin['commit'] and netfetch._git_ok(d):
            print(f'fetch_ui: {name} {pin["version"]} at {pin["commit"][:12]} already')
            return
        shutil.rmtree(d, onexc=netfetch._force_remove)   # git's objects are read-only, which Windows refuses to delete
        print(f'fetch_ui: {name}: removed {d} (HEAD not the pinned {pin["commit"][:12]}, unreadable, or a working tree that differs '
              f'from it); fetching again', file=sys.stderr, flush=True)
    d.mkdir(parents=True, exist_ok=True)
    git('init', '-q', cwd=d)
    netfetch.retry(lambda: git('fetch', '-q', '--depth', '1', pin['repo'], pin['commit'], cwd=d), f'fetch_ui {name}')
    git('checkout', '-q', '--force', 'FETCH_HEAD', cwd=d)
    head = git('rev-parse', 'HEAD', cwd=d)
    if head != pin['commit']:
        sys.exit(f'fetch_ui: {name}: HEAD {head} is not the pinned {pin["commit"]}')
    print(f'fetch_ui: {name} {pin["version"]} at {head[:12]}')


def _get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def download(url, sha, cache):
    data = cache.read_bytes() if cache.exists() else None
    if data is None or hashlib.sha256(data).hexdigest() != sha:
        data = netfetch.retry(lambda: _get(url), f'fetch_ui {url}')   # the sha check below is outside the retry
        got = hashlib.sha256(data).hexdigest()
        if got != sha:
            sys.exit(f'fetch_ui: {url} has sha256 {got}, pinned {sha}: refusing')
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    return data


def fetch_lua(pin, out):
    d = out / 'lua'
    stamp = d / 'PATCHED'
    if stamp.exists() and stamp.read_text().strip() == pin['sha256']:
        print(f'fetch_ui: lua {pin["version"]} already patched')
        return
    data = download(pin['url'], pin['sha256'], out / 'downloads' / Path(pin['url']).name)
    src = d / 'src'
    src.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as t:
        for m in t.getmembers():
            p = Path(m.name)
            if m.isfile() and len(p.parts) == 3 and p.parts[1] == 'src' and p.suffix in ('.c', '.h'):
                (src / p.name).write_bytes(t.extractfile(m).read())
    conf = (src / 'luaconf.h').read_text()
    for old, new in LUACONF:
        if conf.count(old) != 1:
            sys.exit(f'fetch_ui: luaconf.h patch does not apply: {old!r}')
        conf = conf.replace(old, new)
    (src / 'luaconf.h').write_text(conf, newline='\n')
    stamp.write_text(pin['sha256'] + '\n')
    print(f'fetch_ui: lua {pin["version"]} fetched and patched to float numbers')


def fetch_file(name, pin, out):
    dest = out / name / Path(pin['url']).name
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == pin['sha256']:
        print(f'fetch_ui: {dest.name} {pin["version"]} already')
        return
    data = download(pin['url'], pin['sha256'], out / 'downloads' / dest.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f'fetch_ui: {dest.name} {pin["version"]} fetched')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--pins', default=None, help='pin file (default: layout.py ui-pins)')
    ap.add_argument('--out', default=None, help='output folder (default: <game root>/build/ui/src)')
    ap.add_argument('--check', action='store_true', help='validate the pin file only (no network, nothing written)')
    a = ap.parse_args(argv)
    pins_path = Path(a.pins) if a.pins else layout.ui_pins()
    if not pins_path.is_file():
        sys.exit(f'fetch_ui: no pin file {pin_hint(pins_path)}')
    pins, problems = check(pins_path)
    if problems:
        sys.exit('\n'.join(problems))
    if a.check:
        print(f'fetch_ui: {pins_path.as_posix()}: the pin file is valid ({", ".join(KEYS)}; {SCHEMA.name})')
        return 0
    out = Path(a.out) if a.out else layout.game_root() / 'build' / 'ui' / 'src'
    out.mkdir(parents=True, exist_ok=True)
    fetch_git('rmlui', pins['rmlui'], out)
    fetch_git('freetype', pins['freetype'], out)
    fetch_lua(pins['lua'], out)
    fetch_file('stb', pins['stb_image'], out)
    fetch_file('stb', pins['stb_image_write'], out)
    return 0


def pin_hint(p):
    return f'{p} (set wsc.toml [proxy] ui_pins, or keep viewer/pins.json in the game repo)'


# The UI pin file's keys (docs/CONSUMING.md "The UI pin file"), each with what it is for
KEYS = {'rmlui': 'RmlUi, the UI library', 'freetype': "RmlUi's font engine", 'lua': "the host's own Lua 5.1.1 (float numbers)",
        'stb_image': 'image loading', 'stb_image_write': "the in-game host's PNG dump, required since 0.10.0"}
# the reference pin file to copy an entry from: the null game's, beside these tools in the core
REFERENCE = Path(__file__).resolve().parents[1] / 'tests' / 'null_game' / 'viewer' / 'pins.json'


def check(pins_path):
    """(pins, problems): the pin file read and validated against schemas/ui_pins.schema.json; every problem names the file and its key
    (a missing required pin gets the missing_pin text, which says where to copy the entry from). Empty problems: valid."""
    try:
        pins = json.loads(pins_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, [f'fetch_ui: {pins_path}: not readable JSON: {e}']
    errs = validate(pins, json.loads(SCHEMA.read_text(encoding='utf-8')))
    problems = [missing_pin(pins_path, k) for k in KEYS if isinstance(pins, dict) and k not in pins]
    problems += [f'fetch_ui: {pins_path}: {e} ({SCHEMA.name})' for e in errs if not e.startswith('/: missing required field')]
    return pins, problems


def missing_pin(pins_path, key):
    """The refusal for a pin file without `key` (C2 of the 2026-11-03 audit): the key, the five keys, what it is for, the entry to copy."""
    try:
        ref = Path(os.path.relpath(REFERENCE, layout.game_root())).as_posix()
        ref = ref if not ref.startswith('..') else REFERENCE.as_posix()
    except (ValueError, layout.LayoutError):   # another drive (Windows), or no game root
        ref = REFERENCE.as_posix()
    return (f'fetch_ui: {pins_path} has no "{key}" pin ({KEYS[key]}). The UI pin file needs all five keys: {", ".join(KEYS)} '
            f'(docs/CONSUMING.md "The UI pin file"; it is a DLL input, the ui_pins role). Copy the "{key}" entry from the reference pin file, '
            f'the null game\'s {ref}')


if __name__ == '__main__':
    sys.exit(main())
