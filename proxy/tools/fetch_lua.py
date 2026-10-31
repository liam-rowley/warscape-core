#!/usr/bin/env python3
"""Fetch the pinned Lua 5.1.1 source and patch it into the proxy's Lua core (engine-compatible), sha-checked.

purpose: download lua-5.1.1.tar.gz (pinned sha256), extract src/*.c|h into build/lua/src and apply the three engine patches
         (float numbers, the engine's dummynode as a runtime variable, no GC step of our own); fails if any patch does not apply
usage: python3 proxy/tools/fetch_lua.py [--out build/lua]
when: build.sh runs it before compiling the DLL (the Lua bridge needs lua_* that work on the ENGINE's lua_State); never commit the output
not-a-verb: needs network and writes build output, not a registry operation; build.sh calls it

Why these patches (empire-remastered rml_mod/src/CMakeLists.txt, proven on the earlier remaster 2026-10-19; re-checked on the first consumer 2026-10-29: the exe
says "Lua 5.1 Copyright (C) 1994-2006" and its chunks carry a 4-byte float lua_Number):
  luaconf.h  LUA_NUMBER float, as the engine's build.
  ltable.c   the engine's VM tests "no hash part" by pointer equality with ITS static dummynode, so ours is the engine's address,
             set at run time from an engine-made empty table (wsp_sentinel({})).
  lgc.h      our luaC_checkGC never runs our collector on the engine's heap (the engine's own VM collects).
"""
import argparse
import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout  # noqa: E402

ROOT = layout.game_root()   # downloads and output under the game repo's build/ (J12)
PIN = {
    'version': '5.1.1',
    'url': 'https://www.lua.org/ftp/lua-5.1.1.tar.gz',
    'sha256': 'c5daeed0a75d8e4dd2328b7c7a69888247868154acbda69110e97d4a6e17d1f0',
}
PATCHES = {
    'luaconf.h': [
        ('#define LUA_NUMBER_DOUBLE\n#define LUA_NUMBER\tdouble', '#define LUA_NUMBER\tfloat   /* Warscape engine build */'),
        ('#define LUA_NUMBER_SCAN\t\t"%lf"', '#define LUA_NUMBER_SCAN\t\t"%f"'),
        ('#define LUA_NUMBER_FMT\t\t"%.14g"', '#define LUA_NUMBER_FMT\t\t"%.7g"'),
        ('#define lua_str2number(s,p)\tstrtod((s), (p))', '#define lua_str2number(s,p)\t((float)strtod((s), (p)))'),
    ],
    'ltable.c': [
        ('#define dummynode\t\t(&dummynode_)', 'const Node *g_engine_dummynode = 0;\n#define dummynode\t\t(g_engine_dummynode)'),
    ],
    'lgc.h': [
        ('if (G(L)->totalbytes >= G(L)->GCthreshold)', 'if (0)'),
    ],
}
# The core only: no lua.c / luac.c (mains), no standard libraries (the engine has its own), no print.
CORE = ['lapi.c', 'lcode.c', 'ldebug.c', 'ldo.c', 'ldump.c', 'lfunc.c', 'lgc.c', 'llex.c', 'lmem.c', 'lobject.c', 'lopcodes.c',
        'lparser.c', 'lstate.c', 'lstring.c', 'ltable.c', 'ltm.c', 'lundump.c', 'lvm.c', 'lzio.c', 'lauxlib.c']


def fetch(out):
    out = Path(out)
    stamp = out / 'PATCHED'
    if stamp.exists() and stamp.read_text().strip() == PIN['sha256']:
        print(f'fetch_lua: Lua {PIN["version"]} already patched in {out}')
        return out
    cache = ROOT / 'build' / 'downloads' / 'lua-5.1.1.tar.gz'
    data = cache.read_bytes() if cache.exists() else None
    if data is None or hashlib.sha256(data).hexdigest() != PIN['sha256']:
        with urllib.request.urlopen(PIN['url'], timeout=120) as r:
            data = r.read()
        got = hashlib.sha256(data).hexdigest()
        if got != PIN['sha256']:
            raise SystemExit(f'fetch_lua: {PIN["url"]} has sha256 {got}, pinned {PIN["sha256"]}: refusing')
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    src = out / 'src'
    src.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as t:
        for m in t.getmembers():
            p = Path(m.name)
            if len(p.parts) == 3 and p.parts[1] == 'src' and p.suffix in ('.c', '.h'):
                text = t.extractfile(m).read().decode('latin-1')
                for old, new in PATCHES.get(p.name, []):
                    if old not in text:
                        raise SystemExit(f'fetch_lua: patch for {p.name} did not apply ({old[:40]!r})')
                    text = text.replace(old, new)
                (src / p.name).write_text(text, encoding='latin-1', newline='')
    for name in CORE:
        if not (src / name).exists():
            raise SystemExit(f'fetch_lua: {name} missing from the tarball')
    stamp.write_text(PIN['sha256'] + '\n')
    print(f'fetch_lua: Lua {PIN["version"]} extracted and patched into {src}')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', default=str(ROOT / 'build' / 'lua'))
    a = ap.parse_args(argv)
    fetch(a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
