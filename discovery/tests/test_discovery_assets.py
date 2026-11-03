"""Host tests for the J7 discovery passes' pure logic (discovery/core/): pack adapter, ids, roles, image headers, loc, db, gzip, schema."""
import gzip
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'discovery', 'core'))

import assets  # noqa: E402
import db  # noqa: E402
import imagehdr  # noqa: E402
import loc  # noqa: E402
import ron2json  # noqa: E402
import tsvgz  # noqa: E402
from packfs import LOOSE, PackFS, write_pack  # noqa: E402


class PackAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.data = self.tmp.name
        write_pack(os.path.join(d, 'base.pack'), {'ui\\a.tga': b'AAAA', 'db\\t_tables\\t': b'base', 'x\\only_base': b'b1'})
        write_pack(os.path.join(d, 'patch.pack'), {'db\\t_tables\\t': b'patched!'}, pack_type=2)
        os.makedirs(os.path.join(d, 'ui', 'cursors'))
        with open(os.path.join(d, 'ui', 'cursors', 'arrow.cur'), 'wb') as f:
            f.write(b'CUR')

    def tearDown(self):
        self.tmp.cleanup()

    def test_index_precedence_and_read_by_offset(self):
        fs = PackFS(self.data, ['base', 'patch'])
        self.assertEqual(fs.packs, ['base.pack', 'patch.pack'])
        self.assertEqual(len(fs.copies()), 5)
        self.assertEqual(fs.stat('DB/t_tables/t').source, 'patch.pack')
        self.assertEqual(fs.read('db\\t_tables\\t'), b'patched!')
        self.assertEqual(fs.read('x\\only_base'), b'b1')
        self.assertEqual(fs.read('ui\\a.tga'), b'AAAA')
        self.assertEqual(fs.stat('ui\\cursors\\arrow.cur').source, LOOSE)
        self.assertEqual([c.path for c in fs.list(under='ui\\')], ['ui\\a.tga', 'ui\\cursors\\arrow.cur'])
        self.assertEqual(sum(c.effective for c in fs.copies()), 4)
        self.assertEqual(b''.join(PackFS.chunks(fs.stat('ui\\a.tga'))), b'AAAA')

    def test_unlisted_packs_sort_by_header_type(self):
        fs = PackFS(self.data)
        self.assertEqual(fs.packs, ['base.pack', 'patch.pack'])
        fs = PackFS(self.data, ['patch', 'base'])
        self.assertEqual(fs.read('db\\t_tables\\t'), b'base')

    def test_loose_override_is_a_parameter(self):
        write_pack(os.path.join(self.data, 'c.pack'), {'ui\\cursors\\arrow.cur': b'PACK'})
        self.assertEqual(PackFS(self.data).read('ui\\cursors\\arrow.cur'), b'CUR')
        self.assertEqual(PackFS(self.data, loose_wins=False).read('ui\\cursors\\arrow.cur'), b'PACK')


class Ids(unittest.TestCase):
    def test_slug_and_collisions(self):
        ids = assets.ids_for(['ui\\Campaign UI\\a b.tga', 'ui\\campaign_ui\\a_b.tga', 'ui\\flags\\x.tga'])
        self.assertEqual(ids['ui\\flags\\x.tga'], 'ui/flags/x.tga')
        a, b = ids['ui\\Campaign UI\\a b.tga'], ids['ui\\campaign_ui\\a_b.tga']
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith('ui/campaign_ui/a_b.tga#') and b.startswith('ui/campaign_ui/a_b.tga#'))

    def test_long_ids_fit_the_schema(self):
        import re
        p = 'ui\\' + 'very long folder\\' * 12 + 'x.tga'
        i = assets.ids_for([p])[p]
        self.assertLessEqual(len(i), assets.ID_MAX)
        self.assertRegex(i, r'^[a-z0-9][a-z0-9_.:/#-]*$')
        self.assertIn('#', i)
        self.assertTrue(re.match(r'^[a-z0-9]', assets.ids_for(['-odd.tga'])['-odd.tga']))

    def test_hand_set_fields_survive_an_id_change(self):
        row = lambda p: {'pack': 'data.pack', 'path': p, 'size': '1', 'sha256': '0' * 64, 'format': 'tga', 'effective': '1'}
        old = assets.registry_rows([row('ui\\a b.tga')], {}, [])
        old[0]['used_by'] = ['x']
        new = assets.registry_rows([row('ui\\a b.tga'), row('ui\\a_b.tga')], {}, [], old)
        moved = next(r for r in new if r['path'] == 'ui\\a b.tga')
        self.assertNotEqual(moved['id'], old[0]['id'])
        self.assertEqual(moved['used_by'], ['x'])
        self.assertNotIn('used_by', next(r for r in new if r['path'] == 'ui\\a_b.tga'))

    def test_committed_registry_ids_are_unique(self):
        reg = assets.read_registry(os.path.join(ROOT, 'registries', 'assets.jsonl'))
        self.assertEqual(len({r['id'] for r in reg}), len(reg))


