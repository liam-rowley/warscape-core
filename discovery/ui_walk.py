"""Symbolic register walk of a compiled UI script: the engine calls it makes, the fields it reads off their results, its handlers.

purpose: walk one compiled UI script (.luac, Lua 5.1) symbolically and report its engine calls, the fields read off each engine result, data passed in (Initialise, OpenPanel, LuaCall, SetSpecialTooltip), the OnXxx handlers and per-function calls
usage: from ui_walk import walk_chunk; r = walk_chunk(bytes, engine_tables)   (library; ui_atlas.py runs it over every script)
when: J10 static atlas (discovery/ui_atlas.py); any later question of the form "which getter feeds this field"
not-a-verb: a library, ported from empire-remastered rml_mod/docs/atlas/atlas_static.py (Walker) with the engine tables passed in

Static and best-effort: field names are the constant keys a script reads off a register whose value traces back to an engine call,
a parameter or an upvalue (calls, parameters, upvalues, for-in loops are followed); nothing is executed. Engine bindings read their
arguments from the top of the stack down (the game's engine fact lua.arg_stream), so the argument lists here are the script's, not the binding's.
"""
import collections
import re
import struct

import luachunk
from api_inventory import STDLIB
from luachunk import OPS, dec

CAPTURE = {'Find', 'SequentialFind', 'LuaCall', 'OpenPanel', 'ClosePanel', 'IsPanelOpen', 'ClosePanelWithShowData',
           'CreateComponentFromTemplate', 'CreateFromLayout', 'CreateFromComponent', 'SetTooltipText', 'SetSpecialTooltip',
           'LocalisationString', 'UILocalisationString', 'SetStateText', 'SetEventCallback', 'Call', 'CallByAddress',
           'SetState', 'SetImage', 'require', 'Require', 'dofile', 'loadfile', 'CliExecute', 'TriggerAdviceForPanel', 'FormatString',
           'GetProperty', 'SetProperty', 'SetGlobal', 'GlobalExists', 'StealShortcutKey', 'SetTooltipTextWithRLSKey',
           'SetMovie', 'AttachMovieToComponent', 'PlaySound', 'TriggerPanelOpenEvent', 'OnShortcut', 'TransitionTo'}
NOISE_CALLS = {'UIComponent', 'UIImage', 'tostring', 'tonumber', 'ipairs', 'pairs', 'type', 'next', 'unpack', 'select',
               'pcall', 'assert', 'error', 'print', 'setmetatable', 'getmetatable', 'rawget', 'rawset'}
SKIP_METHOD_ROOTS = {':Find', ':Address', ':Parent', ':Position', ':Dimensions', ':Width', ':Height', ':Id', ':Bounds',
                     ':ChildCount', ':CurrentState', ':Visible', ':GetStateText'}
HANDLER = re.compile(r'^On[A-Z]\w*$')


def kv(f, i):
    t, v = f.k[i]
    if t == 'str':
        return v.decode('latin1')
    if t == 'num':
        x = struct.unpack('<f', v)[0]
        return int(x) if x == int(x) else round(x, 4)
    if t == 'bool':
        return v
    return None


def rk(f, regs, x):
    if x >= 256:
        return ('k', f.k[x - 256][0], kv(f, x - 256))
    return regs.get(x, ('reg', x))


def show(e, d=0):
    if e is None:
        return '?'
    if d > 6:
        return '...'
    k = e[0]
    if k == 'k':
        if e[1] == 'str':
            return repr(e[2]) if len(e[2]) <= 40 else repr(e[2][:37] + '...')
        return str(e[2])
    if k == 'global':
        return str(e[1])
    if k == 'field':
        if isinstance(e[2], str):
            return f'{show(e[1], d + 1)}.{e[2]}'
        return f'{show(e[1], d + 1)}[{show(e[2], d + 1) if isinstance(e[2], tuple) else e[2]}]'
    if k == 'call':
        return f"{show(e[1], d + 1)}({', '.join(show(a, d + 1) for a in (e[2] or ())[:4])})"
    if k == 'method':
        return f'{show(e[1], d + 1)}:{e[2]}'
    if k == 'upval':
        return f'^{e[1]}'
    if k == 'param':
        return f'{e[1]}#arg{e[2] + 1}'
    if k == 'elem':
        return f'{show(e[1], d + 1)}[]'
    if k == 'iter':
        return f'pairs({show(e[1], d + 1)})'
    return {'closure': 'function', 'table': '{}'}.get(k, f'${e[1]}' if k == 'local' else '?')


