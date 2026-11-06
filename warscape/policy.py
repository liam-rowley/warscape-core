"""Pull-request policy as library code (verb: warscape/verbs/policy.py): every change reaches `main` through the job queue.

Moved from napoleon-remastered `tools/pr_policy.py` (napoleon J62). The branch name decides what a pull request may change:

  job/<id>    any files, but only row <id> of the jobs registry; <jobs dir>/<id>/brief.md must already be on the base; the branch must
              carry <id>/report.md and <id>/review.md whose verdict line says exactly "merge"; row <id> must be `done`; no session (the
              `[policy] session_trailer` commit trailer) that wrote the report may write the review (never review your own job), and
              every commit touching the report or the review must carry that trailer (fails closed). From job number `[jobs] semver_from`
              on (W29, C27) it may not change VERSION: the release workflow owns it.
              Review integrity (core W27), read from the branch's commits by sha:
                A  a round's own commits change a file outside <jobs dir>/<id>/ and row <id> under a `merge` verdict, and no commit that first wrote a newer
                   round descends from them (a fresh round has then reviewed the change: W40, the one way out, as rule C keeps the old verdict). A warning,
                   or with `[policy] reviewer_code = "error"` (W40; the core's own wsc.toml) a refusal. A round's commits:
                   the review.md commits whose review.md holds round N as its newest, any other commit by a session of those, and a commit by nobody
                   known (no trailer, or a session neither the builder's nor a round's) after the first review commit, which goes to the round of
                   the next review commit (the newest round when none follows). The builder's sessions are every report.md writer (fix sessions too).
                B  each round's sessions are disjoint from the builder's and from every earlier round's.
                C  review rounds are append only: each base round is unchanged at the head, and on every commit an earlier round stays
                   byte-identical once a newer round exists (a rewrite then a restore is refused); before that only its author edits it.
                D  in report.md and review.md at the head: a repo-relative `<path>/runs/<name>` (RUN_PATH: not inside a URL or an absolute path)
                   must exist in the head or the base tree (error); a `job/<X><n>`, `brief/<X><n>` or `origin/<ref>` (BRANCH_CITE, ORIGIN_CITE;
                   not the branch itself, origin/main, origin/HEAD or the base) must be an ancestor of the base or a tag's target, or (squash
                   merges) a job row `done` / a brief on the base: else a warning (unmerged, or not in this clone); a commit sha (SHA_WORD: 7-40 hex
                   in backticks after "commit(s)" or "sha(s)", a list of them; SHA_AT: after `@`) must be reachable from the base or the head or be a
                   tag's target, else a warning.
                E  (warning) a `merge` on more than `[policy] thin_merge_lines` changed lines or `thin_merge_files` files outside the jobs folder and
                   the registries whose newest round cites no evidence (EVIDENCE: a run id, an actions URL, `run <digits>`, a test name, a runs/ path).
                F  with `[policy] decisions_cite_job`, a decisions row added on job/<id> contains <id>.
              Rule A warns by default and D's branch cites warn: the W27 scan of the merged job branches (its report) passed the brief's kill
              criterion; the W40 scan (its report) put the core's rule A at error.
              Workflow inputs (core W36): a changed path matching `[policy] workflow_paths`, and the rendered file of a changed `<template_dir>/<name>.in`
              (the re-render changes both), that <id>'s brief on the base does not contain as a plain substring is a warning per path, so a job
              cannot quietly add a check that posts a fake `policy` status. It warns, not refuses: the W36 scan passed the brief's kill criterion. `brief/`,
              `plan/` and `release/` cannot touch these paths; `meta/` is the sanctioned route, which Liam reviews.
  release/vX.Y.Z  only VERSION, whose content is X.Y.Z, exactly one patch, minor or major step above the base's VERSION (W29, C27: the
              branch the release workflow opens; the workflow re-derives the version before it tags, so a hand-made one tags nothing).
  brief/<id>  only <jobs dir>/<id>/brief.md and row <id> of the jobs registry (which must be `queued` with its brief).
  plan/*      planning: the `[policy] plan` globs. No code.
  meta/*      repo infrastructure: the `[policy] meta` globs.
Anything else is refused. Globs match by path segment (`*` and `?` inside one segment, `**` across folders: repo.matches). Every branch
kind: the `[policy] decisions` file is append only (existing rows unchanged and in order; new rows numbered <prefix><last+1>, with a
YYYY-MM-DD date and Reversible yes or no); a reversal is a new row that names the one it replaces. With `decisions = "registry:<name>"` (core W43)
the same rule holds per file: a row file on the base never changes, moves or goes, and an added one is a minted id (`wsc reg add <name> --mint`) with
those fields and `replaces` naming rows that exist. `changed` runs from the merge base, so a branch behind the base has nothing to merge first. While
`[policy] decisions_retired` names the Markdown file that registry replaced, a head that changes the file's table is refused on every branch kind, as the
`registries` gate cannot reach a head cut before the key (prose may change and the file may go). A repo's own rules (napoleon's rule 79,
the acceptance ledger) come from its `policy`-stage gate modules (warscape/gatemods.py), run after the decisions check: an `error`
Result's details are policy errors. Their facts carry `added_decision_rows` ([{id, text}], W27). Warnings print as `policy: warning: ...` lines
before the verdict line and never change the exit code.

A base given as `origin/<name>` must be listed in the base's `[policy] bases` (core W36; [] accepts any, a sha or other ref is not judged by this):
a stacked pull request is refused before the head is read. A pull request is judged with its base's rules (core W23, C24). The verb's parent
(warscape/policy_base.py `judge`) writes the base's rule inputs into a fresh temporary folder outside every repository and runs the base's code
there in a child process (`wsc policy --judge`, which calls `run_check` here):
  - the base tree: inside the core, the base commit's tree; in a game, the core commit the base's gitlink pins at the base's `[ci] core`, read
    from the submodule's object store (never `core/` on disk, never the head's gitlink), plus the base's wsc.toml, every `[gates] dirs`
    folder and the `[jobs] legacy` file. Git cannot find a repository from inside it (GIT_CEILING_DIRECTORIES);
  - the head is data: the changed paths (merge base ... head, renames as a delete and an add), the blobs the rules read and the trailers of
    its commits, read with git at the clone by sha. Nothing of the head is imported, executed or parsed as configuration;
  - a branch that changes a rule input (the core, wsc.toml, the gate folders, the legacy file, the policy workflow or its template) gets a
    note: what it changes judges the pull requests after it, never itself;
  - fails closed: a ref that does not resolve, no merge base, an unreadable base wsc.toml, a missing gitlink, submodule or pin, an extraction
    error, or a child that gives no verdict (any other exit, a crash, a timeout) is a refusal that names the fix;
  - a base whose core has no `JUDGE_API` line predates W23: it is judged in-process with this checkout's code and configuration, with a note.
`JUDGE_API` versions the child's arguments; a later core may only add optional ones, passed when the base's number allows them.

`scan` (`wsc policy --scan`, W40) re-measures the rules over history, so a warning's move to an error rests on a number: W27's method, every merged
job/ pull request judged at its head against its merge commit's first parent with this checkout's rules, gate modules off and rule F on.
"""
import copy
import json
import re
import subprocess
import tomllib
from pathlib import Path

