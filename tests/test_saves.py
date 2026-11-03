"""Host tests for the core's ESF save tools (saves/esf_edit.py codec, esf_dump.py, esf_diff.py, esf_map.py walker) on synthetic files.

Ported from the first consumer's `tests/test_saves.py` at 6cbb9e9 (B17): the classes `Codec` and `Diff` and the synthetic `Tree` builder.
`Walker` takes the generic half of its map test (record paths, array items, @N values, `grep_id` finding both ends of a link) over a
neutral save; the game's own save map, recipes, staging and noise file are tested in the game repo."""
import contextlib
import importlib
import io
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'saves'))

# the save tools by name from saves/ (they import each other that way); import_module keeps them out of the stdlib-only scan's import list
esf_diff, esf_dump, E, esf_map = (importlib.import_module(m) for m in ('esf_diff', 'esf_dump', 'esf_edit', 'esf_map'))

# ---- an independent encoder: absolute offsets computed here, not by esf_edit
SCALARS = [(0x01, b'\x01'), (0x02, struct.pack('<b', -3)), (0x03, struct.pack('<h', -300)), (0x04, struct.pack('<i', -5)),
           (0x05, struct.pack('<q', -1 << 40)), (0x06, b'\xfe'), (0x07, struct.pack('<H', 65000)), (0x08, struct.pack('<I', 4000000000)),
           (0x09, struct.pack('<Q', 1 << 60)), (0x0a, struct.pack('<f', 1.5)), (0x0b, struct.pack('<d', -2.25)),
           (0x0c, struct.pack('<2f', 1, 2)), (0x0d, struct.pack('<3f', 1, 2, 3)), (0x10, struct.pack('<H', 1234)),
           (0x0e, struct.pack('<H', 2) + 'hi'.encode('utf-16-le')), (0x0f, struct.pack('<H', 3) + b'abc')]
ARRAYS = [(0x41, b'\x01\x00'), (0x44, struct.pack('<3i', 7, 8, 9)), (0x46, b'\x01\x02'), (0x47, struct.pack('<2H', 1, 2)),
          (0x48, struct.pack('<2I', 10, 11)), (0x4a, struct.pack('<2f', 0.5, 0.25)), (0x4c, struct.pack('<2f', 3, 4))]
NAMES = ['ROOT', 'A', 'ARR', 'ITEM']


def encode(base, magic=0xABCE, extra=b''):
    """header | ROOT{ every scalar, every packed array, A{bool}, ARR[2]{u32} , extra } | names"""
    body = b''.join(bytes([t]) + d for t, d in SCALARS)
    pos = base + 8 + len(body)
    for t, d in ARRAYS:
        body += bytes([t]) + struct.pack('<I', pos + 5 + len(d)) + d
        pos += 5 + len(d)
    a = b'\x01\x01'
    body += struct.pack('<BHBI', 0x80, 1, 0, pos + 8 + len(a)) + a
    pos += 8 + len(a)
    items, p = b'', pos + 12
    for k in range(2):
        it = b'\x08' + struct.pack('<I', 100 + k)
        p += 4 + len(it)
        items += struct.pack('<I', p) + it
    body += struct.pack('<BHBII', 0x81, 2, 1, p, 2) + items + extra
    root = struct.pack('<BHBI', 0x80, 0, 2, base + 8 + len(body)) + body
    names = struct.pack('<H', len(NAMES)) + b''.join(struct.pack('<H', len(n)) + n.encode() for n in NAMES)
    return struct.pack('<IIII', magic, 0, 1234, base + len(root)) + root + names


def write(tmp, name, data):
    p = os.path.join(tmp, name)
    with open(p, 'wb') as f:
        f.write(data)
    return p


