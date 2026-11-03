"""discovery/core/x86re.py walk on synthetic bytes: indirect jmp tail calls and jump tables (J15 review 8, J9 deliverable 0).

Needs capstone (the RE venv: discovery/core/re_env.py); skipped without it. Run with the venv python:
<venv>/Scripts/python -m unittest tests.test_x86re
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'discovery' / 'core'))
try:
    import capstone
    import x86re
    HAVE = True
except ImportError:
    HAVE = False

BASE, TEXT = 0x400000, 0x401000


def image(code, data=b''):
    """an x86re.Image over raw bytes: .text at 0x401000 holding `code`, .data right after holding `data` (no pefile needed)"""
    im = x86re.Image.__new__(x86re.Image)
    im.base = BASE
    pad = b'\0' * (TEXT - BASE)
    tsz = 0x1000
    im.img = pad + code.ljust(tsz, b'\xcc') + data.ljust(0x1000, b'\0')
    im.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    im.sections = [('.text', TEXT, tsz, tsz), ('.data', TEXT + tsz, 0x1000, 0x1000)]
    im.text = im.sections[0]
    im._relocs = []
    return im


@unittest.skipUnless(HAVE, 'capstone is not installed here (the RE venv: discovery/core/re_env.py)')
class Walk(unittest.TestCase):
    def test_jmp_register_is_itail(self):
        w = image(b'\x8b\x01' + b'\xff\xe0').walk(TEXT)          # mov eax,[ecx]; jmp eax
        self.assertEqual(w['itail'], [TEXT + 2])
        self.assertEqual(w['tail'], [])
        self.assertEqual(w['switch'], [])

    def test_jmp_memory_is_itail(self):
        code = b'\x8b\x01' + b'\xff\x60\x10'                        # mov eax,[ecx]; jmp [eax+0x10] (vtable tail call)
        code2 = b'\xff\x25' + struct.pack('<I', TEXT + 0x1000)      # jmp [abs] (import-thunk style)
        self.assertEqual(image(code).walk(TEXT)['itail'], [TEXT + 2])
        self.assertEqual(image(code2).walk(TEXT)['itail'], [TEXT])

    def test_jump_table_is_walked(self):
        table = TEXT + 0x1000
        # cmp eax,2; ja default; jmp [eax*4 + table]; case0: ret; case1: call x; ret; case2/default: ret
        code = bytearray(b'\x83\xf8\x02' + b'\x77\x00' + b'\xff\x24\x85' + struct.pack('<I', table))
        c0 = len(code); code += b'\xc3'
        c1 = len(code); code += b'\xe8' + struct.pack('<i', 0x500 - (c1 + 5)) + b'\xc3'
        c2 = len(code); code += b'\xc3'
        code[4] = c2 - 5                                            # ja -> default
        data = struct.pack('<4I', TEXT + c0, TEXT + c1, TEXT + c2, 0)  # three cases, then a dword outside the window ends it
        w = image(bytes(code), data).walk(TEXT)
        self.assertEqual(w['switch'], [(TEXT + 5, 3)])
        self.assertEqual(w['itail'], [])
        self.assertEqual(w['calls'], [(TEXT + c1, TEXT + 0x500)])  # reached only through the table
        self.assertEqual(sorted(w['rets']), [TEXT + c0, TEXT + c1 + 5, TEXT + c2])

    def test_direct_tail_unchanged(self):
        w = image(b'\xe9' + struct.pack('<i', 0x10000)).walk(TEXT)  # jmp far outside the window
        self.assertEqual(w['tail'], [(TEXT, TEXT + 5 + 0x10000)])
        self.assertEqual(w['itail'], [])


if __name__ == '__main__':
    unittest.main()
