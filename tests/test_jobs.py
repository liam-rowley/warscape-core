"""Host tests for warscape/jobq.py and verbs/jobs.py (`wsc jobs`): bad fixtures fail, good ones pass, and the core's own queue passes.

Moved from napoleon-remastered tests/test_jobs.py (napoleon J62); the game-only cases (rule 76, rule 75's PC line, the frozen id sets) stayed there.
"""
import html
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from warscape import jobq as jv  # noqa: E402

BRIEF = '''# J1: thing

Model: Opus, reason: DLL work (D15). Budget about 100 tool calls; at the cap, stop.

## Kill criteria
- It breaks twice: stop.

## Finish
Write `jobs/J1/report.md`. Then `wsc reg set jobs J1 status=review report=jobs/J1/report.md`.
'''
REPORT = '# J1 report: thing\n\n## What exists\nx\n\n## Deviations from the brief, and why\nnone\n\n## Open questions\nnone\n'
REVIEW = '# Review of J1\n\n## Round 1 (2026-10-29, branch job/J1 at abc1234)\n\n**Verdict: merge.**\n'


def row(jid='J1', **kw):
    r = {'id': jid, 'description': 'd', 'title': 't', 'phase': 1, 'status': 'needs_brief', 'model': 'opus', 'needs_pc': False,
         'depends_on': []}
    r.update(kw)
    return r


def files(**kw):
    m = {k.replace('__', '/').replace('_md', '.md'): v for k, v in kw.items()}
    return lambda p: m.get(p)


class Check(unittest.TestCase):
    def errs(self, rows, read=None, folders=()):
        return jv.problems(rows, read or files(), folders)

    def test_good_queue_passes(self):
        rows = [row(status='done', brief='jobs/J1/brief.md', report='jobs/J1/report.md', review='jobs/J1/review.md'),
                row('J2', status='queued', brief='jobs/J2/brief.md', depends_on=['J1'], model='sonnet'), row('J3')]
        read = lambda p: {'jobs/J1/brief.md': BRIEF, 'jobs/J1/report.md': REPORT, 'jobs/J1/review.md': REVIEW,
                          'jobs/J2/brief.md': BRIEF.replace('J1', 'J2').replace('Opus, reason: DLL work', 'Sonnet medium')}.get(p)
        self.assertEqual(self.errs(rows, read, ['J1', 'J2']), [])

    def test_status_needs_its_files(self):
        e = self.errs([row(status='review', brief='jobs/J1/brief.md', report='jobs/J1/report.md')], lambda p: None)
        self.assertTrue(any('brief=jobs/J1/brief.md but the file does not exist' in x for x in e), e)
        self.assertTrue(any('report=jobs/J1/report.md but the file does not exist' in x for x in e), e)

    def test_link_to_another_jobs_file(self):
        e = self.errs([row(status='queued', brief='jobs/J2/brief.md')], lambda p: BRIEF if p == 'jobs/J2/brief.md' else None)
        self.assertTrue(any('points at another job' in x for x in e), e)

    def test_brief_present_but_needs_brief(self):
        e = self.errs([row()], lambda p: BRIEF if p == 'jobs/J1/brief.md' else None)
        self.assertTrue(any('still needs_brief' in x for x in e), e)

    def test_done_needs_merge_verdict_and_date(self):
        rows = [row(status='done', brief='jobs/J1/brief.md', report='jobs/J1/report.md', review='jobs/J1/review.md')]
        read = lambda p: {'jobs/J1/brief.md': BRIEF, 'jobs/J1/report.md': REPORT,
                          'jobs/J1/review.md': '# Review\n\n**Verdict: merge after fixes.**\n'}.get(p)
        e = self.errs(rows, read)
        self.assertTrue(any('verdict is "merge after fixes"' in x for x in e), e)
        self.assertTrue(any('no date' in x for x in e), e)

    def test_dependencies_done_before_review_and_no_cycles(self):
        rows = [row(status='review', brief='jobs/J1/brief.md', report='jobs/J1/report.md', depends_on=['J2']),
                row('J2', depends_on=['J1'])]
        e = self.errs(rows, lambda p: {'jobs/J1/brief.md': BRIEF, 'jobs/J1/report.md': REPORT}.get(p))
        self.assertTrue(any('dependencies J2 are not done' in x for x in e), e)
        self.assertTrue(any('dependency cycle' in x for x in e), e)

    def test_report_shape(self):
        self.assertEqual(jv.report_problems('J1', REPORT), [])
        bad = jv.report_problems('J1', '# Report\n\n## What exists\n')
        self.assertEqual(len(bad), 3, bad)

    def test_folder_without_row(self):
        self.assertEqual(self.errs([], folders=['J9']), ['jobs/J9/ has no row in the jobs registry'])

    def test_brief_shape(self):
        r = row(status='queued', brief='jobs/J1/brief.md')
        self.assertEqual(jv.brief_problems('J1', r, BRIEF), [])
        bad = jv.brief_problems('J1', r, '# J1: thing\n\nModel: Opus. No budget.\n\n## Kill criteria\nnone\n')
        for want in ('without "reason:"', 'no call budget', 'Kill criteria', 'Finish'):
            self.assertTrue(any(want in x for x in bad), (want, bad))
        self.assertTrue(any('row says sonnet' in x for x in jv.brief_problems('J1', row(model='sonnet'), BRIEF)))
        wrapped = BRIEF.replace('Budget about 100 tool calls', 'Budget\nabout 100 tool\ncalls')
        self.assertEqual(jv.brief_problems('J1', r, wrapped), [])


class Next(unittest.TestCase):
    ROWS = [row('J1', status='done'), row('J2', status='queued', depends_on=['J1']), row('J3', status='queued', depends_on=['J4']),
            row('J4', depends_on=['J1']), row('J10', status='queued', depends_on=['J1'])]

    def test_lowest_ready_queued_job_without_a_branch(self):
        self.assertEqual(jv.pick_next(self.ROWS, set())[1]['id'], 'J2')
        self.assertEqual(jv.pick_next(self.ROWS, {'job/J2'})[1]['id'], 'J10')   # numeric order, not text order

    def test_then_a_brief_then_nothing(self):
        kind, r, _ = jv.pick_next(self.ROWS, {'job/J2', 'job/J10'})
        self.assertEqual((kind, r['id']), ('brief', 'J4'))
        kind, r, waiting = jv.pick_next(self.ROWS, {'job/J2', 'job/J10', 'brief/J4'})
        self.assertIsNone(kind)
        self.assertTrue(any(w.startswith('J3') and 'J4' in w for w in waiting), waiting)

    def test_review_pick(self):
        self.assertEqual(jv.pick_review({'J3': row('J3', status='review'), 'J2': jv.Branch(row('J2', status='fix'), 1),
                                         'J1': row('J1', status='done')}), 'J3')
        self.assertIsNone(jv.pick_review({'J1': None}))
        self.assertEqual(jv.pick_branch('fix', {'J3': row('J3', status='review'), 'J2': jv.Branch(row('J2', status='fix'), 1)}), 'J2')


