// ui_render_d3d9.cpp - see ui_render_d3d9.h (ported from empire-remastered rml_mod/src/rml_render_d3d9.cpp, J30)
#include "ui_render_d3d9.h"
#include <RmlUi/Core.h>
#include <RmlUi/Core/DecorationTypes.h>
#include <RmlUi/Core/Dictionary.h>
#include <RmlUi/Core/FileInterface.h>
#include <vector>
#include <cstring>
#include <cmath>
#include <algorithm>
#include <cstdio>
#include <cctype>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_NO_STDIO
#define STBI_ONLY_PNG
#define STBI_ONLY_TGA
#define STBI_ONLY_JPEG
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#pragma GCC diagnostic ignored "-Wsign-compare"
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#pragma GCC diagnostic ignored "-Wimplicit-fallthrough"
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"
#pragma GCC diagnostic ignored "-Wtype-limits"
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wdouble-promotion"
#include <stb_image.h>
#pragma GCC diagnostic pop

// ================================================================ shaders (HLSL, SM3) ==============
static const char* kShaderSource = R"HLSL(
// ---------- vertex: UI geometry ----------
float4 R0 : register(c0);   // rows of (projection * transform)
float4 R1 : register(c1);
float4 R2 : register(c2);
float4 R3 : register(c3);
float4 Translate : register(c4);
float4 HalfPixel : register(c5);  // (1/w, 1/h): D3D9 pixel-centre offset

struct VSMainIn  { float2 pos : POSITION; float4 col : COLOR0; float2 uv : TEXCOORD0; };
struct VSMainOut { float4 pos : POSITION; float4 col : COLOR0; float2 uv : TEXCOORD0; };
VSMainOut VSMain(VSMainIn i) {
    VSMainOut o;
    float4 p = float4(i.pos + Translate.xy, 0, 1);
    o.pos = float4(dot(R0, p), dot(R1, p), dot(R2, p), dot(R3, p));
    o.pos.x -= HalfPixel.x * o.pos.w;
    o.pos.y += HalfPixel.y * o.pos.w;
    o.pos.z = 0.5 * o.pos.w;
    o.col = i.col; o.uv = i.uv;
    return o;
}

// ---------- vertex: full-screen post-process quad (positions already in clip space) ----------
struct VSQuadIn  { float2 pos : POSITION; float2 uv : TEXCOORD0; };
struct VSQuadOut { float4 pos : POSITION; float2 uv : TEXCOORD0; };
VSQuadOut VSQuad(VSQuadIn i) {
    VSQuadOut o;
    o.pos = float4(i.pos.x - HalfPixel.x, i.pos.y + HalfPixel.y, 0.5, 1);
    o.uv = i.uv;
    return o;
}

sampler2D S0 : register(s0);
sampler2D S1 : register(s1);
float4 C[24] : register(c0);

float4 PSColor(float4 col : COLOR0) : COLOR { return col; }
float4 PSTexture(float4 col : COLOR0, float2 uv : TEXCOORD0) : COLOR { return col * tex2D(S0, uv); }
float4 PSPassthrough(float2 uv : TEXCOORD0) : COLOR { return tex2D(S0, uv) * C[0].x; }
float4 PSColorMatrix(float2 uv : TEXCOORD0) : COLOR {
    float4 t = tex2D(S0, uv);
    return float4(dot(C[0], t), dot(C[1], t), dot(C[2], t), t.a);
}
float4 PSBlendMask(float2 uv : TEXCOORD0) : COLOR { return tex2D(S0, uv) * tex2D(S1, uv).a; }

// C[0] = weights 0..3, C[1].xy = texel offset, C[2] = texcoord min.xy / max.zw
float4 PSBlur(float2 uv : TEXCOORD0) : COLOR {
    float w[4] = { C[0].x, C[0].y, C[0].z, C[0].w };
    float4 c = 0;
    [unroll] for (int i = 0; i < 7; i++) {
        float2 t = uv - (float)(i - 3) * C[1].xy;
        float2 r = step(C[2].xy, t) * step(t, C[2].zw);
        c += tex2D(S0, t) * r.x * r.y * w[abs(i - 3)];
    }
    return c;
}

// C[0] = premultiplied colour, C[1] = texcoord min.xy / max.zw
float4 PSDropShadow(float2 uv : TEXCOORD0) : COLOR {
    float2 r = step(C[1].xy, uv) * step(uv, C[1].zw);
    return tex2D(S0, uv).a * r.x * r.y * C[0];
}

// C[0].x = func, C[0].y = number of stops, C[1] = p.xy, v.zw, C[2..17] = stop colours, C[18..21] = stop positions
float StopPos(int i) {
    float4 v = C[18 + i / 4];
    int k = i - (i / 4) * 4;
    return k == 0 ? v.x : (k == 1 ? v.y : (k == 2 ? v.z : v.w));
}
float4 PSGradient(float4 col : COLOR0, float2 uv : TEXCOORD0) : COLOR {
    int func = (int)(C[0].x + 0.5);
    int n = (int)(C[0].y + 0.5);
    float2 p = C[1].xy, v = C[1].zw;
    float t = 0;
    if (func == 0 || func == 3) { float2 V = uv - p; t = dot(v, V) / dot(v, v); }
    else if (func == 1 || func == 4) { float2 V = uv - p; t = length(v * V); }
    else { float2 V = uv - p; float2 Rv = float2(v.x * V.x + v.y * V.y, -v.y * V.x + v.x * V.y); t = 0.5 + atan2(-Rv.x, Rv.y) / 6.28318531; }
    if (func >= 3) {
        float t0 = StopPos(0), t1 = StopPos(n - 1), len = max(t1 - t0, 1e-5);
        float x = t - t0; t = t0 + (x - floor(x / len) * len);
    }
    float4 c = C[2];
    [unroll] for (int i = 1; i < 16; i++) {
        if (i < n) c = lerp(c, C[2 + i], smoothstep(StopPos(i - 1), StopPos(i), t));
    }
    return col * c;
}
)HLSL";

static int s_trace = 40;   // log the first N advanced-rendering calls
static const double kSlowFrameMs = 20.0;   // a frame spending more than this inside the overlay gets a profile line
// Milliseconds since a base that moves every frame (BeginFrame), taken as an integer tick difference first: D3D9 drops the render
// thread's x87 FPU to 24-bit precision (no D3DCREATE_FPU_PRESERVE), and an absolute QPC time in ms rounded to 8-32 ms steps (empire-remastered's
// absolute form logged "slow frame 32.0 ms" for every frame in the J30 smoke, 2026-11-02; the same trap as J44's perf).
static LONGLONG s_msBase = 0;
double RenderInterface_D3D9::NowMs() {
    static LARGE_INTEGER f = [] { LARGE_INTEGER x; QueryPerformanceFrequency(&x); return x; }();
    LARGE_INTEGER c; QueryPerformanceCounter(&c);
    if (!s_msBase) s_msBase = c.QuadPart;
    return (double)((c.QuadPart - s_msBase) * 1000000 / f.QuadPart) / 1000.0;
}
#define TRACE(...) do { if (s_trace > 0) { --s_trace; LOGI(__VA_ARGS__); } } while (0)

