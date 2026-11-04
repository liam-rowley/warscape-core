"""Game gate modules (warscape/gatemods.py, core W13, B1 B46): a game's own checks as modules with NAME and run(ctx) -> Result, run at the
stages they list (`gates`, `jobs`, `policy`, `view`). Throwaway repos driven through the real CLI, in-process."""
import json
import subprocess
import textwrap
import unittest

from _util import TempRepo

from warscape import gatemods, jobq, policy
from warscape.repo import DEFAULTS, Ctx

TOML = '''
registries_dir = "registries"
[registries]
tools = "core:tools"
[tests]
dirs = []
[gates]
dirs = ["checks"]
'''

GOOD = '''
from warscape.gates import Result
NAME = 'house_rule'

def run(ctx):
    bad = [p for p in ctx.files() if p.endswith('.bad')]
    return Result(NAME, 'error' if bad else 'ok', f'{len(bad)} bad files' if bad else 'no bad files', bad)
'''


def mod(body):
    return textwrap.dedent(body).lstrip()


class GatesStage(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo({'checks/house.py': mod(GOOD)}, toml=TOML)
        self.addCleanup(self.repo.close)

    def test_a_gates_module_is_its_own_line_and_fails_the_run_on_error(self):
        rc, out = self.repo.wsc('gates', '--only', 'json,house_rule')
        self.assertEqual(rc, 0, out)
        self.assertIn('ok   house_rule', out)
        self.assertIn('no bad files', out)
        self.assertLess(out.index('json'), out.index('house_rule'))   # after the core gates
        self.repo.write('x.bad', 'x')
        rc, out = self.repo.wsc('gates', '--only', 'json,house_rule')
        self.assertEqual(rc, 1, out)
        self.assertIn('FAIL house_rule', out)
        self.assertIn('x.bad', out)

    def test_in_the_fast_set_unless_fast_is_false(self):
        rc, out = self.repo.wsc('gates', '--fast')
        self.assertIn('house_rule', out)
        self.repo.write('checks/house.py', mod(GOOD) + 'FAST = False\n')
        rc, out = self.repo.wsc('gates', '--fast')
        self.assertNotIn('house_rule', out)
        rc, out = self.repo.wsc('gates', '--only', 'house_rule')
        self.assertIn('house_rule', out)

    def test_skip_and_only_accept_game_gate_names(self):
        self.repo.write('docs/DECISIONS.md', '| D1 | 2026-11-04 | o | skip the house rule | yes |\n')
        self.repo.write('wsc.toml', TOML + 'skip = ["house_rule:D1"]\n[policy]\ndecisions = "docs/DECISIONS.md"\n')
        rc, out = self.repo.wsc('gates', '--fast')
        self.assertNotIn('no bad files', out)
        self.assertIn('skipped house_rule: D1', out)
        rc, out = self.repo.wsc('gates', '--only', 'nope')
        self.assertEqual(rc, 2)
        self.assertIn('unknown gate(s) nope', out)
        self.assertIn('house_rule', out)   # the error lists the game gates too

    def test_a_crashing_run_is_an_error(self):
        self.repo.write('checks/boom.py', "NAME = 'boom'\n\ndef run(ctx):\n    raise KeyError('x')\n")
        rc, out = self.repo.wsc('gates', '--only', 'boom')
        self.assertEqual(rc, 1, out)
        self.assertIn('FAIL boom', out)
        self.assertIn('gate crashed: KeyError', out)

    def test_underscore_files_are_not_modules_and_folder_then_name_order_holds(self):
        self.repo.write('checks/_helper.py', 'raise SystemExit("never loaded")\n')
        self.repo.write('checks/a_first.py', "from warscape.gates import Result\nNAME = 'zed'\n\ndef run(ctx):\n    return Result(NAME, 'ok', 'z')\n")
        mods = gatemods.load(Ctx.load(self.repo.root))
        self.assertEqual([m.name for m in mods], ['zed', 'house_rule'])   # file-name order: a_first.py, house.py


class SkipIsNeverSilent(unittest.TestCase):
    """W28: `[gates] skip` entries are `"<gate>:<decision id>"`; each skipped gate is a warn line naming the decision, and the id must be a row
    of the `[policy] decisions` file."""
    SKIP_TOML = TOML + 'fast = ["json"]\nskip = [{}]\n[policy]\ndecisions = "docs/DECISIONS.md"\n'

    def gates(self, skip, *args):
        repo = TempRepo({'checks/house.py': mod(GOOD), 'docs/DECISIONS.md': '| D7 | 2026-11-04 | o | the house rule is off for now | yes |\n'},
                        toml=self.SKIP_TOML.format(skip))
        self.addCleanup(repo.close)
        return repo.wsc('gates', *args)

    def test_a_skip_with_a_decision_id_is_a_warn_line_and_the_run_passes(self):
        rc, out = self.gates('"house_rule:D7"', '--fast')
        self.assertEqual(rc, 0, out)
        self.assertIn('WARN house_rule', out)
        self.assertIn('skipped house_rule: D7', out)
        self.assertNotIn('no bad files', out)

    def test_a_bare_name_is_a_config_error_that_names_the_fix(self):
        rc, out = self.gates('"house_rule"', '--fast')
        self.assertEqual(rc, 2, out)
        self.assertIn('"house_rule" has no decision id: write "house_rule:<decision id>"', out)

    def test_an_unknown_decision_id_is_an_error(self):
        rc, out = self.gates('"house_rule:D99"', '--fast')
        self.assertEqual(rc, 2, out)
        self.assertIn('D99 is not a row of docs/DECISIONS.md', out)

    def test_only_still_runs_a_skipped_gate(self):
        rc, out = self.gates('"house_rule:D7"', '--only', 'house_rule')
        self.assertEqual(rc, 0, out)
        self.assertIn('ok   house_rule', out)
        self.assertNotIn('skipped house_rule', out)


class LoadErrors(unittest.TestCase):
    def check(self, files, want, toml=TOML):
        repo = TempRepo(files, toml=toml)
        self.addCleanup(repo.close)
        rc, out = repo.wsc('gates', '--only', 'json')
        self.assertEqual(rc, 2, out)
        self.assertIn(want, out)
        return out

    def test_a_missing_folder(self):
        self.check({}, '[gates] dirs: checks does not exist')

    def test_a_name_clash_with_a_core_gate_and_with_another_module(self):
        self.check({'checks/a.py': "NAME = 'tools'\n\ndef run(ctx):\n    pass\n"}, "NAME 'tools' is a core gate")
        self.check({'checks/a.py': mod(GOOD), 'checks/b.py': mod(GOOD)}, "NAME 'house_rule' is already checks/a.py's")

    def test_a_bad_name(self):
        self.check({'checks/a.py': "NAME = 'House-Rule'\n\ndef run(ctx):\n    pass\n"}, "NAME 'House-Rule' must match [a-z][a-z0-9_]*")

    def test_an_unknown_stage(self):
        self.check({'checks/a.py': mod(GOOD) + "STAGES = ('gates', 'polcy')\n"}, "unknown stage 'polcy'")

    def test_a_missing_run_or_name(self):
        self.check({'checks/a.py': "NAME = 'x'\n"}, 'checks/a.py: a gate module needs run')
        self.check({'checks/a.py': "def run(ctx):\n    pass\n"}, 'checks/a.py: a gate module needs NAME')

    def test_a_module_that_still_defines_an_old_hook_name(self):
        out = self.check({'checks/a.py': mod(GOOD) + '\ndef summary(ctx, rows, read):\n    return ""\n'}, 'checks/a.py defines summary')
        self.assertIn('W13', out)
        self.assertIn('docs/CONSUMING.md', out)

    def test_the_removed_jobs_hooks_key_names_its_replacement(self):
        out = self.check({}, '[jobs] hooks was replaced by [gates] dirs', toml=TOML.replace('dirs = ["checks"]', '') + '[jobs]\nhooks = ["x.py"]\n')
        self.assertIn('docs/CONSUMING.md "Game gates"', out)
        self.assertNotIn('unknown key', out)


JOBS_TOML = '''
registries_dir = "registries"
[registries]
jobs = "core:jobs"
[storage]
dir = ["jobs"]
[views]
commit = false
[tests]
dirs = []
[gates]
dirs = ["checks"]
[jobs]
legacy = "jobs/legacy.json"
'''

BRIEF = '''# {jid}: thing

Model: Sonnet. Budget about 40 tool calls; at the cap, stop. BAD

## Kill criteria
- It breaks twice: stop.

## Finish
Write `jobs/{jid}/report.md`. Then `wsc reg set jobs {jid} status=review report=jobs/{jid}/report.md`.
'''

JOBS_MOD = '''
from warscape.gates import Result
NAME = 'brief_rule'
STAGES = ('jobs',)

def run(ctx):
    assert ctx.stage == 'jobs'
    seen = list(ctx.briefs())
    errs = [f'{jid}: brief: says BAD' for jid, row, text in seen if 'BAD' in text and row['id'] == jid]
    n = sum(1 for r in ctx.rows if ctx.read('jobs/' + r['id'] + '/brief.md') is not None)
    return Result(NAME, 'error' if errs else 'ok', f'{len(seen)} of {n} briefs checked', errs)
'''


def job_row(jid):
    return {'id': jid, 'description': 'd', 'title': 't', 'phase': 1, 'status': 'queued', 'model': 'sonnet', 'needs_pc': False,
            'depends_on': [], 'brief': f'jobs/{jid}/brief.md'}


class JobsStage(unittest.TestCase):
    def setUp(self):
        files = {'checks/brief_rule.py': mod(JOBS_MOD), 'jobs/legacy.json': '{"round_rules": [], "brief_hooks": ["J1"]}\n'}
        for j in ('J1', 'J2'):
            files[f'jobs/{j}/brief.md'] = BRIEF.format(jid=j)
            files[f'registries/jobs/{j}.json'] = json.dumps(job_row(j), indent=2) + '\n'
        self.repo = TempRepo(files, toml=JOBS_TOML)
        self.addCleanup(self.repo.close)
        self.addCleanup(jobq.configure_from, DEFAULTS['jobs'])

    def test_briefs_skips_the_legacy_ids(self):
        ctx = Ctx.load(self.repo.root)
        jobq.configure(ctx)
        rows = jobq.main_rows(ctx)
        self.assertEqual([j for j, _, _ in jobq.briefs(rows, lambda p: self.repo.read(p) if (self.repo.root / p).is_file() else None)], ['J2'])

    def test_an_error_fails_jobs_check_and_the_jobs_gate_and_the_summary_lands_on_the_line(self):
        rc, out = self.repo.wsc('jobs', 'check')
        self.assertEqual(rc, 1, out)
        self.assertIn('jobs: J2: brief: says BAD', out)
        self.assertNotIn('J1: brief: says BAD', out)
        self.assertIn('jobs check: 2 rows, 1 problems, 1 of 2 briefs checked', out)
        rc, out = self.repo.wsc('gates', '--only', 'jobs')
        self.assertEqual(rc, 1, out)
        self.assertIn('FAIL jobs', out)
        self.assertIn('J2: brief: says BAD', out)
        self.assertNotIn('brief_rule', out)   # a jobs-stage module is not a gates line of its own

    def test_a_warn_prints_but_does_not_fail(self):
        self.repo.write('checks/brief_rule.py', mod(JOBS_MOD).replace("'error' if errs else 'ok'", "'warn' if errs else 'ok'"))
        rc, out = self.repo.wsc('jobs', 'check')
        self.assertEqual(rc, 0, out)
        self.assertIn('J2: brief: says BAD', out)
        self.assertIn('jobs check: 2 rows, ok, 1 of 2 briefs checked', out)


POLICY_MOD = '''
from warscape.gates import Result
NAME = 'house_policy'
STAGES = ('policy',)

def run(ctx):
    f = ctx.facts
    return Result(NAME, 'error', 'seen', [f"kind={f['kind']}", f"changed={','.join(f['changed'])}", f"extra={f.get('extra')}"])
'''


class PolicyStage(unittest.TestCase):
    def setUp(self):
        # [ci] core = "": no core in this repo, so `wsc policy` judges as before W23 (in-process, this checkout's modules)
        self.repo = TempRepo({'checks/p.py': mod(POLICY_MOD), 'README.md': '# r\n'}, toml=TOML + '[ci]\ncore = ""\n')
        self.addCleanup(self.repo.close)
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'base')
        self.git('branch', '-M', 'main')
        self.git('checkout', '-q', '-b', 'plan/x')
        self.repo.write('docs/note.md', 'n\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'note')

    def git(self, *a):
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *a],
                       cwd=self.repo.root, check=True, capture_output=True)

    def test_a_policy_module_sees_the_facts_and_an_extra_fact(self):
        rc, out = self.repo.wsc('policy', '--branch', 'plan/x', '--base', 'main')
        self.assertEqual(rc, 1, out)
        self.assertIn('policy: kind=plan', out)
        self.assertIn('policy: changed=docs/note.md', out)
        errs, _ = policy.run_check(Ctx.load(self.repo.root), 'plan/x', 'main', 'plan/x', self.repo.root, extra_facts={'extra': 'given'})
        self.assertIn('extra=given', errs)

    def test_wsc_gates_never_runs_it(self):
        rc, out = self.repo.wsc('gates', '--fast')
        self.assertNotIn('house_policy', out)
        self.assertNotIn('kind=', out)
        rc, out = self.repo.wsc('gates', '--only', 'house_policy')
        self.assertEqual(rc, 2)
        self.assertIn('unknown gate(s) house_policy', out)


