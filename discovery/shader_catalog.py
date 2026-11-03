#!/usr/bin/env python3
"""Runtime shader catalogue and frame anatomy from the proxy's frame captures (J8).

purpose: turn frame captures (proxy dev.capture: <capture_dir>\\<name>\\frame.txt and shaders\\<hash>.vs|ps) into committed per-capture summaries (passes, render targets, shader use, constant uploads), the shader bytecode and its disassembly, the fx source and technique of each shader (compiled from the game's own fx sources with the game's compiler version), the catalogue <adapter>/shader_catalog.json and the generated tables of <adapter>/frame_anatomy.md
usage: python3 discovery/shader_catalog.py import --run <run id> [--captures DIR (default: games.json <target>.captures)] [--name N ...] | fxmap [--fx extract/<target>/data/fx] [--work DIR] | build [--check] | hash <file>   (import and fxmap need Windows: D3DCompiler_47 and d3dx9_40 from System32; build --check runs anywhere)
when: after captures on the PC (import), after a game update or a new capture (fxmap, build); `build --check` in the tests gate keeps the catalogue and the anatomy tables in step with their inputs
not-a-verb: reads PC captures and calls Windows D3D DLLs, outside the wsc registry operations

Disassembler: D3DDisassemble from %SystemRoot%\\System32\\D3DCompiler_47.dll (64-bit, the host Python's bitness; present on every
Windows 10/11, nothing downloaded). It reads shader model 1-3 bytecode; the text is only for reading, so its version need not match the
game's compiler. The fx mapping must match it exactly: the captured CTABs name "Microsoft (R) HLSL Shader Compiler 9.24.950.2656",
the version of d3dx9_40.dll (System32 64-bit; the game itself loads the 32-bit debug build D3dx9d_40.dll of the same release), so the
fx sources are compiled with D3DXCreateEffectCompilerFromFileW + ID3DXEffectCompiler::CompileEffect and a shader maps to a source and
technique only when its hash is byte-identical (no name heuristics).
Hash convention: canonical FNV-1a-64 over the bytecode up to and including the walked end token, the same as the core's capture.h
(test vectors shared with proxy/tests/test_capture.cpp).
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

ROOT = Path(paths.REPO)
SHADERS = Path(paths.adapter_file('shaders'))
CATALOG = Path(paths.adapter_file('shader_catalog.json'))
ANATOMY = Path(paths.adapter_file('frame_anatomy.md'))
RUNS = ROOT / 'harness' / 'runs'

# ---- hash and bytecode ------------------------------------------------------------------------------------------------------
FNV_BASIS, FNV_PRIME = 14695981039346656037, 1099511628211


def fnv1a64(b):
    h = FNV_BASIS
    for x in b:
        h = ((h ^ x) * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def shader_length(b):
    """Bytes up to and including the end token, walked as capture.h ShaderLength does; 0 when not a SM1-3 stream."""
    n = len(b) // 4
    if n < 2:
        return 0
    t = struct.unpack_from('<%dI' % n, b)
    ver = t[0]
    if ver & 0xFFFE0000 != 0xFFFE0000:
        return 0
    major = (ver >> 8) & 0xFF
    if not 1 <= major <= 3:
        return 0
    i = 1
    while i < n:
        tok = t[i]
        if tok == 0x0000FFFF:
            return (i + 1) * 4
        op = tok & 0xFFFF
        if op == 0xFFFE:
            i += 1 + ((tok >> 16) & 0x7FFF)
        elif major >= 2:
            i += 1 + ((tok >> 24) & 0x0F)
        elif op == 0x51:
            i += 6
        else:
            i += 1
            while i < n and t[i] & 0x80000000:
                i += 1
    return 0


def shader_hash(b):
    n = shader_length(b)
    return '%016x' % fnv1a64(b[:n] if n else b), n


def comments(b):
    """{fourcc: bytes} of the leading comment blocks (CTAB, PRES, ...)."""
    out, n = {}, len(b) // 4
    t = struct.unpack_from('<%dI' % n, b)
    i = 1
    while i < n and t[i] & 0xFFFF == 0xFFFE:
        ln = (t[i] >> 16) & 0x7FFF
        if ln:
            out.setdefault(b[(i + 1) * 4:(i + 2) * 4].decode('latin1'), b[(i + 2) * 4:(i + 1 + ln) * 4])
        i += 1 + ln
    return out


REGSET = {0: 'b', 1: 'i', 2: 'c', 3: 's'}


def ctab(b):
    """The constant table: {creator, target, flags, constants: [{name, reg, count, set}]}; None without a CTAB."""
    d = comments(b).get('CTAB')
    if not d:
        return None
    sz, cr, ver, nc, ci, fl, tg = struct.unpack_from('<7I', d)
    cstr = lambda o: d[o:d.index(b'\0', o)].decode('latin1')
    consts = []
    for k in range(nc):
        name, rset, ridx, rcnt, _, tinfo, dflt = struct.unpack_from('<IHHHHII', d, ci + 20 * k)
        consts.append({'name': cstr(name), 'reg': f'{REGSET.get(rset, "?")}{ridx}', 'set': REGSET.get(rset, '?'), 'index': ridx, 'count': rcnt})
    return {'creator': cstr(cr), 'target': cstr(tg), 'flags': fl, 'constants': consts}


def version(b):
    v = struct.unpack_from('<I', b)[0]
    return ('ps' if v >> 16 == 0xFFFF else 'vs') + f'_{(v >> 8) & 0xFF}_{v & 0xFF}'


# ---- Windows DLL calls (ctypes, COM vtables) -----------------------------------------------------------------------------------
def _win():
    import ctypes
    from ctypes import wintypes
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        sys.exit('shader_catalog: import and fxmap need 64-bit Python on Windows (System32 D3D DLLs)')
    return ctypes, wintypes


def _vcall(ctypes, obj, slot, restype, argtypes=(), *args):
    """COM method `slot` of `obj` (this first), with explicit argument types."""
    vt = ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0]
    fn = ctypes.cast(vt, ctypes.POINTER(ctypes.c_void_p))[slot]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(fn)(obj, *args)


def _blob(ctypes, p):
    if not p:
        return b''
    ptr = _vcall(ctypes, p, 3, ctypes.c_void_p)
    n = _vcall(ctypes, p, 4, ctypes.c_size_t)
    data = ctypes.string_at(ptr, n)
    _vcall(ctypes, p, 2, ctypes.c_ulong)
    return data


def disassemble(code):
    ctypes, _ = _win()
    dll = ctypes.WinDLL(os.path.join(os.environ['SystemRoot'], 'System32', 'D3DCompiler_47.dll'))
    out = ctypes.c_void_p()
    hr = dll.D3DDisassemble(ctypes.c_char_p(code), ctypes.c_size_t(len(code)), ctypes.c_uint(0), None, ctypes.byref(out))
    if hr & 0x80000000:
        return f'; D3DDisassemble failed 0x{hr & 0xFFFFFFFF:08x}\n'
    return _blob(ctypes, out.value).rstrip(b'\0').decode('latin1').replace('\r\n', '\n')


def compile_effect(path, macros, flags=0x1000):
    """Effect binary (fx_2_0) of one fx file, or (None, errors)."""
    ctypes, _ = _win()
    dll = ctypes.WinDLL(os.path.join(os.environ['SystemRoot'], 'System32', 'd3dx9_40.dll'))

    class Macro(ctypes.Structure):
        _fields_ = [('Name', ctypes.c_char_p), ('Definition', ctypes.c_char_p)]
    arr = (Macro * (len(macros) + 1))(*[Macro(k.encode(), v.encode()) for k, v in macros], Macro(None, None))
    comp, err = ctypes.c_void_p(), ctypes.c_void_p()
    hr = dll.D3DXCreateEffectCompilerFromFileW(ctypes.c_wchar_p(str(path)), arr, None, ctypes.c_uint(flags), ctypes.byref(comp), ctypes.byref(err))
    if hr & 0x80000000:
        return None, _blob(ctypes, err.value).decode('latin1', 'replace')
    eff, err2 = ctypes.c_void_p(), ctypes.c_void_p()
    pp = ctypes.POINTER(ctypes.c_void_p)
    hr = _vcall(ctypes, comp.value, 59, ctypes.c_long, (ctypes.c_uint, pp, pp), flags, ctypes.byref(eff), ctypes.byref(err2))
    _vcall(ctypes, comp.value, 2, ctypes.c_ulong)
    if hr & 0x80000000:
        return None, _blob(ctypes, err2.value).decode('latin1', 'replace')
    return _blob(ctypes, eff.value), ''


def streams_in(blob):
    """Every shader token stream inside an effect binary: {hash: bytes}. A stream starts at a version token and walks to its end token."""
    out = {}
    for o in range(0, len(blob) - 8, 4):
        v = struct.unpack_from('<I', blob, o)[0]
        if v & 0xFFFE0000 == 0xFFFE0000 and 2 <= (v >> 8) & 0xFF <= 3 and v & 0xFF in (0, 1, 0xFF) and v != 0xFFFFFFFF:
            n = shader_length(blob[o:])
            if n and struct.unpack_from('<I', blob, o + 4)[0] & 0xFFFF == 0xFFFE:   # D3DX output always starts with a comment (CTAB)
                h, _ = shader_hash(blob[o:o + n])
                out[h] = blob[o:o + n]
    return out


# ---- frame.txt -> summary ------------------------------------------------------------------------------------------------------
FMT = {21: 'A8R8G8B8', 22: 'X8R8G8B8', 23: 'R5G6B5', 25: 'A1R5G5B5', 26: 'A4R4G4B4', 28: 'A8', 31: 'A2B10G10R10', 32: 'A8B8G8R8',
       34: 'G16R16', 35: 'A2R10G10B10', 36: 'A16B16G16R16', 50: 'L8', 51: 'A8L8', 70: 'D16_LOCKABLE', 71: 'D32', 75: 'D24S8', 77: 'D24X8',
       80: 'D16', 111: 'R16F', 112: 'G16R16F', 113: 'A16B16G16R16F', 114: 'R32F', 115: 'G32R32F', 116: 'A32B32G32R32F'}


def fmt_name(f):
    f = int(f)
    if f in FMT:
        return FMT[f]
    if f > 0xFFFF:
        s = struct.pack('<I', f).decode('latin1')
        if s.isprintable():
            return s
    return str(f)


USAGE_RT, USAGE_DS = 0x1, 0x2
PRIM = {1: 'points', 2: 'lines', 3: 'linestrip', 4: 'tris', 5: 'tristrip', 6: 'trifan'}
RS_NAMES = {7: 'zenable', 14: 'zwrite', 15: 'alphatest', 19: 'srcblend', 20: 'destblend', 22: 'cull', 23: 'zfunc', 27: 'alphablend',
            52: 'stencil', 168: 'colorwrite', 174: 'scissor', 175: 'slope_bias', 194: 'srgbwrite', 195: 'depth_bias'}


def prims(kind, args):
    if kind == 'DIP':
        return int(args[5])
    if kind == 'DP':
        return int(args[2])
    if kind == 'DPUP':
        return int(args[1])
    return int(args[3])   # DIPUP


def summarize(path, ctabs):
    """One capture's frame.txt -> a summary dict. `ctabs` maps a shader hash to its CTAB (for the per-shader constant values)."""
    surf, tex, ids, counts = {}, {}, {}, Counter()
    def sid(p, kind):
        if p in ('0', None):
            return None
        if p not in ids:
            counts[kind] += 1
            ids[p] = f'{kind}{counts[kind]}'
        return ids[p]
    header, backbuffer = '', None
    st = {'rt': [None] * 4, 'ds': None, 'vs': None, 'ps': None, 'tex': {}, 'rs': {}, 'vp': None}
    vc, pc = {}, {}
    passes, events, draws_total, ev_stack = [], [], 0, []
    shaders = defaultdict(lambda: {'draws': 0, 'prims': 0, 'passes': set(), 'pairs': Counter(), 'consts': None})
    cur = None
    in_state = False
    def new_pass(reason):
        nonlocal cur
        cur = {'index': len(passes), 'rt': [r for r in st['rt']], 'ds': st['ds'], 'clear': None, 'draws': 0, 'prims': 0, 'reason': reason,
               'pairs': Counter(), 'reads': Counter(), 'events': [e for e in ev_stack], 'states': Counter(), 'viewport': st['vp']}
        passes.append(cur)
    lines = (gzip.open if str(path).endswith('.gz') else open)(path, 'rt', encoding='latin1')
    for line in lines:
        a = line.split()
        if not a:
            continue
        k = a[0]
        if k == 'CAPTURE':
            header = line.strip()
        elif k == 'STATE':
            in_state = True
        elif k == 'ENDSTATE':
            in_state = False
        elif k == 'SURF':
            surf[a[1]] = {'w': int(a[2]), 'h': int(a[3]), 'fmt': fmt_name(a[4]), 'usage': int(a[5], 16), 'pool': int(a[6]), 'ms': int(a[7]),
                          'container': a[9] if len(a) > 9 and a[9] != '0' else None} if a[2] != '?' else {}
        elif k == 'TEX':
            d = {'type': {3: '2d', 4: 'volume', 5: 'cube'}.get(int(a[2]), a[2]), 'levels': int(a[3])}
            if len(a) >= 10:
                d.update({'w': int(a[4]), 'h': int(a[5]), 'd': int(a[6]), 'fmt': fmt_name(a[7]), 'usage': int(a[8], 16), 'pool': int(a[9])})
            tex[a[1]] = d
        elif k == 'BACKBUFFER':
            backbuffer = a[1]
        elif k == 'RT':
            st['rt'][int(a[1])] = a[2] if a[2] != '0' else None
            if not in_state:
                cur = None
        elif k == 'DS':
            st['ds'] = a[1] if a[1] != '0' else None
            if not in_state:
                cur = None
        elif k in ('VS', 'PS'):
            st[k.lower()] = a[1] if a[1] != '0000000000000000' else None
        elif k == 'T':
            st['tex'][int(a[1])] = a[2] if a[2] != '0' else None
        elif k == 'RS':
            st['rs'][int(a[1])] = int(a[2], 16)
        elif k == 'VP':
            st['vp'] = [int(x) for x in a[1:5]] if len(a) > 4 else None
        elif k in ('VC', 'PC'):
            reg, cnt = int(a[1]), int(a[2])
            vals = [float(x) for x in a[3:]]
            file = vc if k == 'VC' else pc
            for i in range(cnt):
                file[reg + i] = vals[i * 4:i * 4 + 4]
        elif k == 'CLEAR':
            if cur is None or cur['draws']:
                new_pass('clear')
            cur['clear'] = {'flags': int(a[2], 16), 'color': a[3], 'z': float(a[4]), 'stencil': int(a[5])}
        elif k in ('STRETCH', 'UPDSURF', 'READBACK', 'FILL'):
            passes.append({'index': len(passes), 'op': k.lower(), 'src': a[1], 'dst': a[6] if k == 'STRETCH' else a[2] if k != 'FILL' else a[1],
                           'events': [e for e in ev_stack]})
            cur = None
        elif k == 'EVENT':
            ev_stack.append(line.strip()[6:])
            events.append({'name': line.strip()[6:], 'pass': len(passes)})
            cur = None
        elif k == 'EVENTEND':
            if ev_stack:
                ev_stack.pop()
            cur = None
        elif k in ('DP', 'DIP', 'DPUP', 'DIPUP'):
            if cur is None:
                new_pass('bind')
            p = prims(k, a[1:])
            pair = f"{st['vs'] or '-'}/{st['ps'] or '-'}"
            cur['draws'] += 1; cur['prims'] += p; cur['pairs'][pair] += 1; draws_total += 1
            rs = st['rs']
            cur['states'][f"z{rs.get(7, 0)}{rs.get(14, 0)} cw{rs.get(168, 15):x} blend{rs.get(27, 0)} cull{rs.get(22, 0)}"] += 1
            for stage, t in st['tex'].items():
                if t:
                    cur['reads'][(stage, t)] += 1
            for kind, h, file in (('vs', st['vs'], vc), ('ps', st['ps'], pc)):
                if not h:
                    continue
                s = shaders[h]
                s['draws'] += 1; s['prims'] += p; s['passes'].add(cur['index']); s['pairs'][pair] += 1
                if s['consts'] is None and h in ctabs:
                    s['consts'] = {c['name']: [file.get(c['index'] + i) for i in range(min(c['count'], 8))]
                                   for c in ctabs[h]['constants'] if c['set'] == 'c'}
    # stable names: surfaces and textures by first appearance; render-target textures named by their surface
    cont = {d.get('container'): p for p, d in surf.items() if d.get('container')}
    def sname(p):
        return sid(p, 'rt') if p else None
    def tname(p):
        return f"{sid(cont[p], 'rt')}" if p in cont else sid(p, 'tex')
    def desc_s(p):
        d = surf.get(p, {})
        return {'id': sname(p), 'w': d.get('w'), 'h': d.get('h'), 'fmt': d.get('fmt'), 'ms': d.get('ms'), 'texture': bool(d.get('container')),
                'backbuffer': p == backbuffer} if p else None
    out_passes = []
    producer = {}
    for ps in passes:
        if 'op' in ps:
            out_passes.append({'index': ps['index'], 'op': ps['op'], 'src': sname(ps['src']) if ps['src'] in surf else tname(ps['src']),
                               'dst': sname(ps['dst']) if ps['dst'] in surf else tname(ps['dst']), 'events': ps['events']})
            continue
        if not ps['draws'] and not ps['clear']:
            continue
        reads = sorted({(st_, tname(t)) for (st_, t) in ps['reads']}, key=lambda x: (x[0], x[1] or ''))
        rec = {'index': ps['index'], 'rt': [desc_s(r) for r in ps['rt'] if r], 'ds': desc_s(ps['ds']), 'clear': ps['clear'], 'draws': ps['draws'],
               'prims': ps['prims'], 'events': ps['events'], 'viewport': ps['viewport'],
               'pairs': dict(ps['pairs'].most_common()), 'states': dict(ps['states'].most_common(4)),
               'reads_rt': sorted({f's{s}:{n}' for s, n in reads if n and n.startswith('rt')}),
               'reads_from_pass': sorted({producer[n] for s, n in reads if n in producer})}
        for r in ps['rt']:
            if r:
                producer[sname(r)] = ps['index']
        out_passes.append(rec)
    used = {p for ps in out_passes for p in [d['id'] for d in ps.get('rt', []) if d] + [ps['ds']['id'] if ps.get('ds') else None] if p}
    surfaces = {sname(p): {k2: v for k2, v in d.items() if k2 != 'container'} | {'texture': bool(d.get('container')), 'backbuffer': p == backbuffer}
                for p, d in surf.items() if sname(p) in used and d}
    return {'header': header, 'draws': draws_total, 'backbuffer': desc_s(backbuffer), 'surfaces': dict(sorted(surfaces.items())),
            'passes': out_passes, 'events': events,
            'shaders': {h: {'draws': s['draws'], 'prims': s['prims'], 'passes': sorted(s['passes']), 'pairs': dict(s['pairs'].most_common(6)),
                            'consts': s['consts']} for h, s in sorted(shaders.items())}}


