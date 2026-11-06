"""The job queue, as library code (verb: warscape/verbs/jobs.py): the queue rules, the readiness rule, branch reading, the step texts, the
status page and its launch server. Moved from napoleon-remastered `tools/verbs/jobs.py` (napoleon J62); every game-specific string and
rule is repo configuration (`wsc.toml` [jobs], [jobs.text]) or a game gate module (`warscape/gatemods.py`, stages `jobs` and `view`), so a repo with
none of them is a plain queue.

Settings: the module-level `S` holds what the repo configured (`configure(ctx)` fills it from `ctx.config['jobs']`; the defaults are the
generic ones). Tests that want a different configuration call `configure_from(cfg)`.

Rules in short (details in docs/REVIEW.md of the repo that uses them): rows are checked against `jobs/<id>/` files; a job is built on branch
`job/<id>`, briefed on `brief/<id>`; review.md holds `## Round N (YYYY-MM-DD, branch job/<id> at <sha>)` sections, newest first, at most 3, one
verdict each; the reviewer sets the row (merge -> done, otherwise fix, or blocked after round 3); `--serve --auto` starts ready reviews and fixes.
Review claims (core W27): `jobs review` and the autopilot claim round n with the remote ref refs/claims/<id>/round-<n> (warscape/claims.py)
before a reviewer starts; a refused claim names its holder. A job may carry jobs/<id>/handback.md (the builder subagent's own words); its
report.md then has a "## Orchestrator additions" section.
`claude agents --json --all` (Claude Code 2.1.319, read on the PC 2026-11-06, W41; plain `--json` no longer lists finished sessions): a background row has
`kind` "background", `id`, `state` "working", "blocked" (waiting for input), "done", "stopped" or "failed", and `pid` while it has a process, which a
session can lose in any state and keep after it is done; an interactive row has a `pid` but no `id` or `state`. Live (the same-name and PC holder checks)
= working or blocked. The session cap (`[jobs] max_sessions`, W41) counts something else: a background row with a pid, because the cap is for memory (napoleon D59).
"""
import base64
import hashlib
import html
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple, Optional

from . import ci, gatemods
from .checks import strict_loads
from .gitbash import git_bash
from .policy import verdict
from .repo import DEFAULTS, decisions_registry, git_env



class Settings:
    """What the repo configured for the queue (`wsc.toml` [jobs]); the defaults here are the plain, generic queue."""
    prefix = 'J'
    models = ['sonnet', 'opus']
    jobs_dir = 'jobs'
    reg_dir = 'registries'
    ledgers = ''
    failed_results = ''
    semver_from = 0
    usage_from = 0
    usage_cmd = ''
    root = None
    grants = {}   # job id -> extra review rounds the owner granted (W132): decision rows with `grants_round`
    legacy_rounds = frozenset()
    legacy_briefs = frozenset()
    pc_state = ''   # [jobs] pc_state: the PC state folder a needs_pc build needs ('' = no gating; WSC_PC_STATE overrides it, W26)
    max_sessions = 0   # [jobs] max_sessions: background sessions with a process that a launch may not reach (0 = no cap, W41)
    text = dict(DEFAULTS['jobs']['text'])


S = Settings()


def read_grants(folder):
    """{job id: number of decision rows naming it in `grants_round`} of a decisions folder (W132). The rows are append only and `policy`
    admits one only from a `meta/` branch, so the folder of the checked-out tree is as good as the base's once it has merged main (`grant_hint`)."""
    out = {}
    for f in sorted(Path(folder).glob('*.json')) if folder else ():
        try:
            j = strict_loads(f.read_text(encoding='utf-8')).get('grants_round')
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(j, str):
            out[j] = out.get(j, 0) + 1
    return out


def max_rounds(jid, grants=None):
    """Review rounds job `jid` may have: MAX_ROUNDS plus one per grant row naming it (W132)."""
    return MAX_ROUNDS + (S.grants if grants is None else grants).get(jid, 0)


def blocked_by_rounds(jid, grants=None):
    return f'{max_rounds(jid, grants)} review rounds without merge'


def grant_hint():
    return f'the owner can grant one more, {S.text.get("review_doc", "docs/REVIEW.md")} "Rounds", and a grant on main counts here only once this branch has merged main'


def configure_from(cfg, root=None, reg_dir='registries', decisions=''):
    """Fill S from a `[jobs]` table (defaults merged) and, when `root` is given, its legacy file and the owner's round grants."""
    S.prefix, S.models, S.jobs_dir, S.reg_dir, S.ledgers = cfg['id_prefix'], list(cfg['models']), cfg['dir'], reg_dir, cfg['ledgers']
    S.failed_results, S.root = cfg.get('failed_results', ''), (Path(root) if root is not None else None)
    S.semver_from = cfg.get('semver_from', 0)
    S.usage_from, S.usage_cmd = cfg.get('usage_from', 0), cfg.get('usage_cmd', '')
    S.text = dict(cfg['text'])
    S.pc_state = cfg.get('pc_state', '')
    S.max_sessions = cfg.get('max_sessions', 0)
    S.legacy_rounds = S.legacy_briefs = frozenset()
    S.grants = read_grants(Path(root) / reg_dir / decisions) if root is not None and decisions else {}
    if root is not None:
        if cfg['legacy']:
            data = strict_loads((Path(root) / cfg['legacy']).read_text(encoding='utf-8'))
            S.legacy_rounds, S.legacy_briefs = frozenset(data.get('round_rules', [])), frozenset(data.get('brief_hooks', []))
    return S


def configure(ctx):
    return configure_from(ctx.config['jobs'], ctx.root, ctx.config['registries_dir'], decisions_registry(ctx.config) if 'policy' in ctx.config else '')


def ref(key, fmt=' ({})'):
    """A reference text from [jobs.text] formatted into a message, or '' when the repo set none."""
    v = S.text.get(key, '')
    return fmt.format(v) if v else ''


def briefs(rows, read):
    """(jid, row, text) for every row whose brief exists, in id order, skipping the legacy file's `brief_hooks` ids (jobs frozen before a
    game's brief rules existed; the JSON key keeps the name it had when those rules were hooks). What a `jobs`-stage gate module reads as
    `ctx.briefs()`."""
    for r in sorted(rows, key=lambda r: num(r['id'])):
        text = read(f'{S.jobs_dir}/{r["id"]}/brief.md')
        if text is not None and r['id'] not in S.legacy_briefs:
            yield r['id'], r, text


def check(ctx, rows, read, folders=()):
    """The whole queue check (`wsc jobs check` and the `jobs` gate): the core rules, then the repo's `jobs`-stage gate modules
    (warscape/gatemods.py). Returns (errors, warnings, summaries): the modules' non-empty summaries go on the `jobs check` line."""
    res = gatemods.run_stage(ctx, 'jobs', rows=rows, read=read, briefs=lambda: briefs(rows, read))
    errs = views_problems(ctx.config) + problems(rows, read, folders) + gatemods.problems(res)
    summaries = [r.summary for r in res if r.summary and not (r.level == 'error' and not r.details)]
    return errs, gatemods.problems(res, 'warn'), summaries


def views_problems(config):
    """C19 (B49): a repo with a `jobs` registry cannot commit its registry views. `reg set` rewrites `<registries_dir>/jobs.md`, `policy` refuses
    that file on a `brief/` branch and the `registries` gate refuses the branch without it, so no brief branch could ever pass."""
    if 'jobs' in config['registries'] and config['views']['commit']:
        return [f"views are committed beside a jobs registry: set `[views] commit = false` in wsc.toml (C19), git rm the committed "
                f"`{config['registries_dir']}/*.md` views and git-ignore the views dir (`{config['views']['dir']}`)"]
    return []


STATUSES_WITH = {'brief': {'queued', 'review', 'fix', 'done'}, 'report': {'review', 'fix', 'done'}, 'review': {'fix', 'done'}}
DATED = re.compile(r'\b20\d\d-\d\d-\d\d\b')
ROUND = re.compile(r'^## Round\b.*$', re.M)
ROUND_HEAD = re.compile(r'^## Round ([1-9]\d*) \(20\d\d-\d\d-\d\d, branch `?job/[A-Z]\d+`? at `?[0-9a-f]{7,40}`?\)\s*$')
MAX_ROUNDS = 3
def num(jid):
    return int(jid[1:]) if re.fullmatch(r'[A-Z]\d+', jid or '') else 10 ** 9


def semver_rule(jid):
    """True when job `jid` falls under the semver rule (W29, C27): `[jobs] semver_from` is set and the job number is at or above it."""
    return bool(getattr(S, 'semver_from', 0)) and num(jid) >= S.semver_from


