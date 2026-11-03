"""Lua 5.1 chunk reader/writer/editor for a Warscape game's compiled UI scripts.

purpose: parse and re-emit Lua 5.1 chunks (Warscape layout: 4-byte int/size_t/Instruction, 4-byte float) for the API inventory
usage: python3 discovery/luachunk.py roundtrip <dir|file>...   (library for api_inventory.py and lua_api.py)
when: J6 Lua API pass; ported unchanged from empire-remastered ui_scale_mod/tools/luachunk.py (parses all 497 UI scripts of the later game as-is)
not-a-verb: a bytecode reader for game files, not a registry operation


Format: standard Lua 5.1 binary chunk, little-endian, int = size_t = Instruction = 4 bytes, lua_Number = float32.
parse(bytes) -> Chunk; Chunk.serialise() -> bytes (byte-exact for every vanilla script under lua/all/ui).

Functions are addressed like luadis: 'main', 'main#1', 'main#1#0' (proto indices).

Edit primitives (all on a Func):
  f.add_const(v)            -> index (reuses an identical constant; v = float/int, bytes/str, bool, None)
  f.set_const(i, v)         -> replace constant i in place (type may change; every use of K[i] sees it)
  f.insert(pc, ins, ...)    -> insert instruction word(s) before pc; fixes jumps, lineinfo, locals, maxstack
  f.replace(pc, ins)        -> overwrite one instruction (raises maxstack if needed)
  f.set_operand(pc, field, value)   field in A/B/C/Bx/sBx/OP
Assembler: asm(f, 'ADD R21 R16 #28') -> instruction word (literal constants are added to f.k as needed);
           fmt(f, word) -> the same syntax back.  Operands: R<n> register, K<n> constant index, #<number> /
           '<string>' literal constant (added if missing), U<n> upvalue, P<n> proto, ->N jump target (pc), plain int.

CLI:
  python3 tools/luachunk.py roundtrip <dir|file>...   re-emit every chunk and compare byte-for-byte
  python3 tools/luachunk.py list <file> [func]         assembler-syntax listing (what patches.txt accepts)
"""
import struct, sys, os, ast

OPS = ['MOVE', 'LOADK', 'LOADBOOL', 'LOADNIL', 'GETUPVAL', 'GETGLOBAL', 'GETTABLE', 'SETGLOBAL', 'SETUPVAL', 'SETTABLE',
       'NEWTABLE', 'SELF', 'ADD', 'SUB', 'MUL', 'DIV', 'MOD', 'POW', 'UNM', 'NOT', 'LEN', 'CONCAT', 'JMP', 'EQ', 'LT', 'LE',
       'TEST', 'TESTSET', 'CALL', 'TAILCALL', 'RETURN', 'FORLOOP', 'FORPREP', 'TFORLOOP', 'SETLIST', 'CLOSE', 'CLOSURE', 'VARARG']
OPN = {o: i for i, o in enumerate(OPS)}

# operand layout per opcode, in Lua source order.  R reg, RK reg-or-const, K const (Bx), U upvalue, P proto (Bx),
# J signed jump (sBx), N raw number.  Field letters: A, B, C, X (=Bx), S (=sBx)
LAYOUT = {
    'MOVE': 'A:R B:R', 'LOADK': 'A:R X:K', 'LOADBOOL': 'A:R B:N C:N', 'LOADNIL': 'A:R B:R', 'GETUPVAL': 'A:R B:U',
    'GETGLOBAL': 'A:R X:K', 'GETTABLE': 'A:R B:R C:RK', 'SETGLOBAL': 'A:R X:K', 'SETUPVAL': 'A:R B:U',
    'SETTABLE': 'A:R B:RK C:RK', 'NEWTABLE': 'A:R B:N C:N', 'SELF': 'A:R B:R C:RK',
    'ADD': 'A:R B:RK C:RK', 'SUB': 'A:R B:RK C:RK', 'MUL': 'A:R B:RK C:RK', 'DIV': 'A:R B:RK C:RK', 'MOD': 'A:R B:RK C:RK',
    'POW': 'A:R B:RK C:RK', 'UNM': 'A:R B:R', 'NOT': 'A:R B:R', 'LEN': 'A:R B:R', 'CONCAT': 'A:R B:R C:R', 'JMP': 'S:J',
    'EQ': 'A:N B:RK C:RK', 'LT': 'A:N B:RK C:RK', 'LE': 'A:N B:RK C:RK', 'TEST': 'A:R C:N', 'TESTSET': 'A:R B:R C:N',
    'CALL': 'A:R B:N C:N', 'TAILCALL': 'A:R B:N C:N', 'RETURN': 'A:R B:N', 'FORLOOP': 'A:R S:J', 'FORPREP': 'A:R S:J',
    'TFORLOOP': 'A:R C:N', 'SETLIST': 'A:R B:N C:N', 'CLOSE': 'A:R', 'CLOSURE': 'A:R X:P', 'VARARG': 'A:R B:N'}
