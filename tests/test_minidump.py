"""Host tests for warscape/minidump.py (W35): the minidump reader on hand-built dumps (header, directory, exception, module list, thread
list, thread info, memory ranges), named errors for bad dumps (never a traceback), the GNU ld map reader, the map normaliser build.sh runs
and the PE header read. `build_dump` is the builder test_crash_verb.py reuses."""
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from warscape import minidump  # noqa: E402

MDMP = 0x504d444d


def x86_context(eip, esp, ebp=0):
    """A 716-byte x86 CONTEXT with eip, esp and ebp set (the offsets winnt.h gives)."""
    b = bytearray(716)
    struct.pack_into('<I', b, 0, 0x1003f)
    struct.pack_into('<I', b, 0xB4, ebp)
    struct.pack_into('<I', b, 0xB8, eip)
    struct.pack_into('<I', b, 0xC4, esp)
    return bytes(b)


class _Blob:
    def __init__(self):
        self.b = bytearray(32)
        self.streams = []

    def put(self, data):
        while len(self.b) % 4:
            self.b.append(0)
        rva = len(self.b)
        self.b += data
        return rva

    def stream(self, kind, data):
        self.streams.append((kind, len(data), self.put(data)))


def build_dump(exc=None, modules=(), threads=(), memory=(), mem64=False, pad=False, arch=0, thread_info=(), signature=MDMP,
               nstreams=None, raw_streams=()):
    """A minidump as bytes. exc = (thread id, code, address, params, context); modules = [(name, base, size)]; threads = [(id, stack
    start, stack bytes, context)]; memory = [(start, bytes)] (MemoryListStream, or Memory64ListStream with mem64); pad = the 4 bytes some
    writers put after a list's count; arch = SystemInfoStream processor architecture (0 x86, 9 amd64; None = no stream); thread_info =
    [(id, start address)]; raw_streams = [(type, bytes)] added as they are."""
    d = _Blob()
    p4 = b'\0\0\0\0' if pad else b''
    if arch is not None:
        d.stream(7, struct.pack('<HHH', arch, 0, 0) + bytes(50))
    if exc:
        tid, code, addr, params, ctx = exc
        crva = d.put(ctx)
        full = list(params) + [0] * (15 - len(params))
        d.stream(6, struct.pack('<II', tid, 0) + struct.pack('<IIQQII', code, 0, 0, addr, len(params), 0) + struct.pack('<15Q', *full)
                 + struct.pack('<II', len(ctx), crva))
    if modules:
        ents = []
        for name, base, size in modules:
            s = name.encode('utf-16-le')
            nrva = d.put(struct.pack('<I', len(s)) + s + b'\0\0')
            ents.append(struct.pack('<QIIII', base, size, 0, 0, nrva) + bytes(52) + bytes(16) + bytes(16))
        d.stream(4, struct.pack('<I', len(ents)) + p4 + b''.join(ents))
    if threads:
        ents = []
        for tid, start, stack, ctx in threads:
            srva = d.put(stack)
            crva = d.put(ctx)
            ents.append(struct.pack('<IIIIQ', tid, 0, 0, 0, 0x7ffd0000) + struct.pack('<QII', start, len(stack), srva) + struct.pack('<II', len(ctx), crva))
        d.stream(3, struct.pack('<I', len(ents)) + p4 + b''.join(ents))
    if thread_info:
        d.stream(17, struct.pack('<III', 12, 64, len(thread_info)) + b''.join(
            struct.pack('<IIIIQQQQQQ', tid, 0, 0, 0, 0, 0, 0, 0, start, 0) for tid, start in thread_info))
    if memory and not mem64:
        ents = [struct.pack('<QII', start, len(data), d.put(data)) for start, data in memory]
        d.stream(5, struct.pack('<I', len(ents)) + p4 + b''.join(ents))
    if memory and mem64:
        while len(d.b) % 4:
            d.b.append(0)
        hdr_len = 16 + 16 * len(memory)
        hdr_rva = len(d.b)
        base = hdr_rva + hdr_len
        hdr = struct.pack('<QQ', len(memory), base) + b''.join(struct.pack('<QQ', s, len(x)) for s, x in memory)
        d.b += hdr + b''.join(x for _, x in memory)
        d.streams.append((9, hdr_len, hdr_rva))
    for kind, data in raw_streams:
        d.stream(kind, data)
    dir_rva = d.put(b''.join(struct.pack('<III', *s) for s in d.streams))
    d.b[0:32] = struct.pack('<IIIIIIQ', signature, 0xa793, len(d.streams) if nstreams is None else nstreams, dir_rva, 0, 0, 0)
    return bytes(d.b)


