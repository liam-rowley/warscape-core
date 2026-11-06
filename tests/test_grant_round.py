"""W132: the owner can grant a blocked job one more review round.

The grant is a decision row with `grants_round: <job id>`. Two halves:
- the judge: `wsc policy` (parent and `--judge` child, real commits on real branch names in a throwaway clone of this checkout) refuses the row on every
  branch kind but `meta/` (and `decide/`): `plan/` merges itself and a `job/` branch is the job's own. A job reads `blocked` only on its own branch, so its
  row on the base is `queued` (W45 on main, review W132 B1) and the `meta/` pull request carries the grant and that row together;
- the limit: `max_rounds` and everything that used `MAX_ROUNDS` follow the rows (`jobq.S.grants`, read from the decisions folder of the tree).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _util import CORE, core_source, git

sys.path.insert(0, str(CORE))
from warscape import jobq as jv  # noqa: E402

BY = '3 review rounds without merge'


def row_file(i, job='W901', **extra):
    return {f'registries/decisions/C261106-{i}.json': json.dumps(
        {'id': f'C261106-{i}', 'date': '2026-11-06', 'who': 'Liam', 'decision': 'One more round.', 'reversible': 'no' if job else 'yes',
         **({'grants_round': job} if job else {}), **extra}, indent=2) + '\n'}


def jobs_row(jid, **kw):
    return {f'registries/jobs/{jid}.json': json.dumps({'id': jid, 'title': 'A test job', 'status': 'queued', 'brief': f'jobs/{jid}/brief.md', **kw}, indent=2) + '\n'}


def blocked(jid='W901', **kw):
    return jobs_row(jid, **{'status': 'blocked', 'blocked_by': BY, **kw})


class Branches:
    """The few branch helpers the judge tests need over the throwaway clone `d`, whose `main` (and `origin/main`) is the base."""

    def commit(self, files, msg='work', trailer=None):
        for rel, text in files.items():
            p = self.d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8', newline='\n')
        git(self.d, 'add', '-A', '--', *files)
        git(self.d, 'commit', '-q', '-m', msg, *(['--trailer', f'{self.trailer}: {trailer}'] if trailer else []))

    def branch(self, name, files, start='main', trailer=None):
        git(self.d, 'checkout', '-q', '-f', '-B', name, start)
        self.commit(files, trailer=trailer)
        git(self.d, 'checkout', '-q', '-f', 'main')

    def local(self, name):
        git(self.d, 'checkout', '-q', '-f', name)
        try:
            p = subprocess.run([sys.executable, str(CORE / 'wsc.py'), '--root', str(self.d), 'policy', '--branch', name, '--base', 'origin/main'],
                               cwd=self.d, capture_output=True, text=True, timeout=300)
            return p.returncode, p.stdout, p.stderr
        finally:
            git(self.d, 'checkout', '-q', '-f', 'main')


class GrantJudge(Branches, unittest.TestCase):
    trailer = 'Claude-Session'

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls._tmp.name).resolve() / 'core'
        git(cls._tmp.name, 'clone', '-q', str(core_source()), str(cls.d))
        cls.commit(cls, {**jobs_row('W901', semver='none'), **jobs_row('W902'), **jobs_row('W903', status='needs_brief'),
                         'jobs/W901/brief.md': '# W901: blocked on its branch\n', 'jobs/W902/brief.md': '# W902: queued\n'})
        git(cls.d, 'update-ref', 'refs/remotes/origin/main', 'main')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def judge(self, name, files):
        self.branch(name, files, trailer='S1')
        rc, out, err = self.local(name)
        self.assertNotIn('Traceback', err)
        return rc, out + err

    def test_a_grant_on_meta_is_accepted_with_a_queued_row_on_the_base(self):
        rc, out = self.judge('meta/grant', {**row_file('aaaa'), **blocked()})
        self.assertEqual(rc, 0, out)

    def test_a_second_grant_is_accepted_while_the_base_row_is_blocked(self):
        self.merge_to_main('meta/second-a', {**row_file('a001'), **blocked()})
        try:
            rc, out = self.judge('meta/second-b', {**row_file('a002'), **blocked(blocked_by='4 review rounds without merge')})
            self.assertEqual(rc, 0, out)
        finally:
            self.undo_merge()

    def test_a_grant_is_refused_on_plan_brief_release_and_job_branches(self):
        for i, name in enumerate(['plan/grant', 'brief/W902', 'release/v9.9.9', 'job/W901', 'job/W902']):
            for j, extra in enumerate(({}, blocked())):   # the row set in the same branch helps no kind but meta
                rc, out = self.judge(name, {**row_file(f'b0{i}{j}'), **extra})
                self.assertEqual(rc, 1, f'{name}: {out}')
                self.assertIn("grants_round is the owner's alone", out, name)

    def test_a_grant_for_a_job_that_is_not_blocked_is_refused(self):
        rc, out = self.judge('meta/not-blocked', row_file('cccc', job='W902'))
        self.assertEqual(rc, 1, out)
        self.assertIn('not blocked by its review rounds', out)
        self.assertIn('status=blocked', out)

    def test_a_grant_with_another_blocked_reason_is_refused(self):
        rc, out = self.judge('meta/other-reason', {**row_file('c001'), **blocked(blocked_by='waiting for a PC')})
        self.assertEqual(rc, 1, out)
        self.assertIn('not blocked by its review rounds', out)

    def test_a_grant_for_a_job_that_never_ran_is_refused(self):
        rc, out = self.judge('meta/never-ran', {**row_file('c100', job='W903'), **blocked('W903')})
        self.assertEqual(rc, 1, out)
        self.assertIn('its row on the base is needs_brief', out)

    def test_a_grant_for_a_done_job_is_refused(self):
        self.merge_to_main('plan/w902-done', jobs_row('W902', status='done'))
        try:
            rc, out = self.judge('meta/done', {**row_file('c101', job='W902'), **blocked('W902')})
            self.assertEqual(rc, 1, out)
            self.assertIn('its row on the base is done', out)
        finally:
            self.undo_merge()

    def test_a_grant_that_says_it_can_be_reversed_is_refused(self):
        rc, out = self.judge('meta/reversible', {**row_file('c200', reversible='yes'), **blocked()})
        self.assertEqual(rc, 1, out)
        self.assertIn('reversible=no', out)

    def test_a_grant_for_no_job_is_refused(self):
        for i, job in enumerate(['W999', 'nope', 7]):
            rc, out = self.judge('meta/nojob', row_file(f'dd0{i}', job=job))
            self.assertEqual(rc, 1, f'{job!r}: {out}')

    def test_a_row_without_the_field_is_a_plain_decision(self):
        rc, out = self.judge('plan/plain', row_file('eeee', job=None))
        self.assertEqual(rc, 0, out)

    def test_a_merged_grant_cannot_change(self):
        self.merge_to_main('meta/first', {**row_file('ffff'), **blocked()})
        try:
            rc, out = self.judge('meta/change', row_file('ffff', decision='Two more rounds.'))
            self.assertEqual(rc, 1, out)
            self.assertIn('append only', out)
        finally:
            self.undo_merge()

    def merge_to_main(self, name, files):
        self.branch(name, files, trailer='S1')
        git(self.d, 'merge', '-q', '--ff-only', name)
        git(self.d, 'update-ref', 'refs/remotes/origin/main', 'main')

    def undo_merge(self):
        git(self.d, 'reset', '-q', '--hard', 'HEAD~1')
        git(self.d, 'update-ref', 'refs/remotes/origin/main', 'main')


class FourthRound(Branches, unittest.TestCase):
    """The whole road with W45's shape (brief decision 5, review S2): the row is `queued` on the base and `blocked` only on the job's branch, three rounds without
    merge; the grant lands from `meta/`, the branch merges main, answers round 3 and gets a round 4 with a `merge` verdict."""
    trailer = 'Claude-Session'
    ROW = dict(semver='none', model='opus', report='jobs/W901/report.md', review='jobs/W901/review.md')
    BRIEF = ('# W901: a job\n\nModel: Opus, reason: a test\nBudget about 10 tool calls.\nSemver: none\n\n## Kill criteria\n- None.\n\n'
             '## Finish\n`wsc reg set jobs W901 status=review report=jobs/W901/report.md`\n')
    REPORT = '# W901 report\n\n## Deviations from the brief and why\nNone.\n\n## Open questions\nNone.\n\nUsage: 1 tool calls; models: opus; by hand\n'

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls._tmp.name).resolve() / 'core'
        git(cls._tmp.name, 'clone', '-q', str(core_source()), str(cls.d))
        cls.commit(cls, {**jobs_row('W901', semver='none', model='opus'), 'jobs/W901/brief.md': cls.BRIEF})
        git(cls.d, 'update-ref', 'refs/remotes/origin/main', 'main')
        git(cls.d, 'checkout', '-q', '-f', '-B', 'job/W901', 'main')
        report, review = cls.REPORT, ''
        cls.commit(cls, {**jobs_row('W901', status='review', **cls.ROW), 'jobs/W901/report.md': report}, trailer='build')
        for n in (1, 2, 3):
            review = cls.round(n, 'merge after fixes') + review
            row = jobs_row('W901', status='fix', **cls.ROW) if n < 3 else blocked(**cls.ROW)
            cls.commit(cls, {**row, 'jobs/W901/review.md': review}, trailer=f'rev{n}')
            if n < 3:
                report += f'\n## Fix round {n}\nDone.\n'
                cls.commit(cls, {**jobs_row('W901', status='review', **cls.ROW), 'jobs/W901/report.md': report}, trailer='build')
        cls.report, cls.review = report, review
        git(cls.d, 'checkout', '-q', '-f', 'main')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @staticmethod
    def round(n, verdict):
        return f'## Round {n} (2026-11-06, branch job/W901 at abc123{n})\n\n**Verdict: {verdict}.**\n\n'

    def jobs_check(self, name):
        git(self.d, 'checkout', '-q', '-f', name)
        try:
            p = subprocess.run([sys.executable, str(CORE / 'wsc.py'), '--root', str(self.d), 'jobs', 'check'], cwd=self.d, capture_output=True, text=True, timeout=300)
            return p.returncode, p.stdout + p.stderr
        finally:
            git(self.d, 'checkout', '-q', '-f', 'main')

    def fourth_round(self, name, start):
        """Branch `name` off `start`, answering round 3 and writing round 4 with a merge verdict, the row done."""
        git(self.d, 'checkout', '-q', '-f', '-B', name, start)
        self.commit({**jobs_row('W901', status='review', **self.ROW), 'jobs/W901/report.md': self.report + '\n## Fix round 3\nDone.\n'}, trailer='build')
        self.commit({**jobs_row('W901', status='done', **self.ROW), 'jobs/W901/review.md': self.round(4, 'merge') + self.review}, trailer='rev4')
        git(self.d, 'checkout', '-q', '-f', 'main')

    def test_the_grant_then_a_fourth_round(self):
        three = git(self.d, 'rev-parse', 'job/W901').stdout.strip()
        # no grant: policy holds no limit, `jobs check` is what refuses
        self.fourth_round('job/W901', three)
        rc, out, err = self.local('job/W901')
        self.assertEqual(rc, 0, out + err)
        rc, out = self.jobs_check('job/W901')
        self.assertEqual(rc, 1, out)
        self.assertIn('at most 3', out)

        # the grant, on a real meta/ branch, against the row as main holds it
        self.assertEqual(json.loads(git(self.d, 'show', 'origin/main:registries/jobs/W901.json').stdout)['status'], 'queued')
        self.branch('meta/grant-W901', {**row_file('9a01'), **blocked(semver='none', model='opus')}, trailer='owner')
        rc, out, err = self.local('meta/grant-W901')
        self.assertEqual(rc, 0, out + err)
        git(self.d, 'merge', '-q', '--ff-only', 'meta/grant-W901')
        git(self.d, 'update-ref', 'refs/remotes/origin/main', 'main')

        # the grant is on main but not in the branch: the message says what to do
        rc, out = self.jobs_check('job/W901')
        self.assertEqual(rc, 1, out)
        self.assertIn('merged main', out)

        # the branch merges main, keeping its own row, and round 4 passes both
        git(self.d, 'checkout', '-q', '-f', '-B', 'job/W901', three)
        git(self.d, 'merge', '-q', '-s', 'ours', '--no-commit', 'main')
        git(self.d, 'checkout', 'main', '--', 'registries/decisions')
        git(self.d, 'commit', '-q', '-m', 'merge main', '--trailer', f'{self.trailer}: build')
        git(self.d, 'checkout', '-q', '-f', 'main')
        self.fourth_round('job/W901', 'job/W901')
        rc, out, err = self.local('job/W901')
        self.assertEqual(rc, 0, out + err)
        rc, out = self.jobs_check('job/W901')
        self.assertEqual(rc, 0, out)


class RoundLimit(unittest.TestCase):
    def setUp(self):
        self.old = jv.S.grants
        jv.S.grants = {'W45': 1, 'W46': 2}

    def tearDown(self):
        jv.S.grants = self.old

    @staticmethod
    def review(n, v='merge after fixes'):
        return ''.join(f'## Round {i} (2026-11-06, branch job/W45 at abc123{i})\n\n**Verdict: {v}.**\n\n' for i in range(n, 0, -1))

    def test_max_rounds_counts_the_rows_that_name_the_job(self):
        self.assertEqual([jv.max_rounds(j) for j in ('W45', 'W46', 'W47')], [4, 5, 3])
        self.assertEqual(jv.max_rounds('W45', {}), 3)
        self.assertEqual(jv.max_rounds('W45', {'W46': 3}), 3)

    def test_a_fourth_round_needs_a_grant(self):
        self.assertEqual(jv.round_problems(self.review(4), 'W45'), [])
        self.assertIn('at most 3', ' '.join(jv.round_problems(self.review(4), 'W47')))
        self.assertIn('at most 4', ' '.join(jv.round_problems(self.review(5), 'W45')))
        self.assertIn('merged main', ' '.join(jv.round_problems(self.review(4), 'W47')))

    def test_round_three_is_not_the_last_with_a_grant(self):
        row = {'id': 'W45', 'status': 'blocked', 'blocked_by': BY}
        self.assertEqual(jv.round_status_problems({**row, 'id': 'W47'}, self.review(3), ''), [])
        self.assertIn('should be fix', ' '.join(jv.round_status_problems(row, self.review(3), '')))
        self.assertEqual(jv.round_status_problems({**row, 'status': 'review', 'blocked_by': None}, self.review(3), '## Fix round 3\n'), [])
        last = {'id': 'W45', 'status': 'blocked', 'blocked_by': '4 review rounds without merge'}
        self.assertEqual(jv.round_status_problems(last, self.review(4), ''), [])

    def test_review_is_ready_for_a_fourth_round_only_with_a_grant(self):
        by = {'W45': {'id': 'W45', 'status': 'blocked'}, 'W47': {'id': 'W47', 'status': 'blocked'}}
        for jid, want in (('W45', None), ('W47', 'already has 3 rounds')):
            got = jv.not_ready('review', jid, by, set(), {jid: jv.Branch({'id': jid, 'status': 'review'}, 3)})
            self.assertTrue(got is None if want is None else want in got, (jid, got))

    def test_the_review_steps_name_the_last_round(self):
        self.assertIn('then round 4', jv.review_steps('W45', 2))
        self.assertIn('blocked_by="4 review rounds without merge"', jv.review_steps('W45', 3))
        self.assertNotIn('blocked_by', jv.review_steps('W45', 2))
        self.assertIn('blocked_by="3 review rounds without merge"', jv.review_steps('W47', 2))

    def test_read_grants_counts_rows_and_ignores_the_rest(self):
        with tempfile.TemporaryDirectory() as td:
            for name, body in (('a', {'grants_round': 'W45'}), ('b', {'grants_round': 'W45'}), ('c', {}), ('d', {'grants_round': 3})):
                Path(td, name + '.json').write_text(json.dumps(body), encoding='utf-8')
            Path(td, 'e.json').write_text('not json', encoding='utf-8')
            self.assertEqual(jv.read_grants(td), {'W45': 2})
        self.assertEqual(jv.read_grants(''), {})


if __name__ == '__main__':
    unittest.main()
