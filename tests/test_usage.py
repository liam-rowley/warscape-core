"""Host tests for usage accounting (core W31): the report's `Usage:` line, `[jobs] usage_from` and `usage_cmd`, `budget_lifts` and `wsc jobs usage`,
`Result.cards` and the usage chip of `wsc jobs view`. The core reads no transcript: the command is the only seam (tests/fake_usage_cmd.py plays the game).
"""
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from warscape import jobq as jv  # noqa: E402
from warscape.gates import Result  # noqa: E402
from warscape.registry import load_schema  # noqa: E402
from warscape.repo import ConfigError, load_config  # noqa: E402
from warscape.schema import validate  # noqa: E402

FAKE = ROOT / 'tests' / 'fake_usage_cmd.py'
BRIEF = '# J5: thing\n\nModel: Opus, reason: x. Budget about 100 tool calls; at the cap, stop.\n'
LINE = 'Usage: 100 tool calls; models: opus; 1 session, by hand'
REPORT = '# J5 report: thing\n\nWhat was built, in two\nlines.\n\n## Deviations\nnone\n\n## Open questions\nnone\n'


def report(line=LINE):
    return REPORT.replace('## Deviations', f'{line}\n\n## Deviations', 1)


def row(jid='J5', **kw):
    r = {'id': jid, 'description': 'd', 'title': 't', 'phase': 1, 'status': 'review', 'model': 'opus', 'needs_pc': False, 'depends_on': []}
    r.update(kw)
    return r


def lift(frm, to, why='the scope grew', date='2026-11-04'):
    return {'date': date, 'from': frm, 'to': to, 'why': why}


class Rule(unittest.TestCase):
    """Every test here runs with `usage_from = 5`, ids J<n>."""

    def setUp(self):
        for k, v in (('usage_from', 5), ('prefix', 'J')):
            p = mock.patch.object(jv.S, k, v, create=True)
            p.start()
            self.addCleanup(p.stop)


class ParseUsage(unittest.TestCase):
    def ok(self, text):
        u, err = jv.parse_usage(text)
        self.assertIsNone(err)
        return u

    def bad(self, text, *words):
        u, err = jv.parse_usage(text)
        self.assertIsNone(u)
        for w in words:
            self.assertIn(w, err)

    def test_the_exact_shape(self):
        u = self.ok(report('Usage: 142 tool calls; models: opus, sonnet; 2 sessions; about $3, from the reader, 2026-11-04'))
        self.assertEqual((u.calls, u.models), (142, ['opus', 'sonnet']))
        self.assertEqual(u.note, '2 sessions; about $3, from the reader, 2026-11-04')

    def test_extra_spaces_are_read(self):
        u = self.ok(report('Usage:   142  tool  calls ;  models:  opus ,  sonnet ;   a note  '))
        self.assertEqual((u.calls, u.models, u.note), (142, ['opus', 'sonnet'], 'a note'))

    def test_a_crlf_report_is_read(self):
        self.assertEqual(self.ok(report().replace('\n', '\r\n')).calls, 100)

    def test_no_line_says_the_shape(self):
        self.bad(REPORT, 'no "Usage: <n> tool calls; models: <m1>, <m2>; <free text>" line')

    def test_no_models_part_is_an_error(self):
        self.bad(report('Usage: 142 tool calls; 2 sessions'), 'does not parse', '<n> tool calls')

    def test_empty_models_are_an_error(self):
        self.bad(report('Usage: 142 tool calls; models: ; 2 sessions'), 'does not parse')
        self.bad(report('Usage: 142 tool calls; models: opus,, sonnet; 2 sessions'), 'does not parse')

    def test_no_free_text_is_an_error(self):
        self.bad(report('Usage: 142 tool calls; models: opus'), 'does not parse')

    def test_a_count_that_is_not_an_integer_is_an_error(self):
        for n in ('about 142', '14.2', '-1', 'many', '1' * 5000):
            self.bad(report(f'Usage: {n} tool calls; models: opus; x'), 'does not parse')

    def test_two_lines_are_an_error(self):
        self.bad(report(LINE + '\n' + LINE), 'two "Usage:" lines')

    def test_a_line_in_a_code_fence_is_ignored(self):
        fenced = f'```\n{LINE}\n```'
        self.bad(report(fenced), 'no "Usage:')
        self.assertEqual(self.ok(report(LINE + '\n\n' + fenced)).calls, 100)
        self.assertEqual(self.ok(report(LINE + '\n\n~~~~text\n```\nUsage: nonsense\n~~~\n~~~~\n')).calls, 100)

    def test_an_inline_triple_backtick_opens_no_fence(self):
        self.assertEqual(self.ok(report('```not a fence``` text\n\n' + LINE)).calls, 100)

    def test_usage_mid_line_is_not_the_line(self):
        self.bad(report('The Usage: 12 tool calls; models: opus; x line'), 'no "Usage:')


