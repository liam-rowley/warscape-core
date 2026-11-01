// capture.cpp - frame capture (J8, dev.capture): every device call of the next 1..8 frames, written as text lines to
// <dev.capture_dir>\<name>\frame.txt, and each shader's bytecode once per hash to <dev.capture_dir>\shaders\<hash>.vs|.ps.
// Game-agnostic, in the device layer. Decisions (the game repo's jobs/J8/brief.md):
//   - With dev.capture=0 nothing is hooked. With it on, the device's vtable slots below are hooked at CreateDevice; while no capture
//     runs each hook is one load and a branch before the real call, so the idle frame must match the baseline (checked on the PC).
//   - Every call of the captured frames is recorded, not the first draw per shader pair (an older capture's rule): draws,
//     render and depth targets, clears, StretchRect, shader binds, constant uploads with their values, textures per stage with their
//     desc, sampler, render and texture-stage states, viewport, scissor, streams, declarations. At arm time the state left by the
//     previous frame is read back (Get*) and written as a STATE block, so the frame reads complete from its first line.
//   - Shader hash: capture.h ShaderHash (canonical FNV-1a-64 to the walked end token), checked against GetFunction's size.
//   - Calls the runtime makes to itself through the vtable while a hook runs are not recorded twice (s_depth).
//   - The vtable of a device survives Reset, so the hooks stay armed across a device reset; a new device of the same class shares the
//     vtable (VtableHook keeps the first original); a device of another class gets its own hooks at its CreateDevice.
// Threads: the hooks and CapturePresent run on the render thread; CaptureRun (the ctl thread) arms a request and waits for its event.
// Record lines (one call per line, numbers decimal unless named; ptr and hash hex): see the game repo's proxy README "Frame capture".
#include "dev.h"
#include "capture.h"
#include <map>
#include <set>