def callee_name(c, d=0):
    if c is None or d > 6:
        return None
    if c[0] == 'global':
        return c[1]
    if c[0] == 'upval':
        return '^' + str(c[1])
    if c[0] == 'field' and isinstance(c[2], str):
        b = callee_name(c[1], d + 1)
        return f'{b}.{c[2]}' if b else None
    if c[0] == 'method':
        return ':' + str(c[2])
    return None


class Walker:
    def __init__(s, engine_tables):
        s.tables = set(engine_tables)
        s.calls = {}                                # engine fn -> {n, examples, funcs}
        s.other_calls = collections.Counter()       # script or module functions called
        s.methods = collections.Counter()
        s.capt = []                                 # [func, name, fullname, [args]]
        s.comp = collections.defaultdict(set)       # component name (Find) -> methods called on it
        s.comp_alias = {}
        s.fields = collections.defaultdict(set)     # root label -> paths read off it
        s.defines, s.handlers = set(), set()
        s.aliases = {}                              # name -> label of the engine call that filled it
        s.links = []                                # [kind, scope, fn, argidx, label]
        s.refs = set()                              # CampaignUI.X etc. referenced (maybe not called directly)
        s.strings = set()
        s.funcs = []
        s.func_calls = collections.defaultdict(set)  # function name -> engine calls made in it (handlers' engine calls)

    def is_engine(s, name):
        return bool(name) and '.' in name and name.split('.')[0] in s.tables

    def root_of(s, e, d=0):
        """(root label, path) for a field chain; label None when the root is not data."""
        path = []
        while e is not None and d < 14:
            d += 1
            k = e[0]
            if k == 'field':
                key = e[2]
                if isinstance(key, str):
                    path.append('.' + key)
                elif isinstance(key, tuple) and key[0] == 'k' and key[1] == 'num':
                    path.append(f'[{key[2]}]')
                else:
                    path.append('[?]')
                e = e[1]
                continue
            if k == 'elem':
                path.append('[]')
                e = e[1]
                continue
            path.reverse()
            p = ''.join(path)
            if k == 'call':
                n = callee_name(e[1])
                if n is None or n in NOISE_CALLS or n.split('.')[-1] in NOISE_CALLS:
                    return None, p
                if n.startswith(':'):
                    a = (e[2] or ())
                    arg = a[0][2] if a and a[0] and a[0][0] == 'k' and a[0][1] == 'str' else None
                    if n in SKIP_METHOD_ROOTS:
                        return None, p
                    return (f'{n}({arg})' if arg else n), p
                return n + '()', p
            if k == 'param':
                return f'{e[1]}#arg{e[2] + 1}', p
            if k == 'upval':
                return '^' + str(e[1]), p
            if k == 'global':
                if e[1] in s.tables or e[1] in STDLIB:
                    return None, p
                return str(e[1]), p
            return None, p
        return None, ''

    def add_call(s, name, ex, fname):
        c = s.calls.setdefault(name, {'n': 0, 'examples': [], 'funcs': []})
        c['n'] += 1
        if len(c['examples']) < 3 and ex not in c['examples']:
            c['examples'].append(ex)
        if fname not in c['funcs']:
            c['funcs'].append(fname)
        s.func_calls[fname].add(name)

    def find_name(s, e, d=0):
        if e is None or d > 5:
            return None
        if e[0] == 'call':
            cal, args = e[1], e[2] or ()
            if cal == ('global', 'UIComponent') and args:
                return s.find_name(args[0], d + 1)
            if cal and cal[0] == 'method' and cal[2] in ('Find', 'SequentialFind') and args and args[0] and args[0][0] == 'k':
                return str(args[0][2])
            if cal and cal[0] == 'field' and cal[2] == 'SequentialFind' and args and args[0] and args[0][0] == 'k':
                return str(args[0][2])
        if e[0] in ('upval', 'global'):
            return s.comp_alias.get(e[1])
        return None

    def source_label(s, e):
        if e is None:
            return None
        if e[0] == 'call':
            n = callee_name(e[1])
            return n + '()' if s.is_engine(n) else None
        if e[0] in ('field', 'elem'):
            r, p = s.root_of(e)
            if r and ((r.endswith('()') and s.is_engine(r[:-2])) or '#arg' in r or r.startswith('^')):
                return r + p
            return None
        if e[0] == 'param':
            return f'{e[1]}#arg{e[2] + 1}'
        if e[0] == 'upval':
            return '^' + str(e[1])
        return None

    def note_field(s, e):
        r, p = s.root_of(e)
        if r and p:
            s.fields[r].add(p)

    def walk(s, f, fname='main'):
        s.funcs.append(fname)
        code = f.code
        for t, v in f.k:
            if t == 'str':
                s.strings.add(v.decode('latin1'))
        loc = [((n or b'?').decode('latin1'), st, en) for n, st, en in f.locals]

        def local_name(reg, pc):
            act = [x for x in loc if x[1] <= pc < x[2]]
            return act[reg][0] if reg < len(act) else None

        pnames = {}
        for pc, w in enumerate(code):
            d = dec(w)
            if OPS[d['OP']] == 'CLOSURE':
                A, bx = d['A'], d['Bx']
                nups, nm = f.protos[bx].nups, None
                j = pc + 1 + nups
                if j < len(code):
                    d2 = dec(code[j])
                    o2 = OPS[d2['OP']]
                    if o2 == 'SETGLOBAL' and d2['A'] == A:
                        nm = kv(f, d2['Bx'])
                    elif o2 == 'SETTABLE' and d2['C'] == A and d2['B'] >= 256:
                        nm = kv(f, d2['B'] - 256)
                if nm is None:
                    nm = local_name(A, pc + nups + 1)
                pnames[bx] = str(nm) if nm else f'{fname}#{bx}'
        regs = {i: ('param', fname, i) for i in range(f.nparams)}
        for pc in range(len(code)):
            i = dec(code[pc])
            op = OPS[i['OP']]
            A, B, C, Bx = i['A'], i['B'], i['C'], i['Bx']
            if op == 'MOVE':
                regs[A] = regs.get(B, ('local', B))
            elif op == 'LOADK':
                regs[A] = ('k', f.k[Bx][0], kv(f, Bx))
            elif op == 'LOADBOOL':
                regs[A] = ('k', 'bool', bool(B))
            elif op == 'LOADNIL':
                for r in range(A, B + 1):
                    regs[r] = ('k', 'nil', None)
            elif op == 'GETUPVAL':
                regs[A] = ('upval', f.upvals[B].decode('latin1') if B < len(f.upvals) and f.upvals[B] else str(B))
            elif op == 'GETGLOBAL':
                regs[A] = ('global', kv(f, Bx))
            elif op in ('SETGLOBAL', 'SETUPVAL'):
                if op == 'SETGLOBAL':
                    name = kv(f, Bx)
                    s.defines.add(name)
                    if HANDLER.match(str(name or '')):
                        s.handlers.add(name)
                else:
                    name = f.upvals[B].decode('latin1') if B < len(f.upvals) and f.upvals[B] else None
                if name:
                    v = regs.get(A)
                    lab = s.source_label(v)
                    if lab and not lab.startswith('^'):
                        s.aliases[name] = lab
                    cn = s.find_name(v)
                    if cn:
                        s.comp_alias[name] = cn
            elif op == 'GETTABLE':
                key, base = rk(f, regs, C), regs.get(B, ('local', B))
                k2 = key[2] if key[0] == 'k' and key[1] == 'str' else key
                regs[A] = ('field', base, k2)
                if base and base[0] == 'global' and base[1] in s.tables and isinstance(k2, str):
                    s.refs.add(f'{base[1]}.{k2}')
                else:
                    s.note_field(regs[A])
            elif op == 'SETTABLE':
                key, t = rk(f, regs, B), regs.get(A)
                if t and t[0] == 'global' and key[0] == 'k' and key[1] == 'str' and HANDLER.match(str(key[2])):
                    s.handlers.add(key[2])
            elif op == 'SELF':
                key = rk(f, regs, C)
                regs[A] = ('method', regs.get(B, ('local', B)), key[2] if key[0] == 'k' else '?')
                regs[A + 1] = ('self',)
            elif op == 'NEWTABLE':
                regs[A] = ('table',)
            elif op == 'CLOSURE':
                regs[A] = ('closure', Bx)
            elif op in ('CALL', 'TAILCALL'):
                callee, nargs = regs.get(A), B - 1 if B > 0 else None
                is_m = bool(callee and callee[0] == 'method')
                if nargs is None:                      # open call: take what is set
                    args, r = [], A + (2 if is_m else 1)
                    while r in regs and len(args) < 8:
                        args.append(regs[r])
                        r += 1
                elif is_m:
                    args = [regs.get(A + 2 + k) for k in range(nargs - 1)] if nargs >= 1 else []
                else:
                    args = [regs.get(A + 1 + k) for k in range(nargs)]
                s.on_call(fname, callee, args)
                n = callee_name(callee)
                regs[A] = ('iter', args[0]) if n in ('ipairs', 'pairs') and args else ('call', callee, tuple(args[:6]))
                for r in [r for r in regs if r > A]:
                    del regs[r]
                if C > 2:
                    for r in range(A + 1, A + C - 1):
                        regs[r] = ('call', callee, tuple(args[:6]))
                if C == 2 and s.is_engine(n) and fname == 'main':   # top-level local (closures see it as an upvalue)
                    ln = local_name(A, pc + 1)
                    if ln and ln != '?' and not any(x[0] == ln and x[1] <= pc < x[2] for x in loc):
                        s.aliases[ln] = n + '()'
            elif op in ('ADD', 'SUB', 'MUL', 'DIV', 'MOD', 'POW', 'CONCAT', 'UNM', 'NOT', 'LEN', 'VARARG'):
                regs[A] = ('expr',)
                if op == 'VARARG' and B != 1:
                    for r in range(A, A + max(B - 1, 1)):
                        regs[r] = ('expr',)
            elif op in ('FORPREP', 'FORLOOP'):
                for r in range(A, A + 4):
                    regs[r] = ('expr',)
            elif op == 'TESTSET':
                regs[A] = regs.get(B, ('local', B))
            elif op == 'JMP':                          # for-in: the body precedes TFORLOOP; seed its loop variables
                t = pc + 1 + i['sBx']
                if 0 <= t < len(code) and OPS[dec(code[t])['OP']] == 'TFORLOOP':
                    A2 = dec(code[t])['A']
                    it = regs.get(A2)
                    X = it[1] if it and it[0] == 'iter' else it
                    regs[A2 + 3], regs[A2 + 4] = ('expr',), ('elem', X)
        for n, p in enumerate(f.protos):
            s.walk(p, pnames.get(n, f'{fname}#{n}'))

    def on_call(s, fname, callee, args):
        n = callee_name(callee)
        if n is None:
            return
        ex = f"{show(callee)}({', '.join(show(a) for a in args[:5])})"
        if s.is_engine(n):
            s.add_call(n, ex, fname)
        elif n.startswith(':'):
            s.methods[n[1:]] += 1
            cn = s.find_name(callee[1])
            if cn:
                s.comp[cn].add(n[1:])
        elif n not in STDLIB and n.split('.')[0] not in STDLIB and n not in NOISE_CALLS:
            s.other_calls[n] += 1
            fn_name = n.split('.')[-1].lstrip('^')
            mod = n.rsplit('.', 1)[0].split('.')[-1].lstrip('^') if '.' in n else None
            for j, a in enumerate(args[:8]):           # data handed to a script or module function: link its parameters
                lab = s.source_label(a)
                if lab:
                    s.links.append(['Call', mod, fn_name, j, lab])
        last = n.split('.')[-1].lstrip(':')
        if last not in CAPTURE:
            return
        s.capt.append([fname, last, n, [(a[2] if a and a[0] == 'k' else show(a)) for a in args[:6]]])

        def kstr(i):
            return args[i][2] if len(args) > i and args[i] and args[i][0] == 'k' else None
        lab = s.source_label
        if last == 'LuaCall' and kstr(0):
            s.links += [['LuaCall', None, kstr(0), j, lab(a)] for j, a in enumerate(args[1:]) if lab(a)]
        if last == 'OpenPanel' and kstr(0):
            if len(args) > 1 and lab(args[1]):
                s.links.append(['OpenPanel', kstr(0), '<ShowData>', 0, lab(args[1])])
            if kstr(2):
                s.links += [['OpenPanel', kstr(0), kstr(2), j, lab(a)] for j, a in enumerate(args[3:]) if lab(a)]
        if last == 'SetSpecialTooltip' and kstr(0) and len(args) >= 3 and lab(args[2]):
            s.links.append(['SpecialTooltip', kstr(0), kstr(1) or '?', 0, lab(args[2])])
        if last == 'Call' and kstr(0) and kstr(1) and str(kstr(0)).endswith('LuaCall'):
            s.links += [['LuaCall', None, kstr(1), j, lab(a)] for j, a in enumerate(args[2:]) if lab(a)]

    def result(s):
        strs = [x for x in s.strings if isinstance(x, str)]
        return dict(calls={k: s.calls[k] for k in sorted(s.calls)}, other_calls=dict(sorted(s.other_calls.items())),
                    methods=dict(sorted(s.methods.items())), capt=s.capt,
                    comp={k: sorted(v) for k, v in sorted(s.comp.items())},
                    fields={k: sorted(v) for k, v in sorted(s.fields.items())},
                    defines=sorted(str(x) for x in s.defines if x), handlers=sorted(str(x) for x in s.handlers),
                    aliases=dict(sorted(s.aliases.items())), links=s.links, refs=sorted(s.refs), funcs=s.funcs,
                    func_calls={k: sorted(v) for k, v in sorted(s.func_calls.items())},
                    textures=sorted(x for x in strs if re.search(r'\.(tga|dds|png|jpg)$', x, re.I)),
                    strings=sorted(x for x in strs if re.match(r'^[\w .%/\\-]{2,96}$', x)))


def walk_chunk(b, engine_tables):
    w = Walker(engine_tables)
    w.walk(luachunk.parse(b).main)
    return w.result()


# inline Lua (a layout component's source text) and plain .lua sources: regex facts only
RX_CAPT = re.compile(r'\b(' + '|'.join(sorted(CAPTURE)) + r')\s*\(\s*"([^"]*)"')
RX_FUNC = re.compile(r'\bfunction\s+([A-Za-z_][\w.:]*)')
RX_DOFILE = re.compile(r'\b(?:dofile|require|Require)\s*\(?\s*"([^"]+)"')


def inline_facts(src, engine_tables):
    rx = re.compile(r'\b(' + '|'.join(sorted(engine_tables)) + r')\.(\w+)\s*\(')
    funcs = sorted(set(RX_FUNC.findall(src)))
    return dict(calls=dict(sorted(collections.Counter(f'{a}.{b}' for a, b in rx.findall(src)).items())),
                capt=[[m[0], m[1]] for m in RX_CAPT.findall(src)], defines=funcs,
                handlers=[f for f in funcs if HANDLER.match(f)], dofiles=sorted(set(RX_DOFILE.findall(src))))
