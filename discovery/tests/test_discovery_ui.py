"""Host tests for the J10 UI atlas: the script walk (ui_walk.py) and the atlas helpers (ui_atlas.py) on synthetic fixtures."""
import gzip
import hashlib
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'discovery', 'core'))
sys.path.insert(0, os.path.join(ROOT, 'core', 'proxy', 'tools'))
import luachunk  # noqa: E402
import ui_atlas  # noqa: E402
import ui_walk  # noqa: E402
from luachunk import enc  # noqa: E402

TABLES = ['BattleUI', 'CampaignUI', 'Component', 'FrontEnd']


def _func(k, code, protos=(), locals_=(), nparams=0, nups=0):
    f = luachunk.Func()
    f.k = [('str', s.encode()) for s in k]
    f.code, f.protos, f.locals, f.upvals, f.nparams, f.nups = list(code), list(protos), list(locals_), [], nparams, nups
    return f


def _chunk():
    """local d = CampaignUI.RetrieveDetails(); x = d.Name; function OnClick() CampaignUI.EndTurn() end"""
    k = ['CampaignUI', 'RetrieveDetails', 'Name', 'x', 'OnClick', 'EndTurn']
    on_click = _func(k, [enc('GETGLOBAL', 0, bx=0), enc('GETTABLE', 0, 0, 256 + 5), enc('CALL', 0, 1, 1), enc('RETURN', 0, 1)])
    return _func(k, [enc('GETGLOBAL', 0, bx=0), enc('GETTABLE', 0, 0, 256 + 1), enc('CALL', 0, 1, 2),
                     enc('GETTABLE', 1, 0, 256 + 2), enc('SETGLOBAL', 1, bx=3),
                     enc('CLOSURE', 2, bx=0), enc('SETGLOBAL', 2, bx=4), enc('RETURN', 0, 1)],
                 protos=[on_click], locals_=[(b'd', 3, 8)])


class Walk(unittest.TestCase):
    def setUp(self):
        w = ui_walk.Walker(TABLES)
        w.walk(_chunk())
        self.r = w.result()

    def test_engine_calls_and_fields(self):
        self.assertEqual(sorted(self.r['calls']), ['CampaignUI.EndTurn', 'CampaignUI.RetrieveDetails'])
        self.assertEqual(self.r['fields'], {'CampaignUI.RetrieveDetails()': ['.Name']})
        self.assertEqual(self.r['aliases']['d'], 'CampaignUI.RetrieveDetails()')

    def test_handler_and_its_engine_calls(self):
        self.assertEqual(self.r['handlers'], ['OnClick'])
        self.assertEqual(self.r['func_calls']['OnClick'], ['CampaignUI.EndTurn'])

    def test_inline_facts(self):
        f = ui_walk.inline_facts('function OnSelect()\n  CampaignUI.ShowDiplomacy()\n  Component.Call("x")\nend', TABLES)
        self.assertEqual(f['handlers'], ['OnSelect'])
        self.assertEqual(f['calls'], {'CampaignUI.ShowDiplomacy': 1, 'Component.Call': 1})


class Resolve(unittest.TestCase):
    SCRIPTS = {'campaign ui/foo_scripts/foo.luac': {}, 'campaign ui/shared.luac': {}, 'templates/template.list.luac': {}}

    def test_script_paths(self):
        rs = ui_atlas.resolve_script
        self.assertEqual(rs('campaign ui\\foo', 'foo.lua', self.SCRIPTS), 'campaign ui/foo_scripts/foo.luac')
        self.assertEqual(rs('campaign ui\\foo', '../shared.lua', self.SCRIPTS), 'campaign ui/shared.luac')
        self.assertEqual(rs('campaign ui\\foo', 'template.list.lua', self.SCRIPTS), 'templates/template.list.luac')
        self.assertIsNone(rs('campaign ui\\foo', 'template.button_standard.lua', self.SCRIPTS))

    def test_art_ids(self):
        assets = {'ui\\campaign ui\\skins\\a b.tga': 'ui/campaign_ui/skins/a_b.tga'}
        self.assertEqual(ui_atlas.art_id('UI/Campaign UI/Skins/a b.tga', assets), 'ui/campaign_ui/skins/a_b.tga')
        self.assertEqual(ui_atlas.art_id('data\\UI\\Campaign UI\\Skins\\a b.tga', assets), 'ui/campaign_ui/skins/a_b.tga')
        self.assertEqual(ui_atlas.art_id('C:\\Empire\\data\\UI\\Campaign UI\\Skins\\a b.tga', assets), 'ui/campaign_ui/skins/a_b.tga')
        self.assertTrue(ui_atlas.art_id('C:\\Docs\\golden_bullet.tga', assets).startswith('editor_path:'))
        self.assertTrue(ui_atlas.art_id('ui/missing.tga', assets).startswith('unresolved:'))

    def test_nine_slice_group(self):
        def c(name, w=16, h=16):
            return dict(path=f'root/p/{name}', name=name, parent='root/p', w=w, h=h, states=[dict(images=[f'art/{name}'])])
        comps = [dict(path='root/p', name='p', parent='root', w=100, h=100, states=[])]
        comps += [c(f'frame_{k}') for k in ('TL', 'T', 'TR', 'L', 'R', 'BL', 'B', 'BR')]
        g = ui_atlas.frame_groups(comps)
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]['insets'], [16, 16, 16, 16])
        self.assertEqual(g[0]['pieces']['TL'], ['art/frame_TL'])


