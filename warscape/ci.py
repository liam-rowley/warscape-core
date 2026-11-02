"""CI helpers as library code (verb: warscape/verbs/ci.py): which slow checks a diff needs, the failure comment, the rendered workflows.

Moved from napoleon-remastered `tools/changed_inputs.py` and `tools/ci_notify.py` (napoleon J62, J41, J42, J54). Everything a repo decides is in
its `wsc.toml` `[ci]` table: the input sets (set name -> regex of the paths that make that slow job run), the salt of the CI pass markers, the
hint text per failed job, the artifact each build keeps. The workflow templates (warscape/ci_render.py) read the same table.
"""
import hashlib
import json
import re
import subprocess

from .repo import git_env

MARK = '<!-- ci_notify run {run} attempt {attempt} -->'


# ------------------------------------------------------------------ inputs
def input_sets(cfg):
    """{set name: compiled regex} from `[ci] inputs`; a bad regex is an error that names the set."""
    out = {}
    for k, rx in cfg['inputs'].items():
        try:
            out[k] = re.compile(rx)
        except re.error as e:
            raise ValueError(f'wsc.toml [ci] inputs.{k}: bad regex ({e})') from None
    return out


def classify(files, sets):
    """{set: bool}; files None means the base is unknown: everything changed."""
    return {k: files is None or any(rx.search(f) for f in files) for k, rx in sets.items()}


def _git(root, *args):
    """(returncode, stdout lines) of a git command in root; 127 when git cannot start."""
    try:
        r = subprocess.run(['git', '-c', 'core.quotepath=off', *args], cwd=root, capture_output=True, text=True, timeout=60, env=git_env())
        return r.returncode, [l for l in r.stdout.splitlines() if l.strip()]
    except (OSError, subprocess.SubprocessError):
        return 127, []


def known_commit(root, base, git=_git):
    return bool(base) and git(root, 'cat-file', '-e', f'{base}^{{commit}}')[0] == 0


def changed_files(root, base, head='HEAD', git=_git):
    """Files changed from base to head, or None when base is not a commit here (shallow clone, force push, first push)."""
    if not known_commit(root, base, git):
        return None
    rc, files = git(root, 'diff', '--name-only', base, head)
    return files if rc == 0 else None


def tree_entries(root, ref='HEAD', git=_git):
    """[(path, 'mode object')] of every file and gitlink in ref's tree (a submodule is a gitlink: its pinned commit, without the submodule),
    or None when the tree cannot be read."""
    rc, lines = git(root, 'ls-tree', '-r', '--full-tree', ref)
    if rc != 0 or not lines:
        return None
    out = []
    for line in lines:
        meta, sep, path = line.partition('\t')
        parts = meta.split()
        if not sep or len(parts) != 3:
            return None
        out.append((path, f'{parts[0]} {parts[2]}'))
    return out


def tree_hashes(entries, sets, salt):
    """{set: sha256 hex} over the sorted (mode, object, path) entries whose path the set's regex matches, with the set's name and the
    salt; entries None (the tree could not be read) gives '' for every set, which CI treats as "no marker can match": the job runs."""
    out = {}
    for k, rx in sets.items():
        if entries is None:
            out[k] = ''
            continue
        h = hashlib.sha256(f'ci-pass {salt} {k}\n'.encode())
        for path, meta in sorted(entries):
            if rx.search(path):
                h.update(f'{meta}\t{path}\n'.encode())
        out[k] = h.hexdigest()
    return out


def local_base(root, git=_git):
    """The merge base with origin/main, or None (no origin/main, a shallow clone)."""
    rc, out = git(root, 'rev-parse', '--is-shallow-repository')
    if rc != 0 or out[:1] == ['true']:
        return None
    rc, out = git(root, 'merge-base', 'origin/main', 'HEAD')
    return out[0].strip() if rc == 0 and out else None


