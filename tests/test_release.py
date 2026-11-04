"""W29 (C27): release tags by workflow. The plan on pure inputs, the never-move tag rule, the green check and the consumer check with an injected
runner, the token rule, the `release/` policy kind and the job/ VERSION rule, the semver rows and brief line, core_pin's release tag rule, the
adapter compile flags and the rendered workflow. A real throwaway repo runs `release plan` end to end (git objects only, never the working tree).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from _util import CORE, git

from warscape import gates, jobq, policy, release as R
from warscape.repo import DEFAULTS
from warscape.verbs import core as corev

ROW = lambda jid, st='done', sv=None, title='t': {'id': jid, 'status': st, 'title': title, **({'semver': sv} if sv else {})}


def rows(*rs):
    return {r['id']: r for r in rs}


class Plan(unittest.TestCase):
    SF = 39

    def plan(self, head, tag=None, version='0.30.0', last='v0.30.0', **kw):
        kw.setdefault('semver_from', self.SF)
        return R.plan(last, version, tag or {}, head, **kw)

    def test_level_table(self):
        for sv, want in (('patch', '0.30.1'), ('minor', '0.31.0'), ('none', None)):
            p = self.plan(rows(ROW('W40', sv=sv)))
            self.assertEqual((p['action'], p['version'] if want else None), ('release', want) if want else ('none', None), (sv, p))
        p = self.plan(rows(ROW('W40', sv='patch'), ROW('W41', sv='minor'), ROW('W42', sv='none')))
        self.assertEqual((p['action'], p['version'], p['level']), ('release', '0.31.0', 'minor'))
        p = self.plan(rows(ROW('W40')))   # missing semver counts as patch
        self.assertEqual(p['version'], '0.30.1')
        self.assertIn('no semver: patch', p['reasons'][0])

    def test_only_rows_that_became_done_since_the_tag_count(self):
        tag = rows(ROW('W40', sv='minor'), ROW('W41', st='queued', sv='patch'))
        p = self.plan(rows(ROW('W40', sv='minor'), ROW('W41', sv='patch'), ROW('W43', st='review', sv='major')), tag=tag)
        self.assertEqual(([r['id'] for r in p['rows']], p['version']), (['W41'], '0.30.1'))

    def test_major_while_zero_is_minor_with_a_note(self):
        p = self.plan(rows(ROW('W40', sv='major')))
        self.assertEqual((p['version'], p['level']), ('0.31.0', 'minor'))
        self.assertIn('major applied as minor', p['note'])
        self.assertEqual(self.plan(rows(ROW('W40', sv='major')), version='1.2.3', last='v1.2.3')['version'], '2.0.0')

    def test_floor_minor_from_schemas_and_the_verb_set(self):
        r = rows(ROW('W40', sv='patch'))
        self.assertEqual(self.plan(r, changed=[('M', 'schemas/jobs.schema.json')])['version'], '0.31.0')
        self.assertEqual(self.plan(r, changed=[('A', 'warscape/verbs/new.py')])['version'], '0.31.0')
        self.assertEqual(self.plan(r, changed=[('D', 'warscape/verbs/old.py')])['version'], '0.31.0')
        self.assertEqual(self.plan(r, changed=[('M', 'warscape/verbs/ci.py')])['version'], '0.30.1')   # an edit is not a verb set change
        self.assertEqual(self.plan(r, verbs_tag=('a', 'b'), verbs_head=('a', 'b', 'c'))['version'], '0.31.0')
        p = self.plan({}, changed=[('M', 'schemas/x.schema.json')])
        self.assertEqual((p['action'], p['version']), ('release', '0.31.0'))   # a schema change alone is a release

    def test_base_is_the_greater_of_tag_and_version(self):
        p = self.plan(rows(ROW('W40', sv='patch')), version='0.29.0')
        self.assertEqual(p['version'], '0.30.1')

    def test_legacy_hand_bump_is_tagged_as_it_is(self):
        p = self.plan(rows(ROW('W29', sv=None), ROW('W30')), version='0.31.0')
        self.assertEqual((p['action'], p['version']), ('tag', '0.31.0'))
        p = self.plan(rows(ROW('W29')), version='0.31.0', semver_from=0)   # rule off: every row is legacy
        self.assertEqual(p['action'], 'tag')

    def test_tag_after_the_release_merge_and_the_rederivation_refusal(self):
        r = rows(ROW('W40', sv='minor'))
        self.assertEqual(self.plan(r, version='0.31.0')['action'], 'tag')
        p = self.plan(r, version='0.32.0')
        self.assertEqual(p['action'], 'error')
        self.assertIn('is not 0.31.0', p['reasons'][-1])
        self.assertEqual(self.plan(rows(ROW('W40', sv='patch')), version='0.31.0')['action'], 'error')
        # a legacy hand bump below what new rows need gets one more step, above it is tagged
        mixed = rows(ROW('W30'), ROW('W40', sv='minor'))
        self.assertEqual((lambda p: (p['action'], p['version']))(self.plan(mixed, version='0.30.1')), ('release', '0.31.0'))
        self.assertEqual(self.plan(rows(ROW('W30'), ROW('W40', sv='patch')), version='0.31.0')['action'], 'tag')

    def test_nothing_to_release(self):
        p = self.plan({})
        self.assertEqual((p['action'], p['version']), ('none', '0.30.0'))
        self.assertEqual(self.plan(rows(ROW('W40', sv='none')))['action'], 'none')

    def test_manual_version(self):
        self.assertEqual(self.plan({}, forced='1.0.0')['action'], 'release')
        self.assertEqual(self.plan({}, version='1.0.0', forced='1.0.0')['action'], 'tag')
        self.assertEqual(self.plan({}, forced='0.30.0')['action'], 'error')   # not above the last tag
        self.assertEqual(self.plan({}, forced='0.33.0')['action'], 'error')   # not one step above VERSION
        with self.assertRaises(R.ReleaseError):
            self.plan({}, forced='1.0')

    def test_message_names_rows_note_and_consumers(self):
        p = self.plan(rows(ROW('W40', sv='major', title='Big')))
        m = R.tag_message(p, [{'name': 'napoleon', 'state': 'fails', 'detail': 'adapter.cpp:13: error: x'}])
        for want in ('warscape-core v0.31.0', 'W40 Big (major)', 'major applied as minor', 'napoleon: fails: adapter.cpp:13'):
            self.assertIn(want, m)


SHA, OTHER = 'a' * 40, 'b' * 40


class TagNeverMoves(unittest.TestCase):
    def test_remote_states(self):
        self.assertEqual(R.remote_tag_state('', 'v1.0.0', SHA), 'absent')
        ann = f'{"c" * 40}\trefs/tags/v1.0.0\n{SHA}\trefs/tags/v1.0.0^{{}}\n'
        self.assertEqual(R.remote_tag_state(ann, 'v1.0.0', SHA), 'same')
        self.assertEqual(R.remote_tag_state(ann, 'v1.0.0', OTHER), 'other')
        self.assertEqual(R.remote_tag_state(f'{SHA}\trefs/tags/v1.0.0\n', 'v1.0.0', SHA), 'lightweight')
        self.assertEqual(R.remote_tag_state(f'{OTHER}\trefs/tags/v1.0.0\n', 'v1.0.0', SHA), 'other')

    def fake(self, ls):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            out = ls if 'ls-remote' in cmd else ''
            return subprocess.CompletedProcess(cmd, 0, out, '')
        return run, calls

    def test_push_tag_no_op_or_refuse_or_push(self):
        p = R.plan('v0.30.0', '0.31.0', {}, rows(ROW('W30')), semver_from=39)
        run, calls = self.fake(f'{"c" * 40}\trefs/tags/v0.31.0\n{SHA}\trefs/tags/v0.31.0^{{}}\n')
        self.assertIn('nothing to do', R.push_tag('.', p, SHA, run=run))
        self.assertFalse(any('push' in c for c in calls))
        for ls in (f'{SHA}\trefs/tags/v0.31.0\n', f'{"c" * 40}\trefs/tags/v0.31.0\n{OTHER}\trefs/tags/v0.31.0^{{}}\n'):
            run, calls = self.fake(ls)
            with self.assertRaises(R.ReleaseError) as e:
                R.push_tag('.', p, SHA, run=run)
            self.assertIn('never moved', str(e.exception))
            self.assertFalse(any('tag' in c[1:3] and '-a' in c for c in calls))
        run, calls = self.fake('')
        R.push_tag('.', p, SHA, run=run)
        tag = next(c for c in calls if '-a' in c)
        self.assertEqual(tag[-1], SHA)
        self.assertIn(['git', 'push', 'origin', 'refs/tags/v0.31.0'], calls)

    def test_no_force_and_no_workflow_token_anywhere(self):
        texts = {p: (CORE / p).read_text(encoding='utf-8') for p in ('warscape/release.py', 'warscape/verbs/release.py', 'ci/release.yml.in',
                                                                     '.github/workflows/release.yml')}
        for p, t in texts.items():
            code = '\n'.join(l for l in t.splitlines() if not l.lstrip().startswith('#'))
            self.assertNotRegex(code, r"--force|'-f'|\"-f\"|\+refs/tags|push.*--delete|tag\s+-d|'-d'", p)
            if p.endswith('.yml') or p.endswith('.in'):
                self.assertNotRegex(code, r'GITHUB_TOKEN|github\.token', p)

    def test_the_token_check_comes_first_and_names_the_message(self):
        wf = (CORE / '.github' / 'workflows' / 'release.yml').read_text(encoding='utf-8')
        self.assertIn(R.TOKEN_MISSING, wf)
        self.assertLess(wf.index(R.TOKEN_MISSING), wf.index('actions/checkout'))
        self.assertIn('cancel-in-progress: false', wf)
        self.assertNotIn('continue-on-error', ' '.join(l for l in wf.splitlines() if not l.lstrip().startswith('#')))
        self.assertRegex(wf, r'create-github-app-token@[0-9a-f]{40}')
        with self.assertRaises(R.ReleaseError) as e:
            R.need_token({'GITHUB_TOKEN': 'x'})
        self.assertEqual(str(e.exception), R.TOKEN_MISSING)
        self.assertEqual(R.need_token({'RELEASE_TOKEN': 't'}), 't')


def gh_runner(answers):
    """A `run` that answers gh calls by the first matching substring of the joined command."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        line = ' '.join(cmd)
        for k, v in answers.items():
            if k in line:
                rc, out = v if isinstance(v, tuple) else (0, v)
                return subprocess.CompletedProcess(cmd, rc, out, '' if rc == 0 else out)
        return subprocess.CompletedProcess(cmd, 0, '', '')
    run.calls = calls
    return run


