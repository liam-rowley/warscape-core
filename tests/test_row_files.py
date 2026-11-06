"""W43: decisions as one file per row, minted ids, and backlog items as `later` job rows.

The rule (`[policy] decisions = "registry:<name>"`), `wsc reg add --mint`, `wsc reg migrate --from-md`, the retired-file guard, `[gates] skip` by a row
file, the `later` status and `wsc jobs later`. A repo whose `decisions` is a Markdown path takes none of this: test_policy.py and the fixture game hold it."""
import json
import re
import unittest

from _util import TempRepo, git
from warscape import gates as G
from warscape import jobq as J
from warscape import policy as pp
from warscape.registry import Registry, load_all, mint_id
from warscape.repo import DEFAULTS, ConfigError, Ctx, load_config

D = 'registries/decisions'
CFG = pp.settings({**DEFAULTS, 'policy': {**DEFAULTS['policy'], 'decisions': 'registry:decisions', 'decision_prefix': 'C'}})
NEW = 'C261105-a3f2'
TOML = '''
registries_dir = "registries"
[registries]
decisions = "core:decisions"
jobs = "core:jobs"
[storage]
dir = ["decisions", "jobs"]
[views]
commit = false
[tests]
dirs = []
[jobs]
id_prefix = "W"
[policy]
decision_prefix = "C"
decisions = "registry:decisions"
'''
TABLE = ('# Decisions\n\nProse.\n\n| # | Date | Who | Decision | Reversible |\n|---|---|---|---|---|\n'
         '| C1 | 2026-10-28 | Liam | First. | yes |\n'
         '| C2 | 2026-10-29 | proposed (Claude, W1) | Second, with `a` and more. | yes (a rename) |\n')
BACKLOG = ('# Backlog\n\n| # | Change | Why | Raised |\n|---|---|---|---|\n'
           '| B4 | **Large registries**: skip the view | a big one is slow | planning chat, 2026-11-01 |\n'
           '| B19 | **Show-time guard**: a hook | a window can be seen |\n'
           '| B98 | **Harden the rule**: `key = "warn" \\| "error"` | until then a job can add one | W36 report |\n')


def row(rid=NEW, **kw):
    return json.dumps({'id': rid, 'date': '2026-11-05', 'who': 'proposed (Claude, core W43)', 'decision': 'A thing.', 'reversible': 'yes', **kw}, indent=2) + '\n'


def tree(**rows):
    t = {f'{D}/{k}.json': v for k, v in rows.items()}
    return t.get


def problems(changed, base, head):
    return pp.decision_row_problems(changed, base, head, CFG)


