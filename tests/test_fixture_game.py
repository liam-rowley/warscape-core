"""The second consumer: a minimal game repo (tests/fixture_game: ids F<n>, decisions X<n>, trailer Agent-Session, one input set, two game gate
modules) copied into a throwaway git repo and driven through the real verbs. It proves the job pipeline is configuration plus gate modules, not napoleon: no
napoleon wording, id or path is needed to run `jobs check|next|review|fix|view`, `policy`, `ci inputs|render`, or one dry autopilot tick. Real git,
no network; `claude` and `gh` are fakes (napoleon J62).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / 'fixture_game'
sys.path.insert(0, str(ROOT))
from warscape import jobq  # noqa: E402
from warscape.repo import DEFAULTS, Ctx  # noqa: E402

REPORT = '# F1 report: Fixture first job\n\n## What exists\nNothing; a fixture.\n\n## Deviations from the brief, and why\nNone.\n\n## Open questions\nNone.\n'


def git(cwd, *args, check=True):
    env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
    return subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *args],
                          cwd=cwd, env=env, check=check, capture_output=True, text=True)


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls._tmp.name) / 'game'
        shutil.copytree(FIXTURE, cls.d)
        (cls.d / 'jobs' / 'F1' / 'report.md').write_text(REPORT, encoding='utf-8', newline='\n')   # the file the fixture cannot ship as a report.md
        cls.wsc(cls, 'ci', 'render')
        git(cls.d, 'init', '-q', '-b', 'main')
        git(cls.d, 'add', '-A')
        git(cls.d, 'commit', '-q', '-m', 'fixture')
        git(cls.d, 'update-ref', 'refs/remotes/origin/main', 'HEAD')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def wsc(self, *args, cwd=None):
        p = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(self.d), *args], cwd=cwd or self.d, capture_output=True,
                           text=True, timeout=120)
        return p.returncode, p.stdout, p.stderr


class Verbs(Fixture):
    def test_check_runs_the_core_rules_and_the_jobs_stage(self):
        rc, out, err = self.wsc('jobs', 'check')
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), 'jobs check: 3 rows, ok, 2 fixture briefs')   # F1 is legacy for the brief rule, F2 passes it

    def test_a_brief_the_jobs_stage_refuses_and_a_blocked_row_fail_check(self):
        with tempfile.TemporaryDirectory() as t:
            g = Path(t) / 'g'
            shutil.copytree(self.d, g, ignore=shutil.ignore_patterns('.git'))
            (g / 'jobs' / 'F2' / 'brief.md').write_text((g / 'jobs' / 'F2' / 'brief.md').read_text(encoding='utf-8').replace('Fixture rule', 'x'),
                                                        encoding='utf-8', newline='\n')
            p = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(g), 'jobs', 'check'], capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 1)
            self.assertIn('F2: brief: fixture rule: the brief does not say', p.stderr)
            self.assertIn('1 problems', p.stdout)

    def test_next_names_the_job_and_uses_the_configured_texts(self):
        rc, out, err = self.wsc('jobs', 'next', '--offline')
        self.assertEqual(rc, 0, err)
        self.assertIn('F2: Fixture second job (model opus, needs_pc no)', out)
        self.assertIn('python3 core/wsc.py policy --branch job/F2 --base origin/main', out)
        self.assertIn('Never merge it: the reviewer marks it ready and merges (X7).', out)
        for napoleon in ('D32', 'J57', 'PLAN.md', 'tools/pr_policy.py', 'Liam'):
            self.assertNotIn(napoleon, out)

    def test_next_id_refuses_a_job_that_waits(self):
        rc, out, err = self.wsc('jobs', 'next', '--id', 'F3', '--offline')
        self.assertEqual(rc, 1)
        self.assertEqual(err.strip(), 'jobs: F3 (needs_brief): waits for F2')
        rc, out, err = self.wsc('jobs', 'next', '--id', 'F99', '--offline')
        self.assertEqual((rc, err.strip()), (1, 'jobs: F99 is not a row of the jobs registry'))

    def test_review_and_fix_read_the_job_branch_row(self):
        git(self.d, 'checkout', '-q', '-b', 'job/F2', 'main')
        (self.d / 'jobs' / 'F2' / 'report.md').write_text(REPORT.replace('F1', 'F2'), encoding='utf-8', newline='\n')
        row = json.loads((self.d / 'registries' / 'jobs' / 'F2.json').read_text(encoding='utf-8'))
        row.update(status='review', report='jobs/F2/report.md')
        (self.d / 'registries' / 'jobs' / 'F2.json').write_text(json.dumps(row, indent=2) + '\n', encoding='utf-8', newline='\n')
        git(self.d, 'add', '-A')
        git(self.d, 'commit', '-q', '-m', 'F2 report', '--trailer', 'Agent-Session: builder')
        git(self.d, 'update-ref', 'refs/remotes/origin/job/F2', 'HEAD')
        git(self.d, 'checkout', '-q', 'main')
        try:
            rc, out, err = self.wsc('jobs', 'review', '--offline')
            self.assertEqual(rc, 0, err)
            self.assertIn('F2: review branch job/F2', out)
            self.assertIn('This is round 1', out)
            self.assertIn('docs/REVIEW.md', out)
            rc, out, err = self.wsc('jobs', 'fix', '--id', 'F2', '--offline')
            self.assertEqual((rc, err.strip()), (1, 'jobs: F2 is review on job/F2, not fix'))
            rc, out, err = self.wsc('jobs', 'next', '--id', 'F2', '--offline')
            self.assertEqual(rc, 1)   # a branch exists now: the job is in progress
            self.assertIn('in progress on job/F2', err)
            ctx = Ctx.load(self.d)
            jobq.configure(ctx)
            self.addCleanup(jobq.configure_from, DEFAULTS['jobs'])
            branches = jobq.remote_branches(self.d, True)
            on_branch = jobq.branch_rows(self.d, branches, True, 'registries', done={'F1'})
            self.assertEqual(sorted(on_branch), ['F2'])
            self.assertEqual(on_branch['F2'].row['status'], 'review')
            page_rc, page, _ = self.wsc('jobs', 'view', '--offline', '--no-open', '--out', '_scratch/jobs.html')
            self.assertEqual(page_rc, 0)
            html = (self.d / '_scratch' / 'jobs.html').read_text(encoding='utf-8')
            self.assertIn('fixture panel', html)
            self.assertIn('Fixture second job', html)
            self.assertIn('data-id="F2" data-act="review"', html)
        finally:
            git(self.d, 'update-ref', '-d', 'refs/remotes/origin/job/F2')

    def test_one_dry_autopilot_tick_starts_nothing(self):
        git(self.d, 'update-ref', 'refs/remotes/origin/job/F2', 'HEAD')   # a branch whose row on it is queued: nothing is ready for review or fix
        try:
            ctx = Ctx.load(self.d)
            jobq.configure(ctx)
            self.addCleanup(jobq.configure_from, DEFAULTS['jobs'])

            def snapshot():
                rows = jobq.main_rows(ctx)
                branches = jobq.remote_branches(self.d, True)
                return rows, lambda p: None, branches, jobq.branch_rows(self.d, branches, True, 'registries', done={'F1'})
            launched = []
            srv = jobq.JobServer(snapshot, lambda: [], launched.append, which=lambda n: 'claude', dry_run=True, root=self.d,
                                 log_path=self.d / '_scratch' / 'auto.log', ctx=ctx)
            try:
                self.assertEqual(srv.auto_tick(), [])
            finally:
                srv.server_close()
            self.assertEqual(launched, [])
            self.assertIn('nothing ready for review or fix', (self.d / '_scratch' / 'auto.log').read_text(encoding='utf-8'))
        finally:
            git(self.d, 'update-ref', '-d', 'refs/remotes/origin/job/F2')


class Policy(Fixture):
    def branch(self, name, files, trailer=None):
        git(self.d, 'checkout', '-q', '-B', name, 'main')
        for rel, text in files.items():
            p = self.d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8', newline='\n')
        git(self.d, 'add', '-A')
        git(self.d, 'commit', '-q', '-m', 'work', *(['--trailer', f'Agent-Session: {trailer}'] if trailer else []))

    def policy(self, name):
        try:
            return self.wsc('policy', '--branch', name, '--base', 'main')
        finally:
            git(self.d, 'checkout', '-q', 'main')

    def test_brief_plan_meta_and_unknown_branches(self):
        row = json.loads((self.d / 'registries' / 'jobs' / 'F3.json').read_text(encoding='utf-8'))
        row.update(status='queued', brief='jobs/F3/brief.md')
        self.branch('brief/F3', {'jobs/F3/brief.md': 'brief', 'registries/jobs/F3.json': json.dumps(row, indent=2) + '\n'})
        rc, out, err = self.policy('brief/F3')
        self.assertEqual(rc, 0, out + err)
        self.branch('plan/x', {'docs/note.md': 'n'})
        rc, out, err = self.policy('plan/x')
        self.assertEqual(rc, 0, out + err)
        self.branch('plan/y', {'lib/code.py': 'x = 1'})
        rc, out, err = self.policy('plan/y')
        self.assertEqual(rc, 1)
        self.assertIn('a plan/ branch may only touch', err)
        self.branch('meta/z', {'ci/gates.yml.in': 'x'})
        rc, out, err = self.policy('meta/z')
        self.assertEqual(rc, 0, out + err)
        self.branch('foo/bar', {'docs/note.md': 'n'})
        rc, out, err = self.policy('foo/bar')
        self.assertIn('is not job/F<n>, brief/F<n>, plan/* or meta/*', err)

    def test_the_fixtures_own_decision_prefix_and_its_policy_stage_apply(self):
        text = (FIXTURE / 'docs' / 'DECISIONS.md').read_text(encoding='utf-8')
        self.branch('plan/d', {'docs/DECISIONS.md': text + '| X4 | 2026-11-02 | Liam | skipped X3. | yes |\n'})
        rc, out, err = self.policy('plan/d')
        self.assertIn('new row X4 should be X3', err)
        git(self.d, 'checkout', '-q', 'main')
        row = {**json.loads((self.d / 'registries' / 'jobs' / 'F2.json').read_text(encoding='utf-8')), 'status': 'done',
               'report': 'jobs/F2/report.md', 'review': 'jobs/F2/review.md'}
        self.branch('job/F2', {'forbidden/x.txt': 'x', 'jobs/F2/report.md': REPORT.replace('F1', 'F2'),
                               'jobs/F2/review.md': '## Round 1 (2026-11-02, branch job/F2 at abc1234)\n\n**Verdict: merge.**\n',
                               'registries/jobs/F2.json': json.dumps(row, indent=2) + '\n'}, trailer='same')
        rc, out, err = self.policy('job/F2')
        self.assertEqual(rc, 1)
        self.assertIn('fixture policy rule: forbidden/x.txt is in a forbidden folder', err)
        self.assertIn('a session that also wrote the report (same)', err)
        self.assertNotIn('Claude-Session', err)   # the fixture's trailer is Agent-Session


BRIEF = ('# F3: Fixture third job\n\nModel: Sonnet. Budget about 40 tool calls; at the cap, stop. Fixture rule: this brief says so.\n\n'
         '## Kill criteria\n- It breaks twice: stop.\n\n## Finish\nWrite `jobs/F3/report.md`. Then `wsc reg set jobs F3 status=review report=jobs/F3/report.md`.\n')


class BriefBranch(Fixture):
    def test_a_brief_branch_passes_policy_and_gates(self):
        """C19: the brief writer's own commands (the brief file, then `reg set jobs F3 status=queued brief=...`) change the brief and the row and
        nothing else, and the branch passes `policy` (brief and row only) and the gates (queue, registries, rendered workflows). The fixture does not
        commit views (`[views] commit = false`). With `commit = true` the same `reg set` also writes registries/jobs.md, a third file that `policy`
        refuses on a brief branch while the `registries` gate refuses the branch without it: flipping the fixture's wsc.toml makes this test fail at
        the first assertion (checked 2026-11-02; the core's own deadlock, reproduced on a throwaway brief/W1 before C19)."""
        status = lambda: git(self.d, 'status', '--porcelain', '--untracked-files=all').stdout.splitlines()
        git(self.d, 'checkout', '-q', '-B', 'brief/F3', 'main')

        def back():
            git(self.d, 'checkout', '-q', '-f', 'main')
            git(self.d, 'clean', '-fdq')
            git(self.d, 'branch', '-q', '-D', 'brief/F3')
        self.addCleanup(back)
        (self.d / 'jobs' / 'F3').mkdir(parents=True)
        (self.d / 'jobs' / 'F3' / 'brief.md').write_text(BRIEF, encoding='utf-8', newline='\n')
        rc, out, err = self.wsc('reg', 'set', 'jobs', 'F3', 'status=queued', 'brief=jobs/F3/brief.md')
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(sorted(l[3:] for l in status()), ['jobs/F3/brief.md', 'registries/jobs/F3.json'])
        git(self.d, 'add', '-A')
        git(self.d, 'commit', '-q', '-m', 'F3 brief', '--trailer', 'Agent-Session: brief-writer')
        self.assertEqual(git(self.d, 'diff', '--name-only', 'main...HEAD').stdout.split(), ['jobs/F3/brief.md', 'registries/jobs/F3.json'])
        rc, out, err = self.wsc('policy', '--branch', 'brief/F3', '--base', 'main')
        self.assertEqual(rc, 0, out + err)
        self.assertIn('brief/F3: ok (2 files changed)', out)
        rc, out, err = self.wsc('gates', '--only', 'registries,json,conflict_markers,jobs,ci_render')
        self.assertEqual(rc, 0, out + err)
        self.assertIn('queue ok', out)
        self.assertEqual(status(), [])   # neither command left a changed file behind: the view went to the ignored _scratch/registries/
        self.assertTrue((self.d / '_scratch' / 'registries' / 'jobs.md').is_file())


class Ci(Fixture):
    def test_inputs_and_render(self):
        rc, out, err = self.wsc('ci', 'inputs', '--base', '')
        self.assertEqual(rc, 0)
        self.assertEqual([l.split('=')[0] for l in out.splitlines()], ['lib', 'lib_tree', 'tree_salt'])
        self.assertIn('lib=true', out)
        rc, out, err = self.wsc('ci', 'render', '--check')
        self.assertEqual((rc, out.strip().splitlines()[-1]), (0, 'ci render --check: ok'), out)
        gates = (self.d / '.github' / 'workflows' / 'gates.yml').read_text(encoding='utf-8')
        self.assertIn('decide lib "$LIB" "$LIB_HIT" lib-build', gates)
        self.assertIn('token: ${{ secrets.CORE_TOKEN }}', gates)
        self.assertEqual(gates.splitlines()[0], '# Generated by `wsc ci render` from ci/gates.yml.in: do not edit this file; edit the template or [ci] in wsc.toml.')
        (self.d / '.github' / 'workflows' / 'policy.yml').write_text('edited\n', encoding='utf-8')
        try:
            rc, out, err = self.wsc('ci', 'render', '--check')
            self.assertEqual(rc, 1)
            self.assertIn('policy.yml differs from its render', out)
        finally:
            self.wsc('ci', 'render')

    def test_notify_dry_run_uses_the_fixture_hints(self):
        from warscape import ci
        cfg = Ctx.load(self.d).config['ci']
        self.assertEqual(ci.class_hint('gates', '', cfg), 'fixture: run the gates')
        self.assertEqual(ci.class_hint('anything', '', cfg), 'fixture: see the log')
        self.assertIn('Fixture notice.', ci.message([('gates', 's')], 1, 1, 'u', 'job/F2', cfg))

    def test_gates_run_the_queue_and_the_render_checks(self):
        rc, out, err = self.wsc('gates', '--only', 'jobs,ci_render')
        self.assertEqual(rc, 0, out + err)
        self.assertIn('queue ok', out)
        self.assertIn('2 workflows match their render', out)

    def test_the_fixtures_gates_stage_module_is_a_gate_line(self):
        rc, out, err = self.wsc('gates', '--only', 'no_todo')
        self.assertEqual(rc, 0, out + err)
        self.assertIn('ok   no_todo', out)
        self.assertNotIn('fixture_rules', out)   # a jobs, policy and view module is no gates line
        (self.d / 'docs' / 'todo.md').write_text('TODO\n', encoding='utf-8')
        try:
            rc, out, err = self.wsc('gates', '--only', 'no_todo')
            self.assertEqual(rc, 1, out + err)
            self.assertIn('docs/todo.md', out)
        finally:
            (self.d / 'docs' / 'todo.md').unlink()


if __name__ == '__main__':
    unittest.main()
