"""Host tests for the Lua API discovery pass (discovery/core/lua_api.py): pure logic on synthetic Lua 5.1 chunks and name sets."""
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'discovery', 'core'))
import diffout  # noqa: E402
import lua_api  # noqa: E402
import luachunk  # noqa: E402

RK = 256


def chunk(code, consts):
    """A minimal Lua 5.1 chunk (Warscape layout): one main function, no protos, strings as constants."""
    o = bytearray(luachunk.HEADER)
    u32 = lambda v: o.extend(struct.pack('<I', v))
    u32(0)                                      # source: none
    o.extend(struct.pack('<ii', 0, 0))          # line, lastline
    o.extend(bytes([0, 0, 2, 8]))               # nups, nparams, vararg, maxstack
    u32(len(code))
    for w in code:
        u32(w)
    u32(len(consts))
    for c in consts:
        o.append(4)
        u32(len(c) + 1)
        o.extend(c.encode() + b'\0')
    u32(0)                                      # protos
    u32(0)                                      # lineinfo
    u32(0)                                      # locals
    u32(0)                                      # upvalues
    return bytes(o)


def sample():
    e = luachunk.enc
    code = [
        e('GETGLOBAL', 0, bx=0), e('GETTABLE', 1, 0, RK + 1), e('CALL', 1, 1, 1),   # CampaignUI.Foo()
        e('GETGLOBAL', 0, bx=2), e('SELF', 0, 0, RK + 3), e('CALL', 0, 2, 1),       # UIComponent:SetVisible()
        e('GETGLOBAL', 0, bx=4), e('CALL', 0, 1, 1),                                # Bar()
        e('GETGLOBAL', 0, bx=5), e('SETGLOBAL', 0, bx=6),                           # OnClicked = ...
        e('RETURN', 0, 1),
    ]
    return chunk(code, ['CampaignUI', 'Foo', 'UIComponent', 'SetVisible', 'Bar', 'X', 'OnClicked'])


class LuaApi(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.tmp = Path(self._d.name)

    def test_chunk_parses_and_roundtrips(self):
        d = sample()
        self.assertEqual(luachunk.parse(d).serialise(), d)


    def test_inventory_picks_out_global_table_and_method_calls(self):
        tmp_path = self.tmp
        p = tmp_path / 'a.luac'
        p.write_bytes(sample())
        j, per_file, failed = lua_api.inventory({'ui' + chr(92) + 'a.luac': str(p)})
        self.assertFalse(failed)
        assert set(j['calls']) == {'CampaignUI.Foo', 'Bar'}
        assert set(j['methods']) == {'SetVisible'}
        assert set(j['events']) == {'OnClicked'}
        assert per_file['ui/a.luac'] == {'calls': 2, 'methods': 1, 'events': 1}
        fam, tables = lua_api.families(j)
        assert fam['engine globals'] == {'Bar'}
        assert tables == {'CampaignUI': {'CampaignUI.Foo'}}


    def test_bad_script_is_reported_not_fatal(self):
        tmp_path = self.tmp
        p = tmp_path / 'bad.luac'
        p.write_bytes(b'\x1bLuaQ\x00\x01\x04\x04\x04\x04\x00junk')
        _, _, failed = lua_api.inventory({'ui' + chr(92) + 'bad.luac': str(p)})
        assert failed and failed[0][0] == 'ui/bad.luac'


    def test_classify_same_adapter_new_gone(self):
        assert lua_api.classify({'a'}, {'a'}) == ('same', '')
        assert lua_api.classify({'a', 'b'}, {'b', 'c'})[0] == 'adapter'
        assert lua_api.classify(set(), {'a'})[0] == 'new'
        assert lua_api.classify({'a'}, set())[0] == 'gone'
        assert lua_api.status({'a', 'b'}, {'b', 'c'}) == {'a': 'gone', 'b': 'same', 'c': 'new'}


    def test_entry_points_ignore_comments(self):
        t = '--[[ require "x.y" ]]\nlocal m = require "data.m"\n-- Foo = 1\nevents = m.events\nfunction go() end\n'
        assert lua_api.lua_entry_points(t) == {'require': ['data.m'], 'functions': ['go'], 'globals': ['events']}


    def test_build_output_passes_schema(self):
        tmp_path = self.tmp
        p = tmp_path / 'a.luac'
        p.write_bytes(sample())
        empire = {'calls': {'CampaignUI.Foo': {'n': 1, 'scripts': ['ui/a.luac'], 'sigs': {'()': 1}}},
                  'methods': {}, 'global_reads': {}, 'defined': {}, 'events': {}, 'fields_set': {}}
        rows, detail = lua_api.build(empire, {'ui' + chr(92) + 'a.luac': str(p)}, ['events.lua'], {}, {})
        out = tmp_path / 'lua_api.json'
        diffout.write(str(out), 'lua_api', rows, detail)
        assert diffout.problems(json.load(open(out))) == []
        by = {r['item']: r for r in rows}
        assert by['engine globals']['verdict'] == 'new'
        assert by['component methods']['verdict'] == 'new'
        assert by['CampaignUI.*']['verdict'] == 'same'


if __name__ == '__main__':
    unittest.main()