VIEW_MOD = '''
from warscape.gates import Result
NAME = 'panel'
STAGES = ('view',)
HTML = ''

def run(ctx):
    return Result(NAME, 'ok', f'{len(ctx.rows)} rows <b>here</b>', ['a & b'], html=HTML)
'''


class ViewStage(unittest.TestCase):
    def page(self, body):
        repo = TempRepo({'checks/v.py': mod(body)}, toml=TOML)
        self.addCleanup(repo.close)
        return jobq.render_view([], lambda p: None, set(), 'now', ctx=Ctx.load(repo.root))

    def test_the_summary_is_escaped(self):
        page = self.page(VIEW_MOD)
        self.assertIn('<p class="muted">0 rows &lt;b&gt;here&lt;/b&gt;', page)
        self.assertIn('a &amp; b', page)

    def test_html_is_drawn_as_is(self):
        page = self.page(VIEW_MOD.replace("HTML = ''", "HTML = '<p class=\"pc\">PC <b>free</b></p>'"))
        self.assertIn('<p class="pc">PC <b>free</b></p>', page)
        self.assertNotIn('rows &lt;b&gt;', page)

    def test_an_empty_result_draws_nothing(self):
        page = self.page(VIEW_MOD.replace("f'{len(ctx.rows)} rows <b>here</b>', ['a & b']", "''"))
        self.assertNotIn('<p class="muted"></p>', page)


if __name__ == '__main__':
    unittest.main()
