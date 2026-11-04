"""Host tests for warscape/policy.py (`wsc policy`): the pure logic, then the verb on a fixture git repository (the session trailer check).

Moved from napoleon-remastered tests/test_pr_policy.py (napoleon J62); rule 79 and the core-pin cases stayed there with the hook module."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WSC = ROOT / 'wsc.py'
sys.path.insert(0, str(ROOT))
from warscape import policy as pp  # noqa: E402
from warscape.repo import DEFAULTS, Ctx  # noqa: E402

CFG = pp.settings({**DEFAULTS, 'policy': {**DEFAULTS['policy'], 'decisions': 'docs/DECISIONS.md'}})


def check(*a, **k):
    k.setdefault('cfg', CFG)
    return pp.check(*a, **k)

ROW = {'id': 'J1', 'status': 'queued', 'brief': 'jobs/J1/brief.md'}
OTHER = {'id': 'J2', 'status': 'needs_brief'}


def files(**kw):
    return lambda p: kw.get(p)


def pp_rows_at(cwd, ref):
    """pr_policy.rows_at runs git in the current folder (as CI does, from the repo root)."""
    import os
    old = os.getcwd()
    os.chdir(cwd)
    try:
        return pp.rows_at(ref, CFG)
    finally:
        os.chdir(old)


class Policy(unittest.TestCase):
    def run_check(self, branch, changed, base_rows=None, head_rows=None, base=None, head=None):
        return check(branch, changed, base_rows or {'J1': ROW, 'J2': OTHER}, head_rows or {'J1': ROW, 'J2': OTHER},
                        base or files(), head or files())

    def test_a_bootstrap_branch_skips_the_kind_rules_but_not_the_decisions_or_the_hooks(self):
        boot = {**CFG, 'bootstrap': ['pipeline-0.9.0']}
        files_changed = ['warscape/jobq.py', 'docs/DECISIONS.md', 'proxy/x.cpp']
        # an ordinary branch of that name is refused, the listed one is not
        self.assertTrue(pp.check('pipeline-0.9.0', files_changed[:1], {}, {}, files(), files(), cfg=CFG))
        self.assertEqual(pp.check('pipeline-0.9.0', files_changed[:1], {}, {}, files(), files(), cfg=boot), [])
        self.assertTrue(pp.check('pipeline-0.9.1', files_changed[:1], {}, {}, files(), files(), cfg=boot))   # exact names only
        base = '| D1 | 2026-10-28 | Liam | A. | yes |\n'
        e = pp.check('pipeline-0.9.0', ['docs/DECISIONS.md'], {}, {}, files(**{'docs/DECISIONS.md': base}),
                     files(**{'docs/DECISIONS.md': base.replace('A.', 'Changed.')}), cfg=boot)
        self.assertTrue(any('append only' in x for x in e), e)
        e = pp.check('pipeline-0.9.0', ['x'], {}, {}, files(), files(), cfg=boot, hook=lambda f: ['hook says no'])
        self.assertEqual(e, ['hook says no'])

    def test_verdict_parsing(self):
        self.assertEqual(pp.verdict('# R\n\n**Verdict: merge after fixes.** The skeleton is fine.'), 'merge after fixes')
        self.assertEqual(pp.verdict('**Verdict: merge.** Looks good.'), 'merge')
        self.assertEqual(pp.verdict('Verdict: merge'), 'merge')
        self.assertEqual(pp.verdict('**Verdict: merge.**'), 'merge')
        self.assertIsNone(pp.verdict('no verdict here'))

    def test_unknown_branch_refused(self):
        errs = self.run_check('proxy/skeleton', ['proxy/a.cpp'])
        self.assertTrue(errs and 'not job/J<n>' in errs[0])

    def test_job_branch_complete(self):
        done = dict(ROW, status='done', report='jobs/J1/report.md', review='jobs/J1/review.md')
        errs = self.run_check('job/J1', ['proxy/a.cpp', 'registries/jobs/J1.json'], head_rows={'J1': done, 'J2': OTHER},
                              base=files(**{'jobs/J1/brief.md': 'b'}),
                              head=files(**{'jobs/J1/report.md': 'r', 'jobs/J1/review.md': '**Verdict: merge.**'}))
        self.assertEqual(errs, [])

    def test_job_branch_unreviewed_or_unfinished(self):
        errs = self.run_check('job/J1', ['proxy/a.cpp'], base=files(**{'jobs/J1/brief.md': 'b'}),
                              head=files(**{'jobs/J1/review.md': 'Verdict: merge after fixes'}))
        text = '\n'.join(errs)
        self.assertIn('report.md is missing', text)
        self.assertIn('"merge after fixes", not "merge"', text)
        self.assertIn('must be `done`', text)

    def test_job_branch_without_brief_on_base_and_touching_other_rows(self):
        done = dict(ROW, status='done', report='jobs/J1/report.md', review='jobs/J1/review.md')
        errs = self.run_check('job/J1', ['x'], head_rows={'J1': done, 'J2': dict(OTHER, status='queued')},
                              head=files(**{'jobs/J1/report.md': 'r', 'jobs/J1/review.md': 'Verdict: merge'}))
        text = '\n'.join(errs)
        self.assertIn('no brief on the base', text)
        self.assertIn('only its own row', text)

    def test_brief_branch(self):
        q = {'id': 'J2', 'status': 'queued', 'brief': 'jobs/J2/brief.md'}
        self.assertEqual(self.run_check('brief/J2', ['jobs/J2/brief.md', 'registries/jobs/J2.json'], head_rows={'J1': ROW, 'J2': q}), [])
        for other in ('registries/jobs/J3.json', 'registries/jobs.jsonl', 'registries/tools/wsc.jobs.json'):   # J55: its own row file only
            errs = self.run_check('brief/J2', ['jobs/J2/brief.md', 'registries/jobs/J2.json', other], head_rows={'J1': ROW, 'J2': q})
            self.assertTrue(any('may only add' in e and other in e for e in errs), other)
        errs = self.run_check('brief/J2', ['jobs/J2/brief.md', 'proxy/x.cpp'], head_rows={'J1': ROW, 'J2': q})
        self.assertTrue(any('may only add' in e for e in errs))
        errs = self.run_check('brief/J2', ['jobs/J2/brief.md'])
        self.assertTrue(any('must be `queued`' in e for e in errs))

    def test_plan_and_meta_scopes(self):
        self.assertEqual(self.run_check('plan/x', ['docs/plans/PLAN.md', 'jobs/J9/brief.md', 'registries/jobs/J9.json', 'CLAUDE.md']), [])
        self.assertTrue(self.run_check('plan/x', ['tools/a.py']))
        self.assertTrue(self.run_check('plan/x', ['registries/tools/wsc.jobs.json']))
        self.assertEqual(self.run_check('meta/x', ['.github/workflows/gates.yml', 'tests/t.py',
                                                   'registries/tools/wsc.jobs.json', 'registries/hotkeys.jsonl', 'docs/DECISIONS.md']), [])
        errs = self.run_check('meta/x', ['proxy/core/guard.cpp'])
        self.assertTrue(errs and 'game code goes through a job' in errs[0])


    def test_review_by_the_builder_is_refused(self):
        done = {'id': 'J1', 'status': 'done', 'brief': 'jobs/J1/brief.md', 'report': 'jobs/J1/report.md', 'review': 'jobs/J1/review.md'}
        head = files(**{'jobs/J1/report.md': 'r', 'jobs/J1/review.md': '**Verdict: merge.**'})
        base = files(**{'jobs/J1/brief.md': 'b'})
        same = lambda p: [{'S1'}] if p.endswith('report.md') else [{'S2'}, {'S1'}]
        e = check('job/J1', ['x'], {'J1': ROW, 'J2': OTHER}, {'J1': done, 'J2': OTHER}, base, head, same)
        self.assertTrue(any('session that also wrote the report' in x for x in e), e)
        other = lambda p: [{'S1'}] if p.endswith('report.md') else [{'S2'}]
        self.assertEqual(check('job/J1', ['x'], {'J1': ROW, 'J2': OTHER}, {'J1': done, 'J2': OTHER}, base, head, other), [])

    def test_the_newest_round_verdict_decides(self):
        """review.md rounds are newest first, so verdict() reads the latest round with no change to its parser."""
        r1 = '## Round 1 (2026-11-01, branch job/J1 at abc1231)\n\n**Verdict: do not merge.**\n\n'
        r2 = '## Round 2 (2026-11-02, branch job/J1 at abc1232)\n\n**Verdict: merge.**\n\n'
        done = dict(ROW, status='done', report='jobs/J1/report.md', review='jobs/J1/review.md')
        base = files(**{'jobs/J1/brief.md': 'b'})
        reverse = r2.replace('Verdict: merge.', 'Verdict: do not merge.') + r1.replace('Verdict: do not merge.', 'Verdict: merge.')
        for review, ok in (('# R\n\n' + r2 + r1, True), ('# R\n\n' + reverse, False)):
            e = check('job/J1', ['x'], {'J1': ROW, 'J2': OTHER}, {'J1': done, 'J2': OTHER}, base,
                         files(**{'jobs/J1/report.md': 'r', 'jobs/J1/review.md': review}))
            self.assertEqual(e == [], ok, e)
        self.assertEqual(pp.verdict(r2 + r1), 'merge')
        self.assertEqual(pp.verdict(r1 + r2), 'do not merge')

    def test_fix_sessions_writing_the_report_do_not_trip_the_own_review_rule(self):
        """Builder S1 writes the report, reviewer R1 round 1, fixer F1 appends Fix round 1 to the report, reviewer R2 round 2."""
        done = dict(ROW, status='done', report='jobs/J1/report.md', review='jobs/J1/review.md')
        head = files(**{'jobs/J1/report.md': 'r', 'jobs/J1/review.md': '**Verdict: merge.**'})
        base = files(**{'jobs/J1/brief.md': 'b'})
        rounds = lambda p: [{'S1'}, {'F1'}] if p.endswith('report.md') else [{'R1'}, {'R2'}]
        self.assertEqual(check('job/J1', ['x'], {'J1': ROW, 'J2': OTHER}, {'J1': done, 'J2': OTHER}, base, head, rounds), [])
        fixer_reviews = lambda p: [{'S1'}, {'F1'}] if p.endswith('report.md') else [{'R1'}, {'F1'}]
        e = check('job/J1', ['x'], {'J1': ROW, 'J2': OTHER}, {'J1': done, 'J2': OTHER}, base, head, fixer_reviews)
        self.assertTrue(any('also wrote the report (F1)' in x for x in e), e)

    def test_a_commit_without_a_trailer_fails_closed(self):
        done = {'id': 'J1', 'status': 'done', 'brief': 'jobs/J1/brief.md', 'report': 'jobs/J1/report.md', 'review': 'jobs/J1/review.md'}
        head = files(**{'jobs/J1/report.md': 'r', 'jobs/J1/review.md': '**Verdict: merge.**'})
        base = files(**{'jobs/J1/brief.md': 'b'})
        for s in (lambda p: [set()], lambda p: [{'S1'}] if p.endswith('report.md') else [{'S2'}, set()]):
            e = check('job/J1', ['x'], {'J1': ROW, 'J2': OTHER}, {'J1': done, 'J2': OTHER}, base, head, s)
            self.assertTrue(any('no `Claude-Session:` trailer' in x for x in e), e)


class CoreOwnConfig(unittest.TestCase):
    """The core's real wsc.toml (C19): no registry view is committed, so a `brief/W<n>` branch (its brief and its row, nothing else) can pass `policy`
    and the `registries` gate together; before C19 the committed registries/jobs.md made that impossible."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = Ctx.load(ROOT)
        cls.cfg = pp.settings(cls.ctx.config)

    def test_no_view_is_committed(self):
        self.assertIs(self.ctx.config['views']['commit'], False)
        try:
            tracked = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '--', 'registries/*.md'], capture_output=True, text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest('not a git checkout')
        self.assertEqual(tracked, [], 'views are rendered to the git-ignored _scratch/registries/, never committed (C19)')

    def test_the_bootstrap_list_is_empty(self):
        self.assertEqual(self.cfg['bootstrap'], [], 'a standing exemption list stays empty until a repo introduces the pipeline (C18, B48)')

    def test_no_glob_names_a_view_and_a_brief_cannot_touch_one(self):
        reg_dir = self.ctx.config['registries_dir']
        for kind in ('plan', 'meta'):
            views = [g for g in self.cfg[kind] if g.startswith(f'{reg_dir}/') and g.endswith('.md')]
            self.assertEqual(views, [], f'[policy] {kind} names a registry view')
        base = {'W1': {'id': 'W1', 'status': 'done'}, 'W2': {'id': 'W2', 'status': 'needs_brief'}}
        head = {'W1': base['W1'], 'W2': {'id': 'W2', 'status': 'queued', 'brief': 'jobs/W2/brief.md'}}
        brief_and_row = ['jobs/W2/brief.md', 'registries/jobs/W2.json']
        self.assertEqual(pp.check('brief/W2', brief_and_row, base, head, files(), files(), cfg=self.cfg), [])
        errs = pp.check('brief/W2', brief_and_row + ['registries/jobs.md'], base, head, files(), files(), cfg=self.cfg)
        self.assertTrue(any('a brief branch may only add' in e and 'registries/jobs.md' in e for e in errs), errs)
        self.assertTrue(any('registries/jobs.md (a committed registry view: C19, set `[views] commit = false`)' in e for e in errs), errs)
        errs = pp.check('brief/W2', brief_and_row + ['proxy/x.cpp'], base, head, files(), files(), cfg=self.cfg)
        self.assertFalse(any('C19' in e for e in errs), errs)   # only a registry view gets the hint


