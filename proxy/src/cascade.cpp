// cascade.cpp - J25 spike, not for shipping: the device half of the two-cascade prototype behind dev.cascade_proto. Route 1 variant (a): every
// caster draw of the engine's shadow pass is drawn a second time into a near cascade target, with the near matrix in that caster's own registers.
// Decisions (the game repo's jobs/J25/brief.md and report.md):
//   - The engine's state is never left changed: the registers, target, depth surface, viewport and scissor are put back after each duplicate.
//   - The bound vertex shader is read at the draw (GetVertexShader), never tracked: the pass applies 60-75 state blocks, which no Set* hook sees.
//   - Casters are found by their own CTAB at CreateVertexShader, so an unknown shader model or register needs no table.
//   - Receivers are swapped by hash at CreatePixelShader from <dev.cascade_dir>\<hash>.ps, each through CtabGate (fail = stock, logged).
//   - Install before the capture, so a capture sees the engine's calls and this module's own target switches stay out of the record. The cascade's
//     constants go through the device's vtable on purpose: a capture then records them (the density metric reads them).
#include "dev.h"
#include "capture.h"
#include "cascade.h"
#include <map>

namespace wsp {
namespace {

template <typename F> F Slot(void* o, int n) { return reinterpret_cast<F>((*reinterpret_cast<void***>(o))[n]); }
void Rel(void* o) { if (o) Slot<ULONG(WINAPI*)(void*)>(o, 2)(o); }
struct SurfDesc { uint32_t fmt, type, usage, pool, ms, msq, w, h; };
struct Viewport { uint32_t x, y, w, h; float minZ, maxZ; };

#define ORIG(name, ...) using T_##name = HRESULT(WINAPI*)(void*, __VA_ARGS__); T_##name o_##name
ORIG(Reset, void*);
ORIG(CreateVertexBuffer, UINT, DWORD, DWORD, DWORD, void**, void*);
ORIG(CreateIndexBuffer, UINT, DWORD, DWORD, DWORD, void**, void*);
ORIG(SetRenderTarget, DWORD, void*);
ORIG(SetDepthStencilSurface, void*);
ORIG(Clear, DWORD, const void*, DWORD, DWORD, float, DWORD);
ORIG(SetViewport, const Viewport*);
ORIG(SetScissorRect, const RECT*);
ORIG(SetTexture, DWORD, void*);
ORIG(DrawPrimitive, DWORD, UINT, UINT);
ORIG(DrawIndexedPrimitive, DWORD, INT, UINT, UINT, UINT, UINT);
ORIG(DrawPrimitiveUP, DWORD, UINT, const void*, UINT);
ORIG(DrawIndexedPrimitiveUP, DWORD, UINT, UINT, UINT, const void*, DWORD, const void*, UINT);
ORIG(CreateVertexShader, const DWORD*, void**);
ORIG(CreatePixelShader, const DWORD*, void**);
ORIG(SetVertexShaderConstantF, UINT, const float*, UINT);
using T_Lock = HRESULT(WINAPI*)(void*, UINT, UINT, void**, DWORD);
T_Lock o_VbLock, o_IbLock;

struct Keys { bool tint = false, count = false; int split = 40, size = 0; float blend = 0.05f; std::wstring dir; } s_k;
CRITICAL_SECTION s_cs;
struct Lock { Lock() { EnterCriticalSection(&s_cs); } ~Lock() { LeaveCriticalSection(&s_cs); } };

struct Caster { int m, lz; };
std::map<void*, Caster> s_casters;       // vertex shader object -> its registers (under s_cs)
std::map<void*, int> s_receivers;        // pixel shader object -> 1 swapped, 2 stock (under s_cs; only with dev.cascade_count)
std::map<void*, uint64_t> s_psHash;      // receiver and skip-target objects -> their stock hash (under s_cs)
std::map<uint64_t, long long> s_stockDraws;   // draws per stock receiver (under s_cs)
uint64_t s_skipHash = 0; std::map<void*, bool> s_skipPs; long long s_skipped = 0;   // dev.cascade_skip_ps: that shader's draws are not made
std::map<uint64_t, std::string> s_swap;  // stock hash -> replacement bytecode

PassTracker s_pass;
void* s_mapSurf = nullptr; void* s_mapDepth = nullptr;   // the pass's own target and depth, held from the first caster to the pass's end
void* s_tex = nullptr; void* s_surf = nullptr; void* s_depth = nullptr;   // the near cascade (default pool: released at Reset)
int s_texSize = 0; uint32_t s_texFmt = 0;
bool s_frameReady = false;                // this pass has a fit and a cleared target
bool s_noFit = false;                     // this pass could not fit: its casters are counted, not drawn
CascadeFit s_fit;
std::string s_fitWhy;
DWORD s_renderTid = 0;
bool s_tracedPass = false, s_tracedDraw = false;

struct Counts { long long frames, passes, seen, dup, unknown, nofit, lockDiscard, lockNoOver, lockOther, lockOtherThread, swappedDraws, stockDraws, swapped, refused, casters; } s_n;

// Every 4-byte value on the stack that points into the exe's image: the call chain, for question 3 (candidates, not a proper unwind).
void TraceStack(const char* what) {
    const uintptr_t base = (uintptr_t)GetModuleHandleW(nullptr);
    const auto* dos = (const IMAGE_DOS_HEADER*)base;
    const auto* nt = (const IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    const uintptr_t lo = base + nt->OptionalHeader.BaseOfCode, hi = lo + nt->OptionalHeader.SizeOfCode;
    const auto* sp = (const uintptr_t*)__builtin_frame_address(0);
    std::string l; int n = 0;
    for (int i = 0; i < 1024 && n < 28; ++i) {
        const uintptr_t v = sp[i];
        if (v >= lo && v < hi) { char b[16]; snprintf(b, sizeof b, " %lx", (unsigned long)(v - base + nt->OptionalHeader.ImageBase)); l += b; ++n; }
    }
    LOGI("cascade: stack at %s:%s", what, l.c_str());
}

void ReleaseCascade() { Rel(s_surf); Rel(s_depth); Rel(s_tex); s_surf = s_depth = s_tex = nullptr; s_texSize = 0; }
void ReleasePassRefs() { Rel(s_mapSurf); Rel(s_mapDepth); s_mapSurf = s_mapDepth = nullptr; }

bool EnsureTarget(void* d, const SurfDesc& map) {
    const int want = s_k.size > 0 ? s_k.size : (int)map.w;
    if (s_tex && s_texSize == want && s_texFmt == map.fmt) return true;
    ReleaseCascade();
    auto createTex = Slot<HRESULT(WINAPI*)(void*, UINT, UINT, UINT, DWORD, DWORD, DWORD, void**, void*)>(d, 23);
    auto createDs = Slot<HRESULT(WINAPI*)(void*, UINT, UINT, DWORD, DWORD, DWORD, BOOL, void**, void*)>(d, 29);
    if (FAILED(createTex(d, want, want, 1, 1 /* RENDERTARGET */, map.fmt, 0 /* DEFAULT */, &s_tex, nullptr)) || !s_tex) { s_fitWhy = "cannot create the cascade target"; return false; }
    if (FAILED(Slot<HRESULT(WINAPI*)(void*, UINT, void**)>(s_tex, 18)(s_tex, 0, &s_surf)) || !s_surf) { s_fitWhy = "no cascade surface"; return false; }
    if (FAILED(createDs(d, want, want, 77 /* D24X8 */, 0, 0, TRUE, &s_depth, nullptr)) || !s_depth) { s_fitWhy = "cannot create the cascade depth"; return false; }
    s_texSize = want; s_texFmt = map.fmt;
    LOGI("cascade: target %dx%d format %u (engine map %ux%u)", want, want, map.fmt, map.w, map.h);
    return true;
}

// The cascade's constants and sampler. Zero matrix = every pixel outside the map = stock: the state before any fit, and of a frame with none.
void BindConstants(void* d, const float* m) {
    static const float zero[16] = {};
    const float params[4] = { s_texSize ? 1.0f / (float)s_texSize : 1.0f, (float)s_texSize, s_k.blend, s_k.tint ? 1.0f : 0.0f };
    auto setPc = Slot<HRESULT(WINAPI*)(void*, UINT, const float*, UINT)>(d, 109);
    setPc(d, 216, m ? m : zero, 4); setPc(d, 220, params, 1);
}
void BindSampler(void* d) {
    auto setSs = Slot<HRESULT(WINAPI*)(void*, DWORD, DWORD, DWORD)>(d, 69);
    setSs(d, 15, 1, 4); setSs(d, 15, 2, 4); setSs(d, 15, 3, 4); setSs(d, 15, 4, 0xFFFFFFFF);   // BORDER on all axes, white: outside the map is lit
    setSs(d, 15, 5, 1); setSs(d, 15, 6, 1); setSs(d, 15, 7, 0); setSs(d, 15, 11, 0);           // POINT, no mips, no sRGB
}

// The first caster of a pass: read the engine's linear-z row, fit, make and clear the target. Target left as the engine's.
void BeginCascadeFrame(void* d, const Caster& c) {
    s_noFit = true;
    float cam[3], tgt[3], lz[12]; std::string why;
    if (!CameraRead(8, 0x14, cam, tgt, why)) { s_fitWhy = why; return; }
    if (FAILED(Slot<HRESULT(WINAPI*)(void*, UINT, float*, UINT)>(d, 95)(d, c.lz, lz, 3))) { s_fitWhy = "GetVertexShaderConstantF"; return; }
    if (FAILED(Slot<HRESULT(WINAPI*)(void*, DWORD, void**)>(d, 38)(d, 0, &s_mapSurf)) || !s_mapSurf) { s_fitWhy = "GetRenderTarget"; return; }
    if (FAILED(Slot<HRESULT(WINAPI*)(void*, void**)>(d, 40)(d, &s_mapDepth)) || !s_mapDepth) { s_fitWhy = "GetDepthStencilSurface"; return; }
    SurfDesc md{};
    if (FAILED(Slot<HRESULT(WINAPI*)(void*, SurfDesc*)>(s_mapSurf, 12)(s_mapSurf, &md)) || !EnsureTarget(d, md)) return;
    const float tanHalfY = 0.70020753f, aspect = 16.0f / 9.0f;   // 70.0 degrees vertical (fact napoleon.battle.camera_route); 16:9 at every measured size
    s_fit = FitCascade(cam, tgt, lz + 8, 0.0005f, tanHalfY, aspect, 1.0f, (float)s_k.split, s_texSize);
    if (!s_fit.ok) { s_fitWhy = "FitCascade refused"; return; }
    o_SetTexture(d, 15, nullptr);   // the target is about to be written: it must not stay bound as a texture
    o_SetRenderTarget(d, 0, s_surf); o_SetDepthStencilSurface(d, s_depth);
    o_Clear(d, 0, nullptr, 3, 0xFFFFFFFF, 1.0f, 0);
    o_SetRenderTarget(d, 0, s_mapSurf); o_SetDepthStencilSurface(d, s_mapDepth);
    s_noFit = false; s_fitWhy.clear();
}

template <class Draw> HRESULT Dup(void* d, Draw draw) {
    if (s_skipHash) {
        void* ps = nullptr; bool skip = false;
        if (SUCCEEDED(Slot<HRESULT(WINAPI*)(void*, void**)>(d, 108)(d, &ps)) && ps) { { Lock l; skip = s_skipPs.count(ps) != 0; } Rel(ps); }
        if (skip) { ++s_skipped; return 0; }
    }
    const HRESULT hr = draw();
    if (!s_pass.in) {
        if (s_k.count) {
            void* ps = nullptr;
            if (SUCCEEDED(Slot<HRESULT(WINAPI*)(void*, void**)>(d, 108)(d, &ps)) && ps) {
                { Lock l; auto it = s_receivers.find(ps); if (it != s_receivers.end()) { ++(it->second == 1 ? s_n.swappedDraws : s_n.stockDraws); if (it->second == 2) ++s_stockDraws[s_psHash[ps]]; } }
                Rel(ps);
            }
        }
        return hr;
    }
    ++s_n.seen;
    void* vs = nullptr; Caster c{ -1, -1 };
    if (SUCCEEDED(Slot<HRESULT(WINAPI*)(void*, void**)>(d, 93)(d, &vs)) && vs) {
        { Lock l; auto it = s_casters.find(vs); if (it != s_casters.end()) c = it->second; }
        Rel(vs);
    }
    if (c.m < 0) { ++s_n.unknown; return hr; }
    if (!s_frameReady) { BeginCascadeFrame(d, c); s_frameReady = true; }
    if (!s_tracedDraw && !s_noFit) { s_tracedDraw = true; TraceStack("first caster draw"); }
    if (s_noFit) { ++s_n.nofit; return hr; }
    Viewport vp{}; RECT sc{}; float saved[16];
    Slot<HRESULT(WINAPI*)(void*, Viewport*)>(d, 48)(d, &vp);
    Slot<HRESULT(WINAPI*)(void*, RECT*)>(d, 76)(d, &sc);
    Slot<HRESULT(WINAPI*)(void*, UINT, float*, UINT)>(d, 95)(d, c.m, saved, 4);
    o_SetRenderTarget(d, 0, s_surf); o_SetDepthStencilSurface(d, s_depth);
    o_SetVertexShaderConstantF(d, c.m, s_fit.clip, 4);
    if (SUCCEEDED(draw())) ++s_n.dup;
    o_SetVertexShaderConstantF(d, c.m, saved, 4);
    o_SetRenderTarget(d, 0, s_mapSurf); o_SetDepthStencilSurface(d, s_mapDepth);
    o_SetViewport(d, &vp); o_SetScissorRect(d, &sc);
    return hr;
}

HRESULT WINAPI hk_DrawPrimitive(void* d, DWORD t, UINT s, UINT n) { return Dup(d, [&] { return o_DrawPrimitive(d, t, s, n); }); }
HRESULT WINAPI hk_DrawIndexedPrimitive(void* d, DWORD t, INT b, UINT mn, UINT nv, UINT si, UINT pc) { return Dup(d, [&] { return o_DrawIndexedPrimitive(d, t, b, mn, nv, si, pc); }); }
HRESULT WINAPI hk_DrawPrimitiveUP(void* d, DWORD t, UINT n, const void* v, UINT st) { return Dup(d, [&] { return o_DrawPrimitiveUP(d, t, n, v, st); }); }
HRESULT WINAPI hk_DrawIndexedPrimitiveUP(void* d, DWORD t, UINT mn, UINT nv, UINT pc, const void* ix, DWORD f, const void* v, UINT st) { return Dup(d, [&] { return o_DrawIndexedPrimitiveUP(d, t, mn, nv, pc, ix, f, v, st); }); }

HRESULT WINAPI hk_SetRenderTarget(void* d, DWORD i, void* s) {
    if (i == 0) {
        bool isMap = false;
        SurfDesc sd{};
        if (s && SUCCEEDED(Slot<HRESULT(WINAPI*)(void*, SurfDesc*)>(s, 12)(s, &sd))) isMap = IsShadowMapDesc(sd.fmt, sd.usage, sd.w, sd.h);
        const PassStep st = s_pass.OnRenderTarget0(isMap);
        if (st == PassStep::begin) {
            s_renderTid = GetCurrentThreadId(); s_frameReady = false; s_noFit = false; ++s_n.passes;
            if (!s_tracedPass) { s_tracedPass = true; TraceStack("shadow pass begin"); }
        } else if (st == PassStep::end) {
            const bool drew = s_frameReady && !s_noFit;
            ReleasePassRefs();
            const HRESULT hr = o_SetRenderTarget(d, i, s);
            if (drew) {
                Slot<HRESULT(WINAPI*)(void*, DWORD, void*)>(d, 65)(d, 15, s_tex);
                BindSampler(d); BindConstants(d, s_fit.recv);
            } else BindConstants(d, nullptr);
            return hr;
        }
    }
    return o_SetRenderTarget(d, i, s);
}
HRESULT WINAPI hk_SetDepthStencilSurface(void* d, void* s) { return o_SetDepthStencilSurface(d, s); }
HRESULT WINAPI hk_Clear(void* d, DWORD n, const void* r, DWORD f, DWORD c, float z, DWORD st) { return o_Clear(d, n, r, f, c, z, st); }
HRESULT WINAPI hk_SetViewport(void* d, const Viewport* v) { return o_SetViewport(d, v); }
HRESULT WINAPI hk_SetScissorRect(void* d, const RECT* r) { return o_SetScissorRect(d, r); }
HRESULT WINAPI hk_SetTexture(void* d, DWORD st, void* t) { return o_SetTexture(d, st, t); }
HRESULT WINAPI hk_SetVertexShaderConstantF(void* d, UINT s, const float* v, UINT n) { return o_SetVertexShaderConstantF(d, s, v, n); }

HRESULT WINAPI hk_Reset(void* d, void* pp) {
    ReleasePassRefs(); ReleaseCascade();   // default-pool resources: the Reset fails while any is alive
    s_pass.in = false; s_frameReady = false;
    const HRESULT hr = o_Reset(d, pp);
    if (SUCCEEDED(hr)) BindConstants(d, nullptr);
    LOGI("cascade: Reset hr 0x%08lx, the target is recreated at the next pass", (unsigned long)hr);
    return hr;
}

HRESULT WINAPI hk_CreateVertexShader(void* d, const DWORD* code, void** out) {
    const HRESULT hr = o_CreateVertexShader(d, code, out);
    if (FAILED(hr) || !out || !*out) return hr;
    const size_t len = ShaderLength(reinterpret_cast<const uint32_t*>(code), 1u << 20);
    const auto t = ReadCtab(code, len);
    const CtabEntry* m = FindConst(t, "shadow_map_projection_matrix");
    const CtabEntry* z = FindConst(t, "linear_z_shadow_map_projection_matrix");
    Lock l;
    s_casters.erase(*out);   // an object address can be reused by a later shader
    if (m && z) { s_casters[*out] = Caster{ (int)m->index, (int)z->index }; ++s_n.casters; }
    return hr;
}

HRESULT WINAPI hk_CreatePixelShader(void* d, const DWORD* code, void** out) {
    size_t len = 0; bool ok = false;
    const uint64_t h = ShaderHash(code, 1u << 20, len, ok);
    const std::string* repl = nullptr;
    const auto stock = ok ? ReadCtab(code, len) : std::vector<CtabEntry>();
    const bool receiver = FindConst(stock, "shadow_map_texture_sampler") != nullptr;
    if (ok && receiver) {
        auto it = s_swap.find(h);
        if (it != s_swap.end()) {
            std::string why;
            if (CtabGate(stock, ReadCtab(it->second.data(), it->second.size()), why)) repl = &it->second;
            else { ++s_n.refused; LOGE("cascade: swap refused for %s: %s", Hex64(h).c_str(), why.c_str()); }
        } else LOGW("cascade: receiver %s has no replacement: stock", Hex64(h).c_str());
    }
    const HRESULT hr = o_CreatePixelShader(d, repl ? reinterpret_cast<const DWORD*>(repl->data()) : code, out);
    if (SUCCEEDED(hr) && out && *out) {
        Lock l;
        s_receivers.erase(*out); s_psHash.erase(*out); s_skipPs.erase(*out);
        if (receiver) { s_receivers[*out] = repl ? 1 : 2; s_psHash[*out] = h; }
        if (ok && s_skipHash == h) { s_skipPs[*out] = true; LOGI("cascade: draws of %s will be skipped", Hex64(h).c_str()); }
        if (repl) { ++s_n.swapped; LOGI("cascade: swapped %s (%zu -> %zu bytes)", Hex64(h).c_str(), len, repl->size()); }
    }
    return hr;
}

void CountLock(DWORD flags) {
    if (!s_pass.in) return;
    if (GetCurrentThreadId() != s_renderTid) { ++s_n.lockOtherThread; return; }
    ++(flags & 0x2000 ? s_n.lockDiscard : flags & 0x1000 ? s_n.lockNoOver : s_n.lockOther);
}
HRESULT WINAPI hk_VbLock(void* b, UINT o, UINT n, void** p, DWORD f) { CountLock(f); return o_VbLock(b, o, n, p, f); }
HRESULT WINAPI hk_IbLock(void* b, UINT o, UINT n, void** p, DWORD f) { CountLock(f); return o_IbLock(b, o, n, p, f); }
HRESULT WINAPI hk_CreateVertexBuffer(void* d, UINT n, DWORD u, DWORD f, DWORD p, void** o, void* h) {
    const HRESULT hr = o_CreateVertexBuffer(d, n, u, f, p, o, h);
    if (SUCCEEDED(hr) && o && *o && !o_VbLock) VtableHook(*(void***)*o, 11, (void*)hk_VbLock, (void**)&o_VbLock, "IDirect3DVertexBuffer9::Lock");
    return hr;
}
HRESULT WINAPI hk_CreateIndexBuffer(void* d, UINT n, DWORD u, DWORD f, DWORD p, void** o, void* h) {
    const HRESULT hr = o_CreateIndexBuffer(d, n, u, f, p, o, h);
    if (SUCCEEDED(hr) && o && *o && !o_IbLock) VtableHook(*(void***)*o, 11, (void*)hk_IbLock, (void**)&o_IbLock, "IDirect3DIndexBuffer9::Lock");
    return hr;
}

void LoadSwaps() {
    if (s_k.dir.empty()) { LOGW("cascade: dev.cascade_dir is empty: no receiver is swapped"); return; }
    std::wstring root = s_k.dir; if (root.back() != L'\\') root += L'\\';
    WIN32_FIND_DATAW fd; HANDLE h = FindFirstFileW((root + L"*.ps").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) { LOGW("cascade: no replacements in %ls", root.c_str()); return; }
    do {
        const std::string name = Narrow(fd.cFileName);
        std::string bytes;
        if (name.size() == 19 && ReadFileBytes(root + fd.cFileName, bytes)) s_swap[strtoull(name.substr(0, 16).c_str(), nullptr, 16)] = bytes;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    LOGI("cascade: %zu replacements from %ls", s_swap.size(), root.c_str());
}

} // namespace

void CascadeInit(bool tint, bool count, int split, int size, const std::wstring& dir, const std::string& skipPs) {
    InitializeCriticalSection(&s_cs);
    s_k.tint = tint; s_k.count = count; s_k.size = size; s_k.dir = dir;
    s_skipHash = skipPs.empty() ? 0 : strtoull(skipPs.c_str(), nullptr, 16);
    if (split > 0) s_k.split = split;
    LOGI("cascade: prototype on: split %d m, size %d (0 = the engine map's), tint %d, count %d", s_k.split, s_k.size, s_k.tint, s_k.count);
    LoadSwaps();
}

void CascadeInstall(void* dev) {
    void** vt = *(void***)dev;
    struct H { int slot; void* hk; void** orig; const char* name; } hs[] = {
        { 16, (void*)hk_Reset, (void**)&o_Reset, "Reset" }, { 26, (void*)hk_CreateVertexBuffer, (void**)&o_CreateVertexBuffer, "CreateVertexBuffer" },
        { 27, (void*)hk_CreateIndexBuffer, (void**)&o_CreateIndexBuffer, "CreateIndexBuffer" }, { 37, (void*)hk_SetRenderTarget, (void**)&o_SetRenderTarget, "SetRenderTarget" },
        { 39, (void*)hk_SetDepthStencilSurface, (void**)&o_SetDepthStencilSurface, "SetDepthStencilSurface" }, { 43, (void*)hk_Clear, (void**)&o_Clear, "Clear" },
        { 47, (void*)hk_SetViewport, (void**)&o_SetViewport, "SetViewport" }, { 65, (void*)hk_SetTexture, (void**)&o_SetTexture, "SetTexture" },
        { 75, (void*)hk_SetScissorRect, (void**)&o_SetScissorRect, "SetScissorRect" }, { 81, (void*)hk_DrawPrimitive, (void**)&o_DrawPrimitive, "DrawPrimitive" },
        { 82, (void*)hk_DrawIndexedPrimitive, (void**)&o_DrawIndexedPrimitive, "DrawIndexedPrimitive" }, { 83, (void*)hk_DrawPrimitiveUP, (void**)&o_DrawPrimitiveUP, "DrawPrimitiveUP" },
        { 84, (void*)hk_DrawIndexedPrimitiveUP, (void**)&o_DrawIndexedPrimitiveUP, "DrawIndexedPrimitiveUP" }, { 91, (void*)hk_CreateVertexShader, (void**)&o_CreateVertexShader, "CreateVertexShader" },
        { 94, (void*)hk_SetVertexShaderConstantF, (void**)&o_SetVertexShaderConstantF, "SetVertexShaderConstantF" }, { 106, (void*)hk_CreatePixelShader, (void**)&o_CreatePixelShader, "CreatePixelShader" },
    };
    int ok = 0;
    for (const H& h : hs) {
        char n[64]; snprintf(n, sizeof n, "IDirect3DDevice9::%s (cascade)", h.name);
        if (vt[h.slot] == h.hk) { ++ok; continue; }
        if (VtableHook(vt, h.slot, h.hk, *h.orig ? nullptr : h.orig, n)) ++ok;
    }
    BindConstants(dev, nullptr);
    LOGI("cascade: %d of %d device slots hooked", ok, (int)(sizeof hs / sizeof hs[0]));
}

void CascadePresent() {
    if (++s_n.frames % 300) return;
    LOGI("cascade: frames %lld passes %lld casters seen %lld dup %lld unknown %lld nofit %lld (%s) locks in pass discard %lld nooverwrite %lld other %lld otherthread %lld "
         "receivers created swapped %lld refused %lld, draws swapped %lld stock %lld; vs casters %lld; fit r %.3f texel %.5f c (%.3f, %.3f) t %.3f",
         s_n.frames, s_n.passes, s_n.seen, s_n.dup, s_n.unknown, s_n.nofit, s_fitWhy.c_str(), s_n.lockDiscard, s_n.lockNoOver, s_n.lockOther, s_n.lockOtherThread,
         s_n.swapped, s_n.refused, s_n.swappedDraws, s_n.stockDraws, s_n.casters, s_fit.radius, s_fit.texelM, s_fit.cx, s_fit.cy, s_fit.tSlice);
    if (s_n.frames % 3000 == 0) {
        Lock l; std::string t;
        for (const auto& kv : s_stockDraws) t += " " + Hex64(kv.first) + "=" + std::to_string(kv.second);
        LOGI("cascade: stock receiver draws:%s; skipped draws %lld", t.c_str(), s_skipped);
    }
}

} // namespace wsp
