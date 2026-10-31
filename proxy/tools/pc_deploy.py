#!/usr/bin/env python3
"""Kit, install, uninstall and check the proxy on the PC with sha-checked copies and a byte-exact uninstall.

purpose: build a proxy kit (built DLL, default config, pinned DXVK) or a harness kit (the watcher, its adapter and profiles; manifest with sha256 and unique staged names; both carry a sha-checked exe_identity.json), install the proxy into the game folder with sha-checked copies (refused when the exe is not the vanilla build the identity names), uninstall it back to the pre-install snapshot, edit the installed config, check the exe sha after each of them, snapshot and diff a game folder; status reports the exe verdict, any .git in or above the game folder and files no install owns (J18)
usage: pc_deploy.py sync-lua --game G --state S [--dry-run] | kit [--what proxy|harness] [--out DIR] | send --kit DIR --state S | snapshot --game G --out F | install --kit DIR --game G --state S [--assume-closed] | uninstall --game G --state S [--assume-closed] | set --game G [--state S] key=value... | status --game G --state S | diff A B
when: every time built proxy or harness files go to the game folder or the watcher (never copy them by hand); runs in Git Bash on the PC from the repo checkout: `kit` builds into build/kits, `send` puts a kit sha-checked under <state>/kits/<id> (for install and the watcher's `update kit=<id>`); install/uninstall ask the running watcher (<state>/watcher/watcher.status), else tasklist, whether a game of either title is running
not-a-verb: a deploy script with its own subcommands that the PC's installer also runs from a kit folder (a copy travels in every kit), so it stays stdlib only and outside the wsc CLI (whether it becomes a verb: J20 report)
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The game repo and its adapters come from layout.py (J12). A kit's copy of this script on the PC has no repo around it: install,
# uninstall, set, status and diff use only their arguments and the kit, so the repo paths are simply absent there.
try:
    sys.path.insert(0, str(HERE))
    import layout
    ROOT = layout.game_root()
except Exception:   # noqa: BLE001  (ImportError beside a kit, LayoutError outside a repo)
    layout, ROOT = None, HERE
BIG = 100 * 1024 * 1024   # snapshot: files above this are compared by size + mtime (game packs: nothing here ever writes them)
STATE_FILE = 'install.json'


def utc_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha1_file(p, chunk=1 << 20):
    h = hashlib.sha1()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(chunk), b''):
            h.update(b)
    return h.hexdigest()


# ---- the exe identity (J18, J5 ledger row 28: the exe stays vanilla on disk) ------------------------------------------------------
IDENTITY_COPY = 'exe_identity.json'   # the sha-checked copy of the proxy adapter's identity.json that travels in every kit


def _need_repo(what):
    if layout is None:
        raise SystemExit(f'pc_deploy {what}: needs the repo checkout (proxy/tools/layout.py), not a kit copy')


def proxy_adapter(adapter=None):
    """The game's proxy adapter folder: the --adapter folder, else layout.py's."""
    if adapter:
        return Path(adapter).resolve()
    _need_repo('kit')
    return layout.proxy_adapter(ROOT)


def harness_adapter():
    _need_repo('kit')
    return layout.harness_adapter(ROOT)


def harness_scripts():
    """The watcher's scripts: harness/core/ before the move to warscape-core, harness/ in the core after it."""
    _need_repo('kit')
    own = layout.own_root()
    return own / 'harness' / 'core' if (own / 'harness' / 'core' / 'watcher.ps1').is_file() else own / 'harness'


def load_identity(*candidates):
    """The first identity file that exists among the candidates (a kit's copy, the copy beside this script, the repo's own), else None."""
    for c in candidates:
        if c and Path(c).is_file():
            return json.loads(Path(c).read_text(encoding='utf-8'))
    return None


def default_identity(adapter=None):
    try:
        repo = proxy_adapter(adapter) / 'identity.json'
    except (SystemExit, Exception):   # noqa: BLE001  (a kit copy: only the copy beside it)
        repo = None
    return load_identity(Path(__file__).with_name(IDENTITY_COPY), repo)


def exe_verdict(game, ident, exe_name=None):
    """(ok, sha1, line) for the exe in the game folder against an identity. ok is None when it cannot be judged (no identity, no exe)."""
    name = exe_name or (ident or {}).get('exe_name')
    if not ident or not ident.get('sha1') or not name:
        return None, None, f'exe: CANNOT CHECK {name or "the exe"}: no exe identity (the proxy adapter\'s identity.json or a kit copy {IDENTITY_COPY})'
    exe = Path(game) / name
    if not exe.is_file():
        return None, None, f'exe: CANNOT CHECK: {exe} not found'
    h = sha1_file(exe)
    if h == ident['sha1'].lower():
        return True, h, f'exe: ok {exe.name} sha1 {h} is the vanilla build in the identity'
    return False, h, (f'exe: MISMATCH {exe.name} sha1 {h} is not the vanilla build the proxy knows ({ident["sha1"]}): a Steam update or a '
                      f"modified exe. Next step: a new identity.json from proxy/tools/exe_info.py, which is Liam's call")


def git_dirs(game):
    """Every .git in the game folder or in one of its parents up to the drive root (J5 ledger row 32: never git in a game folder)."""
    g = Path(game).resolve() if Path(game).exists() else Path(game)
    return [str(d / '.git') for d in (g, *g.parents) if (d / '.git').exists()]


def game_config_paths(adapter=None):
    """The harness adapter's game-anchored config files (a profile overlays them; never foreign), as game-relative POSIX paths."""
    try:
        a = Path(adapter) if adapter else harness_adapter()
    except (SystemExit, Exception):   # noqa: BLE001
        return []
    if not a.is_file():
        return []
    return [c['path'].replace('\\', '/') for c in json.loads(a.read_text(encoding='utf-8')).get('config_files', []) if c.get('anchor') == 'game']


