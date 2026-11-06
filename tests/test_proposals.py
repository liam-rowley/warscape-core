"""Host tests for the answer round (W45, C41): the row's states and `wsc proposals` in warscape/proposals.py, what `wsc audit` adds to a record,
and the `decide/` kind and the guard in warscape/policy.py, one test per forgery. Pure logic and a plain folder: no test here reads this repo's history."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from warscape import audit as A  # noqa: E402
from warscape import gates, jobq  # noqa: E402
from warscape import policy as pp  # noqa: E402
from warscape import proposals as P  # noqa: E402
from warscape.repo import DEFAULTS, ConfigError, Ctx, audit_problem  # noqa: E402

CONFIG = {**DEFAULTS,
          'registries': {'jobs': 'core:jobs', 'decisions': 'core:decisions', 'proposals': 'core:proposals'},
          'storage': {'dir': ['jobs', 'decisions', 'proposals']},
          'policy': {**DEFAULTS['policy'], 'decisions': 'registry:decisions', 'decision_prefix': 'C'},
          'jobs': {**DEFAULTS['jobs'], 'id_prefix': 'W', 'text': {**DEFAULTS['jobs']['text'], 'owner': 'Liam'}}}
CFG = pp.settings(CONFIG)
AUTO = pp.settings({**CONFIG, 'audit': {**DEFAULTS['audit'], 'auto_apply': ['doc_cap']}})
PDIR, ANS = 'registries/proposals', 'docs/audits/ANSWERS_2026-11-06.md'
ID, ID2 = 'P261106-aaaa', 'P261106-bbbb'
DEC = 'C261106-cccc'


def row(rid=ID, **kw):
    return {'id': rid, 'date': '2026-11-06', 'kind': 'finding', 'finding': 'doc_cap:docs/X.md', 'metric': 'doc_caps', 'class': 'doc_cap',
            'question': 'Split docs/X.md?',
            'baseline': {'record': 'docs/audits/AUDIT_2026-11-05.json', 'value': 29.0, 'threshold': 27.0, 'direction': 'above', 'severity': 'medium', 'evidence': 'docs/X.md is 29 KB.'},
            'options': [{'key': 'split', 'kind': 'job', 'summary': 'Split it.', 'recipe': {'title': 'Split docs/X.md', 'description': 'Split it.', 'phase': 1, 'model': 'sonnet', 'needs_pc': False, 'semver': 'none', 'depends_on': []}},
                        {'key': 'rule', 'kind': 'decision', 'summary': 'Keep it.', 'recipe': {'decision': 'docs/X.md stays whole.', 'reversible': 'yes'}},
                        {'key': 'later', 'kind': 'defer', 'summary': 'Later.'},
                        {'key': 'no', 'kind': 'none', 'summary': 'Leave it.'}],
            'recommended': 'split', 'status': 'open', **kw}


def answered(rid=ID, option='split', by='Liam', record=ANS, status='accepted', **kw):
    extra = {'decision': DEC, 'job': 'W200'} if option == 'split' else {'decision': DEC} if option == 'rule' else {}
    return row(rid, **{**{'status': status, 'answer': {'by': by, 'date': '2026-11-06', 'record': record, 'option': option}}, **extra, **kw})


def text(r):
    return json.dumps(r, indent=2) + '\n'


def path(rid=ID):
    return f'{PDIR}/{rid}.json'


def decision(ids=(ID,), rid=DEC):
    return json.dumps({'id': rid, 'date': '2026-11-06', 'who': 'Liam', 'decision': 'Accepted ' + ', '.join(ids) + '.', 'reversible': 'yes'})


def job(rid='W200', status='needs_brief'):
    return {'id': rid, 'title': 't', 'description': 'd', 'phase': 1, 'status': status, 'model': 'sonnet', 'needs_pc': False, 'depends_on': []}


def judge(branch, base=None, head=None, base_rows=None, head_rows=None, cfg=CFG):
    """Errors for a pull request whose changed paths are the files that differ between `base` and `head` ({path: text})."""
    base, head = base or {}, head or {}
    changed = sorted(p for p in set(base) | set(head) if base.get(p) != head.get(p))
    return pp.check(branch, changed, base_rows or {}, head_rows or {}, base.get, head.get, cfg=cfg)


def decide_head(r=None, extra=None):
    """The files of a good decide/ branch that accepts `r`."""
    return {path(): text(r or answered()), ANS: f'> yes\n\n{ID}\n', f'registries/decisions/{DEC}.json': decision(), **(extra or {})}


class Forgeries(unittest.TestCase):
    """Each is refused: an answer is the owner's, and only a decide/ branch writes it."""
    def refused(self, errs, word):
        self.assertTrue(any(word in e for e in errs), errs)

    def test_a_plan_branch_cannot_accept_a_row(self):
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text(answered())}), 'decide/')

    def test_a_plan_branch_cannot_decline_or_defer_a_row(self):
        for status, option in (('declined', 'no'), ('deferred', 'later')):
            self.refused(judge('plan/x', {path(): text(row())}, {path(): text(answered(option=option, status=status))}), 'decide/')

    def test_a_plan_branch_cannot_add_a_row_already_accepted(self):
        self.refused(judge('plan/x', {}, {path(): text(answered())}), 'decide/')

    def test_a_plan_branch_cannot_write_an_answer_and_leave_the_status_open(self):
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text({**row(), 'answer': answered()['answer']})}), 'decide/')

    def test_auto_apply_cannot_take_a_tagged_row(self):
        r = answered(by='auto_apply', record=row()['baseline']['record'], tag='risk')
        self.refused(judge('plan/x', {path(): text(row(tag='risk'))}, {path(): text(r)}, cfg=AUTO), 'decide/')

    def test_auto_apply_cannot_take_an_option_off_the_recommendation(self):
        r = answered(option='no', status='declined', by='auto_apply', record=row()['baseline']['record'])
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text(r)}, cfg=AUTO), 'decide/')

    def test_auto_apply_reads_the_class_list_of_the_base_not_the_branch(self):
        """The head's wsc.toml is data (C24): `cfg` is the base's, and a list only the head adds to is the plain plan/ refusal."""
        r = answered(by='auto_apply', record=row()['baseline']['record'])
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text(r), 'wsc.toml': '[audit]\nauto_apply = ["doc_cap"]\n'}), 'decide/')

    def test_auto_apply_cannot_claim_the_owner(self):
        r = answered(record=row()['baseline']['record'])   # every other field as auto_apply writes it
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text(r)}, cfg=AUTO), 'decide/')

    def test_auto_apply_must_name_the_baselines_record(self):
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text(answered(by='auto_apply'))}, cfg=AUTO), 'decide/')

    def test_auto_apply_must_set_the_options_status(self):
        r = answered(by='auto_apply', record=row()['baseline']['record'], status='declined')
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text(r)}, cfg=AUTO), 'decide/')

    def test_a_status_alone_counts_as_an_answer(self):
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text(row(status='accepted'))}), 'decide/')

    def test_auto_apply_cannot_change_the_row_it_accepts(self):
        r = answered(by='auto_apply', record=row()['baseline']['record'], question='Another question?')
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text(r)}, cfg=AUTO), 'decide/')

    def test_a_plan_branch_cannot_strip_a_tag(self):
        self.refused(judge('plan/x', {path(): text(row(tag='risk'))}, {path(): text(row())}, cfg=AUTO), 'tag')

    def test_a_plan_branch_cannot_change_a_tag(self):
        self.refused(judge('plan/x', {path(): text(row(tag='risk'))}, {path(): text(row(tag='cost'))}, cfg=AUTO), 'tag')

    def test_a_plan_branch_cannot_relabel_a_rows_class(self):
        self.refused(judge('plan/x', {path(): text(row(**{'class': 'hot_file'}))}, {path(): text(row())}, cfg=AUTO), 'class')

    def test_a_plan_branch_may_add_a_tag(self):
        self.assertEqual(judge('plan/x', {path(): text(row())}, {path(): text(row(tag='risk'))}, cfg=AUTO), [])

    def test_a_tag_or_class_survives_closing_as_gone(self):
        self.assertEqual(judge('plan/x', {path(): text(row(tag='risk'))}, {path(): text(row(tag='risk', status='closed', outcome='gone'))}), [])
        self.refused(judge('plan/x', {path(): text(row(tag='risk'))}, {path(): text(row(status='closed', outcome='gone'))}), 'tag')

    def test_a_job_branch_cannot_change_a_row(self):
        self.refused(judge('job/W9', {path(): text(row())}, {path(): text(row(question='New?'))}), 'proposal')

    def test_a_meta_branch_cannot_change_a_row(self):
        self.refused(judge('meta/x', {path(): text(row())}, {path(): text(row(question='New?'))}), 'proposal')

    def test_no_branch_deletes_a_row(self):
        for branch in ('plan/x', 'decide/2026-11-06'):
            self.refused(judge(branch, {path(): text(row())}, {}), 'never deleted')

    def test_an_answered_row_keeps_its_answer_and_its_content(self):
        for change in ({'recommended': 'no'}, {'question': 'Other?'}, {'answer': {**answered()['answer'], 'option': 'no'}}, {'decision': 'C261106-dddd'}, {'job': 'W201'}):
            self.refused(judge('plan/x', {path(): text(answered())}, {path(): text({**answered(), **change})}), 'answered')

    def test_closing_a_row_cannot_rewrite_it(self):
        r = answered(status='closed', outcome='moved', recommended='no')
        self.refused(judge('plan/x', {path(): text(answered())}, {path(): text(r)}), 'keeps its content')

    def test_an_answered_status_only_goes_to_closed(self):
        self.refused(judge('plan/x', {path(): text(answered())}, {path(): text(answered(status='declined'))}), 'answered')
        self.refused(judge('decide/2026-11-07', {path(): text(answered())}, {path(): text(answered(status='open'))}), 'answered')

    def test_a_closed_row_stays_closed(self):
        done = answered(status='closed', outcome='moved')
        self.refused(judge('plan/x', {path(): text(done)}, {path(): text({**done, 'outcome': 'not_moved'})}), 'closed')

    def test_a_plan_branch_cannot_close_an_open_row_as_moved(self):
        self.refused(judge('plan/x', {path(): text(row())}, {path(): text(row(status='closed', outcome='moved'))}), 'gone')

    def test_a_plan_branch_cannot_add_or_change_an_answers_file(self):
        self.refused(judge('plan/x', {}, {ANS: '> yes, Liam\n'}), 'ANSWERS')
        self.refused(judge('plan/x', {ANS: '> no\n'}, {ANS: '> yes\n'}), 'ANSWERS')

    def test_a_job_branch_cannot_add_an_answers_file(self):
        self.refused(judge('job/W9', {}, {ANS: '> yes, Liam\n'}), 'ANSWERS')

    def test_a_row_file_must_be_a_row(self):
        self.refused(judge('plan/x', {}, {path(): 'not json'}), 'JSON')
        self.refused(judge('plan/x', {}, {path(ID2): text(row(ID))}), 'file name')

    def test_decide_answer_not_by_the_owner(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(answered(by='Someone')), head_rows={'W200': job()}), 'owner')

    def test_decide_answer_by_auto_apply(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(answered(by='auto_apply')), head_rows={'W200': job()}, cfg=AUTO), 'owner')

    def test_decide_answer_naming_another_record(self):
        r = answered(record='docs/audits/ANSWERS_2026-11-01.md')
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(r), head_rows={'W200': job()}), ANS)

    def test_decide_without_its_answers_file(self):
        head = decide_head()
        del head[ANS]
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, head, head_rows={'W200': job()}), ANS)

    def test_decide_row_not_in_the_answers_file(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(extra={ANS: '> yes\n'}), head_rows={'W200': job()}), 'does not name')

    def test_decide_status_not_the_options(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(answered(status='declined')), head_rows={'W200': job()}), 'status')

    def test_decide_option_not_on_the_row(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(answered(option='nope')), head_rows={'W200': job()}), 'option')

    def test_decide_job_row_not_needs_brief(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(), head_rows={'W200': job(status='queued')}), 'needs_brief')

    def test_decide_changing_an_existing_job_row(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(), base_rows={'W1': job('W1')},
                           head_rows={'W1': job('W1', status='needs_brief') | {'title': 'x'}, 'W200': job()}), 'W1')

    def test_decide_removing_a_job_row(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(), base_rows={'W1': job('W1')}, head_rows={'W200': job()}), 'W1')

    def test_decide_touching_code(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(extra={'warscape/x.py': 'x = 1\n'}), head_rows={'W200': job()}), 'warscape/x.py')

    def test_decide_touching_another_doc(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(extra={'docs/REVIEW.md': 'x\n'}), head_rows={'W200': job()}), 'docs/REVIEW.md')

    def test_decide_with_a_decision_row_that_lacks_the_id(self):
        head = decide_head(extra={f'registries/decisions/{DEC}.json': decision(ids=(ID2,))})
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, head, head_rows={'W200': job()}), 'does not name')

    def test_decide_naming_a_decision_row_already_on_the_base(self):
        head = decide_head()
        base = {path(): text(row()), f'registries/decisions/{DEC}.json': head[f'registries/decisions/{DEC}.json']}
        self.refused(judge('decide/2026-11-06', base, head, head_rows={'W200': job()}), 'does not name')

    def test_decide_job_option_without_its_job_row(self):
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head()), 'W200')

    def test_decide_with_a_bad_name(self):
        for branch in ('decide/today', 'decide/2026-11-6', 'decide/2026-11-06-x', 'decide/2026-11-06-1'):
            self.refused(judge(branch, {path(): text(row())}, decide_head(), head_rows={'W200': job()}), 'decide/<YYYY-MM-DD>')

    def test_decide_is_refused_where_the_registry_is_not_declared(self):
        cfg = pp.settings({**CONFIG, 'registries': {'jobs': 'core:jobs', 'decisions': 'core:decisions'}, 'storage': {'dir': ['jobs', 'decisions']}})
        self.refused(judge('decide/2026-11-06', {}, {'x': 'y'}, cfg=cfg), 'proposals')

    def test_decide_fails_closed_without_an_owner(self):
        cfg = {**CFG, 'text': {**CFG['text'], 'owner': ''}}
        self.refused(judge('decide/2026-11-06', {path(): text(row())}, decide_head(), head_rows={'W200': job()}, cfg=cfg), '[jobs.text] owner')