# ------------------------------------------------------------------ check
def brief_problems(jid, row, text):
    """Shape every brief must have (the Model line rule and the Finish rule): Model line agreeing with the row (a reason when Opus), a call budget,
    kill criteria, and a Finish section that ends with the status=review command. A game's own brief rules are a `jobs`-stage gate module
    reading `ctx.briefs()` (warscape/gatemods.py)."""
    errs = []
    if not re.search(rf'^# {jid}:', text, re.M):
        errs.append(f'first heading is not "# {jid}: <title>"')
    m = re.search(r'^Model:\s*(\w+)(.*)$', text, re.M)
    if not m:
        errs.append(f'no "Model: <{"|".join(m.title() for m in S.models)}> ..." line' + ref('ref_models'))
    else:
        if m.group(1).lower() != row.get('model'):
            errs.append(f'Model line says {m.group(1)}, the row says {row.get("model")}')
        if m.group(1).lower() in S.models[1:] and not re.search(r'\breason\b', m.group(2), re.I):
            errs.append(f'{m.group(1).title()} without "reason:" on the Model line' + ref('ref_models', ' ({}: ' + m.group(1).title() + ' only with a stated reason)'))
    if semver_rule(jid):   # W29 (C27): the Semver line agrees with the row, and the brief no longer owns VERSION
        sv = re.search(r'^Semver:\s*(\w+)', text, re.M)
        if not sv:
            errs.append(f'no "Semver: <patch|minor|major|none>" line (from {S.prefix}{S.semver_from} on the release workflow owns VERSION, C27)')
        elif sv.group(1).lower() != row.get('semver'):
            errs.append(f'Semver line says {sv.group(1)}, the row says {row.get("semver")}')
        if re.search(r'^## VERSION\b', text, re.M):
            errs.append('a "## VERSION" section: the release workflow owns VERSION (C27); the Semver line replaces it')
    if brief_budget(text) is None:
        errs.append('no call budget ("Budget about <n> tool calls"' + ref('ref_models', ', {}') + ')')
    kill = re.search(r'^## Kill criteria\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not kill or not re.search(r'^\s*- ', kill.group(1), re.M):
        errs.append('no "## Kill criteria" section with at least one bullet' + ref('ref_models'))
    fin = re.search(r'^## Finish\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    cmd = f'wsc reg set jobs {jid} status=review report={S.jobs_dir}/{jid}/report.md'
    if not fin or cmd not in fin.group(1):
        errs.append(f'no "## Finish" section ending with `{cmd}`')
    return errs


def report_problems(jid, text):
    """Every report says what was built, its deviations and its open questions."""
    errs = []
    if not re.search(rf'^# {jid} report\b', text, re.M):
        errs.append(f'first heading is not "# {jid} report: <title>"')
    for h in ('Deviations', 'Open questions'):
        if not re.search(rf'^## {h}\b', text, re.M):
            errs.append(f'no "## {h} ..." section')
    return errs


# ------------------------------------------------------------------ usage accounting (W31)
BUDGET = re.compile(r'[Bb]udget\s+about\s+([0-9]{1,9})\s+tool\s+calls')
USAGE_SHAPE = 'Usage: <n> tool calls; models: <m1>, <m2>; <free text>'
USAGE_LINE = re.compile(r'Usage:\s*([0-9]{1,9})\s+tool\s+calls\s*;\s*models:\s*([^;]+?)\s*;\s*(\S.*?)\s*\Z')
USAGE_MODEL = re.compile(r'[A-Za-z][\w. -]*\Z')
USAGE_TIMEOUT = 60   # seconds a game's usage_cmd may take
FENCE = re.compile(r' {0,3}(`{3,}|~{3,})(.*)')


class Usage(NamedTuple):
    """A report's `Usage:` line: its tool calls, its models as written, its free text."""
    calls: int
    models: list
    note: str


def brief_budget(text):
    """The brief's `Budget about <n> tool calls` as an int, or None."""
    m = BUDGET.search(text or '')
    return int(m.group(1)) if m else None


def is_count(v):
    return isinstance(v, int) and not isinstance(v, bool)


def effective_budget(row, brief):
    """The budget a job is held to: `to` of the newest `budget_lifts` entry (the last; lift_problems keeps the chain rising), else the brief's."""
    lifts = row.get('budget_lifts')
    if isinstance(lifts, list) and lifts and isinstance(lifts[-1], dict) and is_count(lifts[-1].get('to')):
        return lifts[-1]['to']
    return brief_budget(brief)


def over_budget(calls, budget):
    """True above 1.25 x the budget, in whole numbers (150 allows 187, not 188). No budget: never (brief_problems reports that)."""
    return budget is not None and calls * 4 > budget * 5


def model_family(name):
    """The first word of a model name, lower case: what a report's model and the row's `model` are compared by."""
    m = re.match(r'[a-z0-9]+', str(name).strip().lower())
    return m.group(0) if m else ''


def unfenced(lines):
    """(index, line) of each line outside a fenced code block. A backtick run with a backtick after it on the line is inline code, not a fence."""
    fence = ''
    for i, l in enumerate(lines):
        m = FENCE.match(l.rstrip('\r'))
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                fence = ''
        elif m and not (m.group(1)[0] == '`' and '`' in m.group(2)):
            fence = m.group(1)
        else:
            yield i, l


def usage_hits(lines):
    return [i for i, l in unfenced(lines) if l.startswith('Usage:')]


def parse_usage(report):
    """(Usage, None), or (None, why) for a report with no `Usage:` line, more than one, or one not in the shape. A line in a code fence does not count."""
    lines = report.split('\n')
    hits = usage_hits(lines)
    if not hits:
        return None, f'no "{USAGE_SHAPE}" line'
    if len(hits) > 1:
        return None, 'two "Usage:" lines or more: keep one'
    line = lines[hits[0]].rstrip()
    m = USAGE_LINE.match(line)
    models = [x.strip() for x in m.group(2).split(',')] if m else []
    if not m or not all(USAGE_MODEL.match(x) for x in models):
        return None, f'"{line[:80]}" does not parse: the shape is "{USAGE_SHAPE}"'
    return Usage(int(m.group(1)), models, m.group(3)), None


def usage_rule(jid):
    """True when job `jid` falls under the usage rule (W31): `[jobs] usage_from` is set and the job number is at or above it."""
    return bool(getattr(S, 'usage_from', 0)) and num(jid) >= S.usage_from


def usage_write(jid):
    """The command that fills a report's line: the game's reader, or by hand with no `[jobs] usage_cmd`."""
    return f'{S.text["wsc"]} jobs usage {jid} --write' + ('' if getattr(S, 'usage_cmd', '') else ' --from-json <file>')


def lift_problems(row, brief):
    """The chain of a row's `budget_lifts`: each entry raises the budget, starts from the one before it (the brief's budget for the first) and says why."""
    lifts = row.get('budget_lifts')
    if lifts is None:
        return []
    if not isinstance(lifts, list):
        return ['budget_lifts is not a list of {date, from, to, why}']
    errs, prev = [], brief_budget(brief)
    for i, l in enumerate(lifts):
        at = f'budget_lifts[{i}]'
        if not isinstance(l, dict) or not is_count(l.get('from')) or not is_count(l.get('to')):
            errs.append(f'{at} is not {{date, from, to, why}} with whole numbers')
            prev = None
            continue
        if l['to'] <= l['from']:
            errs.append(f'{at}: to {l["to"]} is not above from {l["from"]}')
        if prev is not None and l['from'] != prev:
            errs.append(f'{at}: from {l["from"]} is not ' + (f"the brief's budget {prev}" if i == 0 else f'the previous to {prev}'))
        if not isinstance(l.get('why'), str) or not l['why'].strip():
            errs.append(f'{at}: no why')
        prev = l['to']
    return errs


def usage_problems(jid, row, brief, report):
    """The usage rule for one row (W31; pure): from `usage_from` on, a report on a row in review, fix or done has a `Usage:` line, at most 1.25 x
    the effective budget, naming only the row's model, and the row's `budget_lifts` chain holds. A row with no report file is the row rule's to report."""
    if not usage_rule(jid) or row.get('status') not in STATUSES_WITH['report'] or report is None:
        return []
    errs = lift_problems(row, brief)
    u, why = parse_usage(report)
    if why:
        return errs + [f'{why} (from {S.prefix}{S.usage_from} on; `{usage_write(jid)}` writes it)']
    budget = effective_budget(row, brief)
    if over_budget(u.calls, budget):
        errs.append(f'usage {u.calls} tool calls is over 1.25 x the budget {budget}: correct the line, or add a budget_lifts entry to the row')
    want = model_family(row.get('model'))
    errs += [f"usage model {m} is not the row's model {row.get('model')}: correct the line, or the row if it was wrong" for m in u.models if model_family(m) != want]
    return errs


def usage_chip(row, brief, report):
    """(text, over budget) for a card, from the report's `Usage:` line and the effective budget, or None with no readable line."""
    u = parse_usage(report)[0] if report is not None else None
    if u is None:
        return None
    budget = effective_budget(row, brief)
    calls = str(u.calls) if budget is None else f'{u.calls} / {budget}'
    return f'usage {calls} calls · {", ".join(u.models)}', over_budget(u.calls, budget)


def usage_record(data):
    """A usage command's answer, checked: {calls, models, sessions, note} with models lower case and the note on one line. ValueError names the bad key."""
    if not isinstance(data, dict):
        raise ValueError('the usage answer is not a JSON object with calls, models, sessions and note')
    for k in ('calls', 'sessions'):
        if not is_count(data.get(k)) or not 0 <= data[k] < 10 ** 9:
            raise ValueError(f'the usage answer needs {k} as a whole number of at least 0, not {data.get(k)!r}')
    models = data.get('models')
    if not isinstance(models, list) or not models or not all(isinstance(m, str) and USAGE_MODEL.match(m.strip()) for m in models):
        raise ValueError(f'the usage answer needs models as a list of model names, not {models!r}')
    for m in models:
        if model_family(m) not in S.models:
            raise ValueError(f'the usage answer has model {m.strip()!r}: name a family from [jobs] models ({", ".join(S.models)}), not a model id')
    if not isinstance(data.get('note'), str):
        raise ValueError(f'the usage answer needs note as text, not {data.get("note")!r}')
    return {'calls': data['calls'], 'models': list(dict.fromkeys(m.strip().lower() for m in models)), 'sessions': data['sessions'],
            'note': ' '.join(data['note'].split())}


def usage_line(u):
    """The report line for a checked usage record."""
    free = f'{u["sessions"]} session{"" if u["sessions"] == 1 else "s"}' + (f', {u["note"]}' if u['note'] else '')
    return f'Usage: {u["calls"]} tool calls; models: {", ".join(u["models"])}; {free}'


def usage_json(text, where):
    """The checked usage record in `text`, which `where` printed or holds."""
    try:
        data = strict_loads(text)
    except ValueError as e:
        raise ValueError(f'{where} is not one JSON object: {e}') from None
    return usage_record(data)


def run_usage_cmd(cmd, jid, root, timeout=USAGE_TIMEOUT, run=subprocess.run):
    """The game's `[jobs] usage_cmd` for job `jid`, as a checked usage record: split into an argv ({id} filled per argument, no shell), run in the repo
    root. This command is the only way usage reaches the core: the core reads no transcript. Anything but exit 0 and one good JSON object is a ValueError."""
    try:
        argv = [a.replace('{id}', jid) for a in shlex.split(cmd)]
    except ValueError as e:
        raise ValueError(f'[jobs] usage_cmd does not split into arguments: {e}') from None
    if not argv:
        raise ValueError('[jobs] usage_cmd is empty: set it in wsc.toml, or give the numbers with --from-json FILE')
    try:
        p = run(argv, cwd=root, capture_output=True, encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL, timeout=timeout, env=git_env())
    except subprocess.TimeoutExpired:
        raise ValueError(f'{argv[0]} timed out after {timeout} s') from None
    except OSError as e:
        raise ValueError(f'{argv[0]} did not start: {e}') from None
    if p.returncode:
        raise ValueError(f'{argv[0]} failed (exit {p.returncode}): {(p.stderr or "").strip()[-300:]}')
    return usage_json(p.stdout, argv[0] + "'s output")


def read_usage_json(path):
    """The checked usage record in file `path` (`--from-json`). A PowerShell-written BOM is fine."""
    try:
        text = Path(path).read_text(encoding='utf-8-sig')
    except OSError as e:
        raise ValueError(f'cannot read {path}: {e}') from None
    return usage_json(text, str(path))


def paragraph_end(lines, head):
    """The index just past the first paragraph under the heading at `head`, or head + 1 when a heading or a code fence comes first."""
    def stops(l):
        return not l.strip() or l.startswith('#') or FENCE.match(l)
    i = head + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i == len(lines) or stops(lines[i]):
        return head + 1
    while i < len(lines) and not stops(lines[i]):
        i += 1
    return i


def set_usage_line(text, jid, line):
    """Report `text` with `line` as its one `Usage:` line: replaces the line there, or inserts it after the first paragraph under the `# <id> report`
    heading. Every other byte stays, line endings too. ValueError for two lines, no heading, or a result parse_usage cannot read."""
    lines = text.split('\n')
    eol = '\r' if '\r\n' in text else ''
    hits = usage_hits(lines)
    if len(hits) > 1:
        raise ValueError('the report has two "Usage:" lines: keep one by hand, then run this again')
    if hits:
        lines[hits[0]] = line + ('\r' if lines[hits[0]].endswith('\r') else '')
    else:
        head = next((i for i, l in unfenced(lines) if re.match(rf'# {re.escape(jid)} report\b', l)), None)
        if head is None:
            raise ValueError(f'the report has no "# {jid} report" heading to put the line under')
        end = paragraph_end(lines, head)
        if end == len(lines):
            lines[-1] += eol
            lines += [eol, line]
        else:
            lines[end:end] = [eol, line + eol] + ([eol] if lines[end].strip() else [])
    out = '\n'.join(lines)
    why = parse_usage(out)[1]
    if why:
        raise ValueError(f'the line would not read back: {why}')
    return out


RUN_CITE = re.compile(r'(?:[\w.-]+/)*runs/[\w.-]*\w')  # ends on a word char: a sentence's '.' or '-' is not part of the path


def failed_results_problems(jid, text, root, glob):
    """Every ctl result (JSON matched by `glob` inside a run folder the report cites) with top-level status "failed" is named, by path
    relative to the run folder or by file name, in the report's ## Deviations section. A report that cites no run folder passes."""
    if not glob:
        return []
    root = Path(root).resolve()
    m = re.search(r'^## Deviations\b[^\n]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    dev = m.group(1) if m else ''
    errs, seen = [], set()
    for cite in RUN_CITE.finditer(text):
        folder = (root / cite.group(0)).resolve()
        if folder in seen or not folder.is_dir() or root not in folder.parents:
            continue
        seen.add(folder)
        for f in sorted(folder.glob(glob)):
            try:
                if not f.is_file() or strict_loads(f.read_text(encoding='utf-8')).get('status') != 'failed':
                    continue
            except (OSError, ValueError, AttributeError):
                continue
            rel = f.relative_to(folder).as_posix()
            if rel not in dev and f.name not in dev:
                errs.append(f'failed ctl result {folder.relative_to(root).as_posix()}/{rel} is not named in ## Deviations')
    return errs


def review_rounds(text):
    """(text before the first round, [(heading line, body)] in file order) of a review.md."""
    heads = list(ROUND.finditer(text or ''))
    if not heads:
        return text or '', []
    ends = [h.start() for h in heads[1:]] + [len(text)]
    return text[:heads[0].start()], [(h.group(0), text[h.end():end]) for h, end in zip(heads, ends)]


def round_count(text):
    return len(review_rounds(text)[1])


def verdict_lines(text):
    """Lines verdict() would read: one parser for what counts as a verdict (CI's policy check reads the first one)."""
    return [l for l in (text or '').splitlines() if verdict(l)]


def round_problems(text, jid=None):
    """The review round rules for one review.md: rounds numbered from 1 with no gap, newest first, at most MAX_ROUNDS, each heading dated
    with its branch and sha, exactly one verdict per round and none outside a round (so verdict() returns the newest round's)."""
    pre, rounds = review_rounds(text)
    if not rounds:
        return [f'review.md has no "## Round N (YYYY-MM-DD, branch job/{S.prefix}<n> at <sha>)" section' + ref('review_doc', ' ({})')]
    errs = []
    nums = []
    for head, body in rounds:
        m = ROUND_HEAD.match(head)
        if not m:
            errs.append(f'"{head.strip()}" is not "## Round N (YYYY-MM-DD, branch job/{S.prefix}<n> at <sha>)"')
            n = re.match(r'## Round (\d+)', head)
            nums.append(int(n.group(1)) if n else 0)
        else:
            nums.append(int(m.group(1)))
        if len(verdict_lines(body)) != 1:
            errs.append(f'"{head.strip()}" has {len(verdict_lines(body))} verdict lines, not exactly one')
    limit = max_rounds(jid)
    if len(rounds) > limit:
        errs.append(f'review.md has {len(rounds)} rounds: at most {limit} (after round {limit} without merge the job is blocked; {grant_hint()})')
    if nums != list(range(len(nums), 0, -1)):
        errs.append(f'rounds are {", ".join(map(str, nums))}: they must count up from 1 with no gap, newest first '
                    f'(want {", ".join(map(str, range(len(nums), 0, -1)))})')
    if verdict_lines(pre):
        errs.append('a verdict line sits above the first round: each verdict belongs inside its round')
    return errs


def round_status_problems(row, review, report):
    """The row must agree with the newest round's verdict: merge -> done; a non-merge in round N < 3 -> fix, or review once
    report.md has "## Fix round N"; a non-merge in the last round (`max_rounds`) -> blocked with `blocked_by_rounds`."""
    st, n, v = row.get('status'), round_count(review), verdict(review)
    if v not in ('merge', 'merge after fixes', 'do not merge') or not n:
        return []   # reported by the verdict and round rules
    if v == 'merge':
        return [] if st == 'done' else [f'round {n} says merge, so the row should be done, not {st}']
    want_by = blocked_by_rounds(row.get('id'))
    if n >= max_rounds(row.get('id')):
        if st == 'blocked' and row.get('blocked_by') == want_by:
            return []
        return [f'round {n} says "{v}": the row must be blocked with blocked_by="{want_by}", not {st} ({grant_hint()})']
    fixed = bool(re.search(rf'^## Fix round {n}\b', report or '', re.M))
    if st == 'fix' and not fixed:
        return []
    if st == 'review' and fixed:
        return []
    want = 'review (report.md has "## Fix round %d")' % n if fixed else f'fix (report.md has no "## Fix round {n}" yet)'
    return [f'round {n} says "{v}", so the row should be {want}, not {st}']


def problems(rows, read, folders=()):
    """The core's errors for the queue. `rows`: the jobs rows; `read(path)`: file text or None; `folders`: job ids that have a jobs/<id>/
    folder. `check` adds the repo's own rules."""
    errs, by = [], {r['id']: r for r in rows}
    for jid in sorted(by, key=num):
        r, st = by[jid], by[jid].get('status')
        for f in ('brief', 'report', 'review'):
            want = f'{S.jobs_dir}/{jid}/{f}.md'
            if r.get(f) and r[f] != want:
                errs.append(f'{jid}: {f}={r[f]} points at another job (want {want})')
            text = read(want)
            if r.get(f) and text is None:
                errs.append(f'{jid}: {f}={want} but the file does not exist')
            if st in STATUSES_WITH[f] and not r.get(f):
                errs.append(f'{jid}: status {st} needs {f}={want}')
            if text is not None and not r.get(f):
                errs.append(f'{jid}: {want} exists but the row has no {f}= (set it, with the status that goes with it)')
        if semver_rule(jid) and st not in ('needs_brief', 'blocked', 'later') and not r.get('semver'):
            errs.append(f'{jid}: status {st} needs semver=<patch|minor|major|none> (from {S.prefix}{S.semver_from} on, C27)')
        if st == 'later' and read(f'{S.jobs_dir}/{jid}/brief.md') is not None:
            errs.append(f'{jid}: has a brief but is still later (set status=queued brief={S.jobs_dir}/{jid}/brief.md)')
        if st == 'needs_brief' and read(f'{S.jobs_dir}/{jid}/brief.md') is not None:
            errs.append(f'{jid}: has a brief but is still needs_brief (set status=queued brief={S.jobs_dir}/{jid}/brief.md)')
        brief = read(f'{S.jobs_dir}/{jid}/brief.md')
        if brief is not None:
            errs += [f'{jid}: brief: {e}' for e in brief_problems(jid, r, brief)]
        report = read(f'{S.jobs_dir}/{jid}/report.md')
        if report is not None:
            errs += [f'{jid}: report: {e}' for e in report_problems(jid, report)]
            if read(f'{S.jobs_dir}/{jid}/handback.md') is not None and not re.search(r'^## Orchestrator additions\b', report, re.M):
                errs.append(f'{jid}: report.md sits beside a handback: say what the orchestrator added (a "## Orchestrator additions" section)')
            if S.failed_results and S.root is not None:
                errs += [f'{jid}: report: {e}' for e in failed_results_problems(jid, report, S.root, S.failed_results)]
            errs += [f'{jid}: report: {e}' for e in usage_problems(jid, r, brief, report)]
        review = read(f'{S.jobs_dir}/{jid}/review.md')
        if review is not None:
            if not DATED.search('\n'.join(review.split('\n')[:5])):
                errs.append(f'{jid}: review.md has no date in its first lines' + ref('review_doc', ' ({}: dated at the top)'))
            if verdict(review) not in ('merge', 'merge after fixes', 'do not merge'):
                errs.append(f'{jid}: review.md has no Verdict line of the three allowed' + ref('review_doc', ' ({} "Output")'))
            elif st == 'done' and verdict(review) != 'merge':
                errs.append(f'{jid}: done, but the review verdict is "{verdict(review)}" (only "merge" makes a job done)')
            if jid not in S.legacy_rounds:
                errs += [f'{jid}: {e}' for e in round_problems(review, jid) + round_status_problems(r, review, report)]
        if st in ('review', 'done'):
            late = [d for d in r.get('depends_on', []) if by.get(d, {}).get('status') != 'done']
            if late:
                errs.append(f'{jid}: {st} while its dependencies {", ".join(late)} are not done')
    for jid in sorted(set(folders) - set(by), key=num):
        errs.append(f'{S.jobs_dir}/{jid}/ has no row in the jobs registry')
    # dependency cycles
    state = {}
    def visit(j, path):
        if state.get(j) == 1:
            errs.append('dependency cycle: ' + ' -> '.join(path[path.index(j):] + [j]))
            return
        if state.get(j) == 2 or j not in by:
            return
        state[j] = 1
        for d in by[j].get('depends_on', []):
            visit(d, path + [j])
        state[j] = 2
    for j in sorted(by, key=num):
        visit(j, [])
    return errs


# ------------------------------------------------------------------ next and review
ACTIONS = {'brief': ('needs_brief', 'brief'), 'build': ('queued', 'job')}   # action: (status it needs, branch prefix that claims it)
BRANCH_ACTIONS = ('review', 'fix')   # ready from the job branch's own row (the status names the action); the only ones --auto starts


class Branch(NamedTuple):
    """What branch_rows reads from one origin/job/<id>: its row, the rounds in its review.md, its head sha, whether it has a handback.md."""
    row: Optional[dict]
    rounds: int = 0
    head: Optional[str] = None
    handback: bool = False


def branch_state(v):
    """An on_branch value as a Branch (a bare row, as the tests and older callers pass, has no rounds and no known head)."""
    return v if isinstance(v, Branch) else Branch(v)


def not_ready(action, jid, by, branches, on_branch=None):
    """The one readiness rule (`jobs next|review|fix`, `--id`, the view's buttons, its server and --auto): why job `jid` cannot be
    started for `action`, or None when it can. brief: needs_brief, every depends_on done, no brief/<id> branch; build: the same with
    queued and job/<id>; review: a job/<id> branch whose row says review (round 2 and 3 too: review.md may exist); fix: a job/<id>
    branch whose row says fix. Both on the branch's own row and its review.md rounds (J52 review 2): review refuses once MAX_ROUNDS
    are written, fix refuses with no round to answer. `by`: rows on main by id; `branches`: remote branch names; `on_branch`:
    {id: Branch or a bare row} (see branch_rows)."""
    r = by.get(jid)
    if r is None:
        return f'{jid} is not a row of the jobs registry'
    if action in BRANCH_ACTIONS:
        if jid not in (on_branch or {}) and f'job/{jid}' not in branches:
            return f'{jid} has no job/{jid} branch on origin'
        if jid not in (on_branch or {}) and r.get('status') == 'done':   # branch_rows skips the branches of done jobs (J56)
            return f'{jid} is done on main'
        b = branch_state((on_branch or {}).get(jid))
        row, rounds = b.row, b.rounds
        if not row:
            return f'job/{jid} has no {jid} row'
        if row.get('status') != action:
            return f'{jid} is {row.get("status")} on job/{jid}, not {action}' + (' (no report yet)' if row.get('status') == 'queued' else '')
        if action == 'review' and rounds >= max_rounds(jid):
            return f'{jid}: review.md already has {rounds} rounds; after round {max_rounds(jid)} the job is blocked for {S.text["owner"]}' + ref('ref_rounds')
        if action == 'fix' and not rounds:
            return f'{jid} is fix on job/{jid} but its review.md has no round to answer'
        return None
    st, prefix = ACTIONS[action]
    if r.get('status') != st:
        return f'{jid} is {r.get("status")}, not {st}'
    late = [d for d in r.get('depends_on', []) if by.get(d, {}).get('status') != 'done']
    if late:
        return f'{jid} ({st}): waits for {", ".join(late)}'
    if f'{prefix}/{jid}' in branches:
        return f'{jid} ({st}): in progress on {prefix}/{jid}'
    if action == 'build' and r.get('needs_pc') and (pc := pc_absent()):
        return f'{jid} needs the PC {pc}'
    return None


def pc_absent():
    """W26, decision 7: why a needs_pc build cannot start on this machine ('(<path> is absent here)'), or None. `WSC_PC_STATE` (read now)
    beats `[jobs] pc_state`; an empty WSC_PC_STATE means "no PC here"; neither set means no gating. `$VAR` and `~` are expanded."""
    env = os.environ.get('WSC_PC_STATE')
    if env is None and not S.pc_state:
        return None
    value = S.pc_state if env is None else env
    if not value:
        return '(WSC_PC_STATE is empty: no PC here)'
    path = os.path.expandvars(os.path.expanduser(value))
    return None if Path(path).is_dir() else f'({path} is absent here)'


def order_key(r):
    """pick_next's order (W26): phase, then number; a row without an int phase sorts as phase 99."""
    ph = r.get('phase')
    return (ph if isinstance(ph, int) and not isinstance(ph, bool) else 99, num(r['id']))


def pick_next(rows, branches):
    """(kind, row, waiting): the first ready job to build ('job') by (phase, number), else the first ready job to brief ('brief'), else
    (None, None, waiting). Ready: not_ready() says None for 'build' (then 'brief')."""
    by = {r['id']: r for r in rows}
    waiting = []
    order = sorted(rows, key=order_key)
    for kind, action in (('job', 'build'), ('brief', 'brief')):
        for r in order:
            if r.get('status') == ACTIONS[action][0]:
                why = not_ready(action, r['id'], by, branches)
                if why is None:
                    return kind, r, waiting
                waiting.append(why)
    waiting += [f'{r["id"]}: {r["status"]}' + (f' ({r.get("blocked_by")})' if r.get('blocked_by') else '')
                for r in order if r.get('status') in ('review', 'blocked')]
    return None, None, sorted(set(waiting), key=lambda w: num(w.split()[0].rstrip(':')))


def pick_branch(action, on_branch):
    """`on_branch`: see not_ready. The lowest-numbered branch ready for `action` (review or fix), or None."""
    for jid in sorted(on_branch, key=num):   # the rule needs a main row only to exist: the branch's row is the one that counts here
        if not_ready(action, jid, {jid: {}}, set(), on_branch) is None:
            return jid
    return None


def pick_review(on_branch):
    return pick_branch('review', on_branch)


FAILED_CHECK = {'FAILURE', 'TIMED_OUT', 'STARTUP_FAILURE', 'ACTION_REQUIRED', 'ERROR'}


def failed_prs(prs):
    """`gh pr list --json number,headRefName,statusCheckRollup` -> one line per failed check on an open pull request's head commit.
    A check run reports `conclusion`, a commit status `state`; a check that is still running or passed is not listed."""
    out = []
    for pr in sorted(prs, key=lambda x: x.get('number', 0)):
        for c in pr.get('statusCheckRollup') or []:
            if (c.get('conclusion') or c.get('state') or '').upper() in FAILED_CHECK:
                name = c.get('name') or c.get('context') or '?'
                url = c.get('detailsUrl') or c.get('targetUrl') or ''
                out.append(f'PR #{pr["number"]} {pr.get("headRefName", "?")}: {name} failed, run {url}'.rstrip())
    return out


def red_prs(root, offline, run=subprocess.run):
    """The failed-check lines for every open pull request, or one line saying why they could not be read (never an exception)."""
    if offline:
        return []
    try:
        p = run(['gh', 'pr', 'list', '--state', 'open', '--limit', '100', '--json', 'number,headRefName,statusCheckRollup'],
                cwd=str(root), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as x:
        return [f'(could not list pull requests with failed checks: {x}; --offline skips this)']
    if p.returncode != 0:
        return [f'(could not list pull requests with failed checks: {(p.stderr or p.stdout).strip()[:200]}; --offline skips this)']
    try:
        return failed_prs(json.loads(p.stdout or '[]'))
    except ValueError as x:
        return [f'(could not read gh pr list output: {x})']


def _gh_json(run, root, path):
    """The parsed JSON of one `gh api` GET; raises RuntimeError with a short reason (the caller turns it into one "unknown" line)."""
    try:
        p = run(['gh', 'api', path], cwd=str(root), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as x:
        raise RuntimeError(f'cannot run gh: {x}') from None
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:200] or f'gh exited {p.returncode}')
    try:
        return json.loads(p.stdout)
    except ValueError as x:
        raise RuntimeError(f'bad JSON from gh: {x}') from None


def main_state(cfg, root, offline, run=subprocess.run):
    """W22: what main's CI looks like, never an exception. {'state': off | unknown | red | green, 'lines': [...], 'runs': [run ids]}.
    For each workflow in `[ci] workflows`, the latest completed push run on main (a workflow with none, like the pull-request-only policy.yml,
    is skipped) and that run's required jobs (`ci.required_jobs`); a red one gives a line. A newer run still in progress is not read."""
    if offline:
        return {'state': 'off', 'lines': [], 'runs': []}
    red, runs = [], []
    try:
        for wf in cfg['workflows']:
            q = f'repos/{{owner}}/{{repo}}/actions/workflows/{wf}/runs?branch=main&event=push&status=completed&per_page=1'
            found = _gh_json(run, root, q)['workflow_runs']
            if not found:
                continue
            r = found[0]
            runs.append(r['id'])
            jobs = _gh_json(run, root, f'repos/{{owner}}/{{repo}}/actions/runs/{r["id"]}/jobs?per_page=100')['jobs']
            for j in ci.required_jobs(cfg, jobs):
                if j.get('conclusion') in ci.RED:
                    when = (r.get('updated_at') or r.get('created_at') or '')[:10] or 'date unknown'
                    red.append(f'main is RED: {j["name"]} failed in run {r["id"]} ({r.get("html_url", "")}), commit {str(r.get("head_sha", ""))[:7]}, '
                               f'{when}: rerun it or push to main; an issue tracks it')
    except (RuntimeError, KeyError, TypeError, AttributeError) as x:
        return {'state': 'unknown', 'runs': [], 'lines': [f"(main's CI state is unknown: {x}; --offline skips this)"]}
    return {'state': 'red' if red else 'green', 'lines': red, 'runs': runs}


def main_health(cfg, root, offline, run=subprocess.run):
    """The lines for a red main, one "unknown" line when it cannot be read, [] when green or offline."""
    return main_state(cfg, root, offline, run)['lines']


def print_main_health(cfg, root, offline, run=subprocess.run):
    """Print main's CI state first (before the pull requests): the red lines, or the unknown line; green prints nothing. Returns the state."""
    st = main_state(cfg, root, offline, run)
    if st['state'] == 'red':
        print('Main CI is red (fix or rerun before a merge verdict):\n  ' + '\n  '.join(st['lines']))
    elif st['state'] == 'unknown':
        print('\n'.join(st['lines']))
    return st


def main_html(st):
    """The one line (or red lines) at the head of the queue page; '' when offline or no state."""
    if not st or st['state'] == 'off':
        return ''
    e = html.escape
    if st['state'] == 'red':
        return ''.join(f'<p class="note warn">{e(l)}</p>' for l in st['lines'])
    if st['state'] == 'unknown':
        return f'<p class="muted">main CI: unknown. {e(st["lines"][0])}</p>'
    return f'<p class="muted">main CI: green (run {", ".join(str(r) for r in st["runs"]) or "none yet"})</p>'


def print_red_prs(root, offline):
    lines = red_prs(root, offline)
    if lines:
        print('Failed checks on open pull requests (look first' + ref('ci_failures_doc', '; {} classes them') + '):\n  ' + '\n  '.join(lines))
    return lines




def checks_lead():
    return ('read ' + S.text['ci_failures_doc'] + '; ' if S.text['ci_failures_doc'] else '') + 'a red required check is a blocker for a merge verdict'


def check_lines(runs):
    """`check_runs` of one commit (GitHub's REST shape; the endpoint lists the latest run of each name) -> one line per run that failed,
    was cancelled or is still running, by name; passed and skipped runs are not listed."""
    out = []
    for c in sorted(runs, key=lambda c: c.get('name') or ''):
        name, url = c.get('name') or '?', c.get('html_url') or c.get('details_url') or ''
        status, concl = (c.get('status') or '').lower(), (c.get('conclusion') or '').lower()
        if status != 'completed':
            what = f'still running ({status or "no status"})'
        elif concl == 'cancelled':
            what = 'did not finish (cancelled)'
        elif concl.upper() in FAILED_CHECK:
            what = f'failed ({concl})'
        else:
            continue
        out.append(f'{name} {what}' + (f': {url}' if url else ''))
    return out


def branch_ci(root, sha, offline, run=subprocess.run):
    """W26, decision 11: the CI state of one head commit, from one `gh api .../commits/<sha>/check-runs` read (never an exception):
    (state, lines). state: 'running' (a run has not completed; it wins over a failure), 'red' (a run failed or was cancelled), 'green'
    (every run passed, was skipped or neutral: a draft's skipped policy is green), 'none' (no check run yet) or 'unknown' (not read:
    offline, no head, or the read failed). lines: check_lines() for red and running, else one line saying what happened."""
    if offline:
        return 'unknown', ['not read: --offline']
    if not sha:
        return 'unknown', ['its head commit is unknown']
    try:   # gh fills {owner}/{repo} from this clone's origin
        p = run(['gh', 'api', f'repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100'],
                cwd=str(root), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as x:
        return 'unknown', [str(x)]
    if p.returncode != 0:
        return 'unknown', [(p.stderr or p.stdout).strip()[:200] or f'gh exited {p.returncode}']
    try:
        runs = json.loads(p.stdout or '{}').get('check_runs') or []
    except (ValueError, AttributeError) as x:
        return 'unknown', [str(x)]
    if not runs:
        return 'none', ['no check runs yet']
    bad = check_lines(runs)
    if not bad:
        return 'green', [f'all {len(runs)} checks passed or were skipped']
    running = any((c.get('status') or '').lower() != 'completed' for c in runs)
    return ('running' if running else 'red'), bad


def branch_checks(root, branch, sha, offline, run=subprocess.run):
    """The CI block `jobs review` and `jobs fix` print above their steps: every check run on the branch's head commit that failed or is
    still running, or one line saying all passed, none ran yet or why they could not be read (branch_ci's read, as text)."""
    where = f'{branch} at {sha[:7]}' if sha else branch
    if offline:
        return f'(CI checks on {where} not read: --offline; read them before a verdict)'
    if not sha:
        return f'(CI checks on {branch} not read: its head commit is unknown)'
    state, lines = branch_ci(root, sha, offline, run)
    if state == 'unknown':
        return f'(CI checks on {where} could not be read: {lines[0]}; --offline skips this)'
    if state == 'none':
        return f'CI on {where}: no check runs yet (CI has not reported; {checks_lead()})'
    if state == 'green':
        return f'CI on {where}: {lines[0]}.'
    return f'CI on {where} ({checks_lead()}):\n  ' + '\n  '.join(lines)


def draft_pr_step(jid, title):
    """The last step of a build or a fix: the job's pull request, opened as a draft when none exists (J54); never a merge."""
    return (f"Then open the pull request as a draft if none exists, so the review sees the branch's CI (CI's policy check skips drafts): "
            f'gh pr view job/{jid}, else gh pr create --draft --base main --head job/{jid} --title "{jid}: {title}" '
            f'--body "<the first paragraph of {S.jobs_dir}/{jid}/report.md>". Never merge it: the reviewer marks it ready and merges' + ref('ref_merge') + '.')


def _git(root, *args):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=300)
    return p.stdout if p.returncode == 0 else None


def remote_heads(root, offline):
    """{branch name: head sha} of origin's job/* and brief/* branches (one `git ls-remote`), or with `offline` every local remote-tracking
    ref under refs/remotes/origin/."""
    if offline:
        out = _git(root, 'for-each-ref', '--format=%(refname:strip=3) %(objectname)', 'refs/remotes/origin/') or ''
        return dict(l.split(' ', 1) for l in out.splitlines() if ' ' in l)
    out = _git(root, 'ls-remote', '--heads', 'origin', 'job/*', 'brief/*')
    if out is None:
        raise ValueError('git ls-remote origin failed (no network or no origin): rerun with --offline to use local refs')
    return {l.split('refs/heads/', 1)[1].strip(): l.split()[0] for l in out.splitlines() if 'refs/heads/' in l}


def remote_branches(root, offline):
    return set(remote_heads(root, offline))


# ------------------------------------------------------------------ claim (W26, decisions 1-5)
CLAIM_ATTEMPTS = 5
STALE_CLAIM_S = 24 * 3600


class Claim(NamedTuple):
    """One claim push: state 'claimed' (the branch was created at `sha`), 'taken' (it exists: another session claimed it) or 'error'
    (anything else: no network, no origin, a hook; nothing was claimed); `line`: git's own line, for the message."""
    state: str
    sha: Optional[str] = None
    line: str = ''


def claim_argv(branch):
    """The claim: a create-only push of the remote-tracking origin/main (never HEAD). The lease with an empty expected value means "the
    ref must not exist": a plain push would fast-forward an empty claim made at an older main (W26 report, Deviations); no --force."""
    return ['git', 'push', '--porcelain', f'--force-with-lease=refs/heads/{branch}:', 'origin', f'origin/main:refs/heads/{branch}']


def claim_line(branch):
    return f'git push origin --force-with-lease=refs/heads/{branch}: origin/main:refs/heads/{branch}'


def fetch_main(root, run=subprocess.run):
    """Bring origin/main up to date before a claim; None, or why it failed."""
    p = run(['git', '-C', str(root), 'fetch', '-q', 'origin', '+refs/heads/main:refs/remotes/origin/main'], capture_output=True, text=True,
            timeout=300, env=git_env())
    return None if p.returncode == 0 else f'git fetch origin main failed: {(p.stderr or p.stdout).strip()[:300]}'


def claim(root, branch, run=subprocess.run):
    """Push origin/main to a new `branch` on origin (see claim_argv) and read the `--porcelain` line of that ref: `*` is a new branch
    (claimed); `=` (already there at this sha) and `!` with "[rejected]" (there at another sha) are a lost race; every other outcome,
    including "[remote rejected]" (a server hook) or no ref line at all, is an error. Never an exception."""
    sha = run(['git', '-C', str(root), 'rev-parse', '--verify', '-q', 'refs/remotes/origin/main^{commit}'], capture_output=True, text=True,
              timeout=60, env=git_env())
    if sha.returncode != 0 or not sha.stdout.strip():
        return Claim('error', None, 'origin/main is unknown in this clone: git fetch origin main, then rerun')
    try:
        p = run(['git', '-C', str(root), *claim_argv(branch)[1:]], capture_output=True, text=True, timeout=300, env=git_env())
    except (OSError, subprocess.SubprocessError) as x:
        return Claim('error', None, f'git push did not run: {x}')
    for line in (p.stdout or '').replace('\r\n', '\n').split('\n'):
        parts = line.split('\t')
        if len(parts) >= 3 and parts[1].endswith(f':refs/heads/{branch}'):
            flag, summary = parts[0], parts[2].strip()
            if flag == '*':
                return Claim('claimed', sha.stdout.strip(), line)
            if flag == '=' or (flag == '!' and summary.startswith('[rejected]')):
                return Claim('taken', None, line.replace('\t', ' '))
            return Claim('error', None, line.replace('\t', ' '))
    return Claim('error', None, ((p.stderr or '') + (p.stdout or '')).strip()[:300] or f'git push exited {p.returncode}')


def _age(seconds):
    return f'{int(seconds // 86400)} d' if seconds >= 86400 else f'{int(seconds // 3600)} h'


def empty_claims(root, rows, heads, now=None, run=subprocess.run):
    """Decision 5: one line per empty claim older than STALE_CLAIM_S: a job/<id> of a queued row or a brief/<id> of a needs_brief row whose
    head is an ancestor of origin/main (no commits of its own). The age is the head commit's committer date, so the claim is that old or
    less (the claim itself leaves no date). Listed, never released: deleting a remote branch is the owner's call."""
    now = time.time() if now is None else now
    by, out = {r['id']: r for r in rows}, []
    for name in sorted(heads, key=lambda b: num(b.partition('/')[2])):
        kind, _, jid = name.partition('/')
        if (kind, by.get(jid, {}).get('status')) not in (('job', 'queued'), ('brief', 'needs_brief')):
            continue
        sha = heads[name]
        if run(['git', '-C', str(root), 'merge-base', '--is-ancestor', sha, 'refs/remotes/origin/main'], capture_output=True, text=True,
               timeout=60, env=git_env()).returncode != 0:
            continue
        p = run(['git', '-C', str(root), 'log', '-1', '--format=%ct', sha], capture_output=True, text=True, timeout=60, env=git_env())
        try:
            age = now - int(p.stdout.strip())
        except ValueError:
            continue
        if age > STALE_CLAIM_S:
            out.append(f'{jid}: claimed {_age(age)} ago or less, nothing pushed; `git push origin --delete {name}` releases it '
                       f'({S.text["owner"]}, or a session they ask)')
    return out


def next_claim(root, rows, read_heads, jid=None, peek=False, offline=False, claim_fn=None, now=None, run=subprocess.run):
    """`jobs next [--id]`: pick the next ready job (or `jid`), claim its branch, and return (exit code, text). `read_heads()` -> {branch:
    sha} (remote_heads). A claim another session won moves on to the next ready job after one re-read, at most CLAIM_ATTEMPTS times;
    any other failure claims nothing and exits 1. `peek` and `offline` never claim: they print what would be picked and the push."""
    claim_fn = claim_fn or claim
    heads = read_heads()
    branches = set(heads)
    contested, fetched = [], False
    for _ in range(CLAIM_ATTEMPTS):
        if jid:
            r = {x['id']: x for x in rows}.get(jid)
            action = {'needs_brief': 'brief', 'queued': 'build'}.get((r or {}).get('status'))
            if r and not action:
                return 1, f'{jid} is {r.get("status")}, not queued or needs_brief: nothing to pick up'
            why = not_ready(action or 'build', jid, {x['id']: x for x in rows}, branches)
            if why:
                return 1, why + (' (claimed by another session just now)' if contested else '')
            kind = 'job' if action == 'build' else 'brief'
        else:
            kind, r, waiting = pick_next(rows, branches)
            if kind is None:
                break
        branch = f'{kind}/{r["id"]}'
        if peek or offline:
            text = steps(kind, r, root, None, '--offline' if offline else '--peek', lead=bool(jid))
            return 0, '\n'.join([text] + empty_claims(root, rows, heads, now, run))
        if not fetched:
            err = fetch_main(root, run)
            if err:
                return 1, err
            fetched = True
        c = claim_fn(root, branch, run)
        if c.state == 'claimed':
            return 0, '\n'.join([steps(kind, r, root, c.sha, lead=bool(jid))] + empty_claims(root, rows, heads, now, run))
        if c.state == 'error':
            return 1, f'claiming {branch} failed, nothing was claimed: {c.line}'
        contested.append(r['id'])
        heads = read_heads()
        branches = set(heads) | {f'{kind}/{x}' for x in contested}
    else:
        if not jid:
            waiting = pick_next(rows, branches)[2]
    if jid:
        return 1, f'{jid}: in progress (claimed by another session just now)'
    lines = waiting or ['(the queue is empty)']
    head = 'Nothing is ready'
    if contested:
        head += (f' (another session claimed {", ".join(contested)} first' +
                 (f'; stopped after {CLAIM_ATTEMPTS} attempts' if len(contested) >= CLAIM_ATTEMPTS else '') + ')')
    return 0, '\n'.join([head + '. Waiting:\n  ' + '\n  '.join(lines)] + empty_claims(root, rows, heads, now, run))


def steps(kind, r, root, sha, why='', lead=False):
    """The build or brief steps after a claim at `sha`, or (sha None) the steps with the push that would claim it."""
    if kind == 'job':
        return build_steps(r, sha, why)
    return brief_steps(r, root, 'needs a brief' if lead else 'needs a brief (nothing queued is ready)', sha, why)


def take_it(branch, sha, why=''):
    """The first step of a pick-up: the claim made (sha), or the one that would be made (W26, decision 3)."""
    get = f'git fetch origin {branch}, git checkout -b {branch} origin/{branch}'
    if sha:
        return f'Claimed: {branch} now exists on origin at {sha[:7]}. Take it: {get}'
    return f'(not claimed: {why or "no claim made"}) `{claim_line(branch)}` claims it ({S.text["wsc"]} jobs next does). Then take it: {get}'


JOB_REFS = 'refs/remotes/origin/job/'


def _blobs(root, specs, run=subprocess.run):
    """{spec: text or None (missing)} for each `<ref>:<path>`, read in one `git cat-file --batch` call."""
    if not specs:
        return {}
    p = run(['git', '-C', str(root), 'cat-file', '--batch'], input=''.join(f'{s}\n' for s in specs).encode(), capture_output=True,
            timeout=300)
    out, at, got = p.stdout or b'', 0, {}
    for spec in specs:
        nl = out.find(b'\n', at)
        head = out[at:nl].split() if nl >= 0 else []
        if len(head) == 3 and head[1] == b'blob':
            size = int(head[2])
            got[spec], at = out[nl + 1:nl + 1 + size].decode('utf-8', 'replace'), nl + 2 + size
        else:   # "<spec> missing" (or an output cut short): no such file on that branch
            got[spec], at = None, (nl + 1 if nl >= 0 else len(out))
    return got


def branch_row_spec(ref, jid, reg_dir):
    """Where a job branch keeps job `jid`'s row: [(`<ref>:<path>`, text -> the row or None)], first match wins. Since J55 the row is its
    own file (`<reg_dir>/jobs/<id>.json`; the core's id_to_file of a plain id is the id); a branch cut before J55 has the JSONL."""
    return [(f'{ref}:{reg_dir}/jobs/{jid}.json', lambda text: strict_loads(text) if text else None),
            (f'{ref}:{reg_dir}/jobs.jsonl', lambda text: next((x for x in load_rows(text) if x.get('id') == jid), None))]


def main_rows(ctx):
    """The jobs registry's rows in the working tree, through the core's loader (either storage)."""
    from warscape.registry import load_all
    return load_all(ctx)['jobs'].rows


def branch_rows(root, branches, offline, reg_dir, only=None, done=(), run=subprocess.run):
    """{id: Branch(row on job/<id> or None, rounds in its review.md, head sha)} for each remote job branch (or just `only`), skipping
    every job in `done` (done on main: lane() and not_ready() need nothing from its branch; `only` is read even when done). One
    `git fetch` of the branches to read (unless offline; none when there is nothing to read), one `for-each-ref` for the heads and one
    `git cat-file --batch` for every row and review.md (J56: was one fetch and three calls per branch)."""
    ids = sorted((b.split('/', 1)[1] for b in branches if b.startswith('job/')), key=num)
    ids = [j for j in ids if j == only] if only else [j for j in ids if j not in done]
    if not ids:
        return {}
    if not offline:
        src = f'refs/heads/job/{only}' if only else 'refs/heads/job/*'
        p = run(['git', '-C', str(root), 'fetch', '-q', 'origin', f'+{src}:{JOB_REFS}{only or "*"}'], capture_output=True, text=True,
                timeout=300)
        if p.returncode != 0:
            raise ValueError(f'git fetch of the job branches failed ({(p.stderr or "").strip()[:200]}): rerun with --offline to use local refs')
    p = run(['git', '-C', str(root), 'for-each-ref', '--format=%(refname:strip=4) %(objectname)', JOB_REFS], capture_output=True,
            text=True, timeout=300)
    heads = dict(l.split(' ', 1) for l in (p.stdout or '').splitlines() if ' ' in l) if p.returncode == 0 else {}
    rows = {j: branch_row_spec(f'origin/job/{j}', j, reg_dir) for j in ids}
    reviews = {j: f'origin/job/{j}:{S.jobs_dir}/{j}/review.md' for j in ids}
    hands = {j: f'origin/job/{j}:{S.jobs_dir}/{j}/handback.md' for j in ids}
    got = _blobs(root, [s for j in ids for s, _ in rows[j]] + [reviews[j] for j in ids] + [hands[j] for j in ids], run)
    row = lambda j: next((parse(got[s]) for s, parse in rows[j] if got.get(s) is not None), None)
    return {j: Branch(row(j), round_count(got.get(reviews[j])), heads.get(j), got.get(hands[j]) is not None) for j in ids}


def take_claim(root, jid, n, head, session, hours):
    """claims.take for `jobs review` and the autopilot (a seam the tests replace): (held, claim); raises claims.ClaimError."""
    from . import claims
    return claims.take(root, jid, n, head, session, hours)


def print_claims(root, offline, branches, rounds=None, release=False):
    """Print one line per live review claim (`jobs next|review|view`; nothing offline). With `release`, first delete the claims whose round
    the branch already has (`rounds`: {id: rounds}; None: only those whose job/<id> branch is gone). An unreadable remote is one line."""
    if offline:
        return
    from . import claims as C
    try:
        got = C.read(root)
    except C.ClaimError as e:
        print(f'Review claims: unknown ({e})')
        return
    gone = C.release(root, [c for c in got if rounds is not None or f'job/{c.jid}' not in branches], rounds or {}, branches) if release else []
    for c in got:
        if c not in gone:
            print(f'Review claim: {c.jid} round {c.round} by {c.session} ({C.age(c)} ago, {C.ref(c.jid, c.round)})')


# ------------------------------------------------------------------ launch (the view's buttons)
PROMPTS = {'brief': 'Write the brief for job {id}: git pull, then run {wsc} jobs next --id {id} and follow it.',
           'build': 'Pick up job {id}: git pull, then run {wsc} jobs next --id {id} and follow it.',
           'review': 'Review job {id}: git pull, then run {wsc} jobs review --id {id} and follow {review_doc}.',
           'fix': 'Fix job {id}: git pull, then run {wsc} jobs fix --id {id} and follow it.'}
LABELS = {'brief': 'Write brief', 'build': 'Implement', 'review': 'Review', 'fix': 'Fix'}
LIVE_STATES = {'working', 'blocked'}   # `claude agents --json --all` states of a session that has not ended (module docstring)
ACCEPTANCE_PURPOSE = 'acceptance'      # how the purpose of harness/acceptance.py's game lock starts (a host test holds the two together)
JOB_SH = Path(__file__).resolve().parent.parent / 'harness' / 'job.sh'


def launch_argv(claude, jid, action, row):
    """The background session for one job: named <id>-<action>, the default model for a brief, the row's model otherwise
    (build, review and fix). No permission flags: the session runs under the user's own settings."""
    model = S.models[0] if action == 'brief' else (row.get('model') or S.models[0])
    return [claude, '--bg', '--name', f'{jid}-{action}', '--model', model, '--effort', 'medium', PROMPTS[action].format(id=jid, wsc=S.text['wsc'], review_doc=S.text['review_doc'])]


def command_line(argv, root=None):
    """argv as one line to paste into PowerShell or Git Bash (the page's copy mode)."""
    line = ' '.join(f'"{a}"' if re.search(r'[\s"]', a) else a for a in argv)
    return f'cd "{Path(root).as_posix()}"; {line}' if root else line


def waiting_rules(ledger_text, jid):
    """Codeable-later rows of an audit ledger (`[jobs] ledgers`, a table row shape: | n | rule | source | before | after | why |) whose
    reason names `jid`: the rules that job's brief has to turn into code. A ledger line is the only place this hand-off lives."""
    out = []
    for line in (ledger_text or '').splitlines():
        c = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(c) >= 6 and c[0].isdigit() and c[4] == 'CL' and re.search(rf'\b{jid}\b', c[5]):
            out.append(f'row {c[0]}: {c[1]}')
    return out


def load_rows(text):
    return [strict_loads(l) for l in (text or '').splitlines() if l.strip()]


# ------------------------------------------------------------------ later rows (W43)
def later_text(change, why, raised):
    """A backlog line's cells as a row description, each kept whole."""
    return change + (f' Why: {why}' if why else '') + (f' Raised: {raised}' if raised else '')


def later_row(jid, cells, area):
    """The `later` row of one backlog table row `[number, change, why, raised]`. Model and phase are placeholders until it is promoted and briefed."""
    bid, change = cells[0], cells[1]
    bold = re.match(r'\*\*(.+?)\*\*', change)
    title = bold.group(1).rstrip(':') if bold else change[:80]
    return {'id': jid, 'description': later_text(*cells[1:]), 'title': title, 'phase': 1, 'status': 'later', 'model': S.models[0], 'needs_pc': False,
            'depends_on': [], 'backlog_id': bid, **({'area': area} if area else {})}


def later_problems(tables, rows, path):
    """One line per backlog table row with no row, or whose text the row's description does not hold."""
    by, errs = {r.get('backlog_id'): r for r in rows}, []
    for cells in tables:
        if cells[0] not in by:
            errs.append(f'{path}: {cells[0]} has no later row')
        elif later_text(*cells[1:]) != by[cells[0]].get('description'):
            errs.append(f'{path}: {cells[0]} differs from row {by[cells[0]]["id"]}')
    return errs


# ------------------------------------------------------------------ view
# (key, heading, what it means): the page's sections, in reading order.
LANES = [('progress', 'In progress', 'a job/ or brief/ branch is open on origin'),
         ('review', 'Waiting for review', 'report written; needs an independent review (wsc jobs review)'),
         ('fix', 'Waiting for fixes', 'a review round asked for changes; a fix session answers it (wsc jobs fix)'),
         ('ready', 'Ready to pick up', 'queued, every dependency done, nobody on it'),
         ('waiting', 'Queued, waiting on dependencies', 'brief written; a dependency is not done yet, or it needs the PC and this machine has none'),
         ('brief', 'Needs a brief', 'no brief yet; one can be written once the dependencies make sense'),
         ('blocked', 'Blocked', 'stopped on something outside the queue'),
         ('later', 'Later', 'recorded for later: nothing picks these up; set status=needs_brief to promote one, batched by area'),
         ('done', 'Done', 'reviewed and merged')]


def lane(r, by, branches, on_branch=None):
    """(lane key, short note) for one row: the registry status refined by the remote branches, the job branch's own row (review,
    fix and blocked are set there before main sees them) and the dependencies."""
    st, jid = r.get('status'), r['id']
    late = [d for d in r.get('depends_on', []) if by.get(d, {}).get('status') != 'done']
    br = branch_state((on_branch or {}).get(jid)).row or {}
    if st != 'done' and br.get('status') in ('review', 'fix', 'blocked'):
        st, r = br['status'], br
    if st == 'done':
        return 'done', ''
    if st == 'later':
        return 'later', r.get('area', '')
    if st == 'review':
        return 'review', ''
    if st == 'fix':
        return 'fix', f'fixing on job/{jid}'
    if st == 'blocked':
        return 'blocked', r.get('blocked_by', '')
    if st == 'queued' and f'job/{jid}' in branches:
        return 'progress', f'being built on job/{jid}'
    if st == 'needs_brief' and f'brief/{jid}' in branches:
        return 'progress', f'brief being written on brief/{jid}'
    if st == 'queued' and not late and r.get('needs_pc') and (pc := pc_absent()):
        return 'waiting', f'{jid} needs the PC {pc}'
    if st == 'queued':
        return ('waiting', 'waits for ' + ', '.join(late)) if late else ('ready', '')
    return 'brief', ('waits for ' + ', '.join(late)) if late else 'can be briefed now'


def panel_html(r):
    """A `view`-stage Result as page HTML: its `html` as is (the repo's own code, as the hook was), else its escaped summary and details
    as a muted paragraph, else nothing."""
    if r.html:
        return r.html
    lines = [x for x in [r.summary, *r.details] if x]
    return f'<p class="muted">{"<br>".join(html.escape(str(x)) for x in lines)}</p>' if lines else ''


def card_lines(results):
    """{job id: [HTML]}: the `cards` of `view`-stage Results, text escaped, {'html': ...} as is (W31). A malformed value is skipped: a card line never fails the page."""
    out = {}
    for r in results:
        cards = getattr(r, 'cards', None)
        for jid, v in (cards.items() if isinstance(cards, dict) else ()):
            line = html.escape(v) if isinstance(v, str) else v.get('html') if isinstance(v, dict) else None
            if isinstance(line, str):
                out.setdefault(jid, []).append(line)
    return out


def render_view(rows, read, branches, generated, on_branch=None, token=None, root=None, auto=None, ctx=None, main_html=''):
    """The queue as one HTML page. `read(path)`: file text or None; `branches`: remote branch names; `generated`: timestamp text;
    `on_branch`: see branch_rows (review and fix buttons need it). Brief, report and review are embedded as escaped Markdown and rendered by
    marked.js when it loads (plain text otherwise). A card gets a button for each action not_ready() allows: with `token` (served by
    `--serve`) it posts (id, action) to /launch; without, it copies the command line (run in `root`). `auto`: the autopilot's state
    ({'interval', 'last', 'dry_run'}) when `--auto` runs. `main_html`: main's CI line(s) for the page head (`main_html(state)`, W22)."""
    e = html.escape
    by = {r['id']: r for r in rows}
    order = sorted(rows, key=lambda r: num(r['id']))
    placed = {k: [] for k, _, _ in LANES}
    for r in order:
        k, note = lane(r, by, branches, on_branch)
        placed[k].append((r, note))
    kind, nxt, _ = pick_next(rows, branches)
    if kind == 'job':
        head = f'Next to pick up: <a href="#{e(nxt["id"])}">{e(nxt["id"])} {e(nxt["title"])}</a>'
    elif kind == 'brief':
        head = f'Nothing queued is ready. Next brief to write: <a href="#{e(nxt["id"])}">{e(nxt["id"])} {e(nxt["title"])}</a>'
    else:
        head = 'Nothing is ready to pick up or brief.'
    if main_html:
        head += '</p>' + main_html + '<p>'
    lines = {}
    if ctx is not None:
        results = gatemods.run_stage(ctx, 'view', rows=rows)
        panel, lines = ''.join(panel_html(r) for r in results), card_lines(results)   # a game's own status lines (`view`-stage gate modules)
        if panel:
            head += '</p>' + panel + '<p>'

    def dep(d):
        st = by.get(d, {}).get('status', 'unknown')
        return f'<a class="dep s-{e(st)}" href="#{e(d)}" title="{e(d)}: {e(by.get(d, {}).get("title", "no row"))} ({e(st)})">{e(d)}</a>'

    def card(r, note):
        jid = r['id']
        docs = ''.join(f'<details class="doc"><summary>{f}</summary><pre class="md">{e(t)}</pre></details>'
                       for f in ('brief', 'report', 'review') if (t := read(f'{S.jobs_dir}/{jid}/{f}.md')) is not None)
        deps = ' '.join(dep(d) for d in r.get('depends_on', [])) or '<span class="muted">none</span>'
        tags = [f'phase {r.get("phase", "?")}', r.get('model', '?'), 'needs PC' if r.get('needs_pc') else 'no PC']
        chip = usage_chip(r, read(f'{S.jobs_dir}/{jid}/brief.md'), read(f'{S.jobs_dir}/{jid}/report.md'))
        extra = (f'<p class="usage{" over" if chip[1] else ""}">{e(chip[0])}</p>' if chip else '') + ''.join(f'<p class="cardline">{l}</p>' for l in lines.get(jid, []))
        acts = [a for a in PROMPTS if not_ready(a, jid, by, branches, on_branch) is None]
        buttons = (('<div class="acts">' + ''.join(
            f'<button class="launch" data-id="{e(jid)}" data-act="{a}" data-cmd="{e(command_line(launch_argv("claude", jid, a, r), root))}">'
            f'{LABELS[a]}</button>' for a in acts) + '<output class="result"></output></div>') if acts else '')
        return (f'<article class="card" id="{e(jid)}" data-text="{e((jid + " " + r.get("title", "") + " " + r.get("description", "")).lower())}">'
                f'<header><span class="id">{e(jid)}</span><h3>{e(r.get("title", ""))}</h3><span class="status s-{e(r.get("status", ""))}">'
                f'{e(r.get("status", ""))}</span></header>'
                + (f'<p class="note">{e(note)}</p>' if note else '')
                + f'<p class="desc">{e(r.get("description", ""))}</p>'
                f'<p class="meta">{" · ".join(e(t) for t in tags)} · depends on {deps}</p>{extra}{buttons}{docs}</article>')

    counts = ''.join(f'<a class="count" href="#lane-{k}"><b>{len(placed[k])}</b> {e(h)}</a>' for k, h, _ in LANES)
    lanes = ''.join(f'<section class="lane" id="lane-{k}"><h2>{e(h)} <span class="muted">({len(placed[k])})</span></h2>'
                    f'<p class="muted">{e(why)}</p>' + ''.join(card(r, n) for r, n in placed[k]) + '</section>'
                    for k, h, why in LANES if placed[k])
    refresh = ('Served by <code>wsc jobs view --serve</code>: reload to refresh; the buttons start background sessions.' if token else
               'Rerun it to refresh; the buttons copy the command (<code>wsc jobs view --serve</code> makes them start it).')
    if auto:
        refresh += (f' <b>Autopilot on</b>{" (dry run)" if auto.get("dry_run") else ""}: starts ready reviews and fixes every '
                    f'{int(auto["interval"])} s; last ran {e(auto.get("last") or "not yet")} (log: <code>_scratch/jobs_auto.log</code>).')
    page = VIEW_PAGE.format(reg_jobs=e(S.reg_dir + '/jobs/'), jobs_dir=e(S.jobs_dir), generated=e(generated), head=head, counts=counts, lanes=lanes, total=len(rows), refresh=refresh,
                            serve=json.dumps({'token': token} if token else None), marked_url=MARKED_URL, marked_sri=MARKED_SRI, csp=CSP_SLOT)
    return page.replace(CSP_SLOT, e(view_csp(page)))


# marked 12.0.2, pinned by Subresource Integrity (W28): a changed file at the URL is refused by the browser and the docs stay plain text.
# Made once (2026-11-04) with: curl -sL <MARKED_URL> | openssl dgst -sha384 -binary | openssl base64 -A
# (cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js gives the same hash). A new marked version needs a new URL, hash and test.
MARKED_URL = 'https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js'
MARKED_SRI = 'sha384-/TQbtLCAerC3jgaim+N78RZSDYV7ryeoBCVqTuzRrFec2akfBkHS7ACQ3PQhvMVi'
CSP_SLOT = 'CSP-SLOT-W28'
INLINE = re.compile(r'<(script|style)>(.*?)</\1>', re.S)


def view_csp(page):
    """The view page's Content-Security-Policy (W28): nothing by default; scripts from the one pinned marked URL and the page's own inline
    script, styles from its own inline style, both by sha256 of their exact text (the script holds the serve token, so the hash is per page);
    fetch only to the serving origin (/launch)."""
    h = {'script': [], 'style': []}
    for tag, body in INLINE.findall(page):
        h[tag].append("'sha256-" + base64.b64encode(hashlib.sha256(body.encode('utf-8')).digest()).decode() + "'")
    return (f"default-src 'none'; script-src {MARKED_URL} {' '.join(h['script'])}; style-src {' '.join(h['style'])}; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'")


VIEW_PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>Job Queue</title>
<style>
:root {{ --bg:#f7f6f3; --card:#fff; --ink:#1f1f1f; --muted:#6b6b6b; --line:#e2e0da; --accent:#2f5d8a;
  --done:#2e7d4f; --review:#8a5a00; --queued:#2f5d8a; --needs:#7a7a7a; --blocked:#b03030; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161616; --card:#202020; --ink:#e8e6e1; --muted:#9a9890; --line:#333;
  --accent:#7fb0e0; --done:#5fbf86; --review:#e0a640; --queued:#7fb0e0; --needs:#9a9a9a; --blocked:#e06a6a; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width:960px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ margin:0 0 4px; font-size:24px; }} h2 {{ margin:32px 0 2px; font-size:18px; }} h3 {{ margin:0; font-size:16px; flex:1; }}
a {{ color:var(--accent); }} .muted {{ color:var(--muted); font-weight:normal; }} p {{ margin:4px 0; }}
.head {{ font-size:16px; margin:12px 0; }}
.counts {{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }}
.count {{ background:var(--card); border:1px solid var(--line); border-radius:6px; padding:4px 10px; text-decoration:none; color:var(--ink); }}
input {{ width:100%; padding:8px 10px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--ink); font:inherit; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; margin:10px 0; }}
.card:target {{ outline:2px solid var(--accent); }}
.card header {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
.id {{ font-weight:700; font-family:ui-monospace, Consolas, monospace; }}
.status, .dep {{ font-size:12px; border-radius:10px; padding:1px 8px; border:1px solid currentColor; text-decoration:none; }}
.s-done {{ color:var(--done); }} .s-review, .s-fix {{ color:var(--review); }} .s-queued {{ color:var(--queued); }}
.s-needs_brief, .s-later {{ color:var(--needs); }} .s-blocked, .s-unknown {{ color:var(--blocked); }}
.note {{ color:var(--review); font-size:14px; }} .desc {{ margin:6px 0; }} .meta, .usage, .cardline {{ color:var(--muted); font-size:13px; }}
.usage.over {{ color:var(--blocked); font-weight:600; }}
.doc {{ margin-top:6px; }} .doc summary {{ cursor:pointer; color:var(--accent); }}
.doc pre.md {{ white-space:pre-wrap; font:13px/1.45 ui-monospace, Consolas, monospace; }}
.doc .rendered {{ border-left:3px solid var(--line); padding:0 0 0 12px; overflow-wrap:anywhere; }}
.rendered pre, .rendered code {{ font-family:ui-monospace, Consolas, monospace; font-size:13px; }}
.rendered pre {{ white-space:pre-wrap; background:var(--bg); padding:8px; border-radius:4px; }}
.rendered table {{ border-collapse:collapse; display:block; overflow-x:auto; }} .rendered td, .rendered th {{ border:1px solid var(--line); padding:2px 6px; }}
.acts {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin:8px 0 2px; }}
.acts button {{ font:inherit; font-size:14px; padding:3px 12px; border-radius:6px; border:1px solid var(--accent); background:var(--card);
  color:var(--accent); cursor:pointer; }} .acts button:hover {{ background:var(--accent); color:var(--card); }} .acts button:disabled {{ opacity:.5; }}
.result {{ font-size:13px; font-family:ui-monospace, Consolas, monospace; overflow-wrap:anywhere; }}
.result.ok {{ color:var(--done); }} .result.err {{ color:var(--blocked); }}
.result textarea {{ width:100%; min-height:4em; font:inherit; background:var(--bg); color:var(--ink); border:1px solid var(--line); }}
</style></head>
<body><main>
<h1>Job queue</h1>
<p class="muted">{total} jobs · generated {generated} by <code>wsc jobs view</code> from {reg_jobs}, {jobs_dir}/ and origin's branches. {refresh}</p>
<p class="head">{head}</p>
<div class="counts">{counts}</div>
<input id="q" type="search" placeholder="Filter by id, title or description">
{lanes}
</main>
<script src="{marked_url}" integrity="{marked_sri}" crossorigin="anonymous"></script>
<script>
// raw HTML in a brief, report or review is shown as text, never run (W28): marked's html renderer returns it escaped
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
if (window.marked) marked.use({{ renderer: {{ html(t) {{ return esc(typeof t === 'string' ? t : t.text); }} }} }});
document.getElementById('q').addEventListener('input', ev => {{
  const q = ev.target.value.toLowerCase();
  document.querySelectorAll('.card').forEach(c => c.hidden = q && !c.dataset.text.includes(q));
}});
document.addEventListener('toggle', ev => {{
  const pre = ev.target.querySelector && ev.target.querySelector('pre.md');
  if (!pre || !window.marked) return;
  const div = document.createElement('div'); div.className = 'rendered';
  div.innerHTML = marked.parse(pre.textContent); pre.replaceWith(div);
}}, true);
const SERVE = {serve};
function show(out, text, cls) {{ out.className = 'result ' + cls; out.textContent = text; }}
document.querySelectorAll('button.launch').forEach(b => b.addEventListener('click', async () => {{
  const out = b.parentElement.querySelector('.result');
  if (!SERVE) {{
    try {{ await navigator.clipboard.writeText(b.dataset.cmd); show(out, 'copied, paste it into a terminal: ' + b.dataset.cmd, 'ok'); }}
    catch (err) {{
      const t = document.createElement('textarea'); t.readOnly = true; t.value = b.dataset.cmd;
      show(out, '', ''); out.append(t); t.select();
    }}
    return;
  }}
  b.disabled = true; show(out, 'starting ' + b.dataset.id + '-' + b.dataset.act + ' ...', '');
  try {{
    const r = await fetch('/launch', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ id: b.dataset.id, action: b.dataset.act, token: SERVE.token }}) }});
    const j = await r.json(); show(out, j.message, r.ok ? 'ok' : 'err');
  }} catch (err) {{ show(out, 'no answer from the server (is wsc jobs view --serve still running?): ' + err, 'err'); }}
  b.disabled = false;
}}));
</script>
</body></html>
'''


# ------------------------------------------------------------------ serve
def _claude(*args, timeout=120, cwd=None):
    """Run claude (no shell, no stdin) with its output in files, not pipes: a background session the command leaves behind may
    inherit the handles, and a pipe would then block until that session ends. `cwd`: where it runs (a session starts in its cwd).
    (returncode, stdout, stderr)."""
    claude = shutil.which('claude')
    if not claude:
        raise ValueError('claude is not on PATH')
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0   # Ctrl+C here spares it
    with tempfile.TemporaryFile('w+', encoding='utf-8') as out, tempfile.TemporaryFile('w+', encoding='utf-8') as err:
        try:
            rc = subprocess.run([claude, *args], stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=timeout,
                                cwd=cwd, creationflags=flags).returncode
        except (OSError, subprocess.TimeoutExpired) as x:
            raise ValueError(f'claude {args[0]} did not finish: {x}')
        out.seek(0), err.seek(0)
        return rc, out.read(), err.read()


def list_agents():
    """`claude agents --json --all` as a list of sessions; ValueError when it cannot be read (the launch then fails closed). `--all`: a
    finished session can still hold a process, which the cap counts and `jobs sessions --stop-finished` stops."""
    rc, out, err = _claude('agents', '--json', '--all', timeout=60)
    if rc != 0:
        raise ValueError(f'claude agents --json --all exited {rc}: {err.strip()[:200]}')
    try:
        agents = json.loads(out)
    except ValueError:
        raise ValueError('claude agents --json --all did not print JSON')
    if not isinstance(agents, list):
        raise ValueError('claude agents --json --all did not print a list')
    return agents


def stop_session(sid):
    """`claude stop <id>`; ValueError when it fails. Read on the PC 2026-11-05 and 2026-11-06: on a done row with a pid it ends the process, the
    row stays done and the pid clears; on a done row with no pid it exits 0 and changes nothing. Never `claude rm`: that deletes the worktree."""
    rc, out, err = _claude('stop', sid, timeout=60)
    if rc != 0:
        raise ValueError(f'claude stop {sid} exited {rc}: {(err or out).strip()[:200]}')


def capped_sessions(agents):
    """The rows the session cap counts: a background row with a process, whatever its state (Liam, 2026-11-06). The cap is for memory (D59), and a
    row with no process uses none: a blocked session with no pid that resumes can take the count over the cap by one for a while."""
    return [a for a in agents if isinstance(a, dict) and a.get('kind') == 'background' and a.get('pid')]


def cap_line(agents):
    """Why no session may start, or None: under the cap, or no cap set."""
    held = capped_sessions(agents)
    if not S.max_sessions or len(held) < S.max_sessions:
        return None
    names = ', '.join(str(a.get('name') or a.get('id') or '?') for a in held[:5])
    return f'{len(held)} of {S.max_sessions} background sessions are live ({names}); wait or run wsc jobs sessions --stop-finished'


def next_sessions(named):
    """What `jobs next` prints about the cap: (lines, stop before claiming). A list that cannot be read is said and blocks nothing: `next` is the
    interactive path, only launches fail closed. `named` (`--id`) goes on at the cap: a session the view launched runs `next --id`, is itself one
    of the live rows, and passed the cap when it was launched."""
    if not S.max_sessions:
        return [], False
    try:
        agents = list_agents()
    except ValueError as x:
        return [f'sessions: cannot read the session list ({x})'], False
    lines = [f'sessions: {len(capped_sessions(agents))} live of {S.max_sessions}']
    if named or cap_line(agents) is None:
        return lines, False
    return lines + ['The session cap is full, so no job was claimed: wait for one to end, or run wsc jobs sessions --stop-finished.'], True


def session_rows(agents, by):
    """`jobs sessions`: the background rows in every state, those with a process first. `counts`: the cap counts it."""
    rows = [{'name': str(a.get('name') or ''), 'id': a.get('id'), 'state': a.get('state'), 'pid': a.get('pid'), 'job': _session_job(a, by),
             'counts': bool(a.get('pid'))} for a in agents if isinstance(a, dict) and a.get('kind') == 'background']
    return sorted(rows, key=lambda r: not r['counts'])


def stop_finished(rows, stop):
    """Stop each `done` row of session_rows that still has a process: (one result per stop, how many done rows had already exited). A failed
    stop does not end the pass. Only `done`, so never a working or blocked session; an exited row is not tried, so it is never a failure."""
    stops = []
    for r in rows:
        if r['state'] == 'done' and r['pid']:
            try:
                if not r['id']:
                    raise ValueError('the row has no id to stop it by')
                stop(r['id'])
                stops.append({'name': r['name'], 'id': r['id'], 'stopped': True, 'error': None})
            except ValueError as x:
                stops.append({'name': r['name'], 'id': r['id'], 'stopped': False, 'error': str(x)})
    return stops, sum(1 for r in rows if r['state'] == 'done' and not r['pid'])


def _job_sh(argv):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60, creationflags=flags)
    return p.returncode, p.stdout + p.stderr


def read_pc_lock(sh=_job_sh):
    """The game lock as the watcher reports it (`lock` of `job.sh status`: owner, session, purpose, age_s, stale), the reader harness/ctl.py and
    harness/acceptance.py use; job.sh finds the adapter itself. None: the lock is free, or there is no harness here (job.sh exits 64: no adapter
    or watcher root, as in the core; no bash). ValueError: a harness that cannot answer, so whether a run holds the PC is unknown. The message
    carries nothing that changes between reads, so a deferral on it logs once."""
    bash = git_bash()
    if not bash:
        return None
    rc, out = sh([bash, str(JOB_SH), 'status'])
    if rc == 64:
        return None
    if rc != 0:
        raise ValueError(f'job.sh status exited {rc}: run it to see why')
    try:
        return json.loads(out[out.index('{'):out.rindex('}') + 1]).get('lock')
    except ValueError:
        raise ValueError('job.sh status did not print JSON')


def start_session(argv, root):
    """Start `claude --bg ...` from argv in the repo root (wsc may run from a subfolder) and return the id it prints. argv[0] is
    ignored: _claude resolves claude again."""
    rc, out, err = _claude(*argv[1:], cwd=root)
    if rc != 0:
        raise ValueError(f'exited {rc}: {(err or out).strip()[:300]}')
    m = re.search(r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?\b', out)
    return m.group(0) if m else out.strip()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        if self.server.log:
            sys.stderr.write('jobs serve: ' + fmt % a + '\n')

    def _send(self, code, body, ctype):
        data = body.encode('utf-8')
        self.send_response(code)
        for k, v in (('Content-Type', ctype), ('Content-Length', str(len(data))), ('Cache-Control', 'no-store'),
                     ('X-Frame-Options', 'DENY')):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        s = self.server
        if self.headers.get('Host') != s.host:   # a DNS-rebound name never gets the page, so never the token
            return self._send(403, f'open {s.url}', 'text/plain; charset=utf-8')
        if self.path.split('?')[0] != '/':
            return self._send(404, 'not found', 'text/plain; charset=utf-8')
        try:
            page = s.page()
        except Exception as x:
            return self._send(500, f'could not render the queue: {x}', 'text/plain; charset=utf-8')
        self._send(200, page, 'text/html; charset=utf-8')

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if self.path != '/launch' or not 0 <= n <= 4096:
            code, msg, extra = (404, 'not found', {}) if self.path != '/launch' else (413, 'body too large', {})
        else:
            code, msg, extra = self.server.launch_request(self.headers, self.rfile.read(n))
        self._send(code, json.dumps({'ok': code == 200, 'message': msg, **extra}), 'application/json')


def _session_job(agent, by):
    """The job id a session named `<id>-<action>` works on, when it is a row of `by` (case as the rows spell it), else None."""
    m = re.match(r'([A-Za-z]\d+)-', str(agent.get('name') or ''))
    return next((j for j in by if m and j.lower() == m.group(1).lower()), None)


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


class JobServer(ThreadingHTTPServer):
    """`wsc jobs view --serve` on 127.0.0.1: GET / renders the queue fresh, POST /launch starts one session after the checks of
    launch_request; with --auto, run_auto() ticks in a thread. Seams (the tests pass fakes): snapshot() -> (rows, read, branches,
    on_branch), read fresh each time; agents() -> the `claude agents --json --all` list; launch(argv) -> session id; which(name) -> path or
    None; log_path: the autopilot's log file (None: stderr only); pc_lock() -> read_pc_lock's answer (None = no lock is read)."""
    daemon_threads = True
    log = True   # one stderr line per request

    def __init__(self, snapshot, agents, launch, which=shutil.which, port=0, dry_run=False, root=None, log_path=None, ctx=None,
                 main_line=None, clock=time.monotonic, ci=None, prune=None, claim=None, pc_lock=None):
        super().__init__(('127.0.0.1', port), _Handler)
        self.snapshot, self.agents, self.launch, self.which, self.dry_run, self.root = snapshot, agents, launch, which, dry_run, root
        # W26 seams: ci(sha) -> (state, lines) (branch_ci; None = read it with gh in `root`); prune() -> (removed, error) (None = no prune)
        self.ci = ci if ci is not None else (lambda sha: branch_ci(root or '.', sha, False))
        self.prune, self.pc_lock = prune, pc_lock
        self.deferred = {}   # (id, action) -> the (head, reason) last logged as a deferral: one line per head and reason
        self.log_path = log_path
        self.ctx = ctx
        self.main_line, self.clock, self._main = main_line, clock, None   # main's CI line: `main_line()` -> html, memoised for 60 s (W22)
        self.claim = claim   # (id, round, head, session) -> (held, claims.Claim): the review claim (W27); None claims nothing
        self.token = secrets.token_urlsafe(32)
        self.host = f'127.0.0.1:{self.server_address[1]}'
        self.url = f'http://{self.host}/'
        self.lock = threading.Lock()
        self.auto = None   # {'interval', 'last', 'dry_run'} while the autopilot runs
        self.started = {}  # (id, action) -> the job branch head the autopilot started it at (J52 review 1)

    def page(self):
        rows, read, branches, on_branch = self.snapshot()
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        return render_view(rows, read, branches, stamp, on_branch, self.token, self.root, self.auto, self.ctx, self.main_html_cached())

    def main_html_cached(self):
        if not self.main_line:
            return ''
        now = self.clock()
        if self._main is None or now - self._main[0] >= 60:
            self._main = (now, self.main_line())
        return self._main[1]

    def start(self, jid, action, by, branches, on_branch, family=False, agents=None):
        """The one launch path (buttons and --auto): (code, message, extra). Readiness 409; a live session of the same name 429 (with
        `family`, any live J<n>-* session: a build or fix that pushed status=review but has not ended must not race its reviewer);
        an agent list that cannot be read 503 (fail closed); at the session cap 429 (W41); claude missing 503; for a review, the round's
        claim (W27): held by another session 409 naming it, unprovable 503; then the launch. A dry run claims nothing. `agents`: a list
        already read this tick, else it is read here."""
        why = not_ready(action, jid, by, branches, on_branch)
        if why:
            return 409, f'refused: {why}', {}
        name = f'{jid}-{action}'
        with self.lock:   # one launch at a time, so a double click cannot start the same session twice
            try:
                agents = self.agents() if agents is None else agents
            except Exception as x:
                return 503, f'refused: cannot list the running sessions ({x})', {}
            live = [str(a.get('name') or '') for a in agents if isinstance(a, dict) and a.get('state') in LIVE_STATES]
            clash = [n for n in live if (n.lower().startswith(f'{jid.lower()}-') if family else n.lower() == name.lower())]
            if clash:
                return 429, (f'refused: {clash[0]} is still running' if family else f'refused: {name} is already running'), {}
            full = cap_line(agents)
            if full:
                return 429, f'refused: {full}', {}
            claude = self.which('claude')
            if not claude:
                return 503, 'refused: claude is not on PATH', {}
            argv = launch_argv(claude, jid, action, by[jid])
            if self.dry_run:
                return 200, 'dry run, would start: ' + command_line(argv), {'argv': argv}
            if action == 'review' and self.claim:
                b = branch_state((on_branch or {}).get(jid))
                try:
                    held, c = self.claim(jid, b.rounds + 1, b.head, name)
                except Exception as x:
                    return 503, f'refused: cannot claim round {b.rounds + 1} of {jid} ({x})', {}
                if not held:
                    return 409, f'refused: round {b.rounds + 1} of {jid} is claimed by {c.session}', {}
            try:
                sid = self.launch(argv)
            except Exception as x:
                return 500, f'claude --bg failed: {x}', {'argv': argv}
        return 200, f'started {name}: claude attach {sid}', {'argv': argv, 'session': sid}

    def auto_log(self, line):
        line = f'{utc_now()} jobs auto: {line}'
        if self.log_path:   # the file first: a stop right after the stderr line must not lose it from the log
            try:
                Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_path, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except OSError as x:
                sys.stderr.write(f'jobs auto: cannot write {self.log_path}: {x}\n')
        sys.stderr.write(line + '\n')
        sys.stderr.flush()

    def auto_tick(self):
        """One autopilot pass: a fresh snapshot and agent list, then every job branch ready for review or fix is started through
        start(..., family=True). Never a brief or a build. A snapshot or agent-list error skips the whole tick. Each (id, action) is
        started at most once per branch head (J52 review 1): a session that ends without pushing leaves the row as it was, and must
        not be started again every tick until someone looks; a push moves the head and allows the next start. The memory is this
        process's: a restarted server may start such a job once more. Returns the (id, action, code, message) of every attempt.
        W26: the tick first prunes dead worktree registrations (decision 13); a review starts only on a green head and a fix waits while CI
        runs or has not reported (decision 11: one check-runs read per candidate head); a needs_pc row waits while another needs_pc row
        has a live session or was started this tick (decision 12). A deferral is logged once per head and reason, and is not a start.
        W41: a start counts against the session cap at once, in this tick's copy of the list; a full cap is one line per tick, not one per
        job; while an acceptance run holds the PC lock no needs_pc session starts (its window would land on the virtual display)."""
        if self.auto is not None:
            self.auto['last'] = utc_now()
        try:
            rows, _, branches, on_branch = self.snapshot()
        except Exception as x:
            self.auto_log(f'tick skipped: cannot read the queue ({x})')
            return []
        self.prune_tick()
        try:
            agents = list(self.agents())
        except Exception as x:
            self.auto_log(f'tick skipped: cannot list the running sessions ({x})')
            return []
        busy, capped = self.pc_busy(), False
        by = {r['id']: r for r in rows}
        pc_holders = [m for m in (_session_job(a, by) for a in agents if isinstance(a, dict) and a.get('state') in LIVE_STATES)
                      if m and by[m].get('needs_pc')]
        done, waiting = [], 0
        for jid in sorted(on_branch or {}, key=num):
            for action in BRANCH_ACTIONS:
                if jid not in by or not_ready(action, jid, by, branches, on_branch) is not None:
                    continue
                head = branch_state(on_branch[jid]).head
                if (jid, action) in self.started and self.started[(jid, action)] == head:
                    self.auto_log(f'{jid}-{action}: started at {(head or "unknown head")[:12]}, waiting for a push to job/{jid}')
                    waiting += 1
                    continue
                full = cap_line(agents)
                if full:
                    if not capped:
                        capped = True
                        self.auto_log(f'deferred, {full}')
                    waiting += 1
                    continue
                why = self.defer_reason(jid, action, head, by, pc_holders, busy)
                if why:
                    if self.deferred.get((jid, action)) != (head, why):
                        self.deferred[(jid, action)] = (head, why)
                        self.auto_log(f'{jid}-{action}: deferred, {why}')
                    waiting += 1
                    continue
                code, msg, _ = self.start(jid, action, by, branches, on_branch, family=True, agents=agents)
                if code == 200:
                    self.started[(jid, action)] = head
                    self.deferred.pop((jid, action), None)
                    agents.append({'name': f'{jid}-{action}', 'kind': 'background', 'state': 'working', 'pid': 'started this tick'})
                    if by[jid].get('needs_pc'):
                        pc_holders.append(jid)
                self.auto_log(f'{jid}-{action}: {msg}')
                done.append((jid, action, code, msg))
        if not done and not waiting:
            self.auto_log(f'tick: nothing ready for review or fix ({len(on_branch or {})} job branches)')
        return done

    def pc_busy(self):
        """Why this tick starts no needs_pc session, or None: an acceptance run holds the game lock (J64 run 20261104_j64pc4 lost a pass to a
        window on the virtual display), or the harness cannot say (fail closed, as for the agent list). A stale lock is on its way out."""
        if self.pc_lock is None:
            return None
        try:
            lock = self.pc_lock()
        except Exception as x:
            return f'cannot read the PC lock ({x})'
        if isinstance(lock, dict) and not lock.get('stale') and str(lock.get('purpose') or '').startswith(ACCEPTANCE_PURPOSE):
            return f"an acceptance run holds the PC lock ({lock.get('owner')})"
        return None

    def defer_reason(self, jid, action, head, by, pc_holders, busy=None):
        """Why the autopilot holds `jid`'s `action` this tick, or None. The PC rules first (no network), then the head's CI."""
        if by[jid].get('needs_pc'):
            other = [m for m in pc_holders if m != jid]
            if other:
                return f'{other[0]} holds the PC'
            if busy:
                return busy
        state, _ = self.ci(head)
        if (state != 'green') if action == 'review' else (state in ('running', 'none')):
            return f'CI {state} at {(head or "unknown")[:7]}'
        return None

    def prune_tick(self):
        """Decision 13: `git worktree prune` once per tick, one line only when it removed something or failed; a dry run only says so."""
        if self.prune is None:
            return
        if self.dry_run:
            self.auto_log('would prune dead worktree registrations')
            return
        try:
            removed, err = self.prune()
        except Exception as x:
            removed, err = 0, str(x) or type(x).__name__
        if err:
            self.auto_log(f'worktree prune failed: {err}')
        elif removed:
            self.auto_log(f'pruned {removed} dead worktree registrations')

    def run_auto(self, interval, stop):
        """Tick now, then every `interval` seconds until `stop` (a threading.Event) is set. An unexpected error is logged and the
        loop goes on."""
        self.auto = {'interval': interval, 'last': None, 'dry_run': self.dry_run}
        self.auto_log(f'on, every {interval} s{" (dry run: nothing is started)" if self.dry_run else ""}')
        while not stop.is_set():
            try:
                self.auto_tick()
            except Exception as x:
                self.auto_log(f'tick failed: {x!r}')
            stop.wait(interval)

    def launch_request(self, headers, body):
        """(HTTP code, message, extra JSON fields), checked in this order: token 403, Origin and Host 403, content type 415, id and
        action 400, then start(): readiness 409, a same-name session 429, the session cap 429, the launch."""
        try:
            req = json.loads(body.decode('utf-8'))
        except ValueError:
            req = None
        req = req if isinstance(req, dict) else {}
        tok = req.get('token')
        if not isinstance(tok, str) or not secrets.compare_digest(tok, self.token):
            return 403, 'refused: bad or missing token (reload the page from this server)', {}
        if headers.get('Origin') != self.url.rstrip('/') or headers.get('Host') != self.host:
            return 403, 'refused: the request did not come from this server\'s own page', {}
        if (headers.get('Content-Type') or '').split(';')[0].strip().lower() != 'application/json':
            return 415, 'refused: the body must be application/json', {}
        try:
            rows, _, branches, on_branch = self.snapshot()
        except Exception as x:
            return 503, f'refused: cannot read the queue ({x})', {}
        by = {r['id']: r for r in rows}
        jid, action = req.get('id'), req.get('action')
        if not isinstance(jid, str) or jid not in by or action not in PROMPTS:
            return 400, f'refused: no such job or action ({jid!r}, {action!r})', {}
        return self.start(jid, action, by, branches, on_branch)



def policy_cmd(jid_branch):
    """The command line that runs CI's policy check locally for a branch name (config `[jobs.text] policy`)."""
    return S.text['policy'].replace('{wsc}', S.text['wsc']) + f' --branch {jid_branch} --base origin/main'


def usage_step(jid, tail=''):
    """The step text that fills the report's usage line, for a job under the rule (W31)."""
    return f'{usage_write(jid)}{tail}, then ' if usage_rule(jid) else ''


def build_steps(r, sha=None, why=''):
    """`sha`: where `jobs next` claimed job/<id> (W26); None prints the push that would claim it."""
    jd = S.jobs_dir
    return (f'{r["id"]}: {r["title"]} (model {r["model"]}, needs_pc {"yes" if r["needs_pc"] else "no"})\n'
            f'{take_it("job/" + r["id"], sha, why)}, then follow {jd}/{r["id"]}/brief.md.\n'
            f'Finish: {jd}/{r["id"]}/report.md, then {usage_step(r["id"])}wsc reg set jobs {r["id"]} status=review report={jd}/{r["id"]}/report.md, pushed; '
            f'CI\'s policy check runs locally as {policy_cmd("job/" + r["id"])}.\n'
            + draft_pr_step(r['id'], r['title']))


def brief_steps(r, root, lead='needs a brief (nothing queued is ready)', sha=None, why=''):
    """`sha`: where `jobs next` claimed brief/<id> (W26); None prints the push that would claim it."""
    jd, T = S.jobs_dir, S.text
    owed = [f'{p.relative_to(root).as_posix()} {w}' for p in (sorted(Path(root).glob(S.ledgers)) if S.ledgers else []) if p.is_file()
            for w in waiting_rules(p.read_text(encoding='utf-8'), r['id'])]
    return (f'{r["id"]}: {r["title"]} {lead}.\n'
            f'{take_it("brief/" + r["id"], sha, why)}.\n'
            f'Write {jd}/{r["id"]}/brief.md on branch brief/{r["id"]} from the row, {T["plan_doc"]} and the reports of '
            f'{", ".join(r["depends_on"]) or "earlier jobs"}, in the shape `wsc jobs check` enforces' + ref('brief_model', ' ({} is the model)') + '; '
            f'then wsc reg set jobs {r["id"]} status=queued brief={jd}/{r["id"]}/brief.md, push, then queue the merge on green CI' + ref('ref_brief_merge') + ': '
            f'{policy_cmd("brief/" + r["id"])} (must say ok), '
            f'gh pr create --base main --head brief/{r["id"]} --title "brief: {r["id"]} {r["title"]}", '
            f'gh pr merge brief/{r["id"]} --auto --squash; do not wait or poll.'
            + ('\n' + T['brief_notes'] if T['brief_notes'] else '')
            + ''.join(f'\nThe brief must cover {o}' for o in owed))


def review_steps(jid, done_rounds=0, handback=False):
    n = done_rounds + 1
    jd, T = S.jobs_dir, S.text
    after = (f'then set the row and commit the review and the row (do not push yet): merge -> status=done review={jd}/{jid}/review.md, then '
             f'in this order ({T["review_doc"]} "Merging"): {policy_cmd("job/" + jid)} says ok, '
             f'gh pr view job/{jid} (gh pr create --draft --base main --head job/{jid} if there is none), gh pr ready job/{jid}, '
             f'git push, gh pr merge job/{jid} --auto --squash (ready before the push, so the pushed head gets a real policy run' + ref('ref_ready', ': {}') + '); '
             f'otherwise push, leave the draft pull request open (never gh pr ready) and set '
             + (f'status=fix review={jd}/{jid}/review.md (a fix session answers it, then round {n + 1})' if n < max_rounds(jid) else
                f'status=blocked blocked_by="{blocked_by_rounds(jid)}" review={jd}/{jid}/review.md (round {n} is the last: {T["owner"]} decides)'))
    return (f'{jid}: review branch job/{jid} (git checkout job/{jid}) following {T["review_doc"]}. You must not have built it, fixed it or '
            f'reviewed an earlier round: CI\'s policy check refuses a round written in a session that wrote report.md or an earlier round.\n'
            + (f'Read {jd}/{jid}/handback.md after the report: the builder\'s own words; the report says what the orchestrator added.\n' if handback else '')
            + f'This is round {n}: write "## Round {n} (YYYY-MM-DD, branch job/{jid} at <sha>)" with its one verdict line at the TOP of '
            f'{jd}/{jid}/review.md' + (', above the earlier rounds (read them first; never edit them: policy checks every commit)' if done_rounds else '')
            + '. If you change any file outside the job folder and its row, the verdict is `merge after fixes` (a fresh round reviews it)'
            + f'; {after}.')


def fix_steps(jid, n, title='', handback=False):
    jd = S.jobs_dir
    return (f'{jid}: fix round {n} on branch job/{jid} (git checkout job/{jid}). Read "## Round {n}" at the top of {jd}/{jid}/review.md '
            + (f'(and {jd}/{jid}/handback.md, the builder\'s own words) ' if handback else '') +
            f'and address its blockers and should-fix items, one commit each where you can, with a test where the code allows.\n'
            f'Then append "## Fix round {n}" to the end of {jd}/{jid}/report.md: for each finding what you changed (commit sha), what you '
            f'left and why. Run {usage_step(jid, " (the line counts fix sessions too)")}{S.text["wsc"]} gates and {policy_cmd("job/" + jid)} (only '
            f'the missing merge verdict and done row may fail), then wsc reg set jobs {jid} status=review and push. '
            f'Never touch review.md or earlier report sections, and never merge: the next review round is a fresh session.\n'
            + draft_pr_step(jid, title or '<title>'))


