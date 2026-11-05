"""Host tests for warscape/policy.py (`wsc policy`): the pure logic, then the verb on a fixture git repository (the session trailer check).

Moved from napoleon-remastered tests/test_pr_policy.py (napoleon J62); rule 79 and the core-pin cases stayed there with the hook module."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WSC = ROOT / 'wsc.py'
sys.path.insert(0, str(ROOT))
from warscape import policy as pp  # noqa: E402
from warscape.repo import DEFAULTS, ConfigError, Ctx, load_config  # noqa: E402

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
                                                   'registries/hotkeys.jsonl', 'docs/DECISIONS.md']), [])
        # W23 (decision 11): globs match by segment, so `registries/*` no longer reaches a per-row registry file
        self.assertTrue(self.run_check('meta/x', ['registries/tools/wsc.jobs.json']))
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

    def test_w23_globs_match_by_path_segment(self):
        """Decision 11: `*` and `?` stay inside one segment and `**` spans folders (repo.matches), so `registries/*` no longer covers
        per-row registry files."""
        self.assertFalse(pp.allowed('registries/jobs/W1.json', ['registries/*']))
        self.assertTrue(pp.allowed('registries/tools.jsonl', ['registries/*']))
        self.assertTrue(pp.allowed('docs/a/b.md', ['docs/**']))
        self.assertFalse(pp.allowed('docs/a/b.md', ['docs/*']))

    def test_w23_a_branch_behind_the_base_on_the_decisions_file_is_told_to_merge(self):
        base = '| D1 | 2026-10-28 | Liam | A. | yes |\n| D2 | 2026-10-28 | Liam | B. | no |\n'
        self.assertEqual(pp.decisions_problems(base, base.splitlines(True)[0], CFG, 'origin/main'),
                         ['docs/DECISIONS.md: merge origin/main: the base has rows this branch lacks (D2)'])
        self.assertIn('append only', pp.decisions_problems(base, base.replace('B.', 'Bee.'), CFG, 'origin/main')[0])

    def test_a_commit_without_a_trailer_fails_closed(self):
        done = {'id': 'J1', 'status': 'done', 'brief': 'jobs/J1/brief.md', 'report': 'jobs/J1/report.md', 'review': 'jobs/J1/review.md'}
        head = files(**{'jobs/J1/report.md': 'r', 'jobs/J1/review.md': '**Verdict: merge.**'})
        base = files(**{'jobs/J1/brief.md': 'b'})
        for s in (lambda p: [set()], lambda p: [{'S1'}] if p.endswith('report.md') else [{'S2'}, set()]):
            e = check('job/J1', ['x'], {'J1': ROW, 'J2': OTHER}, {'J1': done, 'J2': OTHER}, base, head, s)
            self.assertTrue(any('no `Claude-Session:` trailer' in x for x in e), e)


# ---------------------------------------------------------------- W27: review integrity (rules A-F), pure check() with fake git reads
DONE = dict(ROW, status='done', report='jobs/J1/report.md', review='jobs/J1/review.md')
REV = 'jobs/J1/review.md'


def rnd(n, v, extra=''):
    """One review round section."""
    return f'## Round {n} (2026-11-04, branch job/J1 at abc123{n})\n\n**Verdict: {v}.**\n{extra}\n'


def rv(*rounds):
    """A review.md of rounds given newest first as (n, verdict[, extra])."""
    return '# Review of J1\n\n' + ''.join(rnd(*r) for r in rounds)


def fake_reads(commits=(), history=(), numstat=(), exists=(), refs=None, shas=None):
    from types import SimpleNamespace
    return SimpleNamespace(commits=lambda: list(commits), history=lambda p: list(history) if p == REV else [],
                           numstat=lambda: list(numstat), exists=lambda p: p in exists,
                           ref_state=lambda r: (refs or {}).get(r, 'missing'), sha_state=lambda s: (shas or {}).get(s, 'missing'))


def w27(steps, report='# J1 report\n', base=None, cfg=CFG, base_rows=None, changed=('x.py',), branch='job/J1', **kw):
    """check() of job/J1 whose commits are `steps`: (sha, session or None, paths, review.md text after it or None). The builder's first step
    writes report.md. Returns (errors, warnings)."""
    commits, hist, review = [], [], None
    for sha, who, paths, text in steps:
        t = {who} if who else set()
        commits.append((sha, t, list(paths) + ([REV] if text is not None else [])))
        if text is not None:
            hist.append((sha, t, text))
            review = text
    sess = lambda p: [c[1] for c in commits if p in c[2]]
    warns = []
    errs = check(branch, list(changed), base_rows or {'J1': ROW, 'J2': OTHER}, {**(base_rows or {'J2': OTHER}), 'J1': DONE},
                 base or files(**{'jobs/J1/brief.md': 'b'}), files(**{'jobs/J1/report.md': report, REV: review}), sess, cfg=cfg,
                 reads=fake_reads(commits, hist, **kw), warnings=warns)
    return errs, warns


BUILD = ('c1', 'S1', ['warscape/x.py', 'jobs/J1/report.md'], None)
FIX1 = ('c3', 'F1', ['warscape/x.py', 'jobs/J1/report.md'], None)


class W27ReviewerCode(unittest.TestCase):
    """Rule A: a round whose own commits change a file outside jobs/<id>/ and the job's row must say `merge after fixes`."""

    def test_a_reviewer_code_commit_under_merge_is_refused_naming_shas_and_paths(self):
        e, w = w27([BUILD, ('c2', 'R1', ['warscape/y.py', 'registries/jobs/J1.json'], rv((1, 'merge')))])
        self.assertEqual(e, [])   # a warning since the scan of the merged branches (kill criterion: more than 3 beyond the audit's)
        self.assertTrue(any('c2' in x and 'warscape/y.py' in x and 'write the verdict `merge after fixes`' in x for x in w), w)

    def test_a_separate_code_commit_by_the_reviewer_is_part_of_its_round(self):
        _, w = w27([BUILD, ('c2', 'R1', ['docs/REVIEW.md'], None), ('c3', 'R1', [], rv((1, 'merge')))])
        self.assertTrue(any('c2' in x and 'docs/REVIEW.md' in x for x in w), w)

    def test_the_same_change_under_merge_after_fixes_passes_rule_a(self):
        e, w = w27([BUILD, ('c2', 'R1', ['warscape/y.py'], rv((1, 'merge after fixes')))])
        self.assertFalse(any('a fresh round reviews your change' in x for x in e + w), e + w)

    def test_a_reviewer_commit_of_review_md_and_the_row_only_passes(self):
        e, w = w27([BUILD, ('c2', 'R1', ['registries/jobs/J1.json', 'jobs/J1/notes.md'], rv((1, 'merge')))])
        self.assertEqual((e, w), ([], []))

    def test_code_written_by_round_1_is_reviewed_by_round_2(self):
        steps = [BUILD, ('c2', 'R1', ['warscape/y.py'], rv((1, 'merge after fixes'))), FIX1,
                 ('c4', 'R2', ['registries/jobs/J1.json'], rv((2, 'merge'), (1, 'merge after fixes')))]
        self.assertEqual(w27(steps), ([], []))

    def test_an_unattributed_code_commit_after_the_last_round_counts_for_it(self):
        _, w = w27([BUILD, ('c2', 'R1', [], rv((1, 'merge'))), ('c3', 'X9', ['warscape/z.py'], None)])
        self.assertTrue(any('c3' in x and 'warscape/z.py' in x for x in w), w)