class Allowed(unittest.TestCase):
    """The same changes where they belong."""
    def test_decide_accepts_a_job_option(self):
        self.assertEqual(judge('decide/2026-11-06', {path(): text(row())}, decide_head(), head_rows={'W200': job()}), [])

    def test_decide_accepts_a_decision_option(self):
        self.assertEqual(judge('decide/2026-11-06', {path(): text(row())}, decide_head(answered(option='rule'))), [])

    def test_decide_declines_and_defers_with_no_decision_row(self):
        for status, option in (('declined', 'no'), ('deferred', 'later')):
            head = {path(): text(answered(option=option, status=status)), ANS: f'{ID}\n'}
            self.assertEqual(judge('decide/2026-11-06', {path(): text(row())}, head), [])

    def test_a_second_round_that_day(self):
        ans2 = 'docs/audits/ANSWERS_2026-11-06_2.md'
        head = {path(): text(answered(option='no', status='declined', record=ans2)), ans2: f'{ID}\n'}
        self.assertEqual(judge('decide/2026-11-06-2', {path(): text(row())}, head), [])

    def test_plan_adds_and_fills_open_rows(self):
        self.assertEqual(judge('plan/x', {}, {path(): text(row())}), [])
        self.assertEqual(judge('plan/x', {path(): text(row())}, {path(): text(row(question='Better?'))}), [])

    def test_plan_closes_an_applied_row_and_a_gone_open_row(self):
        self.assertEqual(judge('plan/x', {path(): text(answered())}, {path(): text(answered(status='closed', outcome='not_moved'))}), [])
        self.assertEqual(judge('plan/x', {path(): text(row())}, {path(): text(row(status='closed', outcome='gone'))}), [])

    def test_auto_apply_on_plan_for_a_listed_class(self):
        r = answered(by='auto_apply', record=row()['baseline']['record'])
        self.assertEqual(judge('plan/x', {path(): text(row())}, {path(): text(r)}, cfg=AUTO), [])
        self.assertEqual(judge('plan/x', {}, {path(): text(r)}, cfg=AUTO), [])   # W47 drafts and applies in one branch

    def test_a_row_as_the_base_has_it_is_no_change(self):
        self.assertEqual(pp.check('job/W9', [path()], {}, {}, {path(): text(row())}.get, {path(): text(row())}.get, cfg=CFG)
                         and [e for e in pp.check('job/W9', [path()], {}, {}, {path(): text(row())}.get, {path(): text(row())}.get, cfg=CFG) if 'proposal' in e], [])

    def test_a_repo_without_the_registry_is_not_judged(self):
        cfg = pp.settings({**DEFAULTS, 'policy': {**DEFAULTS['policy'], 'decisions': 'docs/DECISIONS.md'}})
        self.assertEqual(judge('plan/x', {}, {'docs/audits/ANSWERS_2026-11-06.md': 'x\n'}, cfg=cfg), [])

    def test_the_plan_globs_reach_the_rows(self):
        self.assertTrue(pp.matches(path(), DEFAULTS['policy']['plan']))