JUMPS = {'JMP', 'FORLOOP', 'FORPREP'}
SKIPS = {'EQ', 'LT', 'LE', 'TEST', 'TESTSET', 'TFORLOOP'}     # the next instruction is part of this one (a JMP)
MAXARG_BX = (1 << 18) - 1; MAXARG_SBX = MAXARG_BX >> 1; BITRK = 256; MAXSTACK = 250


def dec(i):
    op = i & 0x3f; a = (i >> 6) & 0xff; c = (i >> 14) & 0x1ff; b = (i >> 23) & 0x1ff; bx = i >> 14
    return dict(OP=op, A=a, B=b, C=c, Bx=bx, sBx=bx - MAXARG_SBX)


def enc(op, a=0, b=0, c=0, bx=None, sbx=None):
    if isinstance(op, str): op = OPN[op]
    assert 0 <= a <= 0xff, a
    if sbx is not None: bx = sbx + MAXARG_SBX
    if bx is not None:
        assert 0 <= bx <= MAXARG_BX, bx
        return op | (a << 6) | (bx << 14)
    assert 0 <= b <= 0x1ff and 0 <= c <= 0x1ff, (b, c)
    return op | (a << 6) | (c << 14) | (b << 23)


def set_field(i, field, v):
    d = dec(i); op = d['OP']
    if field == 'OP': op = OPN[v] if isinstance(v, str) else v
    if field in ('Bx', 'sBx'):
        return enc(op, d['A'], bx=v if field == 'Bx' else v + MAXARG_SBX)
    fs = {k: d[k] for k in ('A', 'B', 'C')}
    if field in fs: fs[field] = v
    lay = LAYOUT[OPS[op]]
    if 'X:' in lay or 'S:' in lay: return enc(op, fs['A'], bx=d['Bx'])
    return enc(op, fs['A'], fs['B'], fs['C'])


def regs(i):
    """Highest register index an instruction touches (for maxstack), or -1."""
    d = dec(i); o = OPS[d['OP']]; a, b, c = d['A'], d['B'], d['C']
    hi = -1
    for part in LAYOUT[o].split():
        f, kind = part.split(':')
        v = {'A': a, 'B': b, 'C': c}.get(f)
        if kind == 'R' or (kind == 'RK' and v < BITRK): hi = max(hi, v)
    if o == 'CALL' or o == 'TAILCALL': hi = max(hi, a + max(b - 1, 0), a + max(c - 2, 0))
    elif o == 'RETURN' or o == 'VARARG': hi = max(hi, a + max(b - 2, 0))
    elif o in ('FORLOOP', 'FORPREP'): hi = max(hi, a + 3)
    elif o == 'TFORLOOP': hi = max(hi, a + 2 + c)
    elif o == 'SELF': hi = max(hi, a + 1)
    elif o == 'SETLIST': hi = max(hi, a + b)
    return hi


