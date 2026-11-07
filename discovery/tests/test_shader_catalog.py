"""The frame-capture reader (shader_catalog.summarize) against the W19 record lines: an SBAPPLY's STATE readback sets the state of the
draws after it without breaking the pass, the new tags it does not know (SBCREATE, SBCAPTURE, SBAPPLY, OTHERTHREAD, ABANDONED) change
nothing else, and a frame in the format before W19 gives the same summary as before (C20: the reader is unchanged).

purpose: host test of discovery/shader_catalog.py summarize() on small frame.txt fixtures (docs/PROXY_CAPTURE.md is the format)
usage: python3 -m unittest discovery/tests/test_shader_catalog.py  (the tests gate runs it)
when: every gates run
not-a-verb: a host test, which wsc.toml [tools] exempts
"""
import _env  # noqa: F401  (sys.path and the fixture adapter)
import contextlib
import io
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

import shader_catalog

HEAD = """CAPTURE t launch L build B frames 1 utc 2026-11-03T00:00:00Z scene battle
STATE
SURF a1 1280 720 21 1 0 0 0 0
BACKBUFFER a1
RT 0 a1
RT 1 0
DS 0
VP 0 0 1280 720 0 1
RS 7 1
RS 27 0
ENDSTATE
FRAME 1
CLEAR 0 1 ff000000 1 0
SHADER b1 vs 00000000000000aa 100 100
VS 00000000000000aa
SHADER b2 ps 00000000000000bb 100 100
PS 00000000000000bb
DIP 4 0 0 3 0 1
"""
TAIL = """DIP 4 0 0 3 0 2
PRESENT
"""
# an effect's state block, applied between the two draws: alpha blending on, read back as the W19 driver writes it (no RT, DS, BACKBUFFER)
APPLY = """SBCREATE 1 c1
SBCAPTURE c1
SBAPPLY c1
STATE
VP 0 0 1280 720 0 1
RS 7 1
RS 27 1
TSS 0 1 4
SS 0 5 2
T 0 0
VS 00000000000000aa
PS 00000000000000bb
ENDSTATE
"""

# The summary of HEAD + TAIL, written down from the reader as it stood before W19 (it must not change: C20).
OLD_SUMMARY = {
    'header': 'CAPTURE t launch L build B frames 1 utc 2026-11-03T00:00:00Z scene battle', 'draws': 2,
    'backbuffer': {'id': 'rt1', 'w': 1280, 'h': 720, 'fmt': 'A8R8G8B8', 'ms': 0, 'texture': False, 'backbuffer': True},
    'surfaces': {'rt1': {'w': 1280, 'h': 720, 'fmt': 'A8R8G8B8', 'usage': 1, 'pool': 0, 'ms': 0, 'texture': False, 'backbuffer': True}},
    'passes': [{'index': 0, 'rt': [{'id': 'rt1', 'w': 1280, 'h': 720, 'fmt': 'A8R8G8B8', 'ms': 0, 'texture': False, 'backbuffer': True}],
                'ds': None, 'clear': {'flags': 1, 'color': 'ff000000', 'z': 1.0, 'stencil': 0}, 'draws': 2, 'prims': 3, 'events': [],
                'viewport': [0, 0, 1280, 720], 'pairs': {'00000000000000aa/00000000000000bb': 2}, 'states': {'z10 cwf blend0 cull0': 2},
                'reads_rt': [], 'reads_from_pass': []}],
    'events': [],
    'shaders': {'00000000000000aa': {'draws': 2, 'prims': 3, 'passes': [0], 'pairs': {'00000000000000aa/00000000000000bb': 2}, 'consts': None},
                '00000000000000bb': {'draws': 2, 'prims': 3, 'passes': [0], 'pairs': {'00000000000000aa/00000000000000bb': 2}, 'consts': None}},
}


class ImportAndDensity(unittest.TestCase):
    def run_import(self, d, names):
        src = Path(d) / 'cap'
        (src / 'shaders').mkdir(parents=True)
        (src / 'good').mkdir()
        (src / 'good' / 'frame.txt').write_text(HEAD, encoding='utf-8')
        (src / 'bad').mkdir()
        out = io.StringIO()
        with mock.patch.object(shader_catalog, 'ROOT', Path(d)), mock.patch.object(shader_catalog, 'SHADERS', Path(d) / 'shaders'), \
                mock.patch.object(shader_catalog, 'RUNS', Path(d) / 'runs'), contextlib.redirect_stdout(out):
            shader_catalog.main(['import', '--run', 'r', '--captures', str(src), '--name', *names])
        return out.getvalue()

    def test_import_skips_and_lists_a_missing_capture(self):
        with tempfile.TemporaryDirectory() as d:
            text = self.run_import(d, ['good', 'bad'])
            self.assertIn('1 of 2 captures imported; no frame.txt in: bad', text)
            self.assertTrue((Path(d) / 'runs' / 'r' / 'captures' / 'good.json').exists())

    def test_import_with_no_capture_exits_non_zero(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(SystemExit) as e:
            self.run_import(d, ['bad'])
        self.assertTrue(e.exception.code)

    def density(self, argv):
        out = io.StringIO()
        with mock.patch.object(shader_catalog, 'shadow_density', return_value={}), contextlib.redirect_stdout(out):
            shader_catalog.main(['density', *argv])
        return out.getvalue().splitlines()

    def test_density_reads_paths_from_a_file_and_stdin(self):
        with tempfile.TemporaryDirectory() as d:
            caps = []
            for i in range(100):
                caps.append(os.path.join(d, f'c{i}.json'))
                Path(caps[-1]).write_text('{}', encoding='utf-8')
            listing = os.path.join(d, 'list.txt')
            Path(listing).write_text('\n'.join(caps) + '\n\n', encoding='utf-8')
            self.assertEqual(len(self.density(['--from-file', listing])), 100)
            with mock.patch('sys.stdin', io.StringIO('\n'.join(caps[:3]))):
                self.assertEqual(len(self.density(['--from-file', '-'])), 3)
            self.assertEqual(len(self.density(caps[:2])), 2)

    def test_density_with_no_paths_is_an_error(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            shader_catalog.main(['density'])


class Summarize(unittest.TestCase):
    def summary(self, text):
        fd, path = tempfile.mkstemp(suffix='.txt')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(text.encode())
            with warnings.catch_warnings():   # summarize leaves its file to the garbage collector (unchanged reader: C20)
                warnings.simplefilter('ignore', ResourceWarning)
                return shader_catalog.summarize(path, {})
        finally:
            os.unlink(path)

    def test_old_format_unchanged(self):
        self.assertEqual(self.summary(HEAD + TAIL), OLD_SUMMARY)

    def test_unknown_w19_tags_change_nothing(self):
        text = HEAD + 'SBCREATE 1 c1\nSBCAPTURE c1\nOTHERTHREAD 12\n' + TAIL.replace('PRESENT\n', 'OTHERTHREAD 3\nABANDONED frame 1 of 1\n')
        self.assertEqual(self.summary(text), OLD_SUMMARY)

    def test_sbapply_readback_sets_the_next_draws_state(self):
        s = self.summary(HEAD + APPLY + TAIL)
        self.assertEqual(len(s['passes']), 1)             # the readback keeps the pass (no RT or DS inside it)
        p = s['passes'][0]
        self.assertEqual(p['draws'], 2)
        self.assertEqual(p['states'], {'z10 cwf blend0 cull0': 1, 'z10 cwf blend1 cull0': 1})   # the second draw has the applied blend
        self.assertEqual(p['pairs'], {'00000000000000aa/00000000000000bb': 2})


if __name__ == '__main__':
    unittest.main()
