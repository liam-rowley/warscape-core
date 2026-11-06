"""W132: the owner can grant a blocked job one more review round.

The grant is a decision row with `grants_round: <job id>`. Two halves:
- the judge: `wsc policy` (parent and `--judge` child, real commits on real branch names in a throwaway clone of this checkout) refuses the row on every
  branch kind but `meta/` (and `decide/`): `plan/` merges itself and a `job/` branch is the job's own;
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
        {'id': f'C261106-{i}', 'date': '2026-11-06', 'who': 'Liam', 'decision': 'One more round.', 'reversible': 'yes',
         **({'grants_round': job} if job else {}), **extra}, indent=2) + '\n'}


def jobs_row(jid, **kw):
    return {f'registries/jobs/{jid}.json': json.dumps({'id': jid, 'title': 'A test job', 'status': 'queued', 'brief': f'jobs/{jid}/brief.md', **kw}, indent=2) + '\n'}


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
        cls.commit(cls, {**jobs_row('W901', status='blocked', blocked_by=BY, review='jobs/W901/review.md', semver='none'),
                         **jobs_row('W902'), 'jobs/W902/brief.md': '# W902: queued\n', 'jobs/W901/brief.md': '# W901: blocked\n'})
        git(cls.d, 'update-ref', 'refs/remotes/origin/main', 'main')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def judge(self, name, files):
        self.branch(name, files, trailer='S1')
        rc, out, err = self.local(name)
        self.assertNotIn('Traceback', err)
        return rc, out + err

    def test_a_grant_on_meta_is_accepted(self):
        rc, out = self.judge('meta/grant', row_file('aaaa'))
        self.assertEqual(rc, 0, out)

    def test_a_grant_is_refused_on_plan_brief_release_and_job_branches(self):
        for i, name in enumerate(['plan/grant', 'brief/W902', 'release/v9.9.9', 'job/W901', 'job/W902']):
            rc, out = self.judge(name, row_file(f'b00{i}', job='W901' if name != 'job/W902' else 'W901'))
            self.assertEqual(rc, 1, f'{name}: {out}')
            self.assertIn("grants_round is the owner's alone", out, name)

    def test_a_grant_for_a_job_that_is_not_blocked_is_refused(self):
        rc, out = self.judge('meta/not-blocked', row_file('cccc', job='W902'))
        self.assertEqual(rc, 1, out)
        self.assertIn('not blocked by its review rounds', out)

    def test_a_grant_for_no_job_is_refused(self):
        for i, job in enumerate(['W999', 'nope', 7]):
            rc, out = self.judge('meta/nojob', row_file(f'dd0{i}', job=job))
            self.assertEqual(rc, 1, f'{job!r}: {out}')

    def test_a_row_without_the_field_is_a_plain_decision(self):
        rc, out = self.judge('plan/plain', row_file('eeee', job=None))
        self.assertEqual(rc, 0, out)

    def test_a_merged_grant_cannot_change(self):
        self.branch('meta/first', row_file('ffff'), trailer='S1')
        git(self.d, 'checkout', '-q', '-f', 'main')
        git(self.d, 'merge', '-q', '--ff-only', 'meta/first')
        git(self.d, 'update-ref', 'refs/remotes/origin/main', 'main')
        try:
            rc, out = self.judge('meta/change', row_file('ffff', decision='Two more rounds.'))
            self.assertEqual(rc, 1, out)
            self.assertIn('append only', out)
        finally:
            git(self.d, 'reset', '-q', '--hard', 'HEAD~1')
            git(self.d, 'update-ref', 'refs/remotes/origin/main', 'main')


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