REQ = ['gates (ubuntu-latest)', 'policy', 'proxy']


def cr(name, status='completed', conclusion='success', i=1):
    return {'name': name, 'status': status, 'conclusion': conclusion, 'id': i, 'started_at': f'2026-11-04T00:00:0{i}Z'}


class Green(unittest.TestCase):
    def go(self, runs, tip=SHA):
        run = gh_runner({'commits/main': json.dumps({'sha': tip}), 'check-runs': json.dumps({'check_runs': runs})})
        return R.check_green(REQ, SHA, 'o/r', run=run)

    def test_states(self):
        self.assertEqual(self.go([cr('gates (ubuntu-latest)'), cr('proxy')])[0], 'green')        # policy ignored
        self.assertEqual(self.go([cr('gates (ubuntu-latest)'), cr('proxy', conclusion='skipped')])[0], 'green')
        s, lines = self.go([cr('gates (ubuntu-latest)'), cr('proxy', conclusion='failure')])
        self.assertEqual((s, lines), ('red', ['proxy: failure']))
        self.assertEqual(self.go([cr('gates (ubuntu-latest)')])[1], ['proxy: missing'])
        self.assertEqual(self.go([cr('gates (ubuntu-latest)'), cr('proxy', 'in_progress', None)])[1], ['proxy: in_progress'])
        # the latest run of a check decides (a rerun that passed)
        self.assertEqual(self.go([cr('gates (ubuntu-latest)'), cr('proxy', conclusion='failure', i=1), cr('proxy', i=2)])[0], 'green')
        s, lines = self.go([cr('gates (ubuntu-latest)'), cr('proxy')], tip=OTHER)
        self.assertEqual(s, 'stale')
        self.assertIn('newer run decides', lines[0])


