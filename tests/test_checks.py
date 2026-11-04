import unittest

from _util import CORE
from warscape import checks
from warscape.repo import DEFAULTS, glob_to_re, load_config, matches


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

    def test_duplicate_keys_are_refused(self):
        """W28: last-one-wins is a silent data loss; a key twice in one object is refused, nested too, and per line in JSON Lines."""
        self.assertIn("duplicate key 'a'", checks.strict_json_error('{"a": 1, "a": 2}'))
        self.assertIn("duplicate key 'k'", checks.strict_json_error('{"x": [{"k": 1, "k": 1}]}'))
        self.assertIsNone(checks.strict_json_error('{"a": {"a": 1}, "b": [{"a": 2}]}'))   # the same key in different objects is fine
        self.assertEqual(checks.strict_json_error('{"a": 1}\n{"b": 1, "b": 2}\n', jsonl=True), "line 2: duplicate key 'b'")
        with self.assertRaises(ValueError):
            checks.strict_loads('{"a": 1, "a": 1}')

    def test_json_gate_refuses_a_duplicate_key(self):
        from _util import TempRepo
        repo = TempRepo({'data/x.json': '{"a": 1, "a": 2}\n'})
        self.addCleanup(repo.close)
        rc, out = repo.wsc('gates', '--only', 'json')
        self.assertNotEqual(rc, 0, out)
        self.assertIn("data/x.json: duplicate key 'a'", out)


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

    def test_only_a_date_or_run_id_dates_a_claim(self):
        """W28: the loose alternatives (`\\d-\\d\\d`, 'session', '.md)', 'v<digit>') no longer pass; the case of "verified" does not matter."""
        for l in ('VERIFIED on PC', 'verified in session', 'verified 3-10 times', 'verified (see x.md)', 'verified in v2'):
            self.assertEqual(flagged(l), [1], l)
        for l in ('verified 2026-11-04', 'verified, run 20261104_a', 'verified in game (docs/reports/x.md)', 'verified, see [run](records/r.md)'):
            self.assertEqual(flagged(l), [], l)



class CorePin(unittest.TestCase):
    """backlog B5: the pin is checked against the tag, not only VERSION; tags are `vX.Y.Z`, lower-case v."""
    # pin_problems(want, version, pin_commit, head, shallow, any_tags, head_tags): A and B are commits
    def test_pin_matches_tag_and_version(self):
        from warscape.gates import pin_problems
        self.assertEqual(pin_problems('v0.1.0', '0.1.0', 'A', 'A', False, True, ['v0.1.0']), [])
        self.assertEqual(pin_problems('v0.1.0', '0.1.0', None, 'A', False, False), [])          # no tags at all: VERSION only
        self.assertEqual(pin_problems('v0.1.0', '0.1.0', 'A', 'A', True, True, ['v0.1.0']), [])  # shallow with the tag fetched

    def test_bad_pins_fail(self):
        from warscape.gates import pin_problems
        self.assertTrue(any('lower-case v' in e for e in pin_problems('V0.1.0', '0.1.0', 'A', 'A', False, True, ['V0.1.0'])))
        self.assertTrue(any('not the pinned tag v0.1.0' in e for e in pin_problems('v0.1.0', '0.1.0', 'A', 'B', False, True, ['V0.1.0'])))
        self.assertTrue(any('untagged commit' in e for e in pin_problems('v0.1.0', '0.1.0', 'A', 'B', False, True)))
        self.assertTrue(any('checkout is 0.2.0' in e for e in pin_problems('v0.1.0', '0.2.0', 'A', 'A', False, True, ['v0.1.0'])))

    def test_shallow_rule(self):
        """core W11 (B12): a present tag is always checked against HEAD; a missing one is VERSION only in a shallow checkout and nowhere else."""
        from warscape.gates import pin_check, pin_problems
        self.assertEqual([pin_check('A', True, True), pin_check(None, True, True), pin_check(None, False, True), pin_check(None, False, False)],
                         ['tag', 'shallow', 'missing', 'none'])
        self.assertEqual(pin_problems('v0.1.0', '0.1.0', None, 'A', True, True, ['v0.2.0']), [])        # depth-1 CI submodule
        self.assertTrue(any('untagged commit' in e for e in pin_problems('v0.1.0', '0.1.0', 'A', 'B', True, True)))
        self.assertTrue(any('checkout is 0.2.0' in e for e in pin_problems('v0.1.0', '0.2.0', None, 'A', True, True)))
        miss = pin_problems('v0.1.0', '0.1.0', None, 'A', False, True, ['v0.2.0'], core_dir='vendor/core')
        self.assertTrue(any('git -C vendor/core fetch --tags' in e for e in miss), miss)

    def test_core_tags_match_version(self):
        from warscape.gates import core_tag_problems
        self.assertEqual(core_tag_problems('0.1.0', ['v0.1.0']), [])
        self.assertEqual(core_tag_problems('0.1.0', []), [])
        self.assertEqual(len(core_tag_problems('0.1.0', ['V0.1.0'])), 1)
        self.assertEqual(len(core_tag_problems('0.1', [])), 1)



