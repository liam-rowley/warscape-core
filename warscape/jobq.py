"""The job queue, as library code (verb: warscape/verbs/jobs.py): the queue rules, the readiness rule, branch reading, the step texts, the
status page and its launch server. Moved from napoleon-remastered `tools/verbs/jobs.py` (napoleon J62); every game-specific string and
rule is repo configuration (`wsc.toml` [jobs], [jobs.text]) or a hook module (`warscape/hooks.py`), so a repo with none of them is a plain queue.

Settings: the module-level `S` holds what the repo configured (`configure(ctx)` fills it from `ctx.config['jobs']`; the defaults are the
generic ones). Tests that want a different configuration call `configure_from(cfg)`.

Rules in short (details in docs/REVIEW.md of the repo that uses them): rows are checked against `jobs/<id>/` files; a job is built on branch
`job/<id>`, briefed on `brief/<id>`; review.md holds `## Round N (YYYY-MM-DD, branch job/<id> at <sha>)` sections, newest first, at most 3, one
verdict each; the reviewer sets the row (merge -> done, otherwise fix, or blocked after round 3); `--serve --auto` starts ready reviews and fixes.
`claude agents --json` (Claude Code 2.1.316, read on the PC 2026-10-31, napoleon J52): lists background sessions with `state` "working", "blocked"
(waiting for input) or "done" (finished sessions stay listed until removed); interactive sessions carry no state. Live = working or blocked.
"""
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple, Optional

from . import hooks
from .policy import verdict
from .repo import DEFAULTS



class Settings:
    """What the repo configured for the queue (`wsc.toml` [jobs]); the defaults here are the plain, generic queue."""
    prefix = 'J'
    models = ['sonnet', 'opus']
    jobs_dir = 'jobs'
    reg_dir = 'registries'
    ledgers = ''
    legacy_rounds = frozenset()
    legacy_briefs = frozenset()
    hooks = ()
    text = dict(DEFAULTS['jobs']['text'])


S = Settings()


def configure_from(cfg, root=None, reg_dir='registries'):
    """Fill S from a `[jobs]` table (defaults merged) and, when `root` is given, its legacy file and hook modules."""
    S.prefix, S.models, S.jobs_dir, S.reg_dir, S.ledgers = cfg['id_prefix'], list(cfg['models']), cfg['dir'], reg_dir, cfg['ledgers']
    S.text = dict(cfg['text'])
    S.legacy_rounds = S.legacy_briefs = frozenset()
    S.hooks = ()
    if root is not None:
        if cfg['legacy']:
            data = json.loads((Path(root) / cfg['legacy']).read_text(encoding='utf-8'))
            S.legacy_rounds, S.legacy_briefs = frozenset(data.get('round_rules', [])), frozenset(data.get('brief_hooks', []))
        S.hooks = hooks.load(root, cfg['hooks'])
    return S


def configure(ctx):
    return configure_from(ctx.config['jobs'], ctx.root, ctx.config['registries_dir'])


def ref(key, fmt=' ({})'):
    """A reference text from [jobs.text] formatted into a message, or '' when the repo set none."""
    v = S.text.get(key, '')
    return fmt.format(v) if v else ''


def call_hooks(name, ctx, *args, joiner=None):
    """The results of hook `name` in every configured module that defines it (hooks.py): lists are concatenated, strings joined."""
    out = []
    for m in S.hooks:
        f = getattr(m, name, None)
        if f:
            out += list(f(ctx, *args)) if joiner is None else [f(ctx, *args)]
    return out


STATUSES_WITH = {'brief': {'queued', 'review', 'fix', 'done'}, 'report': {'review', 'fix', 'done'}, 'review': {'fix', 'done'}}
DATED = re.compile(r'\b20\d\d-\d\d-\d\d\b')
ROUND = re.compile(r'^## Round\b.*$', re.M)
ROUND_HEAD = re.compile(r'^## Round ([1-9]\d*) \(20\d\d-\d\d-\d\d, branch `?job/[A-Z]\d+`? at `?[0-9a-f]{7,40}`?\)\s*$')
MAX_ROUNDS = 3
BLOCKED_BY_ROUNDS = f'{MAX_ROUNDS} review rounds without merge'
def num(jid):
    return int(jid[1:]) if re.fullmatch(r'[A-Z]\d+', jid or '') else 10 ** 9


