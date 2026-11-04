"""W23: a pull request is judged with its base's rules. The verb (warscape/verbs/policy.py) writes the base's rule inputs into a temporary folder and
runs the base's code there in a child process; the head reaches the judge only as git objects (warscape/policy.py). Throwaway repos, real git, the
real CLI in subprocesses. Every test here was red on f879196, the commit W23 started from.

- CoreMode: a clone of the throwaway core (tests/_util.py `core_source`) judging its own branches: the audit's four bypasses (napoleon-remastered
  docs/audits/AUDIT_2026-11-03.md P2), a head verb module, the rule-input note, local equals CI, the fallback for a base from before W23, and the
  fail-closed cases.
- GameMode: the fixture game with that core as its `core` submodule: a head that edits or drops the base's gate modules, a repointed core gitlink,
  a base pin the submodule lacks, a base with no gitlink, and what the base tree holds.

`ci()` runs what CI's `policy` job runs, chosen by the base's rendered policy.yml. With `pull_request_target` (W23) GitHub runs the base's workflow,
which checks out the base and passes `--head`; before W23, `pull_request` ran the head's workflow on GitHub's merge commit, whose code is the head's
(modelled by the head checkout). `local()` is a run from the head checkout with this checkout's code as the parent, an honest parent.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _util import CORE, core_source, fixture_game, git

sys.path.insert(0, str(CORE))
from warscape import policy as pp  # noqa: E402

WSC = CORE / 'wsc.py'
JUDGED ='policy: judged with the rules of origin/main at '

PEEK = '''import subprocess
from warscape.gates import Result
NAME = 'peek'
STAGES = ('policy',)


def run(ctx):
    out = subprocess.run(['git', '-C', str(ctx.root), 'show', 'HEAD:x'], capture_output=True, text=True, check=True).stdout
    return Result(NAME, 'error', 'read a repository at ctx.root: ' + out.strip())
'''

FACTS = '''from warscape.gates import Result
from warscape.policy import show
NAME = 'facts'
STAGES = ('policy',)


def run(ctx):
    f = ctx.facts
    return Result(NAME, 'error', 'facts', [f"{k}={f.get(k)}" for k in ('branch', 'kind', 'base', 'head', 'base_ref')]
                  + [f"repo_is_root={f.get('repo') == str(ctx.root)}", f"head_blob={(show(f['head'], 'docs/peek.md', cwd=f['repo']) or '').strip()}",
                     f"root_has_x={(ctx.root / 'x').is_file()}"])
'''

SCOPE = '''from warscape.gates import Result
NAME = 'scope'
STAGES = ('policy',)


def run(ctx):
    top = sorted({p.split('/')[0] for p in ctx.files()})
    return Result(NAME, 'error', 'scope', ['top=' + ','.join(top), f"legacy={(ctx.root / 'jobs' / 'legacy.json').is_file()}"])
'''

EVIL = '''

def check(*a, **k):
    with open({sentinel!r}, 'w') as f:
        f.write('the head pin ran')
    return []
'''

LOST = '0123456789abcdef' * 2 + '01234567'


def run(args, cwd, env=None):
    p = subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True, timeout=300, env=env)
    return p.returncode, p.stdout, p.stderr


class Branches:
    """Branch helpers over the throwaway repo `d`, whose `main` (and `origin/main`) is the base."""
    game = False

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
        self.back()

    def back(self):
        git(self.d, 'checkout', '-q', '-f', 'main')
        if self.game:
            git(self.d, 'submodule', 'update', '-q')

    def text(self, rel, ref='main'):
        return git(self.d, 'show', f'{ref}:{rel}').stdout

    def sha(self, ref):
        return git(self.d, 'rev-parse', ref).stdout.strip()

    def ci(self, name):
        wf = self.text('.github/workflows/policy.yml')
        new = re.search(r'^  pull_request_target:', wf, re.M)
        head = self.sha(name)
        git(self.d, 'checkout', '-q', '-f', 'main' if new else name)
        if self.game:
            git(self.d, 'submodule', 'update', '-q')   # actions/checkout with submodules: true
        try:
            wsc = self.d / ('core/wsc.py' if self.game else 'wsc.py')
            return run([wsc, 'policy', '--branch', name, '--base', 'origin/main', *(['--head', head] if new else [])], self.d)
        finally:
            self.back()

    def local(self, name, *extra):
        git(self.d, 'checkout', '-q', '-f', name)
        if self.game:
            git(self.d, 'submodule', 'update', '-q')   # the head's own pin on disk: the judge must never run it
        try:
            return run([WSC, '--root', self.d, 'policy', '--branch', name, '--base', 'origin/main', *extra], self.d)
        finally:
            self.back()

    def policy(self, name, base, env=None):
        """This checkout's parent from the base checkout, naming the head with --head."""
        return run([WSC, '--root', self.d, 'policy', '--branch', name, '--base', base, '--head', name], self.d, env)

    def assertRefused(self, res, *needles):
        rc, out, err = res
        self.assertEqual(rc, 1, out + err)
        for n in needles:
            self.assertIn(n, out + err)

    @staticmethod
    def note(out):
        return next((l for l in out.splitlines() if l.startswith('policy: note: this branch changes ')), '')