namespace {
struct Vtx { float x, y; D3DCOLOR c; float u, v; };
struct QuadVtx { float x, y, u, v; };

inline D3DCOLOR ToD3D(Rml::ColourbPremultiplied c) { return D3DCOLOR_ARGB(c.alpha, c.red, c.green, c.blue); }

enum class FilterType { Invalid, Passthrough, Blur, DropShadow, ColorMatrix, MaskImage };
struct CompiledFilter {
    FilterType type = FilterType::Invalid;
    float blend = 1.f, sigma = 0.f;
    Rml::Vector2f offset;
    Rml::ColourbPremultiplied color;
    Rml::Matrix4f matrix;
};
enum class GradientFunc { Linear, Radial, Conic, RepeatingLinear, RepeatingRadial, RepeatingConic };
struct CompiledShader {
    bool valid = false;
    GradientFunc func = GradientFunc::Linear;
    Rml::Vector2f p, v;
    std::vector<float> positions;
    std::vector<Rml::Colourf> colors;
};
Rml::Colourf ToF(Rml::ColourbPremultiplied c) { Rml::Colourf r; for (int i = 0; i < 4; i++) r[i] = c[i] / 255.f; return r; }
// element(row, col) of a column-major Rml::Matrix4f
inline float El(const Rml::Matrix4f& m, int r, int c) { return m.data()[c * 4 + r]; }

// D3DCompile from d3dcompiler_47 (loaded at run time; no import): the blob is used through its vtable only
// A C-style vtable, not a C++ class with pure virtuals: GCC proves a TU-local abstract class can have no object and turned every call
// through it into "call 0" (the J30 first start-up crash, 2026-11-02: d3d9 CompileShaders+0xba). ID3DBlob = IUnknown + GetBufferPointer, GetBufferSize.
struct BlobVtbl { void* qi; void* addRef; ULONG(WINAPI* Release)(void*); void*(WINAPI* GetBufferPointer)(void*); SIZE_T(WINAPI* GetBufferSize)(void*); };
struct Blob { const BlobVtbl* v; void* Ptr() { return v->GetBufferPointer(this); } void Release() { v->Release(this); } };
using PFN_D3DCompile = HRESULT(WINAPI*)(LPCVOID, SIZE_T, LPCSTR, const void*, void*, LPCSTR, LPCSTR, UINT, UINT, Blob**, Blob**);
} // namespace

RenderInterface_D3D9::RenderInterface_D3D9(IDirect3DDevice9* dev) : m_dev(dev) {}

RenderInterface_D3D9::~RenderInterface_D3D9() {
    ReleaseDeviceResources();
    auto rel = [](auto*& p) { if (p) { p->Release(); p = nullptr; } };
    rel(m_declMain); rel(m_declQuad); rel(m_vsMain); rel(m_vsQuad);
    rel(m_psColor); rel(m_psTexture); rel(m_psGradient); rel(m_psPassthrough); rel(m_psColorMatrix); rel(m_psBlendMask); rel(m_psBlur); rel(m_psDropShadow);
}

// ================================================================ setup =============================
bool RenderInterface_D3D9::CompileShaders() {
    m_shadersTried = true;
    HMODULE dll = LoadLibraryW(L"d3dcompiler_47.dll");   // a system DLL since Windows 8.1; _43 from the DirectX runtime
    if (!dll) dll = LoadLibraryW(L"d3dcompiler_43.dll");
    auto compile = dll ? (PFN_D3DCompile)(void*)GetProcAddress(dll, "D3DCompile") : nullptr;
    if (!compile) { LOGE("rml: no d3dcompiler_47/43.dll — advanced rendering unavailable"); return false; }

    auto build = [&](const char* entry, const char* target, Blob** out) -> bool {
        Blob* errors = nullptr;
        HRESULT hr = compile(kShaderSource, strlen(kShaderSource), "rml_d3d9", nullptr, nullptr, entry, target, (1 << 15) /* D3DCOMPILE_OPTIMIZATION_LEVEL3 */, 0, out, &errors);
        if (FAILED(hr)) { LOGE("rml: shader %s (%s) failed: %s", entry, target, errors ? (const char*)errors->Ptr() : "?"); if (errors) errors->Release(); return false; }
        if (errors) errors->Release();
        return true;
    };
    auto vs = [&](const char* e, IDirect3DVertexShader9** o) { Blob* b = nullptr; if (!build(e, "vs_3_0", &b)) return false; bool ok = SUCCEEDED(m_dev->CreateVertexShader((const DWORD*)b->Ptr(), o)); b->Release(); return ok; };
    auto ps = [&](const char* e, IDirect3DPixelShader9** o) { Blob* b = nullptr; if (!build(e, "ps_3_0", &b)) return false; bool ok = SUCCEEDED(m_dev->CreatePixelShader((const DWORD*)b->Ptr(), o)); b->Release(); return ok; };

    bool ok = vs("VSMain", &m_vsMain) && vs("VSQuad", &m_vsQuad) && ps("PSColor", &m_psColor) && ps("PSTexture", &m_psTexture)
           && ps("PSGradient", &m_psGradient) && ps("PSPassthrough", &m_psPassthrough) && ps("PSColorMatrix", &m_psColorMatrix)
           && ps("PSBlendMask", &m_psBlendMask) && ps("PSBlur", &m_psBlur) && ps("PSDropShadow", &m_psDropShadow);

    const D3DVERTEXELEMENT9 mainDecl[] = {
        { 0, 0, D3DDECLTYPE_FLOAT2, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_POSITION, 0 },
        { 0, 8, D3DDECLTYPE_D3DCOLOR, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_COLOR, 0 },
        { 0, 12, D3DDECLTYPE_FLOAT2, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_TEXCOORD, 0 }, D3DDECL_END() };
    const D3DVERTEXELEMENT9 quadDecl[] = {
        { 0, 0, D3DDECLTYPE_FLOAT2, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_POSITION, 0 },
        { 0, 8, D3DDECLTYPE_FLOAT2, D3DDECLMETHOD_DEFAULT, D3DDECLUSAGE_TEXCOORD, 0 }, D3DDECL_END() };
    ok = ok && SUCCEEDED(m_dev->CreateVertexDeclaration(mainDecl, &m_declMain)) && SUCCEEDED(m_dev->CreateVertexDeclaration(quadDecl, &m_declQuad));
    LOGI("rml: SM3 shaders %s", ok ? "compiled" : "FAILED — UI will not render");
    return ok;
}

bool RenderInterface_D3D9::CreateRT(RT& rt) {
    if (rt.tex) return true;
    const double t0 = NowMs(); ++m_prof.nRt;
    struct Acc { double& d; double t; ~Acc() { d += RenderInterface_D3D9::NowMs() - t; } } acc{ m_prof.rt, t0 };
    if (FAILED(m_dev->CreateTexture(m_targetW, m_targetH, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &rt.tex, nullptr))) {
        LOGE("rml: CreateTexture(render target %dx%d) failed", m_targetW, m_targetH); return false;
    }
    rt.tex->GetSurfaceLevel(0, &rt.surf);
    return true;
}
void RenderInterface_D3D9::FreeRT(RT& rt) {
    if (rt.surf) { rt.surf->Release(); rt.surf = nullptr; }
    if (rt.tex) { rt.tex->Release(); rt.tex = nullptr; }
}

