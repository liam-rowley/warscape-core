import json
import unittest

from _util import TempRepo
from warscape.registry import Registry, RegistryError, load_all
from warscape.repo import Ctx


class RegistryCase(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()
        self.assertEqual(self.repo.wsc('reg', 'render')[0], 0)
        self.ctx = Ctx.load(self.repo.root)

    def tearDown(self):
        self.repo.close()

    def regs(self):
        return load_all(Ctx.load(self.repo.root))

    def errors(self, name):
        regs = self.regs()
        return regs[name].check(regs)


class Rows(RegistryCase):
    def test_empty_registries_render_and_check(self):
        for name, reg in self.regs().items():
            self.assertEqual(reg.check(self.regs()), [], name)
            self.assertEqual(self.repo.read(reg.rel_path), '')

    def test_add_writes_canonical_sorted_rows_in_schema_key_order(self):
        reg = self.regs()['config_keys']
        reg.add({'owner': 'ui', 'id': 'ui.scale', 'default': 1.0, 'description': 'UI scale slider'})
        reg.add({'id': 'a.first', 'description': 'x', 'default': None, 'owner': 'core'})
        reg.save(); reg.write_view()
        lines = self.repo.read('registries/config_keys.jsonl').splitlines()
        self.assertEqual([json.loads(l)['id'] for l in lines], ['a.first', 'ui.scale'])
        self.assertEqual(list(json.loads(lines[1])), ['id', 'description', 'default', 'owner'])
        self.assertEqual(self.errors('config_keys'), [])

    def test_invalid_row_is_refused(self):
        reg = self.regs()['engine_facts']
        with self.assertRaises(RegistryError):
            reg.add({'id': 'f1', 'claim': 'shadow map is 2048', 'state': 'verified'})   # verified needs evidence + date
        reg.add({'id': 'f1', 'claim': 'shadow map is 2048', 'state': 'verified', 'date': '2026-10-28', 'evidence': 'runs/20261028_a'})
        with self.assertRaises(RegistryError):
            reg.add({'id': 'f1', 'claim': 'dup', 'state': 'open'})

    def test_set_changes_and_removes_fields_but_not_the_id(self):
        reg = self.regs()['engine_facts']
        reg.add({'id': 'f1', 'claim': 'c', 'state': 'open', 'notes': 'n'})
        reg.set('f1', {'notes': None, 'state': 'refuted', 'date': '2026-10-28', 'evidence': 'r1'})
        self.assertNotIn('notes', reg.by_id()['f1'])
        with self.assertRaises(RegistryError):
            reg.set('f1', {'id': 'f2'})
        with self.assertRaises(RegistryError):
            reg.set('nope', {'state': 'open'})
        with self.assertRaises(RegistryError):
            reg.set('f1', {'state': 'verified', 'evidence': None})   # the schema still applies after a set

    def test_hand_edits_are_caught(self):
        p = self.repo.root / 'registries/engine_facts.jsonl'
        row = '{"id": "b", "claim": "c", "state": "open"}\n'
        p.write_text(row + '{"id": "a", "claim": "c", "state": "open"}\n' + row, encoding='utf-8')
        errs = '\n'.join(self.errors('engine_facts'))
        self.assertIn('canonical', errs)
        self.assertIn("duplicate id 'b'", errs)
        self.assertIn('stale', errs)
        p.write_text('{"id": "a", "claim": "c", "state": "open", "n": NaN}\n', encoding='utf-8')
        self.assertIn('not strict JSON', '\n'.join(self.errors('engine_facts')))

    def test_render_fixes_order_and_view(self):
        p = self.repo.root / 'registries/engine_facts.jsonl'
        p.write_text('{"state": "open", "id": "b", "claim": "c"}\n{"id": "a", "claim": "c", "state": "open"}\n', encoding='utf-8')
        self.assertEqual(self.repo.wsc('reg', 'render', 'engine_facts')[0], 0)
        self.assertEqual(self.errors('engine_facts'), [])
        self.assertIn('| `a` | open | c |', self.repo.read('registries/engine_facts.md'))


class Rules(RegistryCase):
    def add_hotkey(self, rid, binding, context='battle', source='mod'):
        reg = self.regs()['hotkeys']
        reg.add({'id': rid, 'description': 'd', 'binding': binding, 'action': 'act', 'context': context, 'source': source})
        reg.save(); reg.write_view()

    def test_hotkey_binding_form_and_reserved_keys(self):
        for b in ('Alt+F4', 'Alt+Ctrl+S', 'ctrl+s', 'Ctrl+Alt+Delete'):
            with self.assertRaises(RegistryError, msg=b):
                self.add_hotkey('h', b)
        with self.assertRaises(RegistryError):     # Empire learning: Alt is held for the move gesture, so a mod F4 becomes Alt+F4
            self.add_hotkey('h', 'F4', source='mod')
        self.add_hotkey('v', 'F4', source='vanilla')
        self.add_hotkey('m', 'Ctrl+Alt+LeftDrag')

    def test_hotkey_clashes(self):
        self.add_hotkey('a', 'Alt+S', 'battle')
        self.add_hotkey('b', 'Alt+S', 'campaign')
        self.assertEqual(self.errors('hotkeys'), [])
        self.add_hotkey('c', 'Alt+S', 'global')    # global clashes with every context
        errs = self.errors('hotkeys')
        self.assertEqual(len(errs), 2, errs)
        self.assertTrue(all('clash' in e for e in errs))

    def test_cross_registry_refs(self):
        sites = self.regs()['engine_sites']
        sites.add({'id': 'shadow.size', 'description': 'd', 'purpose': 'p', 'rva': '0x1a2b', 'anchor_bytes': '8b 4d',
                   'stock_bytes': '00 08', 'kind': 'patch', 'patch_bytes': '00 20', 'config_key': 'shadow.map_size',
                   'verified': {'date': '2026-10-28', 'run': '20261028_a'}})
        sites.save(); sites.write_view()
        self.assertIn("config_key 'shadow.map_size' is not an id in config_keys", '\n'.join(self.errors('engine_sites')))
        keys = self.regs()['config_keys']
        keys.add({'id': 'shadow.map_size', 'description': 'shadow map edge in px', 'default': 2048, 'owner': 'gfx'})
        keys.save(); keys.write_view()
        self.assertEqual(self.errors('engine_sites'), [])

    def test_ref_to_an_undeclared_registry_fails_only_when_used(self):
        self.repo.write('wsc.toml', 'registries_dir = "registries"\n[registries]\ntools = "core:tools"\nassets = "core:assets"\n[tests]\ndirs = []\n')
        self.assertEqual(self.repo.wsc('reg', 'render')[0], 0)
        assets = self.regs()['assets']
        row = {'id': 'ui/a.dds', 'description': 'd', 'pack': 'data.pack', 'path': 'ui/a.dds', 'format': 'dds',
               'hash': 'sha1:' + '0' * 40, 'role': 'icon'}
        assets.add(dict(row)); assets.save(); assets.write_view()
        self.assertEqual(self.errors('assets'), [])        # ui_elements undeclared, used_by unused: fine
        assets = self.regs()['assets']
        assets.add(dict(row, used_by=['hud.x']), replace=True); assets.save(); assets.write_view()
        self.assertIn("points at registry 'ui_elements', which this repo does not declare", '\n'.join(self.errors('assets')))

    def test_engine_site_verified_needs_date_and_run(self):
        sites = self.regs()['engine_sites']
        base = {'id': 's', 'description': 'd', 'purpose': 'p', 'rva': '0x10', 'anchor_bytes': 'aa', 'stock_bytes': 'bb', 'kind': 'hook', 'hook': 'detour_x'}
        sites.add(dict(base))
        with self.assertRaises(RegistryError):
            sites.add(dict(base, id='t', verified={'date': '2026-10-28'}))
        with self.assertRaises(RegistryError):
            sites.add(dict(base, id='u', kind='patch'))   # a patch needs patch_bytes

    def test_ui_element_past_atlas_needs_classified_interactions(self):
        ui = self.regs()['ui_elements']
        row = {'id': 'hud.end_turn', 'description': 'd', 'screen': 'hud', 'status': 'atlas', 'interactions': [{'name': 'click'}]}
        ui.add(dict(row))
        with self.assertRaises(RegistryError):
            ui.set('hud.end_turn', {'status': 'contract'})
        ui.set('hud.end_turn', {'status': 'contract', 'interactions': [{'name': 'click', 'decision': 'kept', 'reason': 'same as vanilla'}]})

    def test_campaign_scenario_needs_a_save_battles_need_sky(self):
        sc = self.regs()['scenarios']
        with self.assertRaises(RegistryError):
            sc.add({'id': 'c1', 'description': 'd', 'kind': 'campaign', 'map': 'europe', 'launch': 'x'})
        with self.assertRaises(RegistryError):
            sc.add({'id': 'l1', 'description': 'd', 'kind': 'land', 'map': 'm', 'launch': 'x'})
        sc.add({'id': 'l1', 'description': 'd', 'kind': 'land', 'map': 'm', 'launch': 'x', 'time_of_day': 'noon', 'weather': 'clear',
                'camera_poses': {'overview': {'x': 0, 'y': 50, 'z': 0, 'yaw': 0, 'pitch': -45}}})

    def test_unusable_schema_stops_loading(self):
        self.repo.write('my.schema.json', '{"type": "object", "properties": {"id": {"type": "string", "dependentRequired": {}}}}')
        with self.assertRaises(RegistryError):
            Registry('mine', 'my.schema.json', self.repo.root, 'registries')


if __name__ == '__main__':
    unittest.main()