class CoreMode(Branches, unittest.TestCase):
    trailer = 'Claude-Session'

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls._tmp.name).resolve() / 'core'
        git(cls._tmp.name, 'clone', '-q', str(core_source()), str(cls.d))
        row = {'id': 'W900', 'title': 'A test job', 'status': 'queued', 'brief': 'jobs/W900/brief.md'}
        cls.commit(cls, {'jobs/W900/brief.md': '# W900: a test job\n', 'registries/jobs/W900.json': json.dumps(row, indent=2) + '\n'})
        git(cls.d, 'update-ref', 'refs/remotes/origin/main', 'main')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def toml(self, ref='main'):
        return self.text('wsc.toml', ref)

    # ------------------------------------------------------------ W27: the audit's repros through the CLI, as CI runs it
    def w27_job(self, review_steps, report='# W900 report: a test job\n'):
        """job/W900: the builder S1 writes the report, then each (session, files) step commits; a files dict holding the review sets the row done."""
        git(self.d, 'checkout', '-q', '-f', '-B', 'job/W900', 'main')
        self.commit({'jobs/W900/report.md': report, 'lib/built.py': 'x = 1\n'}, trailer='S1')
        row = {'id': 'W900', 'title': 'A test job', 'status': 'done', 'brief': 'jobs/W900/brief.md', 'report': 'jobs/W900/report.md',
               'review': 'jobs/W900/review.md'}
        for who, fs in review_steps:
            if 'jobs/W900/review.md' in fs:
                fs = {**fs, 'registries/jobs/W900.json': json.dumps(row, indent=2) + '\n'}
            self.commit(fs, trailer=who)
        self.back()
        return self.ci('job/W900')

    @staticmethod
    def w27_round(n, v, extra=''):
        return f'## Round {n} (2026-11-04, branch job/W900 at abc123{n})\n\n**Verdict: {v}.**\n{extra}\n'

    def reviewer_code(self, mode):
        """A base branch whose wsc.toml says `reviewer_code = <mode>`, whatever main's says."""
        name = f'rc-{mode}'
        text = re.sub(r'^reviewer_code = .*\n', '', self.toml(), flags=re.M).replace('[policy]\n', f'[policy]\nreviewer_code = "{mode}"\n', 1)
        self.branch(name, {'wsc.toml': text})
        git(self.d, 'update-ref', f'refs/remotes/origin/{name}', name)
        return f'origin/{name}'

    def reviewer_job(self, extra=None):
        self.w27_job([('R1', {'jobs/W900/review.md': '# Review\n\n' + self.w27_round(1, 'merge'), 'lib/reviewer.py': 'y = 2\n', **(extra or {})})])

    def test_w40_a_reviewer_code_commit_under_merge_warns_with_a_warn_base(self):
        base = self.reviewer_code('warn')
        self.reviewer_job()
        rc, out, err = self.policy('job/W900', base)
        self.assertEqual(rc, 0, out + err)
        self.assertIn('policy: warning: round 1 of jobs/W900/review.md says merge', out)
        self.assertIn('lib/reviewer.py', out)
        self.assertIn('write the verdict `merge after fixes`; a fresh round reviews your change', out)

    def test_w40_a_reviewer_code_commit_under_merge_is_refused_with_an_error_base(self):
        base = self.reviewer_code('error')
        self.reviewer_job()
        res = self.policy('job/W900', base)
        self.assertRefused(res, 'policy: round 1 of jobs/W900/review.md says merge', 'lib/reviewer.py', 'REFUSED',
                           'write the verdict `merge after fixes`; a fresh round reviews your change')
        self.assertNotIn('policy: warning: round 1', res[1])

    def test_w40_a_head_that_flips_the_key_is_judged_with_the_bases_value(self):
        base = self.reviewer_code('error')
        toml = self.text('wsc.toml', base).replace('reviewer_code = "error"', 'reviewer_code = "warn"')
        self.reviewer_job({'wsc.toml': toml})
        self.assertRefused(self.policy('job/W900', base), 'policy: round 1 of jobs/W900/review.md says merge', 'REFUSED')

    def test_w40_a_warn_base_stays_a_warning_when_the_head_says_error(self):
        base = self.reviewer_code('warn')
        toml = self.text('wsc.toml', base).replace('reviewer_code = "warn"', 'reviewer_code = "error"')
        self.reviewer_job({'wsc.toml': toml})
        rc, out, err = self.policy('job/W900', base)
        self.assertEqual(rc, 0, out + err)
        self.assertIn('policy: warning: round 1 of jobs/W900/review.md says merge', out)

    def test_w40_a_fresh_round_clears_a_stranded_merge_with_an_error_base(self):
        base = self.reviewer_code('error')
        r1 = self.w27_round(1, 'merge')
        self.w27_job([('R1', {'jobs/W900/review.md': '# Review\n\n' + r1, 'lib/reviewer.py': 'y = 2\n'}),
                      ('R2', {'jobs/W900/review.md': '# Review\n\n' + self.w27_round(2, 'merge') + r1})])
        rc, out, err = self.policy('job/W900', base)
        self.assertEqual(rc, 0, out + err)

    def scan(self, prs, **kw):
        """`scan` over this repository with `gh` injected; (exit code, printed lines)."""
        printed = []

        def fake(cmd, **_):
            self.assertEqual(cmd[:3], ['gh', 'pr', 'list'])
            return subprocess.CompletedProcess(cmd, 0, json.dumps(prs), '')
        rc = pp.scan(self.d, run=fake, out=printed.append, **kw)
        return rc, printed

    def merged(self, n):
        """Squash job/W900 onto a throwaway main; the pull request record gh would give."""
        head, name = self.sha('job/W900'), f'scan-main-{n}'
        git(self.d, 'checkout', '-q', '-f', '-B', name, 'main')
        git(self.d, 'commit', '-q', '--allow-empty', '-m', f'squash #{n}')
        merge = self.sha(name)
        self.back()
        git(self.d, 'update-ref', 'refs/remotes/origin/scanned', name)
        return {'number': n, 'headRefName': 'job/W900', 'headRefOid': head, 'mergeCommit': {'oid': merge}, 'mergedAt': '2026-11-04T10:00:00Z'}

    def test_w40_scan_judges_a_merged_branch_at_its_head_and_counts_the_rule(self):
        self.reviewer_job()
        rc, lines = self.scan([self.merged(7)], base='origin/scanned')
        self.assertEqual(rc, 0, lines)
        self.assertTrue(any('job/W900 (#7, 2026-11-04)' in x and 'A: round 1 of jobs/W900/review.md says merge' in x for x in lines), lines)
        self.assertIn('1 branches judged, 0 not judged; A 1,', lines[-1])

    def test_w40_scan_since_leaves_out_what_merged_before_it(self):
        self.reviewer_job()
        pr = self.merged(7)
        rc, lines = self.scan([pr], base='origin/scanned', since=pr['mergeCommit']['oid'])
        self.assertEqual(rc, 0, lines)
        self.assertIn('0 branches judged, 0 not judged', lines[-1])

    def test_w40_scan_since_that_does_not_resolve_is_an_error_not_an_empty_count(self):
        self.reviewer_job()
        rc, lines = self.scan([self.merged(7)], base='origin/scanned', since=LOST)
        self.assertEqual(rc, 1, lines)
        self.assertTrue(any('does not resolve' in x for x in lines), lines)

    def test_w40_scan_a_head_it_cannot_read_is_named_and_exits_1(self):
        self.reviewer_job()
        rc, lines = self.scan([{**self.merged(7), 'headRefOid': LOST}], base='origin/scanned')
        self.assertEqual(rc, 1, lines)
        self.assertTrue(any('job/W900 (#7' in x and 'not judged' in x for x in lines), lines)
        self.assertIn('0 branches judged, 1 not judged', lines[-1])

    def test_w27_b_round_2_by_the_round_1_session_is_refused(self):
        r1 = self.w27_round(1, 'merge after fixes')
        res = self.w27_job([('R1', {'jobs/W900/review.md': '# Review\n\n' + r1}),
                            ('F1', {'jobs/W900/report.md': '# W900 report: a test job\n\n## Fix round 1\nDone.\n'}),
                            ('R1', {'jobs/W900/review.md': '# Review\n\n' + self.w27_round(2, 'merge') + r1})])
        self.assertRefused(res, 'round 2 was written by a session that wrote round 1 (R1): a fresh session per round', JUDGED)

    def test_w27_c_a_rewritten_round_1_is_refused_even_after_a_restore(self):
        r1 = self.w27_round(1, 'merge after fixes')
        res = self.w27_job([('R1', {'jobs/W900/review.md': '# Review\n\n' + r1}),
                            ('F1', {'jobs/W900/report.md': '# W900 report: a test job\n\n## Fix round 1\nDone.\n'}),
                            ('R2', {'jobs/W900/review.md': '# Review\n\n' + self.w27_round(2, 'merge') + self.w27_round(1, 'merge')}),
                            ('R2', {'jobs/W900/review.md': '# Review\n\n' + self.w27_round(2, 'merge') + r1})])
        self.assertRefused(res, 'append only', 'round 1', JUDGED)

    def test_w27_d_a_missing_run_folder_and_an_unmerged_branch_are_refused(self):
        git(self.d, 'branch', '-f', 'job/W901', 'main')
        git(self.d, 'checkout', '-q', '-f', 'job/W901')
        self.commit({'lib/unmerged.py': 'z = 3\n'})
        self.back()
        git(self.d, 'update-ref', 'refs/remotes/origin/job/W901', 'job/W901')
        rep = '# W900 report: a test job\n\nEvidence: `harness/runs/20261104_gone` and job/W901.\n'
        res = self.w27_job([('R1', {'jobs/W900/review.md': '# Review\n\n' + self.w27_round(1, 'merge')})], report=rep)
        self.assertRefused(res, 'harness/runs/20261104_gone', 'exists in neither', JUDGED)
        self.assertIn('policy: warning: jobs/W900/report.md cites job/W901: evidence on an unmerged branch', res[1])

    def test_w27_warnings_print_before_the_verdict_and_keep_the_exit_code(self):
        rep = '# W900 report: a test job\n\nBuilt on commit `0badc0ffee1`.\n'
        rc, out, err = self.w27_job([('R1', {'jobs/W900/review.md': '# Review\n\n' + self.w27_round(1, 'merge')})], report=rep)
        self.assertEqual(rc, 0, out + err)
        lines = out.splitlines()
        warn = [i for i, l in enumerate(lines) if l.startswith('policy: warning: ') and '0badc0ffee1' in l]
        verdict = [i for i, l in enumerate(lines) if l.startswith('policy: job/W900: ok')]
        self.assertTrue(warn and verdict and warn[0] < verdict[0], out)

    def test_bypass_1_a_bootstrap_entry_on_the_head_exempts_nothing(self):
        self.branch('foo', {'wsc.toml': self.toml().replace('[policy]\n', '[policy]\nbootstrap = ["foo"]\n'), 'warscape/extra.py': 'X = 1\n'})
        for res in (self.ci('foo'), self.local('foo')):
            self.assertRefused(res, 'branch "foo" is not job/W<n>', JUDGED)
            self.assertIn('wsc.toml', self.note(res[1]))

    def test_bypass_2_an_empty_session_trailer_on_the_head_keeps_the_own_review_rule(self):
        git(self.d, 'checkout', '-q', '-f', '-B', 'job/W900', 'main')
        self.commit({'jobs/W900/report.md': '# W900 report: a test job\n'}, trailer='S1')
        row = {'id': 'W900', 'title': 'A test job', 'status': 'done', 'brief': 'jobs/W900/brief.md', 'report': 'jobs/W900/report.md',
               'review': 'jobs/W900/review.md'}
        self.commit({'jobs/W900/review.md': '## Round 1 (2026-11-04, branch job/W900 at abc1234)\n\n**Verdict: merge.**\n',
                     'registries/jobs/W900.json': json.dumps(row, indent=2) + '\n',
                     'wsc.toml': self.toml().replace('[policy]\n', '[policy]\nsession_trailer = ""\n')}, trailer='S1')
        self.back()
        for res in (self.ci('job/W900'), self.local('job/W900')):
            self.assertRefused(res, 'a session that also wrote the report (S1)', JUDGED)

    def test_bypass_3_the_heads_own_check_returning_nothing_is_never_run(self):
        evil = self.text('warscape/policy.py') + '\n\ndef check(*a, **k):\n    return []\n'
        self.branch('plan/evil', {'warscape/policy.py': evil, 'lib/code.py': 'x = 1\n'})
        for res in (self.ci('plan/evil'), self.local('plan/evil')):
            self.assertRefused(res, 'a plan/ branch may only touch', JUDGED)
            self.assertIn('warscape/policy.py', self.note(res[1]))

    def test_bypass_4_an_empty_decisions_key_on_the_head_keeps_the_file_append_only(self):
        dec = self.text('docs/DECISIONS.md').replace('| C1 | 2026-10-28 |', '| C1 | 2025-10-28 |', 1)
        self.branch('meta/dec', {'wsc.toml': self.toml().replace('decisions = "docs/DECISIONS.md"', 'decisions = ""'), 'docs/DECISIONS.md': dec})
        for res in (self.ci('meta/dec'), self.local('meta/dec')):
            self.assertRefused(res, 'docs/DECISIONS.md is append only: rows C1 were changed', JUDGED)

    def test_a_release_branch_is_judged_by_the_bases_rules(self):
        """W29 (C27): release/vX.Y.Z may change only VERSION, one step above the base's; a head that widens its own kind changes nothing."""
        base = self.text('VERSION').strip()
        a, b, _ = map(int, base.split('.'))
        nxt = f'{a}.{b + 1}.0'
        self.branch(f'release/v{nxt}', {'VERSION': nxt + '\n'})
        for res in (self.ci(f'release/v{nxt}'), self.local(f'release/v{nxt}')):
            self.assertEqual(res[0], 0, res)
        evil = self.text('warscape/policy.py').replace("if extra or not changed:", "if False:")
        self.branch(f'release/v{a}.{b + 2}.0', {'VERSION': f'{a}.{b + 2}.0\n', 'warscape/policy.py': evil})
        for res in (self.ci(f'release/v{a}.{b + 2}.0'), self.local(f'release/v{a}.{b + 2}.0')):
            self.assertRefused(res, 'a release branch may change only VERSION; it changes warscape/policy.py', JUDGED)
            self.assertIn('one patch, minor or major step', res[2])

    def test_a_head_verb_module_that_patches_check_at_import_changes_nothing(self):
        mod = ('import warscape.policy as P\nP.check = lambda *a, **k: []\nNAME = "evil"\nHELP = "x"\n\n\n'
               'def add_arguments(p):\n    pass\n\n\ndef run(args, ctx):\n    return 0\n')
        self.branch('meta/verbs', {'wsc.toml': self.toml() + '\n[cli]\nverb_dirs = ["evil"]\n', 'evil/patch.py': mod})
        for res in (self.ci('meta/verbs'), self.local('meta/verbs')):
            self.assertRefused(res, 'a meta/ branch may only touch repo infrastructure; it also changes: evil/patch.py', JUDGED)

    def test_a_meta_head_that_narrows_or_widens_its_own_globs_is_judged_by_the_bases(self):
        meta = lambda globs: re.sub(r'^meta = \[.*?\]', 'meta = ' + globs, self.toml(), count=1, flags=re.M | re.S)
        self.branch('meta/narrow', {'wsc.toml': meta('["wsc.toml"]'), 'docs/narrow.md': 'n\n'})
        rc, out, err = self.local('meta/narrow')
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.note(out), "policy: note: this branch changes wsc.toml: they judge pull requests after this one merges; "
                                         "this one was judged with origin/main's")
        self.branch('meta/widen', {'wsc.toml': meta('["warscape/**", "wsc.toml"]'), 'warscape/wide.py': 'X = 1\n'})
        res = self.local('meta/widen')
        self.assertRefused(res, 'it also changes: warscape/wide.py')
        self.assertIn('this branch changes warscape/wide.py, wsc.toml:', self.note(res[1]))

    def test_a_rename_counts_as_a_delete_and_an_add(self):
        """Found while building W23: `git diff --name-only` names only the new path of a rename (diff.renames, on by default), so a plan/ branch
        could move code into docs/ and pass. The judge diffs with --no-renames -z: the same shas give the same paths whatever the git config."""
        git(self.d, 'checkout', '-q', '-f', '-B', 'plan/move', 'main')
        git(self.d, 'mv', 'warscape/jobq.py', 'docs/jobq.py')
        git(self.d, 'commit', '-q', '-m', 'move')
        self.back()
        self.assertRefused(self.local('plan/move'), 'it also changes: warscape/jobq.py', JUDGED)

    def test_the_head_checkout_and_the_base_checkout_with_head_print_the_same(self):
        self.branch('plan/same', {'docs/same.md': 's\n', 'lib/same.py': 'x = 1\n'})
        a = self.local('plan/same')
        b = run([WSC, '--root', self.d, 'policy', '--branch', 'plan/same', '--base', 'origin/main', '--head', 'plan/same'], self.d)
        self.assertEqual(a, b)
        self.assertRefused(a, 'a plan/ branch may only touch', JUDGED + self.sha('main')[:12])

    def test_a_base_without_judge_api_is_judged_by_this_checkout_with_a_note(self):
        old = re.sub(r'^JUDGE_API = \d+\n', '', self.text('warscape/policy.py'), flags=re.M) + '\n# a core from before W23\n'
        self.branch('old-main', {'warscape/policy.py': old})
        self.branch('plan/old', {'docs/old.md': 'o\n'}, start='old-main')
        rc, out, err = self.policy('plan/old', 'old-main')
        self.assertEqual(rc, 0, out + err)
        self.assertIn(f"policy: note: the base's core predates base-judged policy (no JUDGE_API at {self.sha('old-main')[:12]}): "
                      "judged with this checkout's rules, as before W23", out)
        self.assertNotIn('judged with the rules of', out)

    def test_a_base_whose_check_raises_is_a_refusal_naming_the_exit_and_the_error(self):
        boom = self.text('warscape/policy.py') + '\n\ndef check(*a, **k):\n    raise RuntimeError("boom in the base")\n'
        self.branch('boom-main', {'warscape/policy.py': boom})
        self.branch('plan/boom', {'docs/boom.md': 'b\n'}, start='boom-main')
        rc, out, err = self.policy('plan/boom', 'boom-main')
        self.assertEqual(rc, 1, out + err)
        self.assertIn("the base's rules gave no verdict (exit 1): RuntimeError: boom in the base", err)
        self.assertIn('policy: plan/boom: REFUSED', out)

    def test_a_base_that_does_not_resolve_is_a_refusal_naming_the_fetch(self):
        rc, out, err = self.policy('main', 'origin/nosuch')
        self.assertEqual(rc, 1, out + err)
        self.assertIn('--base origin/nosuch does not resolve to a commit', err)
        self.assertIn('git fetch', err)

    def test_a_base_whose_wsc_toml_does_not_parse_is_a_refusal(self):
        good = self.toml()
        self.branch('badtoml-main', {'wsc.toml': good + '\n[broken\n'})
        self.branch('meta/t', {'wsc.toml': good, 'docs/t.md': 't\n'}, start='badtoml-main')
        rc, out, err = self.policy('meta/t', 'badtoml-main')
        self.assertEqual(rc, 1, out + err)
        self.assertIn(f"the base's wsc.toml (badtoml-main at {self.sha('badtoml-main')[:12]}) does not parse", err)

    def test_a_policy_module_runs_in_the_base_tree_and_reads_the_head_only_through_git(self):
        self.branch('peek-main', {'peek/peek.py': PEEK, 'peek/facts.py': FACTS, 'x': 'the base commit\n',
                                  'wsc.toml': self.toml() + '\n[gates]\ndirs = ["peek"]\n'})
        self.branch('meta/peek', {'docs/peek.md': 'head blob\n'}, start='peek-main')
        with tempfile.TemporaryDirectory() as t:
            enc = Path(t).resolve() / 'enclosing'   # the PC has a .git above every clone: the base tree's temp folder is inside one here
            (enc / 'tmp').mkdir(parents=True)
            (enc / 'x').write_text('ENCLOSING\n', encoding='utf-8')
            git(enc, 'init', '-q')
            git(enc, 'add', 'x')
            git(enc, 'commit', '-q', '-m', 'x')
            env = {**os.environ, 'TMP': str(enc / 'tmp'), 'TEMP': str(enc / 'tmp'), 'TMPDIR': str(enc / 'tmp')}
            rc, out, err = self.policy('meta/peek', 'peek-main', env=env)
            self.assertEqual(os.listdir(enc / 'tmp'), [], 'the base tree is deleted after the run')
        self.assertEqual(rc, 1, out + err)
        self.assertIn('peek: gate crashed: CalledProcessError', err)   # git found no repository at ctx.root and none above it
        self.assertNotIn('read a repository', err)
        for fact in ('branch=meta/peek', 'kind=meta', f"base={self.sha('peek-main')}", f"head={self.sha('meta/peek')}", 'base_ref=peek-main',
                     'repo_is_root=False', 'head_blob=head blob', 'root_has_x=True'):
            self.assertIn(f'policy: {fact}\n', err)


