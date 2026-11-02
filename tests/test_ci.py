"""Host tests for warscape/ci.py and ci_render.py (`wsc ci`): input sets and tree hashes on a throwaway git repo, the failure comment, the rendered workflows.

Moved from napoleon-remastered tests/test_changed_inputs.py, test_ci_notify.py and test_workflows.py (napoleon J62), with fixture input sets and hints
instead of the game's.
"""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from warscape import ci, ci_render  # noqa: E402
from warscape.repo import DEFAULTS  # noqa: E402

WF = r'^\.github/workflows/'
CFG = {**DEFAULTS['ci'],
       'inputs': {'native': WF + r'|^native/(?!runs/)|^core$|^registries/(sites|keys)\.jsonl$',
                  'host': WF + r'|^host/|^core$|^tests/test_(a|b)\.py$',
                  'web': WF + r'|^web/(?!runs/)|^tests/test_web\.py$'},
       'artifacts': {'native': 'native-build', 'web': 'web-build'},
       'hints': {'gates': 'branch bug first: `python3 core/wsc.py gates` runs the same checks locally',
                 'policy': 'branch bug: `python3 core/wsc.py policy --branch <branch> --base origin/main`',
                 'native~wine|smoke': 'CI-only test unless `build.sh --docker smoke` ran',
                 'native': 'branch bug first: `build.sh --docker all`',
                 'host': "rerun the case with `gh workflow run gates.yml --ref <branch> -f repeat=20`",
                 '*': 'see the failure notes'},
       'notice': 'A failed check leaves this pull request open; fix it on the branch and push.',
       'footer': 'Classes and their guards: `docs/CI_FAILURES.md`.'}
FILES = {
    '.github/workflows/gates.yml': 'name: gates\n',
    'native/adapter.cpp': 'int a;\n',
    'native/runs/2026-10-31_x/console.log': 'log\n',
    'host/watch.ps1': 'Write-Host 1\n',
    'web/main.cpp': 'int v;\n',
    'web/runs/r1.txt': 'run\n',
    'registries/sites.jsonl': '{}\n',
    'jobs/J54/report.md': '# J54\n',
    'jobs/J54/review.md': '# review\n',
}
GITLINK = '1111111111111111111111111111111111111111'


def git(cwd, *args):
    env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
    return subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *args],
                          cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