class Ledger(unittest.TestCase):
    def test_codeable_later_rows_naming_the_job(self):
        led = ('| # | Rule | Source | Before | After | Why |\n|---|---|---|---|---|---|\n'
               '| 7 | Settle before checking | N:PLAN.md:1 | CL | CL | J4 |\n'
               '| 8 | Poses by id | N:PLAN.md:2 | CL | CL | J4, J13 |\n'
               '| 9 | Not this one | N:PLAN.md:3 | CL | E | J4 |\n'
               '| 10 | Nor this | N:PLAN.md:4 | CL | CL | J40 |\n')
        self.assertEqual(jv.waiting_rules(led, 'J4'), ['row 7: Settle before checking', 'row 8: Poses by id'])
        self.assertEqual(jv.waiting_rules(led, 'J13'), ['row 8: Poses by id'])
        self.assertEqual(jv.waiting_rules(led, 'J5'), [])

    def _brief_steps_with(self, ledgers, files=None):
        old = jv.S.ledgers
        self.addCleanup(setattr, jv.S, 'ledgers', old)
        jv.S.ledgers = ledgers
        with tempfile.TemporaryDirectory() as d:
            for name, text in (files or {}).items():
                (Path(d) / name).write_text(text, encoding='utf-8')
            return jv.brief_steps(row('J4'), Path(d))

    def test_brief_steps_with_ledgers_unset_does_not_glob(self):
        out = self._brief_steps_with('')
        self.assertIn('needs a brief', out)
        self.assertNotIn('The brief must cover', out)

    def test_brief_steps_with_ledgers_set_lists_owed_rows(self):
        led = ('| # | Rule | Source | Before | After | Why |\n|---|---|---|---|---|---|\n'
               '| 7 | Settle before checking | N:PLAN.md:1 | CL | CL | J4 |\n')
        out = self._brief_steps_with('LEDGER*.md', {'LEDGER.md': led})
        self.assertIn('The brief must cover LEDGER.md row 7: Settle before checking', out)


class View(unittest.TestCase):
    def test_lanes_follow_status_branches_and_dependencies(self):
        by = {r['id']: r for r in [row('J1', status='done'), row('J2', status='queued', depends_on=['J1']),
                                   row('J3', status='queued', depends_on=['J4']), row('J4'), row('J5', status='queued')]}
        lane = lambda j, b=(): jv.lane(by[j], by, set(b))[0]
        self.assertEqual(lane('J1'), 'done')
        self.assertEqual(lane('J2'), 'ready')
        self.assertEqual(lane('J2', ['job/J2']), 'progress')
        self.assertEqual(lane('J3'), 'waiting')
        self.assertEqual(lane('J4'), 'brief')
        self.assertEqual(lane('J4', ['brief/J4']), 'progress')

    def test_page_escapes_and_embeds_docs(self):
        page = jv.render_view([row('J1', status='queued', brief='jobs/J1/brief.md', title='a <b> & c')],
                              files(jobs__J1__brief_md=BRIEF + '</script>'), set(), 'now')
        self.assertIn('a &lt;b&gt; &amp; c', page)
        self.assertIn('Next to pick up: <a href="#J1">', page)
        self.assertIn('&lt;/script&gt;', page)               # a doc cannot break out of the page
        self.assertNotIn('id="lane-review"', page)            # empty lanes are left out


# The launch fixture: one launchable job per action, and one that is not.
LROWS = [row('J1', status='done'), row('J2', status='queued', depends_on=['J1']), row('J3', model='sonnet'),
         row('J4', status='queued', model='sonnet'), row('J5', status='queued', depends_on=['J3'])]
LBRANCHES = {'job/J4'}
LON_BRANCH = {'J4': row('J4', status='review', model='sonnet')}
LBY = {r['id']: r for r in LROWS}


class Ready(unittest.TestCase):
    def why(self, action, jid, branches=LBRANCHES, on_branch=LON_BRANCH):
        return jv.not_ready(action, jid, LBY, set(branches), on_branch)

    def test_launchable(self):
        self.assertIsNone(self.why('build', 'J2'))
        self.assertIsNone(self.why('brief', 'J3'))
        self.assertIsNone(self.why('review', 'J4'))

    def test_each_refusal(self):
        self.assertEqual(self.why('build', 'J99'), 'J99 is not a row of the jobs registry')
        self.assertEqual(self.why('build', 'J1'), 'J1 is done, not queued')
        self.assertEqual(self.why('build', 'J5'), 'J5 (queued): waits for J3')
        self.assertEqual(self.why('build', 'J2', {'job/J2'}), 'J2 (queued): in progress on job/J2')
        self.assertEqual(self.why('brief', 'J3', {'brief/J3'}), 'J3 (needs_brief): in progress on brief/J3')
        self.assertEqual(self.why('build', 'J4'), 'J4 (queued): in progress on job/J4')
        self.assertEqual(self.why('review', 'J2', set(), {}), 'J2 has no job/J2 branch on origin')
        self.assertIn('not review', self.why('review', 'J4', on_branch={'J4': row('J4', status='queued')}))
        self.assertIn('no J4 row', self.why('review', 'J4', on_branch={'J4': None}))
        self.assertEqual(self.why('fix', 'J4'), 'J4 is review on job/J4, not fix')

    def test_fix_is_ready_from_the_branch_row(self):
        self.assertIsNone(self.why('fix', 'J4', on_branch={'J4': jv.Branch(row('J4', status='fix'), 1)}))
        self.assertIn('no round to answer', self.why('fix', 'J4', on_branch={'J4': jv.Branch(row('J4', status='fix'), 0)}))
        self.assertEqual(self.why('review', 'J4', on_branch={'J4': row('J4', status='fix')}), 'J4 is fix on job/J4, not review')
        self.assertEqual(self.why('fix', 'J2', set(), {}), 'J2 has no job/J2 branch on origin')

    def test_round_2_review_is_ready_after_a_fix(self):
        # review.md exists on the branch (round 1); the fix session set status=review again: readiness reads only the row
        self.assertIsNone(self.why('review', 'J4', on_branch={'J4': jv.Branch(row('J4', status='review', review='jobs/J4/review.md'), 2)}))

    def test_the_round_cap_is_part_of_readiness(self):
        # J52 review 2: the buttons and --auto must not offer a 4th review that jobs review would refuse
        full = {'J4': jv.Branch(row('J4', status='review', review='jobs/J4/review.md'), 3)}
        self.assertIn('already has 3 rounds', self.why('review', 'J4', on_branch=full))
        page = jv.render_view(LROWS, files(), LBRANCHES, 'now', full)
        self.assertNotIn('data-id="J4"', page)

    def test_id_on_the_command_line(self):
        def wsc(*a):
            return subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(ROOT), 'jobs', *a, '--offline'],
                                  capture_output=True, text=True, timeout=120)
        p = wsc('next', '--id', 'J99')
        self.assertEqual((p.returncode, p.stderr.strip()), (1, 'jobs: J99 is not a row of the jobs registry'))
        self.assertEqual(wsc('review', '--id', 'J99').returncode, 1)


def argv(jid, action, model):
    prompt = {'brief': f'Write the brief for job {jid}: git pull, then run python3 core/wsc.py jobs next --id {jid} and follow it.',
              'build': f'Pick up job {jid}: git pull, then run python3 core/wsc.py jobs next --id {jid} and follow it.',
              'review': f'Review job {jid}: git pull, then run python3 core/wsc.py jobs review --id {jid} and follow docs/REVIEW.md.'}
    return ['claude', '--bg', '--name', f'{jid}-{action}', '--model', model, '--effort', 'medium', prompt[action]]


