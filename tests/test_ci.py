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
        # W23: the head's names reach the script through env (pull_request_target), and --head names the commit judged
        self.assertIn('policy --branch "$HEAD_REF" --base "origin/$BASE_REF" --head "$HEAD_SHA"', text)
        self.assertLess(text.index('refs/pull/$PR/head'), text.index('echo extra'))   # the extra steps can read the fetched head

    @staticmethod
    def run_scripts(text):
        """Every `run:` script of a workflow: the line itself, plus the block lines of a `run: |`."""
        lines, out, i = text.splitlines(), [], 0
        while i < len(lines):
            m = re.match(r'^(\s*)(?:- )?run:\s*(.*)$', lines[i])
            i += 1
            if not m:
                continue
            out.append(m.group(2))
            if m.group(2) in ('|', '>'):
                while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > len(m.group(1))):
                    out.append(lines[i])
                    i += 1
        return out

    def test_w23_the_policy_job_runs_base_code_and_names_the_head_only_as_data(self):
        """pull_request_target gives the job the base's privileges: no step checks out, caches or runs the head, and the head's names reach
        scripts only through `env:` (a branch name may hold `$(...)`)."""
        for cfg in (self.CFGR, {**self.CFGR, 'core': '', 'token_secret': '', 'policy_extra_steps': ''}):
            text = self.render('jobs:\n{{wsc policy}}\n{{wsc notify policy}}\n', cfg)
            scripts = self.run_scripts(text)
            self.assertTrue(scripts)
            self.assertEqual([s for s in scripts if '${{' in s], [])
            self.assertIn('--branch "$HEAD_REF" --base "origin/$BASE_REF" --head "$HEAD_SHA"', text)
            for env in ('HEAD_REF: ${{ github.head_ref }}', 'BASE_REF: ${{ github.base_ref }}', 'HEAD_SHA: ${{ github.event.pull_request.head.sha }}',
                        'PR: ${{ github.event.pull_request.number }}'):
                self.assertIn(env, text)
            self.assertIn('git fetch --no-tags origin "+refs/pull/$PR/head:refs/remotes/pull/$PR/head"', text)
            self.assertNotRegex(text, r'(?m)^\s+ref:')   # every checkout is the default one: the base under pull_request_target
            self.assertNotRegex(text, r'git (checkout|switch|worktree)|actions/cache')

    def test_w23_the_render_guard_refuses_a_policy_template_without_pull_request_target(self):
        sys.path.insert(0, str(ROOT / 'tests'))
        from _util import MINIMAL_TOML, TempRepo
        repo = TempRepo(toml=MINIMAL_TOML + '[ci]\nworkflows = ["policy.yml"]\ncore = ""\n')
        self.addCleanup(repo.close)
        old = '# pull_request_target in a comment does not count\nname: policy\non:\n  pull_request:\n    types: [opened]\njobs:\n{{wsc policy}}\n'
        repo.write('ci/policy.yml.in', old)
        rc, out = repo.wsc('ci', 'render')
        self.assertEqual(rc, 1, out)
        self.assertIn('ci/policy.yml.in has {{wsc policy}} but no pull_request_target trigger', out)
        self.assertFalse((repo.root / '.github' / 'workflows' / 'policy.yml').exists())
        rc, out = repo.wsc('gates', '--only', 'ci_render')
        self.assertEqual(rc, 1, out)
        self.assertIn('no pull_request_target trigger', out)
        repo.write('ci/policy.yml.in', old.replace('on:\n', 'on:\n  pull_request_target:\n    types: [opened]\n'))
        rc, out = repo.wsc('ci', 'render')
        self.assertEqual(rc, 0, out)
        self.assertIn('ci/policy.yml.in also has a pull_request trigger', out)
        rc, out = repo.wsc('gates', '--only', 'ci_render')
        self.assertEqual(rc, 0, out)
        self.assertIn('WARN ci_render', out)
        repo.write('ci/policy.yml.in', old.replace('pull_request:', 'pull_request_target:'))
        rc, out = repo.wsc('ci', 'render')
        self.assertEqual(rc, 0, out)
        rc, out = repo.wsc('gates', '--only', 'ci_render')
        self.assertEqual(rc, 0, out)
        self.assertIn('ok   ci_render', out)

    def test_w23_this_repos_policy_workflow_is_pull_request_target_with_the_bootstrap_trigger(self):
        text = (ROOT / '.github' / 'workflows' / 'policy.yml').read_text(encoding='utf-8')
        on = text[text.index('\non:\n'):text.index('\npermissions:')]
        self.assertIn('\n  pull_request_target:\n    types: [opened, synchronize, reopened, ready_for_review]', on)
        self.assertIn("\n  pull_request:\n    types: [opened, synchronize, reopened, ready_for_review]\n    paths: ['jobs/W23/report.md']", on)
        self.assertEqual([s for s in self.run_scripts(text) if '${{' in s], [])
        fixture = (ROOT / 'tests' / 'fixture_game' / 'ci' / 'policy.yml.in').read_text(encoding='utf-8')
        self.assertIn('  pull_request_target:', fixture)
        self.assertNotRegex(fixture, r'(?m)^  pull_request:')   # the fixture switches with no bootstrap trigger

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

    # W21: a game renders the same blocks; a byte that changes fails its `ci_render` gate after a pin bump. Hashes taken on main before W21.
    # W23 changed three of them on purpose, in one commit: the `policy` block (pull_request_target: a base checkout, the head fetched as git
    # objects, head names through env, --head) and `notify policy` (the branch through env), and the fixture's template switched its trigger.
    # The fixture's gates.yml is unchanged.
    ALL_BLOCKS = ('jobs:\n{{wsc changes}}\n  a:\n{{wsc if native}}\n  b:\n{{wsc if host dispatch}}\n{{wsc pass_marker native}}\n'
                  '{{wsc pass_marker host shell=bash}}\n{{wsc policy}}\n{{wsc notify gates needs=changes,a,b}}\n{{wsc notify policy}}\n')
    GOLDEN = {'fixture_game gates.yml': '08df5d836f17dae07ffcb1e3a08ef17e152d82904397c44d679e9886d04855af',
              'fixture_game policy.yml': '9707260ef4246236ae4acfa6e25493bdac0345b9ac576288fab35400cf1bd3e9',
              'all blocks, a game': 'e7c81ab231768f735b0d4fdfd5f5b2720b043e5a7fee4ca854fc1ab28cd7b048',
              'all blocks, the core': '9426d6428a79efc0443175ab8151b8094d11239b23e3b8cbe79374a91abdd8ca'}

    def test_the_existing_blocks_render_byte_for_byte_as_before(self):
        import hashlib
        from warscape.repo import Ctx
        fx = ROOT / 'tests' / 'fixture_game'
        cfg = Ctx.load(fx).config['ci']
        got = {f'fixture_game {n}': ci_render.render_text((fx / 'ci' / f'{n}.in').read_text(encoding='utf-8'), cfg, f'ci/{n}.in')
               for n in ('gates.yml', 'policy.yml')}
        got['all blocks, a game'] = self.render(self.ALL_BLOCKS)
        got['all blocks, the core'] = self.render(self.ALL_BLOCKS, {**self.CFGR, 'core': '', 'token_secret': '', 'policy_extra_steps': ''})
        self.assertEqual({k: hashlib.sha256(v.encode()).hexdigest() for k, v in got.items()}, self.GOLDEN)

    def test_fetch_cache_keys_on_the_pins_and_never_fails_the_job(self):
        for core, prefix in (('core', 'core/'), ('', '')):
            text = self.render('    steps:\n{{wsc fetch_cache}}\n', {**self.CFGR, 'core': core, 'salt': '3'})
            steps = re.split(r'^      - ', text, flags=re.M)[1:]
            self.assertEqual(len(steps), 3, text)
            key, cache, pre = steps
            self.assertIn('id: fetch_key', key)
            self.assertIn(f'run: python3 {prefix}proxy/tools/netfetch.py ci-cache >> "$GITHUB_OUTPUT"', key)
            self.assertIn('uses: actions/cache@v5', cache)
            self.assertIn('continue-on-error: true', cache)
            self.assertIn('path: ${{ steps.fetch_key.outputs.paths }}', cache)
            self.assertIn('key: fetch-3-${{ steps.fetch_key.outputs.key }}', cache)
            self.assertIn(f'run: python3 {prefix}proxy/tools/netfetch.py prefetch', pre)
            self.assertNotIn('continue-on-error', key + pre)   # a failed prefetch fails the job: the fetchers' sha checks judge every byte