def foreign_files(game, state, rec):
    """Diff lines (added/changed/touched) between the pre-install snapshot and the game folder now, outside what the install owns and
    the game-anchored config files; the removed lines are returned apart. ([foreign], [removed])."""
    pre = json.loads((Path(state) / rec['pre_snapshot']).read_text(encoding='utf-8'))
    owned = rec.get('owned', [])
    allowed = set(rec.get('game_config_files') or game_config_paths())

    def ours(k):
        k = k.rstrip('/')
        return k in allowed or any(k == o.rstrip('/') or (o.endswith('/') and k.startswith(o)) for o in owned)
    foreign, removed = [], []
    for line in diff_snapshots(pre, snapshot(game)):
        kind, path = line.split(None, 1)
        if ours(path.split(' (')[0]):
            continue
        (removed if kind == 'removed' else foreign).append(line)
    return foreign, removed


def pc_rules(game, state, ident):
    """The three PC-rule damage checks for status and `wsc setup` (J18): (failures, lines). A check that cannot read its folder reports
    that and counts as a failure, never as a pass."""
    lines, bad = [], 0
    ok, _, line = exe_verdict(game, ident)
    lines.append(line)
    bad += ok is not True
    gits = git_dirs(game)
    lines.append('git: ' + ('FAIL ' + ', '.join(gits) + ' (never run git in a game folder: remove it by hand after checking what made it)' if gits
                            else 'ok, no .git in the game folder or its parents'))
    bad += bool(gits)
    rec_path = Path(state) / STATE_FILE
    if rec_path.exists():
        rec = json.loads(rec_path.read_text(encoding='utf-8'))
        try:
            foreign, removed = foreign_files(game, state, rec)
        except OSError as e:
            foreign, removed = [f'cannot diff against the pre-install snapshot: {e}'], []
        lines.append(f'foreign: {len(foreign)} file(s) added or changed outside the install and the config files'
                     + ''.join('\n    ' + f for f in foreign[:20]))
        if removed:
            lines.append(f'removed: {len(removed)} vanilla path(s) gone since the pre-install snapshot (not failing; Steam verify restores them)'
                         + ''.join('\n    ' + f for f in removed[:10]))
        bad += bool(foreign)
    else:
        lines.append('foreign: not checked, nothing installed by this tool (no pre-install snapshot)')
    return bad, lines


def record_exe(rec, game, ident, action, stamp):
    """Hash the exe after a change and add the verdict to the install history; returns ok (None when it cannot be judged)."""
    ok, h, line = exe_verdict(game, ident, rec.get('exe_name') if rec else None)
    print(f'pc_deploy {action}: {line}')
    if rec is not None:
        rec.setdefault('history', []).append({'utc': stamp, 'action': f'{action} exe check', 'exe_sha1': h,
                                              'exe_verdict': {True: 'vanilla', False: 'MISMATCH', None: 'unchecked'}[ok]})
    if ok is False:
        print(f'pc_deploy {action}: !!! THE EXE ON DISK IS NOT VANILLA AFTER {action.upper()} !!! (D2: the exe stays vanilla; tell Liam)')
    return ok