# ---- verbs ----------------------------------------------------------------------------------------------------------------------
def load_bin():
    out = {}
    for p in sorted((SHADERS / 'bin').glob('*.*s')):
        out[p.stem] = p.read_bytes()
    return out


def cmd_import(a):
    cap = a.captures or json.load(open(paths.adapter_file('games.json'), encoding='utf-8'))[paths.TARGET].get('captures')
    if not cap:
        sys.exit('shader_catalog import: pass --captures DIR or set "captures" in the target entry of games.json')
    src = Path(cap)
    (SHADERS / 'bin').mkdir(parents=True, exist_ok=True); (SHADERS / 'asm').mkdir(parents=True, exist_ok=True)
    new = 0
    for p in sorted((src / 'shaders').glob('*.*s')):
        b = p.read_bytes()
        h, n = shader_hash(b)
        if h != p.stem:
            sys.exit(f'shader_catalog: {p.name} hashes to {h}: the capture and this tool disagree on the convention')
        dst = SHADERS / 'bin' / p.name
        if not dst.exists():
            dst.write_bytes(b); new += 1
        asm = SHADERS / 'asm' / (p.name + '.asm')
        if not asm.exists():
            asm.write_text(disassemble(b), encoding='utf-8', newline='\n')
    ctabs = {h: ctab(b) for h, b in load_bin().items()}
    outdir = RUNS / a.run / 'captures'
    outdir.mkdir(parents=True, exist_ok=True)
    names = a.name or sorted(d.name for d in src.iterdir() if (d / 'frame.txt').exists())
    for name in names:
        f = src / name / 'frame.txt'
        s = summarize(f, ctabs)
        s['raw'] = {'file': str(f), 'bytes': f.stat().st_size, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
        (outdir / f'{name}.json').write_text(json.dumps(s, indent=1) + '\n', encoding='utf-8', newline='\n')
        print(f'import: {name}: {s["draws"]} draws, {len(s["passes"])} passes, {len(s["shaders"])} shaders')
    print(f'import: {new} new shaders, {len(ctabs)} in {SHADERS.relative_to(ROOT).as_posix()}/bin')


def techniques(text):
    """[(name, start, end)] of each technique block (brace-matched)."""
    out = []
    for m in re.finditer(r'^\s*technique\d*\s+([A-Za-z_]\w*)', text, re.M):
        i = text.find('{', m.end())
        if i < 0:
            continue
        depth, j = 0, i
        while j < len(text):
            depth += {'{': 1, '}': -1}.get(text[j], 0)
            if depth == 0:
                break
            j += 1
        out.append((m.group(1), m.start(), j + 1))
    return out


# Engine macros: the names are the exe's own strings (the game's engine fact shaders.macros), the values follow the PC's prefs, which the
# acceptance baseline and every ctl.py capture use (gfx_hdr, gfx_ssao, gfx_distortion, gfx_depth_of_field, gfx_hardware_shadows false;
# gfx_gamma_setting 2; gfx_texture_filtering 1). A shader maps only on a byte-identical hash, so a wrong guess never maps anything: the
# variants each change one macro from the base, and the profile that mapped a shader is recorded with it.
BASE = [('ENABLE_DEPTH', ''), ('DEPTH_BUFFER_FORMAT_INTZ', ''), ('DEPTH_PASS_COLORWRITEENABLE', '0'), ('DEPTH_PRE_PASS', ''),
        ('GAMMA_CORRECT_TEXTURE', 'false'), ('GAMMA_VALUE', '2.00'), ('SOFTWARE_SHADOWS', ''), ('ENABLE_SHADOWS', ''),
        ('MAG_FILTER', 'LINEAR'), ('MIP_FILTER', 'LINEAR'), ('MIN_FILTER', 'LINEAR'), ('FILTER_MAX_ANISOTROPY', '0'),
        ('BORDER_ADDRESS_SUPPORT', ''), ('NVIDIA_GPU', ''), ('MRT_SUPPORT', ''), ('ENABLE_REFLECTION', ''), ('ENABLE_REFRACTION', '')]
TOGGLES = ['ENABLE_DEPTH', 'DEPTH_PRE_PASS', 'ENABLE_HDR', 'ENABLE_SSAO', 'ENABLE_DEPTH_OF_FIELD', 'ENABLE_DISTORTION', 'ENABLE_SHADOWS',
           'BORDER_ADDRESS_SUPPORT', 'NVIDIA_GPU', 'MRT_SUPPORT', 'LOW_QUALITY_SHADERS', 'ENABLE_REFLECTION', 'ENABLE_REFRACTION',
           'ENABLE_OFFSCREEN_PARTICLES']
VALUES = {'DEPTH_PASS_COLORWRITEENABLE': ['RED', '15'], 'GAMMA_VALUE': ['2.20', '1.00'], 'GAMMA_CORRECT_TEXTURE': ['true'],
          'MIN_FILTER': ['ANISOTROPIC', 'POINT'], 'MAG_FILTER': ['POINT'], 'MIP_FILTER': ['POINT'], 'FILTER_MAX_ANISOTROPY': ['16', '1']}
SWAPS = {'shadows_nvidia': ('SOFTWARE_SHADOWS', 'NVIDIA_HARDWARE_SHADOWS'), 'shadows_ati': ('SOFTWARE_SHADOWS', 'ATI_HARDWARE_SHADOWS'),
         'depth_rawz': ('DEPTH_BUFFER_FORMAT_INTZ', 'DEPTH_BUFFER_FORMAT_RAWZ'), 'gpu_ati': ('NVIDIA_GPU', 'ATI_GPU')}


def profile_variants():
    names = [n for n, _ in BASE]
    out = {'base': BASE}
    for t in TOGGLES:
        out[('-' if t in names else '+') + t] = [m for m in BASE if m[0] != t] if t in names else BASE + [(t, '')]
    for k, vs in VALUES.items():
        for v in vs:
            out[f'{k}={v}'] = [(n, v if n == k else d) for n, d in BASE]
    for label, (old, new) in SWAPS.items():
        out[label] = [(new if n == old else n, d) for n, d in BASE]
    out['shadows_off'] = [m for m in BASE if m[0] not in ('ENABLE_SHADOWS', 'SOFTWARE_SHADOWS')]   # gfx_shadow_quality 0 (J8 q0 capture)
    return out


def cmd_fxmap(a):
    fx = Path(a.fx)
    work = Path(a.work) / 'a' / 'fx'
    if work.parent.parent.exists():
        shutil.rmtree(work.parent.parent)
    shutil.copytree(fx, work)
    (work.parent.parent / 'personal_config.h').write_text('', encoding='ascii')   # fxconfig.h includes ../../personal_config.h
    want = set(load_bin())
    found = defaultdict(lambda: defaultdict(set))   # hash -> (fx, technique) -> {profiles that reproduce it}
    errors = {}
    for f in sorted(work.glob('*.fx')):
        text = f.read_text(encoding='latin1')
        techs = techniques(text)
        for prof, macros in profile_variants().items():
            blob, err = compile_effect(f, macros)
            if blob is None:
                if prof == 'base':
                    errors[f.name] = (err.replace('\0', '').strip().splitlines() or ['failed'])[0][:300]
                continue
            hits = set(streams_in(blob)) & want
            for h in hits:
                found[h][(f.name, None)].add(prof)
            fresh = {h for h in hits if not any(fx == f.name and t and prof in ps for (fx, t), ps in found[h].items())}
            if not fresh or not techs:
                continue
            for name, s, e in techs:   # name the technique: a copy with only this technique compiled
                one = text[:techs[0][1]] + text[s:e] + '\n'   # everything before the first technique, then this one alone
                tmp = f.with_name(f.stem + '__T__' + name + '.fx')
                tmp.write_text(one, encoding='latin1')
                b2, _ = compile_effect(tmp, macros)
                tmp.unlink()
                for h in set(streams_in(b2 or b'')) & hits:
                    found[h][(f.name, name)].add(prof)
        print(f'fxmap: {f.name}: {sum(1 for h in found if any(fx == f.name for fx, _ in found[h]))} shaders')
    def recs(h):
        named = {fx for fx, t in found[h] if t}
        return [{'fx': fx, 'technique': t, 'profiles': 'base' if 'base' in ps else sorted(ps)}
                for (fx, t), ps in sorted(found[h].items(), key=lambda x: (x[0][0], x[0][1] or '')) if t or fx not in named]
    found = {h: recs(h) for h in found}
    files = {p.name.lower(): p for p in work.iterdir() if p.is_file()}
    def incl(name, seen):   # every file `name` includes, transitively (case-insensitive, as the compiler on Windows)
        p = files.get(name.lower())
        if not p or name.lower() in seen:
            return seen
        seen.add(name.lower())
        for m in re.finditer(r'^\s*#\s*include\s+"([^"]+)"', p.read_text(encoding='latin1'), re.M):
            incl(Path(m.group(1)).name, seen)
        return seen
    includes = {f.name: sorted(incl(f.name, set()) - {f.name.lower()}) for f in sorted(work.glob('*.fx'))}
    out = {'compiler': 'd3dx9_40.dll (System32, 9.24.950.2656) D3DXCreateEffectCompilerFromFileW + CompileEffect, flags 0x1000',
           'profiles': {k: [f'{n}={v}' if v else n for n, v in m] for k, m in profile_variants().items()},
           'captured': len(want), 'mapped': len([h for h in want if found.get(h)]),
           'shaders': {h: found[h] for h in sorted(found) if found[h]}, 'compile_errors': errors, 'includes': includes}
    (SHADERS / 'fxmap.json').write_text(json.dumps(out, indent=1) + '\n', encoding='utf-8', newline='\n')
    print(f'fxmap: {out["mapped"]} of {out["captured"]} captured shaders map to a source')


def classify(entry):
    fx = (entry.get('fx') or [{}])[0].get('fx', '') if entry.get('fx') else ''
    names = ' '.join(c['name'] for c in (entry.get('ctab') or {}).get('constants', [])).lower()
    tech = ' '.join((r.get('technique') or '') for r in entry.get('fx') or []).lower()
    rules = [('shadow_caster', lambda: 'shadow' in tech and 'cast' in tech or 'shadow_map_projection_matrix' in names and 'texture_transform' not in names),
             ('ui', lambda: fx.lower().startswith(('ui', 'gui', 'flash', 'font')) or 'ui' == tech),
             ('post', lambda: fx.lower().startswith(('hdr', 'bloom', 'blur', 'high_pass', 'passthrough', 'screen', 'dof', 'terrain_ao', 'lenseflare'))),
             ('sky', lambda: fx.lower().startswith(('sky', 'cloud'))), ('water', lambda: fx.lower().startswith(('sea', 'water', 'river', 'shipwake'))),
             ('terrain', lambda: fx.lower().startswith('terrain')), ('vegetation', lambda: fx.lower().startswith(('vegetation', 'grass', 'tree', 'speedtree'))),
             ('unit', lambda: fx.lower().startswith(('variantmesh', 'weighted'))), ('sprite', lambda: 'sprite' in fx.lower() or 'imposter' in fx.lower()),
             ('particle', lambda: fx.lower().startswith(('particle', 'ribbon'))), ('rigid', lambda: fx.lower().startswith('rigid'))]
    for name, test in rules:
        try:
            if test():
                return name
        except Exception:
            pass
    return 'unmapped' if not fx else Path(fx).stem.lower()


def catalog_doc():
    bins = load_bin()
    fxmap = json.loads((SHADERS / 'fxmap.json').read_text(encoding='utf-8')) if (SHADERS / 'fxmap.json').exists() else {'shaders': {}}
    seen = defaultdict(list)
    caps = sorted(RUNS.glob('*/captures/*.json'))
    for c in caps:
        s = json.loads(c.read_text(encoding='utf-8'))
        for h, u in s['shaders'].items():
            seen[h].append({'capture': f'{c.parent.parent.name}/{c.stem}', 'draws': u['draws'], 'passes': u['passes']})
    shaders = {}
    for h, b in sorted(bins.items()):
        ct = ctab(b) or {}
        e = {'stage': version(b)[:2], 'model': version(b), 'size': len(b), 'preshader': 'PRES' in comments(b),
             'fx': fxmap['shaders'].get(h, []), 'ctab': {'flags': ct.get('flags'), 'constants': ct.get('constants', [])},
             'samplers': {c['name']: c['reg'] for c in ct.get('constants', []) if c['set'] == 's'}, 'seen': seen.get(h, [])}
        e['class'] = classify(e)
        shaders[h] = e
    flagged = ['sprite.fx', 'variantmesh.fx', 'weighted.fx', 'vegetation_billboard.fx', 'custom_sprite.fx', 'extendedsprite.fx', 'imposter.fx',
               'rigid_imposter.fx_fragment', 'shadowmap.fx_fragment']
    by_fx = defaultdict(set)
    inc = {k.lower(): v for k, v in fxmap.get('includes', {}).items()}
    for h, e in shaders.items():
        for r in e['fx']:
            by_fx[r['fx'].lower()].add(h)
            for frag in inc.get(r['fx'].lower(), []):   # a fragment counts the mapped shaders whose source includes it
                by_fx[frag].add(h)
    return {'generator': 'discovery/core/shader_catalog.py build', 'hash': 'canonical FNV-1a-64 to the walked end token (core capture.h)',
            'captures': [f'{c.parent.parent.name}/{c.stem}' for c in caps], 'count': len(shaders),
            'mapped': sum(1 for e in shaders.values() if e['fx']), 'by_class': dict(Counter(e['class'] for e in shaders.values()).most_common()),
            'flagged_sources': {f: sorted(by_fx.get(f.lower(), [])) for f in flagged}, 'shaders': shaders}


GEN = re.compile(r'(<!-- gen:(\w+) -->\n)(.*?)(<!-- /gen -->)', re.S)


def short_list(names, keep=6):
    """a capture list for a table cell: the first `keep` names and a count of the rest, so the anatomy doc stays under the doc_size cap
    as runs add captures (J9: 13 more captures took it to 31.9 KB); the full list is in each capture summary"""
    return ', '.join(names[:keep]) + (f' (+{len(names) - keep} more)' if len(names) > keep else '')


def md_table(head, rows):
    return '| ' + ' | '.join(head) + ' |\n|' + '---|' * len(head) + '\n' + ''.join('| ' + ' | '.join(str(x) for x in r) + ' |\n' for r in rows)


# ---- shadow texel density (J8 review 1, finding 4: the metric is owned here, never computed by hand) --------------------------
DENSITY_M = (20, 60, 140)


def _const(s, name):
    """The first captured value of a constant (rows of 4 floats) from any shader of a capture summary; None when absent."""
    for u in s['shaders'].values():
        v = (u.get('consts') or {}).get(name)
        if v and all(r is not None for r in v):
            return v
    return None


def _inv4(m):
    a = [list(map(float, r)) + [1.0 if i == j else 0.0 for j in range(4)] for i, r in enumerate(m)]
    for c in range(4):
        p = max(range(c, 4), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-20:
            return None
        a[c], a[p] = a[p], a[c]
        f = a[c][c]
        a[c] = [x / f for x in a[c]]
        for r in range(4):
            if r != c and a[r][c]:
                g = a[r][c]
                a[r] = [x - g * y for x, y in zip(a[r], a[c])]
    return [r[4:] for r in a]


def shadow_density(s):
    """Shadow-map texels per metre on the ground along the screen-centre view ray, or None.
    Metric: at a point P, texel(Q) = (M0.Q / M3.Q, M1.Q / M3.Q) * size / 2 with M = shadow_map_projection_matrix as uploaded (register i
    is row i: clip_i = dot(register_i, Q)) and size = shadow_map_texture_size; J = d texel / d (x, z) on the horizontal plane at P
    (central differences, 0.5 m); density = sqrt(|det J|) (texels per metre, area-equivalent). P = camera_position + d * ray for d in
    DENSITY_M, the ray through the screen centre from inverse(view_projection). Also the angle between the ray and the direction to the
    sun (-light_direction)."""
    M, VP, C = _const(s, 'shadow_map_projection_matrix'), _const(s, 'view_projection'), _const(s, 'camera_position')
    L, SZ = _const(s, 'light_direction'), _const(s, 'shadow_map_texture_size')
    if not (M and VP and C and SZ) or len(M) < 4 or len(VP) < 4:
        return None
    inv = _inv4([r[:4] for r in VP[:4]])
    if not inv:
        return None
    def unproject(z):
        q = [sum(inv[i][k] * v for k, v in enumerate((0.0, 0.0, z, 1.0))) for i in range(4)]
        return [q[i] / q[3] for i in range(3)]
    a, b = unproject(0.2), unproject(0.9)
    ray = [y - x for x, y in zip(a, b)]
    n = sum(x * x for x in ray) ** 0.5
    ray = [x / n for x in ray]
    cam, size = C[0][:3], SZ[0][0]
    def texel(q):
        h = q + [1.0]
        w = sum(M[3][k] * h[k] for k in range(4))
        return [sum(M[i][k] * h[k] for k in range(4)) / w * size / 2 for i in (0, 1)]
    out = []
    for d in DENSITY_M:
        p = [cam[i] + ray[i] * d for i in range(3)]
        dx = [(u - v) for u, v in zip(texel([p[0] + 0.5, p[1], p[2]]), texel([p[0] - 0.5, p[1], p[2]]))]
        dz = [(u - v) for u, v in zip(texel([p[0], p[1], p[2] + 0.5]), texel([p[0], p[1], p[2] - 0.5]))]
        out.append(round(abs(dx[0] * dz[1] - dx[1] * dz[0]) ** 0.5, 2))
    sun = None
    if L:
        ld = L[0][:3]
        m = sum(x * x for x in ld) ** 0.5
        sun = round(math.degrees(math.acos(max(-1.0, min(1.0, -sum(r * x / m for r, x in zip(ray, ld)))))), 1)
    return {'texels_per_m': dict(zip((f'{d}m' for d in DENSITY_M), out)), 'view_to_sun_deg': sun, 'map': int(size),
            'farz': round(_const(s, 'shadow_map_farz')[0][0], 1) if _const(s, 'shadow_map_farz') else None,
            'ray': [round(x, 4) for x in ray]}


def anatomy_tables(cat):
    caps = {f'{c.parent.parent.name}/{c.stem}': json.loads(c.read_text(encoding='utf-8')) for c in sorted(RUNS.glob('*/captures/*.json'))}
    cls = {h: e['class'] for h, e in cat['shaders'].items()}
    fxn = {h: (e['fx'][0]['fx'] + (':' + e['fx'][0]['technique'] if e['fx'][0].get('technique') else '')) if e['fx'] else h[:8] for h, e in cat['shaders'].items()}
    out = {}
    rows = [[k, s['header'].split(' scene ')[-1] if ' scene ' in s['header'] else '', s['draws'], sum(1 for p in s['passes'] if 'op' not in p),
             f"{s['backbuffer']['w']}x{s['backbuffer']['h']}" if s.get('backbuffer') else '', len(s['shaders']), len(s['events'])] for k, s in caps.items()]
    out['captures'] = md_table(['capture', 'scene', 'draws', 'passes', 'backbuffer', 'shaders', 'events'], rows)
    for k, s in caps.items():
        r = []
        for p in s['passes']:
            if 'op' in p:
                r.append([p['index'], p['op'], f"{p['src']} -> {p['dst']}", '', '', '', '', ' / '.join(p['events'])])
                continue
            rts = ', '.join(f"{d['id']} {d['w']}x{d['h']} {d['fmt']}{' bb' if d['backbuffer'] else ''}" for d in p['rt'])
            ds = f"{p['ds']['id']} {p['ds']['w']}x{p['ds']['h']} {p['ds']['fmt']}" if p['ds'] else '-'
            top = Counter()
            for pair, n in p['pairs'].items():
                v, q = pair.split('/')
                top[cls.get(q, cls.get(v, '?'))] += n
            clr = '' if not p['clear'] else f"clear {p['clear']['flags']:x}"
            r.append([p['index'], rts or '-', ds, p['draws'], p['prims'], ', '.join(f'{c} {n}' for c, n in top.most_common(3)) + (f' ({clr})' if clr else ''),
                      ','.join(str(x) for x in p['reads_from_pass']), ' / '.join(p['events'])])
        out['passes_' + k.split('/')[-1]] = md_table(['#', 'render targets', 'depth', 'draws', 'prims', 'classes (clear)', 'reads passes', 'events'], r)
    inv = {}
    for k, s in caps.items():
        bb = s.get('backbuffer') or {}
        for sid, d in s['surfaces'].items():
            key = (d.get('w'), d.get('h'), d.get('fmt'), d.get('ms'), d.get('texture'))
            tied = 'bb' if (d.get('w'), d.get('h')) == (bb.get('w'), bb.get('h')) else (f"bb/{bb.get('w', 0) // max(d.get('w') or 1, 1)}" if d.get('w') and bb.get('w') and bb['w'] % d['w'] == 0 and bb['h'] % d['h'] == 0 and bb['w'] // d['w'] == bb['h'] // d['h'] else 'fixed')
            inv.setdefault(key, {'scenes': set(), 'tied': set()})
            inv[key]['scenes'].add(k.split('/')[-1]); inv[key]['tied'].add(tied)
    out['targets'] = md_table(['size', 'format', 'msaa', 'texture', 'size rule', 'captures'],
                              [[f'{w}x{h}', f, m, 'yes' if t else 'no', ','.join(sorted(v['tied'])), short_list(sorted(v['scenes']))]
                               for (w, h, f, m, t), v in sorted(inv.items(), key=lambda x: (-(x[0][0] or 0) * (x[0][1] or 0), str(x[0][2])))])
    out['classes'] = md_table(['class', 'shaders'], [[c, n] for c, n in cat['by_class'].items()])
    # matrix, bone, instance and resolution-dependent constants per class (CTAB registers; values are in the capture summaries)
    want = re.compile(r'matri|view|world|projection|bone|instance|animation|texel|screen|resolution|size|camera_position|light_direction', re.I)
    regs = defaultdict(lambda: defaultdict(set))
    for h, e in cat['shaders'].items():
        for c in e['ctab']['constants']:
            if c['set'] == 'c' and want.search(c['name']):
                regs[e['class']][c['name']].add(f"{e['stage']} c{c['index']}" + (f"-c{c['index'] + c['count'] - 1}" if c['count'] > 1 else ''))
    out['registers'] = md_table(['class', 'constant', 'registers (stage, range)'],
                                [[k, n, ', '.join(sorted(v, key=lambda x: (x[:2], int(re.search(r'c(\d+)', x).group(1)), x)))] for k in sorted(regs) for n, v in sorted(regs[k].items())])
    rows = []
    for k, s in caps.items():
        d = shadow_density(s)
        if d:
            rows.append([k.split('/')[-1], d['view_to_sun_deg'], d['map'], d['farz']] + list(d['texels_per_m'].values()))
    merged = {}   # captures with the same numbers share a row (J9: most proof captures repeat the stock pose), so the doc stays under its cap
    for r in rows:
        merged.setdefault(tuple(r[1:]), []).append(r[0])
    rows = [[n[0] + (f' (+{len(n) - 1} same)' if len(n) > 1 else '')] + list(k) for k, n in merged.items()]
    out['shadow_density'] = md_table(['capture', 'view to sun (deg)', 'map', 'farz (m)'] + [f'texels/m at {d} m' for d in DENSITY_M], rows)
    out['flagged'] = md_table(['flagged source', 'captured shaders mapped'], [[f, len(v) if v else 'none captured'] for f, v in cat['flagged_sources'].items()])
    return out


def render_anatomy(text, tables):
    def rep(m):
        return m.group(1) + tables.get(m.group(2), f'(no table {m.group(2)})\n') + m.group(4)
    return GEN.sub(rep, text)


def cmd_build(a):
    cat = catalog_doc()
    cat_text = json.dumps(cat, indent=1) + '\n'
    doc = ANATOMY.read_text(encoding='utf-8') if ANATOMY.exists() else ''
    new_doc = render_anatomy(doc, anatomy_tables(cat))
    if a.check:
        bad = []
        if not CATALOG.exists() or CATALOG.read_text(encoding='utf-8') != cat_text:
            bad.append(str(CATALOG.relative_to(ROOT)))
        if new_doc != doc:
            bad.append(str(ANATOMY.relative_to(ROOT)))
        if bad:
            sys.exit('shader_catalog build --check: stale: ' + ', '.join(bad) + ' (run: python3 discovery/core/shader_catalog.py build)')
        print(f'shader_catalog build --check: ok ({cat["count"]} shaders, {cat["mapped"]} mapped)')
        return
    CATALOG.write_text(cat_text, encoding='utf-8', newline='\n')
    if doc:
        ANATOMY.write_text(new_doc, encoding='utf-8', newline='\n')
    print(f'build: {cat["count"]} shaders, {cat["mapped"]} mapped to an fx source; classes {cat["by_class"]}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('import'); p.add_argument('--run', required=True); p.add_argument("--captures", default=None, help="capture folder (default: games.json <target>.captures)"); p.add_argument('--name', nargs='*')
    p = sub.add_parser('fxmap'); p.add_argument('--fx', default=str(ROOT / 'extract' / paths.TARGET / 'data' / 'fx')); p.add_argument('--work', default=str(ROOT / '_scratch' / 'j8_fx'))
    p = sub.add_parser('build'); p.add_argument('--check', action='store_true')
    p = sub.add_parser('hash'); p.add_argument('file')
    p = sub.add_parser('density'); p.add_argument('captures', nargs='+', help='capture summary files (harness/runs/<run>/captures/<name>.json)')
    a = ap.parse_args(argv)
    if a.cmd == 'hash':
        h, n = shader_hash(Path(a.file).read_bytes()); print(h, n); return
    if a.cmd == 'density':
        for f in a.captures:
            print(Path(f).stem, json.dumps(shadow_density(json.loads(Path(f).read_text(encoding='utf-8')))))
        return
    {'import': cmd_import, 'fxmap': cmd_fxmap, 'build': cmd_build}[a.cmd](a)


if __name__ == '__main__':
    main()