void RenderInterface_D3D9::ReleaseDeviceResources() {
    for (RT& rt : m_layers) FreeRT(rt);
    m_layers.clear();
    for (RT& rt : m_post) FreeRT(rt);
    FreeRT(m_blendMask);
    if (m_depthStencil) { m_depthStencil->Release(); m_depthStencil = nullptr; }
    m_targetW = m_targetH = 0;
}

bool RenderInterface_D3D9::EnsureTargets() {
    if (m_targetW != m_w || m_targetH != m_h) { ReleaseDeviceResources(); m_targetW = m_w; m_targetH = m_h; }
    if (!m_depthStencil && FAILED(m_dev->CreateDepthStencilSurface(m_w, m_h, D3DFMT_D24S8, D3DMULTISAMPLE_NONE, 0, FALSE, &m_depthStencil, nullptr))) {
        LOGE("rml: CreateDepthStencilSurface %dx%d failed", m_w, m_h); return false;
    }
    return true;
}

IDirect3DSurface9* RenderInterface_D3D9::LayerSurface(Rml::LayerHandle layer) {
    size_t i = (size_t)layer;
    if (i == 0) return m_backBuffer;
    return i < m_layers.size() ? m_layers[i].surf : m_backBuffer;
}

void RenderInterface_D3D9::BindTarget(IDirect3DSurface9* s) {
    m_dev->SetRenderTarget(0, s);     // resets the viewport to the full surface
}

