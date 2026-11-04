"""Minidumps and GNU ld maps, standard library only (W35, C30): what `wsc crash symbolise` reads, and the map normaliser `build.sh` runs.

The minidump reader takes the streams that say what happened (minidumpapiset.h layouts, little-endian, `struct` only): ExceptionStream
(code, address, thread, the context record), ModuleListStream (name, base, size), ThreadListStream and ThreadInfoListStream (the faulting
thread, its start address), MemoryListStream or Memory64ListStream (the bytes that exist: the proxy's in-process dump has the stacks and
the memory they reference, no full memory), SystemInfoStream (the architecture; without it, the context size says). Some writers put four
bytes of padding after a list's count; the reader accepts both. A bad dump raises DumpError with a named reason, never another exception.

The map reader parses the "Linker script and memory map" part of a GNU ld `-Map` file: output sections, the input sections in them
(`.text 0x... 0x... <object>`, also wrapped onto two lines when the section name is long) and the global symbols each lists. `lookup(va)`
gives the nearest preceding symbol of the input section holding va (a static function shows as the nearest preceding global of its
object: the map lists globals only), or None when no input section holds it.

`normalise_map` makes a raw map reproducible: checkout paths become labels (core/, adapter/, out/, ui/) and gcc's temporary objects
(`/tmp/ccXXXXXX.o`, one per source compiled in the link command) are named after their sources, in the order the LOAD lines give, which
is the command line's. `write_map(argv)` is the entry `build.sh` calls: it writes `d3d9.map` and the sidecar `d3d9.map.json`
({dll, build_id, dll_sha256, image_base, size, size_of_image}) beside the DLL, with no timestamp in either.
"""
import hashlib
import json
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path


class DumpError(Exception):
    """A minidump this reader cannot use; the message names why."""


class MapError(Exception):
    """A linker map (or a PE file) this reader cannot use; the message names why."""


SIGNATURE = 0x504d444d   # 'MDMP'
THREAD_LIST, MODULE_LIST, MEMORY_LIST, EXCEPTION, SYSTEM_INFO, MEMORY64_LIST, THREAD_INFO_LIST = 3, 4, 5, 6, 7, 9, 17
X86_CONTEXT_SIZE, AMD64_CONTEXT_SIZE = 716, 1232

CODES = {
    0xC0000005: 'EXCEPTION_ACCESS_VIOLATION', 0xC0000006: 'EXCEPTION_IN_PAGE_ERROR', 0xC0000008: 'EXCEPTION_INVALID_HANDLE',
    0xC000001D: 'EXCEPTION_ILLEGAL_INSTRUCTION', 0xC0000025: 'EXCEPTION_NONCONTINUABLE_EXCEPTION', 0xC0000026: 'EXCEPTION_INVALID_DISPOSITION',
    0xC000008C: 'EXCEPTION_ARRAY_BOUNDS_EXCEEDED', 0xC000008D: 'EXCEPTION_FLT_DENORMAL_OPERAND', 0xC000008E: 'EXCEPTION_FLT_DIVIDE_BY_ZERO',
    0xC000008F: 'EXCEPTION_FLT_INEXACT_RESULT', 0xC0000090: 'EXCEPTION_FLT_INVALID_OPERATION', 0xC0000091: 'EXCEPTION_FLT_OVERFLOW',
    0xC0000092: 'EXCEPTION_FLT_STACK_CHECK', 0xC0000093: 'EXCEPTION_FLT_UNDERFLOW', 0xC0000094: 'EXCEPTION_INT_DIVIDE_BY_ZERO',
    0xC0000095: 'EXCEPTION_INT_OVERFLOW', 0xC0000096: 'EXCEPTION_PRIV_INSTRUCTION', 0xC00000FD: 'EXCEPTION_STACK_OVERFLOW',
    0xC000041D: 'STATUS_FATAL_USER_CALLBACK_EXCEPTION', 0xC0000374: 'STATUS_HEAP_CORRUPTION', 0xC0000409: 'STATUS_STACK_BUFFER_OVERRUN', 0xC0000420: 'STATUS_ASSERTION_FAILURE',
    0x80000001: 'EXCEPTION_GUARD_PAGE', 0x80000002: 'EXCEPTION_DATATYPE_MISALIGNMENT', 0x80000003: 'EXCEPTION_BREAKPOINT',
    0x80000004: 'EXCEPTION_SINGLE_STEP', 0xE06D7363: 'MSVC C++ exception', 0x20474343: 'GCC C++ exception',
}