def third_party_imports(text, local=('warscape', '_util')):
    """Top-level modules a Python source imports that are neither the standard library nor this repo's own (C2)."""
    import ast
    import sys
    out = set()
    for n in ast.walk(ast.parse(text)):
        names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module] if isinstance(n, ast.ImportFrom) and not n.level else []
        out |= {m.split('.')[0] for m in names if m and m.split('.')[0] not in sys.stdlib_module_names and m.split('.')[0] not in local}
    return sorted(out)


class StdlibOnly(unittest.TestCase):
    """C2 / CLAUDE.md: standard library only. A dependency needs a dated decision first, then an entry in `local` here."""
    def test_fixture(self):
        self.assertEqual(third_party_imports('import json, os.path\nfrom warscape import x\nfrom . import y\n'), [])
        self.assertEqual(third_party_imports('import yaml\nfrom requests.adapters import X\n'), ['requests', 'yaml'])

    def test_core_sources_are_stdlib_only(self):
        files = [CORE / 'wsc.py', *sorted((CORE / 'warscape').rglob('*.py')), *sorted((CORE / 'tests').glob('*.py'))]
        bad = {str(f.relative_to(CORE)): m for f in files if (m := third_party_imports(f.read_text(encoding='utf-8')))}
        self.assertEqual(bad, {})


class TestsGateSkips(unittest.TestCase):
    """The tests gate shows skips (napoleon J41): a skipped host test is a `warn` with its reason, never a silent pass."""
    def test_real_unittest_output(self):
        import subprocess, sys, tempfile
        from pathlib import Path
        from warscape import gates
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'test_x.py').write_text('\n'.join([
                'import unittest', 'class A(unittest.TestCase):',
                '    def test_plain(self):', '        self.skipTest("no toolchain: test_console")',
                '    def test_doc(self):', '        """Has a docstring."""', '        self.skipTest("docker down")',
                '    def test_ok(self):', '        pass', '']), encoding='utf-8')
            p = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-v', '-s', d, '-t', d], capture_output=True, text=True)
        skips = gates.unittest_skips((p.stdout + p.stderr).splitlines())
        self.assertEqual(sorted(skips), ['A.test_doc: docker down', 'A.test_plain: no toolchain: test_console'])

    def test_both_id_formats(self):
        from warscape import gates
        self.assertEqual(gates.unittest_skips(["test_a (m.C.test_a) ... skipped 'r1'", "test_b (m.C) ... skipped 'r2'", 'test_c (m.C.test_c) ... ok']),
                         ['C.test_a: r1', 'C.test_b: r2'])


class DocPaths(unittest.TestCase):
    """W28 (R11): a backticked repo path in a living doc must exist."""
    TRACKED = ['README.md', 'docs/GUIDE.md', 'docs/img/a.png', 'warscape/gates.py', 'core/wsc.py']

    def stale(self, text, doc='docs/GUIDE.md', ignore=()):
        return checks.stale_doc_paths({doc: text}, checks.run_ref_index(self.TRACKED)[0], ignore)

    def test_a_stale_token_is_flagged_with_its_line(self):
        self.assertEqual(self.stale('ok\nsee `warscape/gone.py` and `warscape/gates.py:12`\n'), ['docs/GUIDE.md:2: path not found: warscape/gone.py'])

    def test_existing_paths_are_not_flagged(self):
        for tok in ('warscape/gates.py', 'warscape/', 'docs/img/', 'img/a.png', 'core/warscape/gates.py', 'core/wsc.py',
                    'warscape/gates.py#L3', './warscape/gates.py'):
            self.assertEqual(self.stale(f'`{tok}`'), [], tok)
        self.assertEqual(self.stale('`core/wsc.py` and `warscape/gates.py`', doc='README.md'), [])

    def test_the_release_branch_pattern_is_not_a_path_in_the_core(self):
        """W28 + W29 turned main red: `.Z` makes the branch pattern look like a file. The core ignores that exact token, not `release/` paths."""
        ignore = load_config(CORE)['docs']['path_ignore']
        self.assertEqual(self.stale('`release/vX.Y.Z`'), ['docs/GUIDE.md:1: path not found: release/vX.Y.Z'])
        self.assertEqual(self.stale('`release/vX.Y.Z`', ignore=ignore), [])
        self.assertEqual(self.stale('`release/notes.md`', ignore=ignore), ['docs/GUIDE.md:1: path not found: release/notes.md'])

    def test_placeholders_commands_ignored_tokens_and_records_are_not_flagged(self):
        for tok in ('jobs/<id>/brief.md', 'docs/*.md', '{a,b}/x.py', '$HOME/x.py', '~/x.py', 'https://x.org/a.py', 'C:/x/y.py',
                    'python3 tools/x.py', 'origin/main', 'job/W28', 'actions/cache'):
            self.assertEqual(self.stale(f'`{tok}`'), [], tok)
        self.assertEqual(self.stale('`plan/` and `tools/x.py`', ignore=['plan/', 'tools/*']), [])
        self.assertEqual(self.stale('`tools/x.py` (was `tools/y.py`)\n`a/b.py` (moved)\n```\n`c/d.py`\n```\n'), [])


