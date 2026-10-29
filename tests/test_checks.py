import unittest

from _util import CORE
from warscape import checks
from warscape.repo import DEFAULTS, glob_to_re, matches


class Globs(unittest.TestCase):
    def test_star_stays_in_a_segment_double_star_spans(self):
        self.assertTrue(matches('a.md', ['**/*.md']))
        self.assertTrue(matches('docs/x/a.md', ['**/*.md']))
        self.assertFalse(matches('docs/a.md', ['*.md']))
        self.assertTrue(matches('docs/runs/x/y.md', ['**/runs/**']))
        self.assertFalse(matches('docs/reruns/y.md', ['**/runs/**']))
        self.assertTrue(glob_to_re('warscape/*.py').match('warscape/cli.py'))
        self.assertFalse(glob_to_re('warscape/*.py').match('warscape/verbs/reg.py'))


class WindowsPaths(unittest.TestCase):
    def test_reserved_bad_chars_trailing_and_case(self):
        errs = checks.windows_path_errors(['ok/a.txt', 'x/con.txt', 'x/AUX', 'x/lpt9.log', 'a:b.md', 'q?.md', 'trail./x', 'sp /x',
                                           'Docs/A.md', 'docs/b.md', 'f.MD', 'f.md', 'back\\slash'])
        bad = '\n'.join(errs)
        for p in ('x/con.txt', 'x/AUX', 'x/lpt9.log', 'a:b.md', 'q?.md', 'trail./x', 'sp /x', 'back\\slash'):
            self.assertIn(p, bad)
        self.assertIn('case clash: f.MD / f.md', bad)
        self.assertIn('folder Docs/ / docs/', bad)
        self.assertNotIn('ok/a.txt', bad)
        self.assertEqual(checks.windows_path_errors(['console.txt', 'com10.txt', 'nul_thing.md']), [])


class StrictJson(unittest.TestCase):
    def test_strict(self):
        self.assertIsNone(checks.strict_json_error('{"a": [1, 2.5, null]}'))
        self.assertIn('non-finite', checks.strict_json_error('{"a": NaN}'))
        self.assertIn('non-finite', checks.strict_json_error('[Infinity]'))
        self.assertIsNotNone(checks.strict_json_error('{"a": 1,}'))
        self.assertIn('byte-order', checks.strict_json_error('﻿{}'))
        self.assertIsNotNone(checks.strict_json_error('{} {}'))

    def test_jsonl(self):
        self.assertIsNone(checks.strict_json_error('{"a": 1}\n\n{"b": 2}\n', jsonl=True))
        self.assertTrue(checks.strict_json_error('{"a": 1}\n{"b": -Infinity}\n', jsonl=True).startswith('line 2'))


class Conflicts(unittest.TestCase):
    def test_full_trio_only(self):
        self.assertEqual(checks.has_conflict_trio('a\n<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> b\n'), 2)
        self.assertEqual(checks.has_conflict_trio('=======\nheading rule\n'), 0)
        self.assertEqual(checks.has_conflict_trio('quote: <<<<<<< HEAD only\n'), 0)


class Docs(unittest.TestCase):
    def test_living_docs_exempt_records_dates_and_generated(self):
        paths = ['README.md', 'docs/PLAN.md', 'docs/reports/x.md', 'docs/2026-10-28_retro.md', 'docs/RETRO_20261023.md',
                 'registries/tools.md', 'notes.txt', 'runs/a/b.md']
        got = checks.living_docs(paths, DEFAULTS['docs'], ['registries/tools.md'])
        self.assertEqual(got, ['README.md', 'docs/PLAN.md'])

    def test_size_cap_is_kib(self):
        self.assertEqual(checks.oversize({'a.md': 30 * 1024, 'b.md': 30 * 1024 + 1}, 30), [('b.md', 30 * 1024 + 1)])
        self.assertEqual(checks.oversize({'a.md': 600}, 0.5), [('a.md', 600)])

    def test_core_docs_are_within_the_cap_and_dated(self):
        for p in ('README.md', 'CLAUDE.md', 'docs/DECISIONS.md'):
            text = (CORE / p).read_text(encoding='utf-8')
            self.assertLess(len(text.encode('utf-8')), 30 * 1024, p)
            self.assertEqual(checks.undated_verified(text.split('\n')), [], p)


def flagged(text):
    return checks.undated_verified(text.split('\n'))