def code_name(code):
    return CODES.get(code, 'unknown')


def exception_detail(code, params):
    """The access violation's operation and address (params[0] 0 read, 1 write, 8 execute; params[1] the address), else ''."""
    if code in (0xC0000005, 0xC0000006) and len(params) >= 2:
        op = {0: 'read', 1: 'write', 8: 'execute'}.get(params[0], f'operation {params[0]}')
        return f'{op} at 0x{params[1]:08x}'
    return ''


@dataclass
class Module:
    name: str
    base: int
    size: int

    @property
    def basename(self):
        return re.split(r'[\\/]', self.name)[-1]


@dataclass
class Exception_:
    thread_id: int
    code: int
    flags: int
    address: int
    params: list
    context: bytes


@dataclass
class Thread:
    thread_id: int
    stack_start: int
    stack: bytes
    context: bytes


@dataclass
class Dump:
    arch: str
    exception: object = None
    modules: list = field(default_factory=list)
    threads: list = field(default_factory=list)
    memory: list = field(default_factory=list)   # [(start, bytes)]
    starts: dict = field(default_factory=dict)   # thread id -> start address (ThreadInfoListStream)

    @property
    def word(self):
        return 8 if self.arch == 'amd64' else 4

    def module_at(self, addr):
        for m in self.modules:
            if m.base <= addr < m.base + m.size:
                return m
        return None

    def module_named(self, name):
        n = name.lower()
        for m in self.modules:
            if m.basename.lower() == n:
                return m
        return None

    def read_mem(self, addr, n):
        for start, data in self.memory:
            if start <= addr and addr + n <= start + len(data):
                return data[addr - start:addr - start + n]
        for t in self.threads:
            if t.stack_start <= addr and addr + n <= t.stack_start + len(t.stack):
                return t.stack[addr - t.stack_start:addr - t.stack_start + n]
        return None

    def range_at(self, addr):
        """(start, bytes) of the memory that holds addr, or None."""
        for start, data in list(self.memory) + [(t.stack_start, t.stack) for t in self.threads]:
            if start <= addr < start + len(data):
                return start, data
        return None

    def registers(self, ctx):
        """ip, sp and bp from a context record of this dump's architecture (None when the record is too short)."""
        if self.arch == 'amd64':
            if len(ctx) < 0x100:
                return None
            sp, bp, ip = struct.unpack_from('<Q', ctx, 0x98)[0], struct.unpack_from('<Q', ctx, 0xA0)[0], struct.unpack_from('<Q', ctx, 0xF8)[0]
        else:
            if len(ctx) < 0xC8:
                return None
            bp, ip, sp = struct.unpack_from('<I', ctx, 0xB4)[0], struct.unpack_from('<I', ctx, 0xB8)[0], struct.unpack_from('<I', ctx, 0xC4)[0]
        return {'ip': ip, 'sp': sp, 'bp': bp}

    def thread_start(self, tid):
        return self.starts.get(tid)


def _at(data, off, fmt, what):
    n = struct.calcsize(fmt)
    if off < 0 or off + n > len(data):
        raise DumpError(f'{what} at 0x{off:x} runs outside the file ({len(data)} bytes)')
    return struct.unpack_from(fmt, data, off)


def _blob(data, rva, size, what):
    if rva + size > len(data):
        raise DumpError(f'{what} at 0x{rva:x} ({size} bytes) runs outside the file ({len(data)} bytes)')
    return data[rva:rva + size]


def _list_start(data, rva, size, count, entry, what):
    """The offset of a list's first entry: right after the 4-byte count, or after 4 more bytes of padding when the stream size says so."""
    if size == 4 + count * entry:
        return rva + 4
    if size == 8 + count * entry:
        return rva + 8
    if size < 4 + count * entry:
        raise DumpError(f'{what}: {count} entries do not fit its {size} bytes')
    return rva + 4