class RunRefs(unittest.TestCase):

    """B13: the rule behind the `run_refs` gate, on plain inputs."""

    def test_which_files_are_run_readmes(self):
        self.assertEqual(checks.run_readmes(['harness/runs/20261102_a/README.md', 'runs/README.md', 'docs/README.md', 'runs/x/NOTES.md', 'reruns/x/README.md']),
                         ['harness/runs/20261102_a/README.md', 'runs/README.md'])

    def test_tokens_links_and_backticks_that_look_like_paths(self):
        text = ('See [the log](logs/run.log#L3) and `harness/ctl.py:12`, `probes/x.lua`, `dir/`, [sibling](notes.md), `../up/y.md`.\n'
                'Not paths: [web](https://a.b/c.md) `https://a.b/c.md` `/abs/x.txt` `C:/x/y.txt` `%APPDATA%/x.txt` `$HOME/x.txt` `~/x.txt` `back\\slash.txt` '
                '`raw/chain1..3/` `glob/*.txt` `a/<b>.txt` `a/{b,c}.txt` `python3 x/y.py a` `a/b` `word` `file.txt` `--out=x/y.txt`.\n'
                '```\n`in/fence.txt`\n```\n')
        self.assertEqual([t for _, t in checks.run_ref_tokens(text)],
                         ['logs/run.log', 'harness/ctl.py', 'probes/x.lua', 'dir/', 'notes.md', '../up/y.md'])
        self.assertEqual(checks.run_ref_tokens('a\nb `x/y.txt`.')[0], (2, 'x/y.txt'))

    def test_found_from_the_root_the_readme_a_suffix_or_an_ignored_path(self):
        readme = 'adapter/runs/20261105_a/README.md'
        index = checks.run_ref_index(['logs/a.log', 'adapter/runs/20261105_a/raw.log', 'adapter/probes/x.lua', 'core/harness/ctl.py', 'adapter/data/q.json'])
        found = lambda tok, ign=None: checks.run_ref_found(tok, readme, index, ign)
        self.assertTrue(found('logs/a.log'))                 # from the root
        self.assertTrue(found('raw.log'))                    # from the README's folder
        self.assertTrue(found('probes/x.lua'))               # the tail of a tracked file
        self.assertTrue(found('harness/ctl.py'))             # a file inside a submodule (the index lists it)
        self.assertTrue(found('data/'))                      # the tail of a tracked folder
        self.assertFalse(found('logs/missing.log'))
        self.assertFalse(found('../../../../etc/x.log'))
        self.assertTrue(found('build/out.dll', lambda p: p == 'build/out.dll'))

    def test_problems_name_the_readme_and_the_line_and_grandfathering_skips_old_runs(self):
        index = checks.run_ref_index(['logs/a.log'])
        readmes = {'runs/20261028_old/README.md': 'x\n`logs/gone.log`\n', 'runs/2026-11-03_new/README.md': 'x\ny `logs/a.log` `logs/gone.log`\n',
                   'runs/nodate/README.md': '`logs/gone.log`\n'}
        errs, checked, skipped = checks.run_ref_problems(readmes, index)
        self.assertEqual((len(errs), checked, skipped), (3, 4, 0))
        errs, checked, skipped = checks.run_ref_problems(readmes, index, since='2026-11-03')
        self.assertEqual((checked, skipped), (3, 1))
        self.assertEqual(sorted(e.split(': names ')[0] for e in errs), ['runs/2026-11-03_new/README.md:2', 'runs/nodate/README.md:1'])
        self.assertEqual(checks.run_folder_date('runs/20261028_old/README.md'), '2026-10-28')
        self.assertIsNone(checks.run_folder_date('runs/README.md'))


if __name__ == '__main__':
    unittest.main()