class Codec(unittest.TestCase):
    def test_every_tag_round_trips_byte_exact(self):
        raw = encode(16)
        e = E.Esf(raw)
        self.assertEqual(e.dumps(), raw)
        self.assertEqual(e.unknown, [])
        root = e.select('ROOT')[0]
        got = [n.get() for n in E.Esf.vals(root)]
        self.assertEqual(got[:4], [True, -3, -300, -5])
        self.assertEqual(got[14:16], ['hi', 'abc'])
        self.assertEqual(got[17], [7, 8, 9])
        self.assertEqual(len(got), len(SCALARS) + len(ARRAYS))

    def test_roundtrip_cli_function_and_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, 'a.save', encode(16))
            ok, s1, s2, d, unk = E.roundtrip(p)
            self.assertTrue(ok)
            self.assertEqual((s1, d, unk), (s2, None, []))
            self.assertIn('unknown tags: none', E.info(p))

    def test_set_copy_remove_rebuild_offsets_and_counts(self):
        e = E.Esf(encode(16))
        root = e.select('ROOT')[0]
        root[15].set('a much longer string')    # 0x0f: every later offset moves
        root[3].set(42)
        arr = e.select_node('ROOT/ARR')
        e.copy_item(arr, 1)
        e.remove_item(arr, 0)
        e.name_id('NEW_NAME')
        out = e.dumps()
        e2 = E.Esf(out)
        self.assertEqual(E.Esf(e2.dumps()).dumps(), out)
        self.assertEqual([c[0].get() for c in e2.select('ROOT/ARR')], [101, 101])
        self.assertEqual(e2.select('ROOT')[0][15].get(), 'a much longer string')
        self.assertEqual(len(e2.names), len(NAMES) + 1)
        with tempfile.TemporaryDirectory() as tmp:   # the offset reader agrees on every end offset
            d = esf_dump.Esf(write(tmp, 'b.save', out))
            lines = []
            rn, o, end = esf_dump.root_span(d)
            esf_dump.tree(d, o, end, 0, 9, lines)
            self.assertIn('ARR[2] (v1)', lines)

    def test_unknown_tag_reported_with_offset(self):
        raw = bytearray(encode(16))
        off = 16 + 8   # first child of ROOT
        raw[off] = 0x3f
        with self.assertRaises(ValueError) as cm:
            E.Esf(bytes(raw))
        self.assertIn('unknown tag 0x3f at offset %d' % off, str(cm.exception))

    def test_unknown_array_element_type_fails_the_gate(self):
        raw = encode(16)
        e = E.Esf(raw)
        e.nodes[0].kids.append(E.Val(0x4e, b'\x00\x01\x02'))   # packed array of utf16: layout not known
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, 'u.save', e.dumps())
            ok, _, _, d, unk = E.roundtrip(p)
            self.assertFalse(ok)
            self.assertIsNone(d)            # still byte-exact: kept raw
            self.assertEqual(unk[0][1], 0x4e)

    def test_locate_names_path_and_tag(self):
        raw = encode(16)
        e = E.Esf(raw)
        arr_items = e.select('ROOT/ARR')
        self.assertEqual(len(arr_items), 2)
        off = raw.rindex(struct.pack('<I', 101)) - 1   # the u32 tag of ARR[1]
        path, tag = E.locate(raw, off)
        self.assertEqual((path, tag), ('ROOT/ARR[1]@value', 0x08))

    def test_cli_refuses_to_write_over_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, 'a.save', encode(16))
            sys.argv = ['esf_edit.py', 'set', p, 'ROOT', '@3', '9', '-o', p]
            with self.assertRaises(SystemExit) as cm:
                E.main()
            self.assertIn('refusing', str(cm.exception))
            out = os.path.join(tmp, 'b.save')
            sys.argv = ['esf_edit.py', 'set', p, 'ROOT', '@3', '9', '-o', out]
            with contextlib.redirect_stdout(io.StringIO()):
                E.main()
            self.assertEqual(E.Esf.load(out).select('ROOT')[0][3].get(), 9)


class Diff(unittest.TestCase):
    def run_diff(self, a, b, skip=''):
        with tempfile.TemporaryDirectory() as tmp:
            pa, pb = write(tmp, 'a.save', a), write(tmp, 'b.save', b)
            A, B = esf_dump.Esf(pa), esf_dump.Esf(pb)
            ra, oa, ea = esf_dump.root_span(A)
            rb, ob, eb = esf_dump.root_span(B)
            d = esf_diff.Differ(A, B, 100, 0.0, esf_diff.skip_names(skip))
            d.seq(oa, ea, ob, eb, ra)
            return d.out

    def test_value_change_item_added_and_skip(self):
        e = E.Esf(encode(16))
        e.select('ROOT')[0][3].set(42)
        e.copy_item(e.select_node('ROOT/ARR'), 0)
        out = self.run_diff(encode(16), e.dumps())
        self.assertIn('~ ROOT@3: -5 -> 42', out)
        self.assertTrue(any(x.startswith('+ ROOT/ARR[2]') for x in out), out)
        self.assertFalse(any('ARR' in x for x in self.run_diff(encode(16), e.dumps(), skip='ARR')))

    def test_nan_is_not_a_change(self):
        a = E.Esf(encode(16))
        a.select('ROOT')[0][9].set(float('nan'))
        raw = a.dumps()
        self.assertEqual(self.run_diff(raw, raw.replace(struct.pack('<I', 1234), struct.pack('<I', 999), 1)), [])

    def test_skip_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, 'noise.txt', b'# noise\nCAI_INTERFACE\n\nQUAD_TREE_BIT_ARRAY  # fog\n')
            self.assertEqual(esf_diff.skip_names('@%s,X' % p), {'CAI_INTERFACE', 'QUAD_TREE_BIT_ARRAY', 'X'})