namespace wsp {
namespace {

template <typename F> F Slot(void* o, int n) { return reinterpret_cast<F>((*reinterpret_cast<void***>(o))[n]); }
void Rel(void* o) { if (o) Slot<ULONG(WINAPI*)(void*)>(o, 2)(o); }
uintptr_t P(const void* p) { return reinterpret_cast<uintptr_t>(p); }

struct SurfDesc { uint32_t fmt, type, usage, pool, ms, msq, w, h; };   // D3DSURFACE_DESC
struct VolDesc { uint32_t fmt, type, usage, pool, w, h, d; };          // D3DVOLUME_DESC
struct VElem { uint16_t stream, offset; uint8_t type, method, usage, usageIndex; };   // D3DVERTEXELEMENT9
struct Viewport { uint32_t x, y, w, h; float minZ, maxZ; };            // D3DVIEWPORT9
const GUID kIidTexture9 = { 0x85C31227, 0x3DE5, 0x4f00, { 0x9B, 0x3A, 0xF1, 0x1A, 0xC3, 0x8C, 0x18, 0xB5 } };
const GUID kIidCubeTexture9 = { 0xFFF32F81, 0xD953, 0x473a, { 0x92, 0x23, 0x93, 0xD6, 0x52, 0xAB, 0xA9, 0x3F } };

enum : LONG { kIdle = 0, kArmed = 1, kRecording = 2, kDone = 3 };
volatile LONG s_state = kIdle;
volatile bool s_rec = false;     // the render thread records (kRecording)
int s_depth = 0;                 // > 0 inside a recorded call (render thread only)
bool s_hooked = false;
std::wstring s_root, s_dir;      // dev.capture_dir, <root>\<name>
std::string s_name, s_err;
int s_frames = 1, s_frame = 0;
HANDLE s_file = INVALID_HANDLE_VALUE, s_doneEv = nullptr;
std::string s_buf;
uint64_t s_bytes = 0, s_lines = 0, s_draws = 0;
std::map<void*, uint64_t> s_shaderHash;   // this capture's shader objects (pointers are only trusted within one capture)
std::set<void*> s_described;              // surfaces, textures and declarations already described in this capture
std::set<uint64_t> s_written;             // shader files written by this process
int s_shadersNew = 0, s_walkBad = 0, s_sizeMismatch = 0;
size_t s_capShaders = 0;                  // distinct shaders bound in the last capture
double s_t0 = 0;

void Flush() {
    if (s_buf.empty() || s_file == INVALID_HANDLE_VALUE) { s_buf.clear(); return; }
    DWORD wr = 0;
    if (!WriteFile(s_file, s_buf.data(), (DWORD)s_buf.size(), &wr, nullptr) || wr != s_buf.size()) s_err = "write failed (" + std::to_string(GetLastError()) + ")";
    s_bytes += s_buf.size(); s_buf.clear();
}
void Line(const std::string& l) { s_buf += l; s_buf += '\n'; ++s_lines; if (s_buf.size() > (4u << 20)) Flush(); }

void DescribeSurface(void* s) {
    if (!s || !s_described.insert(s).second) return;
    SurfDesc d{};
    std::string l = "SURF"; AppendX(l, P(s));
    if (SUCCEEDED(Slot<HRESULT(WINAPI*)(void*, SurfDesc*)>(s, 12)(s, &d))) {
        AppendU(l, d.w); AppendU(l, d.h); AppendU(l, d.fmt); AppendX(l, d.usage); AppendU(l, d.pool); AppendU(l, d.ms); AppendU(l, d.msq);
    } else l += " ? ? ? ? ? ? ?";
    void* c = nullptr;   // the texture it belongs to (a render target that is later sampled)
    if (FAILED(Slot<HRESULT(WINAPI*)(void*, const GUID&, void**)>(s, 11)(s, kIidTexture9, &c)) || !c) {
        c = nullptr; Slot<HRESULT(WINAPI*)(void*, const GUID&, void**)>(s, 11)(s, kIidCubeTexture9, &c);
    }
    AppendX(l, P(c)); Rel(c);
    Line(l);
}
void DescribeTexture(void* t) {
    if (!t || !s_described.insert(t).second) return;
    const uint32_t type = Slot<uint32_t(WINAPI*)(void*)>(t, 10)(t);   // D3DRESOURCETYPE: 3 texture, 4 volume, 5 cube
    const uint32_t levels = Slot<uint32_t(WINAPI*)(void*)>(t, 13)(t);
    std::string l = "TEX"; AppendX(l, P(t)); AppendU(l, type); AppendU(l, levels);
    if (type == 4) { VolDesc d{}; if (SUCCEEDED(Slot<HRESULT(WINAPI*)(void*, UINT, VolDesc*)>(t, 17)(t, 0, &d))) { AppendU(l, d.w); AppendU(l, d.h); AppendU(l, d.d); AppendU(l, d.fmt); AppendX(l, d.usage); AppendU(l, d.pool); } }
    else if (type == 3 || type == 5) { SurfDesc d{}; if (SUCCEEDED(Slot<HRESULT(WINAPI*)(void*, UINT, SurfDesc*)>(t, 17)(t, 0, &d))) { AppendU(l, d.w); AppendU(l, d.h); AppendU(l, 1); AppendU(l, d.fmt); AppendX(l, d.usage); AppendU(l, d.pool); } }
    Line(l);
}
void DescribeDecl(void* v) {
    if (!v || !s_described.insert(v).second) return;
    UINT n = 0; auto get = Slot<HRESULT(WINAPI*)(void*, VElem*, UINT*)>(v, 4);
    std::string l = "DECL"; AppendX(l, P(v));
    if (SUCCEEDED(get(v, nullptr, &n)) && n > 0 && n < 65) {
        VElem e[65]; if (SUCCEEDED(get(v, e, &n))) {
            AppendU(l, n);
            for (UINT i = 0; i < n && e[i].stream != 0xFF; ++i) { char b[64]; snprintf(b, sizeof b, " %u.%u.%u.%u.%u.%u", e[i].stream, e[i].offset, e[i].type, e[i].method, e[i].usage, e[i].usageIndex); l += b; }
        }
    }
    Line(l);
}
uint64_t ShaderOf(void* sh, bool pixel) {
    if (!sh) return 0;
    auto it = s_shaderHash.find(sh);
    if (it != s_shaderHash.end()) return it->second;
    auto fn = Slot<HRESULT(WINAPI*)(void*, void*, UINT*)>(sh, 4);   // GetFunction
    UINT size = 0; std::string code;
    if (SUCCEEDED(fn(sh, nullptr, &size)) && size >= 8 && size < (1u << 24)) { code.assign(size, '\0'); if (FAILED(fn(sh, &code[0], &size))) code.clear(); }
    size_t len = 0; bool ok = false;
    const uint64_t h = code.empty() ? 0 : ShaderHash(code.data(), code.size(), len, ok);
    if (!ok) ++s_walkBad; else if (len != code.size()) ++s_sizeMismatch;
    s_shaderHash[sh] = h;
    if (h && s_written.insert(h).second) {
        const std::wstring p = s_root + L"shaders\\" + WidenUtf8(Hex64(h)) + (pixel ? L".ps" : L".vs");
        if (GetFileAttributesW(p.c_str()) == INVALID_FILE_ATTRIBUTES) { WriteFileAtomic(p, ok ? code.substr(0, len) : code); ++s_shadersNew; }
    }
    std::string l = "SHADER"; AppendX(l, P(sh)); l += pixel ? " ps " : " vs "; l += Hex64(h); AppendU(l, code.size()); AppendU(l, ok ? len : 0);
    Line(l);
    return h;
}

// ---- the record functions (shared by the hooks and the STATE block) ------------------------------------------------------------
void RecRT(DWORD i, void* s) { DescribeSurface(s); std::string l = "RT"; AppendU(l, i); AppendX(l, P(s)); Line(l); }
void RecDS(void* s) { DescribeSurface(s); std::string l = "DS"; AppendX(l, P(s)); Line(l); }
void RecShader(void* sh, bool pixel) { const uint64_t h = ShaderOf(sh, pixel); Line(std::string(pixel ? "PS " : "VS ") + Hex64(h)); }
void RecConstF(bool pixel, UINT start, const float* v, UINT count) {
    std::string l = pixel ? "PC" : "VC"; AppendU(l, start); AppendU(l, count);
    if (v) for (UINT i = 0; i < count * 4; ++i) AppendFloat(l, v[i]);
    Line(l);
}
void RecConstI(bool pixel, UINT start, const int* v, UINT count) {
    std::string l = pixel ? "PI" : "VI"; AppendU(l, start); AppendU(l, count);
    if (v) for (UINT i = 0; i < count * 4; ++i) AppendI(l, v[i]);
    Line(l);
}
void RecConstB(bool pixel, UINT start, const BOOL* v, UINT count) {
    std::string l = pixel ? "PB" : "VB"; AppendU(l, start); AppendU(l, count);
    if (v) for (UINT i = 0; i < count; ++i) AppendI(l, v[i]);
    Line(l);
}
void RecTex(DWORD stage, void* t) { DescribeTexture(t); std::string l = "T"; AppendU(l, stage); AppendX(l, P(t)); Line(l); }
void Rec3(const char* tag, unsigned long long a, unsigned long long b, unsigned long long c) { std::string l = tag; AppendU(l, a); AppendU(l, b); AppendX(l, c); Line(l); }
void RecRS(DWORD s, DWORD v) { std::string l = "RS"; AppendU(l, s); AppendX(l, v); Line(l); }
void RecVP(const Viewport* v) { std::string l = "VP"; if (v) { AppendU(l, v->x); AppendU(l, v->y); AppendU(l, v->w); AppendU(l, v->h); AppendFloat(l, v->minZ); AppendFloat(l, v->maxZ); } Line(l); }
void RecScissor(const RECT* r) { std::string l = "SC"; if (r) { AppendI(l, r->left); AppendI(l, r->top); AppendI(l, r->right); AppendI(l, r->bottom); } Line(l); }
void RecDecl(void* v) { DescribeDecl(v); std::string l = "VD"; AppendX(l, P(v)); Line(l); }
void RecStream(UINT s, void* vb, UINT off, UINT stride) { std::string l = "SSRC"; AppendU(l, s); AppendX(l, P(vb)); AppendU(l, off); AppendU(l, stride); Line(l); }
void RecIdx(void* ib) { std::string l = "IDX"; AppendX(l, P(ib)); Line(l); }
void AppendRect(std::string& l, const RECT* r) { if (r) { AppendI(l, r->left); AppendI(l, r->top); AppendI(l, r->right); AppendI(l, r->bottom); } else l += " - - - -"; }

// The guard every hook takes: records only the outermost call while a capture runs.
struct Depth { bool on; Depth() : on(s_rec && s_depth == 0) { ++s_depth; } ~Depth() { --s_depth; } };

// ---- hooks (IDirect3DDevice9 vtable slots) ---------------------------------------------------------------------------------------
#define ORIG(name, ...) using T_##name = HRESULT(WINAPI*)(void*, __VA_ARGS__); T_##name o_##name
ORIG(StretchRect, void*, const RECT*, void*, const RECT*, DWORD);
ORIG(ColorFill, void*, const RECT*, DWORD);
ORIG(UpdateSurface, void*, const RECT*, void*, const POINT*);
ORIG(UpdateTexture, void*, void*);
ORIG(GetRenderTargetData, void*, void*);
ORIG(SetRenderTarget, DWORD, void*);
ORIG(SetDepthStencilSurface, void*);
ORIG(Clear, DWORD, const void*, DWORD, DWORD, float, DWORD);
ORIG(SetTransform, DWORD, const float*);
ORIG(SetViewport, const Viewport*);
ORIG(SetRenderState, DWORD, DWORD);
ORIG(EndStateBlock, void**);
ORIG(SetTexture, DWORD, void*);
ORIG(SetTextureStageState, DWORD, DWORD, DWORD);
ORIG(SetSamplerState, DWORD, DWORD, DWORD);
ORIG(SetScissorRect, const RECT*);
ORIG(DrawPrimitive, DWORD, UINT, UINT);
ORIG(DrawIndexedPrimitive, DWORD, INT, UINT, UINT, UINT, UINT);
ORIG(DrawPrimitiveUP, DWORD, UINT, const void*, UINT);
ORIG(DrawIndexedPrimitiveUP, DWORD, UINT, UINT, UINT, const void*, DWORD, const void*, UINT);
ORIG(SetVertexDeclaration, void*);
ORIG(SetFVF, DWORD);
ORIG(SetVertexShader, void*);
ORIG(SetVertexShaderConstantF, UINT, const float*, UINT);
ORIG(SetVertexShaderConstantI, UINT, const int*, UINT);
ORIG(SetVertexShaderConstantB, UINT, const BOOL*, UINT);
ORIG(SetStreamSource, UINT, void*, UINT, UINT);
ORIG(SetStreamSourceFreq, UINT, UINT);
ORIG(SetIndices, void*);
ORIG(SetPixelShader, void*);
ORIG(SetPixelShaderConstantF, UINT, const float*, UINT);
ORIG(SetPixelShaderConstantI, UINT, const int*, UINT);
ORIG(SetPixelShaderConstantB, UINT, const BOOL*, UINT);
using T_NoArg = HRESULT(WINAPI*)(void*);
T_NoArg o_BeginScene, o_EndScene, o_BeginStateBlock;

HRESULT WINAPI hk_StretchRect(void* d, void* s, const RECT* sr, void* t, const RECT* tr, DWORD f) {
    if (!s_rec) return o_StretchRect(d, s, sr, t, tr, f);
    Depth g; if (g.on) { DescribeSurface(s); DescribeSurface(t); std::string l = "STRETCH"; AppendX(l, P(s)); AppendRect(l, sr); AppendX(l, P(t)); AppendRect(l, tr); AppendU(l, f); Line(l); }
    return o_StretchRect(d, s, sr, t, tr, f);
}
HRESULT WINAPI hk_ColorFill(void* d, void* s, const RECT* r, DWORD c) {
    if (!s_rec) return o_ColorFill(d, s, r, c);
    Depth g; if (g.on) { DescribeSurface(s); std::string l = "FILL"; AppendX(l, P(s)); AppendRect(l, r); AppendX(l, c); Line(l); }
    return o_ColorFill(d, s, r, c);
}
HRESULT WINAPI hk_UpdateSurface(void* d, void* s, const RECT* r, void* t, const POINT* p) {
    if (!s_rec) return o_UpdateSurface(d, s, r, t, p);
    Depth g; if (g.on) { DescribeSurface(s); DescribeSurface(t); std::string l = "UPDSURF"; AppendX(l, P(s)); AppendX(l, P(t)); Line(l); }
    return o_UpdateSurface(d, s, r, t, p);
}
HRESULT WINAPI hk_UpdateTexture(void* d, void* s, void* t) {
    if (!s_rec) return o_UpdateTexture(d, s, t);
    Depth g; if (g.on) { DescribeTexture(s); DescribeTexture(t); std::string l = "UPDTEX"; AppendX(l, P(s)); AppendX(l, P(t)); Line(l); }
    return o_UpdateTexture(d, s, t);
}
HRESULT WINAPI hk_GetRenderTargetData(void* d, void* s, void* t) {
    if (!s_rec) return o_GetRenderTargetData(d, s, t);
    Depth g; if (g.on) { DescribeSurface(s); DescribeSurface(t); std::string l = "READBACK"; AppendX(l, P(s)); AppendX(l, P(t)); Line(l); }
    return o_GetRenderTargetData(d, s, t);
}
HRESULT WINAPI hk_SetRenderTarget(void* d, DWORD i, void* s) {
    if (!s_rec) return o_SetRenderTarget(d, i, s);
    Depth g; if (g.on) RecRT(i, s);
    return o_SetRenderTarget(d, i, s);
}
HRESULT WINAPI hk_SetDepthStencilSurface(void* d, void* s) {
    if (!s_rec) return o_SetDepthStencilSurface(d, s);
    Depth g; if (g.on) RecDS(s);
    return o_SetDepthStencilSurface(d, s);
}
HRESULT WINAPI hk_BeginScene(void* d) { if (!s_rec) return o_BeginScene(d); Depth g; if (g.on) Line("BEGIN"); return o_BeginScene(d); }
HRESULT WINAPI hk_EndScene(void* d) { if (!s_rec) return o_EndScene(d); Depth g; if (g.on) Line("END"); return o_EndScene(d); }
HRESULT WINAPI hk_BeginStateBlock(void* d) { if (!s_rec) return o_BeginStateBlock(d); Depth g; if (g.on) Line("SBBEGIN"); return o_BeginStateBlock(d); }
HRESULT WINAPI hk_EndStateBlock(void* d, void** sb) {
    if (!s_rec) return o_EndStateBlock(d, sb);
    Depth g; const HRESULT hr = o_EndStateBlock(d, sb);
    if (g.on) { std::string l = "SBEND"; AppendX(l, P(sb ? *sb : nullptr)); Line(l); }
    return hr;
}
HRESULT WINAPI hk_Clear(void* d, DWORD n, const void* rects, DWORD flags, DWORD color, float z, DWORD stencil) {
    if (!s_rec) return o_Clear(d, n, rects, flags, color, z, stencil);
    Depth g; if (g.on) { std::string l = "CLEAR"; AppendU(l, n); AppendX(l, flags); AppendX(l, color); AppendFloat(l, z); AppendU(l, stencil); Line(l); }
    return o_Clear(d, n, rects, flags, color, z, stencil);
}
HRESULT WINAPI hk_SetTransform(void* d, DWORD st, const float* m) {
    if (!s_rec) return o_SetTransform(d, st, m);
    Depth g; if (g.on) { std::string l = "XFORM"; AppendU(l, st); if (m) for (int i = 0; i < 16; ++i) AppendFloat(l, m[i]); Line(l); }
    return o_SetTransform(d, st, m);
}
HRESULT WINAPI hk_SetViewport(void* d, const Viewport* v) { if (!s_rec) return o_SetViewport(d, v); Depth g; if (g.on) RecVP(v); return o_SetViewport(d, v); }
HRESULT WINAPI hk_SetRenderState(void* d, DWORD s, DWORD v) {
    if (!s_rec) return o_SetRenderState(d, s, v);
    Depth g; if (g.on) RecRS(s, v);
    return o_SetRenderState(d, s, v);
}
HRESULT WINAPI hk_SetTexture(void* d, DWORD st, void* t) { if (!s_rec) return o_SetTexture(d, st, t); Depth g; if (g.on) RecTex(st, t); return o_SetTexture(d, st, t); }
HRESULT WINAPI hk_SetTextureStageState(void* d, DWORD st, DWORD ty, DWORD v) { if (!s_rec) return o_SetTextureStageState(d, st, ty, v); Depth g; if (g.on) Rec3("TSS", st, ty, v); return o_SetTextureStageState(d, st, ty, v); }
HRESULT WINAPI hk_SetSamplerState(void* d, DWORD sm, DWORD ty, DWORD v) { if (!s_rec) return o_SetSamplerState(d, sm, ty, v); Depth g; if (g.on) Rec3("SS", sm, ty, v); return o_SetSamplerState(d, sm, ty, v); }
HRESULT WINAPI hk_SetScissorRect(void* d, const RECT* r) { if (!s_rec) return o_SetScissorRect(d, r); Depth g; if (g.on) RecScissor(r); return o_SetScissorRect(d, r); }
HRESULT WINAPI hk_DrawPrimitive(void* d, DWORD ty, UINT start, UINT n) {
    if (!s_rec) return o_DrawPrimitive(d, ty, start, n);
    Depth g; if (g.on) { std::string l = "DP"; AppendU(l, ty); AppendU(l, start); AppendU(l, n); Line(l); ++s_draws; }
    return o_DrawPrimitive(d, ty, start, n);
}
HRESULT WINAPI hk_DrawIndexedPrimitive(void* d, DWORD ty, INT base, UINT mn, UINT nv, UINT si, UINT pc) {
    if (!s_rec) return o_DrawIndexedPrimitive(d, ty, base, mn, nv, si, pc);
    Depth g; if (g.on) { std::string l = "DIP"; AppendU(l, ty); AppendI(l, base); AppendU(l, mn); AppendU(l, nv); AppendU(l, si); AppendU(l, pc); Line(l); ++s_draws; }
    return o_DrawIndexedPrimitive(d, ty, base, mn, nv, si, pc);
}
HRESULT WINAPI hk_DrawPrimitiveUP(void* d, DWORD ty, UINT n, const void* v, UINT stride) {
    if (!s_rec) return o_DrawPrimitiveUP(d, ty, n, v, stride);
    Depth g; if (g.on) { std::string l = "DPUP"; AppendU(l, ty); AppendU(l, n); AppendU(l, stride); Line(l); ++s_draws; }
    return o_DrawPrimitiveUP(d, ty, n, v, stride);
}
HRESULT WINAPI hk_DrawIndexedPrimitiveUP(void* d, DWORD ty, UINT mn, UINT nv, UINT pc, const void* idx, DWORD fmt, const void* v, UINT stride) {
    if (!s_rec) return o_DrawIndexedPrimitiveUP(d, ty, mn, nv, pc, idx, fmt, v, stride);
    Depth g; if (g.on) { std::string l = "DIPUP"; AppendU(l, ty); AppendU(l, mn); AppendU(l, nv); AppendU(l, pc); AppendU(l, fmt); AppendU(l, stride); Line(l); ++s_draws; }
    return o_DrawIndexedPrimitiveUP(d, ty, mn, nv, pc, idx, fmt, v, stride);
}
HRESULT WINAPI hk_SetVertexDeclaration(void* d, void* v) { if (!s_rec) return o_SetVertexDeclaration(d, v); Depth g; if (g.on) RecDecl(v); return o_SetVertexDeclaration(d, v); }
HRESULT WINAPI hk_SetFVF(void* d, DWORD f) { if (!s_rec) return o_SetFVF(d, f); Depth g; if (g.on) { std::string l = "FVF"; AppendX(l, f); Line(l); } return o_SetFVF(d, f); }
HRESULT WINAPI hk_SetVertexShader(void* d, void* s) { if (!s_rec) return o_SetVertexShader(d, s); Depth g; if (g.on) RecShader(s, false); return o_SetVertexShader(d, s); }
HRESULT WINAPI hk_SetPixelShader(void* d, void* s) { if (!s_rec) return o_SetPixelShader(d, s); Depth g; if (g.on) RecShader(s, true); return o_SetPixelShader(d, s); }
HRESULT WINAPI hk_SetVertexShaderConstantF(void* d, UINT s, const float* v, UINT n) { if (!s_rec) return o_SetVertexShaderConstantF(d, s, v, n); Depth g; if (g.on) RecConstF(false, s, v, n); return o_SetVertexShaderConstantF(d, s, v, n); }
HRESULT WINAPI hk_SetVertexShaderConstantI(void* d, UINT s, const int* v, UINT n) { if (!s_rec) return o_SetVertexShaderConstantI(d, s, v, n); Depth g; if (g.on) RecConstI(false, s, v, n); return o_SetVertexShaderConstantI(d, s, v, n); }
HRESULT WINAPI hk_SetVertexShaderConstantB(void* d, UINT s, const BOOL* v, UINT n) { if (!s_rec) return o_SetVertexShaderConstantB(d, s, v, n); Depth g; if (g.on) RecConstB(false, s, v, n); return o_SetVertexShaderConstantB(d, s, v, n); }
HRESULT WINAPI hk_SetPixelShaderConstantF(void* d, UINT s, const float* v, UINT n) { if (!s_rec) return o_SetPixelShaderConstantF(d, s, v, n); Depth g; if (g.on) RecConstF(true, s, v, n); return o_SetPixelShaderConstantF(d, s, v, n); }
HRESULT WINAPI hk_SetPixelShaderConstantI(void* d, UINT s, const int* v, UINT n) { if (!s_rec) return o_SetPixelShaderConstantI(d, s, v, n); Depth g; if (g.on) RecConstI(true, s, v, n); return o_SetPixelShaderConstantI(d, s, v, n); }
HRESULT WINAPI hk_SetPixelShaderConstantB(void* d, UINT s, const BOOL* v, UINT n) { if (!s_rec) return o_SetPixelShaderConstantB(d, s, v, n); Depth g; if (g.on) RecConstB(true, s, v, n); return o_SetPixelShaderConstantB(d, s, v, n); }
HRESULT WINAPI hk_SetStreamSource(void* d, UINT s, void* vb, UINT off, UINT stride) { if (!s_rec) return o_SetStreamSource(d, s, vb, off, stride); Depth g; if (g.on) RecStream(s, vb, off, stride); return o_SetStreamSource(d, s, vb, off, stride); }
HRESULT WINAPI hk_SetStreamSourceFreq(void* d, UINT s, UINT f) { if (!s_rec) return o_SetStreamSourceFreq(d, s, f); Depth g; if (g.on) { std::string l = "FREQ"; AppendU(l, s); AppendX(l, f); Line(l); } return o_SetStreamSourceFreq(d, s, f); }
HRESULT WINAPI hk_SetIndices(void* d, void* ib) { if (!s_rec) return o_SetIndices(d, ib); Depth g; if (g.on) RecIdx(ib); return o_SetIndices(d, ib); }

// ---- the STATE block: what the previous frame left bound, read back at arm time -------------------------------------------------
template <typename F> F DevSlot(void* d, int n) { return Slot<F>(d, n); }
void WriteState(void* d) {
    Line("STATE");
    void* o = nullptr;
    if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, UINT, UINT, UINT, void**)>(d, 18)(d, 0, 0, 0, &o)) && o) {   // GetBackBuffer
        DescribeSurface(o); std::string l = "BACKBUFFER"; AppendX(l, P(o)); Line(l); Rel(o);
    }
    for (DWORD i = 0; i < 4; ++i) { o = nullptr; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, DWORD, void**)>(d, 38)(d, i, &o))) { RecRT(i, o); Rel(o); } }
    o = nullptr; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, void**)>(d, 40)(d, &o))) { RecDS(o); Rel(o); }
    Viewport vp{}; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, Viewport*)>(d, 48)(d, &vp))) RecVP(&vp);
    RECT sc{}; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, RECT*)>(d, 76)(d, &sc))) RecScissor(&sc);
    for (DWORD s = 0; s < 256; ++s) { DWORD v = 0; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, DWORD, DWORD*)>(d, 58)(d, s, &v))) RecRS(s, v); }
    const DWORD samplers[] = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 257, 258, 259, 260 };
    for (DWORD sm : samplers) {
        o = nullptr; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, DWORD, void**)>(d, 64)(d, sm, &o))) { RecTex(sm, o); Rel(o); }
        for (DWORD ty = 1; ty <= 13; ++ty) { DWORD v = 0; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, DWORD, DWORD, DWORD*)>(d, 68)(d, sm, ty, &v))) Rec3("SS", sm, ty, v); }
    }
    o = nullptr; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, void**)>(d, 88)(d, &o))) { RecDecl(o); Rel(o); }
    for (UINT s = 0; s < 8; ++s) {
        UINT off = 0, stride = 0, f = 0; o = nullptr;
        if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, UINT, void**, UINT*, UINT*)>(d, 101)(d, s, &o, &off, &stride))) { if (o || s == 0) RecStream(s, o, off, stride); Rel(o); }
        if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, UINT, UINT*)>(d, 103)(d, s, &f)) && f != 1) { std::string l = "FREQ"; AppendU(l, s); AppendX(l, f); Line(l); }
    }
    o = nullptr; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, void**)>(d, 105)(d, &o))) { RecIdx(o); Rel(o); }
    o = nullptr; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, void**)>(d, 93)(d, &o))) { RecShader(o, false); Rel(o); }
    o = nullptr; if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, void**)>(d, 108)(d, &o))) { RecShader(o, true); Rel(o); }
    static float f[256 * 4]; static int iv[16 * 4]; static BOOL bv[16];
    if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, UINT, float*, UINT)>(d, 95)(d, 0, f, 256))) RecConstF(false, 0, f, 256);
    if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, UINT, int*, UINT)>(d, 97)(d, 0, iv, 16))) RecConstI(false, 0, iv, 16);
    if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, UINT, BOOL*, UINT)>(d, 99)(d, 0, bv, 16))) RecConstB(false, 0, bv, 16);
    if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, UINT, float*, UINT)>(d, 110)(d, 0, f, 224))) RecConstF(true, 0, f, 224);
    if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, UINT, int*, UINT)>(d, 112)(d, 0, iv, 16))) RecConstI(true, 0, iv, 16);
    if (SUCCEEDED(DevSlot<HRESULT(WINAPI*)(void*, UINT, BOOL*, UINT)>(d, 114)(d, 0, bv, 16))) RecConstB(true, 0, bv, 16);
    Line("ENDSTATE");
}