def read(data):
    """A Dump from the bytes of a minidump; DumpError (named) on anything it cannot read."""
    if len(data) < 32:
        raise DumpError(f'truncated: {len(data)} bytes, a minidump header is 32')
    sig, _ver, nstreams, dir_rva = struct.unpack_from('<IIII', data, 0)
    if sig != SIGNATURE:
        raise DumpError(f'bad signature {data[:4]!r}: not a minidump (MDMP)')
    if nstreams == 0:
        raise DumpError('no streams: the header lists none')
    if nstreams > 4096:
        raise DumpError(f'{nstreams} streams: not a minidump this reader trusts')
    streams = {}
    for i in range(nstreams):
        kind, size, rva = _at(data, dir_rva + 12 * i, '<III', 'the stream directory')
        streams.setdefault(kind, (size, rva))
    arch = None
    if SYSTEM_INFO in streams:
        size, rva = streams[SYSTEM_INFO]
        pa = _at(data, rva, '<H', 'SystemInfoStream')[0]
        arch = {0: 'x86', 9: 'amd64'}.get(pa, f'arch{pa}')
    d = Dump(arch=arch or 'x86')
    if EXCEPTION in streams:
        size, rva = streams[EXCEPTION]
        tid, = _at(data, rva, '<I', 'ExceptionStream')
        code, flags, _rec, addr, nparams, _ = _at(data, rva + 8, '<IIQQII', 'ExceptionStream')
        params = list(_at(data, rva + 40, '<15Q', 'ExceptionStream'))[:min(nparams, 15)]
        csize, crva = _at(data, rva + 160, '<II', 'ExceptionStream context')
        ctx = _blob(data, crva, csize, 'the exception context')
        d.exception = Exception_(tid, code, flags, addr, params, ctx)
        if arch is None and csize == AMD64_CONTEXT_SIZE:
            d.arch = 'amd64'
    if MODULE_LIST in streams:
        size, rva = streams[MODULE_LIST]
        n, = _at(data, rva, '<I', 'ModuleListStream')
        off = _list_start(data, rva, size, n, 108, 'ModuleListStream')
        for i in range(n):
            base, msize, _ck, _ts, nrva = _at(data, off + 108 * i, '<QIIII', 'a module entry')
            ln, = _at(data, nrva, '<I', 'a module name')
            name = _blob(data, nrva + 4, ln, 'a module name').decode('utf-16-le', 'replace')
            d.modules.append(Module(name, base, msize))
    if THREAD_LIST in streams:
        size, rva = streams[THREAD_LIST]
        n, = _at(data, rva, '<I', 'ThreadListStream')
        off = _list_start(data, rva, size, n, 48, 'ThreadListStream')
        for i in range(n):
            e = off + 48 * i
            tid, = _at(data, e, '<I', 'a thread entry')
            sstart, ssize, srva = _at(data, e + 24, '<QII', 'a thread stack')
            csize, crva = _at(data, e + 40, '<II', 'a thread context')
            stack = _blob(data, srva, ssize, 'a thread stack') if ssize else b''
            d.threads.append(Thread(tid, sstart, stack, _blob(data, crva, csize, 'a thread context')))
    if THREAD_INFO_LIST in streams:
        size, rva = streams[THREAD_INFO_LIST]
        hsize, esize, n = _at(data, rva, '<III', 'ThreadInfoListStream')
        if esize >= 56:
            for i in range(n):
                e = rva + hsize + esize * i
                tid, = _at(data, e, '<I', 'a thread info entry')
                d.starts[tid] = _at(data, e + 48, '<Q', 'a thread info entry')[0]
    if MEMORY_LIST in streams:
        size, rva = streams[MEMORY_LIST]
        n, = _at(data, rva, '<I', 'MemoryListStream')
        off = _list_start(data, rva, size, n, 16, 'MemoryListStream')
        for i in range(n):
            start, msize, mrva = _at(data, off + 16 * i, '<QII', 'a memory range')
            d.memory.append((start, _blob(data, mrva, msize, 'a memory range')))
    if MEMORY64_LIST in streams:
        size, rva = streams[MEMORY64_LIST]
        n, base = _at(data, rva, '<QQ', 'Memory64ListStream')
        if n > 1 << 20:
            raise DumpError(f'Memory64ListStream: {n} ranges')
        for i in range(n):
            start, msize = _at(data, rva + 16 + 16 * i, '<QQ', 'a memory64 range')
            d.memory.append((start, _blob(data, base, msize, 'a memory64 range')))
            base += msize
    return d


