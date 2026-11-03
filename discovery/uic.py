"""
Parser / serialiser for Warscape UI layout files ("Version025"-"Version033" in the earlier game; the later one adds "Version039").

purpose: parse and re-serialise UI layout files byte for byte (V009-V033 of the earlier game; V039 of the later one and the uied.templates v18 and v35 records)
usage: import uic; doc = uic.parse(bytes, name); uic.serialise(doc) == bytes   |   python3 discovery/uic.py <folder>  (round-trip report)
when: any reading or editing of a layout (J6 layouts pass, J10 UI atlas, later the scale work); extend SPEC when a version's field is decoded
not-a-verb: a binary codec library, ported from empire-remastered ui_scale_mod/tools/uic.py (J6: V039 state_ref, animations; J10: V039 transitions and keyframe state changes)

Design: every byte is accounted for. Fields we understand get names; fields we don't are
kept as raw bytes with a fixed width. Serialising a parsed tree must reproduce the input
byte-for-byte (see roundtrip_all()).
"""
import struct, sys, os, json

# version-dependent widths: (component flag bytes, has c_flag, has i_b, f_raw, s_raw, imageuse tail, has e_a, has z_a)
SPEC = {
    31: dict(flags=7, c_flag=0, i_b=0, f_raw=15, s_raw=16, iu_tail=25, e_a=1, z_a=1),
    30: dict(flags=7, c_flag=0, i_b=0, f_raw=15, s_raw=16, iu_tail=22, e_a=1, z_a=1),
    29: dict(flags=7, c_flag=0, i_b=0, f_raw=15, s_raw=16, iu_tail=21, e_a=1, z_a=1),
    27: dict(flags=7, c_flag=0, i_a=0, i_b=0, f_raw=14, s_raw=16, iu_tail=21, e_a=1, z_a=1),
    26: dict(flags=7, c_flag=0, i_a=0, i_b=0, f_raw=14, s_raw=16, iu_tail=21, e_a=1, z_a=1, pre_font=1),
    22: dict(flags=7, c_flag=0, hdr_v20=1, i_a=0, i_b=0, f_raw=18, s_raw=16, iu_tail=9, e_a=1, z_a=1, pre_font=1),
    21: dict(flags=6, c_flag=0, hdr_v20=1, i_a=0, i_b=0, f_raw=18, s_raw=16, iu_tail=9, e_a=1, z_a=1, pre_font=1),
    20: dict(flags=6, c_flag=0, hdr_v20=1, i_a=0, i_b=0, f_raw=18, s_raw=16, iu_tail=9, e_a=1, z_a=1, pre_font=1),
    25: dict(flags=7, c_flag=0, i_a=0, i_b=0, f_raw=14, s_raw=16, iu_tail=21, e_a=1, z_a=1, pre_font=1),
    28: dict(flags=7, c_flag=0, i_b=0, f_raw=14, s_raw=16, iu_tail=21, e_a=1, z_a=1),
    33: dict(flags=7, c_flag=1, i_b=1, f_raw=15, s_raw=16, iu_tail=21, e_a=1, z_a=1),
    32: dict(flags=7, c_flag=0, i_b=1, f_raw=15, s_raw=16, iu_tail=21, e_a=1, z_a=1),
    # later game (J6): V033 plus a u32 default-state id after c_flag and an animation list before the child count
    39: dict(flags=7, c_flag=1, i_b=1, f_raw=15, s_raw=16, iu_tail=21, e_a=1, z_a=1, state_ref=1, anims=1, trans18=1),
    # uied.templates record v35 (J10): V033 plus V039's animation list and 18-byte transitions, no state_ref
    35: dict(flags=7, c_flag=1, i_b=1, f_raw=15, s_raw=16, iu_tail=21, e_a=1, z_a=1, anims=1, trans18=1),
    # legacy template-only versions (hdr_v16: [pre_inline raw][inline s][default_state s][u32 c_c]; no shader string)
    18: dict(flags=7, hdr_v16=1, pre_inline=3, c_flag=0, i_a=0, i_b=0, f_raw=10, shader=0, s_raw=8, iu_tail=3, x_ab=1, trans=1, e_a=1, z_a=1, pre_font=1),  # J10: v17 with 3 pre bytes (uied.templates Cursor)
    17: dict(flags=7, hdr_v16=1, pre_inline=2, c_flag=0, i_a=0, i_b=0, f_raw=10, shader=0, s_raw=8, iu_tail=3, x_ab=1, trans=1, e_a=1, z_a=1, pre_font=1),
    10: dict(flags=7, hdr_v16=1, pre_inline=3, c_c16=1, c_flag=0, i_a=0, i_b=0, legacy_state=56, iu_tail=0, e_a=0, events=2, z_a=1),
    9:  dict(flags=7, hdr_v16=1, pre_inline=3, c_c16=1, c_flag=0, i_a=0, i_b=0, legacy_state=56, iu_tail=0, e_a=0, events=2, z_a=1),
    12: dict(flags=7, hdr_v16=1, pre_inline=3, c_c16=1, c_flag=0, i_a=0, i_b=0, legacy_state=57, text2=1, legacy_ws=1, iu_tail=0, e_a=1, events=1, z_a=1),
    16: dict(flags=7, hdr_v16=1, pre_inline=2, c_flag=0, i_a=0, i_b=0, f_raw=6, shader=0, s_raw=15, iu_tail=0, x_ab=1, trans=1, e_a=1, z_a=1, pre_font=1),
}
def spec(ver): return SPEC.get(ver) or SPEC[32]