class VerifiedDates(unittest.TestCase):
    """Ported from empire-remastered orchestrator/tools/test_verified_dates.py (2026-10-28)."""

    def test_plain_claim_flagged(self):
        self.assertEqual(flagged('a\nThe port was verified in game.\nb'), [2])

    def test_dated_or_run_id_clears(self):
        self.assertEqual(flagged('Verified 2026-10-27, orchestrator/reports/x.md'), [])
        self.assertEqual(flagged('verified in game (runs/20261026_a)'), [])

    def test_table_inherits_caption_and_header(self):
        cap = '- **Parity (in game 2026-10-24, run x):**\n\n| a | b | Status |\n|---|---|---|\n| row | ok | verified |\n'
        self.assertEqual(flagged(cap), [])
        hdr = 'text\n\n| a | Status (2026-10-24) |\n|---|---|\n| row | verified |\n'
        self.assertEqual(flagged(hdr), [])
        bare = '**Parity table**\n\n| a | Status |\n|---|---|\n| row | verified |\n'
        self.assertEqual(flagged(bare), [5])

    def test_long_paragraph_is_not_a_caption(self):
        para = ('x ' * 200) + '2026-10-24\n\n| a | Status |\n|---|---|\n| row | verified |\n'
        self.assertEqual(flagged(para), [5])

    def test_dated_caption_does_not_leak_to_next_table(self):
        two = 'cap 2026-10-24\n| a |\n|---|\n| verified |\n\nplain text\n\n| b |\n|---|\n| verified |\n'
        self.assertEqual(flagged(two), [10])

    def test_wrapped_list_item_is_one_statement(self):
        self.assertEqual(flagged('- 2026-10-21: sky run\n  proxy relay\n  verified (AV == cube).\n\nverified.'), [5])
        self.assertEqual(flagged('- plain item\n  verified (x)\n- 2026-10-21: other item'), [2])

    def test_code_fence_is_skipped(self):
        self.assertEqual(flagged('```\n// the verified 1:1 port\nOK verified.\n```\nverified.'), [5])

    def test_non_claims(self):
        for l in ('sha-verified copy', 'sha256 verified against the values', 'Legend: **[V]** verified from a repo artefact',
                  'not yet verified', '**Not** verified: anything', 'Nothing has been verified in game yet',
                  'A "verified" line needs a date', 'to be verified later', 'must be re-verified', 'until step 3 is verified',
                  'what I verified', 'the verified vanilla body', 'verified ports and verified hooks', 'the `verified` field'):
            self.assertEqual(flagged(l), [], l)

    def test_claims_with_function_word_or_end_are_kept(self):
        for l in ('verified.', 'verified in game', 'all four verified 0 px', '| x | verified |', 'verified by the user', 'verified live'):
            self.assertEqual(flagged(l), [1], l)



class CorePin(unittest.TestCase):
    """backlog B5: the pin is checked against the tag, not only VERSION; tags are `vX.Y.Z`, lower-case v."""
    def test_pin_matches_tag_and_version(self):
        from warscape.gates import pin_problems
        self.assertEqual(pin_problems('v0.1.0', '0.1.0', ['v0.1.0'], True), [])
        self.assertEqual(pin_problems('v0.1.0', '0.1.0', [], False), [])            # shallow CI checkout: no tags, VERSION only

    def test_bad_pins_fail(self):
        from warscape.gates import pin_problems
        self.assertTrue(any('lower-case v' in e for e in pin_problems('V0.1.0', '0.1.0', ['V0.1.0'], True)))
        self.assertTrue(any('not the pinned tag v0.1.0' in e for e in pin_problems('v0.1.0', '0.1.0', ['V0.1.0'], True)))
        self.assertTrue(any('untagged commit' in e for e in pin_problems('v0.1.0', '0.1.0', [], True)))
        self.assertTrue(any('checkout is 0.2.0' in e for e in pin_problems('v0.1.0', '0.2.0', ['v0.1.0'], True)))

    def test_core_tags_match_version(self):
        from warscape.gates import core_tag_problems
        self.assertEqual(core_tag_problems('0.1.0', ['v0.1.0']), [])
        self.assertEqual(core_tag_problems('0.1.0', []), [])
        self.assertEqual(len(core_tag_problems('0.1.0', ['V0.1.0'])), 1)
        self.assertEqual(len(core_tag_problems('0.1', [])), 1)


if __name__ == '__main__':
    unittest.main()