from . import gatemods
from .registry import file_to_id
from .repo import DEFAULTS, Ctx, decisions_registry, git_env, matches

# The judge's interface (the `--judge` child's arguments), read from a base core's text by warscape/policy_base.py: keep it on a line of its own.
JUDGE_API = 1


class Refusal(Exception):
    """The base's rules cannot be run: a refusal (exit 1) whose message names the fix."""


def settings(config):
    """The policy settings from a loaded wsc.toml: `[policy]` plus the pieces of `[jobs]` and `registries_dir` the rules need."""
    p, j, dreg = config['policy'], config['jobs'], decisions_registry(config)
    return {'decisions': p['decisions'], 'decisions_dir': f"{config['registries_dir']}/{dreg}" if dreg else '', 'decisions_retired': p['decisions_retired'] if dreg else '', 'prefix': p['decision_prefix'], 'trailer': p['session_trailer'], 'plan': list(p['plan']),
            'meta': list(p['meta']), 'bootstrap': list(p['bootstrap']), 'job_prefix': j['id_prefix'], 'semver_from': j.get('semver_from', 0), 'jobs_dir': j['dir'], 'reg_jobs': f"{config['registries_dir']}/jobs",
            'reg_jsonl': f"{config['registries_dir']}/jobs.jsonl",
            'views': [f"{config['registries_dir']}/{n}.md" for n in config['registries']], 'text': dict(j['text']),
            'decisions_cite_job': bool(p.get('decisions_cite_job', False)), 'reviewer_code': p.get('reviewer_code', 'warn'), 'thin_lines': p.get('thin_merge_lines', 500),
            'thin_files': p.get('thin_merge_files', 20), 'workflow_paths': list(p['workflow_paths']), 'template_dir': config['ci']['template_dir']}


def git(*args, cwd=None):
    return subprocess.run(['git', *args], capture_output=True, text=True, check=True, cwd=cwd, env=git_env()).stdout


def show(ref, path, cwd=None):
    """File text at ref, or None when it does not exist there. A policy module reads the head with `show(facts['head'], path, cwd=facts['repo'])`."""
    try:
        return git('show', f'{ref}:{path}', cwd=cwd)
    except subprocess.CalledProcessError:
        return None


def resolve(rev, cwd):
    """The commit sha `rev` names in the repository at `cwd`, or None."""
    try:
        return git('rev-parse', '--verify', '--quiet', '--end-of-options', f'{rev}^{{commit}}', cwd=cwd).strip() or None
    except subprocess.CalledProcessError:
        return None


def rows(text):
    """{id: row} of JSONL text (the jobs registry before napoleon J55)."""
    out = {}
    for line in (text or '').splitlines():
        if line.strip():
            r = json.loads(line)
            out[r['id']] = r
    return out


def rows_at(ref, cfg, cwd=None):
    """{id: row} of the jobs registry at `ref`: its per-id files (one `ls-tree` and one `cat-file --batch`), or the JSONL when the ref
    predates per-row storage. The rules compare these dicts, so they are the same for either layout."""
    try:
        names = [n for n in git('ls-tree', '-z', '--name-only', f"{ref}:{cfg['reg_jobs']}", cwd=cwd).split('\0') if n.endswith('.json')]
    except subprocess.CalledProcessError:
        return rows(show(ref, cfg['reg_jsonl'], cwd))
    if not names:
        return {}
    out = subprocess.run(['git', 'cat-file', '--batch'], input=''.join(f"{ref}:{cfg['reg_jobs']}/{n}\n" for n in names).encode(),
                         capture_output=True, check=True, cwd=cwd, env=git_env()).stdout
    got, at = {}, 0
    for _ in names:
        nl = out.index(b'\n', at)
        size = int(out[at:nl].split()[2])
        r = json.loads(out[nl + 1:nl + 1 + size].decode('utf-8'))
        got[r['id']] = r
        at = nl + 2 + size
    return got


def verdict(review_text):
    """The verdict word(s) from a `Verdict: ...` line ('merge', 'merge after fixes', 'do not merge'), lower case, or None."""
    for line in (review_text or '').splitlines():
        m = re.search(r'verdict\s*:\s*(.+)', line.replace('*', ''), re.I)
        if m:
            return m.group(1).split('.')[0].strip().lower()   # up to the first full stop: '**Verdict: merge.** Looks good' -> 'merge'
    return None


def decisions_problems(base_text, head_text, cfg, base_ref='the base branch'):
    """Errors when the head decisions file is not the base's rows plus well-formed new rows at the end."""
    path, pre = cfg['decisions'], cfg['prefix']
    drow = re.compile(rf'^\|\s*{re.escape(pre)}(\d+)\s*\|')
    rows_ = lambda t: [l.rstrip() for l in (t or '').splitlines() if drow.match(l)]
    old, new, errs = rows_(base_text), rows_(head_text), []
    if len(new) < len(old) and old[:len(new)] == new:   # behind the base tip, not an edit (W23: the judge compares the head, not a merge)
        lacks = [o.split('|')[1].strip() for o in old[len(new):]]
        errs.append(f'{path}: merge {base_ref}: the base has rows this branch lacks ({", ".join(lacks[:5])})')
    elif new[:len(old)] != old:
        changed = [o.split('|')[1].strip() for i, o in enumerate(old) if i >= len(new) or new[i] != o]
        errs.append(f'{path} is append only: rows {", ".join(changed[:5])} were changed, moved or removed '
                    f'(a reversal is a new dated row that names the one it replaces)')
    last = int(drow.match(old[-1]).group(1)) if old else 0
    for l in new[len(old):]:
        cells = [c.strip() for c in l.strip('|').split('|')]
        n = int(drow.match(l).group(1))
        if n != last + 1:
            errs.append(f'{path}: new row {pre}{n} should be {pre}{last + 1}')
        last = n
        if len(cells) != 5 or not re.fullmatch(r'\d{4}-\d\d-\d\d', cells[1]) or cells[4] not in ('yes', 'no') or not cells[2]:
            errs.append(f'{path}: row {pre}{n} is not | {pre}<n> | YYYY-MM-DD | who | decision | yes/no |')
    return errs