class R:
    def __init__(self, d, path='?'):
        self.d = d; self.p = 0; self.path = path
    def u8(self):  v = self.d[self.p]; self.p += 1; return v
    def u16(self): v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v
    def i32(self): v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v
    def u32(self): v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v
    def raw(self, n): v = self.d[self.p:self.p+n]; assert len(v) == n, self.err('eof'); self.p += n; return v
    def s(self):
        n = self.u16(); v = self.d[self.p:self.p+n]; self.p += n
        return v.decode('latin1')
    def ws(self):
        n = self.u16(); v = self.d[self.p:self.p+2*n]; self.p += 2*n
        return v.decode('utf-16le')
    def err(self, msg): return f'{self.path} @0x{self.p:x}: {msg}'

class W:
    def __init__(self): self.b = bytearray()
    def u8(self, v): self.b.append(v)
    def u16(self, v): self.b += struct.pack('<H', v)
    def i32(self, v): self.b += struct.pack('<i', v)
    def u32(self, v): self.b += struct.pack('<I', v)
    def raw(self, v): self.b += v
    def s(self, v): e = v.encode('latin1'); self.u16(len(e)); self.b += e
    def ws(self, v): self.u16(len(v)); self.b += v.encode('utf-16le')

# ---------------------------------------------------------------- image definition
def r_image(r):
    return dict(id=r.u32(), path=r.s(), w=r.i32(), h=r.i32(), colour=r.u32())
def w_image(w, im):
    w.u32(im['id']); w.s(im['path']); w.i32(im['w']); w.i32(im['h']); w.u32(im['colour'])

# ---------------------------------------------------------------- image use (inside a state)
def r_imageuse(r, ver):
    return dict(img=r.u32(), x=r.i32(), y=r.i32(), w=r.i32(), h=r.i32(), colour=r.u32(), tail=r.raw(spec(ver)['iu_tail']))
def w_imageuse(w, u):
    w.u32(u['img']); w.i32(u['x']); w.i32(u['y']); w.i32(u['w']); w.i32(u['h']); w.u32(u['colour']); w.raw(u['tail'])

