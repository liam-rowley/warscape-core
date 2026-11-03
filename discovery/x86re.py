#!/usr/bin/env python3
"""Small static x86 (32-bit PE) reverse-engineering kit: strings, absolute references, rel32 callers, disassembly, function walks.

purpose: library and CLI for static RE of a 32-bit Warscape exe without Ghidra: find a string's address and every dword that points at it, every E8 caller of a function, every instruction reading or writing a global (from the relocation table), and a recursive-descent walk of one function (calls, globals, returns)
usage: <re venv python> -I discovery/x86re.py <exe> str <text> | refs <va> | callers <va> | xrefs <va> | dis <va> [n] | func <va>   (venv: discovery/re_env.py)
when: J15 console RE; J9 engine sites and any later engine-site hunt (every address it prints is a candidate until an engine_sites row with anchor bytes is verified on the PC)
not-a-verb: reads a game exe in place (read only), outside the wsc registry operations

Addresses are VAs at the exe's preferred ImageBase (0x400000 for a typical 32-bit Warscape exe); RVA = VA - ImageBase. Import with
`sys.path.insert(0, 'discovery/core')` and `Image(path)`.
"""
import re
import struct
import sys

import capstone
import pefile


class Image:
    def __init__(self, path):
        self.pe = pefile.PE(path, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.img = self.pe.get_memory_mapped_image()
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self.sections = [(s.Name.rstrip(b'\0').decode(), self.base + s.VirtualAddress, s.Misc_VirtualSize, s.SizeOfRawData)
                         for s in self.pe.sections]
        self.text = next(s for s in self.sections if s[0] == '.text')
        self._relocs = None

    # --- bytes
    def u32(self, va):
        return struct.unpack_from('<I', self.img, va - self.base)[0]

    def f32(self, va):
        return struct.unpack_from('<f', self.img, va - self.base)[0]

    def bytes_at(self, va, n):
        return bytes(self.img[va - self.base: va - self.base + n])

    def cstr(self, va, n=400):
        return self.bytes_at(va, n).split(b'\0')[0].decode('latin1')

    def section_of(self, va):
        for name, start, vsz, raw in self.sections:
            if start <= va < start + vsz:
                return name, va - start < raw   # (section, has file bytes)
        return None, False

    def in_text(self, va):
        return self.text[1] <= va < self.text[1] + self.text[2]

    # --- search
    def find_str(self, s):
        return [self.base + m.start() for m in re.finditer(re.escape(s.encode('latin1') + b'\0'), self.img)]

    def refs(self, va):
        """every place the dword `va` appears in the image (push imm, mov imm, table entries)"""
        return [self.base + m.start() for m in re.finditer(re.escape(struct.pack('<I', va)), self.img)]

    def callers(self, target):
        """E8 rel32 calls to `target` in .text"""
        t0, tsz = self.text[1], self.text[2]
        data = self.img[t0 - self.base: t0 - self.base + tsz]
        out = []
        for m in re.finditer(b'\xe8', data):
            o = m.start()
            if o + 5 <= len(data) and t0 + o + 5 + struct.unpack_from('<i', data, o + 1)[0] == target:
                out.append(t0 + o)
        return out

    def relocs(self):
        if self._relocs is None:
            self.pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_BASERELOC']])
            self._relocs = [self.base + e.rva for b in self.pe.DIRECTORY_ENTRY_BASERELOC for e in b.entries if e.type == 3]
        return self._relocs

    def insn_containing(self, loc):
        """the instruction whose operand dword sits at `loc` (tries starts up to 7 bytes back)"""
        for st in range(loc - 7, loc):
            for i in self.md.disasm(self.bytes_at(st, 16), st):
                if i.address < loc and i.address + i.size >= loc + 4:
                    return i
                break
        return None

    def xrefs(self, va):
        """every relocated instruction operand equal to `va`: [(insn address, mnemonic, operands, kind read|write|other)]"""
        out = []
        for loc in self.relocs():
            if self.u32(loc) != va:
                continue
            i = self.insn_containing(loc)
            if i is None:
                out.append((loc, 'data', '', 'other'))
                continue
            ops = i.op_str
            mem = f'[{hex(va)}]' in ops
            if i.mnemonic in ('mov', 'movss', 'movsd', 'movq', 'movzx', 'movsx') and mem:
                kind = 'write' if ops.split(',')[0].strip().endswith(f'[{hex(va)}]') else 'read'
            elif i.mnemonic in ('cmp', 'test', 'push') and mem:
                kind = 'read'
            elif mem:
                kind = 'write'     # add/or/inc/xchg... on the global: treat as a write
            else:
                kind = 'other'     # immediate use (address taken)
            out.append((i.address, i.mnemonic, ops, kind))
        return out

    # --- code
    def dis(self, va, n=40, stop_ret=False):
        out = []
        for i in self.md.disasm(self.bytes_at(va, n * 16), va):
            out.append(i)
            if len(out) >= n or (stop_ret and i.mnemonic.startswith('ret')):
                break
        return out

    def jump_table(self, op_str, entry, window=0x8000):
        """the targets of a switch `jmp dword ptr [reg*4 + table]`: table dwords read while each points into [entry, entry+window)"""
        m = re.fullmatch(r'dword ptr \[(?:e[a-z]{2})\*4 \+ (0x[0-9a-f]+)\]', op_str)
        if not m:
            return []
        out, at = [], int(m.group(1), 16)
        while self.section_of(at)[1] and len(out) < 1024:
            t = self.u32(at)
            if not entry <= t < entry + window:
                break
            out.append(t)
            at += 4
        return out

    def walk(self, entry, limit=4000):
        """recursive descent over one function: {'calls': [(at, target)], 'icalls': [at], 'rets': [at], 'insns': n,
        'globals': [(at, va)], 'tail': [(at, target)], 'itail': [at], 'switch': [(at, n targets)], 'first': first mnemonic}.
        Direct jumps outside [entry, entry+0x8000) count as tail calls. Every indirect `jmp` is listed: a jump table
        `jmp [reg*4 + table]` whose entries point into the window goes to 'switch' and its targets are walked; any other
        (register, memory) goes to 'itail', a tail call to an unknown target (J15 review 8: walk used to drop both)."""
        seen, todo = set(), [entry]
        res = {'calls': [], 'icalls': [], 'rets': [], 'globals': [], 'tail': [], 'itail': [], 'switch': [], 'insns': 0}
        while todo and res['insns'] < limit:
            pc = todo.pop()
            while pc not in seen and self.in_text(pc):
                ins = next(self.md.disasm(self.bytes_at(pc, 16), pc), None)
                if ins is None:
                    break
                seen.add(pc)
                res['insns'] += 1
                if pc == entry:
                    res['first'] = f'{ins.mnemonic} {ins.op_str}'.strip()
                for m in re.finditer(r'\[(0x[0-9a-f]{6,8})\]', ins.op_str):
                    res['globals'].append((pc, int(m.group(1), 16)))
                mn = ins.mnemonic
                nxt = pc + ins.size
                if mn.startswith('ret'):
                    res['rets'].append(pc)
                    break
                if mn == 'call':
                    if ins.op_str.startswith('0x'):
                        res['calls'].append((pc, int(ins.op_str, 16)))
                    else:
                        res['icalls'].append(pc)
                elif mn == 'jmp':
                    if ins.op_str.startswith('0x'):
                        t = int(ins.op_str, 16)
                        if entry <= t < entry + 0x8000:
                            todo.append(t)
                        else:
                            res['tail'].append((pc, t))
                    else:
                        table = self.jump_table(ins.op_str, entry)
                        if table:
                            res['switch'].append((pc, len(table)))
                            todo.extend(table)
                        else:
                            res['itail'].append(pc)
                    break
                elif mn.startswith('j') or mn.startswith('loop'):
                    if ins.op_str.startswith('0x'):
                        todo.append(int(ins.op_str, 16))
                elif mn == 'int3':
                    break
                pc = nxt
        return res


def _fmt(i):
    return f'{i.address:08x}: {i.bytes.hex():<22} {i.mnemonic} {i.op_str}'


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    im = Image(argv[1])
    cmd, arg = argv[2], argv[3] if len(argv) > 3 else None
    num = (lambda s: int(s, 0))
    if cmd == 'str':
        for a in im.find_str(arg):
            print(hex(a), [hex(r) for r in im.refs(a)])
    elif cmd == 'refs':
        print([hex(r) for r in im.refs(num(arg))])
    elif cmd == 'callers':
        print([hex(r) for r in im.callers(num(arg))])
    elif cmd == 'xrefs':
        va = num(arg)
        print(f'{hex(va)} section {im.section_of(va)}')
        for at, mn, ops, kind in im.xrefs(va):
            print(f'{at:08x} {kind:<5} {mn} {ops}')
    elif cmd == 'dis':
        for i in im.dis(num(arg), int(argv[4]) if len(argv) > 4 else 40):
            print(_fmt(i))
    elif cmd == 'func':
        w = im.walk(num(arg))
        print({k: ([(hex(a), hex(b)) for a, b in v] if k in ('calls', 'globals', 'tail', 'switch') else
                   [hex(x) for x in v] if isinstance(v, list) else v) for k, v in w.items()})
    else:
        sys.exit(f'unknown command {cmd}')


if __name__ == '__main__':
    main(sys.argv)