class TreeHash(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.sets = ci.input_sets(CFG)
        git(self.repo, 'init', '-q')
        for rel, text in FILES.items():
            self.write(rel, text)
        git(self.repo, 'add', '-A')
        git(self.repo, 'update-index', '--add', '--cacheinfo', f'160000,{GITLINK},core')
        git(self.repo, 'commit', '-q', '-m', 'base')

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode())

    def hashes(self, ref='HEAD', salt='1'):
        return ci.tree_hashes(ci.tree_entries(self.repo, ref), self.sets, salt)

    def commit_change(self, rel, text):
        before = self.hashes()
        self.write(rel, text)
        git(self.repo, 'add', '--', rel)   # never -A: the `core` gitlink has no checkout here and -A would stage its removal
        git(self.repo, 'commit', '-q', '-m', rel)
        return before, self.hashes()

    def test_hashes_are_full_sha256_and_differ_per_set(self):
        h = self.hashes()
        self.assertEqual(set(h), {'native', 'host', 'web'})
        self.assertTrue(all(len(v) == 64 for v in h.values()))
        self.assertEqual(len(set(h.values())), 3)   # the set's name is hashed: equal file lists still give distinct keys

    def test_report_review_and_run_evidence_commits_keep_every_hash(self):
        for rel in ('jobs/J54/review.md', 'jobs/J54/report.md', 'native/runs/2026-11-01_y/console.log', 'web/runs/r2.txt'):
            before, after = self.commit_change(rel, f'new {rel}\n')
            self.assertEqual(before, after, rel)

    def test_an_input_changes_only_its_own_hash(self):
        for rel, which in (('native/adapter.cpp', 'native'), ('registries/sites.jsonl', 'native'), ('host/watch.ps1', 'host'), ('web/main.cpp', 'web')):
            before, after = self.commit_change(rel, f'changed {rel}\n')
            self.assertEqual({k for k in before if before[k] != after[k]}, {which}, rel)

    def test_workflow_change_changes_all_sets(self):
        before, after = self.commit_change('.github/workflows/gates.yml', 'name: gates\non: push\n')
        self.assertTrue(all(before[k] != after[k] for k in before))

    def test_core_pin_changes_the_sets_that_list_it(self):
        before = self.hashes()
        git(self.repo, 'update-index', '--cacheinfo', f'160000,{"2" * 40},core')
        git(self.repo, 'commit', '-q', '-m', 'bump core')
        self.assertEqual({k for k in before if before[k] != self.hashes()[k]}, {'native', 'host'})

    def test_mode_change_and_salt_change_the_hash(self):
        before = self.hashes()
        git(self.repo, 'update-index', '--chmod=+x', 'native/adapter.cpp')
        git(self.repo, 'commit', '-q', '-m', 'chmod')
        self.assertNotEqual(before['native'], self.hashes()['native'])
        a, b = self.hashes(salt='1'), self.hashes(salt='2')
        self.assertTrue(all(a[k] != b[k] for k in a))

    def test_unreadable_tree_gives_empty_hashes(self):
        self.assertIsNone(ci.tree_entries(self.repo, 'no-such-ref'))
        self.assertEqual(ci.tree_hashes(None, self.sets, '1'), {'native': '', 'host': '', 'web': ''})
        self.assertIsNone(ci.tree_entries(self.repo, 'HEAD', git=lambda *a: (127, [])))   # git cannot start

    def test_classify_and_an_unknown_base(self):
        self.assertEqual(ci.classify(['web/main.cpp'], self.sets), {'native': False, 'host': False, 'web': True})
        self.assertEqual(ci.classify(['.github/workflows/x.yml'], self.sets), {'native': True, 'host': True, 'web': True})
        self.assertTrue(all(ci.classify(None, self.sets).values()))
        self.assertIsNone(ci.changed_files(self.repo, 'deadbeef' * 5))
        self.assertIsNone(ci.changed_files(self.repo, ''))

    def test_the_verb_prints_the_sets_the_trees_and_the_salt(self):
        (self.repo / 'wsc.toml').write_text('[ci]\nsalt = "7"\n[ci.inputs]\nweb = \'^web/\'\n', encoding='utf-8')
        out = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(self.repo), 'ci', 'inputs', '--base', ''],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        keys = [line.split('=', 1)[0] for line in out.stdout.splitlines()]
        self.assertEqual(keys, ['web', 'web_tree', 'tree_salt'])
        self.assertIn('tree_salt=7', out.stdout)
        head = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(self.repo), 'ci', 'inputs', '--base', 'HEAD', '--head', 'HEAD'],
                              capture_output=True, text=True, timeout=60)
        self.assertIn('web=false', head.stdout)


JOBS = {'jobs': [
    {'name': 'changes', 'conclusion': 'success', 'steps': []},
    {'name': 'gates', 'conclusion': 'success', 'steps': []},
    {'name': 'native', 'conclusion': 'failure', 'steps': [{'name': 'Run build.sh all', 'conclusion': 'success'},
                                                          {'name': 'smoke test the DLL under wine', 'conclusion': 'failure'}]},
    {'name': 'host', 'conclusion': 'skipped', 'steps': []}]}


class FakeGh:
    def __init__(self, prs=({'number': 5},), seen=''):
        self.prs, self.seen, self.calls = list(prs), seen, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        a = argv[1:]
        if a[:2] == ['pr', 'list']:
            out = json.dumps(self.prs)
        elif a[0] == 'api' and a[1].endswith('/jobs'):
            out = json.dumps(JOBS)
        elif a[0] == 'api' and '/comments' in a[-3]:
            out = self.seen
        elif a[0] == 'api':
            out = json.dumps({'u': 'https://github.com/o/r/actions/runs/42'})
        else:
            out = ''
        return subprocess.CompletedProcess(argv, 0, out, '')

    def comments(self):
        return [c for c in self.calls if c[1:3] == ['pr', 'comment']]