class Buttons(unittest.TestCase):
    def buttons(self, page):
        return sorted(re.findall(r'data-id="(J\d+)" data-act="(\w+)"', page))

    def test_only_on_launchable_cards(self):
        page = jv.render_view(LROWS, files(), LBRANCHES, 'now', LON_BRANCH)
        self.assertEqual(self.buttons(page), [('J2', 'build'), ('J3', 'brief'), ('J4', 'review')])
        self.assertEqual(self.buttons(jv.render_view(LROWS, files(), LBRANCHES, 'now')), [('J2', 'build'), ('J3', 'brief')])

    def test_copy_mode_and_served_mode(self):
        page = jv.render_view(LROWS, files(), LBRANCHES, 'now', LON_BRANCH, root='/repo')   # POSIX on every host: CI runs on Linux
        self.assertIn('const SERVE = null;', page)
        cmd = html.unescape(re.search(r'data-act="build" data-cmd="([^"]*)"', page).group(1))
        self.assertEqual(cmd, 'cd "/repo"; claude --bg --name J2-build --model opus --effort medium "' + argv('J2', 'build', 'opus')[-1] + '"')
        page = jv.render_view(LROWS, files(), LBRANCHES, 'now', LON_BRANCH, token='tok123')
        self.assertIn('const SERVE = {"token": "tok123"};', page)


class Serve(unittest.TestCase):
    def start(self, agents=lambda: [], dry_run=False, which=lambda n: n):
        self.launched = []
        def launch(a):
            self.launched.append(a)
            return 'abcd1234'
        srv = jv.JobServer(lambda: (LROWS, files(), set(LBRANCHES), LON_BRANCH), agents, launch, which=which, dry_run=dry_run)
        srv.log = False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.srv = srv
        return srv

    def post(self, body, token=None, origin=None, ctype='application/json'):
        s = self.srv
        data = json.dumps({'token': s.token if token is None else token, **body}).encode()
        req = urllib.request.Request(s.url + 'launch', data=data, method='POST',
                                     headers={'Content-Type': ctype, 'Origin': origin or s.url.rstrip('/')})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as x:
            with x:
                return x.code, json.loads(x.read())

    def test_launch_each_action_with_the_exact_argv(self):
        self.start()
        for jid, action, model in (('J2', 'build', 'opus'), ('J3', 'brief', 'sonnet'), ('J4', 'review', 'sonnet')):
            code, j = self.post({'id': jid, 'action': action})
            self.assertEqual(code, 200, j)
            self.assertEqual(j['message'], f'started {jid}-{action}: claude attach abcd1234')
            self.assertEqual(self.launched[-1], argv(jid, action, model))

    def test_page_is_served_with_the_token_only_to_its_own_host(self):
        srv = self.start()
        with urllib.request.urlopen(srv.url, timeout=10) as r:
            self.assertIn(f'"token": "{srv.token}"', r.read().decode())
        req = urllib.request.Request(srv.url, headers={'Host': f'evil.example:{srv.server_address[1]}'})
        with self.assertRaises(urllib.error.HTTPError) as x:
            urllib.request.urlopen(req, timeout=10)
        x.exception.close()
        self.assertEqual(x.exception.code, 403)

    def test_bad_token_foreign_origin_and_form_post_are_refused(self):
        self.start()
        ok = {'id': 'J2', 'action': 'build'}
        self.assertEqual(self.post(ok, token='wrong')[0], 403)
        self.assertEqual(self.post(ok, token='')[0], 403)
        self.assertEqual(self.post(ok, origin='https://evil.example')[0], 403)
        self.assertEqual(self.post(ok, ctype='application/x-www-form-urlencoded')[0], 415)
        self.assertEqual(self.post({'id': 'J99', 'action': 'build'})[0], 400)
        self.assertEqual(self.post({'id': 'J2', 'action': 'rm -rf'})[0], 400)
        self.assertEqual(self.launched, [])

    def test_unready_job_is_409(self):
        self.start()
        for body in ({'id': 'J5', 'action': 'build'}, {'id': 'J2', 'action': 'review'}, {'id': 'J2', 'action': 'brief'}):
            code, j = self.post(body)
            self.assertEqual(code, 409, j)
        self.assertEqual(self.post({'id': 'J5', 'action': 'build'})[1]['message'], 'refused: J5 (queued): waits for J3')
        self.assertEqual(self.launched, [])

    def test_no_count_cap_but_one_session_per_name(self):
        busy = [{'name': n, 'state': 'working'} for n in ('j13 status brief', 'other', 'third')]
        self.start(agents=lambda: busy + [{'name': 'old', 'state': 'done'}])
        self.assertEqual(self.post({'id': 'J2', 'action': 'build'})[0], 200)   # D34: Liam decides how many run at once
        self.srv.agents = lambda: [{'name': 'j2-BUILD', 'state': 'working'}]
        code, j = self.post({'id': 'J2', 'action': 'build'})
        self.assertEqual((code, j['message']), (429, 'refused: J2-build is already running'))
        self.srv.agents = lambda: [{'name': 'J2-build', 'state': 'done'}]   # finished sessions do not count
        self.assertEqual(self.post({'id': 'J2', 'action': 'build'})[0], 200)

    def test_failing_agent_list_or_missing_claude_refuses(self):
        def broken():
            raise ValueError('claude agents --json exited 1')
        self.start(agents=broken)
        code, j = self.post({'id': 'J2', 'action': 'build'})
        self.assertEqual(code, 503)
        self.assertIn('cannot list the running sessions', j['message'])
        self.srv.agents, self.srv.which = (lambda: []), (lambda n: None)
        self.assertEqual(self.post({'id': 'J2', 'action': 'build'})[1]['message'], 'refused: claude is not on PATH')
        self.assertEqual(self.launched, [])

    def test_dry_run_returns_the_argv_without_launching(self):
        self.start(dry_run=True)
        code, j = self.post({'id': 'J3', 'action': 'brief'})
        self.assertEqual((code, j['argv']), (200, argv('J3', 'brief', 'sonnet')))
        self.assertTrue(j['message'].startswith('dry run, would start: claude --bg --name J3-brief'))
        self.assertEqual(self.launched, [])


class StartSession(unittest.TestCase):
    def test_runs_claude_in_the_repo_root(self):
        seen = {}
        def fake_run(argv, **kw):
            seen.update(kw, argv=argv)
            kw['stdout'].write('started 1a2b3c4d' + chr(10))
            return subprocess.CompletedProcess(argv, 0)
        which, run = jv.shutil.which, jv.subprocess.run
        jv.shutil.which, jv.subprocess.run = (lambda n: '/bin/claude'), fake_run
        try:
            sid = jv.start_session(argv('J2', 'build', 'opus'), Path('/repo'))
        finally:
            jv.shutil.which, jv.subprocess.run = which, run
        self.assertEqual((sid, seen['cwd'], seen['argv'][1:]), ('1a2b3c4d', Path('/repo'), argv('J2', 'build', 'opus')[1:]))