def decision_row(text):
    """The row dict of a decision row file's text, or None when it is not a JSON object."""
    try:
        r = json.loads(text)
    except ValueError:
        return None
    return r if isinstance(r, dict) else None


def decision_row_problems(changed, base_file, head_file, cfg):
    """The append-only rule over a decisions folder (W43): errors for a row file changed, moved or removed, and for an added file that is not a
    well-formed minted row. A file the head has as the base has it is no change, whatever the merge base held. Fails closed on what it cannot parse."""
    d, pre, errs = cfg['decisions_dir'], cfg['prefix'], []
    for p in changed:
        if not p.startswith(d + '/'):
            continue
        name, old, new = p[len(d) + 1:], base_file(p), head_file(p)
        if old == new:
            continue
        if old is not None:
            errs.append(f'{d} is append only: {name} was changed, moved or removed (a reversal is a new row whose `replaces` names the old one)')
        elif '/' in name or not name.endswith('.json'):
            errs.append(f'{p}: only <id>.json row files go in {d}')
        elif (r := decision_row(new)) is None:
            errs.append(f'{p}: not a JSON object')
        else:
            errs += [f'{p}: {e}' for e in decision_row_errors(r, name, pre, d, head_file)]
    return errs


def decision_row_errors(r, name, pre, d, head_file):
    """What is wrong with the added row `r` of file `name`."""
    errs, rid = [], r.get('id')
    if rid != file_to_id(name):
        errs.append(f'id {rid!r} is not its file name')
    elif not re.fullmatch(rf'{re.escape(pre)}\d{{6}}-[0-9a-f]{{4}}', str(rid)):
        errs.append(f'id {rid} is not a minted id: numbers are closed, so two branches never share one (wsc reg add <registry> --mint ...)')
    if not re.fullmatch(r'\d{4}-\d\d-\d\d', str(r.get('date'))):
        errs.append('date is not YYYY-MM-DD')
    errs += [f'{k} is empty' for k in ('who', 'decision') if not str(r.get(k) or '').strip()]
    if r.get('reversible') not in ('yes', 'no'):
        errs.append('reversible is not yes or no')
    gone = [x for x in r.get('replaces') or [] if head_file(f'{d}/{x}.json') is None]
    if gone:
        errs.append(f'replaces {", ".join(map(str, gone))}, not a row')
    return errs


def retired_file_problems(changed, base_file, head_file, cfg, base_ref='the base branch'):
    """The frozen Markdown file (W43): an error when the head changes `decisions_retired` and its table lines differ from the base's. The `registries`
    gate reads the head's wsc.toml, so a head cut before the key passes it; this rule is the base's. Prose may change and the file may go."""
    path = cfg.get('decisions_retired')
    if not path or path not in changed or (new := head_file(path)) is None:
        return []
    table = lambda t: [l.strip() for l in (t or '').splitlines() if l.lstrip().startswith('|')]
    if table(new) == table(base_file(path)):
        return []
    return [f'{path} is frozen: its table differs from {base_ref}\'s. A new decision is a row file (wsc reg add {cfg["decisions_dir"].rsplit("/", 1)[-1]} --mint); '
            f'a branch behind {base_ref} merges it and takes the file as it is there']


def added_decision_files(changed, base_file, head_file, cfg):
    """[{id, text}] of the row files the head adds: `added_decision_rows` for a decisions folder, `text` the row as its table line."""
    d, out = cfg['decisions_dir'], []
    for p in changed:
        if p.startswith(d + '/') and base_file(p) is None and (r := decision_row(head_file(p) or '')):
            out.append({'id': str(r.get('id')), 'text': '| ' + ' | '.join(str(r.get(k, '')) for k in ('id', 'date', 'who', 'decision', 'reversible')) + ' |'})
    return out


def allowed(path, globs):
    return matches(path, globs)