void Close() {
    Flush();
    if (s_file != INVALID_HANDLE_VALUE) { CloseHandle(s_file); s_file = INVALID_HANDLE_VALUE; }
    s_shaderHash.clear(); s_described.clear();
}

} // namespace

bool CaptureHooked() { return s_hooked; }

void CaptureEvent(int kind, const wchar_t* name) {   // the engine's D3DPERF events: pass names when the engine emits them
    if (!s_rec || s_depth) return;
    std::string l = kind == 0 ? "EVENT " : kind == 1 ? "EVENTEND" : "MARKER ";
    if (kind != 1) l += name ? Narrow(name) : std::string("?");
    Line(l);
}

void CaptureInstall(void* dev) {
    if (!Dk().capture || !dev) return;
    void** vt = *(void***)dev;
    struct H { int slot; void* hk; void** orig; const char* name; } hs[] = {
        { 30, (void*)hk_UpdateSurface, (void**)&o_UpdateSurface, "UpdateSurface" }, { 31, (void*)hk_UpdateTexture, (void**)&o_UpdateTexture, "UpdateTexture" },
        { 32, (void*)hk_GetRenderTargetData, (void**)&o_GetRenderTargetData, "GetRenderTargetData" },
        { 34, (void*)hk_StretchRect, (void**)&o_StretchRect, "StretchRect" }, { 35, (void*)hk_ColorFill, (void**)&o_ColorFill, "ColorFill" },
        { 37, (void*)hk_SetRenderTarget, (void**)&o_SetRenderTarget, "SetRenderTarget" }, { 39, (void*)hk_SetDepthStencilSurface, (void**)&o_SetDepthStencilSurface, "SetDepthStencilSurface" },
        { 41, (void*)hk_BeginScene, (void**)&o_BeginScene, "BeginScene" }, { 42, (void*)hk_EndScene, (void**)&o_EndScene, "EndScene" },
        { 43, (void*)hk_Clear, (void**)&o_Clear, "Clear" }, { 44, (void*)hk_SetTransform, (void**)&o_SetTransform, "SetTransform" },
        { 47, (void*)hk_SetViewport, (void**)&o_SetViewport, "SetViewport" }, { 57, (void*)hk_SetRenderState, (void**)&o_SetRenderState, "SetRenderState" },
        { 60, (void*)hk_BeginStateBlock, (void**)&o_BeginStateBlock, "BeginStateBlock" }, { 61, (void*)hk_EndStateBlock, (void**)&o_EndStateBlock, "EndStateBlock" },
        { 65, (void*)hk_SetTexture, (void**)&o_SetTexture, "SetTexture" }, { 67, (void*)hk_SetTextureStageState, (void**)&o_SetTextureStageState, "SetTextureStageState" },
        { 69, (void*)hk_SetSamplerState, (void**)&o_SetSamplerState, "SetSamplerState" }, { 75, (void*)hk_SetScissorRect, (void**)&o_SetScissorRect, "SetScissorRect" },
        { 81, (void*)hk_DrawPrimitive, (void**)&o_DrawPrimitive, "DrawPrimitive" }, { 82, (void*)hk_DrawIndexedPrimitive, (void**)&o_DrawIndexedPrimitive, "DrawIndexedPrimitive" },
        { 83, (void*)hk_DrawPrimitiveUP, (void**)&o_DrawPrimitiveUP, "DrawPrimitiveUP" }, { 84, (void*)hk_DrawIndexedPrimitiveUP, (void**)&o_DrawIndexedPrimitiveUP, "DrawIndexedPrimitiveUP" },
        { 87, (void*)hk_SetVertexDeclaration, (void**)&o_SetVertexDeclaration, "SetVertexDeclaration" }, { 89, (void*)hk_SetFVF, (void**)&o_SetFVF, "SetFVF" },
        { 92, (void*)hk_SetVertexShader, (void**)&o_SetVertexShader, "SetVertexShader" }, { 94, (void*)hk_SetVertexShaderConstantF, (void**)&o_SetVertexShaderConstantF, "SetVertexShaderConstantF" },
        { 96, (void*)hk_SetVertexShaderConstantI, (void**)&o_SetVertexShaderConstantI, "SetVertexShaderConstantI" }, { 98, (void*)hk_SetVertexShaderConstantB, (void**)&o_SetVertexShaderConstantB, "SetVertexShaderConstantB" },
        { 100, (void*)hk_SetStreamSource, (void**)&o_SetStreamSource, "SetStreamSource" }, { 102, (void*)hk_SetStreamSourceFreq, (void**)&o_SetStreamSourceFreq, "SetStreamSourceFreq" },
        { 104, (void*)hk_SetIndices, (void**)&o_SetIndices, "SetIndices" }, { 107, (void*)hk_SetPixelShader, (void**)&o_SetPixelShader, "SetPixelShader" },
        { 109, (void*)hk_SetPixelShaderConstantF, (void**)&o_SetPixelShaderConstantF, "SetPixelShaderConstantF" }, { 111, (void*)hk_SetPixelShaderConstantI, (void**)&o_SetPixelShaderConstantI, "SetPixelShaderConstantI" },
        { 113, (void*)hk_SetPixelShaderConstantB, (void**)&o_SetPixelShaderConstantB, "SetPixelShaderConstantB" },
    };
    int ok = 0;
    for (const H& h : hs) {
        char n[64]; snprintf(n, sizeof n, "IDirect3DDevice9::%s", h.name);
        if (vt[h.slot] == h.hk) { ++ok; continue; }      // a second device of this class
        if (VtableHook(vt, h.slot, h.hk, *h.orig ? nullptr : h.orig, n)) ++ok;   // keep the first original: a later device of the same class shares it
    }
    s_hooked = ok == (int)(sizeof hs / sizeof hs[0]);
    if (!s_doneEv) s_doneEv = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    LOGI("capture: %d of %d device slots hooked (dev.capture=1, dir '%ls')", ok, (int)(sizeof hs / sizeof hs[0]), s_root.c_str());
}