// ================================================================ frame =============================
void RenderInterface_D3D9::BeginFrame() {
    m_stats.draws = 0; m_stats.layersPeak = 0; m_stats.filters = 0;
    { LARGE_INTEGER c; QueryPerformanceCounter(&c); s_msBase = c.QuadPart; }   // small values: exact even at 24-bit precision
    m_prof = Prof(); m_frameStart = NowMs();
    if (!m_shadersTried) m_shadersOk = CompileShaders();
    if (!m_shadersOk) return;
    EnsureTargets();

    m_dev->CreateStateBlock(D3DSBT_ALL, &m_sb);
    m_dev->GetRenderTarget(0, &m_savedRT);
    m_dev->GetDepthStencilSurface(&m_savedDS);           // may legitimately be null
    m_dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &m_backBuffer);

    m_dev->SetRenderTarget(0, m_backBuffer);
    for (DWORD i = 1; i < 4; ++i) m_dev->SetRenderTarget(i, nullptr);
    m_dev->SetDepthStencilSurface(m_depthStencil);
    m_dev->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE);
    m_dev->Clear(0, nullptr, D3DCLEAR_STENCIL, 0, 1.f, 0);

    m_dev->SetRenderState(D3DRS_ZENABLE, FALSE);
    m_dev->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    m_dev->SetRenderState(D3DRS_LIGHTING, FALSE);
    m_dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    m_dev->SetRenderState(D3DRS_FOGENABLE, FALSE);
    m_dev->SetRenderState(D3DRS_CLIPPING, TRUE);
    m_dev->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
    m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    m_dev->SetRenderState(D3DRS_SEPARATEALPHABLENDENABLE, FALSE);
    m_dev->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_ONE);             // premultiplied alpha
    m_dev->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    m_dev->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
    m_dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
    m_dev->SetRenderState(D3DRS_SRGBWRITEENABLE, FALSE);
    m_dev->SetRenderState(D3DRS_FILLMODE, D3DFILL_SOLID);
    m_dev->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    m_dev->SetRenderState(D3DRS_STENCILMASK, 0xFFFFFFFF);
    m_dev->SetRenderState(D3DRS_STENCILWRITEMASK, 0xFFFFFFFF);
    m_dev->SetRenderState(D3DRS_STENCILFAIL, D3DSTENCILOP_KEEP);
    m_dev->SetRenderState(D3DRS_STENCILZFAIL, D3DSTENCILOP_KEEP);
    m_dev->SetRenderState(D3DRS_STENCILPASS, D3DSTENCILOP_KEEP);
    m_dev->SetRenderState(D3DRS_STENCILFUNC, D3DCMP_ALWAYS);
    m_dev->SetRenderState(D3DRS_TWOSIDEDSTENCILMODE, FALSE);
    for (DWORD s = 0; s < 2; ++s) {
        m_dev->SetSamplerState(s, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
        m_dev->SetSamplerState(s, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        m_dev->SetSamplerState(s, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        m_dev->SetSamplerState(s, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        m_dev->SetSamplerState(s, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        m_dev->SetSamplerState(s, D3DSAMP_SRGBTEXTURE, FALSE);
        m_dev->SetSamplerState(s, D3DSAMP_MAXANISOTROPY, 1);
    }
    for (DWORD s = 2; s < 8; ++s) m_dev->SetTexture(s, nullptr);
    m_addr0 = D3DTADDRESS_CLAMP;                          // matches the sampler loop above
    m_mip0 = false;
    if (!m_capsChecked) {
        m_capsChecked = true;
        D3DCAPS9 caps{};
        if (SUCCEEDED(m_dev->GetDeviceCaps(&caps))) m_wrapOk = (caps.TextureCaps & D3DPTEXTURECAPS_POW2) == 0;
        LOGI("rml: texture addressing %s (TextureCaps 0x%08lx)", m_wrapOk ? "WRAP for geometry, CLAMP for post-process" : "CLAMP only (NPOT textures need CLAMP on this device)", (unsigned long)caps.TextureCaps);
    }

    D3DVIEWPORT9 vp{ 0, 0, (DWORD)m_w, (DWORD)m_h, 0.f, 1.f };
    m_dev->SetViewport(&vp);

    m_projection = Rml::Matrix4f::ProjectOrtho(0, (float)m_w, (float)m_h, 0, -10000, 10000);
    SetTransform(nullptr);
    m_scissor = Rml::Rectanglei::MakeInvalid(); m_scissorOn = false;
    m_clipMaskOn = false; m_stencilRef = 1;
    m_layerCount = 1;                                     // layer 0 = back buffer
}

void RenderInterface_D3D9::EndFrame() {
    if (!m_shadersOk || !m_sb) return;
    m_dev->SetRenderTarget(0, m_savedRT);
    m_dev->SetDepthStencilSurface(m_savedDS);
    m_sb->Apply(); m_sb->Release(); m_sb = nullptr;
    if (m_savedRT) { m_savedRT->Release(); m_savedRT = nullptr; }
    if (m_savedDS) { m_savedDS->Release(); m_savedDS = nullptr; }
    if (m_backBuffer) { m_backBuffer->Release(); m_backBuffer = nullptr; }
    m_prof.frame = NowMs() - m_frameStart;
    if (m_prof.frame > kSlowFrameMs)
        LOGI("rml: slow frame %.1f ms: decode %u/%.1f ms, upload %u/%.1f, layer-save %u/%.1f, rt-create %u/%.1f, geometry %u/%.1f, draws %u, layers %u",
             m_prof.frame, m_prof.nDecode, m_prof.decode, m_prof.nUpload, m_prof.upload, m_prof.nSave, m_prof.save, m_prof.nRt, m_prof.rt,
             m_prof.nGeom, m_prof.geom, m_stats.draws, m_stats.layersPeak);
}

// ================================================================ geometry ==========================
Rml::CompiledGeometryHandle RenderInterface_D3D9::CompileGeometry(Rml::Span<const Rml::Vertex> vertices, Rml::Span<const int> indices) {
    const double t0 = NowMs();
    auto* g = new Geometry();
    g->numVertices = (UINT)vertices.size(); g->numIndices = (UINT)indices.size();
    if (FAILED(m_dev->CreateVertexBuffer(g->numVertices * sizeof(Vtx), D3DUSAGE_WRITEONLY, 0, D3DPOOL_MANAGED, &g->vb, nullptr)) ||
        FAILED(m_dev->CreateIndexBuffer(g->numIndices * sizeof(DWORD), D3DUSAGE_WRITEONLY, D3DFMT_INDEX32, D3DPOOL_MANAGED, &g->ib, nullptr))) {
        LOGE("rml: buffer creation failed (%u verts, %u idx)", g->numVertices, g->numIndices);
        ReleaseGeometry((Rml::CompiledGeometryHandle)g); return 0;
    }
    void* p = nullptr;
    if (SUCCEEDED(g->vb->Lock(0, 0, &p, 0))) {
        Vtx* v = (Vtx*)p;
        for (size_t i = 0; i < vertices.size(); ++i) {
            const Rml::Vertex& s = vertices[i];
            v[i] = { s.position.x, s.position.y, ToD3D(s.colour), s.tex_coord.x, s.tex_coord.y };
        }
        g->vb->Unlock();
    }
    if (SUCCEEDED(g->ib->Lock(0, 0, &p, 0))) { memcpy(p, indices.data(), indices.size() * sizeof(int)); g->ib->Unlock(); }
    ++m_stats.geometries; ++m_prof.nGeom; m_prof.geom += NowMs() - t0;
    return (Rml::CompiledGeometryHandle)g;
}

void RenderInterface_D3D9::SubmitGeometryTransform(Rml::Vector2f translation) {
    float rows[24];
    for (int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) rows[r * 4 + c] = El(m_transform, r, c);
    rows[16] = translation.x; rows[17] = translation.y; rows[18] = 0; rows[19] = 0;
    rows[20] = 1.f / (float)m_w; rows[21] = 1.f / (float)m_h; rows[22] = 0; rows[23] = 0;
    m_dev->SetVertexShaderConstantF(0, rows, 6);
    m_dev->SetVertexDeclaration(m_declMain);
    m_dev->SetVertexShader(m_vsMain);
}

void RenderInterface_D3D9::RenderGeometry(Rml::CompiledGeometryHandle geometry, Rml::Vector2f translation, Rml::TextureHandle texture) {
    auto* g = (Geometry*)geometry;
    if (!m_shadersOk || !g || !g->vb) return;
    SubmitGeometryTransform(translation);
    if (texture) {
        auto* tex = (IDirect3DTexture9*)texture;
        SetAddress0(m_wrapOk && !m_clampTex.count(tex) ? D3DTADDRESS_WRAP : D3DTADDRESS_CLAMP);
        const bool mip = m_mipTex.count(tex) != 0;
        if (mip != m_mip0) { m_dev->SetSamplerState(0, D3DSAMP_MIPFILTER, mip ? D3DTEXF_LINEAR : D3DTEXF_NONE); m_mip0 = mip; }
        m_dev->SetTexture(0, tex); m_dev->SetPixelShader(m_psTexture);
    }
    else { m_dev->SetTexture(0, nullptr); m_dev->SetPixelShader(m_psColor); }
    m_dev->SetStreamSource(0, g->vb, 0, sizeof(Vtx));
    m_dev->SetIndices(g->ib);
    m_dev->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, g->numVertices, 0, g->numIndices / 3);
    ++m_stats.draws;
}

void RenderInterface_D3D9::ReleaseGeometry(Rml::CompiledGeometryHandle geometry) {
    auto* g = (Geometry*)geometry;
    if (!g) return;
    if (g->vb) g->vb->Release();
    if (g->ib) g->ib->Release();
    delete g; --m_stats.geometries;
}

// ================================================================ textures ==========================
Rml::TextureHandle RenderInterface_D3D9::CreateTextureRGBA(const Rml::byte* rgba, int w, int h, bool premultiply, bool mips) {
    const double t0 = NowMs(); ++m_prof.nUpload;
    struct Acc { double& d; double t; ~Acc() { d += RenderInterface_D3D9::NowMs() - t; } } acc{ m_prof.upload, t0 };
    UINT levels = 1;
    if (mips) { int m = std::max(w, h); while (m > 1) { m >>= 1; ++levels; } }
    IDirect3DTexture9* tex = nullptr;
    if (FAILED(m_dev->CreateTexture(w, h, levels, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr))) { LOGE("rml: CreateTexture %dx%d (%u levels) failed", w, h, levels); return 0; }
    // level 0 in premultiplied BGRA, then each level a 2x2 box of the one above (premultiplied, so no dark fringes)
    std::vector<DWORD> cur((size_t)w * h);
    for (int y = 0; y < h; ++y) {
        const Rml::byte* s = rgba + (size_t)y * w * 4;
        for (int x = 0; x < w; ++x, s += 4) {
            unsigned r = s[0], g = s[1], b = s[2], a = s[3];
            if (premultiply) { r = (r * a + 127) / 255; g = (g * a + 127) / 255; b = (b * a + 127) / 255; }
            cur[(size_t)y * w + x] = D3DCOLOR_ARGB(a, r, g, b);
        }
    }
    int lw = w, lh = h;
    for (UINT lv = 0; lv < levels; ++lv) {
        D3DLOCKED_RECT lr;
        if (FAILED(tex->LockRect(lv, &lr, nullptr, 0))) { tex->Release(); return 0; }
        for (int y = 0; y < lh; ++y) memcpy((BYTE*)lr.pBits + (size_t)y * lr.Pitch, cur.data() + (size_t)y * lw, (size_t)lw * 4);
        tex->UnlockRect(lv);
        if (lv + 1 == levels) break;
        const int nw = std::max(1, lw / 2), nh = std::max(1, lh / 2);
        std::vector<DWORD> next((size_t)nw * nh);
        for (int y = 0; y < nh; ++y) for (int x = 0; x < nw; ++x) {
            const int x0 = std::min(2 * x, lw - 1), x1 = std::min(2 * x + 1, lw - 1), y0 = std::min(2 * y, lh - 1), y1 = std::min(2 * y + 1, lh - 1);
            const DWORD p[4] = { cur[(size_t)y0 * lw + x0], cur[(size_t)y0 * lw + x1], cur[(size_t)y1 * lw + x0], cur[(size_t)y1 * lw + x1] };
            DWORD o = 0;
            for (int sh = 0; sh < 32; sh += 8) { unsigned s = 2; for (DWORD q : p) s += (q >> sh) & 0xFF; o |= (DWORD)((s / 4) & 0xFF) << sh; }
            next[(size_t)y * nw + x] = o;
        }
        cur.swap(next); lw = nw; lh = nh;
    }
    if (levels > 1) m_mipTex.insert(tex);
    ++m_stats.textures;
    return (Rml::TextureHandle)tex;
}

Rml::TextureHandle RenderInterface_D3D9::LoadTexture(Rml::Vector2i& texture_dimensions, const Rml::String& source) {
    const double t0 = NowMs(); ++m_prof.nDecode;
    Rml::FileInterface* fi = Rml::GetFileInterface();
    Rml::FileHandle fh = fi->Open(source);
    if (!fh) { LOGE("rml: cannot open texture %s", source.c_str()); return 0; }
    size_t len = fi->Length(fh);
    std::vector<unsigned char> buf(len);
    fi->Read(buf.data(), len, fh);
    fi->Close(fh);
    int w = 0, h = 0, n = 0;
    unsigned char* px = stbi_load_from_memory(buf.data(), (int)len, &w, &h, &n, 4);
    if (!px) { LOGE("rml: decode failed for %s: %s", source.c_str(), stbi_failure_reason()); return 0; }
    m_prof.decode += NowMs() - t0;
    Rml::TextureHandle t = CreateTextureRGBA(px, w, h, true, true);   // art: a mip chain for clean downscaling (D19 2.5x masters)
    stbi_image_free(px);
    texture_dimensions = { w, h };
    return t;
}

Rml::TextureHandle RenderInterface_D3D9::GenerateTexture(Rml::Span<const Rml::byte> source, Rml::Vector2i dims) {
    return CreateTextureRGBA(source.data(), dims.x, dims.y, false);
}

void RenderInterface_D3D9::ReleaseTexture(Rml::TextureHandle texture) {
    if (texture) { m_clampTex.erase((IDirect3DTexture9*)texture); m_mipTex.erase((IDirect3DTexture9*)texture); ((IDirect3DTexture9*)texture)->Release(); --m_stats.textures; }
}

void RenderInterface_D3D9::SetAddress0(DWORD mode) {
    if (mode == m_addr0) return;
    m_dev->SetSamplerState(0, D3DSAMP_ADDRESSU, mode);
    m_dev->SetSamplerState(0, D3DSAMP_ADDRESSV, mode);
    m_addr0 = mode;
}

// ================================================================ scissor / transform ===============
// Same contract as RmlUi's GL3 backend: SetScissorRegion() alone switches the scissor on (an invalid rectangle switches it off);
// EnableScissorRegion(true) is always followed by SetScissorRegion() and is ignored.
void RenderInterface_D3D9::EnableScissorRegion(bool enable) {
    if (!enable) SetScissorRegion(Rml::Rectanglei::MakeInvalid());
}
void RenderInterface_D3D9::SetScissorRegion(Rml::Rectanglei region) {
    m_scissor = region;
    m_scissorOn = region.Valid();
    if (m_scissorOn) {
        RECT r{ Rml::Math::Clamp(region.Left(), 0, m_w), Rml::Math::Clamp(region.Top(), 0, m_h),
                Rml::Math::Clamp(region.Right(), 0, m_w), Rml::Math::Clamp(region.Bottom(), 0, m_h) };
        m_dev->SetScissorRect(&r);
    }
    m_dev->SetRenderState(D3DRS_SCISSORTESTENABLE, m_scissorOn ? TRUE : FALSE);
}
void RenderInterface_D3D9::ApplyScissor(Rml::Rectanglei region) {
    RECT r{ std::max(region.Left(), 0), std::max(region.Top(), 0), std::max(region.Right(), 0), std::max(region.Bottom(), 0) };
    m_dev->SetScissorRect(&r);
    m_dev->SetRenderState(D3DRS_SCISSORTESTENABLE, TRUE);
}
void RenderInterface_D3D9::RestoreScissor() {
    SetScissorRegion(m_scissor);
}
Rml::Rectanglei RenderInterface_D3D9::FilterWindow() const {
    const Rml::Rectanglei full = Rml::Rectanglei::FromSize({ m_w, m_h });
    return (m_scissorOn && m_scissor.Valid()) ? m_scissor.IntersectIfValid(full) : full;
}
void RenderInterface_D3D9::SetTransform(const Rml::Matrix4f* transform) {
    m_transform = transform ? (m_projection * (*transform)) : m_projection;
}

// ================================================================ clip mask (stencil) ===============
void RenderInterface_D3D9::EnableClipMask(bool enable) {
    m_clipMaskOn = enable;
    m_dev->SetRenderState(D3DRS_STENCILENABLE, enable ? TRUE : FALSE);
}

void RenderInterface_D3D9::RenderToClipMask(Rml::ClipMaskOperation op, Rml::CompiledGeometryHandle geometry, Rml::Vector2f translation) {
    TRACE("rtt: ClipMask op=%d at %.1f,%.1f", (int)op, translation.x, translation.y);
    DWORD write = 1, test = 1;
    switch (op) {
    case Rml::ClipMaskOperation::Set:
        m_dev->Clear(0, nullptr, D3DCLEAR_STENCIL, 0, 1.f, 0);
        m_dev->SetRenderState(D3DRS_STENCILPASS, D3DSTENCILOP_REPLACE);
        break;
    case Rml::ClipMaskOperation::SetInverse:
        m_dev->Clear(0, nullptr, D3DCLEAR_STENCIL, 0, 1.f, 1);
        m_dev->SetRenderState(D3DRS_STENCILPASS, D3DSTENCILOP_REPLACE);
        write = 0;
        break;
    case Rml::ClipMaskOperation::Intersect:
        m_dev->SetRenderState(D3DRS_STENCILPASS, D3DSTENCILOP_INCR);
        test = m_stencilRef + 1;
        break;
    }
    m_dev->SetRenderState(D3DRS_STENCILENABLE, TRUE);
    m_dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0);
    m_dev->SetRenderState(D3DRS_STENCILFUNC, D3DCMP_ALWAYS);
    m_dev->SetRenderState(D3DRS_STENCILREF, write);
    RenderGeometry(geometry, translation, {});
    m_dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
    m_dev->SetRenderState(D3DRS_STENCILPASS, D3DSTENCILOP_KEEP);
    m_dev->SetRenderState(D3DRS_STENCILFUNC, D3DCMP_EQUAL);
    m_dev->SetRenderState(D3DRS_STENCILREF, test);
    m_stencilRef = test;
}

// ================================================================ post-process helpers ==============
void RenderInterface_D3D9::DrawQuad(IDirect3DTexture9* src, IDirect3DPixelShader9* ps, int vpW, int vpH, Rml::Vector2f off, Rml::Vector2f sc) {
    const float u0 = off.x, v0 = off.y, u1 = sc.x + off.x, v1 = sc.y + off.y;
    const QuadVtx q[4] = { { -1, 1, u0, v0 }, { 1, 1, u1, v0 }, { -1, -1, u0, v1 }, { 1, -1, u1, v1 } };
    const float hp[4] = { 1.f / (float)vpW, 1.f / (float)vpH, 0, 0 };
    m_dev->SetVertexShaderConstantF(5, hp, 1);
    m_dev->SetVertexDeclaration(m_declQuad);
    m_dev->SetVertexShader(m_vsQuad);
    m_dev->SetPixelShader(ps);
    SetAddress0(D3DTADDRESS_CLAMP);                       // full-screen post-process: never wrap
    m_dev->SetTexture(0, src);
    m_dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, q, sizeof(QuadVtx));
    ++m_stats.draws;
}

static void SigmaToParameters(float desired, int& passLevel, float& sigma) {
    const int maxPasses = 10; const float maxSingle = 3.0f;
    passLevel = Rml::Math::Clamp(Rml::Math::Log2(int(desired * (2.f / maxSingle))), 0, maxPasses);
    sigma = Rml::Math::Clamp(desired / float(1 << passLevel), 0.0f, maxSingle);
}

void RenderInterface_D3D9::RenderBlur(float sigma, RT& srcDst, RT& temp, Rml::Rectanglei window) {
    int passLevel = 0;
    TRACE("rtt: Blur sigma=%.2f window %d,%d-%d,%d", sigma, window.Left(), window.Top(), window.Right(), window.Bottom());
    SigmaToParameters(sigma, passLevel, sigma);
    const float onePass[4] = { 1, 0, 0, 0 };
    m_dev->SetPixelShaderConstantF(0, onePass, 1);
    m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);

    // iterative half-scale downsampling into the top-left of the targets
    Rml::Rectanglei sc = window;
    const int W = m_w, H = m_h;
    const Rml::Vector2f uvScale = { (W % 2 == 1) ? (1.f - 1.f / W) : 1.f, (H % 2 == 1) ? (1.f - 1.f / H) : 1.f };
    D3DVIEWPORT9 half{ 0, 0, (DWORD)(W / 2), (DWORD)(H / 2), 0.f, 1.f };
    for (int i = 0; i < passLevel; i++) {
        sc = Rml::Rectanglei::FromCorners((sc.p0 + Rml::Vector2i(1)) / 2, Rml::Math::Max(sc.p1 / 2, (sc.p0 + Rml::Vector2i(1)) / 2));
        const bool fromSource = (i % 2 == 0);
        BindTarget((fromSource ? temp : srcDst).surf);
        m_dev->SetViewport(&half);
        ApplyScissor(sc);
        m_dev->SetPixelShaderConstantF(0, onePass, 1);
        DrawQuad((fromSource ? srcDst : temp).tex, m_psPassthrough, W / 2, H / 2, {}, uvScale);
    }
    // make sure the (downscaled) image is in temp
    if (passLevel % 2 == 0) {
        BindTarget(temp.surf);
        ApplyScissor(sc);
        m_dev->SetPixelShaderConstantF(0, onePass, 1);
        DrawQuad(srcDst.tex, m_psPassthrough, W, H);
    }

    // weights
    float weights[4]; float norm = 0;
    for (int i = 0; i < 4; i++) {
        weights[i] = (std::fabs(sigma) < 0.1f) ? float(i == 0) : std::exp(-float(i * i) / (2.f * sigma * sigma)) / (std::sqrt(2.f * 3.14159265f) * sigma);
        norm += (i == 0 ? 1.f : 2.f) * weights[i];
    }
    for (float& w : weights) w /= norm;
    const float limits[4] = { (sc.Left() + 0.5f) / W, (sc.Top() + 0.5f) / H, (sc.Right() - 0.5f) / W, (sc.Bottom() - 0.5f) / H };

    // vertical: temp -> srcDst
    BindTarget(srcDst.surf);
    ApplyScissor(sc);
    float c[12] = { weights[0], weights[1], weights[2], weights[3], 0, 1.f / H, 0, 0, limits[0], limits[1], limits[2], limits[3] };
    m_dev->SetPixelShaderConstantF(0, c, 3);
    DrawQuad(temp.tex, m_psBlur, W, H);

    // horizontal: srcDst -> temp, with a cleared 1px border around the region
    BindTarget(temp.surf);
    ApplyScissor(sc.Extend(1));
    m_dev->Clear(0, nullptr, D3DCLEAR_TARGET, 0, 1.f, 0);
    ApplyScissor(sc);
    c[4] = 1.f / W; c[5] = 0;
    m_dev->SetPixelShaderConstantF(0, c, 3);
    DrawQuad(srcDst.tex, m_psBlur, W, H);

    // upscale back over the window
    RECT srcR{ sc.Left(), sc.Top(), sc.Right(), sc.Bottom() };
    RECT dstR{ window.Left(), window.Top(), window.Right(), window.Bottom() };
    if (srcR.right > srcR.left && srcR.bottom > srcR.top && dstR.right > dstR.left && dstR.bottom > dstR.top)
        m_dev->StretchRect(temp.surf, &srcR, srcDst.surf, &dstR, D3DTEXF_LINEAR);

    m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    D3DVIEWPORT9 full{ 0, 0, (DWORD)W, (DWORD)H, 0.f, 1.f };
    m_dev->SetViewport(&full);
}

