"""Repo-wide text checks behind `wsc gates`. Each takes plain inputs (path lists, text) so host tests need no repo.

Ported from empire-remastered (2026-10-28): `orchestrator/tools/check_windows_paths.py`, `audit_repo.py` gates_fast
(conflict markers, strict JSON), gates_eol and undated_verified (with its narrowing rules and their tests).
"""
import json
import posixpath
import re
import subprocess

from .repo import git_env, matches

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


def no_duplicate_keys(pairs):
    """`object_pairs_hook` for repo data (W28): a key twice in one object is refused, never last-one-wins."""
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f'duplicate key {k!r}')
        out[k] = v
    return out


def strict_loads(text):
    """`json.loads` for repo data: NaN/Infinity and duplicate keys are refused (ValueError)."""
    return json.loads(text, parse_constant=_boom, object_pairs_hook=no_duplicate_keys)


def strict_json_error(text, jsonl=False):
    """None if `text` is strict JSON (or strict JSON Lines), else the error. NaN/Infinity, duplicate keys and a BOM are refused."""
    if text.startswith('﻿'):
        return 'starts with a byte-order mark'
    try:
        if jsonl:
            for i, line in enumerate(text.split('\n'), 1):
                if line.strip():
                    try:
                        strict_loads(line)
                    except ValueError as e:
                        return f'line {i}: {e}'
        else:
            strict_loads(text)
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
# a date or a run id, nothing looser (W28): an ISO date, a compact date (a run folder such as 20261104_a), or a path under reports/ runs/ records/.
# A link to a dated record passes through its date; "on PC", "in session", "3-10 times", "(see x.md)" and "v2" do not date a claim.
VD_DATED = re.compile(r'\d{4}-\d\d-\d\d|\b20\d{6}|reports/|runs/|records/')
VD_WORD = re.compile(r'\bverified\b', re.I)
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
        if not VD_WORD.search(l) or VD_DATED.search(l) or ctx.get(t) or item.get(t) or VD_NONCLAIM.search(l):
            continue
        if all(VD_ATTRIB.match(l, m.start()) for m in VD_WORD.finditer(l)):
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
        out = subprocess.run(['git', '-C', str(root), 'ls-files', '--eol'], capture_output=True, text=True, check=True, env=git_env()).stdout
    except (OSError, subprocess.CalledProcessError):
        return det
    for ln in out.splitlines():
        info, _, path = ln.partition('\t')
        if re.match(r'i/(crlf|mixed)\b', info) and path.endswith(('.py', '.sh')):
            det.append(f'CR in the index: {path}')
    return det


# ------------------------------------------------------------------ run README references (B13)
RUN_README = re.compile(r'(?:^|/)runs/(?:[^/]+/)*README\.md$')
RUN_DATE = re.compile(r'^(\d{4})-?(\d{2})-?(\d{2})_')
LINK_TARGET = re.compile(r'\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+(?:"[^"\n]*"|\'[^\'\n]*\'))?\s*\)')
BACKTICKED = re.compile(r'`([^`\n]+)`')
FENCE = re.compile(r'^\s*(```|~~~)')
URLISH = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*:')    # https://, mailto:, file: ... and a drive path (C:\ or C:/)
LINE_SUFFIX = re.compile(r':\d+(?:[-:]\d+)*$')
HAS_EXT = re.compile(r'\.[A-Za-z0-9_]{1,10}$')
NOT_A_PATH = re.compile(r'[*?<>{}|\\\s$%~^"\']|^[-/#@=]|=')


def run_readmes(paths):
    """The tracked `**/runs/**/README.md` among `paths`."""
    return sorted(p for p in paths if RUN_README.search(p))


def run_folder_date(path):
    """`YYYY-MM-DD` from the name of the run folder (the child of the `runs/` folder) that holds README `path`, or None when the name starts with no date
    (`YYYYMMDD_` or `YYYY-MM-DD_`)."""
    parts = path.split('/')
    if 'runs' not in parts[:-1]:
        return None
    i = parts.index('runs')
    m = RUN_DATE.match(parts[i + 1]) if i + 2 < len(parts) else None
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else None