class Func:
    def __init__(s): s.protos = []

    # ---------- constants ----------
    @staticmethod
    def kval(v):
        if v is None: return ('nil', None)
        if isinstance(v, bool): return ('bool', v)
        if isinstance(v, (int, float)): return ('num', struct.pack('<f', float(v)))
        if isinstance(v, str): v = v.encode('latin1')
        if isinstance(v, bytes): return ('str', v)
        if isinstance(v, tuple): return v
        raise TypeError(v)

    def add_const(s, v):
        k = s.kval(v)
        if k in s.k: return s.k.index(k)
        s.k.append(k); return len(s.k) - 1

    def set_const(s, i, v): s.k[i] = s.kval(v)

    def find_const(s, v):
        k = s.kval(v); return s.k.index(k) if k in s.k else None

    def kshow(s, i):
        t, v = s.k[i]
        if t == 'num':
            x = struct.unpack('<f', v)[0]; return '#' + (repr(int(x)) if x == int(x) else repr(x))
        if t == 'str': return repr(v.decode('latin1'))
        return f'K{i}'                                       # nil / bool constants: by index

    # ---------- code edits ----------
    def _check_boundary(s, pc):
        if pc == 0: return
        prev = dec(s.code[pc - 1]); o = OPS[prev['OP']]
        if o in SKIPS: raise ValueError(f'pc {pc}: previous instruction {o} skips/uses the next one; insert elsewhere')
        if o == 'LOADBOOL' and prev['C']: raise ValueError(f'pc {pc}: previous LOADBOOL skips the next instruction')
        if o == 'SETLIST' and prev['C'] == 0: raise ValueError(f'pc {pc}: previous SETLIST takes the next word as data')
        if (o == 'CALL' and prev['C'] == 0) or (o == 'VARARG' and prev['B'] == 0):
            raise ValueError(f'pc {pc}: previous {o} leaves an open stack top for the next instruction')
        for back in range(1, min(pc, 256) + 1):                 # CLOSURE is followed by one pseudo-op per upvalue
            q = dec(s.code[pc - back])
            if OPS[q['OP']] == 'CLOSURE' and s.protos[q['Bx']].nups >= back:
                raise ValueError(f'pc {pc}: inside the upvalue list of CLOSURE at pc {pc - back}')

    def insert(s, pc, ins, line=None, jumps_to_pc='new'):
        """Insert instruction word(s) before pc.  Jumps that targeted pc land on the new code ('new', default)
        or still on the old instruction ('old').  Jump operands *inside* `ins` are taken as already final."""
        ins = [ins] if isinstance(ins, int) else list(ins); n = len(ins)
        assert 0 <= pc <= len(s.code)
        s._check_boundary(pc)
        new = []
        for j, w in enumerate(s.code):
            d = dec(w)
            if OPS[d['OP']] in JUMPS:
                t = j + 1 + d['sBx']; nj = j + (n if j >= pc else 0)
                nt = t + (n if t > pc or (t == pc and jumps_to_pc == 'old') else 0)
                w = set_field(w, 'sBx', nt - nj - 1)
            new.append(w)
        s.code = new[:pc] + ins + new[pc:]
        if s.lineinfo:
            ln = line if line is not None else s.lineinfo[pc - 1 if pc else 0]      # same source line as the code before it
            s.lineinfo[pc:pc] = [ln] * n
        s.locals = [(nm, st + (n if st > pc else 0), en + (n if en > pc else 0)) for nm, st, en in s.locals]
        s._fit_stack(ins)
        return n

    def replace(s, pc, w):
        s.code[pc] = w; s._fit_stack([w])

    def set_operand(s, pc, field, v):
        s.code[pc] = set_field(s.code[pc], field, v); s._fit_stack([s.code[pc]])

    def _fit_stack(s, ins):
        hi = max(regs(w) for w in ins) + 1
        if hi > s.maxstack:
            assert hi <= MAXSTACK, hi
            s.maxstack = hi

    # ---------- walking ----------
    def walk(s, name='main'):
        yield name, s
        for i, p in enumerate(s.protos): yield from p.walk(f'{name}#{i}')


