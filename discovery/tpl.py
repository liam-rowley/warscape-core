"""uied.templates container: u32 count, then records: 252-byte name field (name\\0 + 0xFD pad),
u32 version, u32 size, u32 self_offset, u32 ntex, then `size` bytes of payload (textures + component).
First record (InputWindow, version 4) is older: 256-byte name field, [size, version, ntex].

purpose: split data\\ui\\templates\\uied.templates into records and round-trip each record's textures and component through uic.py
usage: python3 discovery/tpl.py <uied.templates>   |   import tpl; tpl.split(bytes); tpl.parse_record(rec); tpl.serialise_record(doc, ver)
when: reading the UiEd template library (J6 layouts pass; later the UI atlas)
not-a-verb: a binary codec library, ported unchanged from empire-remastered ui_scale_mod/tools/tpl.py
"""
import struct
def split(d):
    n=struct.unpack_from('<I',d,0)[0]; recs=[]; p=4
    while p < len(d):
        name=d[p:d.find(b'\0',p)].decode('latin1')
        if p==4:   # legacy first record
            size,ver,ntex=struct.unpack_from('<III',d,p+256); body=d[p+256+12:p+256+12+size-4]
            recs.append(dict(name=name,hdr=p,ver=ver,ntex=ntex,payload=body,legacy=True)); p=p+256+8+size; continue
        ver,size,off,ntex=struct.unpack_from('<IIII',d,p+252)
        assert off==p, (name,hex(p),hex(off))
        body=d[p+252+16:p+252+12+size]
        recs.append(dict(name=name,hdr=p,ver=ver,ntex=ntex,payload=body,legacy=False)); p=p+252+12+size
    assert len(recs)==n,(len(recs),n); return recs
if __name__=='__main__':
    import collections,sys
    recs=split(open(sys.argv[1],'rb').read())
    print(len(recs),'records; versions',sorted(collections.Counter(r['ver'] for r in recs).items()))
    for r in recs: print(f"  {r['name']:36} v{r['ver']:<3} ntex={r['ntex']:<2} payload={len(r['payload'])}")

# ---------------------------------------------------------------- template component = textures + layout component
import uic
def r_textures(rd, n):
    texs=[]
    for i in range(n):
        path=rd.s(); start=rd.p; h=rd.raw(18); idlen=h[0]; w,hh=struct.unpack_from('<HH',h,12); bpp=h[16]
        assert h[2] in (2,3,10), f'{rd.path}: tga type {h[2]} @{start:#x}'
        assert h[2]!=10, f'{rd.path}: RLE tga not handled'
        rd.raw(idlen + w*hh*(bpp//8)); texs.append(dict(path=path, tga=rd.d[start:rd.p]))
    return texs
def w_textures(w, texs):
    for t in texs: w.s(t['path']); w.raw(t['tga'])

_orig_rc=uic.r_component; _orig_wc=uic.w_component
def r_tcomponent(rd, ver):
    n=rd.u32(); texs=r_textures(rd,n)
    c=_orig_rc(rd,ver); c['textures']=texs; return c
def w_tcomponent(w, c, ver):
    w.u32(len(c['textures'])); w_textures(w,c['textures']); _orig_wc(w,c,ver)

def parse_record(r):
    rd=uic.R(r['payload'], r['name']); uic.CTX.clear()
    texs=r_textures(rd, r['ntex'])
    uic.r_component=r_tcomponent
    try: c=_orig_rc(rd, r['ver'])
    finally: uic.r_component=_orig_rc
    assert rd.p==len(r['payload']), f"{r['name']}: trailing {len(r['payload'])-rd.p}"
    return dict(textures=texs, root=c)
def serialise_record(doc, ver):
    w=uic.W(); w_textures(w, doc['textures'])
    uic.w_component=w_tcomponent
    try: _orig_wc(w, doc['root'], ver)
    finally: uic.w_component=_orig_wc
    return bytes(w.b)
