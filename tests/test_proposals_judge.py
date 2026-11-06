"""Host tests for the guard on proposal rows (W45, C41) through the real judge: every case is a real commit on a real branch name, judged by `wsc policy --branch <b> --base origin/main`
(the parent, `git archive` of the base, the `--judge` child), where tests/test_proposals.py calls `check` in-process. One seeded repo for the class: a copy of this checkout's code, so the base's rules are the
rules under test, `[audit] auto_apply = ["doc_cap"]`, refs mirrored and nothing pushed. Each route of "auto-accepted with a tag, or with a class its finding does not have" has a test here.
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
sys.path.insert(0, str(ROOT / 'tests'))
from test_proposals import ID as L, row  # noqa: E402

T, G, W, H = 'P261106-0001', 'P261106-0002', 'P261106-0003', 'P261106-0004'   # tagged open, tagged closed, a class it should not have, a hot_file row
NEW, OTHER, AUD = 'P261106-00ff', 'P261106-00fe', 'docs/audits/AUDIT_2026-11-05.json'
TOML = """registries_dir = "registries"
[ci]
core = ""
[registries]
jobs = "core:jobs"
decisions = "core:decisions"
proposals = "core:proposals"
[storage]
dir = ["jobs", "decisions", "proposals"]
[policy]
decisions = "registry:decisions"
decision_prefix = "C"
plan = ["docs/*", "docs/**", "registries/jobs/*", "registries/decisions/*", "registries/proposals/*"]
[jobs]
id_prefix = "W"
[jobs.text]
owner = "Liam"
[audit]
auto_apply = ["doc_cap"]
"""


def pjson(r):
    return json.dumps(r, indent=2) + '\n'


def rowfile(rid):
    return f'registries/proposals/{rid}.json'


def on(subject, rid=NEW, rule='doc_cap', **kw):
    """A row on the finding `<rule>:<subject>`, its class the rule unless `kw` says otherwise."""
    return row(rid, **{'finding': f'{rule}:docs/{subject}.md', 'metric': 'hot_files' if rule == 'hot_file' else 'doc_caps', 'class': rule, **kw})


def auto(r, **kw):
    """`r` as `wsc proposals answer --auto` leaves it: the recommended `split` is a job option."""
    return {**r, 'status': 'accepted', 'answer': {'by': 'auto_apply', 'date': '2026-11-06', 'record': r['baseline']['record'], 'option': 'split'}, 'decision': 'C261106-cccc', 'job': 'W200', **kw}


def audit_row(fid, metric):
    return {'id': fid, 'metric': metric, 'subject': fid.partition(':')[2], 'severity': 'medium', 'value': 29.0, 'threshold': 27.0, 'direction': 'above', 'evidence': 'e'}


def record(*extra):
    found = [audit_row(f'doc_cap:docs/{n}.md', 'doc_caps') for n in 'LTGN'] + [audit_row(f'hot_file:docs/{n}.md', 'hot_files') for n in ('new', 'H', 'W')]
    return json.dumps({'version': 1, 'date': '2026-11-05', 'metrics': {'doc_caps': {}, 'hot_files': {}}, 'findings': found + list(extra), 'skipped': [], 'failed': []}, indent=2) + '\n'


SEED = {AUD: record(), rowfile(L): pjson(on('L', L)), rowfile(T): pjson(on('T', T, tag='risk')), rowfile(G): pjson(on('G', G, tag='legal', status='closed', outcome='gone')),
        rowfile(W): pjson(on('W', W, rule='hot_file', **{'class': 'doc_cap'})), rowfile(H): pjson(on('H', H, rule='hot_file'))}


class Repo:
    def __init__(self, d):
        self.d = Path(d)
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env = {**env, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull}

    def git(self, *a):
        return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false', *a], cwd=self.d, env=self.env, capture_output=True, text=True, check=True).stdout.strip()

    def put(self, files):
        for p, t in files.items():
            f = self.d / p
            if t is None:
                f.unlink()
            else:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(t, encoding='utf-8', newline='\n')

    def wsc(self, *a):
        p = subprocess.run([sys.executable, '-X', 'utf8', 'wsc.py', '--root', str(self.d), *a], cwd=self.d, env=self.env, capture_output=True, text=True, encoding='utf-8')
        return p.returncode, p.stdout + p.stderr


class RealJudge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.addClassCleanup(cls.tmp.cleanup)
        r = cls.r = Repo(cls.tmp.name)
        r.git('init', '-q', '--template=', '-b', 'main', '.')
        for n in ('warscape', 'schemas'):
            shutil.copytree(ROOT / n, r.d / n, ignore=shutil.ignore_patterns('__pycache__'))
        for n in ('wsc.py', 'VERSION'):
            shutil.copy(ROOT / n, r.d / n)
        r.put({'wsc.toml': TOML, '.gitignore': '__pycache__/\n_scratch/\n', **SEED})
        r.git('add', '-A')
        r.git('commit', '-q', '-m', 'seed')
        cls.seed = r.git('rev-parse', 'HEAD')
        r.git('update-ref', 'refs/remotes/origin/main', cls.seed)

    def setUp(self):
        self.r.git('switch', '-q', '-f', '--detach', self.seed)
        self.r.git('clean', '-fdq')
        self.r.git('update-ref', 'refs/heads/main', self.seed)
        self.r.git('update-ref', 'refs/remotes/origin/main', self.seed)

    def commit(self, branch, files):
        """`files` ({path: text, or None to delete}) as one commit on `branch`, cut from main. Returns the branch."""
        self.r.git('switch', '-q', '-f', '-C', branch, 'main')
        self.r.put(files)
        self.r.git('add', '-A')
        self.r.git('commit', '-q', '--allow-empty', '-m', branch)
        return branch

    def judged(self, branch):
        return self.r.wsc('policy', '--branch', branch, '--base', 'origin/main')

    def land(self, branch):
        """`branch` merged to main, as a merge would leave origin/main."""
        self.r.git('switch', '-q', 'main')
        self.r.git('merge', '-q', '--no-edit', branch)
        self.r.git('update-ref', 'refs/remotes/origin/main', self.r.git('rev-parse', 'HEAD'))

    def refused(self, branch, files, word=''):
        self.commit(branch, files)
        rc, out = self.judged(branch)
        self.assertEqual(rc, 1, out)
        self.assertIn('REFUSED', out)
        self.assertIn(word, out)

    def ok(self, branch, files):
        self.commit(branch, files)
        rc, out = self.judged(branch)
        self.assertEqual(rc, 0, out)
        self.assertIn(f'{branch}: ok', out)

    # The controls: the guard must not stop the round.
    def test_control_add_fill_tag_and_close(self):
        self.ok('plan/add', {rowfile(NEW): pjson(on('N'))})
        self.ok('plan/fill', {rowfile(L): pjson(on('L', L, question='Better?', recommended='rule'))})
        self.ok('plan/tag', {rowfile(L): pjson(on('L', L, tag='taste'))})
        self.ok('plan/close', {rowfile(T): pjson(on('T', T, tag='risk', status='closed', outcome='gone'))})

    def test_control_auto_accepts_a_listed_row(self):
        self.ok('plan/auto', {rowfile(L): pjson(auto(on('L', L)))})
        self.ok('plan/auto-new', {rowfile(NEW): pjson(auto(on('N')))})

    def test_control_the_record_and_its_rows_in_one_branch(self):
        rec = 'docs/audits/AUDIT_2026-11-06.json'
        r = on('Z')
        r['baseline'] = {**r['baseline'], 'record': rec}
        self.ok('plan/audit-1', {rec: record(audit_row('doc_cap:docs/Z.md', 'doc_caps')), rowfile(NEW): pjson(auto(r))})

    def test_control_the_verb_leaves_a_tagged_finding_and_policy_agrees(self):
        """`answer --auto` on the tree `close` leaves: an untagged row re-raised on a tagged finding stays open, and the branch it writes passes."""
        self.commit('plan/verb', {rowfile(T): pjson(on('T', T, tag='risk', status='closed', outcome='gone')), rowfile(NEW): pjson(on('T', reraises=T))})
        rc, out = self.r.wsc('proposals', 'answer', '--auto', '--date', '2026-11-06')
        self.assertEqual(rc, 0, out)
        status = lambda rid: json.loads((self.r.d / rowfile(rid)).read_text(encoding='utf-8'))['status']
        self.assertEqual((status(L), status(NEW), status(W)), ('accepted', 'open', 'open'))
        self.r.git('add', '-A')
        self.r.git('commit', '-q', '-m', 'auto')
        rc, out = self.judged('plan/verb')
        self.assertEqual(rc, 0, out)

    # 1. A class its finding does not have.
    def test_a_new_row_accepted_with_another_rules_class(self):
        self.refused('plan/r1', {rowfile(NEW): pjson(auto(on('new', rule='hot_file', **{'class': 'doc_cap'})))})

    def test_a_new_open_row_with_another_rules_class(self):
        self.refused('plan/r2', {rowfile(NEW): pjson(on('new', rule='hot_file', **{'class': 'doc_cap'}))}, 'class')

    def test_a_row_already_on_the_base_with_another_rules_class(self):
        self.refused('plan/r3', {rowfile(W): pjson(auto(on('W', W, rule='hot_file', **{'class': 'doc_cap'})))}, 'class')

    def test_a_relabel_on_an_existing_row(self):
        self.refused('plan/r4', {rowfile(H): pjson(on('H', H, rule='hot_file', **{'class': 'doc_cap'}))}, 'class')
        self.refused('plan/r4b', {rowfile(H): pjson(auto(on('H', H, rule='hot_file', **{'class': 'doc_cap'})))}, 'class')

    def test_the_finding_changed_to_fit_the_class(self):
        self.refused('plan/r5', {rowfile(H): pjson(on('H', H, **{'metric': 'hot_files'}))}, 'finding')

    def test_a_finding_the_record_does_not_hold(self):
        """`doc_cap:docs/H.md` reads as the class, but the record's finding on that subject is `hot_file`."""
        self.refused('plan/r6', {rowfile(NEW): pjson(auto(on('H')))}, 'record')

    def test_a_finding_under_another_metric(self):
        self.refused('plan/r7', {rowfile(NEW): pjson(auto(on('N', metric='hot_files')))}, 'record')

    def test_a_question_row_has_no_finding_to_be_of_a_class(self):
        r = on('N', kind='question')
        for k in ('finding', 'metric'):
            del r[k]
        self.refused('plan/r8', {rowfile(NEW): pjson(auto(r))}, 'finding')

    def test_a_baseline_naming_a_file_that_is_no_record(self):
        fake = 'docs/fake.json'
        r = on('Q')
        r['baseline'] = {**r['baseline'], 'record': fake}
        self.refused('plan/r9', {fake: record(audit_row('doc_cap:docs/Q.md', 'doc_caps')), rowfile(NEW): pjson(auto(r))}, 'record')
        r['baseline'] = {**r['baseline'], 'record': 'docs/audits/x/../AUDIT_2026-11-05.json'}
        self.refused('plan/r9b', {rowfile(NEW): pjson(auto(r))}, 'record')

    def test_a_merged_record_is_never_rewritten_or_deleted(self):
        extra = audit_row('doc_cap:docs/Q.md', 'doc_caps')
        self.refused('plan/r10', {AUD: record(extra), rowfile(NEW): pjson(auto(on('Q')))}, 'never')
        self.refused('plan/r10b', {AUD: record(extra)}, 'never')
        self.refused('plan/r10c', {AUD: None}, 'never')

    # 2. A tagged finding.
    def test_a_tagged_row_left_open_beside_a_new_accepted_row(self):
        self.refused('plan/t1', {rowfile(NEW): pjson(auto(on('T')))}, 'tag')

    def test_closed_as_gone_and_a_new_accepted_row_in_one_branch(self):
        self.refused('plan/t2', {rowfile(T): pjson(on('T', T, tag='risk', status='closed', outcome='gone')), rowfile(NEW): pjson(auto(on('T')))}, 'tag')

    def test_closed_as_gone_and_a_new_accepted_row_in_two_branches(self):
        self.ok('plan/t3a', {rowfile(T): pjson(on('T', T, tag='risk', status='closed', outcome='gone'))})
        self.land('plan/t3a')
        self.refused('plan/t3b', {rowfile(NEW): pjson(auto(on('T')))}, 'tag')

    def test_a_row_closed_long_ago_still_holds_its_tag(self):
        self.refused('plan/t4', {rowfile(NEW): pjson(auto(on('G')))}, 'tag')

    def test_the_tag_added_in_the_same_branch_on_another_row(self):
        self.refused('plan/t5', {rowfile(NEW): pjson(auto(on('N'))), rowfile(OTHER): pjson(on('N', OTHER, tag='taste'))}, 'tag')

    def test_a_stale_branch_cut_before_the_tag_landed(self):
        """The tag is at the base's tip, not at the merge base."""
        self.commit('plan/t6', {rowfile(NEW): pjson(auto(on('N')))})
        self.commit('plan/t6a', {rowfile(OTHER): pjson(on('N', OTHER, tag='taste'))})
        self.land('plan/t6a')
        self.r.git('switch', '-q', 'plan/t6')
        rc, out = self.judged('plan/t6')
        self.assertEqual(rc, 1, out)
        self.assertIn('tag', out)

    def test_the_tagged_row_moved_off_its_finding(self):
        """The two-branch form: move the row off the finding, then add a clean one. The first branch is what must stop."""
        self.refused('plan/t7', {rowfile(T): pjson(on('Elsewhere', T, tag='risk'))}, 'finding')

    def test_every_field_the_fill_does_not_own_is_frozen(self):
        for k, v in (('kind', 'question'), ('metric', 'hot_files'), ('date', '2026-11-07'), ('reraises', L), ('baseline', {**row()['baseline'], 'record': 'docs/audits/AUDIT_2026-11-06.json'})):
            with self.subTest(k):
                self.refused(f'plan/t8-{k}', {rowfile(T): pjson(on('T', T, tag='risk', **{k: v}))}, k)

    def test_a_tag_stripped_in_each_spelling(self):
        for n, tag in enumerate((None, '', False, 'taste')):
            with self.subTest(tag):
                self.refused(f'plan/t9-{n}', {rowfile(T): pjson(on('T', T, tag=tag))}, 'tag')
        self.refused('plan/t9-gone', {rowfile(T): pjson(on('T', T))}, 'tag')
        self.refused('plan/t9-accept', {rowfile(T): pjson(auto(on('T', T)))}, 'tag')

    def test_a_duplicate_key_reads_as_its_last(self):
        text = pjson(on('T', T, tag='risk')).replace('"tag": "risk"', '"tag": "risk",\n  "tag": null')
        self.refused('plan/t10', {rowfile(T): text}, 'tag')

    def test_the_row_of_a_tagged_finding_under_another_file_name(self):
        for n, name in enumerate(('P261106%2D0001.json', 'P261106-0001', 'P261106-0001.JSON', 'sub/P261106-0001.json')):
            with self.subTest(name):
                self.refused(f'plan/t11-{n}', {f'registries/proposals/{name}': pjson(auto(on('T', T)))})

    def test_the_head_cannot_widen_auto_apply(self):
        self.refused('plan/t12', {'wsc.toml': TOML.replace('["doc_cap"]', '["doc_cap", "hot_file"]'), rowfile(H): pjson(auto(on('H', H, rule='hot_file')))})

    def test_a_status_outside_the_states(self):
        self.refused('plan/t13', {rowfile(T): pjson(on('T', T, tag='risk', status='Accepted'))}, 'status')

    def test_an_answer_that_is_no_object_fails_closed(self):
        self.refused('plan/t14', {rowfile(L): pjson({**on('L', L), 'status': 'accepted', 'answer': 'auto_apply'})})

    def test_a_second_copy_beside_the_folder(self):
        line = json.dumps(auto(on('T'))) + '\n'
        self.refused('plan/t15', {'registries/proposals.jsonl': line})
        self.refused('job/W9', {'registries/proposals.jsonl': line}, 'proposal')

    def test_no_other_kind_adds_a_row(self):
        self.refused('meta/t16', {rowfile(NEW): pjson(auto(on('N')))}, 'proposal')
        self.refused('job/W9', {rowfile(NEW): pjson(auto(on('N')))}, 'proposal')

    def test_decide_cannot_strip_a_tag_or_relabel_a_row_it_does_not_answer(self):
        self.refused('decide/2026-11-06', {rowfile(T): pjson(on('T', T))}, 'tag')
        self.refused('decide/2026-11-06', {rowfile(T): pjson(on('T', T, tag='taste'))}, 'tag')
        self.refused('decide/2026-11-06', {rowfile(H): pjson(on('H', H, rule='hot_file', **{'class': 'doc_cap'}))}, 'class')
        self.refused('decide/2026-11-06', {rowfile(T): pjson(on('Elsewhere', T, tag='risk'))}, 'finding')

    def test_the_known_limit_a_new_hand_written_record(self):
        """Not a wish: the judge reads a diff and cannot re-measure, so a new record with an invented finding passes. docs/PROPOSALS.md "Traps" says so, and this test fails when that changes."""
        rec = 'docs/audits/AUDIT_2026-11-07.json'
        r = on('H')
        r['baseline'] = {**r['baseline'], 'record': rec}
        self.ok('plan/limit', {rec: record(audit_row('doc_cap:docs/H.md', 'doc_caps')), rowfile(NEW): pjson(auto(r))})

    def test_two_branches_each_green_alone(self):
        """Neither sees the other, so the judge passes both: `proposals check`, in the `jobs` gate on the next run, is what refuses the tree they leave."""
        self.ok('plan/race-b', {rowfile(NEW): pjson(auto(on('N')))})
        self.ok('plan/race-a', {rowfile(OTHER): pjson(on('N', OTHER, tag='taste'))})
        self.land('plan/race-a')
        self.land('plan/race-b')
        rc, out = self.r.wsc('proposals', 'check')
        self.assertNotEqual(rc, 0, out)
        self.assertIn('tag', out)


if __name__ == '__main__':
    unittest.main()