class Roles(unittest.TestCase):
    CASES = {
        'ui\\flags\\france\\mon_64.tga': 'flag', 'ui\\units\\icons\\brig.tga': 'unit_card', 'ui\\portraits\\european\\x.jpg': 'portrait',
        'ui\\battle ui\\buttons\\button_canister_selected.tga': 'button_state',
        'ui\\campaign ui\\skins\\paper_pane_tl.tga': 'panel_frame', 'ui\\cursors\\arrow.cur': 'cursor', 'font\\editor_10.cuf': 'font',
        'ui\\campaign ui\\diplomacy_panel': 'layout', 'ui\\templates\\round_button': 'template', 'ui\\common ui\\x.luac': 'ui_script',
        'ui\\flags\\france\\flag.db': 'ui_db', 'ui\\eventpics\\note.txt': 'unclassified',
        'battleterrain\\presets\\hb_lodi\\screenshot_small.tga': 'battle_picture',
    }

    def test_rules_on_fixture_paths(self):
        rules = assets.load_roles()
        for p, want in self.CASES.items():
            with self.subTest(p=p):
                self.assertEqual(assets.role_of(p, rules), want)
        self.assertEqual(assets.role_of('ui\\common ui\\skins\\wavering.tga', rules, 19, 19), 'icon')
        self.assertEqual(assets.role_of('ui\\common ui\\skins\\india_map.tga', rules, 524, 600), 'ui_art')

    def test_refs_resolve_past_length_bytes(self):
        known = {'ui\\campaign ui\\pips\\x.tga', 'ui\\eventpics\\european\\admiral.tga'}
        names = assets.basenames(known)
        self.assertEqual(assets.resolve('-data\\ui\\campaign ui\\pips\\x.tga', known), 'ui\\campaign ui\\pips\\x.tga')
        self.assertEqual(assets.resolve('campaign ui\\pips\\x.tga', known), 'ui\\campaign ui\\pips\\x.tga')
        self.assertEqual(assets.resolve('admiral.tga', known, names), 'ui\\eventpics\\european\\admiral.tga')
        self.assertIsNone(assets.resolve('_selected.tga', known, names))


class ImageHeaders(unittest.TestCase):
    def test_dds(self):
        h = bytearray(128)
        h[:4] = b'DDS '
        struct.pack_into('<III', h, 12, 64, 128, 0)
        struct.pack_into('<I', h, 28, 8)
        struct.pack_into('<I4s', h, 80, 0x4, b'DXT5')
        self.assertEqual(imagehdr.info(bytes(h), '.dds'), {'w': 128, 'h': 64, 'mips': 8, 'pixel': 'dxt5'})
        struct.pack_into('<I4sI', h, 80, 0x41, b'\0\0\0\0', 32)
        struct.pack_into('<I', h, 104, 0xFF000000)
        self.assertEqual(imagehdr.info(bytes(h), '.dds')['pixel'], 'bgra8')

    def test_tga(self):
        h = bytes([0, 0, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0]) + struct.pack('<HHBB', 56, 32, 32, 8)
        self.assertEqual(imagehdr.info(h, '.tga'), {'w': 56, 'h': 32, 'mips': 1, 'pixel': 'bgra8_rle'})
        self.assertIsNone(imagehdr.info(b'\0' * 18, '.tga'))

    def test_png_and_jpg(self):
        png = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>IIBBBBB', 20, 10, 8, 6, 0, 0, 0)
        self.assertEqual(imagehdr.info(png, '.png'), {'w': 20, 'h': 10, 'mips': 1, 'pixel': 'rgba8'})
        jpg = b'\xff\xd8' + b'\xff\xe0' + struct.pack('>H', 4) + b'JF' + b'\xff\xc0' + struct.pack('>HBHHB', 17, 8, 30, 40, 3)
        self.assertEqual(imagehdr.info(jpg, '.jpg'), {'w': 40, 'h': 30, 'mips': 1, 'pixel': 'ycc8'})


class Loc(unittest.TestCase):
    def test_round_trip_and_byte_exact(self):
        ents = [('units_onscreen_name_x', 'Grenadiers', 0), ('ui_y', '', 1)]
        b = loc.encode(1, ents)
        self.assertEqual(loc.decode(b), (1, ents))
        with self.assertRaises(ValueError):
            loc.decode(b + b'\0')
        with self.assertRaises(ValueError):
            loc.decode(b[:-3])

    def test_table_prefix(self):
        self.assertEqual(loc.table_of('units_onscreen_name_x', {'unit', 'units', 'units_to_x'}), 'units')
        self.assertIsNone(loc.table_of('button_ok', {'units'}))