def stack_words(dump, sp, limit=4096):
    """[(offset from sp, word)] from sp to the end of the memory range that holds it (at most `limit` words); [] without memory at sp."""
    got = dump.range_at(sp)
    if not got:
        return []
    start, data = got
    w = dump.word
    fmt = '<Q' if w == 8 else '<I'
    out = []
    off = sp - start
    while off + w <= len(data) and len(out) < limit:
        out.append((off - (sp - start), struct.unpack_from(fmt, data, off)[0]))
        off += w
    return out


# ---- GNU ld maps -------------------------------------------------------------------------------------------------------------------

@dataclass
class Hit:
    section: str     # the output section (.text)
    symbol: str      # the nearest preceding global symbol, or the input section's name when it lists none before va
    offset: int
    obj: str         # the object file (or archive member) the input section came from
    code: bool       # an executable output section (.text, .init, .fini)


@dataclass
class _In:
    out: str
    name: str
    addr: int
    size: int
    obj: str
    syms: list = field(default_factory=list)   # [(addr, name)]


class LinkMap:
    def __init__(self, inputs, image_base):
        self.inputs = sorted((i for i in inputs if i.size > 0), key=lambda i: i.addr)
        self.image_base = image_base
        self._starts = [i.addr for i in self.inputs]

    def lookup(self, va):
        import bisect
        k = bisect.bisect_right(self._starts, va) - 1
        if k < 0:
            return None
        i = self.inputs[k]
        if not (i.addr <= va < i.addr + i.size):
            return None
        best = None
        for a, n in i.syms:
            if a <= va and (best is None or a >= best[0]):
                best = (a, n)
        sym, base = (best[1], best[0]) if best else (i.name, i.addr)
        return Hit(i.out, sym, va - base, i.obj, i.out.split('$')[0] in ('.text', '.init', '.fini'))


_HEX = r'0x([0-9a-fA-F]+)'
_OUT = re.compile(rf'^(\.\S+)\s+{_HEX}\s+{_HEX}')
_OUT_NAME = re.compile(r'^(\.\S+)\s*$')
_IN = re.compile(rf'^ (\.\S+)\s+{_HEX}\s+{_HEX}\s+(\S.*?)\s*$')
_IN_NAME = re.compile(r'^ (\.\S+)\s*$')
_IN_CONT = re.compile(rf'^\s+{_HEX}\s+{_HEX}\s+(\S.*?)\s*$')
_SYM = re.compile(rf'^\s+{_HEX}\s+(\S.*?)\s*$')
_BASE = re.compile(rf'^\s+{_HEX}\s+__image_base__\s*=')


def parse_map(text):
    """A LinkMap from the text of a GNU ld map; MapError when it has no "Linker script and memory map" part."""
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith('Linker script and memory map'))
    except StopIteration:
        raise MapError('not a GNU ld map: no "Linker script and memory map" section') from None
    inputs, out, cur, pend, image_base = [], None, None, None, None
    for ln in lines[start + 1:]:
        m = _BASE.match(ln)
        if m:
            image_base = int(m.group(1), 16)
            continue
        if pend is not None:   # the second line of a wrapped input section
            m = _IN_CONT.match(ln)
            if m and out:
                cur = _In(out, pend, int(m.group(1), 16), int(m.group(2), 16), m.group(3))
                inputs.append(cur)
            pend = None
            continue
        if not ln or ln.startswith(('LOAD ', 'OUTPUT(', ' *', '*')):
            if ln.startswith(' *fill*'):
                cur = None
            continue
        m = _OUT.match(ln)
        if m:
            out, cur = m.group(1), None
            continue
        m = _OUT_NAME.match(ln)
        if m:
            out, cur = m.group(1), None
            continue
        m = _IN.match(ln)
        if m and out:
            cur = _In(out, m.group(1), int(m.group(2), 16), int(m.group(3), 16), m.group(4))
            inputs.append(cur)
            continue
        m = _IN_NAME.match(ln)
        if m:
            pend = m.group(1)
            continue
        m = _SYM.match(ln)
        if m and cur is not None:
            name = m.group(2)
            if '=' in name or name.startswith(('PROVIDE', 'ASSERT', '.')) or ' ' in name:
                continue
            a = int(m.group(1), 16)
            if cur.addr <= a < cur.addr + max(cur.size, 1):
                cur.syms.append((a, name))
    if not inputs:
        raise MapError('the map lists no input sections')
    return LinkMap(inputs, image_base)