class W27FreshRounds(unittest.TestCase):
    """Rule B: every round's sessions are disjoint from the builder's and from every earlier round's."""

    def test_round_2_by_the_round_1_session_is_refused(self):
        steps = [BUILD, ('c2', 'R1', [], rv((1, 'merge after fixes'))), FIX1, ('c4', 'R1', [], rv((2, 'merge'), (1, 'merge after fixes')))]
        e, _ = w27(steps)
        self.assertTrue(any('round 2 was written by a session that wrote round 1 (R1): a fresh session per round' in x for x in e), e)

    def test_the_builder_in_a_round_is_refused(self):
        e, _ = w27([BUILD, ('c2', 'S1', [], rv((1, 'merge')))])
        self.assertTrue(any('session that also wrote the report (S1)' in x for x in e), e)

    def test_a_fix_session_reviewing_a_later_round_is_refused(self):
        steps = [BUILD, ('c2', 'R1', [], rv((1, 'merge after fixes'))), FIX1, ('c4', 'F1', [], rv((2, 'merge'), (1, 'merge after fixes')))]
        e, _ = w27(steps)
        self.assertTrue(any('session that also wrote the report (F1)' in x for x in e), e)

    def test_a_round_commit_without_a_trailer_is_refused(self):
        e, _ = w27([BUILD, ('c2', None, [], rv((1, 'merge')))])
        self.assertTrue(any('no `Claude-Session:` trailer' in x for x in e), e)