class PolicyOnGit(unittest.TestCase):
    """main() on a real fixture repository: job branches whose report and review carry no trailer, or distinct ones."""

    def git(self, *a):
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *a], cwd=self.d, check=True, capture_output=True, text=True)

    def commit(self, path, text, trailer=None):
        p = Path(self.d) / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8', newline='\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', f'write {path}', *(['--trailer', f'Claude-Session: {trailer}'] if trailer else []))

    def write_rows(self, rows, layout, trailer=None):
        """The jobs registry as one JSONL (before J55) or one file per row (J55)."""
        if layout == 'jsonl':
            self.commit('registries/jobs.jsonl', ''.join(json.dumps(r) + '\n' for r in rows), trailer)
            return
        for r in rows:
            p = Path(self.d) / 'registries' / 'jobs' / f'{r["id"]}.json'
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(r, indent=2) + '\n', encoding='utf-8', newline='\n')
        (Path(self.d) / 'registries' / 'jobs.jsonl').unlink(missing_ok=True)
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'rows', *(['--trailer', f'Claude-Session: {trailer}'] if trailer else []))

    def branch(self, report_session, review_session, layout='dir'):
        self.git('checkout', '-q', '-B', 'job/J1', 'main')
        self.commit('jobs/J1/report.md', 'report', report_session)
        done = dict(ROW, status='done', report='jobs/J1/report.md', review='jobs/J1/review.md')
        self.write_rows([done, OTHER], layout, review_session)
        self.commit('jobs/J1/review.md', '**Verdict: merge.**', review_session)
        return subprocess.run([sys.executable, str(WSC), '--root', self.d, 'policy', '--branch', 'job/J1', '--base', 'main'], cwd=self.d,
                              capture_output=True, text=True)

    def setUp(self, layout='dir'):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 't@example.invalid')
        self.git('config', 'user.name', 'test')
        self.commit('wsc.toml', '[policy]\ndecisions = "docs/DECISIONS.md"\n')
        self.commit('jobs/J1/brief.md', 'brief')
        self.write_rows([ROW, OTHER], layout)

    def test_rows_at_reads_either_layout_the_same(self):
        dir_rows = pp_rows_at(self.d, 'main')
        self.git('checkout', '-q', '-b', 'old', 'main')
        self.write_rows([ROW, OTHER], 'jsonl')
        self.assertEqual(pp_rows_at(self.d, 'old'), dir_rows)
        self.assertEqual(sorted(dir_rows), ['J1', 'J2'])

    def test_a_base_from_before_j55_and_a_per_id_head(self):
        """J55's own pull request, and any branch that moves across it: base rows in the JSONL, head rows in files."""
        self.tearDown()
        self.setUp(layout='jsonl')
        r = self.branch('builder-session', 'reviewer-session', layout='dir')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.git('checkout', '-q', '-B', 'job/J1', 'main')   # touching another row is still refused across the layouts
        self.commit('jobs/J1/report.md', 'report', 'builder-session')
        done = dict(ROW, status='done', report='jobs/J1/report.md', review='jobs/J1/review.md')
        self.write_rows([done, dict(OTHER, status='queued')], 'dir', 'reviewer-session')
        self.commit('jobs/J1/review.md', '**Verdict: merge.**', 'reviewer-session')
        r = subprocess.run([sys.executable, str(WSC), '--root', self.d, 'policy', '--branch', 'job/J1', '--base', 'main'], cwd=self.d, capture_output=True, text=True)
        self.assertIn('only its own row; it also changes J2', r.stderr)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_trailers_refused_distinct_trailers_pass(self):
        r = self.branch(None, None)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('report.md has 1 commit(s) with no `Claude-Session:` trailer', r.stderr)
        self.assertIn('review.md has 1 commit(s)', r.stderr)
        r = self.branch('builder-session', 'reviewer-session')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.branch('same-session', 'same-session')
        self.assertEqual(r.returncode, 1)
        self.assertIn('also wrote the report (same-session)', r.stderr)


    def test_decisions_are_append_only(self):
        base = '| # | Date |\n|---|---|\n| D1 | 2026-10-28 | Liam | A. | yes |\n| D2 | 2026-10-28 | Liam | B. | no |\n'
        good = base + '| D3 | 2026-10-29 | agent (J5) | C. | yes |\n'
        self.assertEqual(pp.decisions_problems(base, good, CFG), [])
        self.assertIn('append only', pp.decisions_problems(base, base.replace('B.', 'B changed.'), CFG)[0])
        self.assertIn('should be D3', pp.decisions_problems(base, base + '| D4 | 2026-10-29 | x | C. | yes |\n', CFG)[0])
        self.assertIn('is not', pp.decisions_problems(base, base + '| D3 | today | x | C. | maybe |\n', CFG)[0])
        e = check('plan/x', ['docs/DECISIONS.md'], {'J1': ROW}, {'J1': ROW}, files(**{'docs/DECISIONS.md': base}),
                     files(**{'docs/DECISIONS.md': base.replace('B.', 'Bee.')}))
        self.assertTrue(any('append only' in x for x in e), e)


if __name__ == '__main__':
    unittest.main()
