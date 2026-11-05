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
import time
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


class FailedResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name) / 'runs' / 'r1' / 'raw' / 'a'
        d.mkdir(parents=True)
        (d / 'ok.json').write_text('{"status": "ok"}', encoding='utf-8')
        (d / 'bad.json').write_text('{"status": "failed"}', encoding='utf-8')
        (d / 'junk.json').write_text('not json', encoding='utf-8')

    def rep(self, dev, other='', cite='Evidence: runs/r1.'):
        return '\n'.join(['# J1 report: t', '', cite, '', '## Deviations', dev, '', '## Open questions', other, ''])

    def probs(self, text, glob='raw/**/*.json'):
        return jv.failed_results_problems('J1', text, self.tmp.name, glob)

    def test_unnamed_failure_is_one_problem(self):
        e = self.probs(self.rep('none'))
        self.assertEqual(len(e), 1, e)
        self.assertIn('bad.json', e[0])
        self.assertIn('runs/r1', e[0])

    def test_named_by_file_name_or_relative_path(self):
        self.assertEqual(self.probs(self.rep('bad.json failed, expected')), [])
        self.assertEqual(self.probs(self.rep('raw/a/bad.json failed')), [])

    def test_named_only_elsewhere_fails(self):
        self.assertEqual(len(self.probs(self.rep('none', other='bad.json'))), 1)

    def test_citation_followed_by_punctuation(self):
        for cite in ('see runs/r1.', 'see (runs/r1)', 'runs/r1, and more', 'runs/r1.\n', 'runs/r1:'):
            self.assertEqual(len(self.probs(self.rep('none', cite=cite))), 1, cite)

    def test_no_citation_or_rule_off(self):
        self.assertEqual(self.probs(self.rep('none', cite='no folder')), [])
        self.assertEqual(self.probs(self.rep('none'), glob=''), [])
        self.assertEqual(self.probs(self.rep('none', cite='runs/missing')), [])

    def test_problems_calls_it_only_when_configured(self):
        rows = [row(status='review', brief='jobs/J1/brief.md', report='jobs/J1/report.md')]
        read = files(jobs__J1__brief_md=BRIEF, jobs__J1__report_md=self.rep('none'))
        old = jv.S.failed_results, jv.S.root
        self.addCleanup(lambda: setattr(jv.S, 'failed_results', old[0]) or setattr(jv.S, 'root', old[1]))
        jv.S.failed_results, jv.S.root = '', Path(self.tmp.name)
        self.assertEqual(jv.problems(rows, read, ['J1']), [])
        jv.S.failed_results = 'raw/**/*.json'
        e = jv.problems(rows, read, ['J1'])
        self.assertEqual(len(e), 1, e)
        self.assertTrue(e[0].startswith('J1: report: failed ctl result'), e)


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

    def test_serve_page_pins_marked_escapes_raw_html_and_sets_a_csp(self):
        """W28: marked loads only with its SRI hash; raw HTML in a doc reaches the page as escaped text and marked's html renderer escapes it
        again; a CSP allows the one script URL and the page's own inline script and style by hash; the token sits only in the SERVE JSON."""
        import base64
        import hashlib
        evil = BRIEF + '\n<img src=x onerror=alert(1)>\n<script>alert(2)</script>\n'
        page = jv.render_view([row('J1', status='queued', brief='jobs/J1/brief.md')], files(jobs__J1__brief_md=evil), set(), 'now', token='tok123')
        self.assertIn(f'<script src="{jv.MARKED_URL}" integrity="{jv.MARKED_SRI}" crossorigin="anonymous"></script>', page)
        self.assertRegex(jv.MARKED_SRI, r'^sha384-[A-Za-z0-9+/]{64}$')
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', page)
        self.assertNotIn('<img', page)
        self.assertEqual(page.count('<script>'), 1)            # the page's own inline script only; the doc's is text
        self.assertIn("marked.use({ renderer: { html(t) { return esc(typeof t === 'string' ? t : t.text); } } });", page)
        self.assertEqual(page.count('tok123'), 1)
        self.assertIn('const SERVE = {"token": "tok123"};', page)
        csp = html.unescape(re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', page).group(1))
        sha = lambda t: "'sha256-" + base64.b64encode(hashlib.sha256(t.encode('utf-8')).digest()).decode() + "'"
        script = re.search(r'<script>(.*?)</script>', page, re.S).group(1)
        style = re.search(r'<style>(.*?)</style>', page, re.S).group(1)
        self.assertEqual(csp, f"default-src 'none'; script-src {jv.MARKED_URL} {sha(script)}; style-src {sha(style)}; "
                              "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.assertNotEqual(jv.render_view([], files(), set(), 'now', token='other'), page)   # the script hash follows the token


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
        saved = (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health, jv.remote_heads,
                 jv.fetch_main, jv.claim, jv.print_claims, jv.take_claim)
        try:
            jv.print_claims = lambda *a, **k: None   # W27: no claim on the real origin from a test
            jv.take_claim = lambda *a: (True, None)
            jv.main_rows = lambda ctx: [row('J60', status='review', title='T')]
            jv.print_red_prs = lambda root, offline: print('PR #1 job/J9: gates failed')
            jv.remote_branches = lambda root, offline: {'job/J60'}
            jv.remote_heads = lambda root, offline: {'job/J60': 'abc1234'}
            jv.fetch_main = jv.claim = lambda *a, **k: self.fail('next must not reach origin here')
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
            (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health, jv.remote_heads,
             jv.fetch_main, jv.claim, jv.print_claims, jv.take_claim) = saved


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
        saved = (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health, jv.print_claims,
                 jv.take_claim)
        try:
            jv.print_claims = lambda *a, **k: None   # W27: no claim on the real origin from a test
            jv.take_claim = lambda *a: (True, None)
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
            (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health, jv.print_claims,
             jv.take_claim) = saved


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

    def make(self, on_branch, agents=lambda: [], snapshot=None, dry_run=False, ci=lambda sha: ('green', []), prune=lambda: (0, None)):
        self.launched, self.state = [], {'on': dict(on_branch)}
        def launch(a):
            self.launched.append(a[3])   # the session name
            return 'abcd1234'
        srv = jv.JobServer(snapshot or (lambda: (LROWS, files(), set(LBRANCHES) | {f'job/{j}' for j in self.state['on']},
                                                 self.state['on'])), agents, launch, which=lambda n: n, dry_run=dry_run, ci=ci, prune=prune)
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


# ------------------------------------------------------------------ W26: claim, order, needs_pc, CI-gated autopilot
sys.path.insert(0, str(ROOT / 'tests'))
from _util import git as _ugit  # noqa: E402
from warscape.repo import DEFAULTS as _DEFAULTS  # noqa: E402


def tgit(cwd, *args):
    p = _ugit(cwd, *args, check=False)
    if p.returncode:
        raise AssertionError(f'git {" ".join(args)} in {cwd} failed ({p.returncode}):\n{p.stdout}{p.stderr}')
    return p.stdout.strip()


class Claim(unittest.TestCase):
    """`jobs next` claims job/<id> (brief/<id>) with a create-only push of origin/main before it prints the steps (decisions 1-5).
    Real git: a bare temp origin and two clones A and B; nothing here reaches the real origin."""
    ROWS = [row('J1', status='done'), row('J2', status='queued'), row('J3', status='queued'), row('J8')]

    def setUp(self):
        jv.configure_from(_DEFAULTS['jobs'])
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = Path(self._tmp.name).resolve()
        self.origin, self.a, self.b = d / 'origin.git', d / 'a', d / 'b'
        tgit(d, 'init', '-q', '--bare', str(self.origin))
        tgit(d, 'clone', '-q', str(self.origin), str(self.a))
        reg = self.a / 'registries' / 'jobs'
        reg.mkdir(parents=True)
        for r in self.ROWS:
            (reg / f'{r["id"]}.json').write_text(json.dumps(r, indent=2) + '\n', encoding='utf-8', newline='\n')
        tgit(self.a, 'add', '-A')
        tgit(self.a, 'commit', '-q', '-m', 'm1')
        tgit(self.a, 'push', '-q', 'origin', 'main')
        tgit(d, 'clone', '-q', str(self.origin), str(self.b))

    def remote(self, branch):
        p = _ugit(self.origin, 'rev-parse', '--verify', '-q', f'refs/heads/{branch}', check=False)
        return p.stdout.strip() or None

    def main_sha(self):
        return self.remote('main')

    def live(self, clone):
        return lambda: jv.remote_heads(clone, False)

    def stale_once(self, clone, stale=None):
        """A branch read that returns the list from before A's push once, then the real one (B started before A, fetched after)."""
        calls = []
        def read():
            calls.append(1)
            return dict(stale or {}) if len(calls) == 1 else jv.remote_heads(clone, False)
        return read

    def next(self, clone, read=None, rows=None, **kw):
        return jv.next_claim(clone, rows or self.ROWS, read or self.live(clone), **kw)

    def test_a_claims_and_b_moves_on_to_the_next_ready_job(self):
        rc, out = self.next(self.a)
        self.assertEqual(rc, 0, out)
        sha = self.main_sha()
        self.assertIn(f'Claimed: job/J2 now exists on origin at {sha[:7]}', out)
        self.assertIn('git fetch origin job/J2', out)
        self.assertIn('git checkout -b job/J2 origin/job/J2', out)
        self.assertNotIn('push early', out)
        self.assertEqual(self.remote('job/J2'), sha)
        rc, out = self.next(self.b, self.stale_once(self.b))
        self.assertEqual(rc, 0, out)
        self.assertIn('Claimed: job/J3 now exists on origin', out)
        self.assertEqual((self.remote('job/J2'), self.remote('job/J3')), (sha, sha))

    def test_a_brief_is_claimed_on_its_brief_branch(self):
        rows = [row('J1', status='done'), row('J8')]
        rc, out = self.next(self.a, rows=rows)
        self.assertEqual(rc, 0, out)
        self.assertIn('Claimed: brief/J8 now exists on origin', out)
        self.assertIn('git checkout -b brief/J8 origin/brief/J8', out)
        self.assertEqual(self.remote('brief/J8'), self.main_sha())

    def test_a_refused_claim_never_moves_the_existing_branch(self):
        """A plain push would fast-forward an empty claim to a newer main, and --force would overwrite work: both must stay put."""
        self.assertEqual(self.next(self.a, rows=self.ROWS[:2])[0], 0)
        first = self.remote('job/J2')
        tgit(self.a, 'commit', '-q', '--allow-empty', '-m', 'm2')
        tgit(self.a, 'push', '-q', 'origin', 'main')   # main moves on: B's origin/main is now a descendant of the claim
        rc, out = self.next(self.b, lambda: {}, rows=self.ROWS[:2])
        self.assertEqual(self.remote('job/J2'), first, out)
        self.assertEqual(rc, 0)
        self.assertIn('Nothing is ready', out)
        self.assertIn('J2', out)
        tgit(self.a, 'fetch', '-q', 'origin')
        tgit(self.a, 'checkout', '-q', '-b', 'job/J2', 'origin/job/J2')
        tgit(self.a, 'commit', '-q', '--allow-empty', '-m', 'work')
        tgit(self.a, 'push', '-q', 'origin', 'job/J2')
        work = self.remote('job/J2')
        self.next(self.b, lambda: {}, rows=self.ROWS[:2])
        self.assertEqual(self.remote('job/J2'), work)

    def test_every_candidate_refused_is_nothing_ready_naming_them(self):
        for j in ('J2', 'J3'):
            tgit(self.a, 'push', '-q', 'origin', f'main:refs/heads/job/{j}')
        rc, out = self.next(self.b, lambda: {}, rows=self.ROWS[:3])   # a read that never sees the claims
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith('Nothing is ready'), out)
        self.assertIn('another session claimed J2, J3', out)

    def test_at_most_five_attempts(self):
        rows = [row('J1', status='done')] + [row(f'J{n}', status='queued') for n in range(2, 9)]
        for r in rows[1:]:
            tgit(self.a, 'push', '-q', 'origin', f'main:refs/heads/job/{r["id"]}')
        tried = []
        def counting(root, branch, run=subprocess.run):
            tried.append(branch)
            return jv.claim(root, branch, run)
        rc, out = self.next(self.b, lambda: {}, rows=rows, claim_fn=counting)
        self.assertEqual(tried, [f'job/J{n}' for n in range(2, 7)])
        self.assertIn('another session claimed J2, J3, J4, J5, J6', out)
        self.assertIn('5 attempts', out)

    def test_a_failure_that_is_not_a_race_exits_1_and_claims_nothing(self):
        tgit(self.b, 'remote', 'set-url', '--push', 'origin', str(Path(self._tmp.name) / 'missing.git'))
        rc, out = self.next(self.b)
        self.assertEqual(rc, 1, out)
        self.assertNotIn('Claimed', out)
        self.assertNotIn('Take it', out)
        self.assertIsNone(self.remote('job/J2'))
        self.assertIsNone(self.remote('job/J3'))   # it did not move on as if it had lost a race
        tgit(self.b, 'remote', 'remove', 'origin')   # no origin at all
        rc, out = self.next(self.b, lambda: {})
        self.assertEqual(rc, 1, out)
        self.assertIsNone(self.remote('job/J2'))

    def test_peek_offline_and_view_push_nothing(self):
        rc, out = self.next(self.a, peek=True)
        self.assertEqual(rc, 0)
        self.assertIn('not claimed: --peek', out)
        self.assertIn('git push origin --force-with-lease=refs/heads/job/J2: origin/main:refs/heads/job/J2', out)
        rc, out = self.next(self.a, offline=True)
        self.assertIn('(not claimed: --offline)', out)
        jv.render_view(self.ROWS, files(), set(), 'now')
        self.assertIsNone(self.remote('job/J2'))
        self.assertEqual(tgit(self.origin, 'for-each-ref', 'refs/heads/job/', 'refs/heads/brief/'), '')

    def test_id_claims_and_a_claimed_id_is_in_progress(self):
        rc, out = self.next(self.a, jid='J3')
        self.assertEqual(rc, 0, out)
        self.assertIn('Claimed: job/J3', out)
        rc, out = self.next(self.b, self.stale_once(self.b), jid='J3')
        self.assertEqual(rc, 1)
        self.assertIn('in progress', out)
        rc, out = self.next(self.b, jid='J3')
        self.assertEqual(rc, 1)
        self.assertIn('J3 (queued): in progress on job/J3', out)

    def test_the_claim_pushes_origin_main_not_head(self):
        tgit(self.a, 'commit', '-q', '--allow-empty', '-m', 'local only')
        head = tgit(self.a, 'rev-parse', 'HEAD')
        self.assertEqual(self.next(self.a)[0], 0)
        self.assertEqual(self.remote('job/J2'), self.main_sha())
        self.assertNotEqual(self.remote('job/J2'), head)

    def test_a_claimed_empty_branch_is_in_progress_and_nothing_to_review(self):
        self.next(self.a)
        heads = jv.remote_heads(self.b, False)
        by = {r['id']: r for r in self.ROWS}
        self.assertEqual(jv.not_ready('build', 'J2', by, set(heads)), 'J2 (queued): in progress on job/J2')
        self.assertEqual(jv.pick_next(self.ROWS, set(heads))[1]['id'], 'J3')
        on = jv.branch_rows(self.b, set(heads), False, 'registries')
        self.assertEqual(on['J2'].row['status'], 'queued')
        self.assertIsNone(jv.pick_branch('review', on))
        self.assertIn('no report yet', jv.not_ready('review', 'J2', by, set(heads), on))
        self.assertEqual(jv.lane(by['J2'], by, set(heads), on)[0], 'progress')

    def test_a_stale_claim_is_listed_after_24_hours_and_only_when_empty(self):
        self.next(self.a)                 # job/J2: an empty claim
        self.next(self.a)                 # job/J3: gets a commit of its own
        tgit(self.a, 'fetch', '-q', 'origin')
        tgit(self.a, 'checkout', '-q', '-b', 'job/J3', 'origin/job/J3')
        tgit(self.a, 'commit', '-q', '--allow-empty', '-m', 'work')
        tgit(self.a, 'push', '-q', 'origin', 'job/J3')
        tgit(self.b, 'fetch', '-q', 'origin')
        heads = jv.remote_heads(self.b, False)
        when = int(tgit(self.b, 'log', '-1', '--format=%ct', 'origin/main'))
        self.assertEqual(jv.empty_claims(self.b, self.ROWS, heads, now=when + 23 * 3600), [])
        lines = jv.empty_claims(self.b, self.ROWS, heads, now=when + 50 * 3600)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith('J2: claimed 2 d ago or less'), lines)
        self.assertIn('nothing pushed; `git push origin --delete job/J2` releases it', lines[0])
        rc, out = self.next(self.b, now=when + 50 * 3600, peek=True)
        self.assertIn('J2: claimed', out)