class Consumers(unittest.TestCase):
    C = [{'name': 'napoleon', 'repo': 'o/napoleon', 'adapter': 'proxy/napoleon', 'ref': 'main'}]

    def go(self, answers, make_adapter=True):
        with tempfile.TemporaryDirectory() as td:
            if make_adapter:
                (Path(td) / 'napoleon' / 'proxy' / 'napoleon').mkdir(parents=True)
                (Path(td) / 'napoleon' / 'proxy' / 'napoleon' / 'adapter.cpp').write_text('x')
            return R.check_consumers(self.C, CORE, run=gh_runner(answers), workdir=td)

    def test_ok_fails_skipped(self):
        self.assertEqual(self.go({'adapter_syntax': (0, 'ok')})[0]['state'], 'ok')
        c = self.go({'adapter_syntax': (1, "x\nadapter.cpp:13:5: error: missing initializer for member 'wsp::GameAdapter::gesture'\nmore")})[0]
        self.assertEqual((c['state'], c['detail']), ('fails', "adapter.cpp:13:5: error: missing initializer for member 'wsp::GameAdapter::gesture'"))
        c = self.go({'repo clone': (1, 'GraphQL: Could not resolve to a Repository')})[0]
        self.assertEqual(c['state'], 'skipped')
        self.assertIn('unreachable', c['detail'])
        self.assertEqual(self.go({}, make_adapter=False)[0]['state'], 'skipped')
        self.assertEqual(self.go({'adapter_syntax': (2, 'adapter_syntax: no compiler')})[0]['state'], 'skipped')

    def test_issue_once_per_consumer_and_tag(self):
        c = {'name': 'napoleon', 'state': 'fails', 'detail': 'e', 'adapter': 'proxy/napoleon'}
        run = gh_runner({'issue list': '[]'})
        self.assertEqual(R.consumer_issue(c, 'v0.31.0', 'o/r', run=run), 'issue opened')
        body = next(x for x in run.calls if 'create' in x)[-1]
        self.assertTrue(body.startswith(R.CONSUMER_MARK.format(name='napoleon', tag='v0.31.0')))
        run = gh_runner({'issue list': json.dumps([{'number': 7, 'body': body}])})
        self.assertIn('#7 already open', R.consumer_issue(c, 'v0.31.0', 'o/r', run=run))
        self.assertFalse(any('create' in x for x in run.calls))