def check(branch, changed, base_rows, head_rows, base_file, head_file, sessions=None, cfg=None, hook=None, base_ref=None, reads=None, warnings=None):
    """Errors for this pull request. `base_file`/`head_file` are callables path -> text or None. `sessions`: callable path ->
    list with one set of trailer values per branch commit that touched it (job branches; an empty set is a commit without a trailer, which
    is refused; None skips the authorship check, for the pure-logic tests). `cfg`: settings(). `hook`: callable(facts) -> [str], the
    repo's `policy`-stage gate modules (facts: branch, kind, jid, changed, added_decision_rows), called after the decisions check. `base_ref`:
    the base's name for messages. `reads`: the git reads of rules A-E (a GitReads, or a fake with its methods; None skips them, for the
    pure-logic tests). `warnings`: a list the warnings are appended to (they never refuse)."""
    cfg = cfg or settings(_default_config())
    T, jd, trailer = cfg['text'], cfg['jobs_dir'], cfg['trailer']
    if cfg.get('decisions_dir'):
        errs = decision_row_problems(changed, base_file, head_file, cfg) + retired_file_problems(changed, base_file, head_file, cfg, base_ref or 'the base branch')
    else:
        errs = (decisions_problems(base_file(cfg['decisions']), head_file(cfg['decisions']), cfg, base_ref or 'the base branch')
                if cfg['decisions'] and cfg['decisions'] in changed else [])
    m = re.fullmatch(rf"(job|brief)/({re.escape(cfg['job_prefix'])}[1-9][0-9]*)", branch)
    kind = m.group(1) if m else branch.split('/', 1)[0] if '/' in branch else ''
    warns = warnings if warnings is not None else []
    if cfg.get('decisions_dir'):
        added = added_decision_files(changed, base_file, head_file, cfg)
    else:
        added = added_decision_rows(base_file(cfg['decisions']), head_file(cfg['decisions']), cfg) if cfg['decisions'] in changed else []
    if cfg.get('decisions_cite_job') and kind == 'job':   # rule F
        errs += [f"decision row {r['id']} on {branch} must name the brief that required it (add `{m.group(2)}` to the row, or move it to a plan/ branch)"
                 for r in added if not re.search(rf'(?<![A-Za-z0-9]){re.escape(m.group(2))}(?![0-9])', r['text'])]
    if hook:
        errs += hook({'branch': branch, 'kind': kind, 'jid': m.group(2) if m else None, 'changed': changed, 'added_decision_rows': added})
    if branch in cfg.get('bootstrap', ()):   # [policy] bootstrap: the pull request that introduces the pipeline (see repo.py DEFAULTS)
        return errs
    other_rows_changed = lambda jid: sorted(k for k in set(base_rows) | set(head_rows)
                                             if k != jid and base_rows.get(k) != head_rows.get(k))
    review_ref = f" ({T['review_doc']})" if T.get('review_doc') else ''
    if m and m.group(1) == 'job':
        jid = m.group(2)
        if base_file(f'{jd}/{jid}/brief.md') is None:
            errs.append(f'{jid} has no brief on the base branch: briefs are merged before the job starts (brief/{jid})')
        if head_file(f'{jd}/{jid}/report.md') is None:
            errs.append(f'{jd}/{jid}/report.md is missing: every job ends with a report')
        v = verdict(head_file(f'{jd}/{jid}/review.md'))
        if v is None:
            errs.append(f'{jd}/{jid}/review.md is missing or has no "Verdict:" line: every job is reviewed before merge{review_ref}')
        elif v != 'merge':
            errs.append(f'review verdict is "{v}", not "merge": finish the fixes and get a merge verdict first')
        row = head_rows.get(jid)
        if not row or row.get('status') != 'done':
            errs.append(f'row {jid} must be `done` on the branch (the reviewer sets it with a merge verdict)')
        if other_rows_changed(jid):
            errs.append(f'a job branch may change only its own row; it also changes {", ".join(other_rows_changed(jid))}')
        sf = cfg.get('semver_from') or 0
        if sf and 'VERSION' in changed and int(jid[len(cfg['job_prefix']):]) >= sf:
            errs.append(f'{jid} changes VERSION: the release workflow owns VERSION (C27); from {cfg["job_prefix"]}{sf} on a job states its '
                        f'level as `semver` on its row and leaves VERSION alone (git checkout origin/main -- VERSION)')
        warns += workflow_warnings(jid, changed, base_file, cfg)
        if sessions and trailer:
            # fail closed: a commit with no trailer could be anyone's, so it can prove nothing about who reviewed
            by = {n: sessions(f'{jd}/{jid}/{n}') for n in ('report.md', 'review.md')}
            for n, commits in by.items():
                bare = sum(1 for s in commits if not s)
                if bare:
                    errs.append(f'{jd}/{jid}/{n} has {bare} commit(s) with no `{trailer}:` trailer: authorship cannot be checked'
                                + (f" ({T['trailer_hint']})" if T.get('trailer_hint') else ''))
            both = sorted(set().union(*by['report.md']) & set().union(*by['review.md']))
            if both:
                errs.append(f'the review was written by a session that also wrote the report ({", ".join(both)}): '
                            f'a job is never reviewed by the chat that built it' + (f" ({T['rules_ref']})" if T.get('rules_ref') else ''))
            if reads is not None:   # rules A and B: who wrote each round, and what else its commits changed
                e, w = round_problems(jid, cfg, reads, set().union(*by['report.md']), head_file(f'{jd}/{jid}/review.md'))
                errs += e
                warns += w
        if reads is not None:
            rev = f'{jd}/{jid}/review.md'
            errs += append_only_problems(rev, base_file(rev), reads.history(rev), head_file(rev), base_ref or 'the base branch')   # rule C
            e, w = evidence_problems(jid, cfg, reads, [(p, head_file(p) or '') for p in (f'{jd}/{jid}/report.md', rev)], base_rows, base_file,
                                     base_ref or 'the base branch')   # rule D
            errs += e
            warns += w
            if v == 'merge':
                warns += thin_merge_warning(jid, cfg, reads, head_file(rev))   # rule E
    elif m and m.group(1) == 'brief':
        jid = m.group(2)
        ok = {f'{jd}/{jid}/brief.md', f"{cfg['reg_jobs']}/{jid}.json"}
        extra = [p for p in changed if p not in ok]
        if extra:
            hint = ' (a committed registry view: C19, set `[views] commit = false`)'
            shown = [p + hint if p in cfg.get('views', ()) else p for p in extra]
            errs.append(f'a brief branch may only add {jd}/{jid}/brief.md and update its row; it also changes: {", ".join(shown)}')
        row = head_rows.get(jid)
        if not row or row.get('status') != 'queued' or row.get('brief') != f'{jd}/{jid}/brief.md':
            errs.append(f'row {jid} must be `queued` with brief={jd}/{jid}/brief.md')
        if other_rows_changed(jid):
            errs.append(f'a brief branch may change only its own row; it also changes {", ".join(other_rows_changed(jid))}')
    elif branch.startswith('release/'):
        errs += release_problems(branch, changed, base_file, head_file)
    elif branch.startswith('plan/'):
        extra = [p for p in changed if not allowed(p, cfg['plan'])]
        if extra:
            errs.append(f"a plan/ branch may only touch {T.get('plan_summary') or ', '.join(cfg['plan'])}; it also changes: "
                        f'{", ".join(extra)} (code goes through a job)')
    elif branch.startswith('meta/'):
        extra = [p for p in changed if not allowed(p, cfg['meta'])]
        if extra:
            errs.append(f'a meta/ branch may only touch repo infrastructure; it also changes: {", ".join(extra)} (game code goes through a job)')
    else:
        errs.append(f'branch "{branch}" is not job/{cfg["job_prefix"]}<n>, brief/{cfg["job_prefix"]}<n>, plan/*, meta/* or release/vX.Y.Z: all work goes through the job queue'
                    + (f" ({T['rules_ref']})" if T.get('rules_ref') else '') + '. Rename the branch, or add the work as a job first.')
    return errs


def workflow_warnings(jid, changed, base_file, cfg):
    """One warning per workflow input job `jid` changes and its brief on the base does not name (W36; the module docstring). A deletion and both
    halves of a rename are changed paths (`diff_base` uses --no-renames). A template's rendered file is required even when it is not yet changed."""
    globs, tdir, wf = cfg.get('workflow_paths') or [], cfg.get('template_dir') or 'ci', '.github/workflows/'
    template = lambda p: p.startswith(f'{tdir}/') and p.endswith('.in') and '/' not in p[len(tdir) + 1:]
    rendered = lambda p: f'{wf}{p[len(tdir) + 1:-3]}'
    hits = [p for p in changed if matches(p, globs)]
    need = sorted({*hits, *(r for r in map(rendered, filter(template, hits)) if matches(r, globs))})
    brief = base_file(f"{cfg['jobs_dir']}/{jid}/brief.md") or ''
    out = []
    for p in need:
        if p in brief:
            continue
        pair = (rendered(p), p) if template(p) else (p, f'{tdir}/{p[len(wf):]}.in') if p.startswith(wf) else None
        both = pair and (pair[1] in changed or base_file(pair[1]) is not None)
        out.append(f"`{p}` is a workflow input and {jid}'s brief on the base does not name it: a job cannot quietly add a check that posts a fake "
                   '`policy` status (W36); name the file in the brief (briefs are merged before the job starts) or use a `meta/` branch'
                   + (f' (`{pair[0]}` renders from `{pair[1]}`: name both)' if both else ''))
    return out