class GameMode(Branches, unittest.TestCase):
    game = True
    trailer = 'Agent-Session'

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.d = Path(cls._tmp.name) / 'game'
        fixture_game(cls.d)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_a_head_that_edits_or_drops_the_bases_gate_modules_is_still_judged_by_them(self):
        rules = self.text('gates/rules.py').replace("errs = [] if f['kind'] != 'job' else", 'errs = [] if True else')
        self.assertNotEqual(rules, self.text('gates/rules.py'))
        for name, files in (('job/F2', {'gates/rules.py': rules}), ('job/F2', {'wsc.toml': self.text('wsc.toml').replace('dirs = ["gates"]', 'dirs = []')})):
            self.branch(name, {**files, 'forbidden/x.txt': 'x\n'})
            for res in (self.ci(name), self.local(name)):
                self.assertRefused(res, 'fixture policy rule: forbidden/x.txt is in a forbidden folder', JUDGED)
                self.assertIn(next(iter(files)), self.note(res[1]))

    def test_a_head_that_repoints_the_core_gitlink_never_runs_that_commit(self):
        sentinel = Path(self._tmp.name) / 'sentinel.txt'
        core = self.d / 'core'
        git(self.d, 'checkout', '-q', '-f', '-B', 'plan/evil', 'main')
        git(core, 'checkout', '-q', '-B', 'evil')
        p = core / 'warscape' / 'policy.py'
        p.write_text(p.read_text(encoding='utf-8') + EVIL.format(sentinel=str(sentinel)), encoding='utf-8', newline='\n')
        git(core, 'commit', '-q', '-am', 'a core whose check passes anything')
        git(self.d, 'add', 'core')
        self.commit({'lib/code.py': 'x = 1\n'})
        self.back()
        for res in (self.ci('plan/evil'), self.local('plan/evil')):
            self.assertRefused(res, 'a plan/ branch may only touch', JUDGED)
            self.assertIn('policy: note: this branch changes core:', res[1])
            self.assertFalse(sentinel.exists(), 'the head pin ran')

    def test_a_base_pin_missing_from_the_submodule_is_a_refusal_naming_the_fetch(self):
        git(self.d, 'checkout', '-q', '-f', '-B', 'lost-pin', 'main')
        git(self.d, 'update-index', '--cacheinfo', f'160000,{LOST},core')
        git(self.d, 'commit', '-q', '-m', 'a pin the submodule lacks')
        self.back()
        self.branch('plan/lp', {'docs/lp.md': 'l\n'}, start='lost-pin')
        rc, out, err = self.policy('plan/lp', 'lost-pin')
        self.assertEqual(rc, 1, out + err)
        self.assertIn(f'git -C core fetch origin {LOST}', err)

    def test_a_base_with_no_core_gitlink_is_a_refusal(self):
        git(self.d, 'checkout', '-q', '-f', '-B', 'no-link', 'main')
        git(self.d, 'rm', '-q', '--cached', 'core')
        git(self.d, 'commit', '-q', '-m', 'no gitlink')
        self.back()
        self.branch('plan/nl', {'docs/nl.md': 'n\n'}, start='no-link')
        rc, out, err = self.policy('plan/nl', 'no-link')
        self.assertEqual(rc, 1, out + err)
        self.assertIn('has no core gitlink at core', err)

    def test_the_base_tree_holds_the_pinned_core_the_config_the_gate_modules_and_the_legacy_file(self):
        self.branch('scope-main', {'gates/scope.py': SCOPE})
        self.branch('plan/scope', {'docs/scope.md': 's\n'}, start='scope-main')
        rc, out, err = self.policy('plan/scope', 'scope-main')
        self.assertEqual(rc, 1, out + err)
        self.assertIn('policy: top=core,gates,jobs,wsc.toml\n', err)
        self.assertIn('policy: legacy=True\n', err)
        self.assertIn(f"policy: judged with the rules of scope-main at {self.sha('scope-main')[:12]} (core ", out)


if __name__ == '__main__':
    unittest.main()
