#!/usr/bin/env python3
"""Fetch the pinned stock DXVK release and extract its 32-bit d3d9.dll (renamed d3d9_dxvk.dll) and licence, sha-checked.

purpose: download the pinned stock DXVK release tarball, verify its sha256, extract x32/d3d9.dll as d3d9_dxvk.dll plus DXVK's LICENSE, and verify both
usage: python3 proxy/tools/fetch_dxvk.py [--out build/dxvk] [--print-pin]
when: before kitting the proxy for the PC (pc_deploy.py kit runs it); to move to a newer DXVK change PIN below (version, URLs, three sha256) in its own commit
not-a-verb: needs network and writes build output, not a registry operation; pc_deploy.py and agents call it directly
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
# Stock DXVK, latest stable release when pinned (2026-10-28: tags v3.0 .. v3.1.1, no newer). Never a fork (proxy job decision).
PIN = {
    'version': '3.1.1',
    'tarball_url': 'https://github.com/doitsujin/dxvk/releases/download/v3.1.1/dxvk-3.1.1.tar.gz',
    'tarball_sha256': '40565b4a724aadc4433fa4e010b4b23916d9b1f1baeee64e17186db94f54e608',
    'member': 'dxvk-3.1.1/x32/d3d9.dll',
    'd3d9_sha256': '265888c31ca78dffa290c39cb7e50bfb02762590e41927906e46fb32f01497fa',
    'license_url': 'https://raw.githubusercontent.com/doitsujin/dxvk/v3.1.1/LICENSE',
    'license_sha256': 'a5cb1a6ded7d2d7e92d550ba28edd21be2d1d4044662b399887351023e30ce64',
}


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def get(url, want):
    with urllib.request.urlopen(url, timeout=120) as r:
        b = r.read()
    if sha256(b) != want:
        raise SystemExit(f'fetch_dxvk: {url} has sha256 {sha256(b)}, pinned {want}: refusing')
    return b


def fetch(out):
    out = Path(out)
    dll, lic = out / 'd3d9_dxvk.dll', out / 'LICENSE.dxvk.txt'
    if dll.exists() and sha256(dll.read_bytes()) == PIN['d3d9_sha256'] and lic.exists() and sha256(lic.read_bytes()) == PIN['license_sha256']:
        print(f'fetch_dxvk: DXVK {PIN["version"]} already in {out} (sha256 ok)')
        return dll, lic
    out.mkdir(parents=True, exist_ok=True)
    tb = get(PIN['tarball_url'], PIN['tarball_sha256'])
    with tarfile.open(fileobj=io.BytesIO(tb), mode='r:gz') as t:
        b = t.extractfile(PIN['member']).read()
    if sha256(b) != PIN['d3d9_sha256']:
        raise SystemExit(f'fetch_dxvk: {PIN["member"]} has sha256 {sha256(b)}, pinned {PIN["d3d9_sha256"]}: refusing')
    dll.write_bytes(b)
    lic.write_bytes(get(PIN['license_url'], PIN['license_sha256']))
    print(f'fetch_dxvk: DXVK {PIN["version"]} -> {dll} ({len(b)} bytes, sha256 {PIN["d3d9_sha256"][:12]}) + {lic.name}')
    return dll, lic


def main():
    ap = argparse.ArgumentParser(description='fetch the pinned stock DXVK d3d9.dll')
    ap.add_argument('--out', default=str(ROOT / 'build' / 'dxvk'))
    ap.add_argument('--print-pin', action='store_true')
    a = ap.parse_args()
    if a.print_pin:
        for k, v in PIN.items():
            print(f'{k}: {v}')
        return 0
    fetch(a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
