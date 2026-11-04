"""Host tests for warscape/ci_main.py (`wsc ci main-health`, W22): one issue per red required job on main, on recorded `gh` answers."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from warscape import ci, ci_main  # noqa: E402
from warscape.repo import DEFAULTS  # noqa: E402

CFG = {**DEFAULTS['ci'], 'required_checks': ['gates', 'proxy', 'policy'],
       'hints': {'proxy~build': 'a download timeout? rerun; branch <branch>', 'proxy': 'check the proxy build', '*': 'see the notes'}}
SHA = 'abcdef1234567890'


def job(name, conclusion, step=None):
    steps = [{'name': 'setup', 'conclusion': 'success'}]
    if step:
        steps.append({'name': step, 'conclusion': 'failure'})
    return {'name': name, 'conclusion': conclusion, 'status': 'completed' if conclusion else 'in_progress', 'steps': steps}


def mark(name):
    return f'<!-- ci_main job {name} -->'


class FakeGh:
    """A recorded `gh`: run info, main's tip, the run's jobs, the open issues and their comments; writes are recorded in `.writes`."""
    def __init__(self, jobs, issues=(), comments=None, main=SHA, head=SHA, fail=None):
        self.jobs, self.issues, self.comments, self.main, self.head, self.fail = jobs, list(issues), comments or {}, main, head, fail
        self.calls, self.writes = [], []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        a = argv[1:]
        if self.fail:
            if isinstance(self.fail, BaseException):
                raise self.fail
            return subprocess.CompletedProcess(argv, 1, '', self.fail)
        out = ''
        if a[0] == 'api' and a[-1].endswith('/commits/main') or (a[0] == 'api' and '/commits/main' in a[1]):
            out = json.dumps({'sha': self.main})
        elif a[0] == 'api' and '/attempts/' in a[1]:
            out = json.dumps({'jobs': self.jobs})
        elif a[0] == 'api' and a[1] == '--paginate':
            out = self.comments.get(int(a[2].split('/')[-2]), '')
        elif a[0] == 'api':
            out = json.dumps({'head_sha': self.head, 'html_url': 'https://github.com/o/r/actions/runs/42'})
        elif a[:2] == ['issue', 'list']:
            out = json.dumps(self.issues)
        elif a[0] == 'issue':
            self.writes.append(a)
            out = 'https://github.com/o/r/issues/9\n' if a[1] == 'create' else ''
        return subprocess.CompletedProcess(argv, 0, out, '')

    def kinds(self):
        return [w[1] for w in self.writes]


class MainHealth(unittest.TestCase):
    def go(self, gh, cfg=CFG, dry=False, run_id=42, attempt=1):
        lines = []
        rc = ci_main.main_health(cfg, run_id, attempt, 'o/r', dry, run=gh, out=lines.append)
        return rc, '\n'.join(lines)

    def issue(self, num, name, extra=''):
        return {'number': num, 'title': f'CI is red on main: {name}', 'body': f'{mark(name)}\nfirst red run{extra}'}

    def test_red_with_no_issue_opens_exactly_one(self):
        gh = FakeGh([job('gates', 'success'), job('proxy', 'failure', 'Run build.sh all'), job('notify', 'skipped')])
        rc, out = self.go(gh)
        self.assertEqual(rc, 0)
        self.assertEqual(gh.kinds(), ['create'])
        argv = gh.writes[0]
        self.assertEqual(argv[argv.index('--title') + 1], 'CI is red on main: proxy')
        body = argv[argv.index('--body') + 1]
        self.assertTrue(body.startswith(mark('proxy')))
        for s in ('https://github.com/o/r/actions/runs/42', 'abcdef1', 'Run build.sh all', 'a download timeout? rerun; branch main',
                  'gh run rerun 42 --failed', 'closes itself'):
            self.assertIn(s, body)
        self.assertIn('proxy', out)
        self.assertIn('--repo', argv)

    def test_red_with_an_open_issue_comments_once_per_run_and_attempt(self):
        gh = FakeGh([job('proxy', 'failure', 'x')], issues=[self.issue(7, 'proxy')])
        self.go(gh)
        self.assertEqual(gh.kinds(), ['comment'])
        self.assertEqual(gh.writes[0][2], '7')
        body = gh.writes[0][gh.writes[0].index('--body') + 1]
        self.assertIn('<!-- ci_main run 42 attempt 1 -->', body)
        gh = FakeGh([job('proxy', 'failure', 'x')], issues=[self.issue(7, 'proxy')], comments={7: 'a\n<!-- ci_main run 42 attempt 1 -->\n'})
        self.go(gh)
        self.assertEqual(gh.writes, [])
        gh = FakeGh([job('proxy', 'failure', 'x')], issues=[self.issue(7, 'proxy')], comments={7: '<!-- ci_main run 42 attempt 1 -->'})
        self.go(gh, attempt=2)   # a new attempt is a new comment
        self.assertEqual(gh.kinds(), ['comment'])

    def test_two_red_jobs_open_two_issues(self):
        gh = FakeGh([job('gates', 'timed_out', 's'), job('proxy', 'startup_failure')])
        self.go(gh)
        self.assertEqual(gh.kinds(), ['create', 'create'])
        self.assertEqual({w[w.index('--title') + 1] for w in gh.writes}, {'CI is red on main: gates', 'CI is red on main: proxy'})

    def test_a_name_that_is_a_prefix_of_another_does_not_match_its_issue(self):
        cfg = {**CFG, 'required_checks': ['gates', 'gates (windows)']}
        gh = FakeGh([job('gates', 'failure'), job('gates (windows)', 'success')], issues=[self.issue(3, 'gates (windows)')])
        self.go(gh, cfg)
        self.assertEqual(gh.kinds(), ['create', 'comment', 'close'])   # gates opens its own; the green `gates (windows)` closes only issue 3
        self.assertEqual([w[2] for w in gh.writes[1:]], ['3', '3'])

    def test_an_issue_that_only_quotes_the_mark_is_not_ours(self):
        quoted = {'number': 5, 'title': 'my notes', 'body': f'someone wrote\n{mark("proxy")}'}
        gh = FakeGh([job('proxy', 'success')], issues=[quoted])
        self.go(gh)
        self.assertEqual(gh.writes, [])

    def test_green_closes_the_open_issue_with_one_comment_and_leaves_others(self):
        gh = FakeGh([job('gates', 'success'), job('proxy', 'skipped'), job('policy', 'failure')],
                    issues=[self.issue(7, 'proxy'), self.issue(8, 'policy'), {'number': 9, 'title': 'other', 'body': 'x'}])
        self.go(gh)
        self.assertEqual(gh.kinds(), ['comment', 'close', 'comment'])
        self.assertEqual([w[2] for w in gh.writes], ['7', '7', '8'])
        self.assertIn('green in run 42', gh.writes[0][gh.writes[0].index('--body') + 1])
        self.assertIn(SHA[:7], gh.writes[0][gh.writes[0].index('--body') + 1])

    def test_green_with_no_issue_does_nothing(self):
        gh = FakeGh([job('gates', 'success'), job('proxy', 'skipped')])
        self.go(gh)
        self.assertEqual(gh.writes, [])

    def test_cancelled_and_in_progress_change_nothing(self):
        gh = FakeGh([job('gates', 'cancelled'), job('proxy', None), job('policy', 'neutral')],
                    issues=[self.issue(1, 'gates'), self.issue(2, 'proxy'), self.issue(3, 'policy')])
        self.go(gh)
        self.assertEqual(gh.writes, [])

    def test_a_required_check_the_run_did_not_produce_is_ignored(self):
        gh = FakeGh([job('gates', 'success')], issues=[self.issue(3, 'policy')])
        self.go(gh)
        self.assertEqual(gh.writes, [])   # policy is required but no push run makes it: its issue is not touched

    def test_empty_required_checks_derives_from_the_run(self):
        cfg = {**CFG, 'required_checks': []}
        gh = FakeGh([job('changes', 'failure'), job('notify', 'failure'), job('main_health', 'failure'), job('viewer', 'failure', 's')])
        self.go(gh, cfg)
        self.assertEqual([w[w.index('--title') + 1] for w in gh.writes], ['CI is red on main: viewer'])
        self.assertEqual([j['name'] for j in ci.required_jobs(cfg, [job('changes', 'success'), job('a', 'success')])], ['a'])
        self.assertEqual([j['name'] for j in ci.required_jobs(CFG, [job('changes', 'success'), job('a', 'success'), job('gates', 'success')])], ['gates'])

    def test_a_stale_run_does_nothing(self):
        gh = FakeGh([job('proxy', 'failure')], main='9999999aaaa', head=SHA)
        rc, out = self.go(gh)
        self.assertEqual((rc, gh.writes), (0, []))
        self.assertIn('main moved to 9999999; the newer run decides', out)
        self.assertFalse(any(c[1:3] == ['issue', 'list'] for c in gh.calls))

    def test_gh_problems_print_the_reason_and_return_zero(self):
        for fail in ('HTTP 410: Issues are disabled for this repo', 'HTTP 403: Resource not accessible by integration', 'API rate limit exceeded'):
            rc, out = self.go(FakeGh([job('proxy', 'failure')], fail=fail))
            self.assertEqual(rc, 0, fail)
            self.assertIn(fail[:20], out)
        rc, out = self.go(FakeGh([], fail=FileNotFoundError('gh')))
        self.assertEqual(rc, 0)
        self.assertIn('gh', out)

    def test_issue_write_failure_is_reported_not_raised(self):
        class Denied(FakeGh):
            def __call__(self, argv, **kw):
                if argv[1:3] == ['issue', 'create']:
                    return subprocess.CompletedProcess(argv, 1, '', 'HTTP 403: Resource not accessible by integration')
                return super().__call__(argv, **kw)
        rc, out = self.go(Denied([job('proxy', 'failure', 's')]))
        self.assertEqual(rc, 0)
        self.assertIn('Resource not accessible', out)

    def test_dry_run_posts_nothing_and_says_what_it_would_do(self):
        gh = FakeGh([job('gates', 'failure', 's'), job('proxy', 'success')], issues=[self.issue(7, 'proxy')])
        rc, out = self.go(gh, dry=True)
        self.assertEqual((rc, gh.writes), (0, []))
        self.assertIn('would open', out)
        self.assertIn('would close', out)


class Verb(unittest.TestCase):
    def test_main_health_needs_a_run_id(self):
        import types
        from warscape.verbs import ci as verb
        args = types.SimpleNamespace(action='main-health', run_id=None, attempt=1, repo='', dry_run=False)
        ctx = types.SimpleNamespace(config={'ci': CFG}, root=ROOT)
        self.assertEqual(verb.run(args, ctx), 2)


if __name__ == '__main__':
    unittest.main()