class ReleaseKind(unittest.TestCase):
    CFG = policy.settings({**DEFAULTS, 'jobs': {**DEFAULTS['jobs'], 'id_prefix': 'W', 'semver_from': 39}})

    def check(self, branch, changed, base='0.30.0\n', head='0.31.0\n', head_rows=None):
        return policy.check(branch, changed, {}, head_rows or {}, lambda p: base if p == 'VERSION' else None,
                            lambda p: head if p == 'VERSION' else None, cfg=self.CFG)

    def test_release_branch(self):
        self.assertEqual(self.check('release/v0.31.0', ['VERSION']), [])
        self.assertEqual(self.check('release/v0.30.1', ['VERSION'], head='0.30.1\n'), [])
        self.assertEqual(self.check('release/v1.0.0', ['VERSION'], head='1.0.0\n'), [])
        self.assertTrue(any('only VERSION' in e for e in self.check('release/v0.31.0', ['VERSION', 'warscape/x.py'])))
        self.assertTrue(any('only VERSION' in e for e in self.check('release/v0.31.0', [])))
        self.assertTrue(any('not 0.31.0' in e for e in self.check('release/v0.31.0', ['VERSION'], head='0.31.1\n')))
        self.assertTrue(any('one patch, minor or major step' in e for e in self.check('release/v0.32.0', ['VERSION'], head='0.32.0\n')))
        self.assertTrue(any('one patch, minor or major step' in e for e in self.check('release/v0.30.0', ['VERSION'], head='0.30.0\n')))
        self.assertTrue(any('not release/vX.Y.Z' in e for e in self.check('release/V0.31.0', ['VERSION'])))
        self.assertTrue(any('not release/vX.Y.Z' in e for e in self.check('release/whatever', ['VERSION'])))

    def test_job_branch_version_rule(self):
        new = self.check('job/W39', ['VERSION', 'x.py'])
        self.assertTrue(any('release workflow owns VERSION' in e for e in new), new)
        old = self.check('job/W38', ['VERSION', 'x.py'])
        self.assertFalse(any('owns VERSION' in e for e in old), old)
        self.assertFalse(any('owns VERSION' in e for e in self.check('job/W40', ['x.py'])))

    def test_the_refusal_text_names_the_kind(self):
        self.assertTrue(any('release/vX.Y.Z' in e for e in self.check('feature/x', ['x'])))
        self.assertIn('release/vX.Y.Z', policy.__doc__)