class RedPullRequests(unittest.TestCase):
    """J42: next, review and view print open pull requests with a failed check first, from one gh call; --offline skips it."""
    PRS = [{'number': 7, 'headRefName': 'job/J9', 'statusCheckRollup': [
               {'__typename': 'CheckRun', 'name': 'gates', 'conclusion': 'SUCCESS', 'detailsUrl': 'u1'},
               {'__typename': 'CheckRun', 'name': 'harness-windows', 'conclusion': 'FAILURE', 'detailsUrl': 'https://x/runs/1'},
               {'__typename': 'CheckRun', 'name': 'proxy', 'conclusion': None, 'status': 'IN_PROGRESS'}]},
           {'number': 3, 'headRefName': 'brief/J4', 'statusCheckRollup': [
               {'__typename': 'StatusContext', 'context': 'policy', 'state': 'ERROR', 'targetUrl': 'https://x/runs/2'}]},
           {'number': 9, 'headRefName': 'plan/x', 'statusCheckRollup': None}]

    def test_only_failed_checks_are_listed_oldest_pull_request_first(self):
        self.assertEqual(jv.failed_prs(self.PRS), ['PR #3 brief/J4: policy failed, run https://x/runs/2',
                                                   'PR #7 job/J9: harness-windows failed, run https://x/runs/1'])

    def test_offline_makes_no_call(self):
        def boom(*a, **k):
            raise AssertionError('gh was called')
        self.assertEqual(jv.red_prs(ROOT, True, run=boom), [])

    def test_one_gh_call_and_its_failures_become_a_line_not_an_exception(self):
        calls = []

        def fake(argv, **k):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.PRS), '')
        self.assertEqual(len(jv.red_prs(ROOT, False, run=fake)), 2)
        self.assertEqual(len(calls), 1)
        self.assertIn('statusCheckRollup', calls[0][-1])
        down = jv.red_prs(ROOT, False, run=lambda argv, **k: subprocess.CompletedProcess(argv, 1, '', 'not logged in'))
        self.assertEqual(len(down), 1)
        self.assertIn('not logged in', down[0])

        def missing(argv, **k):
            raise FileNotFoundError('gh')
        self.assertIn('could not list', jv.red_prs(ROOT, False, run=missing)[0])

    def test_next_names_the_local_policy_route(self):
        self.assertIn('python3 core/wsc.py policy --branch job/J1 --base origin/main', jv.build_steps(row(status='queued')))


class MainHealth(unittest.TestCase):
    """W22: `jobs next|review|fix|view` print main's CI state first (the latest completed push run of each workflow, its required jobs)."""
    CFG = {**__import__('warscape.repo', fromlist=['DEFAULTS']).DEFAULTS['ci'], 'workflows': ['gates.yml', 'policy.yml'],
           'required_checks': ['gates', 'proxy', 'policy']}
    RUN = {'id': 77, 'html_url': 'https://github.com/o/r/actions/runs/77', 'head_sha': 'abcdef1234567', 'conclusion': 'failure',
           'status': 'completed', 'updated_at': '2026-11-04T08:30:00Z'}

    def gh(self, runs=None, jobs=None, rc=0, err='', raw=None, missing=False):
        calls = []
        runs = {'gates.yml': [self.RUN]} if runs is None else runs
        jobs = [{'name': 'gates', 'conclusion': 'success'}, {'name': 'proxy', 'conclusion': 'failure'}] if jobs is None else jobs

        def fake(argv, **k):
            calls.append(argv)
            if missing:
                raise FileNotFoundError('gh')
            if rc:
                return subprocess.CompletedProcess(argv, rc, '', err)
            path = argv[2]
            if raw is not None:
                return subprocess.CompletedProcess(argv, 0, raw, '')
            if '/workflows/' in path:
                name = path.split('/workflows/')[1].split('/')[0]
                return subprocess.CompletedProcess(argv, 0, json.dumps({'workflow_runs': runs.get(name, [])}), '')
            return subprocess.CompletedProcess(argv, 0, json.dumps({'jobs': jobs}), '')
        return fake, calls

    def test_red_required_jobs_give_one_line_each_with_run_url_and_commit(self):
        fake, calls = self.gh(jobs=[{'name': 'gates', 'conclusion': 'failure'}, {'name': 'proxy', 'conclusion': 'timed_out'},
                                    {'name': 'viewer', 'conclusion': 'failure'}, {'name': 'policy', 'conclusion': 'failure'}])
        lines = jv.main_health(self.CFG, ROOT, False, run=fake)
        self.assertEqual(len(lines), 3)
        for l, job in zip(lines, ('gates', 'proxy', 'policy')):
            self.assertTrue(l.startswith(f'main is RED: {job} failed in run 77 (https://github.com/o/r/actions/runs/77), commit abcdef1, '), l)
            self.assertIn('rerun it or push to main; an issue tracks it', l)
        self.assertIn('2026-11-04', lines[0])
        first = calls[0][2]
        for s in ('actions/workflows/gates.yml/runs', 'branch=main', 'event=push', 'status=completed', 'per_page=1'):
            self.assertIn(s, first)
        self.assertIn('repos/{owner}/{repo}/', first)

    def test_green_gives_no_lines_and_a_workflow_without_a_completed_run_is_skipped(self):
        fake, calls = self.gh(jobs=[{'name': 'gates', 'conclusion': 'success'}, {'name': 'proxy', 'conclusion': 'skipped'}])
        self.assertEqual(jv.main_health(self.CFG, ROOT, False, run=fake), [])
        self.assertEqual(len(calls), 3)   # gates runs, gates jobs, policy runs (none: no jobs call)
        st = jv.main_state(self.CFG, ROOT, False, run=fake)
        self.assertEqual((st['state'], st['runs']), ('green', [77]))

    def test_offline_makes_no_call(self):
        def boom(*a, **k):
            raise AssertionError('gh was called')
        self.assertEqual(jv.main_health(self.CFG, ROOT, True, run=boom), [])
        self.assertEqual(jv.main_state(self.CFG, ROOT, True, run=boom)['state'], 'off')

    def test_every_failure_to_read_is_exactly_one_unknown_line(self):
        cases = {'no gh': dict(missing=True), 'not logged in': dict(rc=1, err='gh auth login required'), 'bad json': dict(raw='not json'),
                 'wrong shape': dict(raw='[]')}
        for why, kw in cases.items():
            fake, _ = self.gh(**kw)
            lines = jv.main_health(self.CFG, ROOT, False, run=fake)
            self.assertEqual(len(lines), 1, why)
            self.assertTrue(lines[0].startswith("(main's CI state is unknown: "), lines[0])
            self.assertTrue(lines[0].endswith('--offline skips this)'), lines[0])
            self.assertEqual(jv.main_state(self.CFG, ROOT, False, run=fake)['state'], 'unknown', why)

    def test_the_latest_completed_run_counts_and_an_in_progress_run_is_not_read(self):
        fake, calls = self.gh()
        jv.main_health(self.CFG, ROOT, False, run=fake)
        self.assertTrue(all('status=completed' in c[2] for c in calls if '/workflows/' in c[2]))
        self.assertTrue(any('/actions/runs/77/jobs' in c[2] for c in calls))

    def print_state(self, fake, **kw):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            st = jv.print_main_health(self.CFG, ROOT, False, run=fake)
        return st, out.getvalue()

    def test_print_red_unknown_and_green(self):
        st, text = self.print_state(self.gh()[0])
        self.assertTrue(text.startswith('Main CI is red (fix or rerun before a merge verdict):\n  main is RED: proxy failed'), text)
        st, text = self.print_state(self.gh(missing=True)[0])
        self.assertTrue(text.startswith("(main's CI state is unknown"), text)
        st, text = self.print_state(self.gh(jobs=[{'name': 'gates', 'conclusion': 'success'}])[0])
        self.assertEqual(text, '')

    def test_the_page_line_is_red_green_or_unknown(self):
        red = jv.main_html(jv.main_state(self.CFG, ROOT, False, run=self.gh()[0]))
        self.assertIn('main is RED: proxy failed', red)
        self.assertIn('warn', red)
        green = jv.main_html(jv.main_state(self.CFG, ROOT, False, run=self.gh(jobs=[{'name': 'gates', 'conclusion': 'success'}])[0]))
        self.assertIn('main CI: green (run 77)', green)
        self.assertIn('unknown', jv.main_html(jv.main_state(self.CFG, ROOT, False, run=self.gh(missing=True)[0])))
        self.assertEqual(jv.main_html(jv.main_state(self.CFG, ROOT, True)), '')
        page = jv.render_view([row('J1', status='queued')], lambda p: None, set(), 'now', main_html=red)
        self.assertIn('main is RED: proxy failed', page)

    def test_the_server_memoises_the_answer_for_a_minute(self):
        calls = []
        clock = [1000.0]

        def line():
            calls.append(1)
            return f'<p>main {len(calls)}</p>'
        srv = jv.JobServer(lambda: ([row('J1', status='queued')], lambda p: None, set(), {}), lambda: [], lambda a: 's', main_line=line,
                           clock=lambda: clock[0])
        try:
            a = srv.page()
            clock[0] += 59
            b = srv.page()
            self.assertEqual(len(calls), 1)
            self.assertIn('main 1', a + b)
            clock[0] += 2
            self.assertIn('main 2', srv.page())
        finally:
            srv.server_close()

    def test_the_lines_print_before_the_pull_request_lines_in_next_and_review(self):
        import contextlib
        import io
        import types
        from warscape.repo import DEFAULTS
        from warscape.verbs import jobs as jverb
        fake, _ = self.gh()
        ctx = types.SimpleNamespace(root=ROOT, config={'registries_dir': 'registries', 'jobs': DEFAULTS['jobs'], 'ci': self.CFG})
        saved = (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health)
        try:
            jv.main_rows = lambda ctx: [row('J60', status='review', title='T')]
            jv.print_red_prs = lambda root, offline: print('PR #1 job/J9: gates failed')
            jv.remote_branches = lambda root, offline: {'job/J60'}
            jv.branch_rows = lambda *a, **k: {'J60': jv.Branch(row('J60', status='review', title='T'), 0, 'abc1234')}
            jv.branch_checks = lambda *a, **k: 'CI line'
            jv.print_main_health = lambda cfg, root, offline: saved[5](cfg, root, offline, run=fake)
            for action in ('next', 'review'):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = jverb.run(types.SimpleNamespace(action=action, id=None, offline=False, auto=False, serve=False, all=False), ctx)
                text = out.getvalue()
                self.assertEqual(rc, 0, action)
                self.assertLess(text.index('Main CI is red'), text.index('PR #1 job/J9'), action)
        finally:
            (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health) = saved