# ---------------------------------------------------------------- state
CTX=[]
def r_state(r, ver):
    st = {'_off': r.p}; CTX.append(('state',st))
    st['id'] = r.u32(); st['name'] = r.s()
    st['w'] = r.i32(); st['h'] = r.i32()
    if spec(ver).get('legacy_state'):   # v9-v12: 8-bit text, [8-bit text2], fixed middle block, no font/shader strings
        rs = r.ws if spec(ver).get('legacy_ws') else r.s
        st['text'] = rs(); st['text2'] = rs() if spec(ver).get('text2') else ''
        st['mid'] = r.raw(spec(ver)['legacy_state']); st['font'] = ''; st['s_str1'] = r.s(); st['on_leave'] = r.s()
        n = r.u32(); st['uses'] = [r_imageuse(r, ver) for _ in range(n)]
        st['x_a'] = r.i32(); st['x_b'] = r.i32()
        n = r.u32(); st['transitions'] = [(r.u32(), r.u32()) for _ in range(n)]
        CTX.pop(); return st
    st['text'] = r.ws()
    st['text2'] = r.ws(); st['t_b'] = r.i32(); st['t_c'] = r.i32(); st['t_d'] = r.i32()
    st['t_e'] = r.u32(); st['t_f'] = r.u32(); st['t_g'] = r.u8()
    st['text_label'] = r.ws()
    st['text_label2'] = r.ws()
    st['pre_font'] = r.u16() if spec(ver).get('pre_font') else None
    st['font'] = r.s()
    st['f_a'] = r.u32(); st['f_b'] = r.u32(); st['font_colour'] = r.u32()
    st['f_raw'] = r.raw(spec(ver)['f_raw'])
    st['shader'] = r.s() if spec(ver).get('shader',1) else ''
    st['s_raw'] = r.raw(spec(ver)['s_raw']); st['s_str1'] = r.s(); st['on_leave'] = r.s()
    n = r.u32(); st['uses'] = [r_imageuse(r, ver) for _ in range(n)]
    st['x_a'] = r.i32() if spec(ver).get('x_ab',1) else 0; st['x_b'] = r.i32() if spec(ver).get('x_ab',1) else 0
    n = r.u32() if spec(ver).get('trans',1) else 0
    st['transitions'] = [r_trans(r) if spec(ver).get('trans18') else (r.u32(), r.u32()) for _ in range(n)]
    CTX.pop(); return st
# V039 (J10): u32 kind, u32 target state id, a string (an event or function name such as DisableAdviceAudio, mostly empty),
# 8 bytes (zero in vanilla): 18 bytes when the string is empty
def r_trans(r): return (r.u32(), r.u32(), r.s(), r.raw(8))
def w_trans(w, t): w.u32(t[0]); w.u32(t[1]); w.s(t[2]); w.raw(t[3])
def w_state(w, st, ver):
    w.u32(st['id']); w.s(st['name']); w.i32(st['w']); w.i32(st['h'])
    if spec(ver).get('legacy_state'):
        ws_ = w.ws if spec(ver).get('legacy_ws') else w.s
        ws_(st['text'])
        if spec(ver).get('text2'): ws_(st['text2'])
        w.raw(st['mid']); w.s(st['s_str1']); w.s(st['on_leave']); w.u32(len(st['uses']))
        for u in st['uses']: w_imageuse(w, u)
        w.i32(st['x_a']); w.i32(st['x_b']); w.u32(len(st['transitions']))
        for a, b in st['transitions']: w.u32(a); w.u32(b)
        return
    w.ws(st['text']); w.ws(st['text2']); w.i32(st['t_b']); w.i32(st['t_c']); w.i32(st['t_d'])
    w.u32(st['t_e']); w.u32(st['t_f']); w.u8(st['t_g'])
    w.ws(st['text_label']); w.ws(st['text_label2'])
    if spec(ver).get('pre_font'): w.u16(st['pre_font'])
    w.s(st['font'])
    w.u32(st['f_a']); w.u32(st['f_b']); w.u32(st['font_colour']); w.raw(st['f_raw'])
    if spec(ver).get('shader',1): w.s(st['shader'])
    w.raw(st['s_raw']); w.s(st['s_str1']); w.s(st['on_leave'])
    w.u32(len(st['uses']));
    for u in st['uses']: w_imageuse(w, u)
    if spec(ver).get('x_ab',1): w.i32(st['x_a']); w.i32(st['x_b'])
    if spec(ver).get('trans',1): w.u32(len(st['transitions']))
    for t in st['transitions']:
        if spec(ver).get('trans18'): w_trans(w, t)
        else: w.u32(t[0]); w.u32(t[1])

# ---------------------------------------------------------------- animation (V039: OnCreate etc.)
KEYFRAME = 48   # f32 x, f32 y, i32 w, i32 h, u32 rgba, ..., u32 time_ms at +36, u32 interpolation at +40 (J6, partly decoded)
# J10: u32 at +44 is a state-change flag; when set the frame goes on with u32 (uninitialised in vanilla), str, str (the state
# name the frame switches to: battle ui\lb_unit_id OnCreate cycles 000..012). A frame is bytes, or (bytes, u32, str, str).
def r_frame(r):
    k = r.raw(KEYFRAME)
    return (k, r.u32(), r.s(), r.s()) if struct.unpack_from('<I', k, 44)[0] else k
