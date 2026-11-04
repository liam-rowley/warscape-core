#!/usr/bin/env python3
"""Compile a game's proxy adapter against this core's sources with -fsyntax-only (W29, C27): the consumer check before a release tag.

purpose: compile <adapter>/adapter.cpp against proxy/src with the DLL compile line's language, warning and define flags (read from build.sh's build_dll line at run time, so they cannot drift) plus -fsyntax-only: no linking, no Lua or UI objects, no build id; a GameAdapter member the adapter does not initialise fails under -Werror=missing-field-initializers (audit C2)
usage: python3 proxy/tools/adapter_syntax.py --adapter DIR [--src DIR] [--cxx COMPILER] [--print-flags]   (exit 0 compiles, 1 does not (the first error printed), 2 no compiler or no adapter.cpp)
when: CI's proxy job on proxy/tests/null_game (must pass) and a copy missing the gesture member (must fail); `wsc release check-consumers` on each `[release] consumers` adapter before the release workflow tags
not-a-verb: a compiler driver for C++ sources (beside build.sh), called by CI and by `wsc release check-consumers`

Why not `build.sh syntax`: build.sh is a DLL input (proxy/tools/build_id.py INPUTS, role build_sh), so a new target there would change every
build id; this file is not an input. The flags come from build.sh's text, so the two compile lines agree by construction.
"""
import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

OWN = Path(__file__).resolve().parents[2]
BUILD_SH = OWN / 'proxy' / 'tools' / 'build.sh'
COMPILERS = ('i686-w64-mingw32-g++-win32', 'i686-w64-mingw32-g++')


def flags(build_sh_text):
    """The DLL compile line's -std, -O, -W (not -Wl) and -D flags (not the build id), plus UI_DEFS: what decides whether an adapter compiles."""
    ui = []
    lines = build_sh_text.splitlines()
    for l in lines:
        if l.startswith('UI_DEFS=('):
            ui = shlex.split(l[len('UI_DEFS=('):l.rindex(')')])
    start = next((i for i, l in enumerate(lines) if l.lstrip().startswith('"$CXX"') and '-shared' in l), None)
    if start is None:
        raise SystemExit('adapter_syntax: no "$CXX" ... -shared line in build.sh build_dll: update this tool with it')
    cmd = []
    for l in lines[start:]:
        cmd.append(l.rstrip().rstrip('\\'))
        if not l.rstrip().endswith('\\'):
            break
    out = []
    for t in shlex.split(' '.join(cmd)):
        if t.startswith(('-std=', '-O', '-D')) and not t.startswith('-DWSP_BUILD_ID') or t.startswith('-W') and not t.startswith('-Wl,'):
            out.append(t)
    return out + ui


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--adapter', required=True, help='the game proxy adapter folder (adapter.cpp, generated/)')
    ap.add_argument('--src', default=str(OWN / 'proxy' / 'src'), help='the core proxy sources (default: this core)')
    ap.add_argument('--cxx', default='', help='the compiler (default: the i686 mingw-w64 g++ build.sh uses)')
    ap.add_argument('--print-flags', action='store_true', help='print the flags read from build.sh and exit')
    a = ap.parse_args(argv)
    fl = flags(BUILD_SH.read_text(encoding='utf-8'))
    if a.print_flags:
        print(' '.join(fl))
        return 0
    src = Path(a.adapter) / 'adapter.cpp'
    if not src.is_file():
        print(f'adapter_syntax: no {src}')
        return 2
    cxx = a.cxx or next((c for c in COMPILERS if shutil.which(c)), '')
    if not cxx or not shutil.which(cxx):
        print(f'adapter_syntax: no compiler ({a.cxx or " or ".join(COMPILERS)}): install `python3 proxy/tools/toolchain.py apt`')
        return 2
    cmd = [cxx, '-fsyntax-only', *fl, f'-I{a.src}', f'-I{a.adapter}', str(src)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    text = (p.stdout or '') + (p.stderr or '')
    if p.returncode == 0:
        print(f'adapter_syntax: {src}: ok against {a.src}')
        return 0
    first = next((l for l in text.splitlines() if 'error' in l), (text.strip().splitlines() or ['no output'])[0])
    print(f'adapter_syntax: {src}: fails: {first}')
    sys.stdout.write(text)
    return 1


if __name__ == '__main__':
    sys.exit(main())