void RenderInterface_D3D9::RenderFilters(Rml::Span<const Rml::CompiledFilterHandle> filters) {
    const Rml::Rectanglei window = FilterWindow();
    for (Rml::CompiledFilterHandle h : filters) {
        const CompiledFilter& f = *reinterpret_cast<const CompiledFilter*>(h);
        ++m_stats.filters;
        switch (f.type) {
        case FilterType::Passthrough: {
            m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
            BindTarget(m_post[1].surf); RestoreScissor();
            const float k[4] = { f.blend, 0, 0, 0 };
            m_dev->SetPixelShaderConstantF(0, k, 1);
            DrawQuad(m_post[0].tex, m_psPassthrough, m_w, m_h);
            std::swap(m_post[0], m_post[1]);
            m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        } break;
        case FilterType::Blur:
            RenderBlur(f.sigma, m_post[0], m_post[1], window);
            RestoreScissor();
            break;
        case FilterType::DropShadow: {
            if (!CreateRT(m_post[2])) break;
            m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
            BindTarget(m_post[1].surf); RestoreScissor();
            const Rml::Colourf col = ToF(f.color);
            const float c[8] = { col[0], col[1], col[2], col[3],
                (window.Left() + 0.5f) / m_w, (window.Top() + 0.5f) / m_h, (window.Right() - 0.5f) / m_w, (window.Bottom() - 0.5f) / m_h };
            m_dev->SetPixelShaderConstantF(0, c, 2);
            DrawQuad(m_post[0].tex, m_psDropShadow, m_w, m_h, { -f.offset.x / m_w, -f.offset.y / m_h });
            if (f.sigma >= 0.5f) { RenderBlur(f.sigma, m_post[1], m_post[2], window); }
            BindTarget(m_post[1].surf); RestoreScissor();
            m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
            const float one[4] = { 1, 0, 0, 0 };
            m_dev->SetPixelShaderConstantF(0, one, 1);
            DrawQuad(m_post[0].tex, m_psPassthrough, m_w, m_h);
            std::swap(m_post[0], m_post[1]);
        } break;
        case FilterType::ColorMatrix: {
            m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
            BindTarget(m_post[1].surf); RestoreScissor();
            float c[12];
            for (int r = 0; r < 3; ++r) for (int k = 0; k < 4; ++k) c[r * 4 + k] = El(f.matrix, r, k);
            m_dev->SetPixelShaderConstantF(0, c, 3);
            DrawQuad(m_post[0].tex, m_psColorMatrix, m_w, m_h);
            std::swap(m_post[0], m_post[1]);
            m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        } break;
        case FilterType::MaskImage: {
            m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
            BindTarget(m_post[1].surf); RestoreScissor();
            m_dev->SetTexture(1, m_blendMask.tex);
            DrawQuad(m_post[0].tex, m_psBlendMask, m_w, m_h);
            m_dev->SetTexture(1, nullptr);
            std::swap(m_post[0], m_post[1]);
            m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        } break;
        default: break;
        }
    }
}