def w_frame(w, k):
    if isinstance(k, bytes): w.raw(k); return
    w.raw(k[0]); w.u32(k[1]); w.s(k[2]); w.s(k[3])
def frame_bytes(k): return k if isinstance(k, bytes) else k[0]
def r_anim(r):
    a = dict(name=r.s(), s2=r.s()); n = r.u32(); a['frames'] = [r_frame(r) for _ in range(n)]; return a
def w_anim(w, a):
    w.s(a['name']); w.s(a['s2']); w.u32(len(a['frames']))
    for k in a['frames']: w_frame(w, k)

# ---------------------------------------------------------------- component
def r_component(r, ver):
    c = {'_off': r.p}; CTX.append(('comp',c))
    c['id'] = r.u32(); c['name'] = r.s()
    c['x'] = r.i32(); c['y'] = r.i32()
    c['flags'] = r.raw(spec(ver)['flags'])
    sp = spec(ver)
    if not (sp.get('hdr_v20') or sp.get('hdr_v16')): c['template'] = r.s()
    if sp.get('hdr_v16'):            # v10-v17: [pre bytes][inline script][default state name][u32 c_c]
        c['template'] = ''; c['tooltip'] = ''; c['tooltip_label'] = ''; c['c_u8'] = None; c['c_flag'] = None; c['c_a'] = None
        c['pre_inline'] = r.raw(sp.get('pre_inline',0)); c['inline_script'] = r.s(); c['default_state'] = r.s(); c['c_c'] = r.u16() if sp.get('c_c16') else r.u32()
    elif sp.get('hdr_v20'):            # v20-v22: [u32 dock][inline script][u32 c_c]; no template/tooltip fields
        c['template'] = ''; c['tooltip'] = ''; c['tooltip_label'] = ''; c['c_u8'] = None; c['c_flag'] = None
        c['c_a'] = r.i32(); c['inline_script'] = r.s(); c['c_c'] = r.u32()
    else:
      c['c_a'] = r.i32() if sp.get('c_a',1) else None
      c['tooltip'] = r.ws() if sp.get('tooltip',1) else ''
      c['tooltip_label'] = r.ws() if sp.get('label',1) else ''
      c['c_u8'] = r.u8() if sp.get('c_u8',0) else None
      if sp.get('inline_first'):
        c['inline_script'] = r.s() if sp.get('inline',1) else ''
        c['c_c'] = r.u32() if sp.get('c_c',1) else None
        c['c_flag'] = None
      else:
        c['c_c'] = r.u32() if sp.get('c_c',1) else None
        c['c_flag'] = r.u8() if sp['c_flag'] else None
        c['state_ref'] = r.u32() if sp.get('state_ref') else None   # V039: id of the default state (0 = none)
        c['inline_script'] = r.s() if sp.get('inline',1) else ''
    n = r.u32(); c['images'] = [r_image(r) for _ in range(n)]
    c['i_a'] = r.u32() if spec(ver).get('i_a',1) else None; c['i_b'] = r.u32() if spec(ver)['i_b'] else None
    n = r.u32(); c['states'] = [r_state(r, ver) for _ in range(n)]
    c['e_a'] = r.u32() if spec(ver)['e_a'] else None
    c['e_raw'] = r.raw(spec(ver).get('e_raw',0))
    ev = []; c['e_pad'] = None; c['events_raw'] = b''
    if spec(ver).get('events',1) == 2:        # v9/v10: z_a, then u32 count + u16 event ids
        c['z_a'] = r.u32(); c['events_raw'] = r.raw(2 * r.u32())
    while spec(ver).get('events',1) == 1:
        # legacy quirk (campaign ui\sabotage, v029): a stray 0x0D byte before 'events_end'
        if ver < 32 and r.d[r.p] == 0x0d and r.d[r.p+1:r.p+13] == b'\x0a\x00events_end':
            c['e_pad'] = r.u8()
        s = r.s()
        if s == 'events_end': break
        ev.append(s)
    c['events'] = ev
    if spec(ver).get('events',1) != 2: c['z_a'] = r.u32() if spec(ver)['z_a'] else None
    c['anims'] = [r_anim(r) for _ in range(r.u32())] if spec(ver).get('anims') else None
    n = r.u32(); c['children'] = [r_component(r, ver) for _ in range(n)]
    c['script'] = r.s() if spec(ver).get('script',1) else ''
    CTX.pop(); return c