def _atlas(scripts):
    at = object.__new__(ui_atlas.Atlas)
    at.tables, at.scripts, at.memo = set(TABLES), scripts, {}
    at.links = {}
    for rel, r in sorted(scripts.items()):
        for _, _, f, j, lab in r['links']:
            at.links.setdefault((f, j), []).append((rel, lab))
    return at


def _script(**kw):
    base = dict(aliases={}, links=[], other_calls={}, defines=[], func_calls={})
    base.update(kw)
    return base


class Trace(unittest.TestCase):
    def test_engine_alias_and_parameter(self):
        a = _script(aliases={'m': 'CampaignUI.Details()'}, links=[['LuaCall', None, 'Initialise', 0, 'CampaignUI.Details().Region']])
        b = _script()
        at = _atlas({'a.luac': a, 'b.luac': b})
        self.assertEqual(at.resolve('CampaignUI.Details()', a)[0], 'CampaignUI.Details')
        self.assertEqual(at.resolve('^m', a)[0], 'CampaignUI.Details')
        self.assertEqual(at.resolve('Initialise#arg1', b)[0], 'CampaignUI.Details.Region')

    def test_callers_that_disagree_resolve_nothing(self):
        a = _script(links=[['LuaCall', None, 'Init', 0, 'CampaignUI.A()']])
        b = _script(links=[['LuaCall', None, 'Init', 0, 'BattleUI.B()']])
        at = _atlas({'a.luac': a, 'b.luac': b, 'c.luac': _script()})
        label, kind, why = at.resolve('Init#arg1', at.scripts['c.luac'])
        self.assertIsNone(label)
        self.assertIn('different', why)
        # the unit's own caller wins over the others
        self.assertEqual(at.resolve('Init#arg1', at.scripts['c.luac'], scope=frozenset({'a.luac', 'c.luac'}))[0], 'CampaignUI.A')

    def test_modules_are_code(self):
        a = _script(other_calls={'^utils.Format': 3})
        at = _atlas({'a.luac': a})
        self.assertEqual(at.resolve('^utils', a)[1], 'code')
        self.assertEqual(at.resolve('panel_manager', a)[1], 'code')
        self.assertEqual(at.resolve('^other', a)[1], 'upvalue')


class Handlers(unittest.TestCase):
    def test_owner_order(self):
        scripts = {'x.luac': {'defines': ['OnSelect']}, 'y.luac': {'defines': []}}
        comps = {'root': dict(path='root', parent=None, script='x.luac'), 'root/b': dict(path='root/b', parent='root', script='y.luac'),
                 'root/m': dict(path='root/m', parent='root', script='missing:template.button_standard.lua')}
        own = ui_atlas.handler_owner
        self.assertEqual(own(comps['root/b'], comps, 'OnSelect', scripts, {}, []), 'x.luac')
        self.assertEqual(own(comps['root/b'], comps, 'call Root.LuaCall,TransitionBack', scripts, {}, []), 'engine command')
        self.assertIn('not shipped', own(comps['root/m'], comps, 'UpdateSlider', scripts, {}, []))
        self.assertEqual(own(comps['root/b'], comps, 'Play', scripts, {}, [], {'Play': ['G.BattleUI']}), 'engine: BattleUI.Play')