def local_changes(root, git=_git):
    """(base, files) for a local run: committed since the merge base with origin/main, plus staged, unstaged and untracked files, so
    an edit not yet committed still counts. files is None when the base is unknown."""
    base = local_base(root, git)
    files = changed_files(root, base, 'HEAD', git)
    if files is None:
        return base, None
    for args in (('diff', '--name-only', 'HEAD'), ('ls-files', '--others', '--exclude-standard')):
        rc, more = git(root, *args)
        if rc != 0:
            return base, None
        files += more
    return base, sorted(set(files))


# ------------------------------------------------------------------ notify
def class_hint(job, step, cfg, branch=''):
    """What to check first for a failed job and step: `[ci] hints` key "job~substring|substring" (a step containing one), else "job", else "*"."""
    step = step or ''
    hints = cfg['hints']
    for key, text in hints.items():
        name, sep, pats = key.partition('~')
        if sep and name == job and any(p and p in step for p in pats.split('|')):
            return text.replace('<branch>', branch)
    for key in (job, '*'):
        if key in hints:
            return hints[key].replace('<branch>', branch)
    return 'no hint is configured for this job ([ci] hints in wsc.toml)'


def failed(jobs):
    """[(job name, first failed step name)] for the jobs of one run attempt that failed or timed out."""
    out = []
    for j in jobs:
        if j.get('conclusion') in ('failure', 'timed_out', 'startup_failure'):
            step = next((s['name'] for s in j.get('steps') or [] if s.get('conclusion') in ('failure', 'timed_out')), '')
            out.append((j['name'], step))
    return out


def message(fails, run, attempt, url, branch, cfg):
    lines = [MARK.format(run=run, attempt=attempt),
             f'**CI failed** on `{branch}` ([run {run}]({url}){f", attempt {attempt}" if attempt > 1 else ""}). '
             + cfg['notice'], '']
    for job, step in fails:
        lines.append(f'- `{job}`{f", step `{step}`" if step else ""}: {class_hint(job, step, cfg, branch)}')
    if cfg['footer']:
        lines += ['', cfg['footer']]
    return '\n'.join(lines)


def gh(args, run=subprocess.run):
    p = run(['gh', *args], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise SystemExit(f'ci_notify: gh {" ".join(args[:3])} failed: {(p.stderr or p.stdout).strip()[:300]}')
    return p.stdout


def notify(cfg, run_id, attempt, branch, repo='', dry_run=False, run=subprocess.run, out=print):
    """Comment once on the open pull request of `branch` when run `run_id` attempt `attempt` has a failed job. Returns 0."""
    rp = ['--repo', repo] if repo else []
    prs = json.loads(gh(['pr', 'list', *rp, '--head', branch, '--state', 'open', '--json', 'number'], run) or '[]')
    if not prs:
        out(f'ci_notify: {branch} has no open pull request: nothing to tell')
        return 0
    num = prs[0]['number']
    api = f'repos/{repo or "{owner}/{repo}"}'
    jobs = json.loads(gh(['api', f'{api}/actions/runs/{run_id}/attempts/{attempt}/jobs'], run))['jobs']
    fails = failed(jobs)
    if not fails:
        out(f'ci_notify: run {run_id} attempt {attempt} has no failed job (cancelled?): nothing to tell')
        return 0
    seen = gh(['api', '--paginate', f'{api}/issues/{num}/comments', '--jq', '.[].body'], run)
    if MARK.format(run=run_id, attempt=attempt) in seen:
        out(f'ci_notify: PR #{num} already has the comment for run {run_id} attempt {attempt}')
        return 0
    url = json.loads(gh(['api', f'{api}/actions/runs/{run_id}', '--jq', '{u: .html_url}'], run))['u']
    body = message(fails, run_id, attempt, url, branch, cfg)
    if dry_run:
        out(f'ci_notify: would comment on PR #{num}:\n{body}')
        return 0
    gh(['pr', 'comment', str(num), *rp, '--body', body], run)
    out(f'ci_notify: commented on PR #{num}: {", ".join(j for j, _ in fails)} failed')
    return 0