// ================================================================ layers ============================
Rml::LayerHandle RenderInterface_D3D9::PushLayer() {
    const int index = m_layerCount;
    TRACE("rtt: PushLayer -> %d (inFrame=%d bb=%p scissor %s %d,%d-%d,%d)", index, m_sb != nullptr, (void*)m_backBuffer, m_scissorOn ? "on" : "off",
          m_scissor.Left(), m_scissor.Top(), m_scissor.Right(), m_scissor.Bottom());
    if ((int)m_layers.size() <= index) m_layers.resize(index + 1);
    if (!CreateRT(m_layers[index])) return (Rml::LayerHandle)(m_layerCount - 1);
    ++m_layerCount;
    m_stats.layersPeak = std::max(m_stats.layersPeak, (unsigned)m_layerCount);
    BindTarget(m_layers[index].surf);
    RestoreScissor();
    m_dev->Clear(0, nullptr, D3DCLEAR_TARGET, 0, 1.f, 0);
    return (Rml::LayerHandle)index;
}

void RenderInterface_D3D9::CompositeLayers(Rml::LayerHandle source, Rml::LayerHandle destination, Rml::BlendMode blend,
                                           Rml::Span<const Rml::CompiledFilterHandle> filters) {
    if (!CreateRT(m_post[0]) || !CreateRT(m_post[1])) return;
    TRACE("rtt: Composite %d -> %d blend=%d filters=%u window %d,%d-%d,%d", (int)source, (int)destination, (int)blend, (unsigned)filters.size(),
          FilterWindow().Left(), FilterWindow().Top(), FilterWindow().Right(), FilterWindow().Bottom());
    m_dev->StretchRect(LayerSurface(source), nullptr, m_post[0].surf, nullptr, D3DTEXF_NONE);
    // Post-process passes must ignore the clip mask: GL3's post-process framebuffers have no stencil attachment, but in
    // D3D9 our stencil surface stays bound for every target. Only the final composite into the destination is masked.
    m_dev->SetRenderState(D3DRS_STENCILENABLE, FALSE);
    RenderFilters(filters);
    m_dev->SetRenderState(D3DRS_STENCILENABLE, m_clipMaskOn ? TRUE : FALSE);

    BindTarget(LayerSurface(destination));
    RestoreScissor();
    if (blend == Rml::BlendMode::Replace) m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, FALSE);
    const float one[4] = { 1, 0, 0, 0 };
    m_dev->SetPixelShaderConstantF(0, one, 1);
    DrawQuad(m_post[0].tex, m_psPassthrough, m_w, m_h);
    if (blend == Rml::BlendMode::Replace) m_dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    BindTarget(TopSurface());
    RestoreScissor();
}