def run_ref_tokens(text):
    """`[(line, token)]`: the repo paths a run README names. Markdown link targets (a path with a `/` or a file extension) and backticked
    tokens with a `/` that end in a file extension or `/`. Not URLs, absolute or drive paths, `%VAR%`, `$VAR` or `~` paths, backslash paths, a `..` range
    (`raw/chain1..3/`), nor anything with `* ? < > { } |` or a space (a command line). A trailing `:<line>` and punctuation are stripped; a link's
    `#anchor` is dropped. Lines inside a fenced code block are skipped (commands and log output)."""
    out, fenced = [], False
    for n, line in enumerate(text.split('\n'), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for m in LINK_TARGET.finditer(line):
            out.append((n, m.start(), m.group(1).split('#', 1)[0], True))
        for m in BACKTICKED.finditer(line):
            out.append((n, m.start(), m.group(1), False))
    seen, toks = set(), []
    for n, _, tok, link in sorted(out, key=lambda t: t[:2]):
        tok = LINE_SUFFIX.sub('', tok.strip().rstrip('.,;:)!'))
        tok = tok[2:] if tok.startswith('./') else tok
        if not tok or URLISH.match(tok) or NOT_A_PATH.search(tok) or any('..' in seg and seg != '..' for seg in tok.split('/')):
            continue
        if not (tok.endswith('/') or HAS_EXT.search(tok)) or not (link or '/' in tok):
            continue
        if (n, tok) not in seen:
            seen.add((n, tok))
            toks.append((n, tok))
    return toks


def run_ref_index(tracked):
    """What `run_ref_found` looks in: every tracked path, every folder above one, and every trailing sub-path of either (so `probes/x.lua` finds
    `adapter/probes/x.lua`)."""
    every = set()
    for p in tracked:
        parts = p.split('/')
        for i in range(len(parts)):
            every.add('/'.join(parts[i:]))
        for j in range(1, len(parts)):
            for i in range(j):
                every.add('/'.join(parts[i:j]))
    paths = set(tracked)
    for p in tracked:
        parts = p.split('/')
        paths.update('/'.join(parts[:j]) for j in range(1, len(parts)))
    return paths, every


def run_ref_found(token, readme, index, is_ignored=None):
    """True when `token` (a path a run README at `readme` names) exists: from the repo root, from the README's folder, as the tail of any tracked
    file or folder path, or ignored by git on purpose (build output named on purpose). `index`: `run_ref_index`."""
    paths, every = index
    base = readme.rsplit('/', 1)[0] if '/' in readme else ''
    rel = token.rstrip('/')
    cands = [rel]
    if base:
        cands.append(posixpath.normpath(f'{base}/{rel}'))
    cands = [c for c in cands if c and not c.startswith('../') and c != '..']
    if any(c in paths for c in cands) or rel in every:
        return True
    return bool(is_ignored and any(is_ignored(c) for c in cands))


def run_ref_problems(readmes, index, since='', is_ignored=None):
    """`(errors, checked, skipped)` for run READMEs `{path: text}`: each reference that is found nowhere, as `<readme>:<line>: names <token>, which ...`.
    A README whose run folder is dated before `since` (`YYYY-MM-DD`; empty = none skipped) is skipped and counted: a dated record's old paths are not
    wrong, only old."""
    errs, checked, skipped = [], 0, 0
    for path in sorted(readmes):
        d = run_folder_date(path)
        if since and d and d < since:
            skipped += 1
            continue
        for n, tok in run_ref_tokens(readmes[path]):
            checked += 1
            if not run_ref_found(tok, path, index, is_ignored):
                errs.append(f'{path}:{n}: names `{tok}`, which is not in the repo (commit the file, fix the path, or git-ignore it if it is build output)')
    return errs, checked, skipped


# ------------------------------------------------------------------ stale doc paths (W28, R11; B24 generalised)
MOVED_NOTE = re.compile(r'\(was [^)]*\)|\(moved\)')


def doc_path_tokens(text, ignore=()):
    """`[(line, token)]`: the backticked tokens of a living doc that look like a repo path: a `/` in it, a file extension or a trailing `/`, no space, none of `* ? < > { } | $ % ~`
    and the rest of `NOT_A_PATH`, no scheme or drive letter, not in `ignore` (`[docs] path_ignore`: exact tokens, or globs). A trailing `:<line>`,
    punctuation and a `#anchor` are dropped. Fenced blocks and a line that carries `(was <path>)` or `(moved)` are skipped."""
    out, fenced = [], False
    for n, line in enumerate(text.split('\n'), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced or MOVED_NOTE.search(line):
            continue
        for m in BACKTICKED.finditer(line):
            tok = LINE_SUFFIX.sub('', m.group(1).strip().split('#', 1)[0].rstrip('.,;:)!'))
            tok = tok[2:] if tok.startswith('./') else tok
            if '/' not in tok or URLISH.match(tok) or NOT_A_PATH.search(tok) or not (tok.endswith('/') or HAS_EXT.search(tok)):
                continue   # a file has an extension and a folder ends in `/`: `origin/main`, `job/W28` and `actions/cache` are not paths
            if tok in ignore or matches(tok, [g for g in ignore if any(c in g for c in '*?')]):
                continue
            out.append((n, tok))
    return out


def doc_path_found(token, doc, paths):
    """True when `token` (named in living doc `doc`) is a tracked file or a folder above one (`paths`: `run_ref_index(tracked)[0]`), from the
    repo root, from the doc's own folder, or across the `core/` submodule boundary (`core/<p>` in the core is `<p>`; `<p>` in a game may be `core/<p>`)."""
    rel = token.rstrip('/')
    base = doc.rsplit('/', 1)[0] if '/' in doc else ''
    cands = [rel, f'core/{rel}'] + ([rel[5:]] if rel.startswith('core/') else [])
    if base:
        cands.append(posixpath.normpath(f'{base}/{rel}'))
    return any(c in paths for c in cands if c and c != '.')


def stale_doc_paths(docs, paths, ignore=()):
    """`<doc>:<line>: path not found: <token>` for each backticked repo path in living docs `{path: text}` that `doc_path_found` cannot find."""
    errs = []
    for doc in sorted(docs):
        errs += [f'{doc}:{n}: path not found: {tok}' for n, tok in doc_path_tokens(docs[doc], ignore) if not doc_path_found(tok, doc, paths)]
    return errs
