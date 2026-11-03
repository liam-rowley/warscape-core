#!/usr/bin/env python3
"""Static reverse-engineering environment: a venv with capstone and pefile from pinned wheels (version + sha256), outside the repo.

purpose: create or check the venv the static RE tools run in (capstone 5.0.6 and pefile 2024.8.26, each wheel checked against a pinned sha256 before install, nothing vendored); prints the venv's python path
usage: python3 discovery/re_env.py <dir> [--check]   (e.g. a scratch folder outside the repo; then run <dir>/venv/Scripts/python -I discovery/console_cmds.py ...)
when: before any static RE of a game exe (J15 console, J9 engine sites); --check to see the venv is the pinned one
not-a-verb: sets up a local tool environment outside the repo (D30), no registry or game file is touched

Wheels are downloaded by pip into <dir>/wheels with --no-deps, then each file's sha256 must equal the pin before
`pip install --no-index`. A platform without a pinned wheel is refused (add its hash here; never install unpinned).
"""
import argparse
import hashlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

PINS = {
    'capstone==5.0.6': {
        'capstone-5.0.6-py3-none-win_amd64.whl':
            '761c3deae00b22ac697081cdae1383bb90659dd0d79387a09cf5bdbb22b17064',
        'capstone-5.0.6-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl':
            '0358855773100bb91ae6681fabce7299df83156945ba943f6211061a592c54a6',
    },
    'pefile==2024.8.26': {
        'pefile-2024.8.26-py3-none-any.whl':
            '76f8b485dcd3b1bb8166f1128d395fa3d87af26360c2358fb75b80019b957c6f',
    },
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def venv_python(d):
    return os.path.join(d, 'venv', 'Scripts' if os.name == 'nt' else 'bin', 'python' + ('.exe' if os.name == 'nt' else ''))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('dir')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    if os.path.abspath(a.dir).startswith(os.path.abspath(paths.REPO)):
        sys.exit('refused: the RE environment lives outside the repo (D30)')
    py = venv_python(a.dir)
    wheels = os.path.join(a.dir, 'wheels')
    if not a.check:
        os.makedirs(wheels, exist_ok=True)
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps', '--only-binary=:all:', '-d', wheels] + list(PINS),
                       check=True)
        good = []
        for spec, files in PINS.items():
            have = [f for f in os.listdir(wheels) if f in files]
            if not have:
                sys.exit(f'refused: no pinned wheel of {spec} for this platform in {wheels} ({sorted(os.listdir(wheels))})')
            for f in have:
                got = sha256(os.path.join(wheels, f))
                if got != files[f]:
                    sys.exit(f'refused: {f} sha256 {got} != pin {files[f]}')
                good.append(os.path.join(wheels, f))
        if not os.path.exists(py):
            subprocess.run([sys.executable, '-m', 'venv', os.path.join(a.dir, 'venv')], check=True)
        subprocess.run([py, '-m', 'pip', 'install', '-q', '--no-index'] + good, check=True)
    r = subprocess.run([py, '-I', '-c', 'import capstone, pefile; print(capstone.__version__, pefile.__version__)'],
                       capture_output=True, text=True)
    if r.returncode or r.stdout.split() != ['5.0.6', '2024.8.26']:
        sys.exit(f'FAILED: venv at {py} is not the pinned one: {r.stdout.strip()} {r.stderr.strip()[-200:]}')
    print(py)


if __name__ == '__main__':
    main()