void CaptureInit() {   // the folder sits outside the game folder (D25: the uninstall stays byte-exact); empty refuses every capture
    std::wstring r = Dk().captureDir;
    if (!r.empty() && r.back() != L'\\') r += L'\\';
    s_root = r;
}

// The render thread, every Present (before the real Present): closes a recorded frame, starts the next, or arms a waiting request.
void CapturePresent(void* dev) {
    const LONG st = s_state;
    if (st == kRecording) {
        Line("PRESENT");
        if (++s_frame < s_frames) { Line("FRAME " + std::to_string(s_frame + 1)); return; }
        s_rec = false;
        { std::set<uint64_t> u; for (auto& kv : s_shaderHash) if (kv.second) u.insert(kv.second); s_capShaders = u.size(); }
        Close();
        InterlockedExchange(&s_state, kDone);
        SetEvent(s_doneEv);
        return;
    }
    if (st != kArmed || !dev) return;
    s_file = CreateFileW((s_dir + L"frame.txt").c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (s_file == INVALID_HANDLE_VALUE) { s_err = "cannot create frame.txt (" + std::to_string(GetLastError()) + ")"; InterlockedExchange(&s_state, kDone); SetEvent(s_doneEv); return; }
    s_buf.reserve(5u << 20);
    s_bytes = s_lines = s_draws = 0; s_shadersNew = s_walkBad = s_sizeMismatch = 0; s_frame = 0;
    char h[400];
    snprintf(h, sizeof h, "CAPTURE %s launch %s build %s frames %d utc %s scene %s", s_name.c_str(), Rt().launchId.c_str(), WSP_BUILD_ID, s_frames,
             UtcIso(UnixMs()).c_str(), DevSceneNow().c_str());
    Line(h);
    s_depth = 1; WriteState(dev); s_depth = 0;   // the Get* reads call no hook, but a runtime may forward one through its vtable
    Line("FRAME 1");
    s_t0 = MonoS();
    s_rec = true;
    InterlockedExchange(&s_state, kRecording);
}

// The ctl thread: `capture <name> [frames]`. ok + the result members, or false + why.
bool CaptureRun(const std::string& name, int frames, double timeoutS, std::string& result, std::string& why) {
    if (!Dk().capture) { why = "dev.capture=0"; return false; }
    if (!s_hooked) { why = "the device is not hooked (no device created yet, or a slot failed: see the log)"; return false; }
    if (s_state != kIdle) { why = "a capture is running"; return false; }
    if (s_root.empty()) { why = "dev.capture_dir is empty (a folder outside the game folder)"; return false; }
    CreateDirectoryW(s_root.c_str(), nullptr);
    CreateDirectoryW((s_root + L"shaders").c_str(), nullptr);
    s_dir = s_root + WidenUtf8(name) + L"\\";
    if (GetFileAttributesW(s_dir.c_str()) != INVALID_FILE_ATTRIBUTES) { why = "capture " + name + " exists already (names are never reused)"; return false; }
    if (!CreateDirectoryW(s_dir.c_str(), nullptr)) { why = "cannot create " + Narrow(s_dir) + " (" + std::to_string(GetLastError()) + ")"; return false; }
    s_name = name; s_frames = frames; s_err.clear();
    ResetEvent(s_doneEv);
    const double t0 = MonoS();
    InterlockedExchange(&s_state, kArmed);
    if (WaitForSingleObject(s_doneEv, (DWORD)(timeoutS * 1000)) != WAIT_OBJECT_0) {
        if (InterlockedCompareExchange(&s_state, kIdle, kArmed) == kArmed) { why = "no Present within the timeout: nothing recorded"; return false; }
        WaitForSingleObject(s_doneEv, 30000);   // recording: it ends at the next Present(s)
    }
    const double recS = MonoS() - s_t0;
    char b[700];
    snprintf(b, sizeof b, "\"dir\": %s, \"file\": %s, \"shader_dir\": %s, \"frames\": %d, \"bytes\": %llu, \"lines\": %llu, \"draws\": %llu, "
             "\"shaders\": %zu, \"shaders_new\": %d, \"shaders_unwalked\": %d, \"shaders_size_differs\": %d, \"record_s\": %.3f, \"wait_s\": %.3f",
             JStr(Narrow(s_dir)).c_str(), JStr(Narrow(s_dir) + "frame.txt").c_str(), JStr(Narrow(s_root) + "shaders\\").c_str(), s_frame, (unsigned long long)s_bytes,
             (unsigned long long)s_lines, (unsigned long long)s_draws, s_capShaders, s_shadersNew, s_walkBad, s_sizeMismatch, recS, MonoS() - t0);
    result = b;
    const bool ok = s_err.empty();
    if (!ok) why = s_err;
    InterlockedExchange(&s_state, kIdle);
    return ok;
}

} // namespace wsp