def w_component(w, c, ver):
    w.u32(c['id']); w.s(c['name']); w.i32(c['x']); w.i32(c['y']); w.raw(c['flags'])
    if not (spec(ver).get('hdr_v20') or spec(ver).get('hdr_v16')): w.s(c['template'])
    sp = spec(ver)
    if sp.get('hdr_v16'):
        w.raw(c['pre_inline']); w.s(c['inline_script']); w.s(c['default_state']); (w.u16 if sp.get('c_c16') else w.u32)(c['c_c'])
    elif sp.get('hdr_v20'):
        w.i32(c['c_a']); w.s(c['inline_script']); w.u32(c['c_c'])
    else:
      if sp.get('c_a',1): w.i32(c['c_a'])
      if sp.get('tooltip',1): w.ws(c['tooltip'])
      if sp.get('label',1): w.ws(c['tooltip_label'])
      if sp.get('c_u8',0): w.u8(c['c_u8'])
      if sp.get('inline_first'):
        if sp.get('inline',1): w.s(c['inline_script'])
        if sp.get('c_c',1): w.u32(c['c_c'])
      else:
        if sp.get('c_c',1): w.u32(c['c_c'])
        if sp['c_flag']: w.u8(c['c_flag'])
        if sp.get('state_ref'): w.u32(c['state_ref'])
        if sp.get('inline',1): w.s(c['inline_script'])
    w.u32(len(c['images']))
    for im in c['images']: w_image(w, im)
    if spec(ver).get('i_a',1): w.u32(c['i_a'])
    if spec(ver)['i_b']: w.u32(c['i_b'])
    w.u32(len(c['states']))
    for st in c['states']: w_state(w, st, ver)
    if spec(ver)['e_a']: w.u32(c['e_a'])
    w.raw(c.get('e_raw', b''))
    if spec(ver).get('events',1) == 2:
        w.u32(c['z_a']); w.u32(len(c['events_raw']) // 2); w.raw(c['events_raw'])
    if spec(ver).get('events',1) == 1:
        for e in c['events']: w.s(e)
        if c.get('e_pad') is not None: w.u8(c['e_pad'])
        w.s('events_end')
    if spec(ver)['z_a'] and spec(ver).get('events',1) != 2: w.u32(c['z_a'])
    if spec(ver).get('anims'):
        w.u32(len(c['anims']))
        for a in c['anims']: w_anim(w, a)
    w.u32(len(c['children']))
    for ch in c['children']: w_component(w, ch, ver)
    if spec(ver).get('script',1): w.s(c['script'])

# ---------------------------------------------------------------- file
def parse(d, path='?'):
    global LAST_R
    CTX.clear(); r = R(d, path); LAST_R = r
    magic = r.raw(10).decode()
    assert magic.startswith('Version'), r.err('bad magic')
    ver = int(magic[7:])
    root = r_component(r, ver)
    assert r.p == len(d), r.err(f'trailing {len(d)-r.p} bytes')
    return dict(version=ver, root=root)
def serialise(doc):
    w = W(); w.raw(f'Version{doc["version"]:03d}'.encode())
    w_component(w, doc['root'], doc['version'])
    return bytes(w.b)

def walk(c, depth=0):
    yield depth, c
    for ch in c['children']: yield from walk(ch, depth+1)

def roundtrip_all(folder):
    ok = fail = 0; failures = []
    for n in sorted(os.listdir(folder)):
        p = os.path.join(folder, n); d = open(p, 'rb').read()
        if not d.startswith(b'Version'): continue
        try:
            doc = parse(d, n); out = serialise(doc)
            if out == d: ok += 1
            else:
                fail += 1; i = next(i for i in range(min(len(d), len(out))) if d[i] != out[i]) if out != d[:len(out)] else min(len(d), len(out))
                failures.append(f'{n}: MISMATCH at 0x{i:x} (len {len(d)} vs {len(out)})')
        except Exception as e:
            fail += 1; failures.append(f'{n}: {type(e).__name__}: {e}')
    return ok, fail, failures

if __name__ == '__main__':
    ok, fail, failures = roundtrip_all(sys.argv[1])
    print(f'round-trip OK: {ok}  FAIL: {fail}')
    for f in failures: print('  ', f)