def sample(**kw):
    """The standard sample: a host exe at 0x400000, the proxy DLL relocated to 0x20000000, a fault at DLL rva 0x1215, a stack at
    0x0030f000 whose words are a DLL code address, an exe address, a DLL data address and a second DLL code address."""
    esp = 0x0030f010
    stack = struct.pack('<8I', 0, 0, 0, 0, 0x20001150, 0x00401234, 0x20005010, 0x20001420)
    ctx = x86_context(0x20001215, esp, 0x0030f040)
    args = dict(exc=(0x2a, 0xC0000005, 0x20001215, [0, 0x18], ctx),
                modules=[('C:\\game\\host.exe', 0x400000, 0x10000), ('C:\\game\\d3d9.dll', 0x20000000, 0x8000)],
                threads=[(0x2a, 0x0030f000, stack, ctx)], memory=[(0x0030f000, stack)], thread_info=[(0x2a, 0x00401000)])
    args.update(kw)
    return build_dump(**args)


class Reader(unittest.TestCase):
    def test_reads_exception_modules_threads_and_memory(self):
        d = minidump.read(sample())
        self.assertEqual(d.arch, 'x86')
        self.assertEqual((d.exception.thread_id, d.exception.code, d.exception.address), (0x2a, 0xC0000005, 0x20001215))
        self.assertEqual(d.exception.params, [0, 0x18])
        self.assertEqual([(m.name, m.base, m.size) for m in d.modules],
                         [('C:\\game\\host.exe', 0x400000, 0x10000), ('C:\\game\\d3d9.dll', 0x20000000, 0x8000)])
        self.assertEqual(d.module_at(0x20001215).basename, 'd3d9.dll')
        self.assertIsNone(d.module_at(0x30000000))
        regs = d.registers(d.exception.context)
        self.assertEqual((regs['ip'], regs['sp'], regs['bp']), (0x20001215, 0x0030f010, 0x0030f040))
        self.assertEqual(d.threads[0].thread_id, 0x2a)
        self.assertEqual(d.thread_start(0x2a), 0x00401000)
        self.assertEqual(d.read_mem(0x0030f010, 8), struct.pack('<2I', 0x20001150, 0x00401234))
        self.assertIsNone(d.read_mem(0x0030f01c, 8))   # runs past the range

    def test_stack_words_from_the_stack_pointer(self):
        d = minidump.read(sample())
        self.assertEqual(minidump.stack_words(d, 0x0030f010),
                         [(0, 0x20001150), (4, 0x00401234), (8, 0x20005010), (12, 0x20001420)])
        self.assertEqual(minidump.stack_words(d, 0x50000000), [])   # no memory at sp: nothing, not an error

    def test_memory64_and_list_padding(self):
        d = minidump.read(sample(mem64=True))
        self.assertEqual(minidump.stack_words(d, 0x0030f010)[0], (0, 0x20001150))
        d = minidump.read(sample(pad=True))
        self.assertEqual(len(d.modules), 2)
        self.assertEqual(minidump.stack_words(d, 0x0030f010)[3], (12, 0x20001420))

    def test_architecture_from_the_context_size_without_system_info(self):
        self.assertEqual(minidump.read(sample(arch=None)).arch, 'x86')

    def test_bad_dumps_give_a_named_error(self):
        good = sample()
        for data, why in ((b'', 'truncated'), (good[:20], 'truncated'), (b'XXXX' + good[4:], 'signature'),
                          (build_dump(arch=None), 'no streams'), (good[:-40], 'outside the file')):
            with self.assertRaises(minidump.DumpError, msg=why) as cm:
                minidump.read(data)
            self.assertIn(why, str(cm.exception))

    def test_every_truncation_is_a_dump_error_or_a_read(self):
        good = sample()
        for n in range(0, len(good), 7):
            try:
                minidump.read(good[:n])
            except minidump.DumpError:
                pass

    def test_code_names(self):
        self.assertEqual(minidump.code_name(0xC0000005), 'EXCEPTION_ACCESS_VIOLATION')
        self.assertEqual(minidump.code_name(0x12345678), 'unknown')
        self.assertEqual(minidump.exception_detail(0xC0000005, [1, 0x10]), 'write at 0x00000010')
        self.assertEqual(minidump.exception_detail(0xC0000005, [0, 0x18]), 'read at 0x00000018')


MAP = """Archive member included to satisfy reference by file (symbol)

/usr/lib/gcc/i686-w64-mingw32/13-win32/libgcc.a(_chkstk_ms.o)
                              core/backend.cpp.o (___chkstk_ms)

Discarded input sections

 .text          0x00000000        0x0 core/unused.o

Memory Configuration

Name             Origin             Length             Attributes
*default*        0x00000000         0xffffffff

Linker script and memory map

                0x10000000                __image_base__ = 0x10000000
LOAD core/backend.cpp.o
LOAD out/d3d9.dll.lua/lapi.o
                0x00001000                __section_alignment__ = 0x1000

.text           0x10001000     0x3000
 *(.init)
 *(.text)
 .text          0x10001000      0x200 core/backend.cpp.o
                0x10001000                _Direct3DCreate9@4
                0x10001100                _D3DPERF_BeginEvent@8
 *fill*         0x10001200       0x10
 .text          0x10001210      0x100 out/d3d9.dll.lua/lapi.o
                0x10001210                _lua_gettop
                0x10001230                _lua_settop
 .text$_ZN3wsp4FailEP9lua_StatePKc
                0x10001400       0x40 core/luabridge.cpp.o
                0x10001400                __ZN3wsp4FailEP9lua_StatePKc
                0x10002000                PROVIDE (etext, .)

.data           0x10005000      0x200
 .data          0x10005000      0x100 core/backend.cpp.o
                0x10005010                _g_state
OUTPUT(out/d3d9.dll pei-i386)
"""