def release_problems(branch, changed, base_file, head_file):
    """A release/vX.Y.Z branch (W29, C27): VERSION only, its content X.Y.Z, one patch, minor or major step above the base's VERSION."""
    m = re.fullmatch(r'release/v(\d+)\.(\d+)\.(\d+)', branch)
    if not m:
        return [f'branch "{branch}" is not release/vX.Y.Z (lower-case v, three numbers): rename it']
    want = '.'.join(m.groups())
    errs = []
    extra = [p for p in changed if p != 'VERSION']
    if extra or not changed:
        errs.append(f'a release branch may change only VERSION; it changes {", ".join(extra) or "nothing"}')
    head = (head_file('VERSION') or '').strip()
    if head != want:
        errs.append(f'VERSION on the branch is {head!r}, not {want} (the branch name)')
    base = (base_file('VERSION') or '').strip()
    bm = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', base)
    if not bm:
        errs.append(f"the base's VERSION {base!r} is not X.Y.Z")
    else:
        a, b, c = map(int, bm.groups())
        ok = {f'{a}.{b}.{c + 1}', f'{a}.{b + 1}.0', f'{a + 1}.0.0'}
        if want not in ok:
            errs.append(f"{want} is not one patch, minor or major step above the base's VERSION {base} (one of {', '.join(sorted(ok))}): "
                        'merge the base and let the release workflow open the branch')
    return errs


# ---------------------------------------------------------------- review integrity (core W27, C30): rules A-F; the git reads come in as `reads`
RUN_PATH = re.compile(r'(?<![\w./\\:<>~$%@-])(?:[\w.-]+/)*runs/[\w.-]*\w')   # a repo-relative run folder; never part of a URL or an absolute path
BRANCH_CITE = re.compile(r'(?<![\w./-])(?:origin/)?((job|brief)/([A-Z]+[1-9]\d*))\b')
ORIGIN_CITE = re.compile(r'(?<![\w./-])origin/([\w.-]+(?:/[\w.-]+)*\w)')
SHA_WORD = re.compile(r'\b(?:commits?|shas?)\b:?\s+((?:`[0-9a-f]{7,40}`(?:\s*,\s*(?:and\s+)?|\s+and\s+|\s*/\s*)?)+)', re.I)
SHA_AT = re.compile(r'@`?([0-9a-f]{7,40})\b')
EVIDENCE = re.compile(r'\b20\d{6}_\w+|/actions/runs/\d+|\brun \d{6,}\b|\btest_\w+|\btests/[\w/.-]+')


def rounds_of(text):
    """{round number: its section, heading line through its last line} of a review.md (jobq.review_rounds; the first section wins a repeat)."""
    from .jobq import review_rounds   # here: jobq imports this module
    out = {}
    for head, body in review_rounds(text or '')[1]:
        m = re.match(r'## Round (\d+)', head)
        if m:
            out.setdefault(int(m.group(1)), head + body)
    return out


def append_only_problems(path, base_text, history, head_text, base_ref):
    """Rule C: each earlier round stays byte-identical, at the head against the base and commit by commit (`history`: [(sha, sessions, text)]
    oldest first), so a rewrite followed by a restore is refused. Before a newer round exists, only the session that wrote a round edits it."""
    errs = []
    head_r = rounds_of(head_text)
    for n, sec in sorted(rounds_of(base_text).items()):
        if head_r.get(n) != sec:
            errs.append(f'{path}: round {n} differs from the base ({base_ref}): review rounds are append only (a new round goes on top)')
    prev, authors = {}, {}
    for sha, who, text in history:
        cur = rounds_of(text)
        newest = max(max(cur, default=0), max(prev, default=0))
        for n, sec in sorted(prev.items()):
            if cur.get(n) == sec:
                continue
            if n < newest:
                errs.append(f'{path}: round {n} was changed by commit {sha[:12]} after round {newest} existed: review rounds are append only '
                            '(a new round goes on top; an earlier round is never edited)')
            elif who and not who & authors.get(n, set()):
                errs.append(f'{path}: round {n} was edited by commit {sha[:12]} of a session that did not write it ({", ".join(sorted(who))}): '
                            'only its own author edits the newest round')
        for n in cur:
            if n not in prev:
                authors.setdefault(n, set(who))
        prev = cur
    return errs


def round_problems(jid, cfg, reads, builder, head_review):
    """(errors, warnings): rule B's errors, and rule A's lines in the list `[policy] reviewer_code` names (warn by default: the W27 scan of the
    merged job branches found reviewer code under `merge` on 5 core and 27 napoleon branches, past the brief's kill criterion of 3 beyond the
    audit's; W40 added the key), over the commits of the branch (`reads.commits()`, `reads.history(review.md)`). A review commit belongs to the newest
    round its review.md holds; any other commit by a round's session belongs to that round; a commit by nobody known (no trailer, or a
    session that is neither the builder's nor a round's) after the first review commit belongs to the round of the next review commit, or to
    the newest round when none follows. Commits before the first review commit and the builder's own (report.md writers: the builder and
    every fix session) are never a round's. A commit that the first commit of a newer round descends from has been reviewed by that round, so rule A skips it: ancestry, not the
    log's order (`reads.is_ancestor`; a merge lists a side branch's commits in either order), and a round's later edits of itself clear nothing."""
    jd, T = cfg['jobs_dir'], cfg['text']
    rev = f'{jd}/{jid}/review.md'
    hist = reads.history(rev)
    wrote = {sha: max(rounds_of(text), default=0) for sha, _, text in hist}
    by_round, opened = {}, {}
    for sha, who, _ in hist:
        if wrote[sha]:
            by_round.setdefault(wrote[sha], set()).update(who)
            opened.setdefault(wrote[sha], sha)
    errs, doc = [], f" ({T['review_doc']})" if T.get('review_doc') else ''
    for n in sorted(by_round):   # rule B; the builder's sessions are the own-review rule's message
        for j in sorted(k for k in by_round if k < n):
            both = sorted((by_round[n] & by_round[j]) - builder)
            if both:
                errs.append(f'round {n} was written by a session that wrote round {j} ({", ".join(both)}): a fresh session per round{doc}')
    warns = []
    if not by_round:
        return errs, warns
    commits = reads.commits()
    first = next((i for i, c in enumerate(commits) if wrote.get(c[0])), len(commits))
    ok = lambda p: p.startswith(f'{jd}/{jid}/') or p == f"{cfg['reg_jobs']}/{jid}.json"
    hits = {}
    for i, (sha, who, paths) in enumerate(commits):
        code = [p for p in paths if not ok(p)]
        if not code or who & builder:
            continue
        n = wrote.get(sha) or next((k for k in sorted(by_round) if who & by_round[k]), None)
        if n is None:
            if i < first:
                continue
            n = next((wrote[c[0]] for c in commits[i + 1:] if wrote.get(c[0])), max(by_round))
        if not any(k > n and reads.is_ancestor(sha, first_sha) for k, first_sha in opened.items()):   # W40: else a fresh round (rule B) reviewed it
            hits.setdefault(n, []).append((sha, code))
    head_r = rounds_of(head_review)
    rule_a = errs if cfg.get('reviewer_code') == 'error' else warns
    for n, got in sorted(hits.items()):   # rule A
        if verdict(head_r.get(n)) == 'merge':
            shown = '; '.join(f"{s[:12]} ({', '.join(c[:6])}{' and more' if len(c) > 6 else ''})" for s, c in got[:6])
            rule_a.append(f'round {n} of {rev} says merge, but its own commits change files outside {jd}/{jid}/ and its row: {shown}: '
                         'write the verdict `merge after fixes`; a fresh round reviews your change')
    return errs, warns