class Order(unittest.TestCase):
    def test_phase_then_number(self):
        self.assertEqual(jv.pick_next([row('J1', status='queued', phase=2), row('J5', status='queued', phase=1)], set())[1]['id'], 'J5')

    def test_an_absent_phase_sorts_last(self):
        r = row('J1', status='queued')
        del r['phase']
        self.assertEqual(jv.pick_next([r, row('J9', status='queued', phase=3)], set())[1]['id'], 'J9')
        self.assertEqual(jv.pick_next([row('J1', phase=2), row('J4', phase=1)], set())[1]['id'], 'J4')   # briefs too, after builds

    def test_dependencies_still_block_a_lower_phase(self):
        rows = [row('J1', status='queued', phase=1, depends_on=['J7']), row('J5', status='queued', phase=2), row('J7', status='queued', phase=3)]
        self.assertEqual(jv.pick_next(rows, set())[1]['id'], 'J5')


class NeedsPc(unittest.TestCase):
    """Decision 7: `[jobs] pc_state` and `WSC_PC_STATE` gate a needs_pc build where the PC state folder is absent."""
    ROWS = [row('J1', status='done'), row('J2', status='queued', needs_pc=True), row('J3', status='queued')]

    def setUp(self):
        import os
        from unittest import mock
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.missing = self.dir / 'no_state'
        env = mock.patch.dict('os.environ')
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('WSC_PC_STATE', None)
        self.addCleanup(jv.configure_from, _DEFAULTS['jobs'])

    def cfg(self, pc_state):
        jv.configure_from({**_DEFAULTS['jobs'], 'pc_state': pc_state})

    def picked(self):
        return jv.pick_next(self.ROWS, set())[1]['id']

    def test_unset_is_unchanged(self):
        self.cfg('')
        self.assertEqual(self.picked(), 'J2')

    def test_a_missing_folder_skips_the_row_with_the_reason(self):
        self.cfg(str(self.missing))
        by = {r['id']: r for r in self.ROWS}
        self.assertEqual(jv.not_ready('build', 'J2', by, set()), f'J2 needs the PC ({self.missing} is absent here)')
        self.assertEqual(self.picked(), 'J3')
        self.assertEqual(jv.lane(by['J2'], by, set()), ('waiting', f'J2 needs the PC ({self.missing} is absent here)'))
        self.assertIsNone(jv.not_ready('brief', 'J4', {**by, 'J4': row('J4', needs_pc=True)}, set()))   # a brief is written anywhere

    def test_an_existing_folder_is_picked_and_vars_expand(self):
        import os
        self.cfg(str(self.dir))
        self.assertEqual(self.picked(), 'J2')
        os.environ['WSC_TEST_STATE'] = str(self.dir)
        self.cfg('$WSC_TEST_STATE')
        self.assertEqual(self.picked(), 'J2')

    def test_the_environment_beats_the_key(self):
        import os
        self.cfg(str(self.dir))
        os.environ['WSC_PC_STATE'] = ''
        self.assertEqual(self.picked(), 'J3')
        self.assertIn('no PC here', jv.not_ready('build', 'J2', {r['id']: r for r in self.ROWS}, set()))
        self.cfg('')
        os.environ['WSC_PC_STATE'] = str(self.missing)
        self.assertEqual(self.picked(), 'J3')
        os.environ['WSC_PC_STATE'] = str(self.dir)
        self.assertEqual(self.picked(), 'J2')

    def test_review_and_fix_are_not_gated(self):
        self.cfg(str(self.missing))
        by = {r['id']: r for r in self.ROWS}
        self.assertIsNone(jv.not_ready('review', 'J2', by, {'job/J2'}, {'J2': row('J2', status='review', needs_pc=True)}))
        self.assertIsNone(jv.not_ready('fix', 'J2', by, {'job/J2'}, {'J2': jv.Branch(row('J2', status='fix', needs_pc=True), 1)}))