class Rule(unittest.TestCase):
    """The append-only rule as a file rule."""
    BASE = {'C36': row('C36')}

    def p(self, rid, text, base=None):
        return problems([f'{D}/{rid}.json'], tree(**(base or self.BASE)), tree(**{**(base or self.BASE), rid: text}))

    def test_a_minted_row_is_ok(self):
        self.assertEqual(self.p(NEW, row()), [])

    def test_a_changed_row_is_refused(self):
        self.assertIn('append only', self.p('C36', row('C36', decision='Changed.'))[0])

    def test_a_changed_row_is_refused_with_a_replacing_row_too(self):
        got = problems([f'{D}/C36.json', f'{D}/{NEW}.json'], tree(**self.BASE), tree(C36=row('C36', decision='Changed.'), **{NEW: row(replaces=['C36'])}))
        self.assertEqual(len(got), 1)
        self.assertIn('C36', got[0])

    def test_a_deleted_row_is_refused(self):
        self.assertIn('append only', problems([f'{D}/C36.json'], tree(**self.BASE), tree())[0])

    def test_a_rename_is_a_delete_and_an_add_and_is_refused(self):
        got = problems([f'{D}/C36.json', f'{D}/{NEW}.json'], tree(**self.BASE), tree(**{NEW: row()}))
        self.assertTrue(any('append only' in e for e in got))

    def test_a_replacing_row_names_a_row_that_exists(self):
        self.assertEqual(problems([f'{D}/{NEW}.json'], tree(**self.BASE), tree(**self.BASE, **{NEW: row(replaces=['C36'])})), [])
        self.assertIn('C37', self.p(NEW, row(replaces=['C37']))[0])

    def test_a_numeric_id_is_refused(self):
        self.assertIn('wsc reg add', self.p('C40', row('C40'))[0])

    def test_an_id_that_is_not_its_file_name_is_refused(self):
        self.assertIn('file name', self.p(NEW, row('C261105-ffff'))[0])

    def test_each_bad_field_is_refused(self):
        for k, v in (('date', 'today'), ('who', ''), ('decision', ' '), ('reversible', 'maybe')):
            self.assertIn(k, self.p(NEW, row(**{k: v}))[0], k)

    def test_bad_json_fails_closed(self):
        self.assertIn('JSON', self.p(NEW, '{not json')[0])
        self.assertTrue(self.p(NEW, '[1, 2]\n'))

    def test_a_stray_file_in_the_folder_is_refused(self):
        self.assertIn('stray.txt', problems([f'{D}/stray.txt'], tree(), lambda p: 'x')[0])

    def test_a_branch_behind_the_base_changes_nothing(self):
        """`changed` runs from the merge base, so rows the base gained since are not in it: no "merge the base" error."""
        self.assertEqual(problems([f'{D}/{NEW}.json'], tree(**self.BASE, **{'C261105-0000': row('C261105-0000')}), tree(**self.BASE, **{NEW: row()})), [])

    def test_a_row_the_base_already_has_unchanged_is_ok(self):
        self.assertEqual(self.p('C36', row('C36')), [])

    def test_the_added_rows_keep_the_fact_shape(self):
        got = pp.added_decision_files([f'{D}/{NEW}.json'], tree(), tree(**{NEW: row()}), CFG)
        self.assertEqual(got, [{'id': NEW, 'text': f'| {NEW} | 2026-11-05 | proposed (Claude, core W43) | A thing. | yes |'}])

    def test_check_runs_the_rule_on_every_branch_kind_and_rule_f_reads_it(self):
        cfg = {**CFG, 'decisions_cite_job': True, 'job_prefix': 'W'}
        kw = {'cfg': cfg, 'base_ref': 'origin/main'}
        base, bad = tree(**self.BASE), tree(C36=row('C36', decision='Edited.'))
        self.assertTrue(any('append only' in e for e in pp.check('plan/x', [f'{D}/C36.json'], {}, {}, base, bad, **kw)))
        head = lambda p: {f'{D}/{NEW}.json': row(), 'jobs/W9/report.md': 'r'}.get(p)
        e = pp.check('job/W9', [f'{D}/{NEW}.json'], {'W9': {'id': 'W9'}}, {'W9': {'id': 'W9', 'status': 'done'}}, lambda p: 'b' if p.endswith('brief.md') else None, head, **kw)
        self.assertTrue(any('must name the brief' in x for x in e), e)

    def test_a_markdown_repo_never_reads_the_folder(self):
        md = {**CFG, 'decisions': 'docs/DECISIONS.md', 'decisions_dir': ''}
        self.assertEqual(pp.check('plan/x', [f'{D}/C36.json'], {}, {}, tree(**self.BASE), tree(), cfg={**md, 'plan': ['registries/**']}), [])