class BriefBudget(unittest.TestCase):
    def test_reads_the_number_brief_problems_requires(self):
        self.assertEqual(jv.brief_budget(BRIEF), 100)
        self.assertEqual(jv.brief_budget('budget  about 7 tool  calls'), 7)
        self.assertIsNone(jv.brief_budget('Budget about <n> tool calls'))
        self.assertIsNone(jv.brief_budget(''))

    def test_effective_budget_is_the_newest_lift_else_the_brief(self):
        self.assertEqual(jv.effective_budget(row(), BRIEF), 100)
        self.assertEqual(jv.effective_budget(row(budget_lifts=[lift(100, 120), lift(120, 200)]), BRIEF), 200)
        self.assertIsNone(jv.effective_budget(row(), None))
        self.assertEqual(jv.effective_budget(row(budget_lifts=['junk']), BRIEF), 100)   # the schema reports junk; nothing here may crash


class UsageProblems(Rule):
    def errs(self, r=None, brief=BRIEF, rep=None, jid='J5'):
        return jv.usage_problems(jid, r or row(jid), brief, report() if rep is None else rep)

    def test_a_good_line_passes(self):
        self.assertEqual(self.errs(), [])

    def test_off_below_usage_from(self):
        self.assertEqual(self.errs(row('J4'), rep=REPORT, jid='J4'), [])

    def test_off_when_usage_from_is_zero(self):
        with mock.patch.object(jv.S, 'usage_from', 0):
            self.assertEqual(self.errs(rep=REPORT), [])

    def test_a_missing_line_is_an_error_that_names_the_way_out(self):
        (e,) = self.errs(rep=REPORT)
        self.assertIn('no "Usage:', e)
        self.assertIn('jobs usage J5 --write', e)

    def test_a_line_that_does_not_parse_is_an_error(self):
        (e,) = self.errs(rep=report('Usage: lots'))
        self.assertIn('does not parse', e)

    def test_every_status_with_a_report_is_checked(self):
        for st in ('review', 'fix', 'done'):
            self.assertEqual(len(self.errs(row(status=st), rep=REPORT)), 1, st)

    def test_a_row_with_no_report_yet_is_not_checked(self):
        for st in ('needs_brief', 'queued', 'blocked'):
            self.assertEqual(self.errs(row(status=st), rep=REPORT), [], st)
        self.assertEqual(jv.usage_problems('J5', row(), BRIEF, None), [])   # the row rule reports the missing file

    def test_the_ceiling_is_one_and_a_quarter_times_the_budget(self):
        self.assertEqual(self.errs(rep=report('Usage: 125 tool calls; models: opus; x')), [])
        (e,) = self.errs(rep=report('Usage: 126 tool calls; models: opus; x'))
        self.assertIn('126', e)
        self.assertIn('100', e)

    def test_the_ceiling_rounds_nothing(self):
        brief = BRIEF.replace('100', '150')   # 1.25 x 150 = 187.5
        self.assertEqual(self.errs(brief=brief, rep=report('Usage: 187 tool calls; models: opus; x')), [])
        self.assertEqual(len(self.errs(brief=brief, rep=report('Usage: 188 tool calls; models: opus; x'))), 1)

    def test_a_lift_raises_the_ceiling(self):
        over = report('Usage: 200 tool calls; models: opus; x')
        self.assertEqual(len(self.errs(rep=over)), 1)
        self.assertEqual(self.errs(row(budget_lifts=[lift(100, 160)]), rep=over), [])
        self.assertEqual(self.errs(row(budget_lifts=[lift(100, 120), lift(120, 160)]), rep=over), [])
        (e,) = self.errs(row(budget_lifts=[lift(100, 120)]), rep=over)
        self.assertIn('120', e)

    def test_a_lift_must_raise_the_budget(self):
        (e,) = self.errs(row(budget_lifts=[lift(100, 100)]))
        self.assertIn('budget_lifts[0]', e)
        (e,) = self.errs(row(budget_lifts=[lift(100, 90)]), rep=report('Usage: 90 tool calls; models: opus; x'))
        self.assertIn('not above', e)

    def test_the_chain_starts_at_the_brief_and_never_breaks(self):
        (e,) = self.errs(row(budget_lifts=[lift(90, 120)]))
        self.assertIn("the brief's budget 100", e)
        (e,) = self.errs(row(budget_lifts=[lift(100, 120), lift(130, 140)]))
        self.assertIn('budget_lifts[1]', e)
        self.assertIn('previous', e)

    def test_a_lift_needs_a_why(self):
        for why in ('', '   ', None):
            (e,) = self.errs(row(budget_lifts=[lift(100, 120, why=why)]))
            self.assertIn('why', e)

    def test_junk_lifts_are_errors_not_crashes(self):
        self.assertEqual(len(self.errs(row(budget_lifts=['junk']))), 1)
        self.assertEqual(len(self.errs(row(budget_lifts={'to': 1}))), 1)
        self.assertEqual(len(self.errs(row(budget_lifts=[{'from': 'a', 'to': True, 'why': 'x'}]))), 1)

    def test_no_budget_leaves_the_ceiling_to_the_brief_rule(self):
        self.assertEqual(jv.usage_problems('J5', row(), None, report('Usage: 9999 tool calls; models: opus; x')), [])
        self.assertEqual(jv.usage_problems('J5', row(budget_lifts=[lift(1, 2)]), None, report('Usage: 1 tool calls; models: opus; x')), [])

    def test_another_model_is_an_error_naming_both(self):
        (e,) = self.errs(rep=report('Usage: 10 tool calls; models: sonnet; x'))
        self.assertIn('sonnet', e)
        self.assertIn('opus', e)

    def test_models_compare_by_lower_case_first_word(self):
        for m in ('Opus', 'OPUS', 'opus 5.5', 'opus-5-5'):
            self.assertEqual(self.errs(rep=report(f'Usage: 10 tool calls; models: {m}; x')), [], m)

    def test_one_other_model_of_two_is_an_error(self):
        (e,) = self.errs(rep=report('Usage: 10 tool calls; models: opus, haiku; x'))
        self.assertIn('haiku', e)
        self.assertEqual(self.errs(row(model='sonnet'), rep=report('Usage: 10 tool calls; models: sonnet, Sonnet; x')), [])

    def test_a_record_the_verb_takes_is_a_line_the_rule_takes(self):
        for name in ('opus', 'Opus', 'opus 5.5', 'opus-5-5'):
            line = jv.usage_line(jv.usage_record({'calls': 10, 'models': [name], 'sessions': 1, 'note': ''}))
            self.assertEqual(self.errs(rep=report(line)), [], name)