class CoreConfig(unittest.TestCase):
    """The core's own [ci] (W21): which slow job a path runs, and the checks main must require."""
    @classmethod
    def setUpClass(cls):
        from warscape.repo import Ctx
        cls.cfg = Ctx.load(ROOT).config['ci']
        cls.sets = ci.input_sets(cls.cfg)

    def test_input_sets(self):
        cases = {'docs/BACKLOG.md': set(), 'jobs/W21/report.md': set(), 'registries/jobs/W21.json': set(), 'README.md': set(),
                 'proxy/src/x.cpp': {'proxy'}, 'proxy/tools/build.sh': {'proxy', 'harness'}, 'proxy/tests/null_game/proxy/null/adapter.cpp': {'proxy', 'harness'},
                 'proxy/tests/host/t.cpp': {'proxy'}, 'harness/watcher.ps1': {'harness'}, 'tests/test_moved_tools.py': {'harness'},
                 'warscape/ci.py': {'harness'}, 'ci/gates.yml.in': {'proxy', 'harness'}, '.github/workflows/gates.yml': {'proxy', 'harness'},
                 'wsc.toml': {'proxy', 'harness'}}
        for path, want in cases.items():
            got = {k for k, v in ci.classify([path], self.sets).items() if v}
            self.assertEqual(got, want, path)

    def test_required_checks_and_no_artifacts(self):
        self.assertEqual(self.cfg['required_checks'], ['gates (ubuntu-latest)', 'gates (windows-latest)', 'policy', 'proxy', 'harness-windows'])
        self.assertEqual(self.cfg['artifacts'], {})
        self.assertEqual(DEFAULTS['ci']['required_checks'], [])