class BranchChecks(unittest.TestCase):
    """J54: `jobs review` and `jobs fix` read the branch head's check runs (one gh api call) and name the red and running ones."""
    SHA = 'abc1234def5678'
    RUNS = [{'name': 'gates', 'status': 'completed', 'conclusion': 'success', 'html_url': 'https://x/g'},
            {'name': 'proxy', 'status': 'completed', 'conclusion': 'skipped', 'html_url': 'https://x/p'},
            {'name': 'viewer', 'status': 'completed', 'conclusion': 'failure', 'html_url': 'https://x/v'},
            {'name': 'harness-windows', 'status': 'in_progress', 'conclusion': None, 'html_url': 'https://x/h'},
            {'name': 'policy', 'status': 'completed', 'conclusion': 'cancelled', 'html_url': 'https://x/c'}]

    def gh(self, payload=None, rc=0, err=''):
        calls = []

        def fake(argv, **k):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, rc, json.dumps({'total_count': len(payload or []), 'check_runs': payload or []}), err)
        return fake, calls

    def test_failed_running_and_cancelled_are_named_with_their_url(self):
        fake, calls = self.gh(self.RUNS)
        out = jv.branch_checks(ROOT, 'job/J60', self.SHA, False, run=fake)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ['gh', 'api'])
        self.assertIn(f'repos/{{owner}}/{{repo}}/commits/{self.SHA}/check-runs', calls[0][2])
        self.assertTrue(out.startswith('CI on job/J60 at abc1234 (a red required check is a blocker'))
        self.assertIn('viewer failed (failure): https://x/v', out)
        self.assertIn('harness-windows still running (in_progress): https://x/h', out)
        self.assertIn('policy did not finish (cancelled): https://x/c', out)
        self.assertNotIn('gates', out.split('\n', 1)[1])
        self.assertNotIn('proxy', out.split('\n', 1)[1])

    def test_all_green_is_one_line(self):
        fake, _ = self.gh(self.RUNS[:2])
        self.assertEqual(jv.branch_checks(ROOT, 'job/J60', self.SHA, False, run=fake),
                         'CI on job/J60 at abc1234: all 2 checks passed or were skipped.')

    def test_no_runs_yet(self):
        fake, _ = self.gh([])
        self.assertIn('no check runs yet', jv.branch_checks(ROOT, 'job/J60', self.SHA, False, run=fake))

    def test_api_error_missing_gh_and_bad_json_are_one_line(self):
        fake, _ = self.gh(rc=1, err='HTTP 404: Not Found')
        out = jv.branch_checks(ROOT, 'job/J60', self.SHA, False, run=fake)
        self.assertIn('could not be read: HTTP 404', out)
        self.assertNotIn('\n', out)

        def missing(argv, **k):
            raise FileNotFoundError('gh')
        self.assertIn('could not be read', jv.branch_checks(ROOT, 'job/J60', self.SHA, False, run=missing))
        junk = jv.branch_checks(ROOT, 'job/J60', self.SHA, False, run=lambda a, **k: subprocess.CompletedProcess(a, 0, 'not json', ''))
        self.assertIn('could not be read', junk)

    def test_offline_and_unknown_head_make_no_call(self):
        def boom(*a, **k):
            raise AssertionError('gh was called')
        self.assertIn('not read: --offline', jv.branch_checks(ROOT, 'job/J60', self.SHA, True, run=boom))
        self.assertIn('head commit is unknown', jv.branch_checks(ROOT, 'job/J60', None, False, run=boom))

    def test_review_and_fix_print_a_red_check_above_their_steps(self):
        """run() prints the CI block, then the steps, for both actions."""
        import contextlib
        import io
        import types
        fake, _ = self.gh(self.RUNS)
        from warscape.repo import DEFAULTS
        from warscape.verbs import jobs as jverb
        ctx = types.SimpleNamespace(root=ROOT, config={'registries_dir': 'registries', 'jobs': DEFAULTS['jobs'], 'ci': DEFAULTS['ci']})
        saved = (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health)
        try:
            jv.main_rows = lambda ctx: [row('J60', status='review', title='T')]
            jv.print_red_prs = lambda root, offline: []
            jv.print_main_health = lambda cfg, root, offline: None
            jv.remote_branches = lambda root, offline: {'job/J60'}
            for action, status, rounds in (('review', 'review', 0), ('fix', 'fix', 1)):
                on = {'J60': jv.Branch(row('J60', status=status, title='T'), rounds, self.SHA)}
                jv.branch_rows = lambda *a, **k: on
                jv.branch_checks = lambda root, b, sha, offline: saved[4](root, b, sha, offline, run=fake)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = jverb.run(types.SimpleNamespace(action=action, id='J60', offline=False, auto=False, serve=False), ctx)
                self.assertEqual(rc, 0, action)
                text = out.getvalue()
                self.assertIn('viewer failed (failure): https://x/v', text, action)
                self.assertLess(text.index('viewer failed'), text.index(f'J60: {action}'), action)
        finally:
            (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health) = saved