class W27AppendOnly(unittest.TestCase):
    """Rule C: an earlier round stays byte-identical once a newer one exists, checked commit by commit and at the head against the base."""
    R1 = rv((1, 'merge after fixes'))

    def test_round_2_on_top_passes(self):
        steps = [BUILD, ('c2', 'R1', [], self.R1), FIX1, ('c4', 'R2', [], rv((2, 'merge'), (1, 'merge after fixes')))]
        self.assertEqual(w27(steps)[0], [])

    def test_an_edit_inside_round_1_after_round_2_exists_is_refused(self):
        steps = [BUILD, ('c2', 'R1', [], self.R1), FIX1, ('c4', 'R2', [], rv((2, 'merge'), (1, 'merge after fixes'))),
                 ('c5', 'R2', [], rv((2, 'merge'), (1, 'merge after fixes', 'Edited later.')))]
        e, _ = w27(steps)
        self.assertTrue(any('round 1' in x and 'c5' in x and 'append only' in x for x in e), e)

    def test_a_rewrite_then_restore_across_two_commits_is_refused(self):
        steps = [BUILD, ('c2', 'R1', [], self.R1), FIX1, ('c4', 'R2', [], rv((2, 'merge'), (1, 'merge'))),
                 ('c5', 'R2', [], rv((2, 'merge'), (1, 'merge after fixes')))]
        e, _ = w27(steps)
        self.assertTrue(any('round 1' in x and 'c4' in x and 'append only' in x for x in e), e)

    def test_the_newest_rounds_own_author_may_edit_it_before_another_round(self):
        steps = [BUILD, ('c2', 'R1', [], rv((1, 'do not merge'))), ('c3', 'R1', [], rv((1, 'merge', 'Rechecked.')))]
        self.assertEqual(w27(steps)[0], [])

    def test_another_session_editing_the_newest_round_is_refused(self):
        steps = [BUILD, ('c2', 'R1', [], rv((1, 'do not merge'))), ('c3', 'R7', [], rv((1, 'merge')))]
        e, _ = w27(steps)
        self.assertTrue(any('round 1' in x and 'c3' in x and 'did not write it' in x for x in e), e)

    def test_the_head_keeps_the_bases_rounds(self):
        base = files(**{'jobs/J1/brief.md': 'b', REV: self.R1})
        e, _ = w27([BUILD, ('c4', 'R2', [], rv((2, 'merge'), (1, 'merge', 'changed')))], base=base)
        self.assertTrue(any('round 1' in x and 'the base' in x for x in e), e)