def rec(findings=(), metrics=('doc_caps',), since='2026-11-10', skipped=(), failed=(), details=None):
    return {'version': 1, 'repo': 'r', 'date': '2026-11-17', 'main': 'abc', 'window': {'since': since, 'until': '2026-11-17', 'job_merges': 1},
            'metrics': {m: {'value': 1, 'details': details or {}} for m in metrics}, 'findings': list(findings), 'skipped': list(skipped), 'failed': list(failed)}


def found(value=29.0, fid='doc_cap:docs/X.md', direction='above', metric='doc_caps'):
    return {'id': fid, 'metric': metric, 'subject': 'docs/X.md', 'severity': 'medium', 'value': value, 'threshold': 27.0, 'direction': direction, 'evidence': 'e'}


class Overlay(unittest.TestCase):
    """What `wsc audit` adds to a record: `suppressed` and `remeasured`."""
    def over(self, r, rows, jobs=None, merged=None, margin=0.25):
        out = copy.deepcopy(r)
        P.overlay(out, rows, jobs or {}, merged or {}, margin)
        return out

    def verdict(self, r, row_, **kw):
        return self.over(r, [row_], **kw)['remeasured'][0]['verdict']

    def test_a_declined_or_deferred_finding_is_suppressed_inside_the_margin(self):
        for status, option in (('declined', 'no'), ('deferred', 'later')):
            out = self.over(rec([found(30.0)]), [answered(option=option, status=status)])
            self.assertEqual(out['findings'], [])
            self.assertEqual(out['suppressed'][0]['proposal'], ID)

    def test_a_finding_worse_past_the_margin_comes_back(self):
        out = self.over(rec([found(40.0)]), [answered(option='no', status='declined')])
        self.assertEqual([f['id'] for f in out['findings']], ['doc_cap:docs/X.md'])
        self.assertNotIn('suppressed', out)

    def test_worse_at_exactly_the_margin_stays_suppressed(self):
        self.assertFalse(P.worse(125.0, 100.0, 'above', 0.25))
        self.assertTrue(P.worse(125.1, 100.0, 'above', 0.25))

    def test_worse_follows_the_direction(self):
        self.assertTrue(P.worse(0.2, 0.4, 'below', 0.25))
        self.assertFalse(P.worse(0.6, 0.4, 'below', 0.25))

    def test_on_a_baseline_of_zero_any_worsening_counts(self):
        self.assertTrue(P.worse(0.1, 0, 'above', 0.25))
        self.assertFalse(P.worse(0, 0, 'above', 0.25))
        self.assertFalse(P.better(0, 0, 'above', 0.25))   # the same is no better

    def test_only_the_newest_row_on_a_finding_suppresses(self):
        old = answered(ID, option='no', status='declined')
        new = row(ID2, date='2026-11-07')
        self.assertEqual(len(self.over(rec([found(30.0)]), [old, new])['findings']), 1)

    def test_an_open_row_suppresses_nothing(self):
        self.assertEqual(len(self.over(rec([found()]), [row()])['findings']), 1)

    def test_nothing_to_add_adds_no_key(self):
        out = self.over(rec([found()]), [])
        self.assertNotIn('suppressed', out)
        self.assertNotIn('remeasured', out)

    def test_an_old_record_renders_as_it_did(self):
        r = rec([found()])
        self.assertNotIn('Suppressed', A.render_md(r))
        self.assertNotIn('Re-measured', A.render_md(r))

    def test_the_new_keys_render(self):
        r = self.over(rec([found(30.0)]), [answered(option='no', status='declined')])
        self.assertIn(ID, A.render_md(r))
        r = self.over(rec([]), [answered(option='rule')])
        self.assertIn('moved', A.render_md(r))

    def test_moved_when_the_finding_is_absent(self):
        self.assertEqual(self.verdict(rec([]), answered(option='rule')), 'moved')

    def test_moved_when_better_by_the_margin(self):
        self.assertEqual(self.verdict(rec([found(20.0)]), answered(option='rule')), 'moved')

    def test_not_moved_when_better_by_less(self):
        self.assertEqual(self.verdict(rec([found(28.0)]), answered(option='rule')), 'not_moved')

    def test_not_moved_when_the_same(self):
        self.assertEqual(self.verdict(rec([found(29.0)]), answered(option='rule')), 'not_moved')

    def test_a_metric_not_measured_is_never_read_as_fixed(self):
        for r in (rec([], metrics=(), skipped=[{'metric': 'doc_caps', 'reason': 'not in --only'}]), rec([], metrics=(), failed=[{'metric': 'doc_caps', 'reason': 'x'}]), rec([], metrics=())):
            self.assertEqual(self.verdict(r, answered(option='rule')), 'unmeasured')

    def test_too_soon_while_the_window_reaches_back_past_the_answer(self):
        self.assertEqual(self.verdict(rec([], since='2026-11-05'), answered(option='rule')), 'too_soon')

    def test_too_soon_while_the_window_reaches_back_past_the_jobs_merge(self):
        r = answered()
        self.assertEqual(self.verdict(rec([], since='2026-11-10'), r, jobs={'W200': {'status': 'done'}}, merged={'W200': '2026-11-12'}), 'too_soon')
        self.assertEqual(self.verdict(rec([], since='2026-11-12'), r, jobs={'W200': {'status': 'done'}}, merged={'W200': '2026-11-12'}), 'moved')

    def test_a_done_job_with_no_merge_found_is_too_soon(self):
        self.assertEqual(self.verdict(rec([]), answered(), jobs={'W200': {'status': 'done'}}), 'too_soon')

    def test_gone_when_the_subject_left_main(self):
        r = rec([], details={'gone': ['docs/X.md']})
        self.assertEqual(self.verdict(r, answered(option='rule')), 'gone')

    def test_a_job_not_done_is_not_applied(self):
        self.assertNotIn('remeasured', self.over(rec([]), [answered()], jobs={'W200': {'status': 'queued'}}))

    def test_a_closed_or_open_row_is_not_remeasured(self):
        self.assertNotIn('remeasured', self.over(rec([]), [answered(option='rule', status='closed', outcome='moved'), row(ID2)]))

    def test_applied_is_computed(self):
        self.assertTrue(P.applied(answered(option='rule'), {}))
        self.assertFalse(P.applied(answered(), {'W200': {'status': 'review'}}))
        self.assertTrue(P.applied(answered(), {'W200': {'status': 'done'}}))
        self.assertFalse(P.applied(answered(option='no', status='declined'), {}))
        self.assertFalse(P.applied(row(), {}))


