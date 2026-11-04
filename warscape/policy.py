"""Pull-request policy as library code (verb: warscape/verbs/policy.py): every change reaches `main` through the job queue.

Moved from napoleon-remastered `tools/pr_policy.py` (napoleon J62). The branch name decides what a pull request may change:

  job/<id>    any files, but only row <id> of the jobs registry; <jobs dir>/<id>/brief.md must already be on the base; the branch must
              carry <id>/report.md and <id>/review.md whose verdict line says exactly "merge"; row <id> must be `done`; no session (the
              `[policy] session_trailer` commit trailer) that wrote the report may write the review (never review your own job), and
              every commit touching the report or the review must carry that trailer (fails closed).
  brief/<id>  only <jobs dir>/<id>/brief.md and row <id> of the jobs registry (which must be `queued` with its brief).
  plan/*      planning: the `[policy] plan` globs. No code.
  meta/*      repo infrastructure: the `[policy] meta` globs.
Anything else is refused. Globs match by path segment (`*` and `?` inside one segment, `**` across folders: repo.matches). Every branch
kind: the `[policy] decisions` file is append only (existing rows unchanged and in order; new rows numbered <prefix><last+1>, with a
YYYY-MM-DD date and Reversible yes or no); a reversal is a new row that names the one it replaces. A repo's own rules (napoleon's rule 79,
the acceptance ledger) come from its `policy`-stage gate modules (warscape/gatemods.py), run after the decisions check: an `error`
Result's details are policy errors.

A pull request is judged with its base's rules (core W23, C24). The verb's parent (warscape/policy_base.py `judge`) writes the base's rule
inputs into a fresh temporary folder outside every repository and runs the base's code there in a child process (`wsc policy --judge`,
which calls `run_check` here):
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
"""
import json
import re
import subprocess
from pathlib import Path

from . import gatemods
from .repo import DEFAULTS, git_env, matches

# The judge's interface (the `--judge` child's arguments), read from a base core's text by warscape/policy_base.py: keep it on a line of its own.
JUDGE_API = 1


class Refusal(Exception):
    """The base's rules cannot be run: a refusal (exit 1) whose message names the fix."""


def settings(config):
    """The policy settings from a loaded wsc.toml: `[policy]` plus the pieces of `[jobs]` and `registries_dir` the rules need."""
    p, j = config['policy'], config['jobs']
    return {'decisions': p['decisions'], 'prefix': p['decision_prefix'], 'trailer': p['session_trailer'], 'plan': list(p['plan']),
            'meta': list(p['meta']), 'bootstrap': list(p['bootstrap']), 'job_prefix': j['id_prefix'], 'jobs_dir': j['dir'], 'reg_jobs': f"{config['registries_dir']}/jobs",
            'reg_jsonl': f"{config['registries_dir']}/jobs.jsonl",
            'views': [f"{config['registries_dir']}/{n}.md" for n in config['registries']], 'text': dict(j['text'])}


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


def allowed(path, globs):
    return matches(path, globs)


def check(branch, changed, base_rows, head_rows, base_file, head_file, sessions=None, cfg=None, hook=None, base_ref=None):
    """Errors for this pull request. `base_file`/`head_file` are callables path -> text or None. `sessions`: callable path ->
    list with one set of trailer values per branch commit that touched it (job branches; an empty set is a commit without a trailer, which
    is refused; None skips the authorship check, for the pure-logic tests). `cfg`: settings(). `hook`: callable(facts) -> [str], the
    repo's `policy`-stage gate modules (facts: branch, kind, jid, changed), called after the decisions check. `base_ref`: the base's name
    for messages."""
    cfg = cfg or settings(_default_config())
    T, jd, trailer = cfg['text'], cfg['jobs_dir'], cfg['trailer']
    errs = (decisions_problems(base_file(cfg['decisions']), head_file(cfg['decisions']), cfg, base_ref or 'the base branch')
            if cfg['decisions'] and cfg['decisions'] in changed else [])
    m = re.fullmatch(rf"(job|brief)/({re.escape(cfg['job_prefix'])}[1-9][0-9]*)", branch)
    kind = m.group(1) if m else branch.split('/', 1)[0] if '/' in branch else ''
    if hook:
        errs += hook({'branch': branch, 'kind': kind, 'jid': m.group(2) if m else None, 'changed': changed})
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
        errs.append(f'branch "{branch}" is not job/{cfg["job_prefix"]}<n>, brief/{cfg["job_prefix"]}<n>, plan/* or meta/*: all work goes through the job queue'
                    + (f" ({T['rules_ref']})" if T.get('rules_ref') else '') + '. Rename the branch, or add the work as a job first.')
    return errs


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


def run_check(ctx, branch, base, head, repo, extra_facts=None, base_ref=None):
    """The errors and the changed files of `branch` (the commit `head`) against `base`, read with git at `repo` (the clone; refs resolve there
    to shas). `ctx` holds the rules: the base tree in the `--judge` child, this checkout in the pre-W23 fallback. Its config and its gate
    modules judge; `ctx.root` is never a git cwd. `extra_facts`: more facts for the `policy`-stage gate modules (`ctx.facts`)."""
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
                 sessions, cfg, hook, base_ref)
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