class Semver(unittest.TestCase):
    def setUp(self):
        self.old = jobq.S.semver_from
        jobq.S.semver_from = 39
        self.addCleanup(setattr, jobq.S, 'semver_from', self.old)

    BRIEF = ('# W40: t\n\nModel: Sonnet medium.\nSemver: minor\nBudget about 50 tool calls.\n\n## Kill criteria\n- x\n\n## Finish\n'
             '`wsc reg set jobs W40 status=review report=jobs/W40/report.md`\n')

    def row(self, jid='W40', **kw):
        return {'id': jid, 'description': 'd', 'title': 't', 'phase': 1, 'status': 'queued', 'model': 'sonnet', 'needs_pc': False,
                'depends_on': [], 'brief': f'jobs/{jid}/brief.md', **kw}

    def test_row_needs_semver_from_queued(self):
        e = jobq.problems([self.row()], lambda p: self.BRIEF if p == 'jobs/W40/brief.md' else None)
        self.assertTrue(any('needs semver=' in x for x in e), e)
        self.assertEqual(jobq.problems([self.row(semver='minor')], lambda p: self.BRIEF if p == 'jobs/W40/brief.md' else None), [])
        old = self.row('W38')
        self.assertEqual(jobq.problems([old], lambda p: self.BRIEF.replace('W40', 'W38') if p == 'jobs/W38/brief.md' else None), [])

    def test_brief_line(self):
        self.assertEqual(jobq.brief_problems('W40', self.row(semver='minor'), self.BRIEF), [])
        self.assertTrue(any('row says patch' in x for x in jobq.brief_problems('W40', self.row(semver='patch'), self.BRIEF)))
        no = self.BRIEF.replace('Semver: minor\n', '')
        self.assertTrue(any('no "Semver:' in x for x in jobq.brief_problems('W40', self.row(semver='minor'), no)))
        self.assertTrue(any('## VERSION' in x for x in jobq.brief_problems('W40', self.row(semver='minor'), self.BRIEF + '\n## VERSION\n0.31.0\n')))
        self.assertEqual(jobq.brief_problems('W38', self.row('W38'), no.replace('W40', 'W38')), [])

    def test_schema_takes_the_field(self):
        from warscape.registry import load_schema
        from warscape.schema import validate
        doc = load_schema('core:jobs', CORE)
        self.assertEqual(validate(self.row(semver='none'), doc), [])
        self.assertTrue(validate(self.row(semver='huge'), doc))


class CorePinTag(unittest.TestCase):
    def test_release_tag_problem(self):
        f = gates.release_tag_problem
        self.assertEqual(f('0.31.0', False, ['v0.30.0'], '', 999, '0.31.0', 120)[0], 'ok')        # not main
        self.assertEqual(f('0.31.0', True, [], '', 999, '0.31.0', 120)[0], 'ok')                  # tag-less checkout: VERSION only
        self.assertEqual(f('0.31.0', True, ['v0.31.0'], 'tag', 999, '0.31.0', 120)[0], 'ok')      # annotated
        self.assertEqual(f('0.30.0', True, ['v0.30.0'], 'commit', 999, '0.31.0', 120)[0], 'ok')   # lightweight below annotated_from
        self.assertEqual(f('0.31.0', True, ['v0.31.0'], 'commit', 999, '0.31.0', 120)[0], 'error')
        lv, why = f('0.31.0', True, ['v0.30.0'], '', 10, '0.31.0', 120)
        self.assertEqual((lv, 'release workflow pending' in why), ('warn', True))
        self.assertEqual(f('0.31.0', True, ['v0.30.0'], '', 121, '0.31.0', 120)[0], 'error')