class Notify(unittest.TestCase):
    def go(self, gh, dry=False, branch='job/J9'):
        out = io.StringIO()
        rc = ci.notify(CFG, 42, 1, branch, 'o/r', dry, run=gh, out=lambda s: out.write(s + '\n'))
        return rc, out.getvalue()

    def test_failed_names_each_failed_job_and_its_first_failed_step(self):
        self.assertEqual(ci.failed(JOBS['jobs']), [('native', 'smoke test the DLL under wine')])

    def test_comment_names_job_step_url_hint_notice_and_footer(self):
        gh = FakeGh()
        self.assertEqual(self.go(gh)[0], 0)
        [c] = gh.comments()
        body = c[c.index('--body') + 1]
        for s in ('`native`', 'smoke test the DLL under wine', 'https://github.com/o/r/actions/runs/42', 'CI-only test',
                  '<!-- ci_notify run 42 attempt 1 -->', 'A failed check leaves this pull request open', 'docs/CI_FAILURES.md'):
            self.assertIn(s, body)
        self.assertEqual(c[c.index('comment') + 1], '5')

    def test_once_per_run_attempt_and_no_pull_request_no_comment(self):
        gh = FakeGh(seen='earlier\n<!-- ci_notify run 42 attempt 1 -->\n')
        self.go(gh)
        self.assertEqual(gh.comments(), [])
        gh = FakeGh(prs=[])
        self.go(gh)
        self.assertEqual(len(gh.calls), 1)

    def test_a_dry_run_prints_and_posts_nothing(self):
        gh = FakeGh()
        rc, out = self.go(gh, dry=True)
        self.assertIn('would comment on PR #5', out)
        self.assertEqual(gh.comments(), [])

    def test_class_hints_pick_the_step_specific_hint_then_the_job_then_the_fallback(self):
        self.assertIn('wsc.py gates', ci.class_hint('gates', '', CFG))
        self.assertIn('--branch brief/J4 --base', ci.class_hint('policy', '', CFG, 'brief/J4'))
        self.assertIn('--docker smoke', ci.class_hint('native', 'smoke test', CFG))
        self.assertIn('--docker all', ci.class_hint('native', 'Run build.sh all', CFG))
        self.assertIn('repeat=20', ci.class_hint('host', 'host tests', CFG))
        self.assertEqual(ci.class_hint('viewer', 'x', CFG), 'see the failure notes')
        self.assertIn('no hint is configured', ci.class_hint('viewer', 'x', {**CFG, 'hints': {}}))