def rnd(n, v, jid='J60'):
    return f'## Round {n} (2026-11-0{n}, branch job/{jid} at abc123{n})\n\nfindings\n\n**Verdict: {v}.**\n\n- blocker: x\n\n'


def review_md(*rounds, jid='J60'):
    """review.md text with the given (n, verdict) rounds, in the order given (newest first is the rule)."""
    return f'# {jid} review\n\n' + ''.join(rnd(n, v, jid) for n, v in rounds)


class Rounds(unittest.TestCase):
    """D36 (J52): the round format of review.md and the row agreeing with the newest round."""
    BRIEF60 = BRIEF.replace('J1', 'J60')
    REPORT60 = REPORT.replace('J1', 'J60')

    def errs(self, status, review, report=None, **kw):
        r = row('J60', status=status, brief='jobs/J60/brief.md', report='jobs/J60/report.md', review='jobs/J60/review.md', **kw)
        texts = {'jobs/J60/brief.md': self.BRIEF60, 'jobs/J60/report.md': report or self.REPORT60, 'jobs/J60/review.md': review}
        return jv.problems([r], texts.get, ['J60'])

    def test_good_rounds_pass(self):
        self.assertEqual(self.errs('fix', review_md((1, 'merge after fixes'))), [])
        fixed = self.REPORT60 + '\n## Fix round 1\nfixed x in abc1234\n'
        self.assertEqual(self.errs('review', review_md((1, 'do not merge')), fixed), [])
        self.assertEqual(self.errs('done', review_md((2, 'merge'), (1, 'merge after fixes')), fixed), [])

    def test_round_3_non_merge_requires_blocked(self):
        three = review_md((3, 'merge after fixes'), (2, 'do not merge'), (1, 'merge after fixes'))
        e = self.errs('fix', three)
        self.assertTrue(any('must be blocked with blocked_by="3 review rounds without merge"' in x for x in e), e)
        self.assertEqual(self.errs('blocked', three, blocked_by='3 review rounds without merge'), [])
        self.assertTrue(self.errs('blocked', three, blocked_by='something else'))

    def test_a_fourth_round_fails(self):
        four = review_md((4, 'merge'), (3, 'do not merge'), (2, 'do not merge'), (1, 'do not merge'))
        self.assertTrue(any('4 rounds: at most 3' in x for x in self.errs('done', four)))

    def test_rounds_out_of_order_or_with_a_gap_fail(self):
        for rounds in (((1, 'merge after fixes'), (2, 'merge')), ((3, 'merge'), (1, 'merge after fixes')), ((2, 'merge'),)):
            e = self.errs('done', review_md(*rounds))
            self.assertTrue(any('count up from 1 with no gap, newest first' in x for x in e), (rounds, e))

    def test_a_round_with_two_verdicts_or_none_fails(self):
        two = review_md((1, 'merge')).replace('- blocker: x', '**Verdict: do not merge.**')
        self.assertTrue(any('has 2 verdict lines' in x for x in self.errs('done', two)))
        none = '# J60 review\n\n## Round 1 (2026-11-01, branch job/J60 at abc1231)\n\nno verdict\n'
        self.assertTrue(any('has 0 verdict lines' in x for x in self.errs('fix', none)))
        above = '# J60 review\n\n**Verdict: merge.**\n\n' + rnd(1, 'merge')
        self.assertTrue(any('above the first round' in x for x in self.errs('done', above)))

    def test_undated_heading_or_no_rounds_fail(self):
        e = self.errs('fix', review_md((1, 'merge after fixes')).replace('(2026-11-01, branch job/J60 at abc1231)', '(soon)'))
        self.assertTrue(any('is not "## Round N (YYYY-MM-DD' in x for x in e), e)
        e = self.errs('done', '# J60 review\n\n2026-11-01\n\n**Verdict: merge.**\n')
        self.assertTrue(any('has no "## Round N' in x for x in e), e)

    def test_status_that_disagrees_with_the_newest_verdict_fails(self):
        one = review_md((1, 'merge after fixes'))
        self.assertTrue(any('should be fix' in x for x in self.errs('review', one)))     # no Fix round 1 yet
        fixed = self.REPORT60 + '\n## Fix round 1\nx\n'
        self.assertTrue(any('should be review' in x for x in self.errs('fix', one, fixed)))  # the fix is in: back to review
        self.assertTrue(any('only "merge" makes a job done' in x for x in self.errs('done', one)))
        self.assertTrue(any('should be done' in x for x in self.errs('review', review_md((1, 'merge')))))

    def test_the_legacy_set_is_exempt_from_the_round_rules_only(self):
        jv.S.legacy_rounds = frozenset({'J2'})
        self.addCleanup(setattr, jv.S, 'legacy_rounds', frozenset())
        legacy = REVIEW.replace('J1', 'J2')   # no round heading, as J2's merged review
        r = row('J2', status='done', brief='jobs/J2/brief.md', report='jobs/J2/report.md', review='jobs/J2/review.md')
        texts = {'jobs/J2/brief.md': BRIEF.replace('J1', 'J2'), 'jobs/J2/report.md': REPORT.replace('J1', 'J2'), 'jobs/J2/review.md': legacy}
        self.assertEqual(jv.problems([r], texts.get, ['J2']), [])
        texts['jobs/J2/review.md'] = '# J2 review\n\n**Verdict: merge.**\n'   # the date rule still applies
        self.assertTrue(any('no date' in x for x in jv.problems([r], texts.get, ['J2'])))