class W27Evidence(unittest.TestCase):
    """Rule D: cited run folders, branches and commits resolve on a main branch or a pushed tag (errors for what the clone proves)."""
    OK = [BUILD, ('c2', 'R1', [], rv((1, 'merge')))]

    def test_a_run_folder_that_exists_nowhere_is_an_error(self):
        e, _ = w27(self.OK, report='Evidence: `harness/runs/20261104_x/result.json`.\n')
        self.assertTrue(any('harness/runs/20261104_x' in x and 'exists in neither' in x for x in e), e)

    def test_a_run_folder_in_the_head_or_the_base_passes(self):
        self.assertEqual(w27(self.OK, report='See harness/runs/20261104_x.\n', exists={'harness/runs/20261104_x'})[0], [])

    def test_an_absolute_or_url_run_path_is_not_a_repo_cite(self):
        rep = 'C:/pc/runs/20261104_x and https://github.com/o/r/actions/runs/41871905211 and <state>/runs/a1 and ~/runs/b2\n'
        self.assertEqual(w27(self.OK, report=rep), ([], []))

    def test_an_unmerged_job_branch_is_an_error_and_a_merged_one_passes(self):
        e, w = w27(self.OK, report='Built on `job/J9`.\n', refs={'job/J9': 'unmerged'})
        self.assertEqual(e, [])   # a warning since the scan of the merged branches (13 name an open branch in passing)
        self.assertTrue(any('job/J9' in x and 'evidence on an unmerged branch cannot be opened from main' in x for x in w), w)
        self.assertEqual(w27(self.OK, report='Built on `job/J9`.\n', refs={'job/J9': 'merged'}), ([], []))

    def test_a_squash_merged_job_branch_passes_by_its_done_row_on_the_base(self):
        rows = {'J1': ROW, 'J2': OTHER, 'J9': {'id': 'J9', 'status': 'done'}}
        self.assertEqual(w27(self.OK, report='see job/J9\n', refs={'job/J9': 'unmerged'}, base_rows=rows)[0], [])

    def test_a_brief_branch_merged_by_its_brief_on_the_base_passes(self):
        base = files(**{'jobs/J1/brief.md': 'b', 'jobs/J9/brief.md': 'b'})
        self.assertEqual(w27(self.OK, report='see brief/J9\n', refs={'brief/J9': 'unmerged'}, base=base)[0], [])

    def test_an_origin_ref_is_judged_and_origin_main_and_the_branch_itself_are_not(self):
        _, w = w27(self.OK, report='see origin/spike-x and origin/main and job/J1\n', refs={'origin/spike-x': 'unmerged', 'job/J1': 'unmerged'})
        self.assertEqual(len(w), 1, w)
        self.assertIn('origin/spike-x', w[0])

    def test_a_branch_the_clone_lacks_is_a_warning(self):
        e, w = w27(self.OK, report='napoleon job/J30\n')
        self.assertEqual(e, [])
        self.assertTrue(any('job/J30' in x and 'not in this clone' in x for x in w), w)

    def test_cited_commits_each_pattern(self):
        rep = 'commit `abc1234`, sha: `def5678`, commits `aaa1111`, `bbb2222` and core@ccc3333.\n'
        e, w = w27(self.OK, report=rep, shas={'abc1234': 'ok'})
        self.assertEqual(e, [])
        for s in ('def5678', 'aaa1111', 'bbb2222', 'ccc3333'):
            self.assertTrue(any(s in x and 'a commit that is not pushed cannot be opened' in x for x in w), (s, w))
        self.assertFalse(any('abc1234' in x for x in w), w)

    def test_hex_without_a_keyword_is_not_a_cite(self):
        self.assertEqual(w27(self.OK, report='the value `abc1234` and 41871905211\n'), ([], []))


class W27ThinMerge(unittest.TestCase):
    """Rule E: a `merge` on a large diff whose newest round cites no evidence warns."""

    def thin(self, w):
        return any('merge verdict on a large diff cites no evidence (J62, J57)' in x for x in w)

    def test_a_600_line_merge_with_no_evidence_warns(self):
        e, w = w27([BUILD, ('c2', 'R1', [], rv((1, 'merge')))], numstat=[(600, 'warscape/a.py')])
        self.assertEqual(e, [])
        self.assertTrue(self.thin(w), w)

    def test_evidence_in_the_newest_round_silences_it(self):
        for extra in ('CI run 41871905211 green.', 'Ran tests/test_policy.py.', 'test_round_2_on_top_passes is green.',
                      'See harness/runs/20261104_x.', 'https://github.com/o/r/actions/runs/1234', 'run 20261104_a passed.'):
            e, w = w27([BUILD, ('c2', 'R1', [], rv((1, 'merge', extra)))], numstat=[(600, 'warscape/a.py')], exists={'harness/runs/20261104_x'})
            self.assertFalse(self.thin(w), (extra, w))

    def test_a_small_diff_or_one_inside_jobs_and_registries_does_not_warn(self):
        for ns in ([(400, 'warscape/a.py')], [(900, 'jobs/J1/report.md'), (900, 'registries/tools.jsonl')]):
            self.assertFalse(self.thin(w27([BUILD, ('c2', 'R1', [], rv((1, 'merge')))], numstat=ns)[1]), ns)

    def test_many_files_warn_and_the_thresholds_are_settings(self):
        ns = [(1, f'src/f{i}.py') for i in range(21)]
        self.assertTrue(self.thin(w27([BUILD, ('c2', 'R1', [], rv((1, 'merge')))], numstat=ns)[1]))
        cfg = {**CFG, 'thin_files': 50}
        self.assertFalse(self.thin(w27([BUILD, ('c2', 'R1', [], rv((1, 'merge')))], numstat=ns, cfg=cfg)[1]))


