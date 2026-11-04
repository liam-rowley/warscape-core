"""
Purpose: Name the frames of a proxy crash dump from anywhere: read a minidump (exception, modules, the faulting thread's stack bytes) and symbolise it against the GNU ld map of the build that crashed (the map and its sidecar CI keeps as proxy-map-<build id>, or a release attaches).
Usage: wsc crash symbolise <dump> [--map <d3d9.map> | --build-id <id> [--run <run id>] [--repo OWNER/NAME]] [--log <proxy.log>] [--dll <d3d9.dll>] [--module <name>] [--sites <engine_sites.json[l]>] [--force-map] [--json]   (exit 0 the exception frame named in the DLL, 1 the dump parses but names no frame in the DLL, 2 refused: bad dump, wrong map, no map)
When: a crash left <mod>\\dumps\\<launch id>_<code>.dmp (or a WER LocalDumps dump): run it in the cloud or on the PC, no debugger; docs/PROXY_BUILD.md "Symbolising a crash".
Verb: crash
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from .. import minidump

NAME = 'crash'
HELP = 'crash dumps: symbolise a minidump against the linker map of the build that crashed'

SCAN_MAX = 16
EXPIRED = 'kept 90 days; the release attaches its own'


def add_arguments(p):
    sub = p.add_subparsers(dest='crash_cmd', required=True)
    s = sub.add_parser('symbolise', help='name the exception frame and the stack scan candidates of a minidump')
    s.add_argument('dump')
    s.add_argument('--map', help='the d3d9.map of the build (its sidecar d3d9.map.json beside it)')
    s.add_argument('--build-id', help='fetch the CI artifact proxy-map-<id> with gh into _scratch/maps/<id>/ (network)')
    s.add_argument('--run', help='with --build-id: the workflow run that has the artifact (default: the newest that has it)')
    s.add_argument('--repo', help='with --build-id: OWNER/NAME (default: the repository of the current folder)')
    s.add_argument('--log', help="the launch's proxy.log: its build id (and self_hash sha256) must equal the sidecar's")
    s.add_argument('--dll', help="the d3d9.dll that crashed: its sha256 must equal the sidecar's")
    s.add_argument('--module', help="the proxy's module name in the dump (default: the sidecar's dll)")
    s.add_argument('--sites', help='an engine sites registry (JSON list or JSONL): names an exe rva a row anchors')
    s.add_argument('--force-map', action='store_true', help='use a map that disagrees: every output line is prefixed "WRONG MAP? "')
    s.add_argument('--json', action='store_true')


def gh(args, cwd):
    """Run gh; (exit code, stdout, stderr). Tests replace this function."""
    try:
        r = subprocess.run(['gh', *args], cwd=cwd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return 127, '', 'gh is not installed'
    return r.returncode, r.stdout, r.stderr


class Refused(Exception):
    pass


def _fetch(build_id, run, repo, root):
    """Download proxy-map-<id> into <root>/_scratch/maps/<id>/ and return the map's path; Refused with the reason."""
    name = f'proxy-map-{build_id}'
    if not re.fullmatch(r'[A-Za-z0-9._-]+', build_id):
        raise Refused(f'build id {build_id!r} is not a build id')
    api = f'repos/{repo}/actions/artifacts?name={name}&per_page=100' if repo else f'repos/{{owner}}/{{repo}}/actions/artifacts?name={name}&per_page=100'
    rc, out, err = gh(['api', api], root)
    if rc:
        raise Refused(f'gh api failed listing {name}: {err.strip() or out.strip()}')
    try:
        arts = [a for a in json.loads(out).get('artifacts', []) if a.get('name') == name]
    except ValueError:
        raise Refused('gh api did not answer JSON') from None
    if run:
        arts = [a for a in arts if str((a.get('workflow_run') or {}).get('id')) == str(run)]
    if not arts:
        raise Refused(f'no artifact {name}{" in run " + str(run) if run else ""} (CI keeps maps 90 days; a release attaches its own d3d9.map)')
    live = [a for a in arts if not a.get('expired')]
    if not live:
        newest = max(arts, key=lambda a: a.get('created_at', ''))
        raise Refused(f'{name} has expired (made {newest.get("created_at", "?")} by run {(newest.get("workflow_run") or {}).get("id")}): {EXPIRED}')
    pick = max(live, key=lambda a: (a.get('created_at', ''), (a.get('workflow_run') or {}).get('head_branch') == 'main'))
    rid = str((pick.get('workflow_run') or {}).get('id'))
    dest = Path(root) / '_scratch' / 'maps' / build_id
    dest.mkdir(parents=True, exist_ok=True)
    args = ['run', 'download', rid, '-n', name, '-D', str(dest)] + (['--repo', repo] if repo else [])
    rc, out, err = gh(args, root)
    if rc:
        raise Refused(f'gh run download {rid} -n {name} failed: {err.strip() or out.strip()}')
    m = dest / 'd3d9.map'
    if not m.is_file():
        cands = sorted(dest.glob('*.map'))
        if not cands:
            raise Refused(f'{name} from run {rid} has no .map file')
        m = cands[0]
    return m