class Check(unittest.TestCase):
    def test_problems_catch_a_changed_file_and_rows(self):
        with tempfile.TemporaryDirectory() as d:
            shas = {}
            for f in ui_atlas.ATLAS_FILES:
                shas[f] = ui_atlas.jdump(os.path.join(d, f), {'f': f}, gz=True)
            with open(os.path.join(d, 'summary.json'), 'w', encoding='utf-8') as fh:
                json.dump(dict(sha256=shas, units={'campaign.x': {'screen': 'campaign.x'}}), fh)
            rows = os.path.join(d, 'rows.jsonl')
            with open(rows, 'w', encoding='utf-8') as fh:
                fh.write(json.dumps(dict(id='campaign.x', screen='campaign.x', status='atlas')) + '\n')
            self.assertEqual(ui_atlas.problems(d, rows), [])
            with open(os.path.join(d, 'battle.json.gz'), 'rb') as fh:
                raw = fh.read()
            self.assertEqual(raw[4:8], b'\0\0\0\0')
            self.assertEqual(hashlib.sha256(gzip.decompress(raw)).hexdigest(), shas['battle.json.gz'])
            ui_atlas.jdump(os.path.join(d, 'battle.json.gz'), {'f': 'changed'}, gz=True)
            with open(rows, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(dict(id='campaign.y', screen='campaign.y', status='atlas')) + '\n')
            bad = ui_atlas.problems(d, rows)
            self.assertTrue(any('battle.json.gz' in b for b in bad))
            self.assertTrue(any('ids differ' in b for b in bad))


