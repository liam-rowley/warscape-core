"""The tools registry: rows derived from file headers, plus the coverage check.

A tool's header sits in its first 40 lines, as comment lines (`#`, `rem`, `::`, `--`, `//`, `;`) or inside a Python docstring:
    purpose: what it does (one line)
    usage:   how to run it
    when:    when to reach for it
    verb:    <name>        if it implements a `wsc` verb, or
    not-a-verb: <reason>   why it is a standalone script instead
The header is the source; `wsc reg add tools <path>` copies it into the row, and the check fails when they drift.
(Ported from empire-remastered `orchestrator/tools/gen_tools_index.py`, header-first; the first-sentence fallback is dropped: no header, no row.)
"""
import datetime
import re
from pathlib import Path

from .repo import matches

HDR = re.compile(r'^\s*(?:#|rem\b|::|--|//|;)\s*(purpose|usage|when(?: to use)?|verb|not[- ]a[- ]verb)(?:\s*\([^)]*\))?:\s*(.+?)\s*$', re.I)
DOC = re.compile(r'^\s*(?:[rR]?"""|\'\'\')?\s*(purpose|usage|when(?: to use)?|verb|not[- ]a[- ]verb)(?:\s*\([^)]*\))?:\s*(.+?)\s*$', re.I)
HEADER_FIELDS = ('kind', 'path', 'purpose', 'usage', 'when', 'verb', 'not_a_verb')   # set from the header, never by `reg set`


def _key(k):
    k = k.lower()
    return 'when' if k.startswith('when') else 'not_a_verb' if k.startswith('not') else k


def read_header(path):
    out = {}
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            indoc = False
            for i, line in enumerate(f):
                if i >= 40:
                    break
                m = HDR.match(line)
                if not m and (indoc or '"""' in line or "'''" in line):
                    m = DOC.match(line)
                if m and _key(m.group(1)) not in out:
                    out[_key(m.group(1))] = m.group(2).rstrip('"\'').strip()
                n = line.count('"""') + line.count("'''")
                if n % 2:
                    indoc = not indoc
    except OSError:
        pass
    return out


def slug(path):
    stem = path.rsplit('.', 1)[0] if '.' in path.rsplit('/', 1)[-1].lstrip('.') else path
    return re.sub(r'[^a-z0-9_.-]+', '-', stem.lower().lstrip('.').replace('/', '.')).strip('-.')


def is_tool(path, tcfg):
    ext = path.rsplit('.', 1)[-1] if '.' in path.rsplit('/', 1)[-1] else ''
    return (ext in tcfg['extensions'] or matches(path, tcfg['include'])) and not matches(path, tcfg['library']) and not matches(path, tcfg['exempt'])


def tool_files(ctx):
    return [p for p in ctx.files() if is_tool(p, ctx.config['tools'])]


def header_problems(h):
    errs = [f'header has no `{k}:` line' for k in ('purpose', 'usage', 'when') if not h.get(k)]
    if h.get('verb') and h.get('not_a_verb'):
        errs.append('header has both `verb:` and `not-a-verb:` (pick one)')
    elif not h.get('verb') and not h.get('not_a_verb'):
        errs.append('header has neither `verb: <name>` nor `not-a-verb: <reason>` (every tool is a verb, or says why not)')
    return errs


def row_from_header(path, h, rid=None, old=None):
    row = {'id': rid or (old or {}).get('id') or (f"wsc.{h['verb']}" if h.get('verb') else slug(path)), 'kind': 'verb' if h.get('verb') else 'script', 'path': path,
           'purpose': h.get('purpose', ''), 'usage': h.get('usage', ''), 'when': h.get('when', '')}
    if h.get('verb'):
        row['verb'] = h['verb']
    else:
        row['not_a_verb'] = h.get('not_a_verb', '')
    row['status'] = (old or {}).get('status', 'live')
    row['last_used'] = (old or {}).get('last_used') or datetime.date.today().isoformat()
    return row


def add_paths(ctx, reg, paths, rid=None, status=None):
    """Create or refresh rows from headers; returns messages. Raises ValueError on a missing or incomplete header."""
    msgs = []
    for p in paths:
        cand = Path(p.replace('\\', '/'))
        if not cand.is_absolute():   # relative to the shell's folder when it exists there, else to the repo root
            cand = Path.cwd() / cand if (Path.cwd() / cand).exists() else ctx.root / cand
        full = cand.resolve()
        try:
            p = full.relative_to(ctx.root).as_posix()
        except ValueError:
            raise ValueError(f'{p} is outside the repo root {ctx.root}') from None
        if not full.is_file():
            raise ValueError(f'no such file: {p}')
        h = read_header(full)
        bad = header_problems(h)
        if bad:
            raise ValueError(f'{p}: ' + '; '.join(bad) + ' (header format: `warscape/tools.py`)')
        old = next((r for r in reg.rows if r.get('path') == p), None)
        row = row_from_header(p, h, rid, old)
        if status:
            row['status'] = status
        if old and old['id'] != row['id']:
            reg.rows = [r for r in reg.rows if r is not old]
        reg.add(row, replace=True)
        msgs.append(f'{"updated" if old else "added  "} {row["id"]}  ({p}, {row["kind"]}, {row["status"]})')
    return msgs


def missing(ctx, reg):
    have = {r.get('path') for r in reg.rows}
    return [p for p in tool_files(ctx) if p not in have]


def check(ctx, reg):
    """(errors, warnings) for tool coverage and header drift."""
    errs, warns = [], []
    rows = reg.rows
    by_path = {r.get('path'): r for r in rows}
    ids = {r.get('id') for r in rows}
    for p in tool_files(ctx):
        h = read_header(ctx.root / p)
        bad = header_problems(h)
        if bad:
            errs.append(f'{p}: ' + '; '.join(bad))
        r = by_path.get(p)
        if r is None:
            errs.append(f'{p}: tool without a registry row (run `wsc reg add tools {p}`)')
            continue
        if not bad:
            want = row_from_header(p, h, r['id'], r)
            drift = [k for k in HEADER_FIELDS if want.get(k) != r.get(k)]
            if drift:
                errs.append(f'{p}: row differs from the file header in {", ".join(drift)} (run `wsc reg add tools {p}`)')
    files = set(ctx.files())
    for r in rows:
        st = r.get('status', '')
        if st == 'live' and r.get('path') not in files:
            errs.append(f'{reg.rel_path}: {r.get("id")}: live row whose file {r.get("path")!r} does not exist (git rm leftover: supersede it or remove the row)')
        if st.startswith('superseded:'):
            tgt = st.split(':', 1)[1]
            if tgt not in ids:
                errs.append(f'{reg.rel_path}: {r.get("id")}: superseded by {tgt!r}, which is not a tool id')
            elif tgt == r.get('id'):
                errs.append(f'{reg.rel_path}: {r.get("id")}: superseded by itself')
    days = ctx.config['tools']['retire_after_days']
    if days:
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        for r in rows:
            if r.get('status') == 'live' and r.get('last_used', '9999') < cutoff:
                warns.append(f'{r.get("id")}: live but last used {r["last_used"]} (over {days} days): retire it (status superseded:<id>) or record a use')
    return errs, warns