class Config(unittest.TestCase):
    def test_the_registry_must_be_declared_and_one_file_per_row(self):
        for toml, word in ((TOML.replace('decisions = "core:decisions"\n', ''), 'declare'), (TOML.replace('dir = ["decisions", "jobs"]', 'dir = ["jobs"]'), '[storage]')):
            repo = TempRepo(toml=toml)
            self.addCleanup(repo.close)
            with self.assertRaises(ConfigError) as c:
                load_config(repo.root)
            self.assertIn(word, str(c.exception))

    def test_a_head_that_empties_the_key_is_a_rule_input_only(self):
        """C24 in one line: the key is read from the config handed in, which is the base's; tests/test_policy_base.py runs it through the judge."""
        self.assertEqual(pp.settings({**DEFAULTS, 'policy': {**DEFAULTS['policy'], 'decisions': 'registry:decisions'}})['decisions_dir'], D)
        self.assertEqual(pp.settings(DEFAULTS)['decisions_dir'], '')


class Mint(unittest.TestCase):
    def test_the_shape(self):
        self.assertRegex(mint_id('C', set()), r'^C\d{6}-[0-9a-f]{4}$')

    def test_it_never_returns_a_taken_id(self):
        seq = iter(['aaaa', 'aaaa', 'bbbb'])
        self.assertEqual(mint_id('C', {'C261105-aaaa'}, today='261105', rand=lambda: next(seq)), 'C261105-bbbb')

    def test_two_draws_differ(self):
        self.assertGreater(len({mint_id('C', set()) for _ in range(50)}), 1)


