"""`wsc audit` (W44, C41): every rule fires on a repository built to trip it and stays quiet on one built not to.

Each fixture is a synthetic clone with a bare origin in a temp folder, its commits dated by hand; no test reads this repo's history.
"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from _util import main
from warscape import audit as A
from warscape.repo import ConfigError, Ctx, load_config

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
TOML = '''registries_dir = "registries"
[registries]
jobs = "core:jobs"
[storage]
dir = ["jobs"]
[views]
commit = false
[jobs]
id_prefix = "T"
[ci]
core = ""
workflows = ["gates.yml"]
required_checks = ["gates", "proxy"]
'''


def stamp(days):
    return (NOW - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S+00:00')


class Fixture:
    """A clone at `root` of a bare `origin`, on `main`. `extra` is appended to wsc.toml."""

    def __init__(self, extra=''):
        self.td = tempfile.TemporaryDirectory()
        base = Path(self.td.name).resolve()
        self.root, self.origin = base / 'clone', base / 'origin.git'
        self.only = None                                       # the metrics audit() asks for by default: a test of one rule pays for one metric
        self.root.mkdir()
        self.git('init', '-q', '--template=', '-b', 'main')    # no template: the Windows gates sit near [tests] timeout_s, so a fixture stays cheap
        self.git('remote', 'add', 'origin', str(self.origin))
        self.commit('Initial', {'wsc.toml': TOML + extra}, days=40)

    def git(self, *args, cwd=None, days=0):
        when = stamp(days)
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t',
               'GIT_AUTHOR_DATE': when, 'GIT_COMMITTER_DATE': when}
        return subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *args],
                              cwd=cwd or self.root, env=env, check=True, capture_output=True, text=True).stdout

    def write(self, files):
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8', newline='\n')

    def commit(self, subject, files, days):
        self.write(files)
        self.git('add', '-A')
        self.git('commit', '-q', '--allow-empty', '-m', subject, days=days)

    def row(self, jid, status='done', **more):
        return {f'registries/jobs/{jid}.json': json.dumps({'id': jid, 'title': jid, 'phase': 1, 'status': status, 'model': 'opus', 'needs_pc': False, **more})}

    def merge_job(self, n, days, files=None, **row):
        """A squash merge of job T<n> on main, with no branch."""
        self.commit(f'T{n}: job {n} (#{n})', {**self.row(f'T{n}', **row), **(files or {})}, days)

    def branch(self, name, start='main'):
        self.git('checkout', '-q', '-b', name, start)

    def main(self):
        self.git('checkout', '-q', 'main')

    def merge_main(self, days):
        """Merge main into the current branch, keeping ours where both sides touched a file."""
        self.git('merge', '-q', '--no-edit', '-X', 'ours', '--no-ff', 'main', days=days)

    def push(self):
        """A real push to the bare origin, for the tests that read it; the rest mirror their refs with sync()."""
        if not self.origin.exists():
            self.git('init', '-q', '--template=', '--bare', str(self.origin), cwd=self.root.parent)
        self.git('push', '-q', '--all', 'origin')
        self.git('fetch', '-q', 'origin')

    def sync(self):
        """What a push and a fetch leave in this clone, the refs under refs/remotes/origin/, without the transport."""
        heads = self.git('for-each-ref', '--format=%(refname:strip=2) %(objectname)', 'refs/heads/').split('\n')
        cmds = ''.join(f'update refs/remotes/origin/{b} {s}\n' for b, s in (l.split() for l in heads if l))
        subprocess.run(['git', 'update-ref', '--stdin'], cwd=self.root, input=cmds.encode(), check=True, capture_output=True)

    def ctx(self):
        return Ctx.load(self.root)

    def audit(self, offline=True, since=None, only=None, run=subprocess.run, now=NOW):
        self.sync() if offline else self.push()
        return A.record(self.ctx(), since=since, only=only or self.only, offline=offline, now=now, run=run)

    def ids(self, **kw):
        return sorted(f['id'] for f in self.audit(**kw)['findings'])

    def close(self):
        self.td.cleanup()


class Case(unittest.TestCase):
    ONLY = None                                                # the one metric a class tests; None: all of them

    def setUp(self):
        os.environ.pop('WSC_PC_STATE', None)

    def fixture(self, extra=''):
        f = Fixture(extra)
        f.only = [self.ONLY] if self.ONLY else None
        self.addCleanup(f.close)
        return f

    def finding(self, rec, fid):
        got = {x['id']: x for x in rec['findings']}
        self.assertIn(fid, got, sorted(got))
        return got[fid]


class HotFiles(Case):
    ONLY = 'hot_files'

    def test_fires_with_its_share_and_is_high_at_half(self):
        f = self.fixture()
        for n in range(1, 7):
            f.merge_job(n, 3, {'docs/HOT.md': f'{n}\n'} if n <= 5 else {'docs/other.md': 'x\n'})
        x = self.finding(f.audit(), 'hot_file:docs/HOT.md')
        self.assertEqual((x['metric'], x['subject'], x['severity'], x['direction']), ('hot_files', 'docs/HOT.md', 'high', 'above'))
        self.assertEqual((x['value'], x['threshold']), (0.8333, 0.25))
        self.assertIn('5 of 6', x['evidence'])

    def test_medium_under_half(self):
        f = self.fixture('[audit]\nhot_file_min = 2\n')
        for n in range(1, 6):                                  # 2 of 5
            f.merge_job(n, 3, {'docs/HOT.md': f'{n}\n'} if n <= 2 else {})
        self.assertEqual(self.finding(f.audit(), 'hot_file:docs/HOT.md')['severity'], 'medium')

    def test_quiet_under_the_count_the_share_and_outside_the_window(self):
        f = self.fixture('[audit]\nhot_file_min = 3\n')
        for n in range(1, 3):                                  # 2 of 2: the share trips, the count does not
            f.merge_job(n, 3, {'docs/FEW.md': f'{n}\n'})
        self.assertEqual([i for i in f.ids() if i.startswith('hot_file')], [])
        f.merge_job(3, 3, {'docs/FEW.md': '3\n'})
        for n in range(4, 14):                                 # 3 of 13: the count trips, the share does not
            f.merge_job(n, 3)
        self.assertEqual([i for i in f.ids() if i.startswith('hot_file')], [])
        g = self.fixture('[audit]\nhot_file_min = 2\n')
        for n in range(1, 3):
            g.merge_job(n, 20, {'docs/OLD.md': f'{n}\n'})      # older than the 7-day default window
        self.assertEqual([i for i in g.ids() if i.startswith('hot_file')], [])

    def test_the_job_folders_rows_and_hot_exempt_do_not_count(self):
        f = self.fixture('[audit]\nhot_exempt = ["VERSION"]\nhot_file_min = 2\n')
        for n in range(1, 3):
            f.merge_job(n, 3, {f'jobs/T{n}/report.md': 'r\n', 'jobs/shared.md': f'{n}\n', 'VERSION': f'{n}\n'})
        self.assertEqual([i for i in f.ids() if i.startswith('hot_file')], [])

    def test_only_job_merges_count(self):
        f = self.fixture('[audit]\nhot_file_min = 2\n')
        for n in range(1, 3):
            f.commit(f'plan: row {n} (#{n})', {'docs/PLAN.md': f'{n}\n'}, 3)
        self.assertEqual([i for i in f.ids() if i.startswith('hot_file')], [])


class ConflictFiles(Case):
    ONLY = 'conflict_files'

    def both_sides(self, f, n, path='docs/X.md'):
        """A job branch whose merge from main changed `path` on both sides, and left a result that differs from each."""
        f.commit(f'plan: main side {n} (#{n})', {path: f'base {n}\nmiddle\nend\n'}, 6)
        f.branch(f'job/T{n}')
        f.commit('branch side', {path: f'base {n}\nmiddle\nend branch {n}\n'}, 5)
        f.main()
        f.commit(f'plan: main moves {n} (#{n})', {path: f'base {n} main\nmiddle\nend\n'}, 5)
        f.git('checkout', '-q', f'job/T{n}')
        f.git('merge', '-q', '--no-edit', 'main', days=4)
        f.main()

    def test_fires_at_three_and_counts_what_it_read(self):
        f = self.fixture()
        for n in (1, 2, 3):
            self.both_sides(f, n)
        rec = f.audit()
        x = self.finding(rec, 'conflict_file:docs/X.md')
        self.assertEqual((x['value'], x['threshold'], x['metric']), (3, 3, 'conflict_files'))
        d = rec['metrics']['conflict_files']['details']
        self.assertEqual((d['merges'], d['branches']), (3, 3))

    def test_quiet_at_two_and_when_only_one_side_changed(self):
        f = self.fixture()
        for n in (1, 2):
            self.both_sides(f, n)
        self.assertEqual([i for i in f.ids() if i.startswith('conflict_file')], [])
        g = self.fixture()
        for n in (1, 2, 3):                                    # three merges, each file changed on one side only
            g.branch(f'job/T{n}')
            g.commit('branch', {'docs/BRANCH.md': f'{n}\n'}, 5)
            g.main()
            g.commit(f'plan: main (#{n})', {'docs/MAIN.md': f'{n}\n'}, 5)
            g.git('checkout', '-q', f'job/T{n}')
            g.git('merge', '-q', '--no-edit', 'main', days=4)
            g.main()
        rec = g.audit()
        self.assertEqual(rec['metrics']['conflict_files']['details']['merges'], 3)
        self.assertEqual([x['id'] for x in rec['findings'] if x['id'].startswith('conflict_file')], [])

    def test_a_merge_outside_the_window_does_not_count(self):
        f = self.fixture()
        for n in (1, 2, 3):
            self.both_sides(f, n)
        rec = f.audit(since='2026-11-04')
        self.assertEqual(rec['metrics']['conflict_files']['details']['merges'], 0)

    def test_a_clone_without_the_branches_says_so_offline(self):
        f = self.fixture()
        rec = f.audit()
        self.assertIn('conflict_files', [s['metric'] for s in rec['skipped']])
        self.assertNotIn('conflict_files', rec['metrics'])

    def test_online_it_fetches_the_branches(self):
        f = self.fixture()
        for n in (1, 2, 3):
            self.both_sides(f, n)
        f.push()
        clone = f.root.parent / 'second'
        f.git('clone', '-q', '--single-branch', '-b', 'main', str(f.origin), str(clone), cwd=f.root.parent)
        ctx = Ctx.load(clone)
        offline = A.record(ctx, since='2026-10-01', offline=True, now=NOW, only=['conflict_files'], run=gh_down)
        self.assertIn('conflict_files', [s['metric'] for s in offline['skipped']])
        online = A.record(ctx, since='2026-10-01', offline=False, now=NOW, only=['conflict_files'], run=gh_down)
        self.assertEqual(online['metrics']['conflict_files']['value'], {'docs/X.md': 3})


class JobLifetime(Case):
    ONLY = 'job_lifetime'

    def job(self, f, n, start, merged, files=None, from_main=False):
        f.branch(f'job/T{n}')
        f.commit('work', {f'src/{n}.py': 'x\n'}, start)
        if from_main:
            f.main()
            f.commit(f'plan: moves (#{n}0)', {f'docs/{n}.md': 'x\n'}, start - 0.1)
            f.git('checkout', '-q', f'job/T{n}')
            f.merge_main(start - 0.2)
        f.main()
        f.merge_job(n, merged, {f'src/{n}.py': 'x\n', **(files or {})})

    def test_long_job(self):
        f = self.fixture()
        self.job(f, 1, 3, 1)
        rec = f.audit()
        x = self.finding(rec, 'long_job:T1')
        self.assertEqual((x['value'], x['threshold'], x['direction']), (48.0, 24, 'above'))
        d = rec['metrics']['job_lifetime']['details']
        self.assertEqual((d['median_hours'], d['p90_hours'], d['jobs']), (48.0, 48.0, 1))

    def test_quiet_at_the_limit(self):
        f = self.fixture()
        self.job(f, 1, 2, 1)
        self.assertEqual([i for i in f.ids() if i.startswith('long_job')], [])

    def test_wide_job(self):
        f = self.fixture()
        self.job(f, 1, 2, 1.5, {f'src/w{i}.py': 'x\n' for i in range(60)})
        self.assertEqual(self.finding(f.audit(), 'wide_job:T1')['threshold'], 60)
        g = self.fixture()
        self.job(g, 1, 2, 1.5, {f'src/w{i}.py': 'x\n' for i in range(5)})
        self.assertEqual([i for i in g.ids() if i.startswith('wide_job')], [])

    def test_branch_exposure(self):
        f = self.fixture()
        self.job(f, 1, 2, 1.5, from_main=True)
        self.job(f, 2, 2, 1.5)
        rec = f.audit()
        self.assertEqual(self.finding(rec, 'branch_exposure')['value'], 0.5)
        self.assertEqual(rec['metrics']['job_lifetime']['value']['T1']['merges_from_main'], 1)
        g = self.fixture()
        self.job(g, 1, 2, 1.5, from_main=True)
        for n in (2, 3):
            self.job(g, n, 2, 1.5)
        self.assertNotIn('branch_exposure', g.ids())

    def test_a_job_without_a_branch_is_counted_not_measured(self):
        f = self.fixture()
        self.job(f, 1, 2, 1.5)
        f.merge_job(2, 1)
        d = f.audit()['metrics']['job_lifetime']['details']
        self.assertEqual((d['jobs'], d['no_branch']), (1, ['T2']))

    def test_a_job_merged_twice_is_measured_to_its_last_merge(self):
        f = self.fixture()
        self.job(f, 1, 4, 3.5)
        f.merge_job(1, 2)
        self.assertEqual(f.audit()['metrics']['job_lifetime']['value']['T1']['hours'], 48.0)


class WorkMix(Case):
    ONLY = 'work_mix'

    def test_off_by_default_and_counts_phases(self):
        f = self.fixture()
        for n in range(1, 4):
            f.merge_job(n, 3, phase=1)
        rec = f.audit()
        self.assertEqual(rec['metrics']['work_mix']['details']['phases'], {'1': 3})
        self.assertNotIn('overhead_share', [x['id'] for x in rec['findings']])

    def test_fires_over_the_share_of_the_last_jobs(self):
        f = self.fixture('[audit]\noverhead_phases = [1]\nwindow_jobs = 4\n')
        for n in range(1, 4):
            f.merge_job(n, 30, phase=2)                        # older than the last four: not read
        f.merge_job(4, 3, phase=2)
        for n in range(5, 8):
            f.merge_job(n, 3, phase=1)
        x = self.finding(f.audit(), 'overhead_share')
        self.assertEqual((x['value'], x['threshold']), (0.75, 0.4))

    def test_quiet_at_the_share(self):
        f = self.fixture('[audit]\noverhead_phases = [1]\nwindow_jobs = 5\n')
        for n, phase in enumerate((1, 1, 2, 2, 2), 1):
            f.merge_job(n, 3, phase=phase)
        self.assertNotIn('overhead_share', f.ids())


class Queue(Case):
    ONLY = 'queue'

    def test_idle_queue(self):
        f = self.fixture()
        f.commit('plan: rows (#1)', {**f.row('T1', 'queued'), **f.row('T2', 'queued')}, 1)
        rec = f.audit()
        self.assertEqual(self.finding(rec, 'idle_queue')['value'], 2)
        self.assertEqual(rec['metrics']['queue']['value']['ready'], 2)

    def test_a_branch_in_progress_keeps_it_quiet(self):
        f = self.fixture()
        f.commit('plan: rows (#1)', {**f.row('T1', 'queued'), **f.row('T2', 'queued')}, 1)
        f.branch('job/T1')
        f.main()
        rec = f.audit()
        self.assertNotIn('idle_queue', [x['id'] for x in rec['findings']])
        self.assertEqual(rec['metrics']['queue']['value']['progress'], 1)

    def test_a_row_in_review_on_its_branch_keeps_it_quiet(self):
        f = self.fixture()
        f.commit('plan: rows (#1)', {**f.row('T1', 'queued'), **f.row('T2', 'queued')}, 1)
        f.branch('job/T1')
        f.commit('report', f.row('T1', 'review'), 1)
        f.main()
        rec = f.audit()
        self.assertEqual(rec['metrics']['queue']['value']['review'], 1)
        self.assertNotIn('idle_queue', [x['id'] for x in rec['findings']])

    def test_no_ready_rows_is_not_idle(self):
        f = self.fixture()
        f.commit('plan: row (#1)', f.row('T1', 'needs_brief'), 1)
        self.assertNotIn('idle_queue', f.ids())

    def pc_rows(self, f, pc, plain):
        rows = {}
        for n in range(1, pc + 1):
            rows.update(f.row(f'T{n}', 'queued', needs_pc=True))
        for n in range(pc + 1, pc + plain + 1):
            rows.update(f.row(f'T{n}', 'queued'))
        f.commit('plan: rows (#1)', rows, 1)

    def test_pc_serial(self):
        f = self.fixture()
        self.pc_rows(f, 3, 1)
        self.assertEqual(self.finding(f.audit(), 'pc_serial')['value'], 0.75)

    def test_pc_serial_quiet_under_either_limit(self):
        f = self.fixture()
        self.pc_rows(f, 3, 0)
        self.assertNotIn('pc_serial', f.ids())
        g = self.fixture()
        self.pc_rows(g, 2, 2)
        self.assertNotIn('pc_serial', g.ids())

    def test_the_lanes_do_not_depend_on_this_machines_pc(self):
        f = self.fixture('[jobs]\n') if False else self.fixture()
        self.pc_rows(f, 4, 0)
        with mock.patch.dict(os.environ, {'WSC_PC_STATE': ''}):    # "no PC here": jobs view shows these as waiting
            rec = f.audit()
        self.assertEqual(rec['metrics']['queue']['value']['ready'], 4)
        self.assertIn('pc_serial', [x['id'] for x in rec['findings']])

    def chain(self, f, status):
        rows = f.row('T1', status)
        rows.update(f.row('T2', 'queued', depends_on=['T1']))
        rows.update(f.row('T3', 'queued', depends_on=['T1']))
        rows.update(f.row('T4', 'queued', depends_on=['T2']))   # indirect
        rows.update(f.row('T5', 'needs_brief', depends_on=['T4']))
        rows.update(f.row('T6', 'done', depends_on=['T1']))     # done: not gated
        f.commit('plan: rows (#1)', rows, 1)

    def test_chokepoint_counts_indirect_rows_and_is_high_without_a_brief(self):
        f = self.fixture()
        self.chain(f, 'needs_brief')
        x = self.finding(f.audit(), 'chokepoint:T1')
        self.assertEqual((x['value'], x['threshold'], x['severity'], x['subject']), (4, 4, 'high', 'T1'))

    def test_chokepoint_medium_with_a_brief_and_quiet_under_the_fanout(self):
        f = self.fixture()
        self.chain(f, 'queued')
        rec = f.audit()
        self.assertEqual(self.finding(rec, 'chokepoint:T1')['severity'], 'medium')
        self.assertNotIn('chokepoint:T2', [x['id'] for x in rec['findings']])

    def test_a_done_row_is_no_chokepoint_and_a_cycle_ends(self):
        f = self.fixture()
        self.chain(f, 'done')
        self.assertNotIn('chokepoint:T1', f.ids())
        g = self.fixture()
        g.commit('plan: rows (#1)', {**g.row('T1', 'queued', depends_on=['T2']), **g.row('T2', 'queued', depends_on=['T1'])}, 1)
        self.assertNotIn('chokepoint:T1', g.ids())


ROUND = '## Round {n} (2026-11-01, branch `job/T1` at `abcdef0`)\n\n{body}\n\nVerdict: {verdict}\n\n'


class ReviewLoop(Case):
    ONLY = 'review_loop'

    def review(self, *verdicts, later=0):
        text = '# Review\n\n' + ''.join(ROUND.format(n=i, verdict=v, body='**Later:** a thing\n' * later) for i, v in enumerate(verdicts, 1))
        return text

    def test_review_churn(self):
        f = self.fixture()
        f.merge_job(1, 3, {'jobs/T1/review.md': self.review('merge after fixes', 'merge')})
        f.merge_job(2, 3, {'jobs/T2/review.md': self.review('do not merge', 'merge')})
        f.merge_job(3, 3, {'jobs/T3/review.md': self.review('merge')})
        rec = f.audit()
        x = self.finding(rec, 'review_churn')
        self.assertEqual((x['value'], x['threshold'], x['direction']), (0.3333, 0.5, 'below'))
        self.assertEqual(rec['metrics']['review_loop']['details']['rounds'], {'T1': 2, 'T2': 2, 'T3': 1})

    def test_quiet_at_the_share_and_counts_later_lines(self):
        f = self.fixture()
        f.merge_job(1, 3, {'jobs/T1/review.md': self.review('merge', later=2)})
        f.merge_job(2, 3, {'jobs/T2/review.md': self.review('merge after fixes', 'merge', later=1) + '**Why later:** not one\n'})
        rec = f.audit()
        self.assertNotIn('review_churn', [x['id'] for x in rec['findings']])
        self.assertEqual(rec['metrics']['review_loop']['details']['later'], 4)

    def test_one_round_that_asked_for_fixes_is_not_a_round_1_merge(self):
        f = self.fixture()
        f.merge_job(1, 3, {'jobs/T1/review.md': self.review('merge after fixes')})
        self.assertEqual(f.audit()['metrics']['review_loop']['value'], 0.0)

    def test_no_reviews_is_no_finding(self):
        f = self.fixture()
        f.merge_job(1, 3)
        rec = f.audit()
        self.assertIsNone(rec['metrics']['review_loop']['value'])
        self.assertNotIn('review_churn', [x['id'] for x in rec['findings']])

    def test_a_job_not_done_on_main_does_not_count(self):
        f = self.fixture()
        f.merge_job(1, 3, {'jobs/T1/review.md': self.review('do not merge', 'merge')}, status='review')
        self.assertIsNone(f.audit()['metrics']['review_loop']['value'])


class BriefCost(Case):
    ONLY = 'brief_cost'

    def test_brief_heavy(self):
        f = self.fixture()
        f.merge_job(1, 3, {'jobs/T1/brief.md': 'b' * 400, 'jobs/T1/report.md': 'r' * 100})
        f.commit('brief: T2 next (#2)', {}, 3)
        rec = f.audit()
        x = self.finding(rec, 'brief_heavy')
        self.assertEqual((x['value'], x['threshold']), (4.0, 1.5))
        d = rec['metrics']['brief_cost']['details']
        self.assertEqual((d['median_brief'], d['median_report'], d['brief_merges'], d['job_merges']), (400, 100, 1, 1))

    def test_quiet_at_the_ratio_and_without_reports(self):
        f = self.fixture()
        f.merge_job(1, 3, {'jobs/T1/brief.md': 'b' * 150, 'jobs/T1/report.md': 'r' * 100})
        self.assertNotIn('brief_heavy', f.ids())
        g = self.fixture()
        g.merge_job(1, 3, {'jobs/T1/brief.md': 'b' * 150})
        self.assertNotIn('brief_heavy', g.ids())


class StartupRead(Case):
    ONLY = 'startup_read'

    def test_startup_heavy_with_startup_docs(self):
        f = self.fixture('[audit]\nstartup_docs = ["docs/PLAN.md", "docs/GONE.md"]\n')
        f.commit('plan: docs (#1)', {'CLAUDE.md': 'c' * 20480, 'README.md': 'r' * 10240, 'docs/PLAN.md': 'p' * 20480}, 1)
        rec = f.audit()
        x = self.finding(rec, 'startup_heavy')
        self.assertEqual((x['value'], x['threshold']), (50.0, 40))
        self.assertEqual(rec['metrics']['startup_read']['details']['missing'], ['docs/GONE.md'])

    def test_quiet_under(self):
        f = self.fixture()
        f.commit('plan: docs (#1)', {'CLAUDE.md': 'c' * 20480, 'docs/PLAN.md': 'p' * 40960}, 1)
        self.assertNotIn('startup_heavy', f.ids())


class DocCaps(Case):
    ONLY = 'doc_caps'

    def test_fires_at_the_share_and_skips_a_dated_record(self):
        f = self.fixture()
        at = int(30 * 1024 * 0.9)
        f.commit('plan: docs (#1)', {'docs/BIG.md': 'x' * at, 'docs/SMALL.md': 'x' * (at - 1), 'docs/audits/AUDIT_2026-11-01.md': 'x' * 40000}, 1)
        ids = f.ids()
        self.assertIn('doc_cap:docs/BIG.md', ids)
        self.assertEqual([i for i in ids if i.startswith('doc_cap')], ['doc_cap:docs/BIG.md'])

    def test_it_reads_main_not_the_working_tree(self):
        f = self.fixture()
        f.commit('plan: doc (#1)', {'docs/A.md': 'small\n'}, 1)
        f.write({'docs/A.md': 'x' * 30000})
        self.assertEqual([i for i in f.ids() if i.startswith('doc_cap')], [])


class PinLag(Case):
    ONLY = 'pin_lag'

    def core(self, f, *tags):
        c = f.root / 'core'
        c.mkdir()
        f.git('init', '-q', '-b', 'main', cwd=c)
        f.git('commit', '-q', '--allow-empty', '-m', 'core', cwd=c)
        for t in tags:
            f.git('tag', t, cwd=c)

    def game(self, version):
        toml = f'[ci]\ncore = "core"\n[core]\nversion = "{version}"\n'
        f = self.fixture()
        f.write({'wsc.toml': TOML.replace('core = ""\n', 'core = "core"\n') + f'[core]\nversion = "{version}"\n'})
        f.write({'.gitignore': 'core/\n'})
        f.git('add', '-A')
        f.git('commit', '-q', '-m', 'plan: pin (#1)', days=1)
        return f

    def test_fires_at_five_minors(self):
        f = self.game('0.36.0')
        self.core(f, 'v0.40.0', 'v0.41.0', 'v0.9.0', 'V0.99.0', 'not-a-version')
        x = self.finding(f.audit(), 'pin_lag')
        self.assertEqual((x['value'], x['threshold']), (5, 5))
        self.assertIn('0.41.0', x['evidence'])

    def test_a_pin_written_with_its_v_is_read(self):
        f = self.game('v0.30.0')                               # napoleon's wsc.toml writes it this way
        self.core(f, 'v0.41.0')
        self.assertEqual(self.finding(f.audit(), 'pin_lag')['value'], 11)

    def test_quiet_under_and_a_newer_major_counts(self):
        f = self.game('0.37.2')
        self.core(f, 'v0.41.0')
        self.assertNotIn('pin_lag', f.ids())
        g = self.game('0.41.0')
        self.core(g, 'v1.0.0')
        self.assertIn('pin_lag', g.ids())

    def test_the_core_itself_has_no_pin(self):
        rec = self.fixture().audit()
        self.assertEqual([s for s in rec['skipped'] if s['metric'] == 'pin_lag'][0]['reason'], '[ci] core is empty: this repo pins no core')
        self.assertEqual(rec['failed'], [])

    def test_a_submodule_not_checked_out_is_skipped(self):
        f = self.game('0.36.0')
        self.assertIn('pin_lag', [s['metric'] for s in f.audit()['skipped']])


class Throughput(Case):
    ONLY = 'throughput'

    def test_slowdown(self):
        f = self.fixture()
        for n in range(1, 7):
            f.merge_job(n, 10)
        f.commit('brief: T7 (#7)', {}, 9)
        f.merge_job(8, 3)
        rec = f.audit()
        x = self.finding(rec, 'slowdown')
        self.assertEqual((x['value'], x['threshold'], x['direction']), (0.1429, 0.5, 'below'))
        d = rec['metrics']['throughput']['details']
        self.assertEqual((d['jobs'], d['briefs'], d['prior_jobs'], d['prior_briefs']), (1, 0, 6, 1))

    def test_quiet_at_the_ratio_and_with_no_window_before(self):
        f = self.fixture()
        f.merge_job(1, 10)
        f.merge_job(2, 9)
        f.merge_job(3, 3)
        self.assertNotIn('slowdown', f.ids())
        g = self.fixture()
        g.merge_job(1, 3)
        rec = g.audit()
        self.assertIsNone(rec['metrics']['throughput']['value'])

    def test_the_kinds_of_every_subject_are_counted(self):
        f = self.fixture()
        for s in ('T1: a job (#1)', 'T2 a job (#2)', 'brief: T3 (#3)', 'brief/T4: b (#4)', 'plan: p (#5)', 'meta: m (#6)', 'release v1.0.0 (minor): T1 (#7)', 'Backlog B1 (#8)'):
            f.commit(s, {}, 3)
        k = f.audit()['metrics']['throughput']['details']['kinds']
        self.assertEqual(k, {'job': 2, 'brief': 2, 'plan': 1, 'meta': 1, 'release': 1, 'other': 1})


def gh_down(argv, **kw):
    if argv[0] == 'gh':
        return subprocess.CompletedProcess(argv, 1, '', 'gh: not logged in')
    return subprocess.run(argv, **kw)


def gh_runs(minutes):
    """A runner whose `gh api` serves one run per entry of `minutes` ([{check: minutes or (minutes, conclusion)}]) for gates.yml."""
    calls = []

    def run(argv, **kw):
        if argv[0] != 'gh':
            return subprocess.run(argv, **kw)
        path = argv[2]
        calls.append(path)
        if '/runs?' in path:
            return subprocess.CompletedProcess(argv, 0, json.dumps({'workflow_runs': [{'id': i} for i in range(len(minutes))]}), '')
        rid = int(path.split('/runs/')[1].split('/')[0])
        jobs = []
        for name, v in minutes[rid].items():
            m, c = v if isinstance(v, tuple) else (v, 'success')
            jobs.append({'name': name, 'conclusion': c, 'started_at': '2026-11-01T10:00:00Z',
                         'completed_at': (datetime(2026, 11, 1, 10, tzinfo=timezone.utc) + timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M:%SZ')})
        return subprocess.CompletedProcess(argv, 0, json.dumps({'jobs': jobs}), '')
    run.calls = calls
    return run


class CiDurations(Case):
    ONLY = 'ci_durations'

    def test_slow_check(self):
        f = self.fixture()
        rec = f.audit(offline=False, run=gh_runs([{'gates': 12, 'proxy': 4, 'other': 99}, {'gates': 14, 'proxy': 5}, {'gates': 2, 'proxy': 6}]))
        x = self.finding(rec, 'slow_check:gates')
        self.assertEqual((x['value'], x['threshold'], x['subject']), (12.0, 10, 'gates'))
        self.assertEqual(sorted(rec['metrics']['ci_durations']['value']), ['gates', 'proxy'])

    def test_a_skipped_job_has_no_duration_and_the_table_overrides(self):
        f = self.fixture('[audit]\nci_check_default = 3\n[audit.ci_check_minutes]\ngates = 20\n')
        rec = f.audit(offline=False, run=gh_runs([{'gates': 12, 'proxy': 4}, {'gates': 12, 'proxy': (0, 'skipped')}]))
        ids = [x['id'] for x in rec['findings']]
        self.assertNotIn('slow_check:gates', ids)
        self.assertIn('slow_check:proxy', ids)
        self.assertEqual(rec['metrics']['ci_durations']['details']['runs']['proxy'], 1)

    def test_quiet_at_the_limit_and_asks_for_ci_runs(self):
        f = self.fixture('[audit]\nci_runs = 7\n')
        run = gh_runs([{'gates': 10, 'proxy': 1}])
        self.assertEqual([i for i in f.ids(offline=False, run=run) if i.startswith('slow_check')], [])
        self.assertIn('per_page=7', run.calls[0])

    def test_offline_is_skipped_and_gh_is_never_run(self):
        f = self.fixture()
        run = mock.Mock(side_effect=lambda argv, **kw: self.fail('gh ran') if argv[0] == 'gh' else subprocess.run(argv, **kw))
        rec = f.audit(offline=True, run=run)
        self.assertEqual([s['reason'] for s in rec['skipped'] if s['metric'] == 'ci_durations'], ['--offline'])
        self.assertEqual(rec['failed'], [])

    def test_gh_unreadable_is_skipped_not_failed(self):
        f = self.fixture()
        rec = f.audit(offline=False, run=gh_down)
        self.assertIn('not logged in', [s['reason'] for s in rec['skipped'] if s['metric'] == 'ci_durations'][0])
        self.assertEqual(rec['failed'], [])


class Record(Case):
    def tripped(self):
        f = self.fixture()
        for n in range(1, 7):
            f.merge_job(n, 3, {'docs/HOT.md': f'{n}\n', 'jobs/T%d/report.md' % n: 'r\n'})
        f.commit('plan: rows (#9)', {**f.row('T7', 'queued')}, 1)
        return f

    def test_the_shape(self):
        f = self.tripped()
        rec = f.audit()
        self.assertEqual(rec['version'], 1)
        self.assertEqual(sorted(rec), ['date', 'failed', 'findings', 'main', 'metrics', 'repo', 'skipped', 'version', 'window'])
        self.assertEqual(rec['repo'], 'origin')                # the remote's name, never the clone or worktree folder's
        self.assertEqual(rec['date'], '2026-11-05')
        self.assertEqual(rec['main'], f.git('rev-parse', 'origin/main').strip())
        self.assertEqual(rec['window'], {'since': '2026-10-29', 'until': '2026-11-05', 'job_merges': 6})
        for x in rec['findings']:
            self.assertEqual(sorted(x), ['direction', 'evidence', 'id', 'metric', 'severity', 'subject', 'threshold', 'value'])
            self.assertEqual(x['id'].split(':')[0] + (':' + x['subject'] if x['subject'] else ''), x['id'])
        for m in rec['metrics'].values():
            self.assertEqual(sorted(m), ['details', 'value'])
        json.dumps(rec, allow_nan=False)

    def test_a_finding_id_is_the_same_across_two_runs(self):
        f = self.tripped()
        first = f.audit()
        second = f.audit(now=NOW + timedelta(hours=2))
        self.assertTrue(first['findings'])
        self.assertEqual([x['id'] for x in first['findings']], [x['id'] for x in second['findings']])

    def test_the_markdown_is_a_pure_function_of_the_json(self):
        rec = self.tripped().audit()
        text = A.render_md(rec)
        self.assertEqual(text, A.render_md(json.loads(json.dumps(rec))))
        for x in rec['findings']:
            self.assertIn(x['id'], text)
        for s in rec['skipped']:
            self.assertIn(s['metric'], text)
        other = json.loads(json.dumps(rec))
        other['main'] = 'f' * 40
        self.assertNotEqual(text, A.render_md(other))

    def test_only_names_the_rest_as_skipped(self):
        f = self.tripped()
        rec = f.audit(only=['hot_files'])
        self.assertEqual(list(rec['metrics']), ['hot_files'])
        self.assertEqual({s['metric'] for s in rec['skipped']}, set(A.METRICS) - {'hot_files'})
        self.assertEqual({x['metric'] for x in rec['findings']}, {'hot_files'})

    def test_since_a_sha_starts_after_it(self):
        f = self.fixture()
        f.merge_job(1, 3)
        sha = f.git('rev-parse', 'HEAD').strip()
        f.merge_job(2, 3)
        rec = f.audit(since=sha)
        self.assertEqual(rec['window']['job_merges'], 1)
        self.assertEqual(rec['metrics']['hot_files']['details']['job_merges'], 1)

    def test_head_measures_an_older_main(self):
        f = self.fixture()
        f.merge_job(1, 3)
        sha = f.git('rev-parse', 'HEAD').strip()
        f.merge_job(2, 3)
        f.push()
        rec = A.record(f.ctx(), since='2026-10-01', offline=True, now=NOW, head=sha)
        self.assertEqual((rec['main'], rec['window']['job_merges']), (sha, 1))

    def test_bad_input_is_refused(self):
        f = self.fixture()
        for kw in ({'since': 'no-such-rev'}, {'since': '2026-13-45'}, {'only': ['nope']}):
            with self.assertRaises(ValueError):
                f.audit(**kw)


class Config(Case):
    def test_every_threshold_has_a_default_and_a_game_can_name_a_check(self):
        f = self.fixture('[audit]\nhot_file_min = 9\n[audit.ci_check_minutes]\n"gates (ubuntu-latest)" = 15\n')
        cfg = load_config(f.root)['audit']
        self.assertEqual((cfg['hot_file_min'], cfg['hot_file_share'], cfg['dir']), (9, 0.25, 'docs/audits'))
        self.assertEqual(cfg['ci_check_minutes'], {'gates (ubuntu-latest)': 15})

    def test_a_wrong_key_or_type_is_refused(self):
        for extra in ('[audit]\nno_such = 1\n', '[audit]\nhot_file_share = "a lot"\n', '[audit]\nhot_exempt = "VERSION"\n', '[audit]\nwindow_days = 0\n'):
            f = self.fixture(extra)
            with self.assertRaises(ConfigError):
                load_config(f.root)


class Verb(Case):
    def wsc(self, root, *args, run=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(['--root', str(root), 'audit', *args])
        return rc, out.getvalue(), err.getvalue()

    def tripped(self):
        f = self.fixture('[audit]\ndir = "docs/audits"\n')
        for n in range(1, 7):
            f.merge_job(n, 0.5, {'docs/HOT.md': f'{n}\n'})
        f.push()
        return f

    def test_offline_exits_0_and_prints_one_line_per_finding(self):
        f = self.tripped()
        rc, out, _ = self.wsc(f.root, '--offline')
        self.assertEqual(rc, 0)
        self.assertEqual(len([l for l in out.splitlines() if 'hot_file:docs/HOT.md' in l]), 1)
        got = list((f.root / '_scratch' / 'audits').glob('AUDIT_*'))
        self.assertEqual(sorted(p.suffix for p in got), ['.json', '.md'])
        rec = json.loads([p for p in got if p.suffix == '.json'][0].read_text(encoding='utf-8'))
        self.assertIn('ci_durations', [s['metric'] for s in rec['skipped']])
        self.assertEqual([p for p in got if p.suffix == '.md'][0].read_text(encoding='utf-8'), A.render_md(rec))

    def test_record_writes_the_dir_and_a_second_gets_2(self):
        f = self.tripped()
        for _ in range(2):
            self.assertEqual(self.wsc(f.root, '--offline', '--record')[0], 0)
        names = sorted(p.name for p in (f.root / 'docs' / 'audits').iterdir())
        date = names[0][len('AUDIT_'):len('AUDIT_') + 10]
        self.assertEqual(names, [f'AUDIT_{date}.json', f'AUDIT_{date}.md', f'AUDIT_{date}_2.json', f'AUDIT_{date}_2.md'])

    def test_json_replaces_the_default_output_so_nothing_is_written_in_the_repo(self):
        f = self.tripped()
        out = f.root.parent / 'elsewhere' / 'a.json'
        before = f.git('status', '--porcelain', '--ignored')
        rc, _, _ = self.wsc(f.root, '--offline', '--json', str(out))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['version'], 1)
        self.assertTrue(out.with_suffix('.md').is_file())
        self.assertEqual(f.git('status', '--porcelain', '--ignored'), before)
        self.assertFalse((f.root / '_scratch').exists())

    def test_a_metric_that_breaks_exits_1_and_the_rest_are_measured(self):
        f = self.tripped()
        with mock.patch.dict(A.FUNCS, {'doc_caps': mock.Mock(side_effect=KeyError('boom'))}):
            rc, out, _ = self.wsc(f.root, '--offline')
        self.assertEqual(rc, 1)
        self.assertIn('doc_caps', out)
        self.assertIn('hot_file:docs/HOT.md', out)

    def test_an_unreadable_repo_exits_2(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        Path(td.name, 'wsc.toml').write_text(TOML, encoding='utf-8')
        env = {'GIT_CEILING_DIRECTORIES': str(Path(td.name).resolve().parent)}
        with mock.patch.dict(os.environ, env):
            rc, _, err = self.wsc(td.name, '--offline')
        self.assertEqual(rc, 2)
        self.assertIn('audit', err)

    def test_only_with_a_bad_name_exits_2(self):
        f = self.tripped()
        rc, _, err = self.wsc(f.root, '--offline', '--only', 'hot_files,nope')
        self.assertEqual(rc, 2)
        self.assertIn('nope', err)


if __name__ == '__main__':
    unittest.main()