class Steps(unittest.TestCase):
    def test_review_steps_name_the_round_and_where_it_goes(self):
        s = jv.review_steps('J60', 0)
        self.assertIn('This is round 1', s)
        self.assertIn('TOP of jobs/J60/review.md', s)
        self.assertIn('status=fix', s)
        s = jv.review_steps('J60', 2)
        self.assertIn('round 3', s)
        self.assertIn('above the earlier rounds', s)
        self.assertIn('blocked_by="3 review rounds without merge"', s)

    def test_fix_steps(self):
        s = jv.fix_steps('J60', 2)
        for want in ('Round 2', '## Fix round 2', 'status=review', 'Never touch review.md', 'never merge',
                     'policy --branch job/J60'):
            self.assertIn(want, s)

    def test_build_and_fix_steps_open_a_draft_pull_request_and_never_merge(self):
        """J54: the pull request exists from review time, as a draft (policy skips drafts); only the reviewer merges."""
        for s in (jv.build_steps(row('J60', status='queued', title='Do it')), jv.fix_steps('J60', 1, 'Do it')):
            self.assertIn('gh pr view job/J60', s)
            self.assertIn('gh pr create --draft --base main --head job/J60 --title "J60: Do it"', s)
            self.assertNotIn('gh pr merge', s)
            self.assertNotIn('gh pr ready', s)

    def test_review_steps_mark_the_pull_request_ready_before_the_push(self):
        """J57: ready before the review commit is pushed, so the pushed head gets a real policy run (a draft's is skipped = passed)."""
        s = jv.review_steps('J60', 0)
        merge_part, other = s.split('otherwise push', 1)
        order = ['policy --branch job/J60', 'gh pr view job/J60', 'gh pr ready job/J60', 'git push', 'gh pr merge job/J60 --auto --squash']
        at = [merge_part.index(x) for x in order]
        self.assertEqual(at, sorted(at))
        self.assertEqual(len(set(at)), len(at))
        self.assertIn('do not push yet', merge_part)
        self.assertIn('leave the draft pull request open (never gh pr ready)', other)
        self.assertNotIn('gh pr ready', other.split('(never gh pr ready)')[1])

    def test_fix_launch_uses_the_row_model(self):
        self.assertEqual(jv.launch_argv('claude', 'J4', 'fix', row('J4', model='opus')),
                         ['claude', '--bg', '--name', 'J4-fix', '--model', 'opus', '--effort', 'medium',
                          'Fix job J4: git pull, then run python3 core/wsc.py jobs fix --id J4 and follow it.'])

    def test_fix_lane_and_button(self):
        on = {'J4': jv.Branch(row('J4', status='fix', model='sonnet'), 1)}
        self.assertEqual(jv.lane(LBY['J4'], LBY, LBRANCHES, on), ('fix', 'fixing on job/J4'))
        page = jv.render_view(LROWS, files(), LBRANCHES, 'now', on)
        self.assertIn('data-id="J4" data-act="fix"', page)
        self.assertNotIn('data-act="review"', page)


class Autopilot(unittest.TestCase):
    """`view --serve --auto` (D36): the loop with fake snapshot, agents and launch seams."""

    def make(self, on_branch, agents=lambda: [], snapshot=None, dry_run=False):
        self.launched, self.state = [], {'on': dict(on_branch)}
        def launch(a):
            self.launched.append(a[3])   # the session name
            return 'abcd1234'
        srv = jv.JobServer(snapshot or (lambda: (LROWS, files(), set(LBRANCHES) | {f'job/{j}' for j in self.state['on']},
                                                 self.state['on'])), agents, launch, which=lambda n: n, dry_run=dry_run)
        srv.log = False
        self.addCleanup(srv.server_close)
        self.lines = []
        srv.auto_log = self.lines.append
        return srv

    def test_starts_a_review_then_after_the_row_turns_fix_a_fix(self):
        srv = self.make({'J4': row('J4', status='review', model='sonnet')})
        self.assertEqual([(j, a, c) for j, a, c, _ in srv.auto_tick()], [('J4', 'review', 200)])
        self.state['on']['J4'] = jv.Branch(row('J4', status='fix', model='sonnet'), 1)
        srv.auto_tick()
        self.assertEqual(self.launched, ['J4-review', 'J4-fix'])
        self.assertTrue(any(l.startswith('J4-fix: started J4-fix') for l in self.lines), self.lines)

    def test_skips_a_job_with_any_of_its_sessions_live(self):
        for state in ('working', 'blocked'):
            srv = self.make({'J4': row('J4', status='review', model='sonnet')}, agents=lambda: [{'name': 'J4-build', 'state': state}])
            self.assertEqual([c for _, _, c, _ in srv.auto_tick()], [429])
            self.assertEqual(self.launched, [])
            self.assertIn('J4-build is still running', self.lines[-1])
        srv = self.make({'J4': row('J4', status='review', model='sonnet')},
                        agents=lambda: [{'name': 'J4-build', 'state': 'done'}, {'name': 'J40-build', 'state': 'working'}])
        srv.auto_tick()
        self.assertEqual(self.launched, ['J4-review'])   # a finished J4 session and another job's session do not count

    def test_a_session_that_ends_without_pushing_is_started_once_per_branch_head(self):
        # J52 review 1: the reviewer ended (state done) and the row still says review; only a push to the branch allows another start
        srv = self.make({'J4': jv.Branch(row('J4', status='review', model='sonnet'), 0, 'aaa111')},
                        agents=lambda: [{'name': 'J4-review', 'state': 'done'}])
        for _ in range(3):
            srv.auto_tick()
        self.assertEqual(self.launched, ['J4-review'])
        self.assertIn('J4-review: started at aaa111, waiting for a push to job/J4', self.lines[-1])
        self.state['on']['J4'] = jv.Branch(row('J4', status='review', model='sonnet'), 0, 'bbb222')
        srv.auto_tick()
        srv.auto_tick()
        self.assertEqual(self.launched, ['J4-review', 'J4-review'])

    def test_a_refused_launch_is_not_remembered(self):
        busy = {'on': True}
        srv = self.make({'J4': jv.Branch(row('J4', status='review', model='sonnet'), 0, 'aaa111')},
                        agents=lambda: [{'name': 'J4-build', 'state': 'working'}] if busy['on'] else [])
        srv.auto_tick()
        busy['on'] = False
        srv.auto_tick()
        self.assertEqual(self.launched, ['J4-review'])   # the build ended; the same head may start now

    def test_never_starts_a_brief_or_a_build(self):
        srv = self.make({})   # J2 is ready to build and J3 to brief (the button fixture), and nothing is on a job branch
        self.assertEqual(srv.auto_tick(), [])
        self.assertEqual(self.launched, [])
        self.assertIn('nothing ready', self.lines[-1])

    def test_a_snapshot_or_agent_list_error_skips_the_tick(self):
        def broken():
            raise ValueError('git ls-remote origin failed')
        srv = self.make({}, snapshot=broken)
        self.assertEqual(srv.auto_tick(), [])
        self.assertIn('tick skipped: cannot read the queue', self.lines[-1])
        def no_agents():
            raise ValueError('claude agents --json exited 1')
        srv = self.make({'J4': row('J4', status='review', model='sonnet')}, agents=no_agents)
        self.assertEqual(srv.auto_tick(), [])
        self.assertIn('tick skipped: cannot list the running sessions', self.lines[-1])
        self.assertEqual(self.launched, [])

    def test_dry_run_logs_and_starts_nothing(self):
        srv = self.make({'J4': jv.Branch(row('J4', status='fix', model='sonnet'), 1)}, dry_run=True)
        srv.auto_tick()
        self.assertEqual(self.launched, [])
        self.assertIn('dry run, would start: claude --bg --name J4-fix', self.lines[-1])

    def test_run_auto_ticks_until_stopped_and_the_page_shows_it(self):
        srv = self.make({'J4': row('J4', status='review', model='sonnet')})
        stop = threading.Event()
        t = threading.Thread(target=srv.run_auto, args=(3600, stop), daemon=True)
        t.start()
        for _ in range(100):
            if self.launched:
                break
            threading.Event().wait(0.05)
        stop.set()
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(self.launched, ['J4-review'])
        self.assertIn('Autopilot on', srv.page())
        self.assertIn(srv.auto['last'], srv.page())

    def test_the_log_file_gets_one_stamped_line(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            srv = jv.JobServer(lambda: ([], files(), set(), {}), lambda: [], lambda a: 'x', log_path=Path(d) / 'sub' / 'jobs_auto.log')
            self.addCleanup(srv.server_close)
            srv.auto_tick()
            lines = (Path(d) / 'sub' / 'jobs_auto.log').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r'^20\d\d-\d\d-\d\d \d\d:\d\d:\d\d UTC jobs auto: tick: nothing ready')