void RenderInterface_D3D9::PopLayer() {
    if (m_layerCount > 1) --m_layerCount;
    BindTarget(TopSurface());
    RestoreScissor();
}

Rml::TextureHandle RenderInterface_D3D9::SaveLayerAsTexture() {
    const Rml::Rectanglei b = FilterWindow();
    const int w = b.Width(), h = b.Height();
    TRACE("rtt: SaveLayerAsTexture top=%d rect %d,%d-%d,%d", m_layerCount - 1, b.Left(), b.Top(), b.Right(), b.Bottom());
    if (w <= 0 || h <= 0) return 0;
    const double t0 = NowMs(); ++m_prof.nSave;
    struct Acc { double& d; double t; ~Acc() { d += RenderInterface_D3D9::NowMs() - t; } } acc{ m_prof.save, t0 };
    // GPU-only: the saved layer stays a D3DPOOL_DEFAULT render-target texture that is sampled later. The old path
    // read it back to system memory (GetRenderTargetData = a full GPU drain, ~4 ms each under DXVK) to build a MANAGED
    // copy; a panel open did that 7-10 times. DEFAULT-pool textures die at Reset, so OverlayOnPreReset calls
    // Rml::ReleaseTextures() and RmlUi regenerates them on the next frame.
    IDirect3DTexture9* out = nullptr; IDirect3DSurface9* outSurf = nullptr;
    Rml::TextureHandle result = 0;
    if (SUCCEEDED(m_dev->CreateTexture(w, h, 1, D3DUSAGE_RENDERTARGET, D3DFMT_A8R8G8B8, D3DPOOL_DEFAULT, &out, nullptr)) &&
        SUCCEEDED(out->GetSurfaceLevel(0, &outSurf))) {
        RECT src{ b.Left(), b.Top(), b.Right(), b.Bottom() };
        if (SUCCEEDED(m_dev->StretchRect(TopSurface(), &src, outSurf, nullptr, D3DTEXF_NONE))) {
            m_clampTex.insert(out);           // box-shadow etc.: drawn 0..1, keep edges clamped
            result = (Rml::TextureHandle)out; out = nullptr; ++m_stats.textures;
        }
    }
    if (outSurf) outSurf->Release();
    if (out) out->Release();
    if (!result) LOGE("rml: SaveLayerAsTexture %dx%d failed", w, h);
    RestoreScissor();
    return result;
}

Rml::CompiledFilterHandle RenderInterface_D3D9::SaveLayerAsMaskImage() {
    if (!CreateRT(m_blendMask)) return 0;
    m_dev->StretchRect(TopSurface(), nullptr, m_blendMask.surf, nullptr, D3DTEXF_NONE);   // StretchRect ignores stencil/scissor
    auto* f = new CompiledFilter(); f->type = FilterType::MaskImage;
    return reinterpret_cast<Rml::CompiledFilterHandle>(f);
}