class Record(unittest.TestCase):
    GOOD = {'calls': 42, 'models': ['Opus'], 'sessions': 2, 'note': 'from the reader'}

    def test_the_line_is_what_the_rule_reads(self):
        line = jv.usage_line(jv.usage_record(self.GOOD))
        self.assertEqual(line, 'Usage: 42 tool calls; models: opus; 2 sessions, from the reader')
        u, err = jv.parse_usage(line)
        self.assertEqual((err, u.calls, u.models), (None, 42, ['opus']))

    def test_one_session_and_no_note(self):
        self.assertEqual(jv.usage_line(jv.usage_record({**self.GOOD, 'sessions': 1, 'note': ''})), 'Usage: 42 tool calls; models: opus; 1 session')

    def test_a_note_stays_on_one_line(self):
        self.assertTrue(jv.usage_line(jv.usage_record({**self.GOOD, 'note': 'a\nUsage: 1 tool calls; models: x; y'})).endswith('a Usage: 1 tool calls; models: x; y'))

    def test_a_bad_record_is_refused(self):
        for bad, word in (([], 'object'), ({}, 'calls'), ({**self.GOOD, 'calls': True}, 'calls'), ({**self.GOOD, 'calls': -1}, 'calls'),
                          ({**self.GOOD, 'calls': '42'}, 'calls'), ({**self.GOOD, 'models': []}, 'models'), ({**self.GOOD, 'models': 'opus'}, 'models'),
                          ({**self.GOOD, 'models': ['opus; x']}, 'models'), ({**self.GOOD, 'models': ['a,b']}, 'models'), ({**self.GOOD, 'sessions': 1.5}, 'sessions'),
                          ({**self.GOOD, 'note': 3}, 'note'), ({**self.GOOD, 'models': ['claude-opus-5-5']}, "'claude-opus-5-5'"),
                          ({**self.GOOD, 'models': ['opus', 'haiku']}, "'haiku'")):
            with self.assertRaises(ValueError, msg=bad) as c:
                jv.usage_record(bad)
            self.assertIn(word, str(c.exception))