# ---- a small save built from esf_edit nodes with the synthetic Tree builder, walked by the generic esf_map
def V(tag, v):
    n = E.Val(tag, b'')
    n.set(v)
    return n


class Tree:
    def __init__(self):
        self.names = []

    def n(self, name):
        if name not in self.names:
            self.names.append(name)
        return self.names.index(name)

    def rec(self, name, kids, ver=0):
        return E.Rec(self.n(name), ver, kids)

    def arr(self, name, items):
        return E.RArr(self.n(name), 0, items)


def synthetic_save():
    """WORLD with two OWNERs (ids 10 and 20) whose MEMBER_ARRAY items hold ids, and a PLACE that names owner 10 and its own id 4242,
    which owner 20's LINK record names too: the walker must find each link from both ends."""
    t = Tree()

    def member(mid, kind, x):
        return [t.rec('MEMBER', [V(0x08, mid), V(0x0e, kind), V(0x04, x), V(0x48, [mid, 1])])]

    def owner(oid, key, members, extra=()):
        return [t.rec('OWNER', [V(0x08, oid), V(0x0e, key), t.arr('MEMBER_ARRAY', members), *extra])]

    a = owner(10, 'owner_a', [member(77, 'scout', -5), member(88, 'clerk', 9)])
    b = owner(20, 'owner_b', [member(99, 'runner', 0)], [t.rec('LINK', [V(0x08, 4242)])])
    place = t.rec('PLACE', [V(0x0e, 'place_x'), V(0x08, 10), V(0x08, 4242), t.rec('CAI_INTERFACE', [V(0x08, 4242)])])
    world = t.rec('WORLD', [t.arr('OWNER_ARRAY', [a, b]), t.rec('PLACES', [place])])
    root = t.rec('SAVE_ROOT', [world], ver=5)
    e = E.Esf.__new__(E.Esf)
    e.magic, e.zero, e.ts, e.names, e.tail, e.unknown, e.nodes = 0xABCE, 0, 1, t.names, b'', [], [root]
    return e.dumps()


class Walker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = synthetic_save()
        self.path = write(self.tmp.name, 's.save', self.raw)
        self.s = esf_map.Save(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_built_save_round_trips(self):
        self.assertEqual(E.Esf(self.raw).dumps(), self.raw)

    def test_records_items_and_values_by_position(self):
        world = self.s.sub(self.s.root(), 'WORLD')
        owners = self.s.items(world, 'OWNER_ARRAY')
        self.assertEqual(len(owners), 2)
        name, span = self.s.item_rec(owners[0])
        self.assertEqual(name, 'OWNER')
        self.assertEqual((self.s.vals(span)[0], self.s.vals(span)[1]), (10, 'owner_a'))
        members = self.s.items(span, 'MEMBER_ARRAY')
        got = [self.s.vals(self.s.item_rec(m)[1]) for m in members]
        self.assertEqual([(v[0], v[1], v[2], v[3]) for v in got], [(77, 'scout', -5, [77, 1]), (88, 'clerk', 9, [88, 1])])
        place = self.s.chain(self.s.root(), 'WORLD', 'PLACES', 'PLACE')
        self.assertEqual(self.s.vals(place)[0], 'place_x')
        with self.assertRaises(KeyError):
            self.s.chain(self.s.root(), 'WORLD', 'NOWHERE')
        self.assertEqual(len(self.s.path('OWNER_ARRAY', 'OWNER')), 2)

    def test_grep_id_finds_both_ends_outside_the_skipped_records(self):
        self.assertEqual(esf_map.grep_id(self.s, 4242), ['/WORLD/OWNER_ARRAY[1]/OWNER/LINK@0', '/WORLD/PLACES/PLACE@2'])
        self.assertEqual(esf_map.grep_id(self.s, 77), ['/WORLD/OWNER_ARRAY[0]/OWNER/MEMBER_ARRAY[0]/MEMBER@0',
                                                       '/WORLD/OWNER_ARRAY[0]/OWNER/MEMBER_ARRAY[0]/MEMBER@3'])


if __name__ == '__main__':
    unittest.main()