class BranchCi(unittest.TestCase):
    """Decision 11: one read of a head's check runs, as a state."""
    def ci(self, runs, rc=0):
        return jv.branch_ci(ROOT, 'abc1234def', False, run=lambda a, **k: subprocess.CompletedProcess(
            a, rc, json.dumps({'check_runs': runs}), 'HTTP 502' if rc else ''))[0]

    def test_states(self):
        ok = {'name': 'gates', 'status': 'completed', 'conclusion': 'success'}
        self.assertEqual(self.ci([ok, {'name': 'policy', 'status': 'completed', 'conclusion': 'skipped'},
                                  {'name': 'x', 'status': 'completed', 'conclusion': 'neutral'}]), 'green')
        self.assertEqual(self.ci([{'name': 'policy', 'status': 'completed', 'conclusion': 'skipped'}]), 'green')
        self.assertEqual(self.ci([ok, {'name': 'proxy', 'status': 'completed', 'conclusion': 'failure'}]), 'red')
        self.assertEqual(self.ci([ok, {'name': 'proxy', 'status': 'completed', 'conclusion': 'cancelled'}]), 'red')
        self.assertEqual(self.ci([ok, {'name': 'proxy', 'status': 'queued', 'conclusion': None}]), 'running')
        self.assertEqual(self.ci([{'name': 'a', 'status': 'completed', 'conclusion': 'failure'}, {'name': 'b', 'status': 'in_progress'}]), 'running')
        self.assertEqual(self.ci([]), 'none')
        self.assertEqual(self.ci([ok], rc=1), 'unknown')
        self.assertEqual(jv.branch_ci(ROOT, 'abc', True, run=None)[0], 'unknown')
        self.assertEqual(jv.branch_ci(ROOT, None, False, run=None)[0], 'unknown')