class Command(unittest.TestCase):
    def cmd(self, mode):
        return f'{shlex.quote(sys.executable)} {shlex.quote(str(FAKE))} {mode} {{id}}'

    def refused(self, cmd, *words, **kw):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError) as c:
            jv.run_usage_cmd(cmd, 'J5', d, **kw)
        for w in words:
            self.assertIn(w, str(c.exception))

    def test_the_id_is_filled_and_the_cwd_is_the_root(self):
        with tempfile.TemporaryDirectory() as d:
            data = jv.run_usage_cmd(self.cmd('ok'), 'J5', d)
        self.assertEqual(data['calls'], 42)
        self.assertEqual(data['note'], f'fake reader for J5 in {Path(d).name}')

    def test_no_shell_runs_the_argv(self):
        seen = {}

        def fake(argv, **kw):
            seen.update(argv=argv, **kw)
            return subprocess.CompletedProcess(argv, 0, json.dumps(Record.GOOD), '')
        jv.run_usage_cmd('tool --job {id} --name "a b" | cat', 'J5', '.', run=fake)
        self.assertEqual(seen['argv'], ['tool', '--job', 'J5', '--name', 'a b', '|', 'cat'])
        self.assertFalse(seen.get('shell'))
        self.assertEqual(seen['timeout'], jv.USAGE_TIMEOUT)
        self.assertEqual(jv.USAGE_TIMEOUT, 60)

    def test_refusals(self):
        self.refused('', 'usage_cmd')
        self.refused('   ', 'usage_cmd')
        self.refused('tool "unclosed', 'usage_cmd')
        self.refused('no-such-tool-w31 {id}', 'no-such-tool-w31')
        self.refused(self.cmd('fail'), 'exit 3', 'no transcripts here')
        self.refused(self.cmd('badjson'), 'JSON')
        self.refused(self.cmd('missing'), 'sessions')

    def test_a_timeout_is_a_refusal(self):
        self.refused(self.cmd('sleep'), 'timed out', timeout=0.5)