def _sites(path):
    """[(rva, length, id)] of the rows of an engine sites registry that have an rva."""
    text = Path(path).read_text(encoding='utf-8')
    try:
        rows = json.loads(text)
        rows = rows if isinstance(rows, list) else [rows]
    except ValueError:
        rows = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    out = []
    for r in rows:
        try:
            rva = int(str(r['rva']), 16)
        except (KeyError, ValueError, TypeError):
            continue
        n = len(re.findall(r'[0-9A-Fa-f?]{2}', str(r.get('anchor_bytes', '')))) or 1
        out.append((rva, n, str(r.get('id', '?'))))
    return out


def _where(dump, addr, dll, lmap, side_base, sites, exe):
    """One address: {module, rva, section, symbol, offset, obj, code, site} (fields None when unknown)."""
    m = dump.module_at(addr)
    w = {'address': f'0x{addr:08x}', 'module': m.basename if m else None, 'rva': f'0x{addr - m.base:x}' if m else None,
         'section': None, 'symbol': None, 'offset': None, 'object': None, 'code': None, 'site': None}
    if m is not None and dll is not None and m is dll and lmap is not None:
        h = lmap.lookup(side_base + (addr - m.base))
        if h:
            w.update(section=h.section, symbol=h.symbol, offset=f'0x{h.offset:x}', object=h.obj, code=h.code)
    elif m is not None and m is exe:
        r = addr - m.base
        for srva, n, sid in sites:
            if srva <= r < srva + n:
                w['site'] = f'{sid}+0x{r - srva:x}'
                break
    return w


def _fmt(w):
    s = f"{w['module']}+{w['rva']}" if w['module'] else f"{w['address']} (in no module)"
    if w['site']:
        s += f" (site {w['site']})"
    if w['symbol']:
        s += f"  {w['section']}: {w['symbol']}+{w['offset']} [{w['object']}]"
    return s


