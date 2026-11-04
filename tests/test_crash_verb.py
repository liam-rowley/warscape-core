"""Host tests for `wsc crash symbolise` (W35): a hand-built minidump against a small GNU ld map fixture and its sidecar. The exception
frame is named `section: symbol+offset [object]` and labelled certain; stack words in the DLL are "stack scan" candidates; an address in
no input section prints module+rva only; a sidecar that disagrees with the log, the DLL or the dump refuses (exit 2) unless --force-map,
which prefixes every line `WRONG MAP?`; --build-id fetches the CI artifact through a fake gh; --json; byte-identical output."""
import contextlib
import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location('w35_test_minidump', ROOT / 'tests' / 'test_minidump.py')   # the dump builder, by path
_tm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tm)
MAP, build_dump, sample, x86_context = _tm.MAP, _tm.build_dump, _tm.sample, _tm.x86_context
from warscape.cli import main  # noqa: E402
from warscape.verbs import crash  # noqa: E402

DLL = b'MZ' + bytes(100)
SHA = hashlib.sha256(DLL).hexdigest()


class Symbolise(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        (self.t / 'wsc.toml').write_text('registries_dir = "registries"\n')
        self.dump = self.t / 'a.dmp'
        self.dump.write_bytes(sample())
        self.map = self.t / 'd3d9.map'
        self.map.write_text(MAP)
        self.side({})
        self.dll = self.t / 'd3d9.dll'
        self.dll.write_bytes(DLL)
        self.log = self.t / 'proxy.log'
        self.log.write_text('[0.000] d3d9.dll build abc123 loaded into host.exe\n[0.001] self_hash: sha256 %s bytes 102 build abc123 (hashed in 1 ms)\n' % SHA)

    def tearDown(self):
        self.tmp.cleanup()

    def side(self, over):
        d = {'dll': 'd3d9.dll', 'build_id': 'abc123', 'dll_sha256': SHA, 'image_base': '0x10000000', 'size': 102, 'size_of_image': '0x8000'}
        d.update(over)
        (self.t / 'd3d9.map.json').write_text(json.dumps(d))

    def wsc(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(['--root', str(self.t), 'crash', 'symbolise', *map(str, args)])
        return rc, out.getvalue(), err.getvalue()

    def test_the_exception_frame_is_named_and_certain(self):
        rc, out, err = self.wsc(self.dump, '--map', self.map, '--log', self.log, '--dll', self.dll)
        self.assertEqual(rc, 0, out + err)
        self.assertIn('build abc123', out)
        self.assertIn('0xc0000005 EXCEPTION_ACCESS_VIOLATION (read at 0x00000018)', out)
        lines = out.splitlines()
        frame = [ln for ln in lines if ln.startswith('exception frame:')]
        self.assertEqual(len(frame), 1, out)
        self.assertIn('d3d9.dll+0x1215', frame[0])
        self.assertIn('.text: _lua_gettop+0x5 [out/d3d9.dll.lua/lapi.o]', frame[0])
        self.assertNotIn('stack scan', frame[0])

    def test_stack_hits_are_scan_candidates_by_depth(self):
        rc, out, _ = self.wsc(self.dump, '--map', self.map)
        scan = [ln for ln in out.splitlines() if 'stack scan #' in ln]
        self.assertEqual(len(scan), 2, out)   # the exe word and the DLL data word are not code candidates
        self.assertIn('esp+0x0', scan[0])
        self.assertIn('_D3DPERF_BeginEvent@8+0x50 [core/backend.cpp.o]', scan[0])
        self.assertIn('esp+0xc', scan[1])
        self.assertIn('__ZN3wsp4FailEP9lua_StatePKc+0x20', scan[1])
        self.assertIn('candidates, not frames', out)

    def test_an_address_in_no_input_section_is_module_plus_rva(self):
        self.dump.write_bytes(sample(exc=(0x2a, 0xC0000005, 0x20001205, [0, 0x18], x86_context(0x20001205, 0x0030f010))))
        rc, out, _ = self.wsc(self.dump, '--map', self.map)
        self.assertEqual(rc, 1, out)
        frame = [ln for ln in out.splitlines() if ln.startswith('exception frame:')][0]
        self.assertIn('d3d9.dll+0x1205', frame)
        self.assertIn('no input section', frame)

    def test_a_fault_outside_the_dll_names_no_frame_and_lists_the_modules(self):
        self.dump.write_bytes(sample(exc=(0x2a, 0xC0000005, 0x00401234, [1, 0x10], x86_context(0x00401234, 0x0030f010))))
        rc, out, _ = self.wsc(self.dump, '--map', self.map)
        self.assertEqual(rc, 1, out)
        self.assertIn('host.exe+0x1234', out)
        self.assertIn('modules:', out)
        self.assertIn('0x20000000', out)

    def test_wrong_build_id_or_sha256_or_size_refuses_with_both(self):
        self.log.write_text('[0.000] d3d9.dll build other999 loaded into host.exe\n')
        rc, out, err = self.wsc(self.dump, '--map', self.map, '--log', self.log)
        self.assertEqual(rc, 2)
        self.assertIn('abc123', err)
        self.assertIn('other999', err)
        self.log.write_text('[0.000] d3d9.dll build abc123 loaded into host.exe\n')
        self.dll.write_bytes(b'MZ other')
        rc, _, err = self.wsc(self.dump, '--map', self.map, '--log', self.log, '--dll', self.dll)
        self.assertEqual(rc, 2)
        self.assertIn(SHA, err)
        self.dll.write_bytes(DLL)
        self.side({'size_of_image': '0x9000'})
        rc, _, err = self.wsc(self.dump, '--map', self.map)
        self.assertEqual(rc, 2)
        self.assertIn('0x9000', err)
        self.assertIn('0x8000', err)

    def test_force_map_prefixes_every_line(self):
        self.log.write_text('[0.000] d3d9.dll build other999 loaded into host.exe\n')
        rc, out, _ = self.wsc(self.dump, '--map', self.map, '--log', self.log, '--force-map')
        self.assertEqual(rc, 0)
        self.assertTrue(out.strip())
        for ln in out.splitlines():
            self.assertTrue(ln.startswith('WRONG MAP? '), ln)

    def test_no_map_and_bad_dumps_refuse_without_a_traceback(self):
        rc, _, err = self.wsc(self.dump)
        self.assertEqual(rc, 2)
        self.assertIn('no map', err)
        self.dump.write_bytes(b'XXXX' + bytes(40))
        rc, _, err = self.wsc(self.dump, '--map', self.map)
        self.assertEqual(rc, 2)
        self.assertIn('signature', err)
        self.assertNotIn('Traceback', err)
        (self.t / 'd3d9.map.json').unlink()
        self.dump.write_bytes(sample())
        rc, _, err = self.wsc(self.dump, '--map', self.map)
        self.assertEqual(rc, 2)
        self.assertIn('sidecar', err)

    def test_json_fields(self):
        rc, out, _ = self.wsc(self.dump, '--map', self.map, '--json')
        self.assertEqual(rc, 0)
        d = json.loads(out)
        for k in ('build_id', 'exception', 'frame', 'scan', 'modules', 'reproduce', 'wrong_map', 'exit'):
            self.assertIn(k, d)
        self.assertEqual(d['frame']['symbol'], '_lua_gettop')
        self.assertTrue(d['frame']['certain'])
        self.assertEqual([s['symbol'] for s in d['scan']], ['_D3DPERF_BeginEvent@8', '__ZN3wsp4FailEP9lua_StatePKc'])
        self.assertFalse(any(s['certain'] for s in d['scan']))

    def test_output_is_byte_identical(self):
        a = self.wsc(self.dump, '--map', self.map, '--log', self.log)
        b = self.wsc(self.dump, '--map', self.map, '--log', self.log)
        self.assertEqual(a, b)
        self.assertIn('reproduce: ', a[1])

    def test_sites_name_an_exe_rva(self):
        self.dump.write_bytes(sample(exc=(0x2a, 0xC0000005, 0x00401236, [1, 0x10], x86_context(0x00401236, 0x0030f010))))
        sites = self.t / 'engine_sites.jsonl'
        sites.write_text(json.dumps({'id': 'some_site', 'rva': '0x1234', 'anchor_bytes': '8b 45 08 c3'}) + '\n')
        _, out, _ = self.wsc(self.dump, '--map', self.map, '--sites', sites)
        self.assertIn('host.exe+0x1236 (site some_site+0x2)', out)


class BuildId(unittest.TestCase):
    """--build-id: the artifact proxy-map-<id> through gh (faked), into _scratch/maps/<id>/; an expired one is said plainly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        (self.t / 'wsc.toml').write_text('registries_dir = "registries"\n')
        self.dump = self.t / 'a.dmp'
        self.dump.write_bytes(sample())
        self.calls = []
        self.real = crash.gh

    def tearDown(self):
        crash.gh = self.real
        self.tmp.cleanup()

    def fake(self, artifacts):
        def gh(args, cwd):
            self.calls.append(args)
            if args[0] == 'api':
                return 0, json.dumps({'total_count': len(artifacts), 'artifacts': artifacts}), ''
            if args[:2] == ['run', 'download']:
                d = Path(args[args.index('-D') + 1])
                d.mkdir(parents=True, exist_ok=True)
                (d / 'd3d9.map').write_text(MAP)
                (d / 'd3d9.map.json').write_text(json.dumps({'dll': 'd3d9.dll', 'build_id': 'abc123', 'dll_sha256': SHA,
                                                             'image_base': '0x10000000', 'size': 102, 'size_of_image': '0x8000'}))
                return 0, '', ''
            return 1, '', 'unexpected'
        crash.gh = gh

    def wsc(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(['--root', str(self.t), 'crash', 'symbolise', *map(str, args)])
        return rc, out.getvalue(), err.getvalue()

    def test_finds_downloads_and_symbolises(self):
        self.fake([{'name': 'proxy-map-abc123', 'expired': False, 'workflow_run': {'id': 77, 'head_branch': 'main'}, 'created_at': '2026-11-04T00:00:00Z'},
                   {'name': 'proxy-map-abc123', 'expired': False, 'workflow_run': {'id': 70, 'head_branch': 'job/W1'}, 'created_at': '2026-11-01T00:00:00Z'}])
        rc, out, err = self.wsc(self.dump, '--build-id', 'abc123')
        self.assertEqual(rc, 0, out + err)
        dl = [c for c in self.calls if c[:2] == ['run', 'download']][0]
        self.assertEqual(dl[2], '77')
        self.assertIn('proxy-map-abc123', dl)
        self.assertTrue((self.t / '_scratch' / 'maps' / 'abc123' / 'd3d9.map').exists())
        self.assertIn('_lua_gettop', out)

    def test_run_names_one(self):
        self.fake([{'name': 'proxy-map-abc123', 'expired': False, 'workflow_run': {'id': 77, 'head_branch': 'main'}, 'created_at': '2026-11-04T00:00:00Z'},
                   {'name': 'proxy-map-abc123', 'expired': False, 'workflow_run': {'id': 70, 'head_branch': 'job/W1'}, 'created_at': '2026-11-01T00:00:00Z'}])
        rc, _, _ = self.wsc(self.dump, '--build-id', 'abc123', '--run', '70')
        self.assertEqual(rc, 0)
        self.assertEqual([c for c in self.calls if c[:2] == ['run', 'download']][0][2], '70')

    def test_an_expired_artifact_is_said_plainly(self):
        self.fake([{'name': 'proxy-map-abc123', 'expired': True, 'workflow_run': {'id': 77, 'head_branch': 'main'}, 'created_at': '2026-01-04T00:00:00Z'}])
        rc, _, err = self.wsc(self.dump, '--build-id', 'abc123')
        self.assertEqual(rc, 2)
        self.assertIn('expired', err)
        self.assertIn('kept 90 days; the release attaches its own', err)
        self.assertFalse([c for c in self.calls if c[:2] == ['run', 'download']])

    def test_no_artifact(self):
        self.fake([])
        rc, _, err = self.wsc(self.dump, '--build-id', 'abc123')
        self.assertEqual(rc, 2)
        self.assertIn('no artifact proxy-map-abc123', err)


if __name__ == '__main__':
    unittest.main()