class Metrics(unittest.TestCase):
    def test_a_decide_merge_reads_as_decide(self):
        self.assertEqual(A.subject_kind('decide: answers of 2026-11-06 (#7)', 'W'), ('decide', ''))

    def test_the_audit_keys_are_checked(self):
        for k, bad in (('auto_apply', 'doc_cap'), ('reraise_margin', 'x'), ('max_questions', True)):
            with self.assertRaises(ConfigError):
                audit_problem({**DEFAULTS['audit'], k: bad})


class Folder(unittest.TestCase):
    """The verbs' writes, on a plain folder: no git, the branch and the taken job ids are arguments."""
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        (self.root / 'wsc.toml').write_text('registries_dir = "registries"\n[registries]\njobs = "core:jobs"\ndecisions = "core:decisions"\nproposals = "core:proposals"\n'
                                            '[storage]\ndir = ["jobs", "decisions", "proposals"]\n[policy]\ndecisions = "registry:decisions"\ndecision_prefix = "C"\n'
                                            '[jobs]\nid_prefix = "W"\n[jobs.text]\nowner = "Liam"\n[audit]\nauto_apply = ["doc_cap"]\n', encoding='utf-8')
        self.ctx = Ctx.load(self.root)

    def regs(self):
        return P.load(self.ctx)

    def put(self, *rows):
        regs = self.regs()
        for r in rows:
            regs['proposals'].add(r, replace=True)
        regs['proposals'].save()

    def record(self, findings):
        f = self.root / 'docs/audits/AUDIT_2026-11-05.json'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rec(findings)), encoding='utf-8')
        return f

    def answer(self, answers, branch='decide/2026-11-06', quote='Yes to all.\n| a pipe'):
        return P.answer(self.ctx, answers, quote, branch, today='2026-11-06', taken=set())

    def status(self, rid=ID):
        return self.regs()['proposals'].by_id()[rid]

    def test_draft_writes_a_skeleton_per_new_finding_with_its_baseline(self):
        self.record([found(), found(fid='doc_cap:docs/Y.md')])
        made = P.draft(self.ctx, today='2026-11-06')
        self.assertEqual(len(made), 2)
        r = self.regs()['proposals'].by_id()[made[0]]
        self.assertRegex(r['id'], r'^P261106-[0-9a-f]{4}$')
        self.assertEqual((r['class'], r['status'], r['options'], r['baseline']['value'], r['baseline']['record']), ('doc_cap', 'open', [], 29.0, 'docs/audits/AUDIT_2026-11-05.json'))

    def test_draft_skips_a_live_row_and_is_idempotent(self):
        self.record([found()])
        self.put(row())
        self.assertEqual(P.draft(self.ctx, today='2026-11-06'), [])
        self.put(answered(ID2, option='rule'))
        self.assertEqual(P.draft(self.ctx, today='2026-11-06'), [])

    def test_draft_after_a_decline_came_back_names_the_row_it_follows(self):
        self.record([found(40.0)])
        self.put(answered(option='no', status='declined'))
        made = P.draft(self.ctx, today='2026-11-06')
        self.assertEqual(self.status(made[0])['reraises'], ID)

    def test_draft_with_no_record_says_so(self):
        with self.assertRaises(ValueError):
            P.draft(self.ctx, today='2026-11-06')

    def test_check_refuses_a_skeleton_and_a_bad_recommendation(self):
        self.put({**row(options=[]), 'recommended': 'split'})
        self.assertTrue(any('fill the skeleton' in e for e in P.check(self.ctx)))
        self.put(row(ID2, finding='doc_cap:docs/Z.md', recommended='nope'))
        self.assertTrue(any('recommended' in e for e in P.check(self.ctx)))

    def test_check_refuses_a_bad_recipe(self):
        opts = [{'key': 'a', 'kind': 'job', 'summary': 's', 'recipe': {'title': 't'}}, {'key': 'b', 'kind': 'decision', 'summary': 's'}]
        self.put(row(options=opts, recommended='a'))
        errs = P.check(self.ctx)
        self.assertTrue(any('description' in e for e in errs), errs)
        self.assertTrue(any('recipe' in e and "'b'" in e for e in errs), errs)

    def test_check_refuses_two_live_rows_on_a_finding(self):
        self.put(row(), row(ID2))
        self.assertTrue(any('doc_cap:docs/X.md' in e for e in P.check(self.ctx)))

    def test_check_refuses_an_answer_naming_what_does_not_exist(self):
        self.put(answered())
        errs = P.check(self.ctx)
        for word in (ANS, DEC, 'W200'):
            self.assertTrue(any(word in e for e in errs), (word, errs))

    def test_check_is_quiet_on_good_rows(self):
        self.put(row())
        self.assertEqual(P.check(self.ctx), [])

    def test_ask_is_severity_first_and_capped(self):
        high = row(ID2, finding='doc_cap:docs/Y.md')
        high['baseline'] = {**high['baseline'], 'severity': 'high'}
        self.put(row(), high, answered('P261106-cccc', option='no', status='declined'))
        out = P.ask(self.ctx, 1)
        self.assertIn(ID2, out)
        self.assertNotIn(ID + ' ', out)
        self.assertIn('1 more', out)
        self.assertIn(ID, P.ask(self.ctx, 8))
        self.assertNotIn('P261106-cccc', P.ask(self.ctx, 8))

    def test_ask_with_none_open(self):
        self.assertIn('nothing', P.ask(self.ctx, 8).lower())

    def test_answer_writes_rows_a_decision_a_job_and_the_record(self):
        self.put(row(), row(ID2, finding='doc_cap:docs/Y.md'), row('P261106-cccc', finding='doc_cap:docs/Z.md'), row('P261106-dddd', finding='doc_cap:docs/V.md'))
        self.answer({ID: 'recommended', ID2: 'no', 'P261106-cccc': 'later'})
        a, b, c, d = (self.status(i) for i in (ID, ID2, 'P261106-cccc', 'P261106-dddd'))
        self.assertEqual((a['status'], b['status'], c['status'], d['status']), ('accepted', 'declined', 'deferred', 'open'))
        self.assertEqual(a['answer'], {'by': 'Liam', 'date': '2026-11-06', 'record': ANS, 'option': 'split'})
        regs = self.regs()
        self.assertEqual(regs['jobs'].by_id()[a['job']]['status'], 'needs_brief')
        self.assertIn(ID, regs['decisions'].by_id()[a['decision']]['decision'])
        self.assertNotIn(ID2, regs['decisions'].by_id()[a['decision']]['decision'])
        self.assertNotIn('decision', b)
        got = (self.root / ANS).read_text(encoding='utf-8')
        self.assertIn('> Yes to all.\n> | a pipe', got)
        for i in (ID, ID2, 'P261106-cccc'):
            self.assertIn(i, got)
        self.assertNotIn('P261106-dddd', got)

    def test_answer_draws_a_job_id_past_every_branch(self):
        self.put(row())
        P.answer(self.ctx, {ID: 'split'}, 'q', 'decide/2026-11-06', today='2026-11-06', taken={'W7', 'W300'})
        self.assertEqual(self.status()['job'], 'W301')

    def test_one_decision_row_for_the_round(self):
        self.put(row(), row(ID2, finding='doc_cap:docs/Y.md'))
        self.answer({ID: 'rule', ID2: 'split'})
        self.assertEqual(self.status()['decision'], self.status(ID2)['decision'])
        self.assertEqual(len(self.regs()['decisions'].rows), 1)

    def test_a_decision_is_as_reversible_as_its_least_reversible_recipe(self):
        opts = [{'key': 'r', 'kind': 'decision', 'summary': 's', 'recipe': {'decision': 'd', 'reversible': 'no'}}]
        self.put(row(), row(ID2, finding='doc_cap:docs/Y.md', options=opts, recommended='r'))
        self.answer({ID: 'rule', ID2: 'r'})
        self.assertEqual(self.regs()['decisions'].rows[0]['reversible'], 'no')

    def test_answer_is_refused_off_a_decide_branch(self):
        self.put(row())
        for branch in ('plan/x', 'main', 'job/W9'):
            with self.assertRaises(ValueError):
                self.answer({ID: 'split'}, branch=branch)
        self.assertEqual(self.status()['status'], 'open')

    def test_answer_refuses_unknown_rows_options_and_answered_rows_and_writes_nothing(self):
        self.put(row(), answered(ID2, option='no', status='declined'))
        for bad in ({'P261106-ffff': 'split'}, {ID: 'nope'}, {ID: 'split', ID2: 'no'}):
            with self.assertRaises(ValueError):
                self.answer(bad)
        self.assertEqual(self.status()['status'], 'open')
        self.assertFalse((self.root / ANS).exists())

    def test_the_second_round_of_a_day_writes_its_own_record(self):
        self.put(row())
        self.answer({ID: 'no'}, branch='decide/2026-11-06-2')
        self.assertEqual(self.status()['answer']['record'], 'docs/audits/ANSWERS_2026-11-06_2.md')

    def test_auto_accepts_a_listed_untagged_class_at_its_recommendation(self):
        other = row('P261106-eeee', finding='other:x', **{'class': 'other'})
        self.put(row(), row(ID2, finding='doc_cap:docs/Y.md', tag='risk'), other)
        made = P.answer_auto(self.ctx, 'plan/audit-x', today='2026-11-06', taken=set())
        self.assertEqual(made, [ID])
        a = self.status()
        self.assertEqual((a['status'], a['answer']['by'], a['answer']['option'], a['answer']['record']), ('accepted', 'auto_apply', 'split', 'docs/audits/AUDIT_2026-11-05.json'))
        self.assertEqual((self.status(ID2)['status'], self.status('P261106-eeee')['status']), ('open', 'open'))

    def test_auto_is_refused_off_a_plan_branch(self):
        with self.assertRaises(ValueError):
            P.answer_auto(self.ctx, 'decide/2026-11-06', today='2026-11-06', taken=set())

    def closing(self, verdict, value=29.0):
        return {**rec([]), 'remeasured': [{'proposal': ID, 'finding': 'doc_cap:docs/X.md', 'baseline': 29.0, 'value': value, 'verdict': verdict}]}

    def test_close_closes_moved_and_gone(self):
        for verdict in ('moved', 'gone'):
            self.put(answered(option='rule'))
            self.assertEqual(P.close(self.ctx, self.closing(verdict), 'r.json', today='2026-11-17')['closed'], [ID])
            self.assertEqual((self.status()['status'], self.status()['outcome']), ('closed', verdict))

    def test_close_reraises_not_moved_with_the_delta(self):
        self.put(answered(option='rule'))
        out = P.close(self.ctx, self.closing('not_moved', 30.0), 'r.json', today='2026-11-17')
        self.assertEqual(self.status()['outcome'], 'not_moved')
        new = self.status(out['drafted'][0])
        self.assertEqual((new['reraises'], new['status'], new['options']), (ID, 'open', []))
        self.assertIn('+1', new['question'])

    def test_close_leaves_too_soon_and_unmeasured(self):
        for verdict in ('too_soon', 'unmeasured'):
            self.put(answered(option='rule'))
            self.assertEqual(P.close(self.ctx, self.closing(verdict), 'r.json', today='2026-11-17')['closed'], [])
            self.assertEqual(self.status()['status'], 'accepted')

    def test_close_closes_an_open_row_whose_finding_went(self):
        self.put(row())
        P.close(self.ctx, rec([]), 'r.json', today='2026-11-17')
        self.assertEqual((self.status()['status'], self.status()['outcome']), ('closed', 'gone'))

    def test_close_leaves_an_open_row_on_an_unmeasured_metric_or_a_live_finding(self):
        self.put(row())
        P.close(self.ctx, rec([], metrics=()), 'r.json', today='2026-11-17')
        P.close(self.ctx, rec([found()]), 'r.json', today='2026-11-17')
        self.assertEqual(self.status()['status'], 'open')

    def test_the_lane_is_the_open_rows_or_nothing(self):
        self.assertEqual(P.view_html(self.ctx), '')
        self.put(row(question='a <b> question'))
        got = P.view_html(self.ctx)
        self.assertIn('Waiting on Liam', got)
        self.assertIn('a &lt;b&gt; question', got)


    def test_jobs_view_carries_the_lane(self):
        self.put(row(question='a question for the page'))
        jobq.configure(self.ctx)
        page = jobq.render_view([], lambda p: None, set(), 'now', ctx=self.ctx, owner_html=P.view_html(self.ctx))
        self.assertIn('a question for the page', page)

    def test_both_callers_of_the_page_pass_the_lane(self):
        """`jobs view` and `--serve` each build the page: a caller that drops the argument shows nothing and fails nothing."""
        self.assertIn('owner_html=proposals.view_html(ctx)', (ROOT / 'warscape/verbs/jobs.py').read_text(encoding='utf-8'))
        self.assertIn('proposals.view_html(self.ctx)', (ROOT / 'warscape/jobq.py').read_text(encoding='utf-8'))

    def test_the_jobs_gate_runs_the_check(self):
        self.put(row(options=[]))
        got = gates.gate_jobs(self.ctx)
        self.assertEqual(got.level, 'error')
        self.assertTrue(any('fill the skeleton' in d for d in got.details), got.details)

    def test_reg_add_mints_a_proposal_id(self):
        r = row()
        del r['id'], r['date']
        p = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(self.root), 'reg', 'add', 'proposals', '--mint', '--json', json.dumps(r)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(self.regs()['proposals'].rows[0]['id'], r'^P\d{6}-[0-9a-f]{4}$')


class NoRegistry(unittest.TestCase):
    def test_the_lane_and_the_check_are_quiet_where_the_registry_is_not_declared(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, 'wsc.toml').write_text('registries_dir = "registries"\n[registries]\njobs = "core:jobs"\n', encoding='utf-8')
            ctx = Ctx.load(Path(t))
            self.assertEqual(P.view_html(ctx), '')
            self.assertEqual(P.check(ctx), [])


if __name__ == '__main__':
    unittest.main()