class Db(unittest.TestCase):
    FIELDS = [{'name': 'key', 'type': 'StringU16', 'key': True}, {'name': 'n', 'type': 'I32', 'key': False},
              {'name': 'on', 'type': 'Boolean', 'key': False}]

    @staticmethod
    def table(rows, version=None):
        head = (db.VERSION_MARKER + struct.pack('<I', version)) if version is not None else b''
        body = b''.join(struct.pack('<H', len(k)) + k.encode('utf-16-le') + struct.pack('<iB', n, on) for k, n, on in rows)
        return head + b'\x01' + struct.pack('<I', len(rows)) + body

    def test_byte_exact_rule(self):
        b = self.table([('a', 1, 1), ('bb', -2, 0)], version=2)
        self.assertEqual(db.parse_header(b)[1], 2)
        d = db.decode_table(b, [{'version': 2, 'fields': self.FIELDS}])
        self.assertEqual((d['status'], d['rows']), ('decoded', [['a', 1, True], ['bb', -2, False]]))
        d = db.decode_table(b + b'\0', [{'version': 2, 'fields': self.FIELDS}])
        self.assertEqual(d['status'], 'failed')
        self.assertIn('consumed', d['errors'][0])
        self.assertEqual(db.decode_table(b, [])['status'], 'no_schema')
        self.assertEqual(db.decode_table(self.table([]), [])['status'], 'empty')

    def test_other_version_only_after_the_matching_one(self):
        b = self.table([('a', 1, 1)])
        d = db.decode_table(b, [{'version': 3, 'fields': self.FIELDS}])
        self.assertEqual(d['status'], 'decoded_with_v3')
        self.assertEqual(db.table_name('db\\units_tables\\units'), 'units')

    def test_keys_and_refs_inherit_from_newer_versions(self):
        old = [{'name': 'key', 'type': 'StringU16', 'key': False}, {'name': 'cat', 'type': 'StringU16', 'key': False}]
        new = {'version': 9, 'fields': [{'name': 'key', 'type': 'StringU8', 'key': True},
                                        {'name': 'cat', 'type': 'StringU8', 'key': False, 'ref': {'table': 'c', 'column': 'key'}}]}
        f = db.with_inherited(old, [{'version': 1, 'fields': old}, new])
        self.assertEqual(f[0], {'name': 'key', 'type': 'StringU16', 'key': True, 'inherited_from': 9})
        self.assertEqual(f[1]['ref'], {'table': 'c', 'column': 'key'})
        self.assertEqual(f[1]['type'], 'StringU16')

    def test_ron_schema_conversion(self):
        ron = ('(version: 5, definitions: {"units_tables": [(version: 1, fields: [(name: "key", field_type: StringU16, is_key: true, '
               'is_reference: None), (name: "faction", field_type: StringU16, is_key: false, is_reference: Some(("factions", "key")))])]})')
        t = ron2json.convert(ron2json.Ron(ron).val())
        f = t['units_tables'][0]['fields']
        self.assertEqual(f[0], {'name': 'key', 'type': 'StringU16', 'key': True})
        self.assertEqual(f[1]['ref'], {'table': 'factions', 'column': 'key'})


class DeterministicGzip(unittest.TestCase):
    def test_same_rows_same_bytes(self):
        rows = [('b', 2), ('a', 1)]
        self.assertEqual(tsvgz.dumps(['k', 'v'], [('a', '1'), ('b', '2')]), tsvgz.dumps(['k', 'v'], [('b', '2'), ('a', '1')]))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 't.tsv.gz')
            tsvgz.write(p, ['k', 'v'], rows)
            self.assertEqual(open(p, 'rb').read()[4:8], b'\0\0\0\0')
            self.assertEqual(tsvgz.problems(p, ['k', 'v']), [])
            self.assertEqual(tsvgz.read(p), (['k', 'v'], [('a', '1'), ('b', '2')]))
            self.assertTrue(tsvgz.problems(p, ['k', 'x']))
            raw = 'k\tv\nb\t2\na\t1\n'.encode()
            co = zlib.compressobj(9, zlib.DEFLATED, 31)
            open(p, 'wb').write(co.compress(raw) + co.flush())
            self.assertTrue(tsvgz.problems(p))

    def test_other_deflate_bytes_pass(self):
        """A file another zlib build wrote (here: level 1) passes; a name or mtime in the header does not."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 't.tsv.gz')
            rows = [('%04d' % i, 'x' * 40) for i in range(200)]
            other = gzip.compress(tsvgz.text(['k', 'v'], rows), compresslevel=1, mtime=0)
            self.assertNotEqual(other, tsvgz.dumps(['k', 'v'], rows))
            open(p, 'wb').write(other)
            self.assertEqual(tsvgz.problems(p, ['k', 'v']), [])
            body = tsvgz.text(['k', 'v'], rows)
            open(p, 'wb').write(gzip.compress(body, compresslevel=9, mtime=12345))
            self.assertTrue(tsvgz.problems(p))

    def test_paths_with_backslash_t_survive(self):
        self.assertEqual(tsvgz.cell('ui\\templates\\x'), 'ui\\templates\\x')


class CommittedResults(unittest.TestCase):
    def test_discovery_check_covers_j7(self):
        sys.path.insert(0, os.path.join(ROOT, 'tools', 'verbs'))
        import discovery
        self.assertEqual(discovery.j7_problems(ROOT), [])


if __name__ == '__main__':
    unittest.main()