// ================================================================ filters / shaders =================
Rml::CompiledFilterHandle RenderInterface_D3D9::CompileFilter(const Rml::String& name, const Rml::Dictionary& p) {
    CompiledFilter f;
    auto diag = [](float v) { return Rml::Matrix4f::Diag(v, v, v, 1.f); };
    if (name == "opacity") { f.type = FilterType::Passthrough; f.blend = Rml::Get(p, "value", 1.0f); }
    else if (name == "blur") { f.type = FilterType::Blur; f.sigma = Rml::Get(p, "sigma", 1.0f); }
    else if (name == "drop-shadow") {
        f.type = FilterType::DropShadow;
        f.sigma = Rml::Get(p, "sigma", 0.f);
        f.color = Rml::Get(p, "color", Rml::Colourb()).ToPremultiplied();
        f.offset = Rml::Get(p, "offset", Rml::Vector2f(0.f));
    }
    else if (name == "brightness") { f.type = FilterType::ColorMatrix; f.matrix = diag(Rml::Get(p, "value", 1.0f)); }
    else if (name == "contrast") {
        f.type = FilterType::ColorMatrix; const float v = Rml::Get(p, "value", 1.0f), g = 0.5f - 0.5f * v;
        f.matrix = diag(v); f.matrix.SetColumn(3, Rml::Vector4f(g, g, g, 1.f));
    }
    else if (name == "invert") {
        f.type = FilterType::ColorMatrix; const float v = Rml::Math::Clamp(Rml::Get(p, "value", 1.0f), 0.f, 1.f), inv = 1.f - 2.f * v;
        f.matrix = diag(inv); f.matrix.SetColumn(3, Rml::Vector4f(v, v, v, 1.f));
    }
    else if (name == "grayscale") {
        f.type = FilterType::ColorMatrix; const float v = Rml::Get(p, "value", 1.0f), r = 1.f - v;
        const Rml::Vector3f g = v * Rml::Vector3f(0.2126f, 0.7152f, 0.0722f);
        f.matrix = Rml::Matrix4f::FromRows({ g.x + r, g.y, g.z, 0.f }, { g.x, g.y + r, g.z, 0.f }, { g.x, g.y, g.z + r, 0.f }, { 0.f, 0.f, 0.f, 1.f });
    }
    else if (name == "sepia") {
        f.type = FilterType::ColorMatrix; const float v = Rml::Get(p, "value", 1.0f), r = 1.f - v;
        const Rml::Vector3f a = v * Rml::Vector3f(0.393f, 0.769f, 0.189f), b = v * Rml::Vector3f(0.349f, 0.686f, 0.168f), c = v * Rml::Vector3f(0.272f, 0.534f, 0.131f);
        f.matrix = Rml::Matrix4f::FromRows({ a.x + r, a.y, a.z, 0.f }, { b.x, b.y + r, b.z, 0.f }, { c.x, c.y, c.z + r, 0.f }, { 0.f, 0.f, 0.f, 1.f });
    }
    else if (name == "hue-rotate") {
        f.type = FilterType::ColorMatrix; const float v = Rml::Get(p, "value", 1.0f), s = std::sin(v), c = std::cos(v);
        f.matrix = Rml::Matrix4f::FromRows(
            { 0.213f + 0.787f * c - 0.213f * s, 0.715f - 0.715f * c - 0.715f * s, 0.072f - 0.072f * c + 0.928f * s, 0.f },
            { 0.213f - 0.213f * c + 0.143f * s, 0.715f + 0.285f * c + 0.140f * s, 0.072f - 0.072f * c - 0.283f * s, 0.f },
            { 0.213f - 0.213f * c - 0.787f * s, 0.715f - 0.715f * c + 0.715f * s, 0.072f + 0.928f * c + 0.072f * s, 0.f },
            { 0.f, 0.f, 0.f, 1.f });
    }
    else if (name == "saturate") {
        f.type = FilterType::ColorMatrix; const float v = Rml::Get(p, "value", 1.0f);
        f.matrix = Rml::Matrix4f::FromRows(
            { 0.213f + 0.787f * v, 0.715f - 0.715f * v, 0.072f - 0.072f * v, 0.f },
            { 0.213f - 0.213f * v, 0.715f + 0.285f * v, 0.072f - 0.072f * v, 0.f },
            { 0.213f - 0.213f * v, 0.715f - 0.715f * v, 0.072f + 0.928f * v, 0.f },
            { 0.f, 0.f, 0.f, 1.f });
    }
    if (f.type == FilterType::Invalid) { LOGW("rml: unsupported filter '%s'", name.c_str()); return 0; }
    return reinterpret_cast<Rml::CompiledFilterHandle>(new CompiledFilter(f));
}

void RenderInterface_D3D9::ReleaseFilter(Rml::CompiledFilterHandle filter) { delete reinterpret_cast<CompiledFilter*>(filter); }

Rml::CompiledShaderHandle RenderInterface_D3D9::CompileShader(const Rml::String& name, const Rml::Dictionary& p) {
    CompiledShader s;
    auto stops = [&]() {
        auto it = p.find("color_stop_list");
        if (it == p.end() || it->second.GetType() != Rml::Variant::COLORSTOPLIST) return;
        const Rml::ColorStopList& list = it->second.GetReference<Rml::ColorStopList>();
        const int n = std::min((int)list.size(), 16);
        for (int i = 0; i < n; ++i) { s.positions.push_back(list[i].position.number); s.colors.push_back(ToF(list[i].color)); }
        s.valid = n > 0;
    };
    const bool rep = Rml::Get(p, "repeating", false);
    if (name == "linear-gradient") {
        s.func = rep ? GradientFunc::RepeatingLinear : GradientFunc::Linear;
        s.p = Rml::Get(p, "p0", Rml::Vector2f(0.f)); s.v = Rml::Get(p, "p1", Rml::Vector2f(0.f)) - s.p; stops();
    } else if (name == "radial-gradient") {
        s.func = rep ? GradientFunc::RepeatingRadial : GradientFunc::Radial;
        s.p = Rml::Get(p, "center", Rml::Vector2f(0.f)); s.v = Rml::Vector2f(1.f) / Rml::Get(p, "radius", Rml::Vector2f(1.f)); stops();
    } else if (name == "conic-gradient") {
        s.func = rep ? GradientFunc::RepeatingConic : GradientFunc::Conic;
        s.p = Rml::Get(p, "center", Rml::Vector2f(0.f)); const float a = Rml::Get(p, "angle", 0.f); s.v = { std::cos(a), std::sin(a) }; stops();
    }
    if (!s.valid) { LOGW("rml: unsupported shader '%s'", name.c_str()); return 0; }
    return reinterpret_cast<Rml::CompiledShaderHandle>(new CompiledShader(s));
}

void RenderInterface_D3D9::RenderShader(Rml::CompiledShaderHandle shader, Rml::CompiledGeometryHandle geometry, Rml::Vector2f translation, Rml::TextureHandle) {
    const auto* s = reinterpret_cast<const CompiledShader*>(shader);
    auto* g = (Geometry*)geometry;
    if (!m_shadersOk || !s || !g || !g->vb) return;
    float c[22 * 4] = {};
    c[0] = (float)(int)s->func; c[1] = (float)s->positions.size();
    c[4] = s->p.x; c[5] = s->p.y; c[6] = s->v.x; c[7] = s->v.y;
    for (size_t i = 0; i < s->colors.size(); ++i) for (int k = 0; k < 4; ++k) c[(2 + i) * 4 + k] = s->colors[i][k];
    for (size_t i = 0; i < s->positions.size(); ++i) c[18 * 4 + i] = s->positions[i];
    SubmitGeometryTransform(translation);
    m_dev->SetPixelShaderConstantF(0, c, 22);
    m_dev->SetPixelShader(m_psGradient);
    m_dev->SetTexture(0, nullptr);
    m_dev->SetStreamSource(0, g->vb, 0, sizeof(Vtx));
    m_dev->SetIndices(g->ib);
    m_dev->DrawIndexedPrimitive(D3DPT_TRIANGLELIST, 0, 0, g->numVertices, 0, g->numIndices / 3);
    ++m_stats.draws;
}

void RenderInterface_D3D9::ReleaseShader(Rml::CompiledShaderHandle shader) { delete reinterpret_cast<CompiledShader*>(shader); }