# ------------------------------------------------------------------ check-settings (W21, backlog B47): recorded `gh api` answers, 2026-11-03
def rule_checks(*names, strict=False):
    return {'type': 'required_status_checks', 'parameters': {'strict_required_status_checks_policy': strict, 'do_not_enforce_on_create': False,
            'required_status_checks': [{'context': n, 'integration_id': 15368} for n in names]}, 'ruleset_source_type': 'Repository', 'ruleset_id': 1}


def rule_pr(approvals):
    return {'type': 'pull_request', 'parameters': {'required_approving_review_count': approvals, 'dismiss_stale_reviews_on_push': False,
            'require_code_owner_review': False, 'require_last_push_approval': False, 'allowed_merge_methods': ['squash']}, 'ruleset_id': 1}


BASIC = [{'type': 'deletion', 'ruleset_id': 1}, {'type': 'non_fast_forward', 'ruleset_id': 1}]
NOT_PROTECTED = (1, '{"message":"Branch not protected","status":"404"}', 'gh: Branch not protected (HTTP 404)')
CORE_ANSWERS = {'repos/o/core': (0, json.dumps({'allow_auto_merge': False}), ''),
                'repos/o/core/rules/branches/main': (0, json.dumps(BASIC + [rule_checks('gates (ubuntu-latest)', 'gates (windows-latest)')]), ''),
                'repos/o/core/branches/main/protection': NOT_PROTECTED}
GAME_ANSWERS = {'repos/o/game': (0, json.dumps({'allow_auto_merge': True}), ''),
                'repos/o/game/rules/branches/main': (0, json.dumps(BASIC + [rule_pr(0), rule_checks('gates', 'policy', 'proxy', 'harness-windows')]), ''),
                'repos/o/game/branches/main/protection': NOT_PROTECTED}
