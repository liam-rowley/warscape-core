"""`wsc ci check-settings` (W21, backlog B47): the repository settings a pipeline needs, read through `gh api` and compared with the workflows.

Read-only: three GETs (`repos/{r}`, `repos/{r}/rules/branches/{b}`, `repos/{r}/branches/{b}/protection`) through the same injectable runner
as `wsc ci notify` (warscape/ci.py `gh`). The settings are the owner's; this only says when they drift from what the workflows need:
- every expected check must be required (else a red check does not block a merge). Expected: `[ci] required_checks`, or, when that is
  empty, every job id of the workflows in `[ci] workflows` but `changes` and `notify`. A matrix job reports one check per value
  (`gates (ubuntu-latest)`), which cannot be known without a YAML parser: it is named for `[ci] required_checks` instead of guessed;
- every required check must be produced by a workflow job (a renamed job's old check never reports, so every merge waits for it);
- `allow_auto_merge` must be on (`gh pr merge --auto` has nothing to wait for otherwise);
- issues must be enabled (`wsc ci main-health` opens one per red required job on main);
- no rule may require approving reviews (one account cannot approve its own pull request: the pipeline's merges stall).
Notes, not problems: a workflow job that is not required (napoleon's `viewer`), `strict` up-to-date checks, classic protection that
cannot be read without admin rights. Exit 0 no problem, 1 problems, 2 the settings cannot be read (no `gh`, not logged in, no access).
"""
import json
import re
import subprocess
from pathlib import Path

from . import ci

SKIP = ci.SKIP   # changes, notify, main_health (W22): not required checks


def workflow_jobs(text):
    """[(job id, check name or None, is matrix)] of one workflow: the two-space keys under `jobs:`. The check name is the job's
    `name:` when it has a plain one, else its id; None when GitHub names it per matrix value or by an expression."""
    m = re.search(r'^jobs:\s*$', text, re.M)
    if not m:
        return []
    body = text[m.end():]
    parts = re.split(r'^  ([A-Za-z0-9_-]+):\s*$', body, flags=re.M)
    out = []
    for jid, block in zip(parts[1::2], parts[2::2]):
        matrix = re.search(r'^      matrix:', block, re.M) is not None
        nm = re.search(r'^    name:\s*(.+?)\s*$', block, re.M)
        name = nm.group(1).strip('\'"') if nm else jid
        out.append((jid, None if matrix or '${{' in name else name, matrix))
    return out


def read_jobs(cfg, root):
    jobs = []
    for n in cfg['workflows']:
        f = Path(root) / '.github' / 'workflows' / n
        if f.is_file():
            jobs += workflow_jobs(f.read_text(encoding='utf-8'))
    return jobs


def produced(check, jobs):
    """True when a workflow job reports `check` (its name, or `<id> (<value>)` for a matrix job)."""
    return any(check == name or (matrix or name is None) and check.startswith(f'{jid} (') for jid, name, matrix in jobs)


def _api(path, run):
    """(HTTP status, parsed JSON or None, message): 200 on success, else the status gh names ('HTTP 404'), 0 when it names none."""
    try:
        return 200, json.loads(ci.gh(['api', path], run) or 'null'), ''
    except SystemExit as e:
        msg = str(e)
        m = re.search(r'HTTP (\d{3})', msg)
        return (int(m.group(1)) if m else 0), None, msg


def read_settings(repo, branch, run):
    """The settings as one dict, or raise LookupError naming what cannot be read."""
    st, info, msg = _api(f'repos/{repo}', run)
    if st != 200:
        raise LookupError(f'cannot read repos/{repo}: {msg}')
    st, rules, msg = _api(f'repos/{repo}/rules/branches/{branch}', run)
    if st != 200:
        raise LookupError(f'cannot read the rulesets of {branch}: {msg}')
    s = {'auto_merge': bool(info.get('allow_auto_merge')), 'issues': info.get('has_issues'), 'required': [], 'strict': False, 'approvals': 0, 'classic': 'none', 'where': {}}
    for r in rules or []:
        p = r.get('parameters') or {}
        if r.get('type') == 'required_status_checks':
            for c in p.get('required_status_checks') or []:
                s['required'].append(c['context'])
                s['where'][c['context']] = 'ruleset'
            s['strict'] |= bool(p.get('strict_required_status_checks_policy'))
        elif r.get('type') == 'pull_request':
            s['approvals'] = max(s['approvals'], int(p.get('required_approving_review_count') or 0))
    st, prot, msg = _api(f'repos/{repo}/branches/{branch}/protection', run)
    if st == 200:
        s['classic'] = 'read'
        rsc = (prot or {}).get('required_status_checks') or {}
        for c in list(rsc.get('contexts') or []) + [c.get('context') for c in rsc.get('checks') or []]:
            if c and c not in s['required']:
                s['required'].append(c)
                s['where'][c] = 'classic'
        s['strict'] |= bool(rsc.get('strict'))
        rv = (prot or {}).get('required_pull_request_reviews') or {}
        s['approvals'] = max(s['approvals'], int(rv.get('required_approving_review_count') or 0))
    elif st == 404:
        s['classic'] = 'none'
    elif st == 403:
        s['classic'] = 'forbidden'
    else:
        raise LookupError(f'cannot read the classic protection of {branch}: {msg}')
    return s


