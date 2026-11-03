"""Engine API inventory for the compiled UI scripts of a Warscape game (RmlUi plan §5.4).

purpose: walk compiled UI scripts symbolically and list the engine API they use (globals, table functions, component methods, OnXxx handlers)
usage: python3 discovery/api_inventory.py <dir of .luac> --json out.json   (library: Inventory is used by lua_api.py)
when: J6 Lua API pass; ported unchanged from empire-remastered ui_scale_mod/tools/api_inventory.py (runs on the later game's scripts as-is, imports luachunk from this folder)
not-a-verb: a static reader for game files, not a registry operation


Walks every chunk under lua/all (default) with luachunk.py, tracks what each register holds symbolically
(global / table field / method receiver / constant) and records every call whose callee is not defined by the scripts
themselves and is not standard Lua.  Output: Markdown (engine globals, table APIs such as CampaignUI.*, component
methods, script-defined globals, event-handler names) plus a JSON dump for tooling.
The JSON (rml_mod/docs/engine_api.json) is what assets/build_index.py reads (`find.py --kind engine_api`). The Markdown rendering
rml_mod/docs/engine_api.md was retired 2026-10-27 (Liam D3): --md is only for a one-off local report, never commit its output.

  python3 tools/api_inventory.py [lua/all] --json rml_mod/docs/engine_api.json   [--md /tmp/engine_api.md  (optional, not committed)]
"""
import sys, os, json, struct, collections, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import luachunk
from luachunk import dec, OPS

STDLIB = set('''assert collectgarbage dofile error getfenv getmetatable ipairs load loadfile loadstring module next pairs
pcall print rawequal rawget rawset require select setfenv setmetatable tonumber tostring type unpack xpcall _G _VERSION
string table math os io coroutine package debug gcinfo newproxy'''.split())
STD_METHOD_RECV = {'string', 'table', 'math', 'os', 'io', 'coroutine', 'package', 'debug'}
EVENT_RE = re.compile(r'^On[A-Z]\w*$')


def kstr(f, i):
    t, v = f.k[i]
    if t == 'str': return v.decode('latin1')
    if t == 'num':
        x = struct.unpack('<f', v)[0]; return int(x) if x == int(x) else round(x, 4)
    if t == 'bool': return v
    return None


def rk(f, regs, x):
    """Describe an RK operand: constant or whatever the register holds."""
    if x >= 256:
        t, v = f.k[x - 256]
        return ('k', t, kstr(f, x - 256))
    return regs.get(x, ('reg', x))


def show(e):
    if e is None: return '?'
    kind = e[0]
    if kind == 'k':
        _, t, v = e
        if t == 'str': return repr(v) if len(v) <= 40 else repr(v[:37] + '...')
        return str(v)
    if kind == 'global': return e[1]
    if kind == 'field': return f'{show(e[1])}.{e[2]}' if isinstance(e[2], str) else f'{show(e[1])}[{show(e[2])}]'
    if kind == 'call': return f'{show(e[1])}(...)'
    if kind == 'method': return f'{show(e[1])}:{e[2]}'
    if kind == 'upval': return f'^{e[1]}'
    if kind == 'local': return f'${e[1]}'
    if kind == 'closure': return 'function'
    if kind == 'table': return '{}'
    return '?'


def argshape(e):
    """Coarse type of an argument for signature grouping."""
    if e is None: return '?'
    if e[0] == 'k': return {'str': 'str', 'num': 'num', 'bool': 'bool', 'nil': 'nil'}.get(e[1], '?')
    if e[0] == 'closure': return 'fn'
    if e[0] == 'table': return 'tbl'
    if e[0] == 'call' and e[1] and e[1][0] == 'global' and e[1][1] == 'UIComponent': return 'comp'
    return 'expr'


