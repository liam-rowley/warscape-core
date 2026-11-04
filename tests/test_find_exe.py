"""`wsc find` hands exe-shaped words to the game's exe string index (W15, backlog B43; decision 4 of the brief)."""
import json
import sys
import unittest

from _util import CORE, MINIMAL_TOML, TempRepo

sys.path.insert(0, str(CORE / 'discovery'))
import exe_strings  # noqa: E402
import tsvgz  # noqa: E402

from warscape.verbs import find  # noqa: E402

TOML = MINIMAL_TOML + '[discovery]\nadapter = "discovery/game"\n'
ROWS = [
    ('0x0001000', '.rdata', 'a', '20', '2', '0x0000100 0x0000200', '0', '', 'gfx_hardware_shadows'),
    ('0x0001020', '.rdata', 'a', '24', '0', '', '1', '0x0002000', 'gfx_hardware_shadows_max'),
    ('0x0001040', '.rdata', 'u', '10', '1', '0x0000300', '0', '', 'CampaignUI'),
    ('0x0001060', '.data', 'a', '6', '0', '', '0', '', 'shadow'),
]
TOOL = '''#!/usr/bin/env python3
# purpose: Tune shadow quality for the tests.
# usage: python3 shadows.py
# when: in tests only.
# not-a-verb: a test fixture.
'''


class Shape(unittest.TestCase):
    def test_exe_shaped(self):
        for w in ('gfx_hardware_shadows', 'CampaignUI', 'get_character_by_cqi', 'a_b1', 'isOK'):
            self.assertTrue(find.exe_shaped(w), w)
        for w in ('shadow', 'Shadow', 'SHADOW', '_ab_', 'a_b', 'gfx.dist.trees', 'x__', 'ab-cd', '1a_b', 'UI'):
            self.assertFalse(find.exe_shaped(w), w)


class FindExe(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo({'discovery/game/games.json': '{"target": "alpha", "reference": "beta"}\n', 'shadows.py': TOOL}, toml=TOML)
        self.addCleanup(self.repo.close)
        tsvgz.write(str(self.repo.root / 'discovery/game/exe_strings.tsv.gz'), exe_strings.HEADER, ROWS)
        self.assertEqual(self.repo.wsc('reg', 'add', 'tools', 'shadows.py')[0], 0)

    def test_an_exe_shaped_word_prints_the_exe_block(self):
        rc, out = self.repo.wsc('find', 'gfx_hardware_shadows')
        self.assertEqual(rc, 0, out)
        self.assertIn('exe strings (discovery/game/exe_strings.tsv.gz): 2 hits', out)
        self.assertIn(exe_strings.line(ROWS[0]), out)
        self.assertIn("'gfx_hardware_shadows_max'", out)
        self.assertNotIn('no matches', out)             # an exe-only hit is a hit

    def test_words_are_anded_case_insensitively_as_literals(self):
        rc, out = self.repo.wsc('find', 'GFX_hardware', 'shadows_MAX')
        self.assertIn('exe strings (discovery/game/exe_strings.tsv.gz): 1 hits', out)
        rc, out = self.repo.wsc('find', 'campaignUI')
        self.assertIn("'CampaignUI'", out)

    def test_a_plain_word_does_not_search_the_table_unless_forced(self):
        rc, out = self.repo.wsc('find', 'shadow')
        self.assertEqual(rc, 0, out)
        self.assertIn('shadows', out)
        self.assertNotIn('exe strings', out)
        rc, out = self.repo.wsc('find', '--exe', 'shadow')
        self.assertIn('exe strings (discovery/game/exe_strings.tsv.gz): 3 hits', out)

    def test_in_names_where_to_search(self):
        rc, out = self.repo.wsc('find', 'gfx_hardware_shadows', '--in', 'tools')
        self.assertNotIn('exe strings', out)
        self.assertEqual(rc, 1, out)
        rc, out = self.repo.wsc('find', 'shadow', '--in', 'exe_strings')
        self.assertEqual(rc, 0, out)
        self.assertIn('exe strings (discovery/game/exe_strings.tsv.gz): 3 hits', out)
        self.assertNotIn('shadows.py', out)
        self.assertNotIn('no matches', out)

    def test_the_limit_cuts_and_says_how_to_see_more(self):
        rc, out = self.repo.wsc('find', '--exe', 'a', '-n', '1')
        self.assertIn('exe strings (discovery/game/exe_strings.tsv.gz): 4 hits', out)
        self.assertIn('... 3 more (wsc find --exe a -n 4)', out)

    def test_json(self):
        rc, out = self.repo.wsc('find', 'CampaignUI', '--json')
        self.assertEqual(rc, 0, out)
        rows = [json.loads(x) for x in out.splitlines() if x.startswith('{')]
        self.assertEqual(rows, [{'registry': 'exe_strings', 'row': dict(zip(exe_strings.HEADER, ROWS[2]))}])

    def test_exit_1_when_neither_has_a_hit(self):
        rc, out = self.repo.wsc('find', 'nothing_like_this')
        self.assertEqual(rc, 1, out)
        self.assertIn('no matches', out)
        self.assertIn('exe strings (discovery/game/exe_strings.tsv.gz): 0 hits', out)


class NoTable(unittest.TestCase):
    def test_no_adapter_is_silent_and_exe_names_the_fix(self):
        repo = TempRepo({'shadows.py': TOOL})
        self.addCleanup(repo.close)
        repo.wsc('reg', 'add', 'tools', 'shadows.py')
        rc, out = repo.wsc('find', 'gfx_hardware_shadows')
        self.assertEqual(rc, 1, out)
        self.assertNotIn('exe', out)
        rc, out = repo.wsc('find', 'shadow')
        self.assertEqual(rc, 0, out)
        self.assertNotIn('exe', out)
        rc, out = repo.wsc('find', '--exe', 'shadow')
        self.assertIn('exe_strings.py build <exe> --out', out)
        self.assertIn('discovery/re_env.py', out)

    def test_an_adapter_without_a_table_is_silent(self):
        repo = TempRepo({'discovery/game/games.json': '{}\n'}, toml=TOML)
        self.addCleanup(repo.close)
        rc, out = repo.wsc('find', 'gfx_hardware_shadows')
        self.assertEqual(rc, 1, out)
        self.assertNotIn('exe', out)


class CoreCheckout(unittest.TestCase):
    def test_find_in_the_core_prints_no_exe_block(self):
        import contextlib
        import io
        from warscape.cli import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main(['--root', str(CORE), 'find', 'reg_remove', 'last_used'])
        self.assertNotIn('exe strings', out.getvalue())
        self.assertIn(rc, (0, 1))


if __name__ == '__main__':
    unittest.main()