class AutopilotGates(unittest.TestCase):
    """Decisions 11-13: review waits for green CI, fix for CI to finish; one needs_pc row at a time; the tick prunes."""
    make = Autopilot.make

    def ci_of(self, states):
        self.ci_calls = []
        def ci(sha):
            self.ci_calls.append(sha)
            return (states[sha] if isinstance(states, dict) else states), []
        return ci

    def test_review_starts_only_on_green_and_logs_a_deferral_once_per_head(self):
        for state in ('red', 'running', 'none', 'unknown'):
            srv = self.make({'J4': jv.Branch(row('J4', status='review', model='sonnet'), 0, 'aaa1111bbb')}, ci=self.ci_of(state))
            srv.auto_tick()
            srv.auto_tick()
            self.assertEqual(self.launched, [], state)
            self.assertEqual([l for l in self.lines if 'deferred' in l], [f'J4-review: deferred, CI {state} at aaa1111'], state)
            self.assertNotIn(('J4', 'review'), srv.started)
        srv = self.make({'J4': jv.Branch(row('J4', status='review', model='sonnet'), 0, 'aaa1111bbb')}, ci=self.ci_of('green'))
        srv.auto_tick()
        self.assertEqual(self.launched, ['J4-review'])

    def test_a_deferral_does_not_set_started_so_green_later_starts(self):
        states = {'aaa1111bbb': 'red'}
        srv = self.make({'J4': jv.Branch(row('J4', status='review', model='sonnet'), 0, 'aaa1111bbb')}, ci=self.ci_of(states))
        srv.auto_tick()
        states['aaa1111bbb'] = 'green'
        srv.auto_tick()
        self.assertEqual(self.launched, ['J4-review'])
        srv.auto_tick()   # started at this head: no further CI read for it
        self.assertEqual(len(self.ci_calls), 2)

    def test_fix_defers_only_while_ci_has_not_finished(self):
        for state, started in (('running', []), ('none', []), ('red', ['J4-fix']), ('green', ['J4-fix']), ('unknown', ['J4-fix'])):
            srv = self.make({'J4': jv.Branch(row('J4', status='fix', model='sonnet'), 1, 'ccc2222ddd')}, ci=self.ci_of(state))
            srv.auto_tick()
            self.assertEqual(self.launched, started, state)

    def pc_snapshot(self, on):
        rows = [dict(r, needs_pc=True) if r['id'] == 'J4' else r for r in LROWS]
        rows += [row('J6', status='queued', needs_pc=True), row('J7', status='queued', needs_pc=True), row('J8', status='queued')]
        return lambda: (rows, files(), {f'job/{j}' for j in on}, on)

    def test_one_needs_pc_row_at_a_time(self):
        on = {j: jv.Branch(row(j, status='review'), 0, f'{j.lower()}head') for j in ('J4', 'J6', 'J8')}
        srv = self.make({}, snapshot=self.pc_snapshot(on))
        srv.auto_tick()
        self.assertEqual(self.launched, ['J4-review', 'J8-review'])   # J6 needs the PC too, J8 does not
        self.assertIn('J6-review: deferred, J4 holds the PC', self.lines)

    def test_a_live_session_of_another_pc_row_defers_and_a_non_pc_one_does_not(self):
        on = {'J6': jv.Branch(row('J6', status='review'), 0, 'j6head')}
        srv = self.make({}, snapshot=self.pc_snapshot(on), agents=lambda: [{'name': 'J7-build', 'state': 'working'}])
        srv.auto_tick()
        self.assertEqual(self.launched, [])
        self.assertIn('J6-review: deferred, J7 holds the PC', self.lines)
        srv = self.make({}, snapshot=self.pc_snapshot(on), agents=lambda: [{'name': 'J8-build', 'state': 'working'},
                                                                           {'name': 'J7-review', 'state': 'done'}])
        srv.auto_tick()
        self.assertEqual(self.launched, ['J6-review'])

    def test_the_tick_prunes_once_logs_a_removal_and_survives_a_failure(self):
        calls = []
        def prune(result):
            def f():
                calls.append(1)
                if isinstance(result, Exception):
                    raise result
                return result
            return f
        srv = self.make({}, prune=prune((0, None)))
        srv.auto_tick()
        self.assertEqual(len(calls), 1)
        self.assertFalse([l for l in self.lines if 'prune' in l])
        srv = self.make({}, prune=prune((2, None)))
        srv.auto_tick()
        self.assertIn('pruned 2 dead worktree registrations', self.lines)
        for bad in ((0, 'fatal: not a git repository'), OSError('no git')):
            srv = self.make({}, prune=prune(bad))
            srv.auto_tick()
            self.assertTrue(any(l.startswith('worktree prune failed') for l in self.lines), self.lines)
            self.assertIn('nothing ready', self.lines[-1])
        calls.clear()
        srv = self.make({}, prune=prune((5, None)), dry_run=True)
        srv.auto_tick()
        self.assertEqual(calls, [])
        self.assertIn('would prune dead worktree registrations', self.lines)