class CoreBumpPure(unittest.TestCase):
    def test_set_core_version_keeps_comments(self):
        t = '# top\n[core]\n# the pin\nversion = "v0.1.0"   # a comment\n\n[ci]\ncore = "core"\n'
        self.assertEqual(corev.set_core_version(t, 'v0.31.0'), t.replace('v0.1.0', 'v0.31.0'))
        self.assertIn('\n[core]\nversion = "v0.31.0"\n', corev.set_core_version('[ci]\ncore = "core"\n', 'v0.31.0'))
        self.assertEqual(corev.set_core_version('[core]\n[ci]\n', 'v1.0.0'), '[core]\nversion = "v1.0.0"\n[ci]\n')

    def test_collisions(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / 'tools' / 'verbs'
            d.mkdir(parents=True)
            (d / 'discovery.py').write_text("NAME = 'discovery'\n")
            (d / 'mine.py').write_text('NAME = "mine"\n')
            (d / '_helper.py').write_text("NAME = 'jobs'\n")
            self.assertEqual(corev.collisions(td, ['tools/verbs'], ('jobs', 'discovery')), [('tools/verbs/discovery.py', 'discovery')])

    def test_core_verbs_read_as_text(self):
        self.assertEqual(R.core_verbs((CORE / 'warscape' / 'cli.py').read_text(encoding='utf-8'))[-2:], ('release', 'core'))


class AdapterSyntaxFlags(unittest.TestCase):
    def test_flags_are_the_dll_lines(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('adapter_syntax', CORE / 'proxy' / 'tools' / 'adapter_syntax.py')
        adapter_syntax = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter_syntax)
        fl = adapter_syntax.flags((CORE / 'proxy' / 'tools' / 'build.sh').read_text(encoding='utf-8'))
        for want in ('-std=c++17', '-Wall', '-Wextra', '-Wshadow', '-Werror', '-DRMLUI_STATIC_LIB'):
            self.assertIn(want, fl)
        self.assertFalse([f for f in fl if f.startswith(('-Wl,', '-DWSP_BUILD_ID')) or f in ('-s', '-shared')], fl)


class PlanOnARepo(unittest.TestCase):
    """`release plan` end to end on a throwaway repo: tag, rows and VERSION from git objects; an uncommitted VERSION changes nothing."""
    def test_plan(self):
        with tempfile.TemporaryDirectory() as td:
            r = Path(td)
            (r / 'registries' / 'jobs').mkdir(parents=True)
            (r / 'wsc.toml').write_text('[registries]\njobs = "core:jobs"\n[storage]\ndir = ["jobs"]\n[jobs]\nid_prefix = "W"\nsemver_from = 2\n'
                                        '[tests]\ndirs = []\n', encoding='utf-8')
            (r / 'VERSION').write_text('0.1.0\n')
            w = lambda jid, st, sv=None: (r / 'registries' / 'jobs' / f'{jid}.json').write_text(json.dumps(
                {'id': jid, 'description': 'd', 'title': f'title {jid}', 'phase': 1, 'status': st, 'model': 'sonnet', 'needs_pc': False,
                 'depends_on': [], **({'semver': sv} if sv else {})}))
            w('W1', 'done')
            w('W2', 'queued', 'minor')
            git(r, 'init', '-q', '-b', 'main')
            git(r, 'add', '-A')
            git(r, 'commit', '-q', '-m', 'one')
            git(r, 'tag', 'v0.1.0')
            w('W2', 'done', 'minor')
            git(r, 'commit', '-q', '-am', 'two')
            (r / 'VERSION').write_text('9.9.9\n')   # the working tree is never read
            out = subprocess.run([sys.executable, str(CORE / 'wsc.py'), '--root', str(r), 'release', 'plan', '--json'],
                                 capture_output=True, text=True, timeout=60)
            p = json.loads(out.stdout)
            self.assertEqual((p['action'], p['version'], [x['id'] for x in p['rows']]), ('release', '0.2.0', ['W2']), out.stderr)


if __name__ == '__main__':
    unittest.main()