class Chunk:
    def __init__(s, header, main): s.header = header; s.main = main

    def funcs(s): return dict(s.main.walk())

    def func(s, name):
        f = s.main
        for part in name.split('#')[1:]: f = f.protos[int(part)]
        return f

    def serialise(s):
        out = bytearray(s.header); _wfunc(out, s.main); return bytes(out)


HEADER = b'\x1bLuaQ\x00\x01\x04\x04\x04\x04\x00'


def parse(d):
    assert d[:12] == HEADER, f'unexpected header {d[:12]!r}'
    p = [12]

    def u8():
        v = d[p[0]]; p[0] += 1; return v

    def i32():
        v = struct.unpack_from('<i', d, p[0])[0]; p[0] += 4; return v

    def u32():
        v = struct.unpack_from('<I', d, p[0])[0]; p[0] += 4; return v

    def lstr():
        n = u32()
        if n == 0: return None
        v = d[p[0]:p[0] + n]; p[0] += n
        assert v[-1:] == b'\0', 'string without terminating NUL'
        return v[:-1]

    def func():
        f = Func()
        f.source = lstr(); f.line = i32(); f.lastline = i32()
        f.nups, f.nparams, f.vararg, f.maxstack = u8(), u8(), u8(), u8()
        f.code = [u32() for _ in range(i32())]
        f.k = []
        for _ in range(i32()):
            t = u8()
            if t == 0: f.k.append(('nil', None))
            elif t == 1: f.k.append(('bool', bool(u8())))
            elif t == 3: f.k.append(('num', d[p[0]:p[0] + 4])); p[0] += 4
            elif t == 4: f.k.append(('str', lstr()))
            else: raise ValueError(f'constant type {t}')
        f.protos = [func() for _ in range(i32())]
        f.lineinfo = [i32() for _ in range(i32())]
        f.locals = [(lstr(), i32(), i32()) for _ in range(i32())]
        f.upvals = [lstr() for _ in range(i32())]
        return f

    m = func()
    assert p[0] == len(d), f'{len(d) - p[0]} trailing bytes'
    return Chunk(d[:12], m)


def _wfunc(o, f):
    def i32(v): o.extend(struct.pack('<i', v))

    def lstr(v):
        if v is None: i32(0)
        else: i32(len(v) + 1); o.extend(v); o.append(0)

    lstr(f.source); i32(f.line); i32(f.lastline)
    o.extend(bytes([f.nups, f.nparams, f.vararg, f.maxstack]))
    i32(len(f.code)); [o.extend(struct.pack('<I', w)) for w in f.code]
    i32(len(f.k))
    for t, v in f.k:
        if t == 'nil': o.append(0)
        elif t == 'bool': o.extend(bytes([1, int(v)]))
        elif t == 'num': o.append(3); o.extend(v)
        else: o.append(4); lstr(v)
    i32(len(f.protos)); [_wfunc(o, p) for p in f.protos]
    i32(len(f.lineinfo)); [i32(x) for x in f.lineinfo]
    i32(len(f.locals))
    for nm, st, en in f.locals: lstr(nm); i32(st); i32(en)
    i32(len(f.upvals)); [lstr(u) for u in f.upvals]


# ---------------- assembler ----------------
def tokens(text):
    """Split on whitespace, keeping quoted strings (with \\ escapes) together."""
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch.isspace(): i += 1; continue
        if ch in '\'"':                                      # Python string literal syntax (what fmt prints)
            j = i + 1
            while text[j] != ch: j += 2 if text[j] == '\\' else 1
            out.append(('str', ast.literal_eval(text[i:j + 1]))); i = j + 1; continue
        j = i
        while j < len(text) and not text[j].isspace(): j += 1
        out.append(('tok', text[i:j])); i = j
    return out