def _symbolise(a, root):
    if not a.map and not a.build_id:
        raise Refused('no map: pass --map <d3d9.map> (its sidecar beside it) or --build-id <id> (the CI artifact)')
    try:
        data = Path(a.dump).read_bytes()
    except OSError as e:
        raise Refused(f'cannot read the dump: {e}') from None
    try:
        dump = minidump.read(data)
    except minidump.DumpError as e:
        raise Refused(f'bad dump {a.dump}: {e}') from None
    map_path = Path(a.map) if a.map else _fetch(a.build_id, a.run, a.repo, root)
    side_path = Path(str(map_path) + '.json')
    try:
        side = json.loads(side_path.read_text(encoding='utf-8'))
        lmap = minidump.parse_map(map_path.read_text(encoding='utf-8', errors='replace'))
    except OSError as e:
        raise Refused(f'no map or no sidecar: {e} (build.sh writes d3d9.map and d3d9.map.json side by side)') from None
    except (ValueError, minidump.MapError) as e:
        raise Refused(f'unreadable map or sidecar {side_path}: {e}') from None
    for k in ('build_id', 'dll_sha256', 'image_base', 'dll'):
        if k not in side:
            raise Refused(f'the sidecar {side_path} has no {k}')
    side_base = int(str(side['image_base']), 0)
    wrong = []
    if a.build_id and side['build_id'] != a.build_id:
        wrong.append(f"the sidecar is build {side['build_id']}, --build-id asked for {a.build_id}")
    if a.log:
        try:
            log = Path(a.log).read_text(encoding='utf-8', errors='replace')
        except OSError as e:
            raise Refused(f'cannot read the log: {e}') from None
        m = re.search(r'd3d9\.dll build (\S+) loaded', log)
        if not m:
            raise Refused(f'{a.log} has no launch line ("d3d9.dll build <id> loaded")')
        if m.group(1) != side['build_id']:
            wrong.append(f"the log's launch line is build {m.group(1)}, the map's sidecar build {side['build_id']}")
        m = re.search(r'self_hash: sha256 ([0-9a-f]{64})', log)
        if m and m.group(1) != side['dll_sha256']:
            wrong.append(f"the log's self_hash is sha256 {m.group(1)}, the sidecar's {side['dll_sha256']}")
    if a.dll:
        try:
            have = hashlib.sha256(Path(a.dll).read_bytes()).hexdigest()
        except OSError as e:
            raise Refused(f'cannot read the DLL: {e}') from None
        if have != side['dll_sha256']:
            wrong.append(f"{a.dll} is sha256 {have}, the sidecar's {side['dll_sha256']}")
    modname = a.module or side['dll']
    dll = dump.module_named(modname)
    if dll is not None and 'size_of_image' in side and int(str(side['size_of_image']), 0) != dll.size:
        wrong.append(f"{modname} in the dump has size of image 0x{dll.size:x}, the sidecar's is {side['size_of_image']}")
    if wrong and not a.force_map:
        raise Refused('wrong map: ' + '; '.join(wrong) + ' (find the map of the build that crashed; --force-map uses this one anyway)')
    sites = _sites(a.sites) if a.sites else []
    exe = next((m for m in dump.modules if m.basename.lower().endswith('.exe')), dump.modules[0] if dump.modules else None)
    rep = ['python3 wsc.py crash symbolise', a.dump] + (['--map', a.map] if a.map else ['--build-id', a.build_id]) + \
          (['--run', a.run] if a.run else []) + (['--log', a.log] if a.log else []) + (['--dll', a.dll] if a.dll else []) + \
          (['--module', a.module] if a.module else []) + (['--sites', a.sites] if a.sites else []) + (['--force-map'] if a.force_map else [])
    res = {'build_id': side['build_id'], 'arch': dump.arch, 'dump': a.dump, 'map': str(map_path), 'dll': modname, 'dll_sha256': side['dll_sha256'],
           'wrong_map': wrong, 'exception': None, 'frame': None, 'scan': [], 'skipped_scan': 0, 'modules': [], 'reproduce': ' '.join(rep), 'exit': 1}
    res['modules'] = [{'name': m.name, 'base': f'0x{m.base:08x}', 'size': f'0x{m.size:x}'} for m in dump.modules]
    if dll is None:
        res['note'] = f'{modname} is not in the dump\'s module list'
    e = dump.exception
    if e is None:
        res['note'] = 'the dump has no exception stream'
        return res
    res['exception'] = {'code': f'0x{e.code:08x}', 'name': minidump.code_name(e.code), 'detail': minidump.exception_detail(e.code, e.params),
                        'address': f'0x{e.address:08x}', 'thread': f'0x{e.thread_id:x}'}
    start = dump.thread_start(e.thread_id)
    if start is not None:
        res['exception']['thread_start'] = _fmt(_where(dump, start, dll, lmap, side_base, sites, exe))
    f = _where(dump, e.address, dll, lmap, side_base, sites, exe)
    f['certain'] = True
    res['frame'] = f
    regs = dump.registers(e.context)
    if regs and dll is not None:
        res['sp'] = f"0x{regs['sp']:08x}"
        for off, word in minidump.stack_words(dump, regs['sp']):
            if not (dll.base <= word < dll.base + dll.size):
                continue
            w = _where(dump, word, dll, lmap, side_base, sites, exe)
            if not w['code']:
                res['skipped_scan'] += 1
                continue
            if len(res['scan']) < SCAN_MAX:
                w.update(certain=False, depth=len(res['scan']) + 1, sp_offset=f'0x{off:x}')
                res['scan'].append(w)
    res['exit'] = 0 if (f['symbol'] and dll is not None and f['module'] == dll.basename) else 1
    return res


def _text(res):
    sp = 'rsp' if res.get('arch') == 'amd64' else 'esp'
    out = [f"crash symbolise: build {res['build_id']} ({res['dll']} sha256 {res['dll_sha256']}), map {res['map']}"]
    for w in res['wrong_map']:
        out.append(f'map disagrees: {w}')
    if res.get('note'):
        out.append(f"note: {res['note']}")
    e = res['exception']
    if e:
        detail = f" ({e['detail']})" if e['detail'] else ''
        out.append(f"exception: {e['code']} {e['name']}{detail} at {e['address']}, thread {e['thread']}"
                   + (f", started at {e['thread_start']}" if e.get('thread_start') else ''))
        f = res['frame']
        tail = '' if f['symbol'] else ('  (no input section of the map holds it)' if f['module'] == res['dll'] else '  (outside the DLL)')
        out.append(f'exception frame: {_fmt(f)}{tail}')
    if res['scan'] or res.get('sp'):
        out.append(f"stack scan from {sp} {res.get('sp', '?')} (candidates, not frames: words on the stack that point into the DLL's code, by depth;"
                   f" {res['skipped_scan']} data pointers skipped)")
        for w in res['scan']:
            out.append(f"  stack scan #{w['depth']} {sp}+{w['sp_offset']}: {_fmt(w)}")
    if res['exit'] != 0:
        out.append('modules:')
        for m in res['modules']:
            out.append(f"  {m['base']} {m['size']:>10} {m['name']}")
    out.append(f"reproduce: {res['reproduce']}")
    if res['wrong_map']:
        out = ['WRONG MAP? ' + ln for ln in out]
    return '\n'.join(out) + '\n'


def run(args, ctx):
    try:
        res = _symbolise(args, ctx.root)
    except Refused as e:
        print(f'crash symbolise: refused: {e}', file=sys.stderr)
        return 2
    if args.json:
        sys.stdout.write(json.dumps(res, indent=2) + '\n')
    else:
        sys.stdout.write(_text(res))
    return res['exit']