class Render(unittest.TestCase):
    """The templates: placeholders become the generic jobs; `if:` rules are evaluated by a small translation to Python (napoleon J57)."""
    CFGR = {**CFG, 'core': 'core', 'token_secret': 'CORE_TOKEN', 'policy_extra_steps': '      - run: echo extra'}

    def render(self, template, cfg=None):
        return ci_render.render_text(template, cfg or self.CFGR, 'ci/x.yml.in')

    @staticmethod
    def job_ifs(text):
        body = text[re.search(r'^jobs:\s*$', text, re.M).end():]
        out = {}
        parts = re.split(r'^  ([A-Za-z0-9_-]+):\s*$', body, flags=re.M)
        for name, block in zip(parts[1::2], parts[2::2]):
            m = re.search(r'^    if:\s*(.+?)\s*$', block, re.M)
            expr = m.group(1) if m else None
            if expr and expr.startswith('${{') and expr.endswith('}}'):
                expr = expr[3:-2].strip()
            out[name] = expr
        return out

    @staticmethod
    def effective(expr, event, changes_result, output):
        """GitHub's rule: an `if:` without a status function gets an implicit success(); `!cancelled()` replaces it."""
        py = (expr.replace('&&', ' and ').replace('||', ' or ').replace('!cancelled()', 'True').replace('!=', ' != ')
              .replace('github.event_name', repr(event)).replace('needs.changes.result', repr(changes_result)))
        py = re.sub(r'(?<![=!])!(?!=)', ' not ', py)
        py = re.sub(r"needs\.changes\.outputs\.\w+", repr(output), py)
        ok = eval(py, {})
        return bool(ok) if '!cancelled()' in expr else bool(ok) and changes_result == 'success'

    def test_a_failed_changes_job_never_skips_a_slow_job(self):
        text = self.render('jobs:\n  proxy:\n{{wsc if native}}\n  host:\n{{wsc if host dispatch}}\n')
        ifs = self.job_ifs(text)
        for out in ('true', 'false', ''):
            self.assertTrue(self.effective(ifs['proxy'], 'push', 'failure', out), out)
            self.assertTrue(self.effective(ifs['host'], 'push', 'failure', out), out)
        self.assertTrue(self.effective(ifs['proxy'], 'push', 'success', 'true'))
        self.assertFalse(self.effective(ifs['proxy'], 'push', 'success', 'false'))
        for result in ('success', 'failure'):
            self.assertFalse(self.effective(ifs['proxy'], 'workflow_dispatch', result, 'true'))
            self.assertTrue(self.effective(ifs['host'], 'workflow_dispatch', result, 'false'))

    def test_pass_markers_save_nothing_without_a_tree_hash(self):
        text = self.render('{{wsc pass_marker native}}\n{{wsc pass_marker host shell=bash}}\n')
        self.assertEqual(len(re.findall(r"needs\.changes\.outputs\.\w+_tree != ''", text)), 4)   # two steps per slow job
        self.assertIn('shell: bash', text)
        self.assertEqual(len(re.findall(r'enableCrossOsArchive: true', text)), 2)

    def test_changes_job_has_the_outputs_restore_steps_and_decisions_of_every_set(self):
        text = self.render('jobs:\n{{wsc changes}}\n')
        for k in ('native', 'host', 'web'):
            self.assertIn(f'{k}: ${{{{ steps.run.outputs.{k} }}}}', text)
            self.assertIn(f'path: .ci-pass/{k}', text)
        self.assertIn("decide native \"$NATIVE\" \"$NATIVE_HIT\" native-build", text)
        self.assertIn("decide host \"$HOST\" \"$HOST_HIT\" ''", text)
        self.assertIn('git submodule update --init --depth 1 core', text)
        self.assertIn('token: ${{ secrets.CORE_TOKEN }}', text)
        self.assertIn('python3 core/wsc.py ci inputs --base "$base"', text)
        plain = self.render('jobs:\n{{wsc changes}}\n', {**self.CFGR, 'core': '', 'token_secret': ''})
        self.assertNotIn('submodule', plain)
        self.assertNotIn('token:', plain)
        self.assertIn('python3 wsc.py ci inputs', plain)

    def test_policy_skips_drafts_and_notify_is_silent_for_ready_for_review(self):
        text = self.render('jobs:\n{{wsc policy}}\n{{wsc notify policy}}\n')
        ifs = self.job_ifs(text)
        self.assertIn('github.event.pull_request.draft == false', ifs['policy'])
        self.assertIn('failure()', ifs['notify'])
        self.assertIn("github.event.action != 'ready_for_review'", ifs['notify'])
        self.assertIn('echo extra', text)
        self.assertIn('policy --branch "${{ github.head_ref }}"', text)

    def test_notify_of_a_push_workflow_waits_for_the_named_jobs(self):
        text = self.render('jobs:\n{{wsc notify gates needs=changes,gates,proxy}}\n')
        self.assertIn('needs: [changes, gates, proxy]', text)
        self.assertIn("github.event_name == 'push' && github.ref != 'refs/heads/main'", text)

    def test_an_unknown_block_is_an_error_and_the_first_line_says_generated(self):
        with self.assertRaises(ValueError):
            self.render('{{wsc nope}}\n')
        self.assertTrue(self.render('x: 1\n').startswith('# Generated by `wsc ci render` from ci/x.yml.in'))

    def test_this_repos_committed_workflows_equal_their_render(self):
        from warscape.repo import Ctx
        self.assertEqual(ci_render.problems(Ctx.load(ROOT)), [])


if __name__ == '__main__':
    unittest.main()