class Handback(unittest.TestCase):
    """W27 (R10): a report beside jobs/<id>/handback.md says what the orchestrator added."""
    ROW = dict(status='review', brief='jobs/J1/brief.md', report='jobs/J1/report.md')

    def errs(self, report, handback):
        read = files(jobs__J1__brief_md=BRIEF, jobs__J1__report_md=report, jobs__J1__handback_md=handback)
        return jv.problems([row(**self.ROW)], read, ['J1'])

    def test_a_handback_without_orchestrator_additions_fails(self):
        e = self.errs(REPORT, 'The builder said this.\n')
        self.assertIn('J1: report.md sits beside a handback: say what the orchestrator added (a "## Orchestrator additions" section)', e)

    def test_with_the_section_or_without_a_handback_it_passes(self):
        self.assertEqual(self.errs(REPORT + '\n## Orchestrator additions\nNone.\n', 'words\n'), [])
        self.assertEqual(self.errs(REPORT, None), [])

    def test_review_and_fix_steps_name_the_handback(self):
        self.assertIn('jobs/J1/handback.md', jv.review_steps('J1', 0, handback=True))
        self.assertNotIn('handback', jv.review_steps('J1', 0))
        self.assertIn('jobs/J1/handback.md', jv.fix_steps('J1', 1, handback=True))