class W27DecisionsCiteJob(unittest.TestCase):
    """Rule F: with `[policy] decisions_cite_job`, a decision row added on job/<id> names <id>."""
    BASE = '| D1 | 2026-10-28 | Liam | A. | yes |\n'

    def run_f(self, row, branch='job/J1', on=True):
        cfg = {**CFG, 'decisions_cite_job': on}
        head = files(**{'docs/DECISIONS.md': self.BASE + row, 'jobs/J1/report.md': 'r', REV: rv((1, 'merge'))})
        base = files(**{'docs/DECISIONS.md': self.BASE, 'jobs/J1/brief.md': 'b'})
        seen = []
        e = check(branch, ['docs/DECISIONS.md'], {'J1': ROW, 'J2': OTHER}, {'J1': DONE if branch.startswith('job/') else ROW, 'J2': OTHER},
                  base, head, cfg=cfg, hook=lambda f: seen.append(f) or [])
        return e, seen[0]

    def test_a_row_without_the_job_id_is_refused(self):
        e, _ = self.run_f('| D2 | 2026-11-04 | Claude | B. | yes |\n')
        self.assertIn('decision row D2 on job/J1 must name the brief that required it (add `J1` to the row, or move it to a plan/ branch)', e)

    def test_a_row_naming_the_job_passes_and_the_facts_carry_it(self):
        e, facts = self.run_f('| D2 | 2026-11-04 | proposed (Claude, J1) | B. | yes |\n')
        self.assertEqual(e, [])
        self.assertEqual(facts['added_decision_rows'], [{'id': 'D2', 'text': '| D2 | 2026-11-04 | proposed (Claude, J1) | B. | yes |'}])

    def test_off_by_default_and_plan_branches_are_unchanged(self):
        self.assertEqual(self.run_f('| D2 | 2026-11-04 | Claude | B. | yes |\n', on=False)[0], [])
        self.assertEqual(self.run_f('| D2 | 2026-11-04 | Claude | B. | yes |\n', branch='plan/x')[0], [])


