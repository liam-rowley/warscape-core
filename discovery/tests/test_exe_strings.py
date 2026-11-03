"""discovery/exe_strings.py: string scan rules and the find mode, on synthetic bytes and a synthetic table (no exe, no RE venv)."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import _env  # noqa: F401,E402  (paths and the fixture adapter)
import exe_strings  # noqa: E402
import tsvgz  # noqa: E402


def fake_image(rdata, text_flags=0x60000020, data_flags=0x40000040):
    """.text (executable, holds a string that must be skipped) at RVA 0x1000, .rdata at RVA 0x2000"""
    text = b'\x90' * 16 + b'in_code_string\0'
    img = b'\0' * 0x1000 + text.ljust(0x1000, b'\0') + rdata.ljust(0x1000, b'\0')
    sec = lambda n, va, raw, fl: SimpleNamespace(Name=n, VirtualAddress=va, SizeOfRawData=raw, Misc_VirtualSize=raw, Characteristics=fl)
    return SimpleNamespace(base=0x400000, img=img, pe=SimpleNamespace(sections=[
        sec(b'.text\0\0\0', 0x1000, 0x1000, text_flags), sec(b'.rdata\0\0', 0x2000, 0x1000, data_flags)]))


class Scan(unittest.TestCase):
    def test_rules(self):
        rdata = (b'abc\0'                                   # 3 chars: too short
                 + b'imposter distance\0'                   # ASCII at +4
                 + b'\0\0'                                  # pad to an even offset for the wide string
                 + 'SPRITE_FACING'.encode('utf-16-le') + b'\0\0'
                 + b'no terminator')                        # runs into the zero padding: still NUL-terminated, kept
        got = exe_strings.scan(fake_image(rdata))
        texts = {(enc, t): va for va, _, enc, t in got}
        self.assertIn(('a', 'imposter distance'), texts)
        self.assertEqual(texts[('a', 'imposter distance')], 0x402004)
        self.assertIn(('u', 'SPRITE_FACING'), texts)
        self.assertNotIn(('a', 'abc'), texts)
        self.assertFalse(any(t == 'in_code_string' for _, t in texts), 'executable sections are not scanned')
        self.assertTrue(all(s == '.rdata' for _, s, _, _ in got))


class Find(unittest.TestCase):
    def test_find_and_refs_filter(self):
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / 's.tsv.gz'
            tsvgz.write(t, exe_strings.HEADER, [
                ('0x0f3c2f0', '.rdata', 'a', 17, 1, '0x0015583', 0, '', 'imposter distance'),
                ('0x0f3c318', '.rdata', 'a', 23, 0, '', 0, '', 'large imposter distance'),
            ])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                hits = exe_strings.find(str(t), 'imposter')
            self.assertEqual(len(hits), 2)
            self.assertIn('0x0015583', out.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                hits = exe_strings.find(str(t), 'imposter', refs_only=True)
            self.assertEqual([h[8] for h in hits], ['imposter distance'])


if __name__ == '__main__':
    unittest.main()
