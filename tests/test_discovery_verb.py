"""Host tests for the `discovery` verb's wiring (W4): the [discovery] adapter table, layout.discovery_adapter(), and `wsc discovery render|check`
on a throwaway game with made-up names. The passes' own logic is tested in discovery/tests/."""
import importlib.util
import json
import os
import subprocess
import sys
import unittest

from _util import CORE, TempRepo
from warscape.repo import ConfigError, load_config


def _layout():
    spec = importlib.util.spec_from_file_location('layout_w4', CORE / 'proxy' / 'tools' / 'layout.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AREAS = ('packs', 'layouts', 'fonts', 'lua_api', 'shaders', 'exe')


def diff_doc(area, ref='beta', tgt='alpha'):
    row = {'item': 'x', ref: '1', tgt: '2', 'verdict': 'new', 'adapter': '', 'evidence': 'e'}
    return json.dumps({'schema': 1, 'area': area, 'rows': [row], 'detail': {}}, indent=1, sort_keys=True) + '\n'


class Config(unittest.TestCase):
    def test_the_discovery_table_is_accepted_and_an_unknown_key_is_refused(self):
        r = TempRepo()
        try:
            r.write('wsc.toml', r.read('wsc.toml') + '\n[discovery]\nadapter = "discovery/alpha"\n')
            self.assertEqual(load_config(r.root)['discovery']['adapter'], 'discovery/alpha')
            r.write('wsc.toml', r.read('wsc.toml') + 'adaptr = "x"\n')
            with self.assertRaises(ConfigError) as e:
                load_config(r.root)
            self.assertIn("unknown key 'discovery.adaptr'", str(e.exception))
        finally:
            r.close()


class Layout(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.pop('WSP_DISCOVERY_ADAPTER', None)
        self.lay = _layout()
        self.r = TempRepo({'discovery/a/games.json': '{}'})

    def tearDown(self):
        self.r.close()
        if self.saved is not None:
            os.environ['WSP_DISCOVERY_ADAPTER'] = self.saved

    def test_one_adapter_is_found_two_are_named_and_the_table_picks_one(self):
        self.assertEqual(self.lay.discovery_adapter(self.r.root), self.r.root / 'discovery' / 'a')
        self.r.write('discovery/b/games.json', '{}')
        with self.assertRaises(self.lay.LayoutError) as e:
            self.lay.discovery_adapter(self.r.root)
        self.assertIn('discovery/a/games.json, discovery/b/games.json', str(e.exception))
        self.r.write('wsc.toml', self.r.read('wsc.toml') + '\n[discovery]\nadapter = "discovery/b"\n')
        self.assertEqual(self.lay.discovery_adapter(self.r.root), self.r.root / 'discovery' / 'b')
        os.environ['WSP_DISCOVERY_ADAPTER'] = str(self.r.root)
        try:
            self.assertEqual(self.lay.discovery_adapter(self.r.root), self.r.root)
        finally:
            del os.environ['WSP_DISCOVERY_ADAPTER']


class Verb(unittest.TestCase):
    def setUp(self):
        self.r = TempRepo({'discovery/alpha/games.json': json.dumps({'target': 'alpha', 'reference': 'beta'}),
                           'discovery/alpha/carry_over.json': json.dumps({'families': [{'family': 'f', 'verdict': 'same', 'note': 'n'}]})})
        self.r.write('wsc.toml', self.r.read('wsc.toml') + '\n[discovery]\nadapter = "discovery/alpha"\n')

    def tearDown(self):
        self.r.close()

    def wsc(self, *a):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('WSP_', 'GIT_'))}
        p = subprocess.run([sys.executable, str(CORE / 'wsc.py'), *a], cwd=self.r.root, capture_output=True, text=True, env=env)
        return p.returncode, p.stdout + p.stderr

    def test_render_names_the_games_from_games_json(self):
        for a in AREAS:
            self.r.write(f'discovery/diff/{a}.json', diff_doc(a))
        rc, out = self.wsc('discovery', 'render')
        self.assertEqual(rc, 0, out)
        text = self.r.read('discovery/diff/README.md')
        self.assertIn('# Beta to Alpha diff (J6)', text)
        self.assertIn('| Area | Item | Beta | Alpha | Verdict |', text)
        self.assertIn('`discovery/alpha/carry_over.json`', text)

    def test_check_refuses_a_diff_row_that_does_not_carry_the_games_names(self):
        for a in AREAS:
            self.r.write(f'discovery/diff/{a}.json', diff_doc(a, 'one', 'two'))
        rc, out = self.wsc('discovery', 'check')
        self.assertEqual(rc, 1, out)
        self.assertIn("want ['adapter', 'alpha', 'beta', 'evidence', 'item', 'verdict']", out)


if __name__ == '__main__':
    unittest.main()