def findings(cfg, jobs, s, branch):
    """[(level, text)]: 'problem' or 'note'."""
    out = []
    explicit = list(cfg.get('required_checks') or [])
    if explicit:
        expected = explicit
    else:
        expected = []
        for jid, name, matrix in jobs:
            if jid in SKIP:
                continue
            if name is None:
                out.append(('note', f'matrix job {jid}: list its checks in [ci] required_checks (GitHub names them `{jid} (<value>)`)'))
            elif name not in expected:
                expected.append(name)
    req = set(s['required'])
    for e in expected:
        if e not in req:
            out.append(('problem', f'`{e}` is expected but not a required check on {branch}: a red `{e}` would not block a merge'))
    for r in s['required']:
        if not produced(r, jobs):
            out.append(('problem', f'required check `{r}` ({s["where"].get(r, "ruleset")}) is produced by no workflow job in [ci] workflows: '
                                   'it never reports, so every merge waits for it (a renamed job?)'))
    if not s['auto_merge']:
        out.append(('problem', 'allow_auto_merge is false: `gh pr merge --auto` has nothing to wait for (Settings, General, "Allow auto-merge")'))
    if s.get('issues') is False:
        out.append(('problem', 'issues are disabled: `main_health` cannot open an issue for a red main (Settings, General, Features, "Issues")'))
    if s['approvals']:
        out.append(('problem', f'a rule requires {s["approvals"]} approving review(s): one account cannot approve its own pull request, '
                               'so the pipeline\'s merges stall'))
    flagged = {e for e in expected if e not in req}
    for jid, name, matrix in jobs:
        if jid in SKIP or (name in flagged):
            continue
        if name is None:
            if not any(r.startswith(f'{jid} (') for r in req) and explicit:
                out.append(('note', f'workflow job `{jid}` (matrix) has no required check'))
        elif name not in req and name not in expected:
            out.append(('note', f'workflow job `{name}` is not a required check'))
    if s['strict']:
        out.append(('note', 'strict: required checks must pass on a branch that is up to date with main (every main merge restarts the queue)'))
    return out


RELEASE_MANUAL = ('manual: the release workflow (W29, C27) needs what a settings read cannot show without admin rights: the secrets '
                  'RELEASE_APP_CLIENT_ID and RELEASE_APP_KEY (a GitHub App with contents, pull requests and issues write, checks read; '
                  'or one secret RELEASE_TOKEN), allow_auto_merge kept on, and a tag ruleset on refs/tags/v* that blocks update and deletion '
                  '(docs/CONSUMING.md, Releases)')


def manual_lines(cfg):
    """Lines the owner checks by hand: a secret's value cannot be read, and tag rulesets need admin rights to list."""
    return [RELEASE_MANUAL] if 'release.yml' in (cfg.get('workflows') or []) else []


def check(cfg, root, repo='', branch='main', run=subprocess.run, out=print):
    """Print the settings and the findings; 0 no problem, 1 problems, 2 cannot read."""
    try:
        if not repo:
            repo = json.loads(ci.gh(['repo', 'view', '--json', 'nameWithOwner'], run))['nameWithOwner']
        s = read_settings(repo, branch, run)
    except OSError as e:
        out(f'check-settings: cannot run gh ({e}): install the GitHub CLI and `gh auth login`')
        return 2
    except (SystemExit, LookupError, ValueError, KeyError) as e:
        out(f'check-settings: cannot read the settings of {repo or "this repository"}: {e}')
        return 2
    jobs = read_jobs(cfg, root)
    classic = {'none': 'no classic branch protection', 'read': 'classic branch protection read',
               'forbidden': 'classic branch protection cannot be read without admin rights (HTTP 403); the rulesets answered'}[s['classic']]
    out(f'check-settings: {repo} {branch}: required checks {", ".join(s["required"]) or "none"}; allow_auto_merge '
        f'{str(s["auto_merge"]).lower()}; {classic}')
    out(f'check-settings: workflow checks {", ".join(n or f"{j} (matrix)" for j, n, _ in jobs if j not in SKIP) or "none"} '
        f'([ci] workflows); expected {", ".join(cfg.get("required_checks") or []) or "derived from the workflows"}')
    fs = findings(cfg, jobs, s, branch)
    for level, text in fs:
        out(f'{level}: {text}')
    for line in manual_lines(cfg):
        out(line)
    probs = sum(1 for level, _ in fs if level == 'problem')
    out(f'check-settings: {probs} problem(s), {len(fs) - probs} note(s); this changes nothing: the fix is the owner\'s, in the repository settings')
    return 1 if probs else 0
