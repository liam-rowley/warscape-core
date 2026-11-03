"""The found-path rule for briefs (J5 ledger row 80, D14): a brief names a game-side path only as a registry id, never as a path somebody searched for.

purpose: flag game-side paths in a job brief (the extract store, pack-form paths, paths under a game folder that are not a registry id, layout and script paths a ui_elements unit holds) and parse a brief's `## Registry gaps` section
usage: from briefpaths import found_path_problems, load_known, registry_gaps   (called by a game's jobs-stage gate module, e.g. tools/gates/pipeline.py, so `python3 core/wsc.py jobs check` runs it)
when: before pushing a brief (jobs check), and in the tests gate (CI); the four flagged shapes and the escape hatch are listed in wsc.toml [jobs.text] brief_notes ("How a brief cites"), which every brief writer is shown
not-a-verb: a library; the verb is `wsc jobs check`

Pure functions of `text` and a `Known` (game folders, assets ids, ui_elements ids and their layout and script paths, the repo's tracked files), so
nothing here reads the game or the PC. `load_known(root)` builds `Known` once per process from the committed index, the registries and
`git ls-files`. Game-agnostic: a second game passes its own folders and ids.
"""
import json
import re
import subprocess
from pathlib import Path
from typing import NamedTuple

QUOTED = 'Quoted, not a citation:'
GAP_OWNER = re.compile(r'^(J\d+|liam)$')
EXTRACT = re.compile(r'/?extract/[^/]+/')   # the extract store of any game: derived, uncommitted
BS = chr(92)
EDGE = '"\'()[]<>,;:*!? '


class Known(NamedTuple):
    folders: frozenset      # top-level game folders (lowercase) of the asset index
    asset_ids: frozenset    # assets registry ids (forward-slash pack paths)
    ui_ids: frozenset       # ui_elements ids
    ui_paths: dict          # normalized layout or script path -> [unit ids]
    repo_files: frozenset   # git ls-files
    repo_dirs: frozenset    # every directory prefix of a tracked file


def norm(t):
    """A token as the registry spells paths: forward slashes, lowercase, no leading ./ and no trailing slash."""
    t = t.strip().replace('\\', '/').lower()
    while t.startswith('./'):
        t = t[2:]
    return t.rstrip('/')


def make_known(folders, asset_ids, ui_units, repo_files):
    """`ui_units`: {unit id: vanilla_source dict}. Each layout or script path is stored whole and without its leading '<context> ' word."""
    paths = {}
    for uid, src in ui_units.items():
        for field in ('layout', 'script'):
            for p in (src or {}).get(field, '').split(', '):
                if not p.strip():
                    continue
                k = norm(p)
                for key in {k, k.split(' ', 1)[-1]}:
                    paths.setdefault(key, [])
                    if uid not in paths[key]:
                        paths[key].append(uid)
    files = frozenset(repo_files)
    dirs = frozenset('/'.join(f.split('/')[:i]) for f in files for i in range(1, f.count('/') + 1))
    return Known(frozenset(f.lower() for f in folders), frozenset(asset_ids), frozenset(ui_units), paths, files, dirs)


_CACHE = {}