# ------------------------------------------------------------------ check
def brief_problems(jid, row, text, ctx=None):
    """Shape every brief must have (the Model line rule and the Finish rule): Model line agreeing with the row (a reason when Opus), a call budget,
    kill criteria, and a Finish section that ends with the status=review command. With `ctx`, a brief whose id is not in the legacy
    `brief_hooks` list also passes every `brief_problems(ctx, jid, row, text)` hook (hooks.py): a game's own brief rules."""
    errs = []
    if ctx is not None and jid not in S.legacy_briefs:
        errs += call_hooks('brief_problems', ctx, jid, row, text)
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
    if not re.search(r'[Bb]udget\s+about\s+\d+\s+tool\s+calls', text):
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


def round_problems(text):
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
    if len(rounds) > MAX_ROUNDS:
        errs.append(f'review.md has {len(rounds)} rounds: at most {MAX_ROUNDS} (after round {MAX_ROUNDS} without merge the job is blocked)')
    if nums != list(range(len(nums), 0, -1)):
        errs.append(f'rounds are {", ".join(map(str, nums))}: they must count up from 1 with no gap, newest first '
                    f'(want {", ".join(map(str, range(len(nums), 0, -1)))})')
    if verdict_lines(pre):
        errs.append('a verdict line sits above the first round: each verdict belongs inside its round')
    return errs


def round_status_problems(row, review, report):
    """The row must agree with the newest round's verdict: merge -> done; a non-merge in round N < 3 -> fix, or review once
    report.md has "## Fix round N"; a non-merge in round 3 -> blocked with BLOCKED_BY_ROUNDS."""
    st, n, v = row.get('status'), round_count(review), verdict(review)
    if v not in ('merge', 'merge after fixes', 'do not merge') or not n:
        return []   # reported by the verdict and round rules
    if v == 'merge':
        return [] if st == 'done' else [f'round {n} says merge, so the row should be done, not {st}']
    if n >= MAX_ROUNDS:
        if st == 'blocked' and row.get('blocked_by') == BLOCKED_BY_ROUNDS:
            return []
        return [f'round {n} says "{v}": the row must be blocked with blocked_by="{BLOCKED_BY_ROUNDS}", not {st}']
    fixed = bool(re.search(rf'^## Fix round {n}\b', report or '', re.M))
    if st == 'fix' and not fixed:
        return []
    if st == 'review' and fixed:
        return []
    want = 'review (report.md has "## Fix round %d")' % n if fixed else f'fix (report.md has no "## Fix round {n}" yet)'
    return [f'round {n} says "{v}", so the row should be {want}, not {st}']


def problems(rows, read, folders=(), ctx=None):
    """Errors for the queue. `rows`: the jobs rows; `read(path)`: file text or None; `folders`: job ids that have a jobs/<id>/ folder;
    `ctx`: the repo context, which switches the brief hooks on (see brief_problems)."""
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
        if st == 'needs_brief' and read(f'{S.jobs_dir}/{jid}/brief.md') is not None:
            errs.append(f'{jid}: has a brief but is still needs_brief (set status=queued brief={S.jobs_dir}/{jid}/brief.md)')
        brief = read(f'{S.jobs_dir}/{jid}/brief.md')
        if brief is not None:
            errs += [f'{jid}: brief: {e}' for e in brief_problems(jid, r, brief, ctx)]
        report = read(f'{S.jobs_dir}/{jid}/report.md')
        if report is not None:
            errs += [f'{jid}: report: {e}' for e in report_problems(jid, report)]
        review = read(f'{S.jobs_dir}/{jid}/review.md')
        if review is not None:
            if not DATED.search('\n'.join(review.split('\n')[:5])):
                errs.append(f'{jid}: review.md has no date in its first lines' + ref('review_doc', ' ({}: dated at the top)'))
            if verdict(review) not in ('merge', 'merge after fixes', 'do not merge'):
                errs.append(f'{jid}: review.md has no Verdict line of the three allowed' + ref('review_doc', ' ({} "Output")'))
            elif st == 'done' and verdict(review) != 'merge':
                errs.append(f'{jid}: done, but the review verdict is "{verdict(review)}" (only "merge" makes a job done)')
            if jid not in S.legacy_rounds:
                errs += [f'{jid}: {e}' for e in round_problems(review) + round_status_problems(r, review, report)]
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
    """What branch_rows reads from one origin/job/<id>: its row, the rounds in its review.md, its head sha."""
    row: Optional[dict]
    rounds: int = 0
    head: Optional[str] = None


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
        row, rounds, _ = branch_state((on_branch or {}).get(jid))
        if not row:
            return f'job/{jid} has no {jid} row'
        if row.get('status') != action:
            return f'{jid} is {row.get("status")} on job/{jid}, not {action}' + (' (no report yet)' if row.get('status') == 'queued' else '')
        if action == 'review' and rounds >= MAX_ROUNDS:
            return f'{jid}: review.md already has {rounds} rounds; after round {MAX_ROUNDS} the job is blocked for {S.text["owner"]}' + ref('ref_rounds')
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
    return None