class Verbs(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(toml=TOML)
        self.addCleanup(self.repo.close)

    def reg(self):
        return load_all(Ctx.load(self.repo.root))

    def test_add_mint_writes_a_row_file_and_defaults_the_date(self):
        rc, out = self.repo.wsc('reg', 'add', 'decisions', '--mint', 'who=Liam', 'decision=Yes.', 'reversible=yes')
        self.assertEqual(rc, 0, out)
        r = self.reg()['decisions'].rows[0]
        self.assertRegex(r['id'], r'^C\d{6}-[0-9a-f]{4}$')
        self.assertRegex(r['date'], r'^\d{4}-\d\d-\d\d$')
        self.assertTrue((self.repo.root / D / f"{r['id']}.json").is_file())

    def test_mint_refuses_a_given_id_and_another_registry(self):
        self.assertNotEqual(self.repo.wsc('reg', 'add', 'decisions', '--mint', 'id=C9', 'who=L', 'decision=x', 'reversible=yes')[0], 0)
        self.assertNotEqual(self.repo.wsc('reg', 'add', 'jobs', '--mint', 'title=x')[0], 0)

    def test_from_md_round_trip_and_check(self):
        self.repo.write('docs/DECISIONS.md', TABLE)
        rc, out = self.repo.wsc('reg', 'migrate', 'decisions', '--from-md', 'docs/DECISIONS.md')
        self.assertEqual(rc, 0, out)
        got = {r['id']: r for r in self.reg()['decisions'].rows}
        self.assertEqual(got['C2'], {'id': 'C2', 'date': '2026-10-29', 'who': 'proposed (Claude, W1)', 'decision': 'Second, with `a` and more.', 'reversible': 'yes (a rename)'})
        rc, out = self.repo.wsc('reg', 'migrate', 'decisions', '--from-md', 'docs/DECISIONS.md', '--check')
        self.assertEqual(rc, 0, out)
        self.assertIn('2 rows', out)

    def test_check_names_a_lost_row_and_a_changed_row(self):
        self.repo.write('docs/DECISIONS.md', TABLE)
        self.repo.wsc('reg', 'migrate', 'decisions', '--from-md', 'docs/DECISIONS.md')
        self.repo.write('docs/DECISIONS.md', TABLE + '| C3 | 2026-10-30 | Liam | Third. | no |\n')
        (self.repo.root / D / 'C1.json').write_text(row('C1', decision='Other.'), encoding='utf-8')
        rc, out = self.repo.wsc('reg', 'migrate', 'decisions', '--from-md', 'docs/DECISIONS.md', '--check')
        self.assertEqual(rc, 1)
        self.assertIn('C3', out)
        self.assertIn('C1', out)

    def test_the_view_sorts_by_date_then_natural_id_and_is_not_cut(self):
        long = 'word ' * 80
        self.repo.write(f'{D}/C10.json', row('C10', date='2026-10-30'))
        self.repo.write(f'{D}/C2.json', row('C2', date='2026-10-30', decision=long.strip()))
        self.repo.write(f'{D}/{NEW}.json', row())
        text = self.reg()['decisions'].render()
        self.assertLess(text.index('`C2`'), text.index('`C10`'))
        self.assertLess(text.index('`C10`'), text.index(NEW))
        self.assertIn(long.strip(), text)

    def test_a_registry_without_the_view_key_keeps_its_order_and_its_cut(self):
        reg = self.reg()['jobs']
        reg.rows = [{'id': i, 'title': 't' * 300, 'status': 'done'} for i in ('W2', 'W10')]
        text = reg.render()
        self.assertLess(text.index('W10'), text.index('W2`'))
        self.assertIn('...', text)

    def test_rows_are_json_so_the_doc_cap_never_sees_them(self):
        self.repo.write(f'{D}/{NEW}.json', row(decision='x' * 40000))
        git(self.repo.root, 'add', '-A')
        self.assertEqual(G.gate_doc_size(Ctx.load(self.repo.root)).level, 'ok')


class RetiredFile(unittest.TestCase):
    """[policy] decisions_retired as a policy rule: the base's rules reach a head the `registries` gate cannot."""
    P = 'docs/DECISIONS.md'
    ROW = '| C3 | 2026-11-05 | Liam | Stale branch. | yes |\n'
    CFG = {**CFG, 'decisions_retired': P}

    def errs(self, new, old=TABLE, branch='plan/x', changed=None, cfg=None):
        return pp.check(branch, [self.P] if changed is None else changed, {}, {}, lambda p: old if p == self.P else None, lambda p: new if p == self.P else None,
                        cfg=cfg or self.CFG)

    def frozen(self, errs):
        return [e for e in errs if 'is frozen' in e]

    def test_a_changed_table_is_refused_on_every_branch_kind(self):
        for branch in ('plan/x', 'meta/x', 'brief/W9', 'job/W9', 'release/v9.0.0', 'decide/x', 'other'):
            self.assertTrue(self.frozen(self.errs(TABLE + self.ROW, branch=branch)), branch)
        self.assertTrue(self.frozen(self.errs(TABLE + self.ROW, branch='boot', cfg={**self.CFG, 'bootstrap': ['boot']})))

    def test_any_table_line_counts_not_only_a_well_formed_row(self):
        self.assertTrue(self.frozen(self.errs(TABLE.replace('| C2 ', '|  C2 '))))        # an edit
        self.assertTrue(self.frozen(self.errs(TABLE + '| not an id | x |\n')))           # a row no id pattern matches
        self.assertTrue(self.frozen(self.errs(TABLE + '  ' + self.ROW)))                 # an indented one
        self.assertTrue(self.frozen(self.errs(TABLE + self.ROW, old=None)))              # a file the base has dropped, put back

    def test_prose_and_deleting_the_file_pass(self):
        self.assertEqual(self.frozen(self.errs('# Moved\n\nProse.\n\n' + TABLE + '\nMore.\n')), [])
        self.assertEqual(self.frozen(self.errs(None)), [])

    def test_a_branch_that_leaves_the_file_alone_is_not_judged_for_being_behind(self):
        self.assertEqual(self.frozen(self.errs(TABLE, old=TABLE + self.ROW, changed=['docs/X.md'])), [])

    def test_no_key_no_rule_and_markdown_mode_has_no_key(self):
        self.assertEqual(self.frozen(self.errs(TABLE + self.ROW, cfg=CFG)), [])
        md = pp.settings({**DEFAULTS, 'policy': {**DEFAULTS['policy'], 'decisions': self.P, 'decisions_retired': self.P}})
        self.assertEqual(md['decisions_retired'], '')


class Gates(unittest.TestCase):
    RETIRED = TOML + 'decisions_retired = "docs/DECISIONS.md"\n'

    def repo_with(self, toml, text=TABLE):
        repo = TempRepo({'docs/DECISIONS.md': text}, toml=toml)
        self.addCleanup(repo.close)
        repo.wsc('reg', 'migrate', 'decisions', '--from-md', 'docs/DECISIONS.md')
        return repo

    def test_a_retired_file_in_step_passes(self):
        repo = self.repo_with(self.RETIRED)
        self.assertEqual(G.gate_registries(Ctx.load(repo.root)).level, 'ok')

    def test_a_row_added_to_the_retired_file_fails_the_gate(self):
        repo = self.repo_with(self.RETIRED)
        repo.write('docs/DECISIONS.md', TABLE + '| C3 | 2026-11-05 | Liam | Stale branch. | yes |\n')
        res = G.gate_registries(Ctx.load(repo.root))
        self.assertEqual(res.level, 'error')
        self.assertIn('C3', ' '.join(res.details))

    def test_a_deleted_retired_file_passes(self):
        repo = self.repo_with(self.RETIRED)
        (repo.root / 'docs/DECISIONS.md').unlink()
        self.assertEqual(G.gate_registries(Ctx.load(repo.root)).level, 'ok')

    def test_a_skip_finds_its_decision_in_a_row_file(self):
        repo = self.repo_with(TOML + '[gates]\nskip = ["eol:C1"]\n')
        self.assertEqual(G.skips(Ctx.load(repo.root)), {'eol': 'C1'})
        repo.write('wsc.toml', (TOML + '[gates]\nskip = ["eol:C9"]\n'))
        with self.assertRaises(ValueError) as c:
            G.skips(Ctx.load(repo.root))
        self.assertIn('C9', str(c.exception))


LATER = {'id': 'W7', 'description': 'a later item', 'title': 'Later', 'phase': 1, 'status': 'later', 'model': 'sonnet', 'needs_pc': False, 'depends_on': [], 'backlog_id': 'B96', 'area': 'core'}


class Later(unittest.TestCase):
    """The `later` status: recorded and searchable, never picked up."""

    def setUp(self):
        self.repo = TempRepo(toml=TOML.replace('id_prefix = "W"', 'id_prefix = "W"\nsemver_from = 1'))
        self.addCleanup(self.repo.close)
        self.repo.write('registries/jobs/W7.json', json.dumps(LATER, indent=2) + '\n')
        J.configure(Ctx.load(self.repo.root))

    def test_nothing_picks_it_up(self):
        self.assertEqual(J.pick_next([LATER], set())[:2], (None, None))
        self.assertIn('later', J.not_ready('brief', 'W7', {'W7': LATER}, set()))
        self.assertIn('later', J.not_ready('build', 'W7', {'W7': LATER}, set()))

    def test_jobs_next_id_refuses_it(self):
        rc, msg = J.next_claim(self.repo.root, [LATER], lambda: {}, jid='W7', peek=True)
        self.assertEqual(rc, 1)
        self.assertIn('later', msg)

    def test_jobs_check_passes_it_with_no_semver_and_no_brief(self):
        rc, out = self.repo.wsc('jobs', 'check')
        self.assertEqual(rc, 0, out)

    def test_a_later_row_with_a_brief_is_refused(self):
        self.repo.write('jobs/W7/brief.md', '# W7: x\n')
        rc, out = self.repo.wsc('jobs', 'check')
        self.assertEqual(rc, 1)
        self.assertIn('later', out)

    def test_it_has_its_own_lane(self):
        self.assertEqual(J.lane(LATER, {'W7': LATER}, set())[0], 'later')
        self.assertIn('later', [k for k, _, _ in J.LANES])

    def test_promotion_is_a_status_change(self):
        rc, out = self.repo.wsc('reg', 'set', 'jobs', 'W7', 'status=needs_brief')
        self.assertEqual(rc, 0, out)
        self.assertIsNone(J.not_ready('brief', 'W7', {'W7': {**LATER, 'status': 'needs_brief'}}, set()))

    def test_find_resolves_the_old_number_ahead_of_a_row_that_cites_it(self):
        self.repo.write('registries/jobs/W1.json', json.dumps({**LATER, 'id': 'W1', 'description': 'Covers B96 and B96.', 'backlog_id': 'B2'}, indent=2) + '\n')
        rc, out = self.repo.wsc('find', 'B96')
        self.assertEqual(rc, 0, out)
        self.assertLess(out.index('W7'), out.index('W1'))


class LaterImport(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo({'docs/BACKLOG.md': BACKLOG}, toml=TOML)
        self.addCleanup(self.repo.close)
        self.repo.write('registries/jobs/W43.json', json.dumps({**LATER, 'id': 'W43'}, indent=2) + '\n')

    def rows(self):
        return {r.get('backlog_id'): r for r in load_all(Ctx.load(self.repo.root))['jobs'].rows}

    def run_it(self, *more):
        return self.repo.wsc('jobs', 'later', '--from-md', 'docs/BACKLOG.md', '--area', 'harness', *more)

    def test_each_table_row_becomes_a_later_row_with_no_text_lost(self):
        self.repo.write('registries/jobs/W43.json', json.dumps({**LATER, 'id': 'W43', 'backlog_id': 'B1'}, indent=2) + '\n')
        rc, out = self.run_it()
        self.assertEqual(rc, 0, out)
        got = self.rows()
        self.assertEqual([got[b]['id'] for b in ('B4', 'B19', 'B98')], ['W44', 'W45', 'W46'])
        r = got['B4']
        self.assertEqual((r['status'], r['area'], r['title'], r['model'], r['phase'], r['needs_pc']), ('later', 'harness', 'Large registries', 'sonnet', 1, False))
        for text in ('**Large registries**: skip the view', 'a big one is slow', 'planning chat, 2026-11-01'):
            self.assertIn(text, r['description'])
        self.assertIn('`key = "warn" | "error"`', got['B98']['description'])
        self.assertIn('a window can be seen', got['B19']['description'])

    def test_check_and_a_second_run(self):
        self.run_it()
        rc, out = self.run_it('--check')
        self.assertEqual(rc, 0, out)
        self.assertIn('3 rows', out)
        n = len(self.rows())
        self.assertEqual(self.run_it()[0], 0)
        self.assertEqual(len(self.rows()), n)

    def test_check_names_a_lost_row(self):
        self.run_it()
        self.repo.write('docs/BACKLOG.md', BACKLOG + '| B99 | **New**: x | y | z |\n')
        rc, out = self.run_it('--check')
        self.assertEqual(rc, 1)
        self.assertIn('B99', out)

    def test_check_names_changed_text(self):
        self.run_it()
        self.repo.write('docs/BACKLOG.md', BACKLOG.replace('a big one is slow', 'a big one is fast'))
        rc, out = self.run_it('--check')
        self.assertEqual(rc, 1)
        self.assertIn('B4', out)


class Shipped(unittest.TestCase):
    def test_the_shipped_schema_takes_both_id_forms(self):
        repo = TempRepo(toml=TOML)
        self.addCleanup(repo.close)
        repo.write(f'{D}/C1.json', row('C1'))
        repo.write(f'{D}/{NEW}.json', row(replaces=['C1']))
        self.assertEqual(repo.wsc('reg', 'check', 'decisions')[0], 0)
        self.assertIsInstance(load_all(Ctx.load(repo.root))['decisions'], Registry)
        self.assertTrue(re.fullmatch(r'C\d{6}-[0-9a-f]{4}', NEW))


if __name__ == '__main__':
    unittest.main()