_TMP_OBJ = re.compile(r'\S*/cc[A-Za-z0-9]{6}\.o\b')


def normalise_map(text, subs, sources):
    """The map with each (old prefix, label) of `subs` replaced (longest first) and gcc's temporary objects named `<source>.o` in LOAD
    order (`sources`: the sources of the link command in its order, e.g. backend.cpp ... adapter/adapter.cpp; a bare name gets core/)."""
    temps = []
    for ln in text.splitlines():
        if ln.startswith('LOAD '):
            t = ln[5:].strip()
            if _TMP_OBJ.fullmatch(t) and t not in temps:
                temps.append(t)
    if len(temps) != len(sources):
        raise MapError(f'the map loads {len(temps)} temporary objects, the link compiled {len(sources)} sources: cannot name them')
    names = {t: (s if '/' in s else 'core/' + s) + '.o' for t, s in zip(temps, sources)}
    text = _TMP_OBJ.sub(lambda m: names.get(m.group(0), m.group(0)), text)
    for old, new in sorted(subs, key=lambda s: -len(s[0])):
        if old:
            text = text.replace(old, new)
    return text


def pe_info(data):
    """{image_base, size_of_image} from the bytes of a PE file (PE32 or PE32+); MapError when it is not one."""
    try:
        if data[:2] != b'MZ':
            raise MapError('not a PE file (no MZ)')
        pe, = struct.unpack_from('<I', data, 0x3c)
        if data[pe:pe + 4] != b'PE\0\0':
            raise MapError('not a PE file (no PE signature)')
        opt = pe + 24
        magic, = struct.unpack_from('<H', data, opt)
        if magic == 0x10b:
            base, = struct.unpack_from('<I', data, opt + 28)
        elif magic == 0x20b:
            base, = struct.unpack_from('<Q', data, opt + 24)
        else:
            raise MapError(f'unknown optional header magic 0x{magic:x}')
        size, = struct.unpack_from('<I', data, opt + 56)
    except struct.error:
        raise MapError('truncated PE header') from None
    return {'image_base': base, 'size_of_image': size}


def write_map(argv):
    """build.sh's entry: write_map --raw R --out MAP --dll DLL --build-id ID --sources "a.cpp b.cpp adapter/adapter.cpp" [--sub OLD=NEW]...
    Writes MAP (normalised) and MAP.json (the sidecar); prints one line. Returns an exit code (2 on a map it cannot normalise)."""
    import argparse
    ap = argparse.ArgumentParser(prog='minidump.write_map')
    ap.add_argument('--raw', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--dll', required=True)
    ap.add_argument('--build-id', required=True)
    ap.add_argument('--sources', required=True)
    ap.add_argument('--sub', action='append', default=[])
    a = ap.parse_args(argv)
    raw = Path(a.raw).read_text(encoding='utf-8', errors='replace')
    subs = [tuple(s.split('=', 1)) for s in a.sub]
    try:
        text = normalise_map(raw, subs, a.sources.split())
        dll = Path(a.dll).read_bytes()
        pe = pe_info(dll)
    except MapError as e:
        print(f'build.sh: linker map: {e}', file=sys.stderr)
        return 2
    out = Path(a.out)
    out.write_bytes(text.encode('utf-8'))
    side = {'dll': Path(a.dll).name, 'build_id': a.build_id, 'dll_sha256': hashlib.sha256(dll).hexdigest(),
            'image_base': f"0x{pe['image_base']:08x}", 'size': len(dll), 'size_of_image': f"0x{pe['size_of_image']:x}"}
    Path(str(out) + '.json').write_bytes((json.dumps(side, indent=2) + '\n').encode('utf-8'))
    print(f'build.sh: linker map {out.name} ({len(text.encode("utf-8"))} bytes) and {out.name}.json: build {a.build_id} sha256 {side["dll_sha256"]}')
    return 0


if __name__ == '__main__':
    sys.exit(write_map(sys.argv[1:]))
