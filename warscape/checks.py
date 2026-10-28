"""Repo-wide text checks behind `wsc gates`. Each takes plain inputs (path lists, text) so host tests need no repo.

Ported from empire-remastered (2026-10-28): `orchestrator/tools/check_windows_paths.py`, `audit_repo.py` gates_fast
(conflict markers, strict JSON), gates_eol and undated_verified (with its narrowing rules and their tests).
"""
import json
import re
import subprocess

from .repo import matches

# ------------------------------------------------------------------ Windows-safe paths
WIN_RESERVED = re.compile(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$', re.I)
WIN_BAD = re.compile(r'[<>:"|?*\\\x00-\x1f]|[ .]$')


def windows_path_errors(paths):
    errs, seen = [], {}
    for p in paths:
        if any(WIN_RESERVED.match(s) or WIN_BAD.search(s) for s in p.split('/')):
            errs.append(f'invalid on Windows: {p}')
        k = p.casefold()
        if k in seen and seen[k] != p:
            errs.append(f'case clash: {seen[k]} / {p}')
        seen.setdefault(k, p)
    # a file and a folder whose names differ only in case clash too
    dirs = {}
    for p in paths:
        parts = p.split('/')
        for i in range(1, len(parts)):
            d = '/'.join(parts[:i])
            if d.casefold() in dirs and dirs[d.casefold()] != d:
                errs.append(f'case clash: folder {dirs[d.casefold()]}/ / {d}/')
            dirs.setdefault(d.casefold(), d)
    return sorted(set(errs))


# ------------------------------------------------------------------ strict JSON
def _boom(c):
    raise ValueError(f'non-finite constant {c}')


def strict_json_error(text, jsonl=False):
    """None if `text` is strict JSON (or strict JSON Lines), else the error. NaN/Infinity are refused; a BOM is refused."""
    if text.startswith('﻿'):
        return 'starts with a byte-order mark'
    try:
        if jsonl:
            for i, line in enumerate(text.split('\n'), 1):
                if line.strip():
                    try:
                        json.loads(line, parse_constant=_boom)
                    except ValueError as e:
                        return f'line {i}: {e}'
        else:
            json.loads(text, parse_constant=_boom)
    except ValueError as e:
        return str(e)
    return None


# ------------------------------------------------------------------ conflict markers
def has_conflict_trio(text):
    """Line of the first full <<<<<<< / ======= / >>>>>>> trio (a lone rule line or a quoted marker is not a conflict), else 0."""
    st, at = 0, 0
    for i, l in enumerate(text.split('\n'), 1):
        if st == 0 and l.startswith('<<<<<<< '):
            st, at = 1, i
        elif st == 1 and l.rstrip() == '=======':
            st = 2
        elif st == 2 and l.startswith('>>>>>>> '):
            return at
    return 0


# ------------------------------------------------------------------ docs: which are living, size cap
DATED_NAME = re.compile(r'(19|20)\d\d-\d\d-\d\d|(?<!\d)(19|20)\d{6}(?!\d)')


def living_docs(paths, dcfg, generated=()):
    """Living docs: match docs.living, not a dated record (records glob, or a date in the file name), not exempt, not generated."""
    gen = set(generated)
    out = []
    for p in paths:
        if p in gen or not matches(p, dcfg['living']) or matches(p, dcfg['exempt']):
            continue
        if matches(p, dcfg['records']) or DATED_NAME.search(p.rsplit('/', 1)[-1]):
            continue
        out.append(p)
    return out


def oversize(sizes, max_kb):
    """[(path, bytes)] over the cap; `sizes` is {path: bytes}. KB is KiB (1024 bytes)."""
    cap = int(max_kb * 1024)
    return [(p, n) for p, n in sorted(sizes.items()) if n > cap]


# ------------------------------------------------------------------ undated "verified" (empire audit_repo.py sot.verified_dates, 2026-10-28)
VD_DATED = re.compile(r'\d{4}-\d\d-\d\d|\b20\d{6}|\b\d{1,2}-\d{2}\b|reports/|runs/|records/|\.md\)|session|\bv\d')
VD_NONCLAIM = re.compile(r'\bunverified\b|\bnot\W{0,4}(?:yet\W+)?verified|\b(?:nothing|never|none)\b[^.|]{0,40}\bverified|["“`]\s*verified\b|\[V\]|\bwhat\b[^.|]{0,12}\bverified\b'
                         r'|\b(?:sha\d*|md5|crc\d*|byte|hash|checksum)[- ]verified'
                         r'|\b(?:to be|must be|should be|will be|can be|needs? to be|be)\s+(?:re-?)?verified'
                         r'|\b(?:until|once|if|when|unless)\b[^.;|]{0,60}\b(?:is|are)\s+(?:re-?)?verified', re.I)
VD_ATTRIB = re.compile(r'\bverified\s+(?!(?:in|by|on|at|as|to|for|from|with|within|without|against|via|across|after|before|during|once|when|while|then|and|or|but|nor|so|the|a|an|it|its|that|this|these|those|both|all|each|every|no|not|live|clean|true|ok|fine|correct|exact|exactly|again|twice|too|also|only|now|here|there)\b)[a-z][\w-]*', re.I)
ITEM = re.compile(r'\s*(?:[-*+]|\d+[.)])\s')


def undated_verified(lines):
    """1-based line numbers that claim "verified" with no date or run id. A table row inherits a date or run id from its header row or
    a short caption line above the table; a wrapped list item is one statement; code fences are skipped."""
    ctx, i, n = {}, 0, len(lines)
    while i < n:
        if not lines[i].lstrip().startswith('|'):
            i += 1
            continue
        j = i
        while j < n and lines[j].lstrip().startswith('|'):
            j += 1
        k = i - 1
        if k >= 0 and not lines[k].strip():
            k -= 1
        cap = lines[k] if k >= 0 and len(lines[k]) <= 300 else ''
        d = bool(VD_DATED.search(lines[i]) or VD_DATED.search(cap))
        for t in range(i, j):
            ctx[t] = d
        i = j
    item, t = {}, 0
    while t < n:
        if not ITEM.match(lines[t]):
            t += 1
            continue
        u = t + 1
        while u < n and lines[u].strip() and not re.match(r'\s*(?:[-*+]|\d+[.)])\s|#|\s*\|', lines[u]):
            u += 1
        d = any(VD_DATED.search(lines[x]) for x in range(t, u))
        for x in range(t, u):
            item[x] = d
        t = u
    fence, out = False, []
    for t, l in enumerate(lines):
        if re.match(r'\s*(```|~~~)', l):
            fence = not fence
            continue
        if fence:
            continue
        if not re.search(r'\b[Vv]erified\b', l) or VD_DATED.search(l) or ctx.get(t) or item.get(t) or VD_NONCLAIM.search(l):
            continue
        if all(VD_ATTRIB.match(l, m.start()) for m in re.finditer(r'\b[Vv]erified\b', l)):
            continue
        out.append(t + 1)
    return out


# ------------------------------------------------------------------ line endings (warn only)
def eol_problems(root):
    """Tracked .py/.sh with a CR in the index (a CR in a shebang breaks the script on Linux); .gitattributes missing."""
    det = []
    if not (root / '.gitattributes').is_file():
        det.append('.gitattributes is missing (copy the core\'s line-ending policy)')
    try:
        out = subprocess.run(['git', '-C', str(root), 'ls-files', '--eol'], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return det
    for ln in out.splitlines():
        info, _, path = ln.partition('\t')
        if re.match(r'i/(crlf|mixed)\b', info) and path.endswith(('.py', '.sh')):
            det.append(f'CR in the index: {path}')
    return det