def pick_next(rows, branches):
    """(kind, row, waiting): the lowest-numbered ready job to build ('job'), else the lowest ready job to brief ('brief'), else
    (None, None, waiting). Ready: not_ready() says None for 'build' (then 'brief')."""
    by = {r['id']: r for r in rows}
    waiting = []
    order = sorted(rows, key=lambda r: num(r['id']))
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


def branch_checks(root, branch, sha, offline, run=subprocess.run):
    """The CI block `jobs review` and `jobs fix` print above their steps: every check run on the branch's head commit that failed or is
    still running, or one line saying all passed, none ran yet or why they could not be read (never an exception, as red_prs)."""
    where = f'{branch} at {sha[:7]}' if sha else branch
    if offline:
        return f'(CI checks on {where} not read: --offline; read them before a verdict)'
    if not sha:
        return f'(CI checks on {branch} not read: its head commit is unknown)'
    try:   # gh fills {owner}/{repo} from this clone's origin
        p = run(['gh', 'api', f'repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100'],
                cwd=str(root), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as x:
        return f'(CI checks on {where} could not be read: {x}; --offline skips this)'
    if p.returncode != 0:
        return f'(CI checks on {where} could not be read: {(p.stderr or p.stdout).strip()[:200]}; --offline skips this)'
    try:
        runs = json.loads(p.stdout or '{}').get('check_runs') or []
    except (ValueError, AttributeError) as x:
        return f'(CI checks on {where} could not be read: {x})'
    if not runs:
        return f'CI on {where}: no check runs yet (CI has not reported; {checks_lead()})'
    bad = check_lines(runs)
    if not bad:
        return f'CI on {where}: all {len(runs)} checks passed or were skipped.'
    return f'CI on {where} ({checks_lead()}):\n  ' + '\n  '.join(bad)


def draft_pr_step(jid, title):
    """The last step of a build or a fix: the job's pull request, opened as a draft when none exists (J54); never a merge."""
    return (f"Then open the pull request as a draft if none exists, so the review sees the branch's CI (CI's policy check skips drafts): "
            f'gh pr view job/{jid}, else gh pr create --draft --base main --head job/{jid} --title "{jid}: {title}" '
            f'--body "<the first paragraph of {S.jobs_dir}/{jid}/report.md>". Never merge it: the reviewer marks it ready and merges' + ref('ref_merge') + '.')


def _git(root, *args):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=300)
    return p.stdout if p.returncode == 0 else None