def load_known(root):
    """Known for this repo, built once per process (the index load is about 0.1 s)."""
    root = str(Path(root).resolve())
    if root in _CACHE:
        return _CACHE[root]
    import tsvgz
    r = Path(root)
    _, rows = tsvgz.read(str(r / 'discovery' / 'assets' / 'index.tsv.gz'))
    folders = {x[1].replace('\\', '/').split('/')[0] for x in rows if '\\' in x[1]}
    assets = [json.loads(x)['id'] for x in (r / 'registries' / 'assets.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    units = {}
    for x in (r / 'registries' / 'ui_elements.jsonl').read_text(encoding='utf-8').splitlines():
        if x.strip():
            u = json.loads(x)
            units[u['id']] = u.get('vanilla_source') or {}
    out = subprocess.run(['git', '-C', root, 'ls-files'], capture_output=True, text=True)
    files = [f for f in out.stdout.splitlines() if f]
    _CACHE[root] = make_known(folders, assets, units, files)
    return _CACHE[root]


def registry_gaps(text):
    """(gaps, problems) from a brief's `## Registry gaps` section: one bullet per path, `path: <p>; owner: <J<n>|liam>; reason: <why>`."""
    m = re.search(r'^## Registry gaps\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not m:
        return [], []
    gaps, bad = [], []
    for b in re.findall(r'^\s*[-*]\s+(.*)$', m.group(1), re.M):
        f = {k.strip().lower(): v.strip().strip('`') for k, v in (p.split(':', 1) for p in b.split(';') if ':' in p)}
        if not f.get('path'):
            bad.append(f'Registry gaps bullet has no "path: <path>": {b[:80]}')
        elif not GAP_OWNER.match(f.get('owner', '')):
            bad.append(f'Registry gaps bullet for `{f["path"]}` needs "owner: <job id or liam>"')
        elif not f.get('reason'):
            bad.append(f'Registry gaps bullet for `{f["path"]}` needs "reason: <why no registry row>"')
        else:
            gaps.append({'path': f['path'], 'owner': f['owner'], 'reason': f['reason']})
    return gaps, bad


def _tokens(line):
    """Candidate groups of one line: per backticked span [whole span, its separator-bearing words], and per bare word with a separator [word].
    A group reports at most one problem (the whole span first). Placeholders and globs (<name>, *, {x}) are patterns, not citations."""
    spans = re.findall(r'`([^`]+)`', line)
    rest = re.sub(r'`[^`]*`', ' ', line)
    groups = [[s] + [w for w in s.split() if w != s and ('/' in w or BS in w)] for s in spans]
    groups += [[w] for w in rest.split() if '/' in w or BS in w]
    out = []
    for g in groups:
        g = [t.strip(EDGE).rstrip('.').strip(EDGE) for t in g]
        g = [t for t in g if t and not re.search(r'[<>*{}]', t)]
        if g:
            out.append(g)
    return out


def _zones(lines):
    """Per line: 'quoted' (exempt), 'evidence' (exempt from the folder rule) or ''."""
    z = [''] * len(lines)
    in_fence = False
    fence_quoted = False
    quoted_bullet = False
    evidence = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith('```'):
            if not in_fence:
                fence_quoted = i > 0 and lines[i - 1].strip() == QUOTED
            in_fence = not in_fence
            z[i] = 'quoted' if fence_quoted else ''
            continue
        if in_fence:
            z[i] = 'quoted' if fence_quoted else ''
            continue
        if s.startswith('#'):
            evidence = 'evidence base' in s.lower()
        body = re.sub(r'^[-*]\s+', '', s)
        if not s:
            quoted_bullet = False
        if body.startswith(QUOTED):
            z[i] = 'quoted'
            quoted_bullet = True
            continue
        if quoted_bullet and ln[:1] in (' ', '\t') and s:
            z[i] = 'quoted'
            continue
        quoted_bullet = False
        if body.lower().startswith('evidence base'):
            z[i] = 'evidence'
        elif evidence:
            z[i] = 'evidence'
    # a paragraph continues an Evidence base bullet until the next blank line or bullet
    for i in range(1, len(lines)):
        if z[i - 1] == 'evidence' and lines[i].strip() and not lines[i].lstrip().startswith(('-', '*', '#')) and not z[i]:
            z[i] = 'evidence'
    return z


def _cite(known, n):
    return ('python3 core/wsc.py find <words> names the registry id'
            + (' (assets ids are the pack path with forward slashes)' if n in known.asset_ids else ''))


def token_problem(t, known, gap_paths=(), evidence=False):
    """Why token `t` is a found path, or None."""
    n = norm(t)
    if not n or '://' in n or n in gap_paths:
        return None
    if EXTRACT.match(n):
        return 'starts with the extract store, which is derived, uncommitted and PC-only; cite the registry id (python3 core/wsc.py find <words>)'
    if n in known.ui_paths and n not in known.repo_files:
        ids = known.ui_paths[n]
        return f'a layout or script path a ui_elements unit holds; cite the unit id {ids[0]}' + (f' (also {", ".join(ids[1:4])})' if len(ids) > 1 else '')
    first, _, rest = n.partition('/')
    if not rest or first not in known.folders:
        return None
    if '\\' in t:
        want = n if n in known.asset_ids else None
        return 'a pack-form path (backslashes under a game folder); cite the registry id' + (f' {want}' if want else ' (python3 core/wsc.py find <words>)')
    if evidence or n in known.asset_ids or n in known.ui_ids or n in known.repo_files or n in known.repo_dirs:
        return None
    return f'a path under the game folder "{first}" that is not a registry id; cite the id ({_cite(known, n)}) or list it under "## Registry gaps"'


def found_path_problems(text, known):
    """Errors for one brief text: ['line N: `token` ...']. Empty when the brief cites only registry ids, repo paths and quoted text."""
    gaps, bad = registry_gaps(text)
    gap_paths = {norm(g['path']) for g in gaps}
    errs = list(bad)
    lines = text.split('\n')
    zones = _zones(lines)
    in_gaps = False
    for i, ln in enumerate(lines):
        if ln.startswith('#'):
            in_gaps = ln.strip().lower() == '## registry gaps'
        if in_gaps or zones[i] == 'quoted':
            continue
        for group in _tokens(ln):
            for t in group:
                why = token_problem(t, known, gap_paths, zones[i] == 'evidence')
                if why:
                    errs.append(f'line {i + 1}: `{t}` is a found path: {why}')
                    break
    return errs