def _g(cwd, *args, check=True, env=None):
    import os
    e = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t', **(env or {})}
    return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', '-c', 'init.defaultBranch=main', *args],
                          cwd=cwd, env=e, check=check, capture_output=True, text=True)


class ReviewClaim(unittest.TestCase):
    """W27 (R7): `refs/claims/<id>/round-<n>` on origin; git refuses a second creator, so the push is the lock. Real git, a bare temp origin."""

    def setUp(self):
        from warscape import claims
        self.claims = claims
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        t = Path(self._tmp.name).resolve()
        self.origin = t / 'origin.git'
        _g(t, 'init', '-q', '--bare', str(self.origin))
        seed = t / 'seed'
        _g(t, 'init', '-q', '-b', 'main', str(seed))
        (seed / 'a.txt').write_text('a\n', encoding='utf-8')
        _g(seed, 'add', '-A')
        _g(seed, 'commit', '-q', '-m', 'seed')
        _g(seed, 'push', '-q', str(self.origin), 'main:main', 'main:job/J1')
        self.a, self.b = t / 'a', t / 'b'
        for c in (self.a, self.b):
            _g(t, 'clone', '-q', str(self.origin), str(c))
        self.head = _g(self.a, 'rev-parse', 'origin/job/J1').stdout.strip()

    def test_the_first_claimer_wins_and_the_second_is_refused_naming_the_first(self):
        ok, c = self.claims.take(self.a, 'J1', 1, self.head, 'J1-review-A')
        self.assertTrue(ok)
        self.assertEqual((c.jid, c.round, c.session), ('J1', 1, 'J1-review-A'))
        ok2, c2 = self.claims.take(self.b, 'J1', 1, self.head, 'J1-review-B')
        self.assertFalse(ok2)
        self.assertEqual(c2.session, 'J1-review-A')
        got = _g(self.a, 'ls-remote', str(self.origin), 'refs/claims/*').stdout.split()
        self.assertEqual(got[1::2], ['refs/claims/J1/round-1'])
        self.assertTrue(self.claims.take(self.a, 'J1', 1, self.head, 'J1-review-A')[0])   # the holder asking again keeps it

    def test_a_stale_claim_is_taken_over(self):
        old = int(time.time()) - 5 * 3600
        self.assertTrue(self.claims.take(self.a, 'J1', 1, self.head, 'old-session', now=old)[0])
        ok, c = self.claims.take(self.b, 'J1', 1, self.head, 'new-session', hours=4)
        self.assertTrue(ok)
        self.assertEqual(self.claims.read(self.a)[0].session, 'new-session')

    def test_a_round_the_branch_already_has_releases_the_claim(self):
        self.claims.take(self.a, 'J1', 1, self.head, 'S')
        self.claims.take(self.a, 'J1', 2, self.head, 'S')
        gone = self.claims.release(self.b, self.claims.read(self.b), {'J1': 1}, {'job/J1'})
        self.assertEqual([(c.jid, c.round) for c in gone], [('J1', 1)])
        self.assertEqual([(c.jid, c.round) for c in self.claims.read(self.a)], [('J1', 2)])

    def test_an_unreadable_remote_refuses(self):
        _g(self.b, 'remote', 'set-url', 'origin', str(self.origin) + '-missing')
        with self.assertRaises(self.claims.ClaimError):
            self.claims.take(self.b, 'J1', 1, self.head, 'S')
        with self.assertRaises(self.claims.ClaimError):
            self.claims.read(self.b)

    def test_two_jobs_review_runs_leave_one_winner(self):
        import contextlib
        import io
        import types
        from warscape.repo import DEFAULTS
        from warscape.verbs import jobs as jverb
        r = row('J1', status='review', title='T', brief='jobs/J1/brief.md', report='jobs/J1/report.md')
        saved = (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health)
        res = []
        try:
            jv.main_rows = lambda ctx: [r]
            jv.print_red_prs = lambda root, offline: None
            jv.remote_branches = lambda root, offline: {'job/J1'}
            jv.branch_rows = lambda *a, **k: {'J1': jv.Branch(r, 0, self.head)}
            jv.branch_checks = lambda *a, **k: ''
            jv.print_main_health = lambda cfg, root, offline: None
            for clone, who in ((self.a, 'first-session'), (self.b, 'second-session')):
                ctx = types.SimpleNamespace(root=clone, config={'registries_dir': 'registries', 'jobs': DEFAULTS['jobs'], 'ci': DEFAULTS['ci']})
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    rc = jverb.run(types.SimpleNamespace(action='review', id='J1', offline=False, auto=False, serve=False, all=False,
                                                         session=who), ctx)
                res.append((rc, out.getvalue()))
        finally:
            (jv.main_rows, jv.print_red_prs, jv.remote_branches, jv.branch_rows, jv.branch_checks, jv.print_main_health) = saved
        self.assertEqual(res[0][0], 0, res[0][1])
        self.assertIn('Claimed round 1 of J1 (refs/claims/J1/round-1) for first-session', res[0][1])
        self.assertEqual(res[1][0], 1, res[1][1])
        self.assertIn('round 1 of J1 is claimed by first-session', res[1][1])
        self.assertNotIn('review branch job/J1', res[1][1])

    def test_the_server_returns_409_for_a_claimed_round(self):
        held = self.claims.Claim('J4', 1, 'f' * 40, 'J4-review-elsewhere', int(time.time()))
        srv = jv.JobServer(lambda: (LROWS, files(), set(LBRANCHES), LON_BRANCH), lambda: [], lambda a: 'sid', which=lambda n: n,
                           claim=lambda jid, n, head, session: (False, held))
        self.addCleanup(srv.server_close)
        code, msg, _ = srv.start('J4', 'review', {r['id']: r for r in LROWS}, set(LBRANCHES), LON_BRANCH)
        self.assertEqual(code, 409, msg)
        self.assertIn('round 1 of J4 is claimed by J4-review-elsewhere', msg)

    def test_the_server_fails_closed_when_the_claim_cannot_be_read(self):
        def boom(*a):
            raise self.claims.ClaimError('git ls-remote origin failed')
        srv = jv.JobServer(lambda: (LROWS, files(), set(LBRANCHES), LON_BRANCH), lambda: [], lambda a: 'sid', which=lambda n: n, claim=boom)
        self.addCleanup(srv.server_close)
        code, msg, _ = srv.start('J4', 'review', {r['id']: r for r in LROWS}, set(LBRANCHES), LON_BRANCH)
        self.assertEqual(code, 503, msg)


