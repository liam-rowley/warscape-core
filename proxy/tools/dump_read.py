#!/usr/bin/env python3
"""Read a WER or proxy minidump with cdb (x86): the exception, the faulting thread's stack against its limit, the repeating frame cycle.

purpose: classify a crash or hang dump: exception record, stack depth vs the TEB limit, shortest repeating frame cycle and who owns it, graphics modules loaded
usage: python3 proxy/tools/dump_read.py DUMP [DUMP...] [--exe NAME] [--cdb PATH] [--sym-cache DIR] [--threads] [--json OUT] [--raw DIR]   (needs WinDbg: winget install Microsoft.WinDbg; --exe: the game exe's module, default the dump's own main module)
when: a crash or hang leaves a dump in %LOCALAPPDATA%\\CrashDumps\\<mod> or <mod>\\dumps; copy dumps to _scratch before reading (WER keeps 5). The markdown goes into the run report; offsets only, never the dump.
not-a-verb: wraps an external debugger on a local dump
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# modules worth naming in a graphics crash, with the game's exe added per dump (watch_list); a frame's owner is the text before '!'
WATCH = ('d3d9', 'd3d9_dxvk', 'opengl32', 'nvoglv32', 'nvgpucomp32', 'amdvlk32', 'vulkan_1', 'gameoverlayrenderer', 'dxgi')
CMDS = """.lastevent
.echo @@MAIN
|
.echo @@ENDMAIN
.exr -1
.ecxr
r
!teb
.echo @@STACK
kc 0n60000
.echo @@ENDSTACK
.echo @@MODS
lm
.echo @@ENDMODS
{threads}q
"""


def find_cdb(explicit):
    if explicit:
        return explicit
    hits = glob.glob(r'C:\Program Files (x86)\Windows Kits\10\Debuggers\x86\cdb.exe')
    # WindowsApps cannot be listed, so glob misses the winget WinDbg; ask Appx for its folder
    loc = subprocess.run(['powershell', '-NoProfile', '-Command', '(Get-AppxPackage Microsoft.WinDbg).InstallLocation'],
                         capture_output=True, text=True).stdout.strip()
    if loc and os.path.exists(os.path.join(loc, 'x86', 'cdb.exe')):
        hits.append(os.path.join(loc, 'x86', 'cdb.exe'))
    if not hits:
        sys.exit('cdb.exe (x86) not found: winget install Microsoft.WinDbg, or pass --cdb')
    return hits[-1]


def run_cdb(cdb, dump, sym_cache, threads):
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
        f.write(CMDS.format(threads='.echo @@THREADS\n~*kc 0n40\n.echo @@ENDTHREADS\n' if threads else ''))
        script = f.name
    try:
        sym = f'srv*{sym_cache}*https://msdl.microsoft.com/download/symbols'
        out = subprocess.run([cdb, '-z', str(dump), '-y', sym, '-c', f'$$<{script}'], capture_output=True, text=True,
                             errors='replace', timeout=1800)
        return out.stdout
    finally:
        os.unlink(script)


def section(text, name):
    m = re.search(rf'@@{name}\n(.*?)@@END{name}', text, re.S)
    return m.group(1) if m else ''


def main_module(text):
    """The dump's main module as `lm` names it, from cdb's `|` line (`.  0  id: 2bf4  examine  name: C:\\...\\game.exe`); None when cdb gave no name."""
    m = re.search(r'\bname:\s*(.+?)\s*$', section(text, 'MAIN'), re.M)
    if not m:
        return None
    name = re.split(r'[\\/]', m.group(1))[-1]
    return name[:-4] if name.lower().endswith('.exe') else name


def watch_list(exe, text):
    """WATCH and the game's exe: `--exe` when given (with or without .exe), else the dump's own main module."""
    name = exe[:-4] if exe and exe.lower().endswith('.exe') else exe
    name = name or main_module(text)
    return WATCH + (name,) if name else WATCH


def frames_of(stack):
    out = []
    for line in stack.splitlines():
        line = line.strip()
        if not line or line.startswith(('WARNING', 'Unable', '***', '0:', 'Call Site', '.echo', '@@')):   # cdb echoes each .echo: the command, then its text
            continue
        out.append(re.sub(r'\+0x[0-9a-f]+$', '', line))
    return out


def find_cycle(frames, max_period=32):
    """Shortest period p whose repetition covers the longest run of frames: (period, start, reps) or None."""
    best = None
    for p in range(1, min(max_period, len(frames) // 2) + 1):
        run = start = 0
        for i in range(len(frames) - p):
            if frames[i] == frames[i + p]:
                run += 1
                if best is None or run + p > best[3]:
                    best = (p, i - run + 1, (run + p) // p, run + p)
            else:
                run = 0
    if best and best[2] >= 3:
        return best[:3]
    return None


def num(text, pat):
    m = re.search(pat, text)
    return m.group(1) if m else None


def analyse(dump, text, exe=None):
    r = {'dump': str(dump)}
    r['session_time'] = num(text, r'Debug session time: (.+)')
    r['process_uptime'] = num(text, r'Process Uptime: (.+)')
    r['exception_code'] = num(text, r'ExceptionCode: (\w+)')
    r['exception_address'] = num(text, r'ExceptionAddress: (\S+ \S+)')
    r['access'] = num(text, r'(Attempt to (?:read|write|execute) (?:from |to )?address \w+)')
    r['thread'] = num(text, r'Last event: (\w+\.\w+)')
    esp, base, limit = num(text, r'\besp=(\w+)'), num(text, r'StackBase:\s+(\w+)'), num(text, r'StackLimit:\s+(\w+)')
    r.update(esp=esp, stack_base=base, stack_limit=limit)
    if esp and base and limit:
        r['stack_used'] = int(base, 16) - int(esp, 16)
        r['esp_minus_limit'] = int(esp, 16) - int(limit, 16)
    frames = frames_of(section(text, 'STACK'))
    r['frames'] = len(frames)
    owners = {}
    for f in frames:
        owners[f.split('!')[0]] = owners.get(f.split('!')[0], 0) + 1
    r['frame_owners'] = dict(sorted(owners.items(), key=lambda kv: -kv[1])[:12])
    cyc = find_cycle(frames)
    if cyc:
        p, start, reps = cyc
        r['cycle'] = {'period': p, 'repeats': reps, 'first_index': start, 'frames': frames[start:start + p]}
        r['above_cycle'] = frames[:start][:25]
        r['below_cycle'] = frames[start + p * reps:][:40]
    else:
        r['top'] = frames[:40]
    mods = section(text, 'MODS')
    r['modules'] = {m: bool(re.search(rf'^\w+ \w+\s+{re.escape(m)}\s', mods, re.M | re.I)) for m in watch_list(exe, text)}
    th = section(text, 'THREADS')
    if th:
        r['threads'] = th.strip()
    return r


def md(r):
    L = [f"### {Path(r['dump']).name}", '',
         f"- session {r['session_time']}, process uptime {r['process_uptime']}, thread {r['thread']}",
         f"- exception {r['exception_code']} at {r['exception_address']} ({r['access'] or 'no access info'})"]
    if 'stack_used' in r:
        L.append(f"- stack base {r['stack_base']}, limit {r['stack_limit']}, esp {r['esp']}: {r['stack_used']} bytes used, "
                 f"esp {r['esp_minus_limit']:+d} bytes from the limit")
    L.append(f"- {r['frames']} frames; owners: " + ', '.join(f'{k} {v}' for k, v in r['frame_owners'].items()))
    if 'cycle' in r:
        c = r['cycle']
        L.append(f"- **repeating cycle**: period {c['period']}, {c['repeats']} repeats, from frame {c['first_index']}:")
        L += [f'  - `{f}`' for f in c['frames']]
        L.append('- above the cycle (fault side): ' + ' <- '.join(f'`{f}`' for f in r['above_cycle'][:14]))
        L.append('- below the cycle (entry side): ' + ' <- '.join(f'`{f}`' for f in r['below_cycle'][:14]))
    else:
        L.append('- no repeating cycle; top frames: ' + ' <- '.join(f'`{f}`' for f in r['top'][:20]))
    L.append('- loaded: ' + ', '.join(m for m, v in r['modules'].items() if v))
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('dumps', nargs='+', type=Path)
    ap.add_argument('--cdb')
    ap.add_argument('--exe', help="the game exe's module for the loaded list (default: the dump's own main module)")
    ap.add_argument('--sym-cache', default=str(Path('_scratch', 'symcache').resolve()), help='symbol cache folder (default: _scratch/symcache under the current folder)')
    ap.add_argument('--threads', action='store_true', help='also every thread\'s top 40 frames')
    ap.add_argument('--json', type=Path)
    ap.add_argument('--raw', type=Path, help='folder for the raw cdb output, one .log per dump')
    a = ap.parse_args()
    cdb = find_cdb(a.cdb)
    results = []
    for d in a.dumps:
        text = run_cdb(cdb, d.resolve(), a.sym_cache, a.threads)
        if a.raw:
            a.raw.mkdir(parents=True, exist_ok=True)
            (a.raw / (d.name + '.log')).write_text(text, encoding='utf-8')
        if 'Could not open dump file' in text:
            sys.exit(f'cdb could not open {d}')
        r = analyse(d, text, a.exe)
        results.append(r)
        print(md(r))
    if a.json:
        a.json.write_text(json.dumps(results, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