class Inventory:
    def __init__(s):
        s.calls = collections.defaultdict(lambda: dict(n=0, scripts=set(), sigs=collections.Counter(),
                                                      examples=collections.Counter(), results=collections.Counter()))
        s.methods = collections.defaultdict(lambda: dict(n=0, scripts=set(), sigs=collections.Counter(),
                                                        examples=collections.Counter(), receivers=collections.Counter(),
                                                        results=collections.Counter()))
        s.global_reads = collections.defaultdict(lambda: dict(n=0, scripts=set()))
        s.defined = collections.defaultdict(set)          # global name -> scripts that SETGLOBAL it
        s.events = collections.defaultdict(set)           # OnXxx function names -> scripts
        s.fields_set = collections.defaultdict(set)       # table.field assignments on globals (module exports etc.)

    def record_call(s, script, callee, args, nres):
        if callee is None: return
        if callee[0] == 'method':
            recv, name = callee[1], callee[2]
            if recv and recv[0] == 'global' and recv[1] in STD_METHOD_RECV: return
            m = s.methods[name]; m['n'] += 1; m['scripts'].add(script)
            m['sigs'][','.join(argshape(a) for a in args) or '()'] += 1
            m['examples'][f"{show(recv)}:{name}({', '.join(show(a) for a in args)})"] += 1
            m['receivers'][show(recv)] += 1; m['results'][nres] += 1
            return
        if callee[0] == 'global':
            name = callee[1]
        elif callee[0] == 'field' and isinstance(callee[2], str):
            root = callee[1]
            while root and root[0] == 'field': root = root[1]
            if not root or root[0] != 'global' or root[1] in STD_METHOD_RECV: return
            name = show(callee)
        else:
            return
        if name in STDLIB or name.split('.')[0] in STDLIB: return
        c = s.calls[name]; c['n'] += 1; c['scripts'].add(script)
        c['sigs'][','.join(argshape(a) for a in args) or '()'] += 1
        c['examples'][f"{name}({', '.join(show(a) for a in args)})"] += 1; c['results'][nres] += 1

    def walk(s, script, f, fname='main'):
        regs = {}
        code = f.code
        pc = 0
        while pc < len(code):
            i = dec(code[pc]); op = OPS[i['OP']]; A, B, C, Bx = i['A'], i['B'], i['C'], i['Bx']
            if op == 'MOVE': regs[A] = regs.get(B, ('local', B))
            elif op == 'LOADK': regs[A] = ('k', f.k[Bx][0], kstr(f, Bx))
            elif op == 'LOADBOOL': regs[A] = ('k', 'bool', bool(B))
            elif op == 'LOADNIL':
                for r in range(A, B + 1): regs[r] = ('k', 'nil', None)
            elif op == 'GETUPVAL': regs[A] = ('upval', f.upvals[B].decode('latin1') if B < len(f.upvals) and isinstance(f.upvals[B], bytes) else B)
            elif op == 'GETGLOBAL':
                name = kstr(f, Bx); regs[A] = ('global', name)
                if name not in STDLIB:
                    g = s.global_reads[name]; g['n'] += 1; g['scripts'].add(script)
            elif op == 'SETGLOBAL':
                name = kstr(f, Bx); s.defined[name].add(script)
                if EVENT_RE.match(name or ''): s.events[name].add(script)
            elif op == 'GETTABLE':
                key = rk(f, regs, C)
                regs[A] = ('field', regs.get(B, ('local', B)), key[2] if key[0] == 'k' and key[1] == 'str' else key)
            elif op == 'SETTABLE':
                key = rk(f, regs, C); t = regs.get(A)
                if t and t[0] == 'global' and key[0] == 'k' and key[1] == 'str':
                    s.fields_set[f'{t[1]}.{key[2]}'].add(script)
                    if EVENT_RE.match(key[2]): s.events[key[2]].add(script)
            elif op == 'SELF':
                key = rk(f, regs, C)
                regs[A] = ('method', regs.get(B, ('local', B)), key[2] if key[0] == 'k' else '?'); regs[A + 1] = ('self',)
            elif op == 'NEWTABLE': regs[A] = ('table',)
            elif op == 'CLOSURE':
                regs[A] = ('closure', Bx)
            elif op in ('CALL', 'TAILCALL'):
                callee = regs.get(A)
                nargs = B - 1 if B > 0 else None
                if callee and callee[0] == 'method':
                    args = [regs.get(A + 2 + k) for k in range(nargs - 1)] if nargs is not None and nargs >= 1 else [('vararg',)]
                else:
                    args = [regs.get(A + 1 + k) for k in range(nargs)] if nargs is not None else [('vararg',)]
                s.record_call(script, callee, args, C - 1 if C > 0 else 'multi')
                regs[A] = ('call', callee)
                for r in list(regs):
                    if r > A: del regs[r]
            elif op in ('ADD', 'SUB', 'MUL', 'DIV', 'MOD', 'POW', 'CONCAT', 'UNM', 'NOT', 'LEN', 'VARARG', 'TFORLOOP'):
                regs[A] = ('expr',)
                if op == 'VARARG' and B != 1:
                    for r in range(A, A + max(B - 1, 1)): regs[r] = ('expr',)
            elif op in ('FORPREP', 'FORLOOP'):
                for r in range(A, A + 4): regs[r] = ('expr',)
            elif op == 'TESTSET': regs[A] = regs.get(B, ('local', B))
            elif op == 'JMP':
                # a jump target can be reached with different register contents; be conservative
                pass
            pc += 1
        for n, p in enumerate(f.protos): s.walk(script, p, f'{fname}#{n}')

    def to_json(s):
        def conv(d):
            return {k: dict(n=v['n'], scripts=sorted(v['scripts']), sigs=dict(v['sigs']), results={str(a): b for a, b in v.get('results', {}).items()},
                            examples=[e for e, _ in v['examples'].most_common(6)],
                            receivers=[r for r, _ in v['receivers'].most_common(6)] if 'receivers' in v else None) for k, v in d.items()}
        return dict(calls=conv(s.calls), methods=conv(s.methods),
                    global_reads={k: dict(n=v['n'], scripts=sorted(v['scripts'])) for k, v in s.global_reads.items()},
                    defined={k: sorted(v) for k, v in s.defined.items()}, events={k: sorted(v) for k, v in s.events.items()},
                    fields_set={k: sorted(v) for k, v in s.fields_set.items()})


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    root = args[0] if args else 'lua/all'
    md = sys.argv[sys.argv.index('--md') + 1] if '--md' in sys.argv else None
    js = sys.argv[sys.argv.index('--json') + 1] if '--json' in sys.argv else None
    inv = Inventory(); nfiles = 0; failed = []
    for dp, _, fs in os.walk(root):
        for fn in sorted(fs):
            path = os.path.join(dp, fn); d = open(path, 'rb').read()
            if d[:4] != b'\x1bLua': continue
            rel = os.path.relpath(path, root).replace('\\', '/')
            try:
                inv.walk(rel, luachunk.parse(d).main); nfiles += 1
            except Exception as e:
                failed.append((rel, repr(e)))
    defined = set(inv.defined)
    engine_calls = {k: v for k, v in inv.calls.items() if k.split('.')[0] not in defined}
    script_calls = {k: v for k, v in inv.calls.items() if k.split('.')[0] in defined}
    out = []
    w = out.append
    w(f'# Engine API inventory — {nfiles} compiled scripts under `{root}`\n')
    w('Generated by `tools/api_inventory.py` (static walk of the bytecode; receivers/arguments are best-effort symbolic). '
      'Signature column = argument kinds seen (`str`/`num`/`bool`/`fn`/`tbl`/`comp` = `UIComponent(...)` result/`expr`), with counts. '
      '`→` = number of results the caller keeps.\n')
    if failed: w(f'\n**Failed to parse:** {failed}\n')

    def table(title, items, with_recv=False):
        w(f'\n## {title} ({len(items)})\n')
        w('| name | calls | scripts | signatures seen | ' + ('receivers | ' if with_recv else '') + 'examples |')
        w('|---|---|---|---|' + ('---|' if with_recv else '') + '---|')
        for k, v in sorted(items.items(), key=lambda kv: -kv[1]['n']):
            sigs = ', '.join(f'`({sg})`×{n}' for sg, n in v['sigs'].most_common(4))
            res = ', '.join(f'→{r}' for r, _ in v['results'].most_common(2))
            ex = '<br>'.join(f'`{e}`' for e, _ in v['examples'].most_common(2)).replace('|', '\\|')
            recv = ('`' + '`, `'.join(r for r, _ in v['receivers'].most_common(3)).replace('|', '\\|') + '` | ') if with_recv else ''
            w(f"| `{k}` | {v['n']} | {len(v['scripts'])} | {sigs} {res} | {recv}{ex} |")

    direct = {k: v for k, v in engine_calls.items() if '.' not in k}
    tables = collections.defaultdict(dict)
    for k, v in engine_calls.items():
        if '.' in k: tables[k.split('.')[0]][k] = v
    table('Engine globals called directly', direct)
    for t in sorted(tables, key=lambda t: -sum(v['n'] for v in tables[t].values())):
        table(f'`{t}.*` (engine table)', tables[t])
    table('Component / object methods (`obj:Method(...)`)', inv.methods, with_recv=True)
    w(f'\n## Script-defined globals called ({len(script_calls)})\n')
    w('Functions the scripts define themselves (SETGLOBAL somewhere under this root) — reusable helpers, not engine API.\n')
    w('| name | calls | defined in | scripts using |'); w('|---|---|---|---|')
    for k, v in sorted(script_calls.items(), key=lambda kv: -kv[1]['n'])[:200]:
        w(f"| `{k}` | {v['n']} | {', '.join(sorted(inv.defined.get(k.split('.')[0], []))[:3])} | {len(v['scripts'])} |")
    w(f'\n## Event-handler names defined (`OnXxx`) ({len(inv.events)})\n')
    w('| handler | scripts |'); w('|---|---|')
    for k, v in sorted(inv.events.items(), key=lambda kv: -len(kv[1])):
        w(f'| `{k}` | {len(v)} |')
    reads_only = {k: v for k, v in inv.global_reads.items() if k not in inv.calls and k not in defined and k not in tables}
    w(f'\n## Engine globals read but never called directly ({len(reads_only)})\n')
    w('Tables/values supplied by the engine (indexed or passed around).\n')
    w('| name | reads | scripts |'); w('|---|---|---|')
    for k, v in sorted(reads_only.items(), key=lambda kv: -kv[1]['n']):
        w(f"| `{k}` | {v['n']} | {len(v['scripts'])} |")
    text = '\n'.join(out) + '\n'
    if md:
        os.makedirs(os.path.dirname(md) or '.', exist_ok=True); open(md, 'w', encoding='utf-8').write(text)
        print(f'wrote {md} ({len(text)} bytes)')
    else:
        sys.stdout.write(text)
    if js:
        os.makedirs(os.path.dirname(js) or '.', exist_ok=True)
        json.dump(inv.to_json(), open(js, 'w'), indent=1); print(f'wrote {js}')
    print(f'{nfiles} scripts; {len(direct)} engine globals, {sum(len(t) for t in tables.values())} table functions in {len(tables)} tables, '
          f'{len(inv.methods)} methods, {len(inv.events)} event handlers', file=sys.stderr)


if __name__ == '__main__':
    main()