class WriteLine(unittest.TestCase):
    NEW = 'Usage: 7 tool calls; models: opus; 1 session'

    def test_insert_after_the_first_paragraph(self):
        got = jv.set_usage_line(REPORT, 'J5', self.NEW)
        self.assertEqual(got, REPORT.replace('## Deviations', f'{self.NEW}\n\n## Deviations', 1))

    def test_replace_changes_nothing_else(self):
        text = report().replace('none\n', 'none  \n\ttabbed\n')
        got = jv.set_usage_line(text, 'J5', self.NEW)
        self.assertEqual(got, text.replace(LINE, self.NEW))

    def test_replace_takes_a_broken_line_too(self):
        self.assertEqual(jv.set_usage_line(report('Usage: lots'), 'J5', self.NEW), report(self.NEW))

    def test_crlf_stays_crlf(self):
        text = report().replace('\n', '\r\n')
        self.assertEqual(jv.set_usage_line(text, 'J5', self.NEW), text.replace(LINE, self.NEW))
        text = REPORT.replace('\n', '\r\n')
        self.assertEqual(jv.set_usage_line(text, 'J5', self.NEW), text.replace('## Deviations', f'{self.NEW}\r\n\r\n## Deviations', 1))

    def test_no_paragraph_goes_under_the_heading(self):
        self.assertEqual(jv.set_usage_line('# J5 report: t\n\n## Deviations\n', 'J5', self.NEW), f'# J5 report: t\n\n{self.NEW}\n\n## Deviations\n')
        self.assertEqual(jv.set_usage_line('# J5 report: t\n## Deviations\n', 'J5', self.NEW), f'# J5 report: t\n\n{self.NEW}\n\n## Deviations\n')
        self.assertEqual(jv.set_usage_line('# J5 report: t', 'J5', self.NEW), f'# J5 report: t\n\n{self.NEW}')

    def test_never_inside_a_fence(self):
        text = '# J5 report: t\n\n```\nsome\n\ncode\n```\n\n## Deviations\n'
        self.assertEqual(jv.parse_usage(jv.set_usage_line(text, 'J5', self.NEW))[0].calls, 7)
        text = '# J5 report: t\n\nA paragraph\n```\nsome\n\ncode\n```\n'
        self.assertEqual(jv.parse_usage(jv.set_usage_line(text, 'J5', self.NEW))[0].calls, 7)

    def test_a_fenced_example_is_not_replaced(self):
        got = jv.set_usage_line(REPORT + f'\n```\n{LINE}\n```\n', 'J5', self.NEW)
        self.assertIn(LINE, got)
        self.assertEqual(jv.parse_usage(got)[0].calls, 7)

    def test_two_lines_are_refused(self):
        with self.assertRaises(ValueError):
            jv.set_usage_line(report(LINE + '\n' + LINE), 'J5', self.NEW)

    def test_a_report_with_no_title_is_refused(self):
        with self.assertRaises(ValueError):
            jv.set_usage_line('no heading\n', 'J5', self.NEW)