class Live(unittest.TestCase):
    """The live pass: trees from proxy logs and ctl results, and the rules that decide reached (run 20261102_j10pc)."""
    @staticmethod
    def _tree(label, nodes, parts=1):
        items = [f'{p}|1|0,0|{w},10|NewState' for p, w in nodes]
        size = -(-len(items) // parts)
        chunks = [';'.join(items[i:i + size]) + ';' for i in range(0, len(items), size)]
        chunks[-1] += 'END flags=0'
        return [f'[INFO ] lua: j10tree {label} {i + 1}: {c}' for i, c in enumerate(chunks)]

    @staticmethod
    def _surface(head, kids, w=100):
        comps = [dict(path='root', parent=None, name='root', w=None), dict(path=f'root/{head}', parent='root', name=head, w=w)]
        comps += [dict(path=f'root/{head}/{k}', parent=f'root/{head}', name=k, w=10) for k in kids]
        return dict(components=comps)

    def _run(self, d):
        raw = os.path.join(d, 'raw')
        os.makedirs(raw)
        with open(os.path.join(raw, 'a_proxy.log'), 'w', encoding='utf-8') as fh:   # a stale sitting: three parts, wrong tree
            fh.write('\n'.join(self._tree('battle1', [('old', 5), ('old/x', 5), ('old/y', 5)], parts=3)) + '\n')
        with open(os.path.join(raw, 'b_proxy.log'), 'w', encoding='utf-8') as fh:   # the re-run: one part
            fh.write('\n'.join(self._tree('battle1', [('hud', 200), ('hud/orders', 100), ('hud/orders/a', 10), ('hud/orders/b', 10),
                                                      ('hud/orders/c', 10), ('Banner', 5)])) + '\n')
        with open(os.path.join(raw, 'page_sp.txt'), 'w', encoding='utf-8') as fh:   # a ctl result: the tree is in its "log" list
            json.dump(dict(status='ok', chunk='sp|true|true', log=self._tree('fe_sp', [('page', 100), ('page/x', 10), ('page/y', 10), ('page/z', 10)])), fh)
        with open(os.path.join(raw, 'shots_s.txt'), 'w', encoding='utf-8') as fh:   # not JSON: ignored by the tree reader
            fh.write('j10_fe_sp.jpg\n')
        return d

    def test_trees_from_logs_and_results(self):
        with tempfile.TemporaryDirectory() as d:
            t = ui_atlas.parse_trees(self._run(d))
            self.assertEqual([n[0] for n in t['battle1']], ['hud', 'hud/orders', 'hud/orders/a', 'hud/orders/b', 'hud/orders/c', 'Banner'])
            self.assertEqual([n[0] for n in t['fe_sp']], ['page', 'page/x', 'page/y', 'page/z'])

    def test_reach_rules(self):
        surfaces = {'battle': {'ui/orders': self._surface('orders_bar', ['a', 'b', 'c']),
                               'ui/tiny': self._surface('Banner', [])},
                    'frontend': {'ui/sp': self._surface('page', ['x', 'y', 'z']),
                                 'ui/mp': self._surface('page', ['x', 'y', 'z', 'q'])}}
        units = [dict(id='battle.orders', ctx='battle', surface='ui/orders'), dict(id='battle.tiny', ctx='battle', surface='ui/tiny'),
                 dict(id='frontend.sp', ctx='frontend', surface='ui/sp'), dict(id='frontend.mp', ctx='frontend', surface='ui/mp')]
        with tempfile.TemporaryDirectory() as d:
            r = ui_atlas.live(None, units, surfaces, self._run(d))['units_reach']
        # attached under the placeholder's name: found as the live parent of its children
        self.assertEqual((r['battle.orders']['reach'], r['battle.orders']['live_path']), ('reached', 'hud/orders'))
        # the copy matches the same node less well and loses it
        self.assertEqual((r['frontend.sp']['reach'], r['frontend.sp']['shot']), ('reached', 'j10_fe_sp.jpg'))
        self.assertEqual(r['frontend.mp']['reach'], 'static_only')
        self.assertIn("frontend.sp's", r['frontend.mp']['reason'])
        # a head name alone is no evidence
        self.assertEqual(r['battle.tiny']['reach'], 'static_only')
        self.assertIn('fewer than 3', r['battle.tiny']['reason'])

    def test_known_reason_beats_a_name_match(self):
        # frontend.password_entry has the same parts as the page 'page' below, but needs a multiplayer lobby: its reason is not the page's
        surfaces = {'frontend': {'ui/sp': self._surface('page', ['x', 'y', 'z']), 'ui/pw': self._surface('password_entry', ['x', 'y', 'z'])}}
        units = [dict(id='frontend.password_entry', ctx='frontend', surface='ui/pw')]
        with tempfile.TemporaryDirectory() as d:
            r = ui_atlas.live(None, units, surfaces, self._run(d))['units_reach']['frontend.password_entry']
        self.assertEqual(r['reach'], 'static_only')
        self.assertIn('multiplayer lobby', r['reason'])

    def _run_nodes(self, d, label, nodes):
        raw = os.path.join(d, 'raw')
        os.makedirs(raw)
        with open(os.path.join(raw, 'a_proxy.log'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(self._tree(label, nodes)) + '\n')
        return d

    def test_guard_fails_on_a_pattern_that_overrides_live_evidence(self):
        # the head is found under its own name as a top-level node at agreement 1.0, yet a STATIC_ONLY pattern matches it
        surfaces = {'frontend': {'ui/ps': self._surface('password_entry', ['x', 'y', 'z'])}}
        units = [dict(id='frontend.password_entry', ctx='frontend', surface='ui/ps')]
        with tempfile.TemporaryDirectory() as d:
            run = self._run_nodes(d, 'fe_x', [('password_entry', 100), ('password_entry/x', 10), ('password_entry/y', 10), ('password_entry/z', 10)])
            with self.assertRaises(ui_atlas.StaticOnlyConflict) as cm:
                ui_atlas.live(None, units, surfaces, run)
        for part in ('frontend.password_entry', 'live path password_entry', 'multiplayer lobby'):
            self.assertIn(part, str(cm.exception))

    def test_guard_allows_a_match_inside_another_pages_node(self):
        # the parts sit inside the options page: the head is named, but nested, so the pattern still wins
        surfaces = {'frontend': {'ui/ps': self._surface('password_entry', ['x', 'y', 'z'])}}
        units = [dict(id='frontend.password_entry', ctx='frontend', surface='ui/ps')]
        with tempfile.TemporaryDirectory() as d:
            run = self._run_nodes(d, 'fe_x', [('options', 200), ('options/password_entry', 100), ('options/password_entry/x', 10),
                                              ('options/password_entry/y', 10), ('options/password_entry/z', 10)])
            r = ui_atlas.live(None, units, surfaces, run)['units_reach']['frontend.password_entry']
        self.assertEqual((r['reach'], r['reason']), ('static_only', 'needs a multiplayer lobby or Steam session'))


class Ids(unittest.TestCase):
    def test_unit_id_has_no_hyphen(self):
        self.assertEqual(ui_atlas.unit_id('campaign', 'load-save_game'), 'campaign.load_save_game')
        self.assertEqual(ui_atlas.unit_id('campaign', 'Two Words'), 'campaign.two_words')

    def test_template_users(self):
        rec = dict(kind='layout', scripts_attached=['campaign ui/a_scripts/a.luac'], scripts_folder=[],
                   templates_used=['script:Widget', 'layout:templates/frame'], opened_by=[])
        tpl = dict(kind='uied_template', opened_by=['CreateComponentFromTemplate("BuildingFrame") in campaign ui/a_scripts/a.luac Fn'])
        surfaces = {'campaign': {'campaign ui/a': rec}, 'template': {'uied.templates/BuildingFrame': tpl}}
        units = [dict(id='campaign.a', screen='campaign.a', ctx='campaign', surface='campaign ui/a')]
        u = ui_atlas.template_users(units, surfaces)
        self.assertEqual(u['template.widget'], ['campaign.a'])
        self.assertEqual(u['template.frame'], ['campaign.a'])
        self.assertEqual(u['template.buildingframe'], ['campaign.a'])


if __name__ == '__main__':
    unittest.main()