class BranchRows(unittest.TestCase):
    """J56: branch_rows makes one fetch for every job branch, reads done jobs' branches only when asked, and its git calls are counted."""
    REG = 'registries'

    def fake_git(self, files, fetch_rc=0):
        """A recording git: `files` {"<ref>:<path>": text}; heads are a fixed sha per job branch in `files`. Returns (run, calls)."""
        calls = []

        def run(argv, input=None, **k):
            args = argv[3:]   # after git -C <root>
            calls.append(args[0])
            if args[0] == 'fetch':
                calls[-1] = ('fetch', args[-1])
                return subprocess.CompletedProcess(argv, fetch_rc, '', 'fatal: no network' if fetch_rc else '')
            if args[0] == 'for-each-ref':
                jids = sorted({f.split(':')[0].split('/')[-1] for f in files})
                return subprocess.CompletedProcess(argv, 0, ''.join(f'{j} {j.lower()}sha\n' for j in jids), '')
            if args[0] == 'cat-file':
                out = b''
                for spec in input.decode().split():
                    calls.append(('blob', spec))
                    if spec in files:
                        body = files[spec].encode()
                        out += b'0123abcd blob %d\n' % len(body) + body + b'\n'
                    else:
                        out += spec.encode() + b' missing\n'
                return subprocess.CompletedProcess(argv, 0, out, b'')
            raise AssertionError(f'unexpected git {args}')
        return run, calls

    def files(self, *ids, status='review', layout='dir'):
        f = {}
        for j in ids:
            if layout == 'dir':   # J55: one file per row
                f[f'origin/job/{j}:{self.REG}/jobs/{j}.json'] = json.dumps(row(j, status=status), indent=2) + '\n'
                f[f'origin/job/{j}:{self.REG}/jobs/J1.json'] = json.dumps(row('J1', status='done'), indent=2) + '\n'
            else:                 # a branch cut before J55
                f[f'origin/job/{j}:{self.REG}/jobs.jsonl'] = (json.dumps(row(j, status=status)) + '\n'
                                                              + json.dumps(row('J1', status='done')) + '\n')
            f[f'origin/job/{j}:jobs/{j}/review.md'] = review_md((1, 'changes'), jid=j)
        return f

    def test_one_fetch_for_n_branches(self):
        ids = [f'J{n}' for n in range(60, 70)]
        run, calls = self.fake_git(self.files(*ids))
        on = jv.branch_rows(ROOT, {f'job/{j}' for j in ids} | {'brief/J99'}, False, self.REG, run=run)
        self.assertEqual(sorted(on, key=jv.num), ids)
        self.assertEqual([c for c in calls if isinstance(c, tuple) and c[0] == 'fetch'], [('fetch', '+refs/heads/job/*:refs/remotes/origin/job/*')])
        self.assertEqual([c for c in calls if not isinstance(c, tuple)], ['for-each-ref', 'cat-file'])   # 3 git calls for 10 branches
        self.assertEqual(on['J61'], jv.Branch(row('J61', status='review'), 1, 'j61sha'))

    def test_a_branch_from_before_j55_still_reads_its_row(self):
        run, calls = self.fake_git({**self.files('J60'), **self.files('J61', status='fix', layout='jsonl')})
        on = jv.branch_rows(ROOT, {'job/J60', 'job/J61'}, True, self.REG, run=run)
        self.assertEqual((on['J60'].row['status'], on['J61'].row['status']), ('review', 'fix'))
        self.assertEqual([c for c in calls if not isinstance(c, tuple)], ['for-each-ref', 'cat-file'])   # still one batch

    def test_offline_makes_no_fetch(self):
        run, calls = self.fake_git(self.files('J60'))
        on = jv.branch_rows(ROOT, {'job/J60'}, True, self.REG, run=run)
        self.assertEqual(on['J60'].row['status'], 'review')
        self.assertFalse([c for c in calls if isinstance(c, tuple) and c[0] == 'fetch'])

    def test_done_jobs_read_no_blobs_unless_all(self):
        run, calls = self.fake_git(self.files('J60', 'J61'))
        on = jv.branch_rows(ROOT, {'job/J60', 'job/J61'}, False, self.REG, done={'J61'}, run=run)
        self.assertEqual(list(on), ['J60'])
        self.assertFalse([c for c in calls if isinstance(c, tuple) and c[0] == 'blob' and 'J61' in c[1]])
        run, calls = self.fake_git(self.files('J60', 'J61'))   # every branch done: nothing to read, not even a fetch
        self.assertEqual(jv.branch_rows(ROOT, {'job/J60', 'job/J61'}, False, self.REG, done={'J60', 'J61'}, run=run), {})
        self.assertEqual(calls, [])
        run, calls = self.fake_git(self.files('J60', 'J61'))   # --all passes no done set
        self.assertEqual(sorted(jv.branch_rows(ROOT, {'job/J60', 'job/J61'}, False, self.REG, run=run)), ['J60', 'J61'])

    def test_id_of_a_done_job_still_reads_that_branch_only(self):
        run, calls = self.fake_git(self.files('J60', 'J61', status='done'))
        on = jv.branch_rows(ROOT, {'job/J60', 'job/J61'}, False, self.REG, only='J61', done={'J60', 'J61'}, run=run)
        self.assertEqual(list(on), ['J61'])
        self.assertIn(('fetch', '+refs/heads/job/J61:refs/remotes/origin/job/J61'), calls)
        self.assertEqual({c[1].split(':')[0] for c in calls if isinstance(c, tuple) and c[0] == 'blob'}, {'origin/job/J61'})

    def test_a_missing_file_reads_as_none(self):
        f = self.files('J60')
        del f['origin/job/J60:jobs/J60/review.md']
        run, _ = self.fake_git(f)
        self.assertEqual(jv.branch_rows(ROOT, {'job/J60'}, False, self.REG, run=run)['J60'].rounds, 0)

    def test_a_fetch_failure_names_offline(self):
        run, _ = self.fake_git(self.files('J60'), fetch_rc=1)
        with self.assertRaisesRegex(ValueError, '--offline'):
            jv.branch_rows(ROOT, {'job/J60'}, False, self.REG, run=run)

    def test_a_done_job_skipped_on_the_branch_is_refused_as_done(self):
        self.assertEqual(jv.not_ready('review', 'J5', {'J5': row('J5', status='done')}, {'job/J5'}, {}), 'J5 is done on main')

    def test_blobs_reads_a_real_repo(self):
        got = jv._blobs(ROOT, ['HEAD:warscape/jobq.py', 'HEAD:no/such/file'])
        self.assertIn('def branch_rows', got['HEAD:warscape/jobq.py'])
        self.assertIsNone(got['HEAD:no/such/file'])


class ThisRepo(unittest.TestCase):
    def test_the_queue_passes_jobs_check(self):
        p = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(ROOT), 'jobs', 'check'],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == '__main__':
    unittest.main()
