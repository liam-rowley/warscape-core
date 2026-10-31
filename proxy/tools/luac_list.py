#!/usr/bin/env python3
"""List a Lua 5.1 binary chunk (the engine's compiled UI scripts) as readable bytecode, like `luac -l -l`, in pure Python.

purpose: read the engine's .luac UI scripts (function names, arguments, the calls they make, constants) without a 32-bit luac
usage: luac_list.py FILE.luac [--func NAME ...] [--calls]   (--func: only functions whose debug name or first line matches; --calls: one
       line per call with the callee expression reconstructed from GETGLOBAL/GETTABLE/SELF and its constant arguments)
when: discovery of the front-end, campaign and battle scripts (autostart, reset, scene probes); input comes from pack_list.py --extract.
      Handles the Warscape format: little endian, int 4, size_t 4, Instruction 4, lua_Number 4-byte float.
not-a-verb: a bytecode reader for game files, not a registry operation
"""
import argparse
import struct
import sys

OPS = ['MOVE', 'LOADK', 'LOADBOOL', 'LOADNIL', 'GETUPVAL', 'GETGLOBAL', 'GETTABLE', 'SETGLOBAL', 'SETUPVAL', 'SETTABLE', 'NEWTABLE',
       'SELF', 'ADD', 'SUB', 'MUL', 'DIV', 'MOD', 'POW', 'UNM', 'NOT', 'LEN', 'CONCAT', 'JMP', 'EQ', 'LT', 'LE', 'TEST', 'TESTSET',
       'CALL', 'TAILCALL', 'RETURN', 'FORLOOP', 'FORPREP', 'TFORLOOP', 'SETLIST', 'CLOSE', 'CLOSURE', 'VARARG']
ABX = {'LOADK', 'GETGLOBAL', 'SETGLOBAL', 'CLOSURE'}
ASBX = {'JMP', 'FORLOOP', 'FORPREP'}


class R:
    def __init__(self, b):
        self.b, self.p = b, 0
        h = b[:12]
        if h[:4] != b'\x1bLua' or h[4] != 0x51:
            raise ValueError('not a Lua 5.1 chunk')
        self.le, self.si, self.ss, self.sins, self.sn, self.integral = h[6] == 1, h[7], h[8], h[9], h[10], h[11]
        self.p = 12

    def u8(self):
        v = self.b[self.p]; self.p += 1; return v

    def i(self, n=4):
        v = int.from_bytes(self.b[self.p:self.p + n], 'little'); self.p += n; return v

    def s(self):
        n = self.i(self.ss)
        if n == 0:
            return None
        v = self.b[self.p:self.p + n - 1].decode('latin-1'); self.p += n; return v

    def num(self):
        raw = self.b[self.p:self.p + self.sn]; self.p += self.sn
        if self.integral:
            return int.from_bytes(raw, 'little', signed=True)
        return struct.unpack('<f' if self.sn == 4 else '<d', raw)[0]


def func(r, parent_src='?'):
    f = {'source': r.s() or parent_src, 'line': r.i(r.si), 'lastline': r.i(r.si)}
    f['nups'], f['nparams'], f['vararg'], f['maxstack'] = r.u8(), r.u8(), r.u8(), r.u8()
    f['code'] = [r.i(r.sins) for _ in range(r.i(r.si))]
    ks = []
    for _ in range(r.i(r.si)):
        t = r.u8()
        ks.append(None if t == 0 else bool(r.u8()) if t == 1 else r.num() if t == 3 else r.s())
    f['k'] = ks
    f['protos'] = [func(r, f['source']) for _ in range(r.i(r.si))]
    f['lineinfo'] = [r.i(r.si) for _ in range(r.i(r.si))]
    f['locals'] = []
    for _ in range(r.i(r.si)):
        f['locals'].append((r.s(), r.i(r.si), r.i(r.si)))
    f['upvals'] = [r.s() for _ in range(r.i(r.si))]
    return f


def dec(ins):
    op = OPS[ins & 0x3F] if (ins & 0x3F) < len(OPS) else f'OP{ins & 0x3F}'
    a = (ins >> 6) & 0xFF
    c = (ins >> 14) & 0x1FF
    b = (ins >> 23) & 0x1FF
    bx = (ins >> 14) & 0x3FFFF
    return op, a, b, c, bx, bx - 131071


