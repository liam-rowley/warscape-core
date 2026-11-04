#!/usr/bin/env python3
"""The proxy DLL's toolchain pin: the build image and every mingw-w64 package at its exact version, a build-id input (W24, C24).

purpose: hold the pinned ubuntu:24.04 image digest and the exact apt versions of the mingw-w64 packages that make the DLL; print them for apt and docker; check the installed toolchain against them
usage: python3 proxy/tools/toolchain.py apt | image | installed | check <cxx>   (apt: `pkg=version ...` sorted on one line; image: the image reference; installed: the pinned packages' installed versions on one line; check: exit 0 with one `toolchain: pinned:` line, else one line per difference, the fix, and exit 2)
when: CI's proxy job installs `$(toolchain.py apt)`; build.sh reads `image` and `apt` for --docker, runs `check "$CXX"` before the first mingw compile of dll, all and repro, and stamps the cached UI objects with `installed`
not-a-verb: a build helper like build_id.py, read by build.sh and CI, not a registry operation

Why a committed pin and not the compiler's version lines in the id: rule 79 of the first consumer recomputes the build id from committed
content with no compiler (build_id.py, the `toolchain` role is this file), and Ubuntu's version lines name neither the package revision nor
mingw-w64-i686-dev (the headers, CRT and import libraries linked into the DLL): `i686-w64-mingw32-g++-win32 (GCC) 13-win32` is the whole first line.
The set is what `apt-get install --no-install-recommends g++-mingw-w64-i686-win32` installs, listed by `dpkg-query -W '*mingw-w64*'`, identical
on the GitHub ubuntu-24.04 runner and in the pinned image (CI run 41802947502, 2026-11-04); every version is from the `noble` release pocket
(`apt-cache madison`: noble/universe, none from noble-updates), which never changes. A bump is a core job that edits PIN: a new build id, which is
the truth (a new toolchain is a new DLL). Contract: docs/PROXY_BUILD.md.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

PIN = {
    # ubuntu:24.04 by digest (moved from build.sh, pinned 2026-10-29): the --docker container, the PC route (the first consumer's D31)
    'image': 'ubuntu@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852',
    'apt': {
        'binutils-mingw-w64-i686': '2.41.90.20240122-1ubuntu1+11.4',
        'g++-mingw-w64-i686-win32': '13.2.0-6ubuntu1+26.1',
        'gcc-mingw-w64-base': '13.2.0-6ubuntu1+26.1',
        'gcc-mingw-w64-i686-win32': '13.2.0-6ubuntu1+26.1',
        'gcc-mingw-w64-i686-win32-runtime': '13.2.0-6ubuntu1+26.1',
        'mingw-w64-common': '11.0.1-3build1',
        'mingw-w64-i686-dev': '11.0.1-3build1',
    },
}


def apt_line(pin=PIN):
    """`pkg=version ...`, the words sorted: the argument list of `apt-get install`."""
    return ' '.join(sorted(f'{p}={v}' for p, v in pin['apt'].items()))


def _run(argv):
    """(exit code, stdout); OSError when the program is missing (the tests inject a fake)."""
    p = subprocess.run(argv, capture_output=True, text=True)
    return p.returncode, p.stdout


def installed(pin=PIN, run=_run):
    """{package: installed version or None} for the pinned packages; None when there is no dpkg-query (the pin cannot be read)."""
    try:
        _, out = run(['dpkg-query', '-W', '-f', '${Package}\t${Version}\t${db:Status-Abbrev}\n', *sorted(pin['apt'])])
    except OSError:
        return None
    have = {p: None for p in pin['apt']}
    for line in out.splitlines():   # an unknown package is a stderr line and exit 1; a known one not installed shows `un ` / `rc `
        parts = line.split('\t')
        if len(parts) == 3 and parts[0] in have and parts[2][1:2] == 'i':
            have[parts[0]] = parts[1]
    return have


def _first_line(run, argv):
    try:
        rc, out = run(argv)
    except OSError:
        return f'{argv[0]}: not found'
    return (out.splitlines() or [f'{argv[0]}: no output'])[0].strip()


def _self():
    try:
        return Path(os.path.relpath(Path(__file__).resolve(), Path.cwd())).as_posix()
    except ValueError:   # another drive (Windows)
        return Path(__file__).resolve().as_posix()


def check(cxx, pin=PIN, run=_run):
    """(ok, lines): every pinned package installed at its pin and `cxx` (resolved like `readlink -f`) owned by a pinned package. ok: one
    `toolchain: pinned:` line with the compiler's and the linker's first version lines; else one line per difference, then the fix."""
    have = installed(pin, run)
    bad = []
    if have is None:
        bad.append('toolchain: no dpkg-query: the pin cannot be checked')
    else:
        for p, want in sorted(pin['apt'].items()):
            got = have.get(p)
            if got != want:
                bad.append(f'toolchain: {p} {got + " installed" if got else "not installed"}, pinned {want}')
        path = cxx if '/' in cxx else (shutil.which(cxx) or cxx)
        try:
            rc, real = run(['readlink', '-f', path])
            real = real.strip() if rc == 0 and real.strip() else path
        except OSError:
            real = os.path.realpath(path)
        try:
            rc, out = run(['dpkg', '-S', real])
        except OSError:
            rc, out = 1, ''
        owners = set()
        for line in out.splitlines() if rc == 0 else []:
            if ': ' in line and not line.startswith('diversion'):
                owners.update(o.strip().split(':')[0] for o in line.split(': ', 1)[0].split(','))
        if not owners & set(pin['apt']):
            bad.append(f'toolchain: {cxx} resolves to {real}, owned by {", ".join(sorted(owners)) or "no package"}, not by a pinned package '
                       f'(a compiler earlier on PATH cannot stand in)')
    if bad:
        return False, bad + [f'toolchain: fix: install the pins (sudo apt-get install -y --no-install-recommends $(python3 {_self()} apt)), '
                             'or build with build.sh --docker; WSP_TOOLCHAIN=any builds off the pin with a -dirty id']
    ld = (cxx[:cxx.index('g++')] if 'g++' in cxx else '') + 'ld'
    return True, [f'toolchain: pinned: {len(pin["apt"])} packages at their pins; {_first_line(run, [cxx, "--version"])}; '
                  f'{_first_line(run, [ld, "--version"])}']


def main(argv=None, run=_run):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ['apt']:
        print(apt_line())
        return 0
    if argv == ['image']:
        print(PIN['image'])
        return 0
    if argv == ['installed']:
        have = installed(run=run)
        print('no dpkg-query' if have is None else ' '.join(f'{p}={v or "none"}' for p, v in sorted(have.items())))
        return 0
    if len(argv) == 2 and argv[0] == 'check':
        ok, lines = check(argv[1], run=run)
        print('\n'.join(lines))
        return 0 if ok else 2
    print(__doc__.split('\n')[3], file=sys.stderr)
    return 64


if __name__ == '__main__':
    sys.exit(main())