class LinkMap(unittest.TestCase):
    def setUp(self):
        self.m = minidump.parse_map(MAP)

    def test_nearest_preceding_symbol_of_the_input_section(self):
        h = self.m.lookup(0x10001215)
        self.assertEqual((h.section, h.symbol, h.offset, h.obj), ('.text', '_lua_gettop', 5, 'out/d3d9.dll.lua/lapi.o'))
        self.assertEqual(self.m.lookup(0x10001235).symbol, '_lua_settop')
        h = self.m.lookup(0x10001150)   # a gap between two symbols: the one before it
        self.assertEqual((h.symbol, h.offset, h.obj), ('_D3DPERF_BeginEvent@8', 0x50, 'core/backend.cpp.o'))

    def test_a_wrapped_input_section_line(self):
        h = self.m.lookup(0x10001420)
        self.assertEqual((h.section, h.symbol, h.offset, h.obj), ('.text', '__ZN3wsp4FailEP9lua_StatePKc', 0x20, 'core/luabridge.cpp.o'))

    def test_no_input_section_and_code_sections(self):
        self.assertIsNone(self.m.lookup(0x10001205))   # in *fill*
        self.assertIsNone(self.m.lookup(0x10009000))
        self.assertTrue(self.m.lookup(0x10001010).code)
        self.assertFalse(self.m.lookup(0x10005010).code)
        self.assertEqual(self.m.image_base, 0x10000000)

    def test_a_text_that_is_no_map(self):
        with self.assertRaises(minidump.MapError):
            minidump.parse_map('hello\n')


RAW = """Linker script and memory map

LOAD /usr/lib/gcc/i686-w64-mingw32/13-win32/../../../../i686-w64-mingw32/lib/dllcrt2.o
LOAD /tmp/ccAb12Cd.o
LOAD /tmp/ccZZ99yy.o
LOAD /tmp/ccQq00Ww.o
LOAD /work/build/proxy/null_game/d3d9.dll.lua/lapi.o
LOAD /work/build/ui/obj/mingw32/rml/Core.o
 .text          0x10001000      0x200 /tmp/ccZZ99yy.o
 .text          0x10001200      0x200 /tmp/ccAb12Cd.o
 .rdata         0x10002000       0x10 /work/src/proxy/src/d3d9.def
OUTPUT(/work/build/proxy/null_game/d3d9.dll pei-i386)
"""


class Normalise(unittest.TestCase):
    def test_temp_objects_by_load_order_and_prefixes(self):
        subs = [('/work/build/proxy/null_game/', 'out/'), ('/work/build/ui/obj/mingw32/', 'ui/'), ('/work/src/proxy/src/', 'core/')]
        out = minidump.normalise_map(RAW, subs, ['backend.cpp', 'dllmain.cpp', 'adapter/adapter.cpp'])
        self.assertIn('LOAD core/backend.cpp.o', out)
        self.assertIn('LOAD core/dllmain.cpp.o', out)
        self.assertIn('LOAD adapter/adapter.cpp.o', out)
        self.assertIn(' .text          0x10001000      0x200 core/dllmain.cpp.o', out)
        self.assertIn('LOAD out/d3d9.dll.lua/lapi.o', out)
        self.assertIn('LOAD ui/rml/Core.o', out)
        self.assertIn('core/d3d9.def', out)
        self.assertIn('OUTPUT(out/d3d9.dll pei-i386)', out)
        self.assertNotIn('/tmp/', out)
        self.assertNotIn('/work/', out)

    def test_a_count_mismatch_refuses(self):
        with self.assertRaises(minidump.MapError):
            minidump.normalise_map(RAW, [], ['backend.cpp'])


def pe_bytes(image_base=0x10000000, size_of_image=0x8000):
    b = bytearray(0x200)
    b[0:2] = b'MZ'
    struct.pack_into('<I', b, 0x3c, 0x80)
    b[0x80:0x84] = b'PE\0\0'
    opt = 0x80 + 4 + 20
    struct.pack_into('<H', b, opt, 0x10b)
    struct.pack_into('<I', b, opt + 28, image_base)
    struct.pack_into('<I', b, opt + 56, size_of_image)
    return bytes(b)


class PeInfo(unittest.TestCase):
    def test_image_base_and_size(self):
        self.assertEqual(minidump.pe_info(pe_bytes()), {'image_base': 0x10000000, 'size_of_image': 0x8000})
        with self.assertRaises(minidump.MapError):
            minidump.pe_info(b'not a pe')


if __name__ == '__main__':
    unittest.main()