def evidence_problems(jid, cfg, reads, texts, base_rows, base_file, base_ref):
    """Rule D: (errors, warnings) for the evidence `texts` ([(path, text)]: report.md and review.md at the head) cite. Errors only for what this
    clone proves; warnings for what it cannot."""
    jd, errs, warns, seen = cfg['jobs_dir'], [], [], set()
    skip = {f'job/{jid}', 'origin/HEAD', 'origin/main', base_ref, base_ref.removeprefix('origin/')}

    def branch(path, ref, name, kind=None, bid=None):
        if (path, ref) in seen or ref in skip or name in skip:
            return
        seen.add((path, ref))
        if kind == 'job' and (base_rows.get(bid) or {}).get('status') == 'done':
            return   # squash-merged: the row is done on the base
        if kind == 'brief' and base_file(f'{jd}/{bid}/brief.md') is not None:
            return
        st = reads.ref_state(name)
        if st == 'missing':
            warns.append(f"{path} cites {ref}, which is not in this clone (another repository's?): evidence must sit on a main branch or a pushed tag")
        elif st != 'merged':   # a warning: the W27 scan found 13 merged branches that name an open branch in passing
            warns.append(f'{path} cites {ref}: evidence on an unmerged branch cannot be opened from main: merge it, tag it, or copy it into the repo')

    for path, text in texts:
        for m in RUN_PATH.finditer(text):
            p = m.group(0)
            if (path, p) not in seen:
                seen.add((path, p))
                if not reads.exists(p):
                    errs.append(f'{path} cites {p}, which exists in neither the head nor {base_ref}: commit the run folder or cite one that is on {base_ref}')
        for m in BRANCH_CITE.finditer(text):
            branch(path, m.group(1), m.group(1), m.group(2), m.group(3))
        for m in ORIGIN_CITE.finditer(text):
            if not re.match(r'(job|brief)/', m.group(1)):
                branch(path, m.group(0), m.group(0))
        shas = [s for m in SHA_WORD.finditer(text) for s in re.findall(r'`([0-9a-fA-F]{7,40})`', m.group(1))] + SHA_AT.findall(text)
        for s in dict.fromkeys(shas):
            if (path, s) in seen:
                continue
            seen.add((path, s))
            st = reads.sha_state(s)
            if st == 'missing':
                warns.append(f'{path} cites commit {s}, which this clone does not have: a commit that is not pushed cannot be opened')
            elif st != 'ok':
                warns.append(f'{path} cites commit {s}, which is not reachable from {base_ref} or the head and is no tag: '
                             'a commit that is not pushed cannot be opened')
    return errs, warns


def thin_merge_warning(jid, cfg, reads, head_review):
    """Rule E: a `merge` on a diff over the `[policy] thin_merge_lines` or `thin_merge_files` outside the jobs folder and the registries, whose
    newest round cites no run id, runs/ path, CI run or test name."""
    jd, reg = cfg['jobs_dir'], cfg['reg_jobs'].rsplit('/', 1)[0]
    stat = [(n, p) for n, p in reads.numstat() if not p.startswith((f'{jd}/', f'{reg}/'))]
    lines, nfiles = sum(n for n, _ in stat), len(stat)
    if lines <= cfg.get('thin_lines', 500) and nfiles <= cfg.get('thin_files', 20):
        return []
    rounds = rounds_of(head_review)
    newest = rounds.get(max(rounds, default=0), head_review or '')
    if EVIDENCE.search(newest) or RUN_PATH.search(newest):
        return []
    return [f'merge verdict on a large diff cites no evidence (J62, J57): {lines} changed lines in {nfiles} files outside {jd}/ and {reg}/; '
            'the newest round names no run id, runs/ path, CI run or test']


def added_decision_rows(base_text, head_text, cfg):
    """[{id, text}] of the decisions rows the head has and the base does not (the `added_decision_rows` policy fact)."""
    drow = re.compile(rf"^\|\s*({re.escape(cfg['prefix'])}\d+)\s*\|")
    old = {l.rstrip() for l in (base_text or '').splitlines() if drow.match(l)}
    return [{'id': drow.match(l).group(1), 'text': l.rstrip()} for l in (head_text or '').splitlines() if drow.match(l) and l.rstrip() not in old]