def operand(f, kind, tok, pc, add=True, target=None):
    t, v = tok

    def const(val):
        idx = f.add_const(val) if add else f.find_const(val)
        if idx is None: raise KeyError(f'constant {val!r} not in function')
        return idx

    if t == 'str': idx = const(v)
    elif v.startswith('#'): idx = const(float(v[1:]))
    elif v[0] in 'Kk' and v[1:].isdigit(): idx = int(v[1:])
    else: idx = None
    if kind == 'RK':
        if idx is not None:
            assert idx < BITRK, f'constant index {idx} too large for an RK operand'
            return idx + BITRK
        return int(v.lstrip('Rr'))
    if kind == 'K':
        if idx is None: idx = int(v)
        return idx
    if kind == 'J':
        if v.startswith('->'): return (target(int(v[2:])) if target else int(v[2:])) - pc - 1
        return int(v)
    if idx is not None: raise ValueError(f'{kind} operand cannot be a constant: {v}')
    return int(v.lstrip('RrUuPp'))


def asm(f, text, pc=0, add=True, target=None):
    """Assemble one instruction.  pc = where it will sit (only matters for ->N jump targets);
    target(N) maps a written pc to a real pc (apply_patches passes the vanilla->current map)."""
    tk = tokens(text); op = tk[0][1].upper(); parts = LAYOUT[op].split()
    if len(tk) - 1 != len(parts): raise ValueError(f'{op} takes {len(parts)} operands ({LAYOUT[op]}): {text!r}')
    vals = {}
    for part, tok in zip(parts, tk[1:]):
        fld, kind = part.split(':'); vals[fld] = operand(f, kind, tok, pc, add, target)
    if 'X' in vals: return enc(op, vals.get('A', 0), bx=vals['X'])
    if 'S' in vals: return enc(op, vals.get('A', 0), sbx=vals['S'])
    return enc(op, vals.get('A', 0), vals.get('B', 0), vals.get('C', 0))


def fmt(f, w, pc=None):
    d = dec(w); o = OPS[d['OP']]; out = [o]
    for part in LAYOUT[o].split():
        fld, kind = part.split(':')
        v = d['Bx'] if fld == 'X' else d['sBx'] if fld == 'S' else d[fld]
        if kind == 'R': out.append(f'R{v}')
        elif kind == 'RK': out.append(f.kshow(v - BITRK) if v >= BITRK else f'R{v}')
        elif kind == 'K': out.append(f.kshow(v))
        elif kind == 'U': out.append(f'U{v}')
        elif kind == 'P': out.append(f'P{v}')
        elif kind == 'J': out.append(f'->{pc + 1 + v}' if pc is not None else str(v))
        else: out.append(str(v))
    return ' '.join(out)


def listing(ch, only=None):
    out = []
    for name, f in ch.main.walk():
        if only and name != only: continue
        out.append(f'-- {name}  line {f.line}  params={f.nparams} maxstack={f.maxstack} '
                   f'upvals={[u.decode("latin1") if u else u for u in f.upvals]}')
        for pc, w in enumerate(f.code):
            ln = f.lineinfo[pc] if pc < len(f.lineinfo) else '?'
            out.append(f'  {pc:4} L{ln:<4} {fmt(f, w, pc)}')
    return '\n'.join(out)


def _files(args):
    for a in args:
        if os.path.isdir(a):
            for r, _, fs in os.walk(a):
                for fn in sorted(fs):
                    if fn.endswith('.luac'): yield os.path.join(r, fn)
        else: yield a


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'roundtrip':
        ok = bad = 0
        for p in _files(sys.argv[2:]):
            d = open(p, 'rb').read()
            try:
                same = parse(d).serialise() == d
            except Exception as e:
                same = False; print('ERROR', p, e)
            if same: ok += 1
            else: bad += 1; print('MISMATCH', p)
        print(f'{ok} byte-identical, {bad} failed'); sys.exit(1 if bad else 0)
    elif cmd == 'list':
        print(listing(parse(open(sys.argv[2], 'rb').read()), sys.argv[3] if len(sys.argv) > 3 else None))
    else:
        print(__doc__)