# ---- kit ------------------------------------------------------------------------------------------------------------
def kit_packs(had, mod):
    """Game packs the kit carries beside the proxy, built by the game's own builders: the harness adapter's `kit_packs` list of
    {id, module (repo-relative .py with build(input) -> (path, info)), input (repo-relative)}. A builder that cannot run here (the game's
    packs unreadable: CI) is recorded as absent with its reason, so a launch whose file rules need the pack is refused (ctl.py).
    -> ([(path, kit path, role)], {id: {present, path, sha256} | {present: False, reason}})"""
    import importlib.util
    files, packs = [], {}
    for p in had.get('kit_packs', []):
        stem = Path(p['module']).stem
        try:
            mod_ = sys.modules.get(stem)
            if mod_ is None:
                spec = importlib.util.spec_from_file_location(stem, ROOT / p['module'])
                mod_ = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod_)
            path, _ = mod_.build(ROOT / p['input'])
            files.append((path, f'{mod}/packs/{Path(path).name}', 'dev'))
            packs[p['id']] = {'present': True, 'path': f'{mod}/packs/{Path(path).name}', 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
        except (OSError, SystemExit, KeyError, ImportError) as e:
            packs[p['id']] = {'present': False, 'reason': str(e) or type(e).__name__}
            print(f"pc_deploy kit: no {p['id']} pack ({e}): a file rule that adds it then finds nothing (ctl.py refuses that launch)")
    return files, packs


def build_kit(out, adapter=None, dll=None, dxvk_dir=None, build_id=None, identity=None):
    """Kit folder: manifest.json + payload files stored FLAT under unique names (<sha12>__<name>): a resend of a stale cached copy
    (empire-remastered LEARNINGS lesson 18) can never pass for the new file, because install checks every staged file's sha256."""
    adir = proxy_adapter(adapter)
    ident_path = Path(identity or adir / 'identity.json')
    ident = json.loads(ident_path.read_text(encoding='utf-8'))
    mod, ini = ident['mod_dir'], ident['config_file']
    had = json.loads(harness_adapter().read_text(encoding='utf-8'))
    dll = Path(dll or ROOT / 'build' / 'proxy' / adir.name / 'd3d9.dll')
    if not dll.exists():
        raise SystemExit(f'pc_deploy kit: {dll} missing: run proxy/tools/build.sh dll first')
    if dxvk_dir is None:
        sys.path.insert(0, str(Path(__file__).parent))
        import fetch_dxvk
        d, lic = fetch_dxvk.fetch(ROOT / 'build' / 'dxvk')
    else:
        d, lic = Path(dxvk_dir) / 'd3d9_dxvk.dll', Path(dxvk_dir) / 'LICENSE.dxvk.txt'
    files = [(dll, 'd3d9.dll', 'proxy'), (adir / ini, ini, 'config'),
             (d, f'{mod}/dxvk/d3d9_dxvk.dll', 'backend'), (lic, f'{mod}/LICENSE.dxvk.txt', 'licence')]
    # dev side (J3): the Lua bridge files and the wrapper pack; inert unless dev keys are set (all default off)
    ldir = adir / 'lua'
    packs = {}
    if ldir.is_dir():
        sys.path.insert(0, str(Path(__file__).parent))
        import build_dev_pack
        pack, _ = build_dev_pack.build(adir)
        files.append((pack, f'{mod}/packs/{pack.name}', 'dev'))
        # the game's own packs (J44's fixed sky, J12: declared by the game, built where its packs are readable; a CI kit goes without)
        more, packs = kit_packs(had, mod)
        files += more
        for p in sorted(ldir.rglob('*')):
            if p.is_file() and p.suffix in ('.lua', '.txt') and p.name != 'wrappers.txt':
                files.append((p, f'{mod}/lua/' + p.relative_to(ldir).as_posix(), 'dev'))
    if build_id is None:
        try:
            build_id = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short=12', 'HEAD'], capture_output=True, text=True).stdout.strip() or 'nogit'
        except OSError:
            build_id = 'nogit'
    kit_id = f'kit_{utc_stamp()}_{build_id}'
    kdir = Path(out) / kit_id
    kdir.mkdir(parents=True)
    entries = []
    for src, dest, role in files:
        b = Path(src).read_bytes()
        h = hashlib.sha256(b).hexdigest()
        staged = f'{h[:12]}__{dest.replace("/", "__")}'
        (kdir / staged).write_bytes(b)
        entries.append({'path': dest, 'staged': staged, 'sha256': h, 'size': len(b), 'role': role})
    man = {'kit_id': kit_id, 'build_id': build_id, 'created_utc': utc_stamp(), 'game': ident['game'], 'exe_name': ident['exe_name'],
           'other_exes': list(had.get('other_images', [])), 'mod_dir': mod, 'config_file': ini, 'owned': ['d3d9.dll', ini, mod + '/'], 'files': entries,
           'game_config_files': game_config_paths(), 'packs': packs}
    ib = ident_path.read_bytes()   # the copy install checks the exe against (J18): byte-identical to the source, sha256 in the manifest
    (kdir / IDENTITY_COPY).write_bytes(ib)
    man['exe_identity'] = {'name': IDENTITY_COPY, 'sha256': hashlib.sha256(ib).hexdigest()}
    (kdir / 'manifest.json').write_text(json.dumps(man, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(__file__, kdir / 'pc_deploy.py')
    print(f'pc_deploy kit: {kdir} ({len(entries)} files)')
    return kdir


def verify_kit(kdir):
    """Every staged file must exist with the manifest's sha256 and size. Returns (manifest, problems)."""
    kdir = Path(kdir)
    man = json.loads((kdir / 'manifest.json').read_text(encoding='utf-8'))
    bad = []
    for e in man['files']:
        p = kdir / e['staged']
        if not p.exists():
            bad.append(f"{e['staged']}: missing")
        elif p.stat().st_size != e['size'] or sha256_file(p) != e['sha256']:
            bad.append(f"{e['staged']}: sha256 {sha256_file(p)[:12]} != manifest {e['sha256'][:12]} (stale or partial copy: re-send under a new name)")
        if '..' in e['path'].split('/') or e['path'].startswith('/'):
            bad.append(f"{e['path']}: not a relative path inside the game folder")
        if not any(e['path'] == o or (o.endswith('/') and e['path'].startswith(o)) for o in man['owned']):
            bad.append(f"{e['path']}: outside the paths the kit owns")
    ei = man.get('exe_identity')
    if not ei:
        bad.append(f'no {IDENTITY_COPY} in the manifest (a kit from before J18): build a new kit')
    elif not (kdir / ei['name']).exists() or sha256_file(kdir / ei['name']) != ei['sha256']:
        bad.append(f"{ei['name']}: missing or sha256 differs from the manifest")
    return man, bad


# ---- harness kit: the watcher and what it needs on the PC ------------------------------------------------------------
HARNESS_SRC = ['watcher.ps1', 'watch.cmd', 'update.ps1', 'dump.ps1', 'procfreeze.ps1', 'spawn_detached.ps1', 'vdisplay_probe.ps1', 'win_probe.ps1']
HARNESS_KIT_FILES = ['install.ps1', 'Install watcher.cmd', 'Uninstall watcher.cmd', 'job.sh']   # real names at the top of the kit folder
WIN_TEXT = ('.ps1', '.cmd', '.bat')


def norm_for_pc(name, b):
    """Windows scripts reach the PC with CRLF whatever the checkout had (a LF-only .cmd can break goto/labels), and as ASCII: Windows
    PowerShell 5.1 reads a script without a BOM as ANSI, so a non-ASCII byte silently becomes another character."""
    if name.lower().endswith(WIN_TEXT):
        try:
            b.decode('ascii')
        except UnicodeDecodeError as e:
            raise SystemExit(f'pc_deploy kit: {name} contains a non-ASCII byte at {e.start}: Windows PowerShell 5.1 would misread it; keep PC scripts ASCII')
        b = b.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    return b


def build_harness_kit(out, adapter=None, build_id=None, identity=None):
    """Kit folder for the watcher: manifest.json (kind harness) + payload files stored FLAT under unique names (<sha12>__<path>) whose
    paths are relative to the watcher root (src/..., profiles/...), + the installer and job.sh under their real names (kit_files, sha256 in
    the manifest), + pc_deploy.py. Every kit has a new id; install.ps1 and update.ps1 check every sha256 before anything is written."""
    hdir = harness_scripts()                 # the watcher's scripts
    adir = harness_adapter().parent          # the game's harness adapter: adapter.json and profiles/
    ad = json.loads((adir / 'adapter.json').read_text(encoding='utf-8'))
    files = [(hdir / n, 'src/' + n, 'watcher') for n in HARNESS_SRC] + [(adir / 'adapter.json', 'src/adapter.json', 'adapter')]
    # the watcher checks the exe before every launch against this copy, beside its adapter.json (J18)
    files.append((Path(identity or proxy_adapter(adapter) / 'identity.json'), 'src/' + IDENTITY_COPY, 'identity'))
    for p in sorted((adir / 'profiles').rglob('*')):
        if p.is_file():
            files.append((p, 'profiles/' + p.relative_to(adir / 'profiles').as_posix(), 'profile'))
    if build_id is None:
        try:
            build_id = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short=12', 'HEAD'], capture_output=True, text=True).stdout.strip() or 'nogit'
        except OSError:
            build_id = 'nogit'
    kit_id = f'harness_{utc_stamp()}_{build_id}'
    kdir = Path(out) / kit_id
    kdir.mkdir(parents=True)
    entries = []
    for src, dest, role in files:
        b = norm_for_pc(src.name, Path(src).read_bytes())
        h = hashlib.sha256(b).hexdigest()
        staged = f'{h[:12]}__{dest.replace("/", "__")}'
        (kdir / staged).write_bytes(b)
        entries.append({'path': dest, 'staged': staged, 'sha256': h, 'size': len(b), 'role': role})
    kit_files = []
    for n in HARNESS_KIT_FILES + ['adapter.json']:
        src = adir / 'adapter.json' if n == 'adapter.json' else hdir / n
        b = norm_for_pc(n, src.read_bytes())
        (kdir / n).write_bytes(b)
        kit_files.append({'name': n, 'sha256': hashlib.sha256(b).hexdigest()})
    m = re.search(r"\$Version\s*=\s*'([^']+)'", (hdir / 'watcher.ps1').read_text(encoding='ascii'))
    wroot = ad['state_dir'].rstrip('\\') + '\\' + ad['watcher_subdir']
    man = {'kind': 'harness', 'kit_id': kit_id, 'build_id': build_id, 'created_utc': utc_stamp(), 'game': ad['game'],
           'watcher_version': m.group(1) if m else None, 'watcher_root': wroot, 'task_name': ad['task_name'], 'files': entries, 'kit_files': kit_files}
    (kdir / 'manifest.json').write_text(json.dumps(man, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(__file__, kdir / 'pc_deploy.py')
    print(f'pc_deploy kit: {kdir} ({len(entries)} files + {len(kit_files)} kit files; watcher {man["watcher_version"]})')
    return kdir


def verify_harness_kit(kdir):
    """Same stale-resend guard as verify_kit, for a harness kit. Returns (manifest, problems)."""
    kdir = Path(kdir)
    man = json.loads((kdir / 'manifest.json').read_text(encoding='utf-8'))
    bad = []
    if man.get('kind') != 'harness':
        bad.append('not a harness kit')
    for e in man['files']:
        p = kdir / e['staged']
        if not p.exists() or p.stat().st_size != e['size'] or sha256_file(p) != e['sha256']:
            bad.append(f"{e['staged']}: missing or sha256 differs from the manifest (stale or partial copy: re-send under a new name)")
        if '..' in e['path'].split('/') or e['path'].startswith('/') or e['path'].split('/')[0] not in ('src', 'profiles'):
            bad.append(f"{e['path']}: outside src/ and profiles/")
    for k in man['kit_files']:
        p = kdir / k['name']
        if not p.exists() or sha256_file(p) != k['sha256']:
            bad.append(f"{k['name']}: missing or sha256 differs from the manifest")
    return man, bad


# ---- send: a built kit to <state>/kits/<id> ------------------------------------------------------------------------------------
def send_kit(kit, state):
    """Copy a built kit (proxy or harness) into <state>/kits/<kit id>, every file sha-checked, the folder renamed into place only once
    it verifies. A kit id that is already there is refused: a resend is a new kit (the stale-copy guard install and update rely on)."""
    kit, state = Path(kit), Path(state)
    man = json.loads((kit / 'manifest.json').read_text(encoding='utf-8'))
    kid = man['kit_id']
    if kit.name != kid:
        raise SystemExit(f'pc_deploy send: {kit} is not named after its kit id {kid}')
    _, bad = (verify_harness_kit if man.get('kind') == 'harness' else verify_kit)(kit)
    if bad:
        raise SystemExit('pc_deploy send: the source kit does not verify, nothing sent:\n  ' + '\n  '.join(bad))
    dest = state / 'kits' / kid
    if dest.exists():
        raise SystemExit(f'pc_deploy send: {dest} already exists: a kit id is never reused (build a new kit)')
    tmp = state / 'kits' / f'{kid}.{utc_stamp()}.partial'
    shutil.copytree(kit, tmp, copy_function=shutil.copyfile)
    for p in kit.rglob('*'):
        if p.is_file() and sha256_file(p) != sha256_file(tmp / p.relative_to(kit)):
            raise SystemExit(f'pc_deploy send: {tmp / p.relative_to(kit)} does not verify after the copy; {tmp} left for inspection')
    os.replace(tmp, dest)
    n = sum(1 for p in dest.rglob('*') if p.is_file())
    print(f'pc_deploy send: {kid} -> {dest} ({n} files, sha256 checked)')
    return dest


# ---- snapshots ----------------------------------------------------------------------------------------------------------------
def snapshot(game, big=BIG):
    game = Path(game)
    out = {}
    for dp, dns, fns in os.walk(game):
        dns.sort()
        for fn in sorted(fns):
            p = Path(dp) / fn
            rel = p.relative_to(game).as_posix()
            st = p.stat()
            out[rel] = {'size': st.st_size, 'mtime_ns': st.st_mtime_ns, 'sha256': sha256_file(p) if st.st_size <= big else None}
        if not fns and not dns and Path(dp) != game:
            out[Path(dp).relative_to(game).as_posix() + '/'] = {'dir': True}
    return out


def diff_snapshots(a, b):
    """Lines describing how b differs from a (empty = byte-identical for hashed files, size+mtime-identical for the big ones)."""
    out = []
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if x is None:
            out.append(f'added   {k}')
        elif y is None:
            out.append(f'removed {k}')
        elif x.get('dir') or y.get('dir'):
            continue
        elif x['size'] != y['size'] or (x['sha256'] or y['sha256']) and x['sha256'] != y['sha256']:
            out.append(f'changed {k}')
        elif x['sha256'] is None and x['mtime_ns'] != y['mtime_ns']:
            out.append(f'touched {k} (large file: same size, other mtime)')
    return out


# ---- game-closed check ------------------------------------------------------------------------------------------------------------
def watcher_view(state, now=None):
    """The watcher's own view of the PC's processes: ('', None) when no watcher was ever installed under <state>/watcher, else
    (why-not-usable, status dict). A watcher whose heartbeat (watcher.alive mtime) is older than 30 s cannot vouch for anything."""
    if state is None:
        return '', None
    wdir = Path(state) / 'watcher'
    if not (wdir / 'watcher.status').exists() and not (wdir / 'watcher.alive').exists():
        return '', None
    try:
        age = (now or time.time()) - (wdir / 'watcher.alive').stat().st_mtime
    except OSError:
        return 'the watcher folder exists but has no heartbeat (watcher.alive): the watcher cannot tell whether a game is running', None
    if age > 30:
        return f'the watcher heartbeat is {int(age)} s old (watcher not running): it cannot tell whether a game is running', None
    for _ in range(8):   # watcher.status is replaced every 2 s: a read can hit the swap
        try:
            return '', json.loads((wdir / 'watcher.status').read_bytes().decode('utf-8'))
        except (OSError, ValueError):
            time.sleep(0.1)
    return 'watcher.status could not be read', None


def windows_images():
    """Lower-case image names of every running process (tasklist CSV), or None off Windows. Raises OSError/SubprocessError."""
    if os.name != 'nt':
        return None
    r = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=30, check=True)
    return {line.split('","')[0].strip('"').lower() for line in r.stdout.splitlines() if line.startswith('"')}


def running_check(game, mod_dir, exe_name, now=None, state=None, other_exes=(), images=None):
    """'' when no game looks open, else why not. With a watcher installed (<state>/watcher) its process list is authoritative for BOTH
    titles. Without one: tasklist on Windows; elsewhere (host tests) the proxy's own log - a launch whose log has no final 'process
    detach' line and was written in the last 10 minutes is taken as running. `images` is the process-list provider (None: windows_images,
    looked up at call time), so a test reaches the log fallback on any OS (J22)."""
    why, st = watcher_view(state, now)
    if why:
        return why
    titles = [exe_name, *other_exes]
    if st is not None:
        lower = {x.lower() for x in titles}
        hits = [p for p in st.get('processes', []) if str(p.get('image', '')).lower() in lower]
        return ('watcher process list: ' + ', '.join(f"{p['image']} (pid {p['pid']})" for p in hits) + ' is running') if hits else ''
    try:
        images = (images or windows_images)()
    except (OSError, subprocess.SubprocessError):
        return 'tasklist failed: cannot tell whether the game is running'
    if images is not None:
        hit = [x for x in titles if x.lower() in images]
        return f"tasklist: {', '.join(hit)} is running" if hit else ''
    log = Path(game) / mod_dir / 'logs' / 'proxy.log'
    if not log.exists():
        return ''
    text = log.read_bytes().decode('utf-8', 'replace').rstrip()
    last = text.splitlines()[-1] if text else ''
    age = (now or time.time()) - log.stat().st_mtime
    if 'process detach' not in last and age < 600:
        return f'{log.name} was written {int(age)} s ago and has no final "process detach" line: the game may be running'
    return ''


def require_closed(game, man, assume, state=None):
    why = running_check(game, man['mod_dir'], man['exe_name'], state=state, other_exes=man.get('other_exes', []))
    if why and not assume:
        raise SystemExit(f'pc_deploy: refusing: {why}. Close the game first (or pass --assume-closed once Liam has confirmed it is closed).')
    if why:
        print(f'pc_deploy: warning: {why}; continuing on --assume-closed')


# ---- moving (never deleting) --------------------------------------------------------------------------------------------------
def move_out(src, dest):
    """Move src (file or tree) to dest. Across two mounts a rename fails, so: copy, verify every file's sha256, then remove the source.
    Nothing is deleted without a verified copy (the PC rule: move to _to_delete, never delete)."""
    src, dest = Path(src), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dest)
        return
    except OSError:
        pass
    if src.is_dir():
        shutil.copytree(src, dest, copy_function=shutil.copy2)
        for p in src.rglob('*'):
            if p.is_file() and sha256_file(p) != sha256_file(dest / p.relative_to(src)):
                raise SystemExit(f'pc_deploy: copy of {p} does not verify; nothing removed')
        try:
            shutil.rmtree(src)
        except OSError as e:
            raise SystemExit(f'pc_deploy: copied {src} to {dest} but cannot remove the source ({e}): allow deletion in the game folder, then run again')
    else:
        shutil.copy2(src, dest)
        if sha256_file(src) != sha256_file(dest):
            raise SystemExit(f'pc_deploy: copy of {src} does not verify; nothing removed')
        try:
            os.remove(src)
        except OSError as e:
            raise SystemExit(f'pc_deploy: copied {src} to {dest} but cannot remove the source ({e}): allow deletion in the game folder, then run again')


# ---- install / uninstall ------------------------------------------------------------------------------------------------------
def install(kit, game, state, assume_closed=False):
    game, state = Path(game), Path(state)
    man, bad = verify_kit(kit)
    if bad:
        raise SystemExit('pc_deploy install: kit does not verify, nothing installed:\n  ' + '\n  '.join(bad))
    if not (game / man['exe_name']).exists():
        raise SystemExit(f"pc_deploy install: {game / man['exe_name']} not found: wrong game folder")
    ident = load_identity(Path(kit) / IDENTITY_COPY)
    ok, _, line = exe_verdict(game, ident, man['exe_name'])
    if ok is not True:   # before any change (J18): the proxy's engine sites are anchored to one build
        raise SystemExit(f'pc_deploy install: {line}' + chr(10) + 'pc_deploy install: nothing was installed.')
    print(f'pc_deploy install: {line}')
    require_closed(game, man, assume_closed, state)
    state.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    rec_path = state / STATE_FILE
    rec = json.loads(rec_path.read_text(encoding='utf-8')) if rec_path.exists() else None
    def save():   # the record is on disk BEFORE each change to the game folder, so a failed install can still be uninstalled
        rec_path.write_text(json.dumps(rec, indent=2) + '\n', encoding='utf-8')
    if rec is None:
        pre = snapshot(game)
        (state / 'snapshots').mkdir(exist_ok=True)
        pre_path = state / 'snapshots' / f'pre_install_{stamp}.json'
        pre_path.write_text(json.dumps(pre), encoding='utf-8')
        rec = {'pre_snapshot': str(pre_path.relative_to(state)), 'backups': [], 'history': [], 'kit_id': None, 'build_id': None,
               'installed_utc': None, 'files': []}
        rec.update({'owned': man['owned'], 'mod_dir': man['mod_dir'], 'exe_name': man['exe_name'], 'config_file': man['config_file'], 'other_exes': man.get('other_exes', [])})
        save()
        # anything already at a path the kit owns is foreign (not ours): back it up for the uninstall to restore
        for o in man['owned']:
            p = game / o.rstrip('/')
            if p.exists():
                b = state / 'backup' / stamp / o.rstrip('/')
                rec['backups'].append({'path': o.rstrip('/'), 'backup': str(b.relative_to(state))})
                save()
                move_out(p, b)
                print(f'pc_deploy install: backed up the existing {o} to {b}')
    rec['exe_identity'] = {'sha1': ident['sha1'], 'exe_name': man['exe_name']}   # on disk before any change: a failed install's uninstall checks it
    rec['history'].append({'utc': stamp, 'action': 'install started', 'kit_id': man['kit_id']})
    save()
    for e in man['files']:
        dest = game / e['path']
        if dest.exists():   # ours from an earlier kit: out of the way, never deleted
            move_out(dest, state / '_to_delete' / stamp / e['path'])
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + f'.{stamp}.tmp')
        shutil.copyfile(Path(kit) / e['staged'], tmp)
        if sha256_file(tmp) != e['sha256']:
            raise SystemExit(f'pc_deploy install: {tmp} does not verify after the copy')
        os.replace(tmp, dest)
        if sha256_file(dest) != e['sha256']:
            raise SystemExit(f'pc_deploy install: {dest} does not verify after the copy')
        print(f"pc_deploy install: {e['path']} sha256 {e['sha256'][:12]} ok")
    rec.update({'kit_id': man['kit_id'], 'build_id': man['build_id'], 'installed_utc': stamp, 'owned': man['owned'],
                'files': [{k: e[k] for k in ('path', 'sha256', 'size')} for e in man['files']], 'mod_dir': man['mod_dir'],
                'exe_name': man['exe_name'], 'config_file': man['config_file'], 'game_config_files': man.get('game_config_files', []),
                'packs': man.get('packs', {})})
    rec['history'].append({'utc': stamp, 'action': 'install', 'kit_id': man['kit_id']})
    after = record_exe(rec, game, ident, 'install', stamp)
    rec_path.write_text(json.dumps(rec, indent=2) + '\n', encoding='utf-8')
    print(f"pc_deploy install: kit {man['kit_id']} installed (build {man['build_id']})")
    if after is not True:
        raise SystemExit('pc_deploy install: the exe is not vanilla after the install (see above)')
    return rec


def uninstall(game, state, assume_closed=False):
    game, state = Path(game), Path(state)
    rec_path = state / STATE_FILE
    if not rec_path.exists():
        raise SystemExit(f'pc_deploy uninstall: no {STATE_FILE} in {state}: nothing installed by this tool')
    rec = json.loads(rec_path.read_text(encoding='utf-8'))
    require_closed(game, rec, assume_closed, state)
    stamp = utc_stamp()
    for o in rec['owned']:   # the whole owned set, including what the DLL wrote at runtime (logs, dumps, DXVK caches, the notice)
        p = game / o.rstrip('/')
        if p.exists():
            move_out(p, state / '_to_delete' / f'uninstall_{stamp}' / o.rstrip('/'))
            print(f'pc_deploy uninstall: moved {o} to _to_delete')
    for b in rec['backups']:
        if not (state / b['backup']).exists():   # recorded just before a backup move that never happened (a failed install)
            continue
        move_out(state / b['backup'], game / b['path'])
        print(f"pc_deploy uninstall: restored the original {b['path']}")
    pre = json.loads((state / rec['pre_snapshot']).read_text(encoding='utf-8'))
    post = snapshot(game)
    diffs = diff_snapshots(pre, post)
    (state / 'snapshots').mkdir(exist_ok=True)
    (state / 'snapshots' / f'post_uninstall_{stamp}.json').write_text(json.dumps(post), encoding='utf-8')
    rec['history'].append({'utc': stamp, 'action': 'uninstall', 'identical': not diffs, 'diffs': diffs[:50]})
    exe_ok = record_exe(rec, game, rec.get('exe_identity') or default_identity(), 'uninstall', stamp)   # never refuses, only reports
    (state / 'history').mkdir(exist_ok=True)
    (state / 'history' / f'install_{stamp}.json').write_text(json.dumps(rec, indent=2) + '\n', encoding='utf-8')
    move_out(rec_path, state / '_to_delete' / f'uninstall_{stamp}' / STATE_FILE)
    if diffs:
        print('pc_deploy uninstall: game folder DIFFERS from the pre-install snapshot:\n  ' + '\n  '.join(diffs[:50]))
        return False
    if exe_ok is False:
        return False
    print(f'pc_deploy uninstall: game folder identical to the pre-install snapshot ({len(post)} files)')
    return True


# ---- config edits ---------------------------------------------------------------------------------------------------------------
def edit_ini(text, sets):
    """sets: {'proxy.backend': 'system'}. Replaces key lines in their section, appends missing ones; keeps CRLF and every other line."""
    nl = '\r\n' if '\r\n' in text else '\n'
    lines = text.split(nl)
    if lines and lines[-1] == '':
        lines.pop()
    todo = dict(sets)
    sec = None
    for i, l in enumerate(lines):
        s = l.strip()
        if s.startswith('[') and ']' in s:
            sec = s[1:s.index(']')].strip().lower()
        elif sec and '=' in s and not s.startswith((';', '#')):
            k = f"{sec}.{s.split('=', 1)[0].strip().lower()}"
            if k in todo:
                lines[i] = f"{k.split('.', 1)[1]}={todo.pop(k)}"
    for k, v in todo.items():
        sec, name = k.split('.', 1)
        idx = next((i for i, l in enumerate(lines) if l.strip().lower() == f'[{sec}]'), None)
        if idx is None:
            lines += ['', f'[{sec}]', f'{name}={v}']
        else:
            lines.insert(idx + 1, f'{name}={v}')
    return nl.join(lines) + nl


def resolve_keys(text, sets):
    """Bare names (`backend=system`) take the one section of the file that has them; an unknown or ambiguous bare name is a
    clear error, never a traceback (2026-10-28 PC test, proxy/runs/20261028_pctest: a bare key crashed `set`)."""
    sec, have = None, {}
    for l in text.splitlines():
        s = l.strip()
        if s.startswith('[') and ']' in s:
            sec = s[1:s.index(']')].strip().lower()
        elif sec and '=' in s and not s.startswith((';', '#')):
            have.setdefault(s.split('=', 1)[0].strip().lower(), []).append(sec)
    out = {}
    for k, v in sets.items():
        k = k.strip().lower()
        if '.' not in k:
            secs = have.get(k, [])
            if len(secs) != 1:
                known = ', '.join(sorted(f'{s}.{n}' for n, ss in have.items() for s in ss))
                raise SystemExit(f'pc_deploy set: key {k!r} is ' + ('ambiguous' if secs else 'not in the file')
                                 + f'; use section.key, one of: {known}')
            k = f'{secs[0]}.{k}'
        out[k] = v
    return out


def set_keys(game, pairs, config_file, state=None):
    """Returns 0, or 1 when the exe is not vanilla afterwards (checked after, never refused; recorded in install.json when there is one)."""
    if not config_file:   # the installed kit's name for it, else the identity's (a kit copy: the one beside it)
        rec0 = Path(state) / STATE_FILE if state else None
        config_file = (json.loads(rec0.read_text(encoding='utf-8')).get('config_file') if rec0 and rec0.exists() else None) or (default_identity() or {}).get('config_file')
        if not config_file:
            raise SystemExit('pc_deploy set: no --config-file and no install record or identity that names it')
    p = Path(game) / config_file
    bad = [x for x in pairs if '=' not in x]
    if bad:
        raise SystemExit(f'pc_deploy set: expected key=value, got {bad}')
    text = p.read_bytes().decode('utf-8')
    sets = resolve_keys(text, dict(x.split('=', 1) for x in pairs))
    p.write_bytes(edit_ini(text, sets).encode('utf-8'))
    print(f'pc_deploy set: {p.name}: ' + ', '.join(f'{k}={v}' for k, v in sets.items()))
    rec_path = Path(state) / STATE_FILE if state else None
    rec = json.loads(rec_path.read_text(encoding='utf-8')) if rec_path and rec_path.exists() else None
    ok = record_exe(rec, game, (rec or {}).get('exe_identity') or default_identity(), 'set', utc_stamp())
    if rec is not None:
        rec_path.write_text(json.dumps(rec, indent=2) + '\n', encoding='utf-8')
    return 1 if ok is False else 0


def status(game, state):
    game, state = Path(game), Path(state)
    rec_path = state / STATE_FILE
    rec = json.loads(rec_path.read_text(encoding='utf-8')) if rec_path.exists() else None
    fails, lines = pc_rules(game, state, (rec or {}).get('exe_identity') or default_identity())
    if rec is None:
        print('pc_deploy status: not installed by this tool')
        print('  ' + '\n  '.join(lines))
        return 1 if fails else 0
    print(f"pc_deploy status: kit {rec['kit_id']} build {rec['build_id']} installed {rec['installed_utc']}")
    bad = 0
    for f in rec['files']:
        p = game / f['path']
        ok = p.exists() and sha256_file(p) == f['sha256']
        bad += not ok
        print(f"  {'ok ' if ok else 'BAD'} {f['path']}")
    md = game / rec['mod_dir']
    dumps = sorted((md / 'dumps').glob('*.dmp')) if (md / 'dumps').exists() else []
    print(f"  dumps: {len(dumps)}{' ' + ', '.join(d.name for d in dumps) if dumps else ''}")
    print(f"  notice: {'EXE_MISMATCH.txt present' if (md / 'EXE_MISMATCH.txt').exists() else 'none'}")
    print('  ' + '\n  '.join(lines))
    return 1 if bad or fails else 0


def lua_files(adapter=None):
    """The repo's dev Lua files as (source, path under the game folder, mod_dir): the same set `kit` ships."""
    adir = proxy_adapter(adapter)
    ident = json.loads((adir / 'identity.json').read_text(encoding='utf-8'))
    ldir = adir / 'lua'
    return [(p, f"{ident['mod_dir']}/lua/" + p.relative_to(ldir).as_posix())
            for p in sorted(ldir.rglob('*')) if p.is_file() and p.suffix in ('.lua', '.txt') and p.name != 'wrappers.txt']


def sync_lua(game, state, adapter=None, assume_closed=False, dry_run=False):
    """Bring the installed Lua files (the dev scripts and battle presets) up to the repo's, no new kit: each changed file is staged under a
    unique name (<sha12>__<name>) beside its destination, sha-checked, then moved into place; the old copy goes to <state>/_to_delete and
    install.json is updated, so uninstall stays byte-exact. Files the install does not own are never touched. Returns the changed paths."""
    game, state = Path(game), Path(state)
    rec_path = state / STATE_FILE
    if not rec_path.exists():
        raise SystemExit('pc_deploy sync-lua: nothing is installed (no install.json): install a kit first')
    rec = json.loads(rec_path.read_text(encoding='utf-8'))
    if not dry_run:
        require_closed(game, rec, assume_closed, state)
    stamp = utc_stamp()
    known = {f['path']: f for f in rec['files']}
    changed = []
    for src, dest in lua_files(adapter):
        b = src.read_bytes()
        h = hashlib.sha256(b).hexdigest()
        target = game / dest
        if target.exists() and sha256_file(target) == h and dest in known:
            continue
        changed.append(dest)
        if dry_run:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(f'{h[:12]}__{target.name}.{stamp}.tmp')
        staged.write_bytes(b)
        if sha256_file(staged) != h:
            raise SystemExit(f'pc_deploy sync-lua: {staged} does not verify after the copy')
        if target.exists():
            move_out(target, state / '_to_delete' / stamp / dest)
        os.replace(staged, target)
        if sha256_file(target) != h:
            raise SystemExit(f'pc_deploy sync-lua: {target} does not verify after the copy')
        known[dest] = {'path': dest, 'sha256': h, 'size': len(b)}
        print(f'pc_deploy sync-lua: {dest} sha256 {h[:12]} ok')
    if changed and not dry_run:
        rec['files'] = list(known.values())
        rec['history'].append({'utc': stamp, 'action': 'sync-lua', 'files': changed})
    exe_ok = None if dry_run else record_exe(rec, game, rec.get('exe_identity') or default_identity(), 'sync-lua', stamp)   # never refuses
    if not dry_run:
        rec_path.write_text(json.dumps(rec, indent=2) + '\n', encoding='utf-8')
    print(f"pc_deploy sync-lua: {len(changed)} file(s) {'would change' if dry_run else 'changed'}")
    if exe_ok is False:
        raise SystemExit('pc_deploy sync-lua: the exe is not vanilla after the sync (see above)')
    return changed


def main():
    ap = argparse.ArgumentParser(description='proxy kit, install, uninstall')
    sub = ap.add_subparsers(dest='cmd', required=True)
    k = sub.add_parser('kit'); k.add_argument('--out', default=str(ROOT / 'build' / 'kits')); k.add_argument('--adapter', help='the proxy adapter folder (default: layout.py proxy-adapter)'); k.add_argument('--dll'); k.add_argument('--what', choices=['proxy', 'harness'], default='proxy')
    sd = sub.add_parser('send'); sd.add_argument('--kit', required=True); sd.add_argument('--state', required=True)
    s = sub.add_parser('snapshot'); s.add_argument('--game', required=True); s.add_argument('--out', required=True)
    i = sub.add_parser('install'); i.add_argument('--kit', required=True); i.add_argument('--game', required=True); i.add_argument('--state', required=True); i.add_argument('--assume-closed', action='store_true')
    u = sub.add_parser('uninstall'); u.add_argument('--game', required=True); u.add_argument('--state', required=True); u.add_argument('--assume-closed', action='store_true')
    c = sub.add_parser('set'); c.add_argument('--game', required=True); c.add_argument('--state'); c.add_argument('--config-file', help="the proxy's config file name (default: the identity's config_file)"); c.add_argument('pairs', nargs='+')
    st = sub.add_parser('status'); st.add_argument('--game', required=True); st.add_argument('--state', required=True)
    sl = sub.add_parser('sync-lua'); sl.add_argument('--game', required=True); sl.add_argument('--state', required=True); sl.add_argument('--assume-closed', action='store_true'); sl.add_argument('--dry-run', action='store_true')
    d = sub.add_parser('diff'); d.add_argument('a'); d.add_argument('b')
    a = ap.parse_args()
    if a.cmd == 'kit':
        if a.what == 'harness':
            build_harness_kit(a.out, a.adapter)
        else:
            build_kit(a.out, a.adapter, a.dll)
    elif a.cmd == 'send':
        send_kit(a.kit, a.state)
    elif a.cmd == 'snapshot':
        snap = snapshot(a.game)
        Path(a.out).write_text(json.dumps(snap), encoding='utf-8')
        print(f'pc_deploy snapshot: {len(snap)} entries -> {a.out}')
    elif a.cmd == 'install':
        install(a.kit, a.game, a.state, a.assume_closed)
    elif a.cmd == 'uninstall':
        return 0 if uninstall(a.game, a.state, a.assume_closed) else 1
    elif a.cmd == 'set':
        return set_keys(a.game, a.pairs, a.config_file, a.state)
    elif a.cmd == 'status':
        return status(a.game, a.state)
    elif a.cmd == 'sync-lua':
        sync_lua(a.game, a.state, assume_closed=a.assume_closed, dry_run=a.dry_run)
    elif a.cmd == 'diff':
        out = diff_snapshots(json.loads(Path(a.a).read_text()), json.loads(Path(a.b).read_text()))
        print('\n'.join(out) if out else 'identical')
        return 1 if out else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
