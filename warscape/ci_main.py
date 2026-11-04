"""`wsc ci main-health` (W22, audit 2026-11-03 P1): one issue per red required job on main, closed once the job is green.

Run by the `main_health` workflow job after every push run on main. It reads the run's jobs, keeps the required ones (`ci.required_jobs`), and
for each: red with no open issue opens one; red with an open issue adds one comment per (run, attempt); green with an open issue comments and
closes it; anything else (cancelled, still running) is left alone. Open issues are found by a hidden mark that starts the body, never by title
search or label. A run that is not main's tip does nothing (an older run finishing late must not reopen or close out of order). A problem it can
explain (issues disabled, no permission, rate limit, no gh) is printed and the exit code stays 0: the job must never turn main red.
All `gh` calls go through `ci.gh(args, run=...)`, so tests inject recorded answers.
"""
import json
import subprocess

from . import ci

TITLE = 'CI is red on main: {job}'
JOB_MARK = '<!-- ci_main job {job} -->'
RUN_MARK = '<!-- ci_main run {run} attempt {attempt} -->'
GREEN_MARK = '<!-- ci_main green run {run} attempt {attempt} -->'


def _body(job, step, run_id, url, sha, cfg):
    return '\n'.join([
        JOB_MARK.format(job=job),
        f'**CI is red on `main`: `{job}`.** First red run: [run {run_id}]({url}), commit `{sha[:7]}`' + (f', failed step `{step}`.' if step else '.'),
        '', ci.class_hint(job, step, cfg, 'main'), '',
        f'Rerun the failed jobs of the run (`gh run rerun {run_id} --failed`) or push to `main`. This issue closes itself once the job is green.'])


def _find(issues, job):
    """The open issue (lowest number) whose body starts with the job's whole mark, or None."""
    mark = JOB_MARK.format(job=job)
    hits = [i for i in issues if (i.get('body') or '').lstrip().startswith(mark)]
    return min(hits, key=lambda i: i['number']) if hits else None


def main_health(cfg, run_id, attempt, repo='', dry_run=False, run=subprocess.run, out=print):
    """Returns 0 always for a gh problem it can explain (printed with its reason); the verb returns 2 for bad arguments."""
    rp = ['--repo', repo] if repo else []
    api = f'repos/{repo or "{owner}/{repo}"}'

    def say(s):
        out(f'ci main-health: {s}')
    try:
        info = json.loads(ci.gh(['api', f'{api}/actions/runs/{run_id}', '--jq', '{head_sha: .head_sha, html_url: .html_url}'], run))
        tip = json.loads(ci.gh(['api', f'{api}/commits/main', '--jq', '{sha: .sha}'], run))['sha']
        if tip != info['head_sha']:
            say(f'main moved to {tip[:7]}; the newer run decides')
            return 0
        jobs = json.loads(ci.gh(['api', f'{api}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100'], run))['jobs']
        required = ci.required_jobs(cfg, jobs)
        if not required:
            say(f'run {run_id} has no required job: nothing to do')
            return 0
        issues = json.loads(ci.gh(['issue', 'list', *rp, '--state', 'open', '--limit', '200', '--json', 'number,title,body'], run) or '[]')
        sha, url = info['head_sha'], info['html_url']
        fails = dict(ci.failed(jobs))
        for j in required:
            name, concl = j['name'], j.get('conclusion')
            open_issue = _find(issues, name)
            if concl in ci.RED:
                if open_issue is None:
                    if dry_run:
                        say(f'{name}: red; would open an issue "{TITLE.format(job=name)}"')
                        continue
                    ci.gh(['issue', 'create', *rp, '--title', TITLE.format(job=name),
                           '--body', _body(name, fails.get(name, ''), run_id, url, sha, cfg)], run)
                    say(f'{name}: red; opened an issue')
                    continue
                num = open_issue['number']
                mark = RUN_MARK.format(run=run_id, attempt=attempt)
                if mark in ci.gh(['api', '--paginate', f'{api}/issues/{num}/comments', '--jq', '.[].body'], run):
                    say(f'{name}: red; issue #{num} already has the comment for run {run_id} attempt {attempt}')
                elif dry_run:
                    say(f'{name}: red; would comment on issue #{num}')
                else:
                    ci.gh(['issue', 'comment', str(num), *rp, '--body',
                           f'{mark}\nStill red in [run {run_id}]({url}) (attempt {attempt}), commit `{sha[:7]}`'
                           + (f', failed step `{fails[name]}`.' if fails.get(name) else '.')], run)
                    say(f'{name}: red; commented on issue #{num}')
            elif concl in ci.GREEN:
                if open_issue is None:
                    say(f'{name}: green; no open issue')
                    continue
                num = open_issue['number']
                mark = GREEN_MARK.format(run=run_id, attempt=attempt)
                if dry_run:
                    say(f'{name}: green; would close issue #{num}')
                    continue
                if mark not in ci.gh(['api', '--paginate', f'{api}/issues/{num}/comments', '--jq', '.[].body'], run):
                    ci.gh(['issue', 'comment', str(num), *rp, '--body', f'{mark}\ngreen in run {run_id} ({sha[:7]}): [run]({url}), attempt {attempt}. Closing.'], run)
                ci.gh(['issue', 'close', str(num), *rp], run)
                say(f'{name}: green; closed issue #{num}')
            else:
                say(f'{name}: {concl or "not finished"}; left alone')
    except SystemExit as e:
        say(f'cannot finish: {e}')
    except (OSError, subprocess.SubprocessError) as e:
        say(f'cannot run gh ({e})')
    except (ValueError, KeyError, TypeError) as e:
        say(f'unexpected answer from gh ({type(e).__name__}: {e})')
    return 0