class NextWithReviewClaims(unittest.TestCase):
    """W26 and W27 together: `next` lists the review claims, then claims the job; `--peek` releases no claim."""

    def run_next(self, **flags):
        import contextlib
        import io
        import types
        from unittest import mock
        from warscape.repo import DEFAULTS
        from warscape.verbs import jobs as jverb
        calls = []
        ctx = types.SimpleNamespace(root=ROOT, config={'registries_dir': 'registries', 'jobs': DEFAULTS['jobs'], 'ci': {}})
        args = types.SimpleNamespace(action='next', id=None, offline=False, auto=False, serve=False, all=False, **flags)
        with mock.patch.multiple(jv, main_rows=lambda ctx: [row('J60', status='queued', title='T')], print_red_prs=lambda *a: None,
                                 print_main_health=lambda *a: None, remote_branches=lambda *a: {'job/J9'},
                                 print_claims=lambda root, offline, branches, release=False: calls.append(('claims', branches, release)),
                                 next_claim=lambda *a, **k: (calls.append(('next', k['peek'])), (0, 'steps'))[1]):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rc = jverb.run(args, ctx)
        self.assertEqual((rc, out.getvalue().strip()), (0, 'steps'))
        return calls

    def test_the_claims_are_listed_and_released_before_the_job_is_claimed(self):
        self.assertEqual(self.run_next(), [('claims', {'job/J9'}, True), ('next', False)])

    def test_peek_releases_nothing(self):
        self.assertEqual(self.run_next(peek=True), [('claims', {'job/J9'}, False), ('next', True)])


