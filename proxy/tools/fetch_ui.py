#!/usr/bin/env python3
"""Fetch the RmlUi host's pinned sources (RmlUi and FreeType by commit; Lua 5.1.1, stb_image and stb_image_write by sha256), Lua patched to float numbers.

purpose: fetch RmlUi, FreeType, Lua and the stb headers at the commits and sha256 of the game's UI pin file into <game>/build/ui/src, check each, patch luaconf.h to float
usage: python3 proxy/tools/fetch_ui.py [--pins FILE] [--out DIR]   (defaults: proxy/tools/layout.py ui-pins, <game root>/build/ui/src)
when: build.sh runs it before compiling the DLL or the UI host tests; the review viewer's build runs it too (one fetcher, one pin file); never commit the output
not-a-verb: needs network and writes build output, not a registry operation; build.sh calls it

Promoted from the first consumer's viewer/core/fetch_sources.py (J31, J30): the review viewer and the in-game RmlUi host must
build from the same sources (the consumer's decision D37), so both read one pin file (the game's viewer/pins.json, layout.py ui-pins) through this
fetcher. The Lua copy is the viewer's: float lua_Number (the engine's number type) and nothing else; the proxy's engine-patched core
(fetch_lua.py: the engine's dummynode, no GC step) is a different copy for the engine's own lua_State. The host links this one with
its symbols made local (build.sh), so the two never meet.
Needs git (RmlUi, FreeType) and network; downloads are cached under the output folder.
"""
import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout  # noqa: E402

LUACONF = [
    ('#define LUA_NUMBER_DOUBLE\n#define LUA_NUMBER\tdouble', '#define LUA_NUMBER\tfloat   /* Warscape engine build */'),
    ('#define LUA_NUMBER_SCAN\t\t"%lf"', '#define LUA_NUMBER_SCAN\t\t"%f"'),
    ('#define LUA_NUMBER_FMT\t\t"%.14g"', '#define LUA_NUMBER_FMT\t\t"%.7g"'),
    ('#define lua_str2number(s,p)\tstrtod((s), (p))', '#define lua_str2number(s,p)\t((float)strtod((s), (p)))'),
]


def git(*args, cwd):
    return subprocess.run(['git', '-c', 'safe.directory=*', '-c', 'advice.detachedHead=false', *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def fetch_git(name, pin, out):
    d = out / name
    if (d / '.git').exists() and git('rev-parse', 'HEAD', cwd=d) == pin['commit']:
        print(f'fetch_ui: {name} {pin["version"]} at {pin["commit"][:12]} already')
        return
    d.mkdir(parents=True, exist_ok=True)
    if not (d / '.git').exists():
        git('init', '-q', cwd=d)
    git('fetch', '-q', '--depth', '1', pin['repo'], pin['commit'], cwd=d)
    git('checkout', '-q', '--force', 'FETCH_HEAD', cwd=d)
    head = git('rev-parse', 'HEAD', cwd=d)
    if head != pin['commit']:
        sys.exit(f'fetch_ui: {name}: HEAD {head} is not the pinned {pin["commit"]}')
    print(f'fetch_ui: {name} {pin["version"]} at {head[:12]}')


def download(url, sha, cache):
    data = cache.read_bytes() if cache.exists() else None
    if data is None or hashlib.sha256(data).hexdigest() != sha:
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
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
    a = ap.parse_args(argv)
    pins_path = Path(a.pins) if a.pins else layout.ui_pins()
    if not pins_path.is_file():
        sys.exit(f'fetch_ui: no pin file {pin_hint(pins_path)}')
    pins = json.loads(pins_path.read_text(encoding='utf-8'))
    out = Path(a.out) if a.out else layout.game_root() / 'build' / 'ui' / 'src'
    out.mkdir(parents=True, exist_ok=True)
    for k in ('rmlui', 'freetype', 'lua', 'stb_image', 'stb_image_write'):
        if k not in pins:
            sys.exit(f'fetch_ui: {pins_path} has no "{k}" pin')
    fetch_git('rmlui', pins['rmlui'], out)
    fetch_git('freetype', pins['freetype'], out)
    fetch_lua(pins['lua'], out)
    fetch_file('stb', pins['stb_image'], out)
    fetch_file('stb', pins['stb_image_write'], out)
    return 0


def pin_hint(p):
    return f'{p} (set wsc.toml [proxy] ui_pins, or keep viewer/pins.json in the game repo)'


if __name__ == '__main__':
    sys.exit(main())