CORE_WF = {'gates.yml': 'name: gates\non:\n  push:\njobs:\n  changes:\n    runs-on: x\n  gates:\n    strategy:\n      matrix:\n        os: [a, b]\n'
                        '    runs-on: x\n  proxy:\n    needs: changes\n  harness-windows:\n    needs: changes\n  notify:\n    needs: [gates]\n',
           'policy.yml': 'name: policy\njobs:\n  policy:\n    runs-on: x\n  notify:\n    needs: [policy]\n'}
GAME_WF = {'gates.yml': 'name: gates\njobs:\n  changes:\n    runs-on: x\n  gates:\n    runs-on: x\n  proxy:\n    runs-on: x\n  viewer:\n    runs-on: x\n'
                        '  harness-windows:\n    runs-on: x\n  notify:\n    runs-on: x\n',
           'policy.yml': CORE_WF['policy.yml']}
CORE_REQUIRED = ['gates (ubuntu-latest)', 'gates (windows-latest)', 'policy', 'proxy', 'harness-windows']


class FakeApi:
    def __init__(self, answers, repo='o/core'):
        self.answers, self.repo, self.calls = answers, repo, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        a = argv[1:]
        if a[:2] == ['repo', 'view']:
            return subprocess.CompletedProcess(argv, 0, json.dumps({'nameWithOwner': self.repo}), '')
        if a[0] == 'api' and a[-1] in self.answers:
            rc, out, err = self.answers[a[-1]]
            return subprocess.CompletedProcess(argv, rc, out, err)
        return subprocess.CompletedProcess(argv, 1, '', f'gh: Not Found (HTTP 404) {a}')


class CheckSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def go(self, answers, workflows, required=(), repo='', **kw):
        from warscape import ci_settings
        wf = self.root / '.github' / 'workflows'
        wf.mkdir(parents=True, exist_ok=True)
        for n, text in workflows.items():
            (wf / n).write_text(text, encoding='utf-8')
        cfg = {**DEFAULTS['ci'], 'workflows': list(workflows), 'required_checks': list(required)}
        lines = []
        gh = answers if callable(answers) else FakeApi(answers, kw.pop('default_repo', 'o/core'))
        rc = ci_settings.check(cfg, self.root, repo=repo, branch='main', run=gh, out=lines.append)
        self.gh = gh
        return rc, '\n'.join(lines)

    def problems(self, text):
        return [l for l in text.splitlines() if l.startswith('problem:')]

    def test_the_core_today_lacks_three_checks_and_auto_merge(self):
        rc, out = self.go(CORE_ANSWERS, CORE_WF, CORE_REQUIRED)
        self.assertEqual(rc, 1, out)
        probs = self.problems(out)
        self.assertEqual(len(probs), 4, out)
        for name in ('`policy`', '`proxy`', '`harness-windows`', 'allow_auto_merge'):
            self.assertTrue(any(name in p for p in probs), name)
        self.assertIn('no classic branch protection', out)
        self.assertIn('repos/o/core', ' '.join(' '.join(c) for c in self.gh.calls))   # the repo came from `gh repo view`
        self.assertTrue(all(c[1] in ('api', 'repo') for c in self.gh.calls))
        self.assertTrue(all('-X' not in c and '--method' not in c for c in self.gh.calls))   # read-only: GETs only

    def test_the_core_after_the_owner_fixes_it(self):
        answers = {**CORE_ANSWERS, 'repos/o/core': (0, json.dumps({'allow_auto_merge': True}), ''),
                   'repos/o/core/rules/branches/main': (0, json.dumps(BASIC + [rule_checks(*CORE_REQUIRED)]), '')}
        rc, out = self.go(answers, CORE_WF, CORE_REQUIRED)
        self.assertEqual((rc, self.problems(out)), (0, []), out)

    def test_the_game_explicit_only_notes_viewer(self):
        rc, out = self.go(GAME_ANSWERS, GAME_WF, ['gates', 'policy', 'proxy', 'harness-windows'], repo='o/game')
        self.assertEqual(rc, 0, out)
        notes = [l for l in out.splitlines() if l.startswith('note:')]
        self.assertTrue(any('`viewer`' in n for n in notes), out)
        self.assertFalse(any('`gates`' in n or '`proxy`' in n for n in notes), out)
        self.assertEqual(self.gh.calls[0][1], 'api')   # --repo given: no `gh repo view`

    def test_derived_expected_checks_and_a_matrix_job(self):
        rc, out = self.go(GAME_ANSWERS, GAME_WF, repo='o/game')   # no required_checks: every job but changes and notify is expected
        self.assertEqual(rc, 1, out)
        self.assertEqual(len(self.problems(out)), 1)
        self.assertIn('`viewer`', self.problems(out)[0])
        rc, out = self.go(CORE_ANSWERS, CORE_WF)
        self.assertIn('matrix job gates: list its checks in [ci] required_checks', out)
        self.assertFalse(any('`gates' in p for p in self.problems(out)), out)

    def test_a_renamed_required_check_and_approving_reviews_and_strict(self):
        answers = {**GAME_ANSWERS, 'repos/o/game/rules/branches/main': (0, json.dumps(
            BASIC + [rule_pr(1), rule_checks('gates', 'policy', 'proxy', 'harness', strict=True)]), '')}
        rc, out = self.go(answers, GAME_WF, ['gates', 'policy', 'proxy', 'harness-windows'], repo='o/game')
        self.assertEqual(rc, 1, out)
        probs = '\n'.join(self.problems(out))
        self.assertIn('`harness` (ruleset) is produced by no workflow job', probs)
        self.assertIn('`harness-windows`', probs)
        self.assertIn('1 approving review', probs)
        self.assertIn('strict', '\n'.join(l for l in out.splitlines() if l.startswith('note:')))

    def test_classic_protection_403_is_said_and_not_fatal_and_classic_checks_count(self):
        answers = {**CORE_ANSWERS, 'repos/o/core/branches/main/protection': (1, '{"message":"Must have admin rights"}', 'gh: Must have admin rights to Repository. (HTTP 403)')}
        rc, out = self.go(answers, CORE_WF, CORE_REQUIRED)
        self.assertEqual(rc, 1, out)
        self.assertIn('HTTP 403', out)
        self.assertEqual(len(self.problems(out)), 4, out)
        classic = {'required_status_checks': {'strict': False, 'contexts': ['policy'], 'checks': [{'context': 'proxy', 'app_id': 1}]},
                   'required_pull_request_reviews': {'required_approving_review_count': 2}}
        answers = {**CORE_ANSWERS, 'repos/o/core/branches/main/protection': (0, json.dumps(classic), '')}
        rc, out = self.go(answers, CORE_WF, CORE_REQUIRED)
        probs = '\n'.join(self.problems(out))
        self.assertNotIn('`policy`', probs)
        self.assertNotIn('`proxy`', probs)
        self.assertIn('`harness-windows`', probs)
        self.assertIn('2 approving review', probs)

    def test_cannot_read_exits_2(self):
        def no_gh(argv, **kw):
            raise FileNotFoundError('gh')
        rc, out = self.go(no_gh, CORE_WF, CORE_REQUIRED)
        self.assertEqual(rc, 2)
        self.assertIn('gh', out)

        def logged_out(argv, **kw):
            return subprocess.CompletedProcess(argv, 4, '', 'To get started with GitHub CLI, please run:  gh auth login')
        rc, out = self.go(logged_out, CORE_WF, CORE_REQUIRED)
        self.assertEqual(rc, 2)
        self.assertIn('gh auth login', out)
        rc, out = self.go({}, CORE_WF, CORE_REQUIRED, repo='o/nope')
        self.assertEqual(rc, 2, out)

    def test_the_verb_has_the_action(self):
        out = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), 'ci', '--help'], capture_output=True, text=True, timeout=60)
        self.assertIn('check-settings', out.stdout)


if __name__ == '__main__':
    unittest.main()