class UsageRule(unittest.TestCase):
    """W31: `problems` calls usage_problems; a queue below `usage_from` is untouched."""
    LINE = 'Usage: 90 tool calls; models: opus; 1 session, by hand\n\n'

    def setUp(self):
        keep = getattr(jv.S, 'usage_from', 0)
        jv.S.usage_from = 2
        self.addCleanup(setattr, jv.S, 'usage_from', keep)

    def errs(self, jid, report, **kw):
        r = row(jid, status='review', brief=f'jobs/{jid}/brief.md', report=f'jobs/{jid}/report.md', **kw)
        docs = {f'jobs/{jid}/brief.md': BRIEF.replace('J1', jid), f'jobs/{jid}/report.md': None if report is None else report.replace('J1', jid)}
        return jv.problems([r], docs.get)

    def test_a_report_with_the_line_passes(self):
        self.assertEqual(self.errs('J2', REPORT.replace('## What exists', self.LINE + '## What exists')), [])

    def test_a_report_without_it_fails_with_the_job_and_the_file_named(self):
        (e,) = self.errs('J2', REPORT)
        self.assertTrue(e.startswith('J2: report: no "Usage:'), e)

    def test_a_row_with_no_report_file_gets_the_old_error_only(self):
        self.assertEqual(self.errs('J2', None), ['J2: report=jobs/J2/report.md but the file does not exist'])

    def test_a_done_row_below_usage_from_is_untouched(self):
        r = row('J1', status='done', brief='jobs/J1/brief.md', report='jobs/J1/report.md', review='jobs/J1/review.md')
        self.assertEqual(jv.problems([r], files(jobs__J1__brief_md=BRIEF, jobs__J1__report_md=REPORT, jobs__J1__review_md=REVIEW)), [])

    def test_default_off_changes_nothing(self):
        jv.S.usage_from = 0
        self.assertEqual(self.errs('J2', REPORT), [])


class ThisRepo(unittest.TestCase):
    def test_the_queue_passes_jobs_check(self):
        p = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(ROOT), 'jobs', 'check'],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == '__main__':
    unittest.main()