class GitReads:
    """What rules A-E read, from the clone at `repo` by sha (b base, h head, mb merge base); check() takes any object with these methods."""

    def __init__(self, repo, b, h, mb, trailer):
        self.repo, self.b, self.h, self.mb, self.fmt = repo, b, h, mb, f'%(trailers:key={trailer},valueonly,separator=%x1f)'

    def _ok(self, *args):
        return subprocess.run(['git', *args], capture_output=True, cwd=self.repo, env=git_env()).returncode == 0

    @staticmethod
    def _who(fields):
        return {v.strip() for v in fields if v.strip()}

    def commits(self):
        """[(sha, sessions, paths)] of mb..h, oldest first; a merge lists no paths."""
        out = git('-c', 'core.quotePath=false', 'log', '--reverse', '--topo-order', '--no-renames', '--name-only', f'--format=%x1e%H%x1f{self.fmt}',
                  f'{self.mb}..{self.h}', cwd=self.repo)
        recs = []
        for r in out.split('\x1e')[1:]:
            first, *paths = r.split('\n')
            sha, *who = first.split('\x1f')
            recs.append((sha, self._who(who), [p for p in paths if p.strip()]))
        return recs

    def is_ancestor(self, sha, of):
        """True when `sha` is `of` or in its history; a git error is False, so rule A keeps the hit."""
        return self._ok('merge-base', '--is-ancestor', sha, of)

    def history(self, path):
        """[(sha, sessions, text or None)] of the commits of mb..h that touch `path`, oldest first."""
        out = git('log', '--reverse', '--topo-order', '--full-history', f'--format=%H%x1f{self.fmt}%x1e', f'{self.mb}..{self.h}', '--', path, cwd=self.repo)
        recs = [r.strip('\n').split('\x1f') for r in out.split('\x1e') if r.strip()]
        if not recs:
            return []
        blob = subprocess.run(['git', 'cat-file', '--batch'], input=''.join(f'{r[0]}:{path}\n' for r in recs).encode(), capture_output=True,
                              check=True, cwd=self.repo, env=git_env()).stdout
        got, at = [], 0
        for r in recs:
            nl = blob.index(b'\n', at)
            head = blob[at:nl].split()
            if len(head) == 3 and head[1] == b'blob':
                size = int(head[2])
                got.append((r[0], self._who(r[1:]), blob[nl + 1:nl + 1 + size].decode('utf-8', 'replace')))
                at = nl + 2 + size
            else:
                got.append((r[0], self._who(r[1:]), None))
                at = nl + 1
        return got

    def numstat(self):
        """[(changed lines, path)] of mb...h (a binary file counts 0 lines)."""
        out = git('diff', '--numstat', '--no-renames', '-z', f'{self.mb}...{self.h}', cwd=self.repo)
        rows = []
        for rec in out.split('\0'):
            parts = rec.split('\t')
            if len(parts) == 3:
                rows.append(((int(parts[0]) if parts[0].isdigit() else 0) + (int(parts[1]) if parts[1].isdigit() else 0), parts[2]))
        return rows

    def exists(self, path):
        return any(self._ok('cat-file', '-e', f'{rev}:{path}') for rev in (self.h, self.b))

    def _merged(self, sha):
        return self._ok('merge-base', '--is-ancestor', sha, self.b) or bool(git('tag', '--points-at', sha, cwd=self.repo).strip())

    def ref_state(self, name):
        """'merged' (an ancestor of the base, or a tag points at it), 'unmerged', or 'missing' (this clone has no such ref)."""
        cands = [f'refs/remotes/{name}'] if name.startswith('origin/') else [f'refs/remotes/origin/{name}', f'refs/heads/{name}']
        sha = next((s for s in (resolve(c, self.repo) for c in cands) if s), None)
        return 'missing' if not sha else 'merged' if self._merged(sha) else 'unmerged'

    def sha_state(self, s):
        """'ok' (reachable from the base or the head, or a tag's target), 'unreachable', or 'missing'."""
        sha = resolve(s, self.repo)
        if not sha:
            return 'missing'
        return 'ok' if self._merged(sha) or self._ok('merge-base', '--is-ancestor', sha, self.h) else 'unreachable'


def _default_config():
    return DEFAULTS


def diff_base(base, head, repo, base_ref=None, head_ref=None):
    """(base sha, head sha, merge base, changed paths) at `repo`. Renames count as a delete and an add, and the output does not depend on
    git config (diff.renames, core.quotePath), so the same two shas give the same paths anywhere. Raises Refusal."""
    b, h = resolve(base, repo), resolve(head, repo)
    if not b:
        raise Refusal(f'--base {base_ref or base} does not resolve to a commit: `git fetch` first (a stale or missing base judges with the wrong rules)')
    if not h:
        raise Refusal(f'--head {head_ref or head} does not resolve to a commit: fetch the pull request head (`git fetch origin <branch>`)')
    try:
        mb = git('merge-base', b, h, cwd=repo).strip()
    except subprocess.CalledProcessError:
        raise Refusal(f'{base_ref or base} and {head_ref or head} have no merge base: the branch must be cut from the base (`git fetch` a full history)') from None
    changed = [p for p in git('diff', '--name-only', '--no-renames', '-z', f'{mb}...{h}', cwd=repo).split('\0') if p]
    return b, h, mb, changed


def run_check(ctx, branch, base, head, repo, extra_facts=None, base_ref=None, warnings=None):
    """The errors and the changed files of `branch` (the commit `head`) against `base`, read with git at `repo` (the clone; refs resolve there
    to shas). `ctx` holds the rules: the base tree in the `--judge` child, this checkout in the pre-W23 fallback. Its config and its gate
    modules judge; `ctx.root` is never a git cwd. `extra_facts`: more facts for the `policy`-stage gate modules (`ctx.facts`). `warnings`: a list
    that gets the warnings (rules D and E)."""
    cfg = settings(ctx.config)
    repo = str(Path(repo).resolve())
    b, h, mb, changed = diff_base(base, head, repo, base_ref)
    base_ref = base_ref or base
    facts = {'root': ctx.root, 'branch': branch, 'base': b, 'head': h, 'merge_base': mb, 'changed': changed, 'base_ref': base_ref, 'repo': repo}
    trailer = cfg['trailer']

    def sessions(path):
        out = git('log', f'--format=%H%x1f%(trailers:key={trailer},valueonly,separator=%x1f)%x1e', f'{mb}..{h}', '--', path, cwd=repo)
        recs = [r.strip('\n').split('\x1f') for r in out.split('\x1e') if r.strip()]
        return [{v.strip() for v in r[1:] if v.strip()} for r in recs]

    gatemods.load(ctx)   # a load error stops the check before any git read below

    def hook(f):
        return gatemods.problems(gatemods.run_stage(ctx, 'policy', facts={**facts, **f, **(extra_facts or {})}))

    errs = check(branch, changed, rows_at(mb, cfg, repo), rows_at(h, cfg, repo), lambda p: show(b, p, repo), lambda p: show(h, p, repo),
                 sessions, cfg, hook, base_ref, GitReads(repo, b, h, mb, trailer) if trailer else None, warnings)
    return errs, changed