def rk(f, x):
    if x >= 256:
        k = f['k'][x - 256]
        return repr(k) if isinstance(k, str) else str(k)
    return f'r{x}'


def names(f):
    """Debug names of nested functions from the SETGLOBAL/SETTABLE that stores each CLOSURE."""
    out = {}
    code = f['code']
    for pc, ins in enumerate(code):
        op, a, b, c, bx, _ = dec(ins)
        if op == 'CLOSURE':
            for ins2 in code[pc + 1:pc + 1 + 8 + f['protos'][bx]['nups']]:
                op2, a2, b2, c2, bx2, _ = dec(ins2)
                if op2 == 'SETGLOBAL' and a2 == a:
                    out[bx] = f['k'][bx2]; break
                if op2 == 'SETTABLE' and c2 == a:
                    out[bx] = rk(f, b2).strip("'"); break
    return out


def listing(f, name, calls_only, want, depth=0):
    show = not want or any(w.lower() in (name or '').lower() for w in want)
    if show:
        print(f"\nfunction {name or '<main>'} (line {f['line']}-{f['lastline']}, params {f['nparams']}{', vararg' if f['vararg'] else ''}, {len(f['code'])} ins)")
        loc = [l[0] for l in f['locals'][:f['nparams']]]
        if loc:
            print('  params: ' + ', '.join(loc))
        reg = {}
        for pc, ins in enumerate(f['code']):
            op, a, b, c, bx, sbx = dec(ins)
            line = f['lineinfo'][pc] if pc < len(f['lineinfo']) else 0
            if op == 'GETGLOBAL':
                reg[a] = f['k'][bx]
            elif op == 'GETTABLE':
                reg[a] = f"{reg.get(b, f'r{b}')}[{rk(f, c)}]" if c >= 256 else f"{reg.get(b, f'r{b}')}[{reg.get(c, f'r{c}')}]"
            elif op == 'SELF':
                reg[a] = f"{reg.get(b, f'r{b}')}:{rk(f, c).strip(chr(39))}"; reg[a + 1] = reg.get(b, f'r{b}')
            elif op == 'LOADK':
                reg[a] = repr(f['k'][bx]) if isinstance(f['k'][bx], str) else str(f['k'][bx])
            elif op == 'MOVE':
                reg[a] = reg.get(b, f'r{b}')
            elif op == 'GETUPVAL':
                reg[a] = f['upvals'][b] if b < len(f['upvals']) and f['upvals'][b] else f'up{b}'
            elif op == 'LOADNIL':
                for x in range(a, b + 1): reg[x] = 'nil'
            elif op == 'LOADBOOL':
                reg[a] = 'true' if b else 'false'
            if op in ('CALL', 'TAILCALL'):
                nargs = (b - 1) if b else None
                start = 2 if str(reg.get(a, '')).find(':') >= 0 else 1
                args = [reg.get(a + k, f'r{a + k}') for k in range(start, (nargs or 0) + 1)] if nargs is not None else ['...']
                print(f"  [{line:4}] call {reg.get(a, f'r{a}')}({', '.join(map(str, args))})")
                reg[a] = f"<ret {reg.get(a, '?')}>"
            elif not calls_only:
                if op in ABX:
                    arg = f"{a} {bx}" + (f"  ; {f['k'][bx]!r}" if op in ('LOADK', 'GETGLOBAL', 'SETGLOBAL') else '')
                elif op in ASBX:
                    arg = f"{a} {sbx}"
                else:
                    arg = f"{a} {b} {c}" + (f"  ; {rk(f, b)} {rk(f, c)}" if op in ('GETTABLE', 'SETTABLE', 'SELF', 'EQ', 'LT', 'LE', 'ADD', 'SUB') else '')
                print(f"  [{line:4}] {pc:4} {op:9} {arg}")
    nm = names(f)
    for i, p in enumerate(f['protos']):
        listing(p, nm.get(i, f'{name or "main"}#{i}'), calls_only, want, depth + 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('file')
    ap.add_argument('--func', action='append', default=[])
    ap.add_argument('--calls', action='store_true')
    a = ap.parse_args(argv)
    r = R(open(a.file, 'rb').read())
    f = func(r)
    print(f"source {f['source']}")
    listing(f, None, a.calls, a.func)
    return 0


if __name__ == '__main__':
    sys.exit(main())