def remote_branches(root, offline):
    if offline:
        out = _git(root, 'for-each-ref', '--format=%(refname:strip=3)', 'refs/remotes/origin/') or ''
        return set(out.split())
    out = _git(root, 'ls-remote', '--heads', 'origin', 'job/*', 'brief/*')
    if out is None:
        raise ValueError('git ls-remote origin failed (no network or no origin): rerun with --offline to use local refs')
    return {l.split('refs/heads/', 1)[1] for l in out.splitlines() if 'refs/heads/' in l}


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
    return [(f'{ref}:{reg_dir}/jobs/{jid}.json', lambda text: json.loads(text) if text else None),
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
    got = _blobs(root, [s for j in ids for s, _ in rows[j]] + [reviews[j] for j in ids], run)
    row = lambda j: next((parse(got[s]) for s, parse in rows[j] if got.get(s) is not None), None)
    return {j: Branch(row(j), round_count(got.get(reviews[j])), heads.get(j)) for j in ids}


# ------------------------------------------------------------------ launch (the view's buttons)
PROMPTS = {'brief': 'Write the brief for job {id}: git pull, then run {wsc} jobs next --id {id} and follow it.',
           'build': 'Pick up job {id}: git pull, then run {wsc} jobs next --id {id} and follow it.',
           'review': 'Review job {id}: git pull, then run {wsc} jobs review --id {id} and follow {review_doc}.',
           'fix': 'Fix job {id}: git pull, then run {wsc} jobs fix --id {id} and follow it.'}
LABELS = {'brief': 'Write brief', 'build': 'Implement', 'review': 'Review', 'fix': 'Fix'}
LIVE_STATES = {'working', 'blocked'}   # `claude agents --json` states of a session that has not ended ("done" stays listed: J52)


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
    return [json.loads(l) for l in (text or '').splitlines() if l.strip()]


# ------------------------------------------------------------------ view
# (key, heading, what it means): the page's sections, in reading order.
LANES = [('progress', 'In progress', 'a job/ or brief/ branch is open on origin'),
         ('review', 'Waiting for review', 'report written; needs an independent review (wsc jobs review)'),
         ('fix', 'Waiting for fixes', 'a review round asked for changes; a fix session answers it (wsc jobs fix)'),
         ('ready', 'Ready to pick up', 'queued, every dependency done, nobody on it'),
         ('waiting', 'Queued, waiting on dependencies', 'brief written; a dependency is not done yet'),
         ('brief', 'Needs a brief', 'no brief yet; one can be written once the dependencies make sense'),
         ('blocked', 'Blocked', 'stopped on something outside the queue'),
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
    if st == 'queued':
        return ('waiting', 'waits for ' + ', '.join(late)) if late else ('ready', '')
    return 'brief', ('waits for ' + ', '.join(late)) if late else 'can be briefed now'


def render_view(rows, read, branches, generated, on_branch=None, token=None, root=None, auto=None, ctx=None):
    """The queue as one HTML page. `read(path)`: file text or None; `branches`: remote branch names; `generated`: timestamp text;
    `on_branch`: see branch_rows (review and fix buttons need it). Brief, report and review are embedded as escaped Markdown and rendered by
    marked.js when it loads (plain text otherwise). A card gets a button for each action not_ready() allows: with `token` (served by
    `--serve`) it posts (id, action) to /launch; without, it copies the command line (run in `root`). `auto`: the autopilot's state
    ({'interval', 'last', 'dry_run'}) when `--auto` runs."""
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
    if ctx is not None:
        panel = ''.join(call_hooks('view_panel', ctx, joiner=''))   # a game's own status line (view_panel hook)
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
        acts = [a for a in PROMPTS if not_ready(a, jid, by, branches, on_branch) is None]
        buttons = (('<div class="acts">' + ''.join(
            f'<button class="launch" data-id="{e(jid)}" data-act="{a}" data-cmd="{e(command_line(launch_argv("claude", jid, a, r), root))}">'
            f'{LABELS[a]}</button>' for a in acts) + '<output class="result"></output></div>') if acts else '')
        return (f'<article class="card" id="{e(jid)}" data-text="{e((jid + " " + r.get("title", "") + " " + r.get("description", "")).lower())}">'
                f'<header><span class="id">{e(jid)}</span><h3>{e(r.get("title", ""))}</h3><span class="status s-{e(r.get("status", ""))}">'
                f'{e(r.get("status", ""))}</span></header>'
                + (f'<p class="note">{e(note)}</p>' if note else '')
                + f'<p class="desc">{e(r.get("description", ""))}</p>'
                f'<p class="meta">{" · ".join(e(t) for t in tags)} · depends on {deps}</p>{buttons}{docs}</article>')

    counts = ''.join(f'<a class="count" href="#lane-{k}"><b>{len(placed[k])}</b> {e(h)}</a>' for k, h, _ in LANES)
    lanes = ''.join(f'<section class="lane" id="lane-{k}"><h2>{e(h)} <span class="muted">({len(placed[k])})</span></h2>'
                    f'<p class="muted">{e(why)}</p>' + ''.join(card(r, n) for r, n in placed[k]) + '</section>'
                    for k, h, why in LANES if placed[k])
    refresh = ('Served by <code>wsc jobs view --serve</code>: reload to refresh; the buttons start background sessions.' if token else
               'Rerun it to refresh; the buttons copy the command (<code>wsc jobs view --serve</code> makes them start it).')
    if auto:
        refresh += (f' <b>Autopilot on</b>{" (dry run)" if auto.get("dry_run") else ""}: starts ready reviews and fixes every '
                    f'{int(auto["interval"])} s; last ran {e(auto.get("last") or "not yet")} (log: <code>_scratch/jobs_auto.log</code>).')
    return VIEW_PAGE.format(reg_jobs=e(S.reg_dir + '/jobs/'), jobs_dir=e(S.jobs_dir), generated=e(generated), head=head, counts=counts, lanes=lanes, total=len(rows), refresh=refresh,
                            serve=json.dumps({'token': token} if token else None))


VIEW_PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
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
.s-needs_brief {{ color:var(--needs); }} .s-blocked, .s-unknown {{ color:var(--blocked); }}
.note {{ color:var(--review); font-size:14px; }} .desc {{ margin:6px 0; }} .meta {{ color:var(--muted); font-size:13px; }}
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
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script>
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
    """`claude agents --json` as a list of sessions; ValueError when it cannot be read (the launch then fails closed)."""
    rc, out, err = _claude('agents', '--json', timeout=60)
    if rc != 0:
        raise ValueError(f'claude agents --json exited {rc}: {err.strip()[:200]}')
    try:
        agents = json.loads(out)
    except ValueError:
        raise ValueError('claude agents --json did not print JSON')
    if not isinstance(agents, list):
        raise ValueError('claude agents --json did not print a list')
    return agents


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


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


class JobServer(ThreadingHTTPServer):
    """`wsc jobs view --serve` on 127.0.0.1: GET / renders the queue fresh, POST /launch starts one session after the checks of
    launch_request; with --auto, run_auto() ticks in a thread. Seams (the tests pass fakes): snapshot() -> (rows, read, branches,
    on_branch), read fresh each time; agents() -> the `claude agents --json` list; launch(argv) -> session id; which(name) -> path or
    None; log_path: the autopilot's log file (None: stderr only)."""
    daemon_threads = True
    log = True   # one stderr line per request

    def __init__(self, snapshot, agents, launch, which=shutil.which, port=0, dry_run=False, root=None, log_path=None, ctx=None):
        super().__init__(('127.0.0.1', port), _Handler)
        self.snapshot, self.agents, self.launch, self.which, self.dry_run, self.root = snapshot, agents, launch, which, dry_run, root
        self.log_path = log_path
        self.ctx = ctx
        self.token = secrets.token_urlsafe(32)
        self.host = f'127.0.0.1:{self.server_address[1]}'
        self.url = f'http://{self.host}/'
        self.lock = threading.Lock()
        self.auto = None   # {'interval', 'last', 'dry_run'} while the autopilot runs
        self.started = {}  # (id, action) -> the job branch head the autopilot started it at (J52 review 1)

    def page(self):
        rows, read, branches, on_branch = self.snapshot()
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        return render_view(rows, read, branches, stamp, on_branch, self.token, self.root, self.auto, self.ctx)

    def start(self, jid, action, by, branches, on_branch, family=False, agents=None):
        """The one launch path (buttons and --auto): (code, message, extra). Readiness 409; a live session of the same name 429 (with
        `family`, any live J<n>-* session: a build or fix that pushed status=review but has not ended must not race its reviewer);
        an agent list that cannot be read 503 (fail closed); claude missing 503; then the launch (no count cap). `agents`: a
        list already read this tick, else it is read here."""
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
            claude = self.which('claude')
            if not claude:
                return 503, 'refused: claude is not on PATH', {}
            argv = launch_argv(claude, jid, action, by[jid])
            if self.dry_run:
                return 200, 'dry run, would start: ' + command_line(argv), {'argv': argv}
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
        process's: a restarted server may start such a job once more. Returns the (id, action, code, message) of every attempt."""
        if self.auto is not None:
            self.auto['last'] = utc_now()
        try:
            rows, _, branches, on_branch = self.snapshot()
        except Exception as x:
            self.auto_log(f'tick skipped: cannot read the queue ({x})')
            return []
        try:
            agents = self.agents()
        except Exception as x:
            self.auto_log(f'tick skipped: cannot list the running sessions ({x})')
            return []
        by = {r['id']: r for r in rows}
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
                code, msg, _ = self.start(jid, action, by, branches, on_branch, family=True, agents=agents)
                if code == 200:
                    self.started[(jid, action)] = head
                self.auto_log(f'{jid}-{action}: {msg}')
                done.append((jid, action, code, msg))
        if not done and not waiting:
            self.auto_log(f'tick: nothing ready for review or fix ({len(on_branch or {})} job branches)')
        return done

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
        action 400, then start(): readiness 409, a same-name session 429, the launch (no count cap)."""
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


def build_steps(r):
    jd = S.jobs_dir
    return (f'{r["id"]}: {r["title"]} (model {r["model"]}, needs_pc {"yes" if r["needs_pc"] else "no"})\n'
            f'Take it: git checkout -b job/{r["id"]} origin/main, follow {jd}/{r["id"]}/brief.md, push early so the branch claims it.\n'
            f'Finish: {jd}/{r["id"]}/report.md, then wsc reg set jobs {r["id"]} status=review report={jd}/{r["id"]}/report.md, pushed; '
            f'CI\'s policy check runs locally as {policy_cmd("job/" + r["id"])}.\n'
            + draft_pr_step(r['id'], r['title']))


def brief_steps(r, root, lead='needs a brief (nothing queued is ready)'):
    jd, T = S.jobs_dir, S.text
    owed = [f'{p.relative_to(root).as_posix()} {w}' for p in (sorted(root.glob(S.ledgers)) if S.ledgers else []) if p.is_file()
            for w in waiting_rules(p.read_text(encoding='utf-8'), r['id'])]
    return (f'{r["id"]}: {r["title"]} {lead}.\n'
            f'Write {jd}/{r["id"]}/brief.md on branch brief/{r["id"]} from the row, {T["plan_doc"]} and the reports of '
            f'{", ".join(r["depends_on"]) or "earlier jobs"}, in the shape `wsc jobs check` enforces' + ref('brief_model', ' ({} is the model)') + '; '
            f'then wsc reg set jobs {r["id"]} status=queued brief={jd}/{r["id"]}/brief.md, push, then queue the merge on green CI' + ref('ref_brief_merge') + ': '
            f'{policy_cmd("brief/" + r["id"])} (must say ok), '
            f'gh pr create --base main --head brief/{r["id"]} --title "brief: {r["id"]} {r["title"]}", '
            f'gh pr merge brief/{r["id"]} --auto --squash; do not wait or poll.'
            + ('\n' + T['brief_notes'] if T['brief_notes'] else '')
            + ''.join(f'\nThe brief must cover {o}' for o in owed))


def review_steps(jid, done_rounds=0):
    n = done_rounds + 1
    jd, T = S.jobs_dir, S.text
    after = (f'then set the row and commit the review and the row (do not push yet): merge -> status=done review={jd}/{jid}/review.md, then '
             f'in this order ({T["review_doc"]} "Merging"): {policy_cmd("job/" + jid)} says ok, '
             f'gh pr view job/{jid} (gh pr create --draft --base main --head job/{jid} if there is none), gh pr ready job/{jid}, '
             f'git push, gh pr merge job/{jid} --auto --squash (ready before the push, so the pushed head gets a real policy run' + ref('ref_ready', ': {}') + '); '
             f'otherwise push, leave the draft pull request open (never gh pr ready) and set '
             + (f'status=fix review={jd}/{jid}/review.md (a fix session answers it, then round {n + 1})' if n < MAX_ROUNDS else
                f'status=blocked blocked_by="{BLOCKED_BY_ROUNDS}" review={jd}/{jid}/review.md (round {MAX_ROUNDS} is the last: {T["owner"]} decides)'))
    return (f'{jid}: review branch job/{jid} (git checkout job/{jid}) following {T["review_doc"]}. You must not have built it or fixed it: '
            f'CI\'s policy check refuses a review.md written in a session that wrote report.md.\n'
            f'This is round {n}: write "## Round {n} (YYYY-MM-DD, branch job/{jid} at <sha>)" with its one verdict line at the TOP of '
            f'{jd}/{jid}/review.md' + (', above the earlier rounds (read them first; never edit them)' if done_rounds else '') + f'; {after}.')


def fix_steps(jid, n, title=''):
    jd = S.jobs_dir
    return (f'{jid}: fix round {n} on branch job/{jid} (git checkout job/{jid}). Read "## Round {n}" at the top of {jd}/{jid}/review.md '
            f'and address its blockers and should-fix items, one commit each where you can, with a test where the code allows.\n'
            f'Then append "## Fix round {n}" to the end of {jd}/{jid}/report.md: for each finding what you changed (commit sha), what you '
            f'left and why. Run {S.text["wsc"]} gates and {policy_cmd("job/" + jid)} (only '
            f'the missing merge verdict and done row may fail), then wsc reg set jobs {jid} status=review and push. '
            f'Never touch review.md or earlier report sections, and never merge: the next review round is a fresh session.\n'
            + draft_pr_step(jid, title or '<title>'))