def rule_input_note(config, changed, base_ref):
    """The note for a branch that changes what judges pull requests (decided by the base's config), or ''."""
    ci, core = config['ci'], config['ci']['core']
    pats = ['wsc.toml', '.github/workflows/policy.yml', f"{ci['template_dir']}/policy.yml.in", *([core] if core else ['wsc.py', 'warscape/**']),
            *(f'{d}/**' for d in config['gates']['dirs']), *([config['jobs']['legacy']] if config['jobs']['legacy'] else [])]
    hit = [p for p in changed if matches(p, pats)]
    if not hit:
        return ''
    shown = ', '.join(hit[:8]) + (f' and {len(hit) - 8} more' if len(hit) > 8 else '')
    return f"policy: note: this branch changes {shown}: they judge pull requests after this one merges; this one was judged with {base_ref}'s"


# What marks a rule's line, first match wins: E before D, its line says "cites" too. A line of no rule (the branch kind, the row) is not counted.
SCAN_MARKS = (('A', 'says merge, but its own commits change files'), ('B', 'a fresh session per round'), ('C', 'review rounds are append only'),
              ('C', 'only its own author edits'), ('E', 'merge verdict on a large diff'), ('D', ' cites '), ('F', 'must name the brief that required it'))
SCAN_RULES = 'ABCDEF'


def scan_rule(line):
    """The rule letter of a policy line, or None."""
    return next((r for r, mark in SCAN_MARKS if mark in line), None)


def scan_config(text):
    """A config for `scan` from a repo's wsc.toml text: the defaults plus the keys the rules read, gate modules off and rule F on. Not load_config:
    a repo pinned to an older core has keys this core refuses, and the scan judges its history, not its setup."""
    raw, cfg = tomllib.loads(text), copy.deepcopy(DEFAULTS)
    jobs = raw.get('jobs', {})
    cfg['jobs'].update({k: jobs[k] for k in ('id_prefix', 'dir', 'semver_from') if k in jobs})
    cfg['jobs']['text'].update(jobs.get('text', {}))
    cfg['policy'].update({k: v for k, v in raw.get('policy', {}).items() if k in cfg['policy']})
    cfg['policy']['decisions_cite_job'] = True
    cfg['registries_dir'] = raw.get('registries_dir', cfg['registries_dir'])
    cfg['registries'] = raw.get('registries', {})
    cfg['gates']['dirs'] = []
    return cfg


def merged_prs(repo, run=subprocess.run):
    """The merged pull requests of job/ branches, from `gh` run in the clone. Raises Refusal."""
    try:
        p = run(['gh', 'pr', 'list', '--state', 'merged', '--search', 'head:job/', '--limit', '1000', '--json', 'number,headRefName,headRefOid,mergeCommit,mergedAt'],
                cwd=repo, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refusal(f'gh could not list the merged pull requests: {e}') from None
    if p.returncode:
        raise Refusal(f'gh could not list the merged pull requests: {p.stderr.strip()}')
    return json.loads(p.stdout)


def scan_targets(prs, after=None):
    """The merged job/ pull requests to judge, oldest first; with `after` (a set of commit shas), those whose merge commit is in it."""
    got = [p for p in prs if p['headRefName'].startswith('job/') and p.get('mergeCommit')]
    return sorted((p for p in got if after is None or p['mergeCommit']['oid'] in after), key=lambda p: p['mergedAt'])


def scan_label(p):
    return f"{p['headRefName']} (#{p['number']}, {p['mergedAt'][:10]})"


def scan_tally(results, only=None):
    """(one line per branch a rule hit, {rule: branches}) of `results` ([(pull request, policy lines)]); `only`: that rule alone."""
    rules = only or SCAN_RULES
    counts, lines = dict.fromkeys(rules, 0), []
    for p, got in results:
        by = {}
        for x in got:
            r = scan_rule(x)
            if r in counts:
                by.setdefault(r, []).append(x)
        for r in by:
            counts[r] += 1
        if by:
            lines.append(f'{scan_label(p)}: ' + ' | '.join(f"{r}: {v[0]}{f' (and {len(v) - 1} more)' if len(v) > 1 else ''}" for r, v in sorted(by.items())))
    return lines, counts


def scan_shas(p, repo):
    """(base, head) of a merged pull request: its merge commit's first parent and its head, fetching a head whose branch was deleted (objects only:
    no ref and no FETCH_HEAD change in the clone); None when either cannot be read."""
    head, sha = None, p['headRefOid']
    for fetch in (False, True):
        if fetch:
            subprocess.run(['git', 'fetch', '--quiet', '--no-write-fetch-head', 'origin', f"refs/pull/{p['number']}/head"], cwd=repo, env=git_env(), capture_output=True)
        head = resolve(sha, repo)
        if head:
            break
    base = resolve(f"{p['mergeCommit']['oid']}^1", repo)
    return (base, head) if base and head else None


def scan(root, base='origin/main', since=None, rule=None, run=subprocess.run, out=print):
    """`wsc policy --scan`: print one line per merged job/ branch a rule refuses or warns about, then the branches per rule. Reads `root`'s clone; its
    rules are this checkout's and its configuration `base`'s wsc.toml. Exit 1 when it could not run or a branch was not judged: a count that left
    a branch out is not the number a decision needs."""
    repo = str(Path(root).resolve())
    try:
        text = show(base, 'wsc.toml', repo)
        if text is None:
            raise Refusal(f'{base} has no wsc.toml in {repo}: `git fetch` first')
        after = None
        if since:
            s = resolve(since, repo)
            if not s:
                raise Refusal(f'--since {since} does not resolve in {repo}: `git fetch` first')
            after = set(git('rev-list', f'{s}..{base}', cwd=repo).split())
        ctx, targets = Ctx(root=Path(repo), config=scan_config(text)), scan_targets(merged_prs(repo, run), after)
    except (Refusal, ValueError) as e:   # ValueError: gh's JSON or the TOML
        out(f'policy: scan: {e}')
        return 1
    results, lost = [], 0
    for p in targets:
        shas = scan_shas(p, repo)
        try:
            if not shas:
                raise Refusal('its head or merge commit is not in this clone and could not be fetched')
            warns = []
            errs, _ = run_check(ctx, p['headRefName'], shas[0], shas[1], repo, base_ref=base, warnings=warns)
            results.append((p, errs + warns))
        except (Refusal, subprocess.CalledProcessError, ValueError, KeyError) as e:
            lost += 1
            out(f'policy: scan: {scan_label(p)}: not judged: {e}')
    lines, counts = scan_tally(results, rule)
    for x in lines:
        out(f'policy: scan: {x}')
    out(f"policy: scan: {len(results)} branches judged, {lost} not judged; {', '.join(f'{r} {n}' for r, n in counts.items())} (branches per rule)")
    return 1 if lost else 0