class W36WorkflowFiles(unittest.TestCase):
    """W36 decision 1: a job's change to a workflow input its brief on the base does not name. A warning, not a refusal: the scan of the merged job
    branches passed the brief's kill criterion (jobs/W36/report.md)."""
    WF, GATES, TPL = '.github/workflows/x.yml', '.github/workflows/gates.yml', 'ci/gates.yml.in'

    def run_w(self, changed, brief='# J1\n', branch='job/J1', cfg=CFG, extra=None):
        """(errors, warnings) of `branch` changing `changed`; the job is otherwise mergeable."""
        warns = []
        base = files(**{'jobs/J1/brief.md': brief, **(extra or {})})
        head = files(**{'jobs/J1/report.md': 'r', REV: rv((1, 'merge'))})
        row = DONE if branch.startswith('job/') else ROW
        errs = check(branch, list(changed), {'J1': ROW, 'J2': OTHER}, {'J1': row, 'J2': OTHER}, base, head, cfg=cfg, warnings=warns)
        return errs, warns

    def missing(self, warns):
        return [w.split('`')[1] for w in warns if 'is a workflow input' in w]

    def test_a_workflow_the_brief_names_passes_and_one_it_does_not_warns(self):
        self.assertEqual(self.run_w([self.WF], brief=f'# J1\nAdds `{self.WF}`.\n'), ([], []))
        errs, warns = self.run_w([self.WF])
        self.assertEqual(errs, [])
        self.assertEqual(warns, [f"`{self.WF}` is a workflow input and J1's brief on the base does not name it: a job cannot quietly add a check that posts a fake "
                                 "`policy` status (W36); name the file in the brief (briefs are merged before the job starts) or use a `meta/` branch"])

    def test_one_warning_per_path(self):
        self.assertEqual(self.missing(self.run_w(['ci/a.txt', 'ci/b.txt', 'warscape/x.py'], brief='`ci/b.txt`')[1]), ['ci/a.txt'])

    def test_a_template_change_must_name_the_rendered_file(self):
        warns = self.run_w([self.TPL, self.GATES], brief=f'Edit `{self.TPL}`.', extra={self.TPL: 't'})[1]
        self.assertEqual(self.missing(warns), [self.GATES])
        self.assertIn(f'`{self.GATES}` renders from `{self.TPL}`: name both', warns[0])
        self.assertEqual(self.run_w([self.TPL, self.GATES], brief=f'`{self.TPL}` and `{self.GATES}`', extra={self.TPL: 't'})[1], [])

    def test_a_template_change_alone_still_needs_the_rendered_file_named(self):
        """The re-render changes both; the `ci_render` gate fails the branch that leaves the workflow behind."""
        self.assertEqual(self.missing(self.run_w([self.TPL], brief=f'`{self.TPL}`', extra={self.TPL: 't'})[1]), [self.GATES])

    def test_a_rendered_file_names_its_template_sibling_only_when_there_is_one(self):
        self.assertEqual(self.missing(self.run_w([self.GATES], brief=f'`{self.TPL}`', extra={self.TPL: 't'})[1]), [self.GATES])
        self.assertNotIn('name both', self.run_w([self.WF])[1][0])
        self.assertNotIn('name both', self.run_w(['ci/helper.sh'])[1][0])

    def test_the_template_folder_comes_from_the_config(self):
        cfg = {**CFG, 'template_dir': 'tpl', 'workflow_paths': ['.github/workflows/**', 'tpl/**']}
        warns = self.run_w(['tpl/gates.yml.in', self.GATES], brief='`tpl/gates.yml.in`', cfg=cfg, extra={'tpl/gates.yml.in': 't'})[1]
        self.assertEqual(self.missing(warns), [self.GATES])
        self.assertIn('renders from `tpl/gates.yml.in`', warns[0])

    def test_a_delete_and_a_rename_count(self):
        self.assertEqual(self.missing(self.run_w([self.WF])[1]), [self.WF])   # a delete is a changed path the base has
        old, new = '.github/workflows/old.yml', '.github/workflows/new.yml'   # --no-renames: a delete and an add
        self.assertEqual(self.missing(self.run_w([old, new], brief=f'`{new}`')[1]), [old])
        self.assertEqual(self.missing(self.run_w([old, new], brief=f'`{old}`')[1]), [new])

    def test_an_empty_list_switches_the_rule_off(self):
        self.assertEqual(self.run_w([self.WF], cfg={**CFG, 'workflow_paths': []}), ([], []))

    def test_other_paths_and_other_branch_kinds_are_unchanged(self):
        self.assertEqual(self.run_w(['warscape/x.py', '.github/CODEOWNERS', 'docs/ci/x.md']), ([], []))
        for branch in ('plan/x', 'meta/x', 'brief/J1', 'release/v1.0.0'):
            with self.subTest(branch):
                self.assertEqual(self.run_w([self.WF], branch=branch)[1], [])
        self.assertEqual(self.run_w([self.WF], branch='meta/x', cfg={**CFG, 'meta': ['.github/**']}), ([], []))

    def test_the_default_globs_and_the_core_spells_them_out(self):
        self.assertEqual(DEFAULTS['policy']['workflow_paths'], ['.github/workflows/**', 'ci/**'])
        self.assertEqual(DEFAULTS['policy']['bases'], ['main'])
        for root in (ROOT, ROOT / 'tests' / 'fixture_game'):
            raw = tomllib.loads((root / 'wsc.toml').read_text(encoding='utf-8'))['policy']
            self.assertEqual((raw['workflow_paths'], raw['bases']), (['.github/workflows/**', 'ci/**'], ['main']), root)

    def test_the_keys_are_lists_of_strings(self):
        for key in ('workflow_paths', 'bases'):
            for bad in ('main', 1, [1], ['']):
                with self.subTest(key=key, bad=bad), tempfile.TemporaryDirectory() as t:
                    Path(t, 'wsc.toml').write_text(f'[policy]\n{key} = {json.dumps(bad)}\n', encoding='utf-8')
                    with self.assertRaises(ConfigError) as e:
                        load_config(Path(t))
                    self.assertIn(f'policy.{key}', str(e.exception))


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
        # [ci] core = "": a repo with no core of its own (no gitlink, no warscape/policy.py) is judged as before W23, with a note
        self.commit('wsc.toml', '[policy]\ndecisions = "docs/DECISIONS.md"\n[ci]\ncore = ""\n')
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
