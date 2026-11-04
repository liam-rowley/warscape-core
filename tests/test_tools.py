import datetime
import json
import unittest

from _util import TOOL_PY, TempRepo
from warscape import tools
from warscape.registry import load_all
from warscape.repo import Ctx


class Headers(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()

    def tearDown(self):
        self.repo.close()

    def test_comment_docstring_and_batch_forms(self):
        p = self.repo.write('a.py', TOOL_PY.format(name='a.py'))
        self.assertEqual(tools.read_header(p), {'purpose': 'Do a thing for the tests.', 'usage': 'python3 a.py', 'when': 'in tests only.', 'not_a_verb': 'a test fixture.'})
        p = self.repo.write('b.py', '"""\nPurpose: B things.\nUsage (cloud): python3 b.py\nWhen to use: rarely.\nVerb: bee\n"""\nx = 1\n')
        self.assertEqual(tools.read_header(p), {'purpose': 'B things.', 'usage': 'python3 b.py', 'when': 'rarely.', 'verb': 'bee'})
        p = self.repo.write('c.cmd', '@echo off\nrem purpose: C things\nrem usage: c.cmd\nrem when: on Windows\nrem not a verb: runs in cmd.exe\n')
        self.assertEqual(tools.read_header(p)['not_a_verb'], 'runs in cmd.exe')
        p = self.repo.write('d.lua', '-- purpose: D\n-- purpose: second wins nothing\n')
        self.assertEqual(tools.read_header(p)['purpose'], 'D')

    def test_header_must_be_in_the_first_40_lines(self):
        p = self.repo.write('late.py', '\n' * 45 + '# purpose: too late\n')
        self.assertEqual(tools.read_header(p), {})

    def test_header_problems(self):
        self.assertTrue(any('neither' in e for e in tools.header_problems({'purpose': 'p', 'usage': 'u', 'when': 'w'})))
        self.assertTrue(any('both' in e for e in tools.header_problems({'purpose': 'p', 'usage': 'u', 'when': 'w', 'verb': 'v', 'not_a_verb': 'r'})))
        self.assertEqual(tools.header_problems({'purpose': 'p', 'usage': 'u', 'when': 'w', 'verb': 'v'}), [])
        self.assertEqual(len(tools.header_problems({})), 4)

    def test_slug(self):
        self.assertEqual(tools.slug('adapter/tools/pc_sync.py'), 'adapter.tools.pc_sync')
        self.assertEqual(tools.slug('.githooks/pre-push'), 'githooks.pre-push')
        self.assertEqual(tools.slug('Scripts/Run Me.cmd'), 'scripts.run-me')


class Coverage(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo({'adapter/sync.py': TOOL_PY.format(name='adapter/sync.py'), 'notes.txt': 'not a tool'})
        self.repo.wsc('reg', 'render')

    def tearDown(self):
        self.repo.close()

    def check(self):
        ctx = Ctx.load(self.repo.root)
        return tools.check(ctx, load_all(ctx)['tools'])

    def test_missing_row_then_add_then_drift(self):
        errs, _ = self.check()
        self.assertEqual(len(errs), 1)
        self.assertIn('without a registry row', errs[0])
        rc, out = self.repo.wsc('reg', 'add', 'tools', str(self.repo.root / 'adapter/sync.py'))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.check(), ([], []))
        self.repo.write('adapter/sync.py', TOOL_PY.format(name='adapter/sync.py').replace('Do a thing', 'Do another thing'))
        errs, _ = self.check()
        self.assertIn('differs from the file header in purpose', errs[0])

    def test_header_fields_cannot_be_set_by_hand(self):
        self.repo.wsc('reg', 'add', 'tools', '--missing')
        rc, out = self.repo.wsc('reg', 'set', 'tools', 'adapter.sync', 'purpose=hand edit')
        self.assertEqual(rc, 2)
        self.assertIn('come from the file header', out)

    def test_add_refuses_a_file_without_a_header(self):
        self.repo.write('bare.py', 'print(1)\n')
        rc, out = self.repo.wsc('reg', 'add', 'tools', str(self.repo.root / 'bare.py'))
        self.assertEqual(rc, 2)
        self.assertIn('no `purpose:` line', out)

    def test_removed_file_superseded_chain_and_retirement(self):
        self.repo.write('adapter/sync2.py', TOOL_PY.format(name='adapter/sync2.py'))
        self.assertEqual(self.repo.wsc('reg', 'add', 'tools', '--missing')[0], 0)
        (self.repo.root / 'adapter/sync.py').unlink()
        errs, _ = self.check()
        self.assertTrue(any('live row whose file' in e for e in errs), errs)
        self.assertEqual(self.repo.wsc('reg', 'set', 'tools', 'adapter.sync', 'status=superseded:adapter.sync2')[0], 0)
        self.assertEqual(self.check(), ([], []))
        rc, out = self.repo.wsc('reg', 'set', 'tools', 'adapter.sync2', 'status=superseded:nothing')
        errs, _ = self.check()
        self.assertTrue(any("superseded by 'nothing'" in e for e in errs), errs)
        self.repo.wsc('reg', 'set', 'tools', 'adapter.sync2', 'status=live', 'last_used=2020-01-01')
        self.assertEqual(self.check(), ([], []))            # retirement warnings are off by default
        self.repo.write('wsc.toml', self.repo.read('wsc.toml') + '\n[tools]\nretire_after_days = 90\n')
        errs, warns = self.check()
        self.assertEqual(errs, [])
        self.assertIn('retire', warns[0])

    def test_a_moved_tool_keeps_its_id(self):
        self.repo.wsc('reg', 'add', 'tools', '--missing')
        (self.repo.root / 'adapter/sync.py').rename(self.repo.root / 'adapter/pc_sync.py')
        rc, out = self.repo.wsc('reg', 'add', 'tools', str(self.repo.root / 'adapter/pc_sync.py'), '--id', 'adapter.sync')
        self.assertEqual(rc, 0, out)
        ctx = Ctx.load(self.repo.root)
        self.assertEqual([(r['id'], r['path']) for r in load_all(ctx)['tools'].rows], [('adapter.sync', 'adapter/pc_sync.py')])
        self.assertEqual(self.check(), ([], []))

    def test_library_and_exempt_globs(self):
        self.repo.write('wsc.toml', self.repo.read('wsc.toml') + '\n[tools]\nlibrary = ["lib/**"]\nexempt = ["runs/**"]\n')
        self.repo.write('lib/deep/helper.py', 'x = 1\n')
        self.repo.write('runs/20261028_a/probe.py', 'x = 1\n')
        self.repo.wsc('reg', 'add', 'tools', '--missing')
        self.assertEqual(self.check(), ([], []))


JOBS_TOML = '''
registries_dir = "registries"
[registries]
tools = "core:tools"
jobs = "core:jobs"
[storage]
dir = ["jobs"]
[views]
commit = false
[tests]
dirs = []
'''
VERB_PY = '''"""
Purpose: A verb for the tests.
Usage: wsc reg ...
When: in tests only.
Verb: reg
"""
'''
SH = '''#!/bin/sh
# purpose: A shell tool for the tests.
# usage: harness/job.sh
# when: in tests only.
# not-a-verb: a test fixture.
'''


def ago(days):
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


class LastUse(unittest.TestCase):
    """B6: a tool's last use is derived from merged (done) job reports that cite it (decision 2 of W15)."""

    def setUp(self):
        self.repo = TempRepo({'harness/job.sh': SH, 'tools/regv.py': VERB_PY, 'tools/other.py': TOOL_PY.format(name='tools/other.py'),
                              'tools/idle.py': TOOL_PY.format(name='tools/idle.py')}, toml=JOBS_TOML)
        self.addCleanup(self.repo.close)
        self.assertEqual(self.repo.wsc('reg', 'add', 'tools', '--missing')[0], 0)
        for rid in ('harness.job', 'wsc.reg', 'tools.other', 'tools.idle'):
            self.assertEqual(self.repo.wsc('reg', 'set', 'tools', rid, 'last_used=2020-01-01')[0], 0)

    def job(self, jid, status, report, review):
        row = {'id': jid, 'description': 'd', 'title': 't', 'phase': 1, 'status': status, 'model': 'sonnet', 'needs_pc': False,
               'depends_on': [], 'brief': f'jobs/{jid}/brief.md', 'report': f'jobs/{jid}/report.md', 'review': f'jobs/{jid}/review.md'}
        self.repo.write(f'registries/jobs/{jid}.json', json.dumps(row, indent=2) + '\n')
        self.repo.write(f'jobs/{jid}/brief.md', f'# {jid}\n')
        self.repo.write(f'jobs/{jid}/report.md', report)
        if review is not None:
            self.repo.write(f'jobs/{jid}/review.md', review)

    @staticmethod
    def rounds(*dates):
        return '# review\n\n' + ''.join(f'## Round {i} ({d}, branch `job/W1` at `abc1234`)\nVerdict: fix\n\n' for i, d in enumerate(dates, 1))

    def uses(self):
        return tools.last_uses(Ctx.load(self.repo.root))

    def test_a_done_report_citing_a_path_dates_the_tool_by_its_newest_round(self):
        self.job('W1', 'done', 'Ran `core/harness/job.sh run` twice.\n', self.rounds(ago(9), ago(7)))
        self.assertEqual(self.uses()['harness.job'], (ago(7), 'jobs/W1/report.md'))

    def test_a_verb_is_cited_as_wsc_verb_or_wsc_py_verb(self):
        self.job('W1', 'done', 'Then `wsc reg check` passed.\n', self.rounds(ago(9)))
        self.assertEqual(self.uses()['wsc.reg'], (ago(9), 'jobs/W1/report.md'))
        self.job('W2', 'done', 'python3 core/wsc.py reg set jobs W2\n', self.rounds(ago(8)))
        self.assertEqual(self.uses()['wsc.reg'], (ago(8), 'jobs/W2/report.md'))
        self.job('W3', 'done', 'wsc regular, wsc.py registry, wsc.regex\n', self.rounds(ago(1)))
        self.assertEqual(self.uses()['wsc.reg'], (ago(8), 'jobs/W2/report.md'))

    def test_a_path_inside_a_longer_path_does_not_cite(self):
        self.job('W1', 'done', 'See xharness/job.sh, harness/job.sh.bak, a/harness/job.sh and harness/job.shx.\n', self.rounds(ago(3)))
        self.assertNotIn('harness.job', self.uses())
        self.job('W2', 'done', 'It ends with harness/job.sh.\n', self.rounds(ago(4)))
        self.assertEqual(self.uses()['harness.job'], (ago(4), 'jobs/W2/report.md'))

    def test_a_job_that_is_not_done_does_not_count(self):
        self.job('W1', 'review', 'harness/job.sh\n', None)
        self.job('W2', 'fix', 'harness/job.sh\n', self.rounds(ago(2)))
        self.assertEqual(self.uses(), {})

    def test_a_legacy_review_dated_in_its_first_lines_counts_and_an_undated_one_is_skipped(self):
        self.job('W1', 'done', 'tools/other.py\n', f'# W1 review\n\nReviewed {ago(20)} by a fresh session.\n')
        self.job('W2', 'done', 'tools/idle.py\n', '# W2 review\n\nno date\n\n\n\n\nlate 2026-01-01\n')
        self.assertEqual(self.uses(), {'tools.other': (ago(20), 'jobs/W1/report.md')})

    def test_no_jobs_registry_gives_nothing(self):
        repo = TempRepo()
        self.addCleanup(repo.close)
        self.assertEqual(tools.last_uses(Ctx.load(repo.root)), {})

    def test_the_window_uses_the_derived_date_and_names_its_source(self):
        self.job('W1', 'done', 'harness/job.sh\n', self.rounds(ago(5)))
        self.repo.write('wsc.toml', self.repo.read('wsc.toml') + '\n[tools]\nretire_after_days = 90\n')
        ctx = Ctx.load(self.repo.root)
        errs, warns = tools.check(ctx, load_all(ctx)['tools'])
        self.assertEqual(errs, [])
        self.assertFalse(any(w.startswith('harness.job:') for w in warns), warns)
        self.assertIn('tools.idle: live but last used 2020-01-01 (row) (over 90 days)', '\n'.join(warns))
        self.assertEqual(len(warns), 3, warns)
        self.job('W2', 'done', 'tools/idle.py\n', self.rounds(ago(200)))
        ctx = Ctx.load(self.repo.root)
        _, warns = tools.check(ctx, load_all(ctx)['tools'])
        self.assertIn(f'tools.idle: live but last used {ago(200)} (jobs/W2/report.md) (over 90 days)', '\n'.join(warns))


if __name__ == '__main__':
    unittest.main()
