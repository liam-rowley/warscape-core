#!/usr/bin/env python3
"""Read a 32-bit Windows exe and print the identity facts the proxy pins, as JSON.

purpose: print an exe's identity (sha1, PE TimeDateStamp, SizeOfImage, CheckSum, LAA/ASLR/NX flags, sections, DRM stub signs) its d3d9.dll imports (and any other DLL's with --imports: which hooks an IAT slot can reach), and check that the proxy's d3d9.def exports cover them
usage: python3 proxy/tools/exe_info.py <game.exe> [--def [d3d9.def]] [--identity [identity.json]] [--imports user32.dll ...]   (a flag with no value takes layout.py's default: the core's proxy/src/d3d9.def, the game's proxy adapter identity.json)
when: to re-check the target exe before pinning it or after a Steam update (runs in Git Bash on the PC against the game folder, or anywhere on a copy); exit 1 when the identity file or the def file disagrees
not-a-verb: a standalone stdlib reader of one exe that also runs on a copy of the exe away from the repo (whether it becomes a verb: J20 report)
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout.py beside this file


def parse_pe(b):
    if b[:2] != b'MZ':
        raise ValueError('no MZ header')
    lfanew = struct.unpack_from('<I', b, 0x3C)[0]
    if b[lfanew:lfanew + 4] != b'PE\0\0':
        raise ValueError('no PE signature')
    machine, nsec, tds = struct.unpack_from('<HHI', b, lfanew + 4)
    opt_size, chars = struct.unpack_from('<HH', b, lfanew + 20)
    opt = lfanew + 24
    if struct.unpack_from('<H', b, opt)[0] != 0x10B:
        raise ValueError('not PE32')
    entry = struct.unpack_from('<I', b, opt + 16)[0]
    image_base = struct.unpack_from('<I', b, opt + 28)[0]
    size_of_image, size_of_headers, checksum = struct.unpack_from('<III', b, opt + 56)
    dll_chars = struct.unpack_from('<H', b, opt + 70)[0]
    ndirs = struct.unpack_from('<I', b, opt + 92)[0]
    dirs = [struct.unpack_from('<II', b, opt + 96 + 8 * i) for i in range(min(ndirs, 16))]
    secs = []
    sh = opt + opt_size
    for i in range(nsec):
        name = b[sh:sh + 8].rstrip(b'\0').decode('latin-1')
        vsize, va, rsize, roff = struct.unpack_from('<IIII', b, sh + 8)
        sc = struct.unpack_from('<I', b, sh + 36)[0]
        secs.append({'name': name, 'rva': va, 'vsize': vsize, 'raw_off': roff, 'raw_size': rsize, 'characteristics': sc})
        sh += 40
    return {'machine': machine, 'time_date_stamp': tds, 'characteristics': chars, 'entry_rva': entry, 'image_base': image_base,
            'size_of_image': size_of_image, 'size_of_headers': size_of_headers, 'checksum': checksum, 'dll_characteristics': dll_chars,
            'dirs': dirs, 'sections': secs}


def rva_to_off(pe, rva):
    for s in pe['sections']:
        if s['rva'] <= rva < s['rva'] + max(s['vsize'], s['raw_size']):
            return s['raw_off'] + (rva - s['rva'])
    return rva if rva < pe['size_of_headers'] else None


def cstr(b, off):
    return b[off:b.index(b'\0', off)].decode('latin-1')


def imports(b, pe):
    out = {}
    rva, size = pe['dirs'][1] if len(pe['dirs']) > 1 else (0, 0)
    if not rva:
        return out
    off = rva_to_off(pe, rva)
    while True:
        oft, _, _, name_rva, ft = struct.unpack_from('<IIIII', b, off)
        if not name_rva:
            break
        dll = cstr(b, rva_to_off(pe, name_rva)).lower()
        names, t = [], rva_to_off(pe, oft or ft)
        while True:
            v = struct.unpack_from('<I', b, t)[0]
            if not v:
                break
            names.append(f'#{v & 0xFFFF}' if v & 0x80000000 else cstr(b, rva_to_off(pe, v) + 2))
            t += 4
        out[dll] = names
        off += 20
    return out


def def_exports(path):
    names, on = [], False
    for line in Path(path).read_text().splitlines():
        s = line.split(';')[0].strip()
        if s.upper() == 'EXPORTS':
            on = True
        elif on and s:
            names.append(s.split()[0].split('=')[0])
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('exe')
    ap.add_argument('--def', dest='deffile', nargs='?', const='auto', help='check the d3d9 imports against this def file (no value: proxy/src/d3d9.def)')
    ap.add_argument('--identity', nargs='?', const='auto', help='compare with this identity file (no value: the proxy adapter identity.json)')
    ap.add_argument('--imports', nargs='+', default=[], metavar='DLL', help='also list the functions imported from these DLLs')
    a = ap.parse_args()
    if 'auto' in (a.deffile, a.identity):
        import layout   # the two game defaults come from layout.py (W4); needed only for a flag without a value
        if a.deffile == 'auto':
            a.deffile = str(layout.proxy_src() / 'd3d9.def')
        if a.identity == 'auto':
            a.identity = str(layout.proxy_adapter() / 'identity.json')
    b = Path(a.exe).read_bytes()
    pe = parse_pe(b)
    dc = pe['dll_characteristics']
    imp = imports(b, pe)
    code = [s for s in pe['sections'] if s['characteristics'] & 0x20000000]
    info = {
        'file': a.exe, 'size': len(b), 'sha1': hashlib.sha1(b).hexdigest(), 'sha256': hashlib.sha256(b).hexdigest(),
        'machine': hex(pe['machine']), 'time_date_stamp': f"0x{pe['time_date_stamp']:08x}", 'size_of_image': f"0x{pe['size_of_image']:08x}",
        'checksum': f"0x{pe['checksum']:08x}", 'image_base': f"0x{pe['image_base']:08x}", 'entry_rva': f"0x{pe['entry_rva']:08x}",
        'large_address_aware': bool(pe['characteristics'] & 0x20), 'aslr': bool(dc & 0x40), 'nx': bool(dc & 0x100),
        'has_relocs': bool(pe['dirs'][5][0]) if len(pe['dirs']) > 5 else False,
        'sections': [f"{s['name']} rva=0x{s['rva']:x} vsize=0x{s['vsize']:x} raw=0x{s['raw_size']:x} ch=0x{s['characteristics']:08x}" for s in pe['sections']],
        'drm_stub_signs': [s['name'] for s in pe['sections'] if s['name'] == '.bind'] +
                          (['entry point outside the first code section'] if code and not (code[0]['rva'] <= pe['entry_rva'] < code[0]['rva'] + code[0]['vsize']) else []),
        'd3d9_imports': imp.get('d3d9.dll', []),
        'import_dlls': sorted(imp),
    }
    for dll in a.imports:
        info[f'imports_{dll.lower()}'] = sorted(imp.get(dll.lower(), []))
    bad = []
    if a.deffile:
        exp = set(def_exports(a.deffile))
        missing = [n for n in info['d3d9_imports'] if n not in exp]
        info['def_missing'] = missing
        bad += [f'd3d9.def does not export {n}' for n in missing]
    if a.identity:
        want = json.loads(Path(a.identity).read_text())
        for k in ('sha1', 'time_date_stamp', 'size_of_image'):
            if want.get(k) and str(want[k]).lower() != str(info[k]).lower():
                bad.append(f'{k}: exe {info[k]}, identity file {want[k]}')
    info['problems'] = bad
    print(json.dumps(info, indent=2))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