class Verb(unittest.TestCase):
    """`wsc jobs usage` end to end on a throwaway repo (no git: the action needs none)."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.d = Path(t.name)
        (self.d / 'registries' / 'jobs').mkdir(parents=True)
        (self.d / 'jobs' / 'J5').mkdir(parents=True)
        (self.d / 'registries' / 'jobs' / 'J5.json').write_text(json.dumps(row(status='queued', brief='jobs/J5/brief.md'), indent=2) + '\n', encoding='utf-8')
        (self.d / 'jobs' / 'J5' / 'brief.md').write_text(BRIEF, encoding='utf-8')
        self.rep = self.d / 'jobs' / 'J5' / 'report.md'
        self.config('ok')

    def config(self, mode):
        cmd = f'{shlex.quote(sys.executable)} {shlex.quote(str(FAKE))} {mode} {{id}}' if mode else ''
        (self.d / 'wsc.toml').write_text('[registries]\njobs = "core:jobs"\n[storage]\ndir = ["jobs"]\n[views]\ncommit = false\n'
                                         f"[jobs]\nusage_from = 5\nusage_cmd = '''{cmd}'''\n", encoding='utf-8')

    def wsc(self, *args):
        p = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(self.d), 'jobs', *args], capture_output=True, encoding='utf-8', timeout=120)
        return p.returncode, p.stdout, p.stderr

    def test_prints_the_line_and_writes_nothing(self):
        self.rep.write_bytes(REPORT.encode())
        rc, out, err = self.wsc('usage', 'J5')
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), f'Usage: 42 tool calls; models: opus; 2 sessions, fake reader for J5 in {self.d.name}')
        self.assertEqual(self.rep.read_bytes(), REPORT.encode())

    def test_failures_exit_1_and_write_nothing(self):
        self.rep.write_bytes(REPORT.encode())
        for mode, word in (('fail', 'exit 3'), ('badjson', 'JSON'), ('missing', 'sessions'), ('', 'usage_cmd')):
            self.config(mode)
            rc, out, err = self.wsc('usage', 'J5', '--write')
            self.assertEqual((rc, out), (1, ''), mode)
            self.assertIn(word, err)
            self.assertEqual(self.rep.read_bytes(), REPORT.encode(), mode)

    def test_write_inserts_then_replaces_byte_for_byte(self):
        self.rep.write_bytes(REPORT.replace('\n', '\r\n').encode())
        rc, out, err = self.wsc('usage', 'J5', '--write')
        self.assertEqual(rc, 0, err)
        line = out.splitlines()[0]
        want = REPORT.replace('## Deviations', f'{line}\n\n## Deviations', 1).replace('\n', '\r\n')
        self.assertEqual(self.rep.read_bytes(), want.encode())
        rc, out, err = self.wsc('usage', 'J5', '--write')
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.rep.read_bytes(), want.encode())          # a second run leaves one line

    def test_write_refuses_a_missing_report(self):
        rc, out, err = self.wsc('usage', 'J5', '--write')
        self.assertEqual(rc, 1)
        self.assertIn('report', err)
        self.assertFalse(self.rep.exists())

    def test_from_json_needs_no_command_and_takes_a_bom(self):
        self.config('')
        self.rep.write_bytes(REPORT.encode())
        f = self.d / 'numbers.json'
        f.write_bytes(b'\xef\xbb\xbf' + json.dumps(Record.GOOD).encode())
        rc, out, err = self.wsc('usage', 'J5', '--write', '--from-json', str(f))
        self.assertEqual(rc, 0, err)
        self.assertIn('Usage: 42 tool calls; models: opus; 2 sessions, from the reader', self.rep.read_text(encoding='utf-8'))

    def test_from_json_refusals(self):
        self.rep.write_bytes(REPORT.encode())
        f = self.d / 'numbers.json'
        for body in ('{"calls": 1,', '{"calls": 1, "calls": 2, "models": ["opus"], "sessions": 1, "note": ""}', '{"calls": 1}'):
            f.write_text(body, encoding='utf-8')
            rc, out, err = self.wsc('usage', 'J5', '--write', '--from-json', str(f))
            self.assertEqual(rc, 1, body)
        rc, out, err = self.wsc('usage', 'J5', '--from-json', str(self.d / 'absent.json'))
        self.assertEqual(rc, 1)
        self.assertEqual(self.rep.read_bytes(), REPORT.encode())

    def test_the_id_must_be_a_row(self):
        for args in (('usage',), ('usage', 'J9'), ('usage', '../..')):
            rc, out, err = self.wsc(*args)
            self.assertEqual(rc, 1, args)

    def test_only_usage_takes_a_bare_id(self):
        """`jobs next W31` must not silently pick another job now that the parser has a positional."""
        rc, out, err = self.wsc('next', 'J5', '--peek', '--offline')
        self.assertEqual(rc, 1)
        self.assertIn('--id', err)


class Config(unittest.TestCase):
    def load(self, body):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'wsc.toml').write_text(body, encoding='utf-8')
            return load_config(Path(d))

    def test_the_defaults_are_off(self):
        cfg = self.load('')
        self.assertEqual((cfg['jobs']['usage_from'], cfg['jobs']['usage_cmd']), (0, ''))

    def test_bad_values_are_refused(self):
        for body in ('[jobs]\nusage_from = -1\n', '[jobs]\nusage_from = "J5"\n', '[jobs]\nusage_from = true\n', '[jobs]\nusage_cmd = 5\n', '[jobs]\nusage_cmd = ["a"]\n'):
            with self.assertRaises(ConfigError, msg=body):
                self.load(body)

    def test_configure_fills_the_settings(self):
        cfg = self.load('[jobs]\nusage_from = 9\nusage_cmd = "tool {id}"\n')['jobs']
        with mock.patch.multiple(jv.S, usage_from=0, usage_cmd='', prefix=jv.S.prefix, models=jv.S.models, jobs_dir=jv.S.jobs_dir, reg_dir=jv.S.reg_dir, ledgers=jv.S.ledgers,
                                 failed_results=jv.S.failed_results, root=jv.S.root, semver_from=jv.S.semver_from, text=jv.S.text, pc_state=jv.S.pc_state, create=True):
            s = jv.configure_from(cfg)
            self.assertEqual((s.usage_from, s.usage_cmd), (9, 'tool {id}'))


class Schema(unittest.TestCase):
    S = load_schema('core:jobs', ROOT)

    def test_a_valid_lift(self):
        self.assertEqual(validate(row(status='needs_brief', budget_lifts=[lift(100, 120)]), self.S), [])

    def test_bad_lifts(self):
        for bad in ({**lift(100, 120), 'extra': 1}, lift(100, 120, date='04/11/2026'), lift(100, 120, date='2026-13-01'), lift(100, 120, why=''), lift(100, 120, why='  '),
                    {'date': '2026-11-04', 'from': 100, 'to': 120}, lift('100', 120), lift(100, 1.5)):
            self.assertNotEqual(validate(row(status='needs_brief', budget_lifts=[bad]), self.S), [], bad)


class RegSet(unittest.TestCase):
    def test_reg_set_writes_a_lift(self):
        """Decision 6: `wsc reg set` takes JSON through key:=, so a lift needs no JSONL edit."""
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / 'registries' / 'jobs').mkdir(parents=True)
            (d / 'registries' / 'jobs' / 'J5.json').write_text(json.dumps(row(status='needs_brief'), indent=2) + '\n', encoding='utf-8')
            (d / 'wsc.toml').write_text('[registries]\njobs = "core:jobs"\n[storage]\ndir = ["jobs"]\n[views]\ncommit = false\n', encoding='utf-8')
            p = subprocess.run([sys.executable, str(ROOT / 'wsc.py'), '--root', str(d), 'reg', 'set', 'jobs', 'J5', 'budget_lifts:=' + json.dumps([lift(100, 120)])],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            got = json.loads((d / 'registries' / 'jobs' / 'J5.json').read_text(encoding='utf-8'))
            self.assertEqual(got['budget_lifts'], [lift(100, 120)])


class Chip(unittest.TestCase):
    def test_within_budget(self):
        self.assertEqual(jv.usage_chip(row(), BRIEF, report()), ('usage 100 / 100 calls · opus', False))

    def test_a_lift_is_applied(self):
        r = row(budget_lifts=[lift(100, 160)])
        self.assertEqual(jv.usage_chip(r, BRIEF, report('Usage: 200 tool calls; models: opus, sonnet; x')), ('usage 200 / 160 calls · opus, sonnet', False))

    def test_over_is_flagged(self):
        self.assertEqual(jv.usage_chip(row(), BRIEF, report('Usage: 126 tool calls; models: opus; x')), ('usage 126 / 100 calls · opus', True))

    def test_no_budget(self):
        self.assertEqual(jv.usage_chip(row(), None, report()), ('usage 100 calls · opus', False))

    def test_missing_or_broken_draws_nothing(self):
        self.assertIsNone(jv.usage_chip(row(), BRIEF, None))
        self.assertIsNone(jv.usage_chip(row(), BRIEF, REPORT))
        self.assertIsNone(jv.usage_chip(row(), BRIEF, report('Usage: lots')))


class Cards(unittest.TestCase):
    ROWS = [row('J1', status='queued', brief='jobs/J1/brief.md'), row('J2', status='review', brief='jobs/J2/brief.md', report='jobs/J2/report.md')]

    def page(self, *results, reports=None):
        docs = {'jobs/J1/brief.md': BRIEF.replace('J5', 'J1'), 'jobs/J2/brief.md': BRIEF.replace('J5', 'J2'), **(reports or {})}
        with mock.patch.object(jv.gatemods, 'run_stage', return_value=list(results)):
            return jv.render_view(self.ROWS, docs.get, set(), 'now', ctx=object())

    def card(self, page, jid):
        return page[page.index(f'<article class="card" id="{jid}"'):].split('</article>')[0]

    def test_a_line_lands_on_its_own_card_under_the_meta_line_escaped(self):
        p = self.page(Result('u', 'ok', '', cards={'J2': 'a <b> & c'}))
        self.assertIn('a &lt;b&gt; &amp; c', self.card(p, 'J2'))
        self.assertNotIn('a &lt;b&gt;', self.card(p, 'J1'))
        c = self.card(p, 'J2')
        self.assertLess(c.index('class="meta"'), c.index('a &lt;b&gt;'))

    def test_html_is_drawn_as_is_only_when_asked_for(self):
        self.assertIn('<i>mine</i>', self.card(self.page(Result('u', 'ok', '', cards={'J2': {'html': '<i>mine</i>'}})), 'J2'))

    def test_every_module_gets_its_line(self):
        c = self.card(self.page(Result('a', 'ok', '', cards={'J2': 'first'}), Result('b', 'ok', '', cards={'J2': 'second'})), 'J2')
        self.assertLess(c.index('first'), c.index('second'))

    def test_an_unknown_id_is_ignored(self):
        self.assertNotIn('ghost', self.page(Result('u', 'ok', '', cards={'J9': 'ghost'})))

    def test_malformed_cards_never_fail_the_page(self):
        for bad in ('not a dict', None, 5, ['J2']):
            r = Result('u', 'ok', '')
            r.cards = bad
            self.assertIn('id="J2"', self.page(r))
        self.assertIn('id="J2"', self.page(Result('u', 'ok', '', cards={'J1': 5, 'J2': {'html': 7}})))

    def test_a_cards_only_result_draws_no_panel(self):
        self.assertEqual(jv.panel_html(Result('u', 'ok', '', cards={'J2': 'x'})), '')

    def test_the_chip_is_drawn_from_the_report(self):
        p = self.page(reports={'jobs/J2/report.md': report().replace('J5', 'J2')})
        c = self.card(p, 'J2')
        self.assertIn('<p class="usage">usage 100 / 100 calls · opus</p>', c)
        self.assertLess(c.index('class="meta"'), c.index('class="usage"'))
        self.assertNotIn('class="usage', self.card(p, 'J1'))

    def test_over_budget_is_red(self):
        p = self.page(reports={'jobs/J2/report.md': report('Usage: 126 tool calls; models: opus; x').replace('J5', 'J2')})
        self.assertIn('<p class="usage over">usage 126 / 100 calls · opus</p>', self.card(p, 'J2'))

    def test_a_chip_needs_no_gate_context(self):
        docs = {'jobs/J2/brief.md': BRIEF.replace('J5', 'J2'), 'jobs/J2/report.md': report().replace('J5', 'J2')}
        self.assertIn('class="usage"', self.card(jv.render_view(self.ROWS, docs.get, set(), 'now'), 'J2'))


class Steps(Rule):
    def test_finish_says_to_fill_the_line_once_the_rule_is_on(self):
        with mock.patch.object(jv.S, 'usage_cmd', 'tool {id}', create=True):
            self.assertIn('jobs usage J5 --write', jv.build_steps(row(status='queued'), sha='abc1234'))
            self.assertIn('jobs usage J5 --write', jv.fix_steps('J5', 1))
            self.assertNotIn('jobs usage', jv.build_steps(row('J4', status='queued'), sha='abc1234'))
            self.assertNotIn('jobs usage', jv.fix_steps('J4', 1))

    def test_with_no_command_it_says_the_hand_route(self):
        with mock.patch.object(jv.S, 'usage_cmd', '', create=True):
            self.assertIn('jobs usage J5 --write --from-json <file>', jv.build_steps(row(status='queued'), sha='abc1234'))


if __name__ == '__main__':
    unittest.main()
