// ui_host.cpp - the RmlUi host inside the proxy (napoleon J30): context and lifecycle on the main D3D9 device, the frame pass from the
// Present chain, input routing (a Win32 window subclass plus the DirectInput mouse and keyboard devices' vtables), the scale model, the
// `ui` control verb and the lossless back-buffer dump. Pure decisions live in ui_core.h (host-tested); the render interface in
// ui_render_d3d9.*; Lua in ui_lua.* (its own copy). Ported in design from empire-remastered rml_mod/src/{overlay,input,hooks}.cpp
// without its panel manager, warm copies, tips, native holes, gestures or MinHook (D26: IAT and vtable hooks only).
//
// ui.enabled=0 (the default and the release value): UiInit returns after reading the keys; no hook, no allocation, no RmlUi call.
// Threads: Present (the render thread), the game window's procedure, the DirectInput reads and the ctl thread. Every RmlUi call is made
// under s_cs. The ctl thread never touches RmlUi or the device: it queues a request the next Present runs (show, hide, reload, scale,
// dump) or sends window messages (click, wheel) that take the same route real input takes.
#include "ui_d3d9.h"
#include "ui_core.h"
#include "ui_host.h"
#include "ui_lua.h"
#include "ui_render_d3d9.h"
#include "ui_rml.h"
#include <RmlUi/Core.h>
#include <RmlUi/Core/Factory.h>
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wsign-compare"
#pragma GCC diagnostic ignored "-Wimplicit-fallthrough"
#pragma GCC diagnostic ignored "-Wunused-function"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STBI_WRITE_NO_STDIO
#include <stb_image_write.h>
#pragma GCC diagnostic pop
#include <map>
#include <vector>
#include <cstdio>

namespace wsp {

const char* BackendName();

namespace {

// ---- keys and state ---------------------------------------------------------------------------------------------------------------
struct Keys { bool enabled = false; int scale = 100; std::wstring dir, dumpDir; std::string show; } K;
bool s_on = false;                       // ui.enabled and the plan allows D3D hooks
CRITICAL_SECTION s_cs;
struct Lock { Lock() { EnterCriticalSection(&s_cs); } ~Lock() { LeaveCriticalSection(&s_cs); } };

UiLifecycle s_life;
IDirect3DDevice9* s_dev = nullptr;
RenderInterface_D3D9* s_ri = nullptr;
Rml::Context* s_ctx = nullptr;
bool s_rmlUp = false, s_showDone = false;
std::string s_offWhy;                    // why the UI is off (no shader compiler, Rml::Initialise failed)
int s_bbW = 0, s_bbH = 0, s_scale = 100;
float s_dp = 1.f;
HWND s_hwnd = nullptr; WNDPROC s_prevProc = nullptr; bool s_wide = true;
DWORD s_presentTid = 0, s_wndTid = 0;
std::string s_luaWhy;

struct Doc { Rml::ElementDocument* doc = nullptr; bool visible = false; };
std::map<std::string, Doc> s_docs;       // by the path under the UI folder

UiRouteState s_route; bool s_rmlOwner = false;
volatile LONG64 s_cnt[6][2];             // per UiEv: [0] delivered to RmlUi, [1] to the engine
volatile LONG s_wmLButton = 0, s_diStateButtons = 0, s_diDataButtons = 0, s_diStateReads = 0, s_diDataReads = 0;
unsigned s_diMouseBtnPrev = 0;
volatile LONG s_rmlWarn = 0, s_rmlErr = 0;

struct Sample { double t; float upd, rnd, hook; unsigned draws; };
std::vector<Sample> s_samples; size_t s_sampleNext = 0; bool s_sampleWrapped = false;
const size_t kSamples = 32768;
uint64_t s_framesDrawn = 0, s_presents = 0; unsigned s_lastDraws = 0;

// ---- the render-thread request (show, hide, reload, scale, dump) ----------------------------------------------------------------
struct Req { UiArgs a; std::string result, why; bool ok = false; };
Req* s_req = nullptr; HANDLE s_reqDone = nullptr;

std::string Narrow8(const std::wstring& w) { return Narrow(w); }
std::string JEsc(const std::string& s) {
    std::string o; for (char c : s) { if (c == '"' || c == '\\') { o += '\\'; o += c; } else if ((unsigned char)c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; } else o += c; }
    return o;
}

// ---- RmlUi interfaces -------------------------------------------------------------------------------------------------------------
class System : public Rml::SystemInterface {
public:
    double GetElapsedTime() override { return MonoS() - t0; }
    bool LogMessage(Rml::Log::Type type, const Rml::String& m) override {
        if (type == Rml::Log::LT_ERROR || type == Rml::Log::LT_ASSERT) { InterlockedIncrement(&s_rmlErr); LOGE("rml: %s", m.c_str()); }
        else if (type == Rml::Log::LT_WARNING) { InterlockedIncrement(&s_rmlWarn); LOGW("rml: %s", m.c_str()); }
        else LOGI("rml: %s", m.c_str());
        return true;
    }
    double t0 = MonoS();
} s_sys;

UiClicks s_clicks;   // data-host-counter (ui_rml.h)

std::wstring UiPath(const std::string& rel) {
    std::wstring p = Rt().gameDir + K.dir; if (!p.empty() && p.back() != L'\\') p += L'\\';
    std::wstring r = WidenUtf8(rel); for (auto& c : r) if (c == L'/') c = L'\\';
    return p + r;
}

bool AnyVisible() { for (auto& kv : s_docs) if (kv.second.visible) return true; return false; }

void ApplyScale() {
    s_dp = UiDpRatio(s_bbH, s_scale);
    if (s_ctx) { s_ctx->SetDimensions({ s_bbW, s_bbH }); s_ctx->SetDensityIndependentPixelRatio(s_dp); }
    if (s_ri) s_ri->SetViewport(s_bbW, s_bbH);
    LOGI("ui: back buffer %dx%d, ui.scale %d %% -> dp ratio %.4f", s_bbW, s_bbH, s_scale, s_dp);
}

bool LoadDoc(const std::string& name, std::string& why) {
    auto it = s_docs.find(name);
    if (it != s_docs.end() && it->second.doc) return true;
    const std::string path = Narrow8(UiPath(name));
    if (GetFileAttributesW(UiPath(name).c_str()) == INVALID_FILE_ATTRIBUTES) { why = "no file " + path; return false; }
    Rml::ElementDocument* d = s_ctx->LoadDocument(path);
    if (!d) { why = "RmlUi could not load " + path + " (log: rml: lines)"; return false; }
    d->AddEventListener(Rml::EventId::Click, &s_clicks);
    s_docs[name].doc = d;
    return true;
}
bool ShowDoc(const std::string& name, std::string& why) {
    if (!LoadDoc(name, why)) return false;
    Doc& d = s_docs[name]; d.doc->Show(); d.visible = true;
    LOGI("ui: show %s", name.c_str());
    return true;
}
bool HideDoc(const std::string& name, std::string& why) {
    auto it = s_docs.find(name);
    if (it == s_docs.end() || !it->second.doc) { why = name + " is not loaded"; return false; }
    it->second.doc->Hide(); it->second.visible = false;
    LOGI("ui: hide %s", name.c_str());
    return true;
}
bool ReloadDoc(const std::string& name, std::string& why) {
    auto it = s_docs.find(name);
    const bool wasVisible = it == s_docs.end() ? true : it->second.visible;
    if (it != s_docs.end() && it->second.doc) { it->second.doc->Close(); s_docs.erase(it); }
    Rml::Factory::ClearStyleSheetCache(); Rml::Factory::ClearTemplateCache();
    if (!LoadDoc(name, why)) return false;
    if (wasVisible) { s_docs[name].doc->Show(); s_docs[name].visible = true; }
    LOGI("ui: reload %s", name.c_str());
    return true;
}

void LoadFonts() {
    std::wstring dir = UiPath("fonts") + L"\\";
    WIN32_FIND_DATAW fd; int n = 0;
    HANDLE h = FindFirstFileW((dir + L"*.ttf").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) { LOGW("ui: no fonts in %ls", dir.c_str()); return; }
    do { if (Rml::LoadFontFace(Narrow8(dir + fd.cFileName))) ++n; else LOGW("ui: font %ls did not load", fd.cFileName); } while (FindNextFileW(h, &fd));
    FindClose(h);
    LOGI("ui: %d fonts from %ls", n, dir.c_str());
}

// Shut RmlUi down (device destroyed and another created, or detach). Documents are forgotten but their names kept to re-show.
std::vector<std::string> Shutdown() {
    std::vector<std::string> shown;
    for (auto& kv : s_docs) if (kv.second.visible) shown.push_back(kv.first);
    if (s_rmlUp) { Rml::Shutdown(); s_rmlUp = false; }
    UiLuaStop();
    s_ctx = nullptr; s_docs.clear();
    delete s_ri; s_ri = nullptr;
    LOGI("ui: shut down (%zu documents to show again)", shown.size());
    return shown;
}

bool StartRml(IDirect3DDevice9* dev, const std::vector<std::string>& reshow) {
    s_ri = new RenderInterface_D3D9(dev);
    s_ri->SetViewport(s_bbW, s_bbH);
    if (!s_ri->EnsureShaders()) { s_offWhy = "no shader compiler (d3dcompiler_47/43): UI off"; LOGE("ui: %s", s_offWhy.c_str()); delete s_ri; s_ri = nullptr; return false; }
    Rml::SetSystemInterface(&s_sys);
    Rml::SetRenderInterface(s_ri);
    if (!Rml::Initialise()) { s_offWhy = "Rml::Initialise failed: UI off"; LOGE("ui: %s", s_offWhy.c_str()); delete s_ri; s_ri = nullptr; return false; }
    s_rmlUp = true;
    s_luaWhy.clear();
    if (!UiLuaStart(s_luaWhy)) LOGW("ui: Lua off (%s): documents draw without their scripts", s_luaWhy.c_str());
    LoadFonts();
    s_ctx = Rml::CreateContext("main", { s_bbW, s_bbH });
    if (!s_ctx) { s_offWhy = "Rml::CreateContext failed: UI off"; LOGE("ui: %s", s_offWhy.c_str()); Shutdown(); return false; }
    ApplyScale();
    std::string why;
    for (const std::string& n : reshow) if (!ShowDoc(n, why)) LOGW("ui: show %s again: %s", n.c_str(), why.c_str());
    if (!s_showDone && !K.show.empty()) { s_showDone = true; if (!ShowDoc(K.show, why)) LOGW("ui: ui.show=%s: %s", K.show.c_str(), why.c_str()); }
    LOGI("ui: RmlUi %s up on device %p (%s backend), Lua %s", Rml::GetVersion().c_str(), (void*)dev, BackendName(), UiLuaUp() ? "up" : "off");
    return true;
}

// ---- the back-buffer dump (lossless PNG) ------------------------------------------------------------------------------------------
void PngSink(void* ctx, void* data, int size) { static_cast<std::string*>(ctx)->append((const char*)data, (size_t)size); }
bool Dump(const UiArgs& a, std::string& result, std::string& why) {
    IDirect3DSurface9* bb = nullptr; IDirect3DSurface9* rt = nullptr; IDirect3DSurface9* sys = nullptr;
    struct Rel { IDirect3DSurface9*& p; ~Rel() { if (p) p->Release(); } } r1{ bb }, r2{ rt }, r3{ sys };
    if (FAILED(s_dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &bb))) { why = "GetBackBuffer failed"; return false; }
    D3DSURFACE_DESC d; bb->GetDesc(&d);
    if (d.Format != D3DFMT_X8R8G8B8 && d.Format != D3DFMT_A8R8G8B8) { why = "back buffer format " + std::to_string((int)d.Format) + " is not 8-bit RGB"; return false; }
    // a plain render target first (a multisampled back buffer cannot be read back directly), then system memory
    if (FAILED(s_dev->CreateRenderTarget(d.Width, d.Height, d.Format, D3DMULTISAMPLE_NONE, 0, FALSE, &rt, nullptr)) ||
        FAILED(s_dev->StretchRect(bb, nullptr, rt, nullptr, D3DTEXF_NONE)) ||
        FAILED(s_dev->CreateOffscreenPlainSurface(d.Width, d.Height, d.Format, D3DPOOL_SYSTEMMEM, &sys, nullptr)) ||
        FAILED(s_dev->GetRenderTargetData(rt, sys))) { why = "back-buffer read-back failed"; return false; }
    int x = 0, y = 0, w = (int)d.Width, h = (int)d.Height;
    if (a.rect) { x = a.x; y = a.y; w = a.w; h = a.h; if (x + w > (int)d.Width || y + h > (int)d.Height) { why = "rect outside the back buffer"; return false; } }
    D3DLOCKED_RECT lr;
    if (FAILED(sys->LockRect(&lr, nullptr, D3DLOCK_READONLY))) { why = "LockRect failed"; return false; }
    std::vector<unsigned char> rgb((size_t)w * h * 3);
    for (int j = 0; j < h; ++j) {
        const DWORD* s = (const DWORD*)((const BYTE*)lr.pBits + (size_t)(y + j) * lr.Pitch) + x;
        unsigned char* o = &rgb[(size_t)j * w * 3];
        for (int i = 0; i < w; ++i) { const DWORD p = s[i]; o[3 * i] = (p >> 16) & 0xFF; o[3 * i + 1] = (p >> 8) & 0xFF; o[3 * i + 2] = p & 0xFF; }
    }
    sys->UnlockRect();
    std::string png;
    if (!stbi_write_png_to_func(PngSink, &png, w, h, 3, rgb.data(), w * 3)) { why = "PNG encode failed"; return false; }
    CreateDirectoryW(K.dumpDir.c_str(), nullptr);
    std::wstring dir = K.dumpDir; if (!dir.empty() && dir.back() != L'\\') dir += L'\\';
    const std::wstring file = dir + WidenUtf8(a.name) + L".png";
    if (!WriteFileAtomic(file, png)) { why = "cannot write " + Narrow8(file); return false; }
    char b[512];
    snprintf(b, sizeof b, "\"dump\": {\"file\": \"%s\", \"x\": %d, \"y\": %d, \"w\": %d, \"h\": %d, \"bytes\": %zu, \"backbuffer\": [%u, %u], \"dp_ratio\": %.4f, \"scale\": %d}",
             JEsc(Narrow8(file)).c_str(), x, y, w, h, png.size(), d.Width, d.Height, s_dp, s_scale);
    result = b;
    return true;
}

void RunRequest(Req& r) {   // render thread, under s_cs
    const UiArgs& a = r.a;
    if (!s_ctx) { r.why = s_offWhy.empty() ? "no RmlUi context yet (no main device)" : s_offWhy; return; }
    if (a.op == "show") r.ok = ShowDoc(a.doc, r.why);
    else if (a.op == "hide") r.ok = HideDoc(a.doc, r.why);
    else if (a.op == "reload") r.ok = ReloadDoc(a.doc, r.why);
    else if (a.op == "scale") {
        const UiScale s = UiClampScale(a.percent);
        if (s.changed) LOGW("ui: ui scale %d is outside 85-125 or off the 5 %% grid: clamped to %d", a.percent, s.percent);
        s_scale = s.percent; ApplyScale(); r.ok = true;
        char b[160]; snprintf(b, sizeof b, "\"scale\": %d, \"clamped\": %s, \"dp_ratio\": %.4f", s_scale, s.changed ? "true" : "false", s_dp); r.result = b;
    }
    else if (a.op == "dump") r.ok = Dump(a, r.result, r.why);
    else r.why = "not a render-thread operation";
    if (r.ok && (a.op == "show" || a.op == "hide" || a.op == "reload")) {
        auto it = s_docs.find(a.doc);
        r.result = "\"document\": \"" + JEsc(a.doc) + "\", \"visible\": " + ((it != s_docs.end() && it->second.visible) ? "true" : "false");
    }
}

// ---- the frame pass ------------------------------------------------------------------------------------------------------------
LARGE_INTEGER s_qpf;
double Ms(LARGE_INTEGER a, LARGE_INTEGER b) { return (double)(b.QuadPart - a.QuadPart) * 1000.0 / (double)s_qpf.QuadPart; }   // integer ticks first (x87 24-bit, J44)

void Record(float upd, float rnd, float hook, unsigned draws) {
    if (s_samples.size() < kSamples) s_samples.push_back({ MonoS(), upd, rnd, hook, draws });
    else { s_samples[s_sampleNext] = { MonoS(), upd, rnd, hook, draws }; s_sampleWrapped = true; }
    s_sampleNext = (s_sampleNext + 1) % kSamples;
}

void Frame(IDirect3DDevice9* dev) {
    LARGE_INTEGER t0, t1, t2, t3; QueryPerformanceCounter(&t0);
    Lock l;
    ++s_presents;
    if (!s_presentTid && dev == s_dev) { s_presentTid = GetCurrentThreadId(); LOGI("ui: Present runs on thread %lu", s_presentTid); }
    Req* req = (s_req && s_req->a.op != "dump") ? s_req : nullptr;
    if (req) { RunRequest(*req); s_req = nullptr; SetEvent(s_reqDone); }
    float upd = 0, rnd = 0; unsigned draws = 0;
    t1 = t0; t2 = t0;
    if (s_ctx && (s_life.Present(dev, AnyVisible()) & kActDraw)) {
        QueryPerformanceCounter(&t1);
        s_ctx->Update();
        QueryPerformanceCounter(&t2);
        if (SUCCEEDED(dev->BeginScene())) {
            s_ri->BeginFrame(); s_ctx->Render(); s_ri->EndFrame();
            dev->EndScene();
            draws = s_ri->GetStats().draws; ++s_framesDrawn;
        }
        UiLuaStep();
        QueryPerformanceCounter(&t3);
        upd = (float)Ms(t1, t2); rnd = (float)Ms(t2, t3);
    }
    s_lastDraws = draws;
    if (s_req && s_req->a.op == "dump" && dev == s_dev) { RunRequest(*s_req); s_req = nullptr; SetEvent(s_reqDone); }   // after the UI drew
    LARGE_INTEGER te; QueryPerformanceCounter(&te);
    Record(upd, rnd, (float)Ms(t0, te), draws);
}

// ---- D3D hooks -------------------------------------------------------------------------------------------------------------------
using PFN_CreateDevice = HRESULT(WINAPI*)(IDirect3D9*, UINT, D3DDEVTYPE, HWND, DWORD, D3DPRESENT_PARAMETERS*, IDirect3DDevice9**);
using PFN_Reset = HRESULT(WINAPI*)(IDirect3DDevice9*, D3DPRESENT_PARAMETERS*);
using PFN_Present = HRESULT(WINAPI*)(IDirect3DDevice9*, const RECT*, const RECT*, HWND, const RGNDATA*);
PFN_CreateDevice o_CreateDevice; PFN_Reset o_Reset; PFN_Present o_Present;

void SizeFrom(const D3DPRESENT_PARAMETERS* pp, HWND w) {
    s_bbW = (int)pp->BackBufferWidth; s_bbH = (int)pp->BackBufferHeight;
    if ((s_bbW == 0 || s_bbH == 0) && w) { RECT rc; GetClientRect(w, &rc); s_bbW = rc.right; s_bbH = rc.bottom; }
}

LRESULT CALLBACK WndProc(HWND h, UINT msg, WPARAM wp, LPARAM lp);
void Subclass(HWND w) {
    if (!w || w == s_hwnd) return;
    if (s_hwnd && s_prevProc) LOGW("ui: a second game window %p (first %p): input stays on the first", (void*)w, (void*)s_hwnd);
    if (s_hwnd) return;
    s_wide = IsWindowUnicode(w) != 0;
    s_prevProc = (WNDPROC)(LONG_PTR)(s_wide ? SetWindowLongW(w, GWL_WNDPROC, (LONG)(LONG_PTR)WndProc) : SetWindowLongA(w, GWL_WNDPROC, (LONG)(LONG_PTR)WndProc));
    s_hwnd = w; s_wndTid = GetWindowThreadProcessId(w, nullptr);
    LOGI("ui: window %p subclassed (%s, thread %lu), previous procedure %p", (void*)w, s_wide ? "unicode" : "ansi", s_wndTid, (void*)s_prevProc);
}

HRESULT WINAPI hk_Present(IDirect3DDevice9* dev, const RECT* a, const RECT* b, HWND w, const RGNDATA* r) {
    if (dev == s_dev) Frame(dev);
    return o_Present(dev, a, b, w, r);
}
HRESULT WINAPI hk_Reset(IDirect3DDevice9* dev, D3DPRESENT_PARAMETERS* pp) {
    { Lock l; if ((s_life.PreReset(dev) & kActReleaseDefault) && s_ri) { s_ri->ReleaseDeviceResources(); LOGI("ui: Reset: default-pool resources released"); } }
    const HRESULT hr = o_Reset(dev, pp);
    Lock l;
    if (s_life.PostReset(dev, SUCCEEDED(hr)) & kActRebuild) { SizeFrom(pp, s_hwnd); ApplyScale(); LOGI("ui: Reset ok: rebuilt lazily at the next frame"); }
    else if (dev == s_dev) LOGW("ui: Reset -> 0x%08lx: nothing drawn until a Reset succeeds", (unsigned long)hr);
    return hr;
}
HRESULT WINAPI hk_CreateDevice(IDirect3D9* d3d, UINT ad, D3DDEVTYPE type, HWND focus, DWORD flags, D3DPRESENT_PARAMETERS* pp, IDirect3DDevice9** out) {
    const HRESULT hr = o_CreateDevice(d3d, ad, type, focus, flags, pp, out);
    if (FAILED(hr) || !out || !*out || !pp) return hr;
    IDirect3DDevice9* dev = *out;
    HWND w = pp->hDeviceWindow ? pp->hDeviceWindow : focus;
    D3DPRESENT_PARAMETERS q = *pp; SizeFrom(&q, w);
    const bool main = UiIsMainDevice((unsigned)s_bbW, (unsigned)s_bbH, w != nullptr && GetAncestor(w, GA_ROOT) == w);
    LOGI("ui: CreateDevice %p window %p back buffer %ux%u (%s, flags 0x%lx, multisample %d) -> %s", (void*)dev, (void*)w, pp->BackBufferWidth, pp->BackBufferHeight,
         pp->Windowed ? "windowed" : "fullscreen", flags, (int)pp->MultiSampleType, main ? "the UI's device" : "not the UI's (helper)");
    Lock l;
    const uint8_t act = s_life.Created(dev, main);
    if (!act) return hr;
    std::vector<std::string> reshow;
    if (act & kActShutdown) { LOGI("ui: a new main device replaces %p: release and re-init", (void*)s_dev); reshow = Shutdown(); }
    s_dev = dev;   // no reference of our own: a held device could block the game re-creating it in exclusive mode
    void** vt = *(void***)dev;
    VtableHook(vt, 16, (void*)hk_Reset, o_Reset ? nullptr : (void**)&o_Reset, "IDirect3DDevice9::Reset (ui)");
    VtableHook(vt, 17, (void*)hk_Present, o_Present ? nullptr : (void**)&o_Present, "IDirect3DDevice9::Present (ui)");
    Subclass(w);
    if (!StartRml(dev, reshow)) s_life.Fail();
    return hr;
}

// ---- input: the window subclass -------------------------------------------------------------------------------------------------
LRESULT Engine(HWND h, UINT msg, WPARAM wp, LPARAM lp) { return s_wide ? CallWindowProcW(s_prevProc, h, msg, wp, lp) : CallWindowProcA(s_prevProc, h, msg, wp, lp); }
inline int LpX(LPARAM lp) { return (int)(short)LOWORD(lp); }
inline int LpY(LPARAM lp) { return (int)(short)HIWORD(lp); }
int Mods() {
    int m = 0;
    if (GetKeyState(VK_CONTROL) & 0x8000) m |= Rml::Input::KM_CTRL;
    if (GetKeyState(VK_SHIFT) & 0x8000) m |= Rml::Input::KM_SHIFT;
    if (GetKeyState(VK_MENU) & 0x8000) m |= Rml::Input::KM_ALT;
    return m;
}
void ToBackbuffer(int& x, int& y) {   // client pixels -> back-buffer pixels (a windowed back buffer may differ from the client size)
    RECT rc; if (!s_hwnd || !GetClientRect(s_hwnd, &rc) || rc.right <= 0 || rc.bottom <= 0) return;
    if (rc.right != s_bbW) x = (int)((long long)x * s_bbW / rc.right);
    if (rc.bottom != s_bbH) y = (int)((long long)y * s_bbH / rc.bottom);
}
// After RmlUi saw the pointer: is it over an interactive element, and can anything under it scroll?
void Sense() {
    s_route.hoverInteractive = s_ctx->IsMouseInteracting();
    s_route.overScrollable = UiOverScrollable(s_ctx);
    s_route.textFocus = UiTextFocus(s_ctx);
}
void Count(UiEv ev, uint8_t to) {
    if (to & kToRml) InterlockedIncrement64(&s_cnt[(int)ev][0]);
    if (to & kToEngine) InterlockedIncrement64(&s_cnt[(int)ev][1]);
}
Rml::Input::KeyIdentifier Key(WPARAM vk) {
    using namespace Rml::Input;
    if (vk >= 'A' && vk <= 'Z') return (KeyIdentifier)(KI_A + (vk - 'A'));
    if (vk >= '0' && vk <= '9') return (KeyIdentifier)(KI_0 + (vk - '0'));
    switch (vk) {
    case VK_BACK: return KI_BACK; case VK_DELETE: return KI_DELETE; case VK_LEFT: return KI_LEFT; case VK_RIGHT: return KI_RIGHT;
    case VK_UP: return KI_UP; case VK_DOWN: return KI_DOWN; case VK_HOME: return KI_HOME; case VK_END: return KI_END;
    case VK_RETURN: return KI_RETURN; case VK_TAB: return KI_TAB; case VK_ESCAPE: return KI_ESCAPE; case VK_SPACE: return KI_SPACE;
    default: return KI_UNKNOWN;
    }
}

LRESULT CALLBACK WndProc(HWND h, UINT msg, WPARAM wp, LPARAM lp) {
    UiEv ev; int button = -1; bool down = false;
    switch (msg) {
    case WM_MOUSEMOVE: ev = UiEv::Move; break;
    case WM_LBUTTONDOWN: case WM_LBUTTONDBLCLK: ev = UiEv::Down; button = 0; down = true; if (InterlockedIncrement(&s_wmLButton) == 1) LOGI("ui: input: first WM_LBUTTONDOWN through the window procedure"); break;
    case WM_RBUTTONDOWN: case WM_RBUTTONDBLCLK: ev = UiEv::Down; button = 1; down = true; break;
    case WM_MBUTTONDOWN: case WM_MBUTTONDBLCLK: ev = UiEv::Down; button = 2; down = true; break;
    case WM_LBUTTONUP: ev = UiEv::Up; button = 0; break;
    case WM_RBUTTONUP: ev = UiEv::Up; button = 1; break;
    case WM_MBUTTONUP: ev = UiEv::Up; button = 2; break;
    case WM_MOUSEWHEEL: ev = UiEv::Wheel; break;
    case WM_KEYDOWN: case WM_KEYUP: case WM_SYSKEYDOWN: case WM_SYSKEYUP: ev = UiEv::Key; break;
    case WM_CHAR: ev = UiEv::Char; break;
    case WM_ACTIVATEAPP: { Lock l; s_route.engineButtons = 0; s_route.rmlButtons = 0; } return Engine(h, msg, wp, lp);   // a release lost to alt-tab
    default: return Engine(h, msg, wp, lp);
    }
    UiRoute r; bool leave = false;
    {
        Lock l;
        const bool live = s_ctx && AnyVisible();
        if (live && (ev == UiEv::Move || ev == UiEv::Down || ev == UiEv::Up || ev == UiEv::Wheel)) {
            int x, y;
            if (ev == UiEv::Wheel) { POINT p{ LpX(lp), LpY(lp) }; ScreenToClient(h, &p); x = p.x; y = p.y; } else { x = LpX(lp); y = LpY(lp); }
            ToBackbuffer(x, y);
            s_ctx->ProcessMouseMove(x, y, Mods());   // a click or wheel can arrive with no move before it
            Sense();
        } else if (!live) { s_route.hoverInteractive = s_route.overScrollable = s_route.textFocus = false; }
        r = UiDecide(ev, button, s_route, s_rmlOwner);
        if (!live) r.to &= (uint8_t)~kToRml;   // no document: nothing for RmlUi (the idle host passes everything on)
        if (live && (r.to & kToRml)) {
            switch (ev) {
            case UiEv::Down: s_ctx->ProcessMouseButtonDown(button, Mods()); break;
            case UiEv::Up: { const std::string before = s_clicks.last; s_ctx->ProcessMouseButtonUp(button, Mods()); if (s_clicks.last != before) LOGI("ui: counted click: %s", s_clicks.last.c_str()); } break;
            case UiEv::Wheel: s_ctx->ProcessMouseWheel(Rml::Vector2f(0.f, -(float)GET_WHEEL_DELTA_WPARAM(wp) / WHEEL_DELTA), Mods()); break;
            case UiEv::Key: if (msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN) s_ctx->ProcessKeyDown(Key(wp), Mods()); else s_ctx->ProcessKeyUp(Key(wp), Mods()); break;
            case UiEv::Char: if (wp >= 32) s_ctx->ProcessTextInput((Rml::Character)wp); break;
            default: break;
            }
        }
        leave = r.engineLeave;
        s_rmlOwner = UiRmlOwnsPointer(s_route);
        Count(ev, r.to);
        (void)down;
    }
    if (leave) Engine(h, WM_MOUSEMOVE, 0, MAKELPARAM((WORD)(short)-30000, (WORD)(short)-30000));   // hand-over: the engine's hover clears
    if (r.to & kToEngine) return Engine(h, msg, wp, lp);
    return 0;   // RmlUi took it
}

// ---- input: DirectInput (the mouse and keyboard devices' vtables) -----------------------------------------------------------------
const GUID kSysMouse = { 0x6F1D2B60, 0xD5A0, 0x11CF, { 0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00 } };
const GUID kSysKeyboard = { 0x6F1D2B61, 0xD5A0, 0x11CF, { 0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00 } };
struct DiData { DWORD ofs, data, time, seq; UINT_PTR app; };
void* s_diMouse = nullptr; void* s_diKeyboard = nullptr;
using PFN_DI8Create = HRESULT(WINAPI*)(HINSTANCE, DWORD, REFIID, void**, void*);
using PFN_DICreateDevice = HRESULT(WINAPI*)(void*, REFGUID, void**, void*);
using PFN_DIState = HRESULT(WINAPI*)(void*, DWORD, void*);
using PFN_DIData = HRESULT(WINAPI*)(void*, DWORD, DiData*, DWORD*, DWORD);
PFN_DI8Create o_DI8Create; PFN_DICreateDevice o_DICreateDevice; PFN_DIState o_DIState; PFN_DIData o_DIData;

HRESULT WINAPI hk_DIState(void* dev, DWORD cb, void* data) {
    const HRESULT hr = o_DIState(dev, cb, data);
    if (FAILED(hr) || !data) return hr;
    const UiRouteState s = s_route;   // a copy: the window thread owns the decisions
    if (dev == s_diMouse && cb >= 16) {
        InterlockedIncrement(&s_diStateReads);
        BYTE* b = (BYTE*)data + 12; const DWORD n = cb - 12;
        unsigned mask = 0; for (DWORD i = 0; i < n && i < 8; ++i) if (b[i] & 0x80) mask |= 1u << i;
        if (mask && mask != s_diMouseBtnPrev && InterlockedIncrement(&s_diStateButtons) == 1) LOGI("ui: input: first DirectInput mouse button (GetDeviceState)");
        s_diMouseBtnPrev = mask;
        if (UiBlankDiButtons(s)) memset(b, 0, n);
        if (UiBlankDiWheel(s)) ((LONG*)data)[2] = 0;
    } else if (dev == s_diKeyboard && cb == 256 && s.textFocus) memset(data, 0, cb);
    return hr;
}
HRESULT WINAPI hk_DIData(void* dev, DWORD cbObj, DiData* rg, DWORD* inOut, DWORD flags) {
    const HRESULT hr = o_DIData(dev, cbObj, rg, inOut, flags);
    if (FAILED(hr) || !rg || !inOut || (flags & 1 /* DIGDD_PEEK */) || cbObj < sizeof(DWORD) * 2) return hr;
    const UiRouteState s = s_route;
    for (DWORD i = 0; i < *inOut; ++i) {
        DiData* e = (DiData*)((BYTE*)rg + (size_t)i * cbObj);
        if (dev == s_diMouse) {
            InterlockedIncrement(&s_diDataReads);
            const bool btn = e->ofs >= 12 && e->ofs < 20, wheel = e->ofs == 8;
            if (btn && (e->data & 0x80) && InterlockedIncrement(&s_diDataButtons) == 1) LOGI("ui: input: first DirectInput mouse button (GetDeviceData)");
            if ((btn && UiBlankDiButtons(s)) || (wheel && UiBlankDiWheel(s))) memset(e, 0, cbObj);
        } else if (dev == s_diKeyboard && s.textFocus) memset(e, 0, cbObj);
    }
    return hr;
}
HRESULT WINAPI hk_DICreateDevice(void* di, REFGUID g, void** out, void* outer) {
    const HRESULT hr = o_DICreateDevice(di, g, out, outer);
    if (SUCCEEDED(hr) && out && *out) {
        const bool mouse = IsEqualGUID(g, kSysMouse), kb = IsEqualGUID(g, kSysKeyboard);
        if (mouse) s_diMouse = *out;
        if (kb) s_diKeyboard = *out;
        if (mouse || kb) {
            void** vt = *(void***)*out;
            VtableHook(vt, 9, (void*)hk_DIState, o_DIState ? nullptr : (void**)&o_DIState, "IDirectInputDevice8::GetDeviceState (ui)");
            VtableHook(vt, 10, (void*)hk_DIData, o_DIData ? nullptr : (void**)&o_DIData, "IDirectInputDevice8::GetDeviceData (ui)");
            LOGI("ui: DirectInput %s device %p", mouse ? "mouse" : "keyboard", *out);
        }
    }
    return hr;
}
HRESULT WINAPI hk_DI8Create(HINSTANCE inst, DWORD ver, REFIID iid, void** out, void* outer) {
    const HRESULT hr = o_DI8Create(inst, ver, iid, out, outer);
    if (SUCCEEDED(hr) && out && *out) VtableHook(*(void***)*out, 3, (void*)hk_DICreateDevice, o_DICreateDevice ? nullptr : (void**)&o_DICreateDevice, "IDirectInput8::CreateDevice (ui)");
    return hr;
}
bool s_diHooked = false;
void HookDirectInput() {
    if (s_diHooked) return;
    const int n = IatHook(GetModuleHandleW(nullptr), "dinput8.dll", "DirectInput8Create", (void*)hk_DI8Create, (void**)&o_DI8Create);
    s_diHooked = n != -1;
    if (n == 0) LOGW("ui: the exe does not import DirectInput8Create: window messages only");
}

std::string CostJson(const char* name, std::vector<double> v) {
    const UiCost c = UiCostOf(std::move(v));
    char b[200]; snprintf(b, sizeof b, "\"%s\": {\"n\": %zu, \"p50\": %.4f, \"p99\": %.4f, \"max\": %.4f}", name, c.n, c.p50, c.p99, c.max);
    return b;
}

std::string StateJson(double windowS, double since) {
    Lock l;
    std::string j;
    char b[1024];
    const char* life = s_life.state == UiLife::Ready ? "ready" : s_life.state == UiLife::Lost ? "lost" : s_life.state == UiLife::Off ? "off" : "no_device";
    snprintf(b, sizeof b, "\"ui\": {\"enabled\": %s, \"life\": \"%s\", \"off_why\": \"%s\", \"backend\": \"%s\", \"device\": \"%p\", \"backbuffer\": [%d, %d], \"scale\": %d, \"dp_ratio\": %.4f, "
             "\"threads\": {\"present\": %lu, \"window\": %lu}, \"lua\": {\"up\": %s, \"why\": \"%s\", \"mem_kb\": %.1f}, \"rml_log\": {\"warnings\": %ld, \"errors\": %ld}, "
             "\"presents\": %llu, \"frames_drawn\": %llu, \"draws_last_frame\": %u",
             s_on ? "true" : "false", life, JEsc(s_offWhy).c_str(), BackendName(), (void*)s_dev, s_bbW, s_bbH, s_scale, s_dp, s_presentTid, s_wndTid,
             UiLuaUp() ? "true" : "false", JEsc(s_luaWhy).c_str(), UiLuaMemKb(), (long)s_rmlWarn, (long)s_rmlErr,
             (unsigned long long)s_presents, (unsigned long long)s_framesDrawn, s_lastDraws);
    j += b;
    j += ", \"documents\": [";
    bool first = true;
    for (auto& kv : s_docs) { j += std::string(first ? "" : ", ") + "{\"name\": \"" + JEsc(kv.first) + "\", \"visible\": " + (kv.second.visible ? "true" : "false") + "}"; first = false; }
    j += "], \"counters\": {"; first = true;
    for (auto& kv : s_clicks.counts) { j += std::string(first ? "" : ", ") + "\"" + JEsc(kv.first) + "\": " + std::to_string(kv.second); first = false; }
    j += "}";
    std::string hov = "";
    if (s_ctx) if (Rml::Element* e = s_ctx->GetHoverElement()) hov = e->GetTagName() + (e->GetId().empty() ? "" : "#" + e->GetId());
    j += ", \"hovered\": \"" + JEsc(hov) + "\"";
    snprintf(b, sizeof b, ", \"route_state\": {\"hover_interactive\": %s, \"over_scrollable\": %s, \"text_focus\": %s, \"engine_buttons\": %u, \"rml_buttons\": %u, \"rml_owns_pointer\": %s}",
             s_route.hoverInteractive ? "true" : "false", s_route.overScrollable ? "true" : "false", s_route.textFocus ? "true" : "false", s_route.engineButtons, s_route.rmlButtons, s_rmlOwner ? "true" : "false");
    j += b;
    j += ", \"routing\": {";
    for (int e = 0; e < 6; ++e) {
        snprintf(b, sizeof b, "%s\"%s\": {\"rml\": %lld, \"engine\": %lld}", e ? ", " : "", UiEvName((UiEv)e), (long long)s_cnt[e][0], (long long)s_cnt[e][1]);
        j += b;
    }
    snprintf(b, sizeof b, "}, \"input_paths\": {\"wm_lbuttondown\": %ld, \"di_mouse\": %s, \"di_keyboard\": %s, \"di_state_reads\": %ld, \"di_state_button_presses\": %ld, \"di_data_reads\": %ld, \"di_data_button_presses\": %ld}",
             (long)s_wmLButton, s_diMouse ? "true" : "false", s_diKeyboard ? "true" : "false", (long)s_diStateReads, (long)s_diStateButtons, (long)s_diDataReads, (long)s_diDataButtons);
    j += b;
    std::vector<double> upd, rnd, hook, drawnHook; unsigned maxDraws = 0;
    for (const Sample& s : s_samples) {
        if (s.t < since) continue;
        hook.push_back(s.hook);
        if (s.draws || s.upd > 0) { upd.push_back(s.upd); rnd.push_back(s.rnd); drawnHook.push_back(s.hook); if (s.draws > maxDraws) maxDraws = s.draws; }
    }
    snprintf(b, sizeof b, ", \"cost_ms\": {\"window_s\": %.1f, ", windowS); j += b;
    j += CostJson("update", upd) + ", " + CostJson("render", rnd) + ", " + CostJson("hook_all_presents", hook) + ", " + CostJson("hook_drawn", drawnHook);
    snprintf(b, sizeof b, ", \"max_draws\": %u}}", maxDraws); j += b;
    return j;
}

bool SendInput(UINT msg, WPARAM wp, LPARAM lp, double timeoutS) {
    DWORD_PTR res = 0;
    return SendMessageTimeoutW(s_hwnd, msg, wp, lp, SMTO_ABORTIFHUNG, (UINT)(timeoutS * 1000), &res) != 0;
}

} // namespace

bool UiEnabled() { return s_on; }

void UiInit() {
    Runtime& rt = Rt();
    K.enabled = rt.cfg.Bool("ui.enabled");
    if (!K.enabled) return;   // release: nothing hooked, loaded or allocated
    if (!rt.plan.d3dHooks) { LOGW("ui: ui.enabled=1 but the plan forbids D3D hooks (pass-through): UI off"); return; }
    const UiScale s = UiClampScale(rt.cfg.Int("ui.scale"));
    if (s.changed) LOGW("ui: ui.scale=%ld is outside 85-125 or off the 5 %% grid: using %d", rt.cfg.Int("ui.scale"), s.percent);
    K.scale = s.percent; s_scale = s.percent;
    K.dir = WidenUtf8(rt.cfg.Str("ui.dir")); K.dumpDir = WidenUtf8(rt.cfg.Str("ui.dump_dir")); K.show = rt.cfg.Str("ui.show");
    if (K.dir.empty()) { LOGW("ui: ui.dir is empty: UI off"); return; }
    InitializeCriticalSection(&s_cs);
    QueryPerformanceFrequency(&s_qpf);
    s_reqDone = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    s_samples.reserve(kSamples);
    s_on = true;
    HookDirectInput();
    LOGI("ui: enabled: dir '%ls', scale %d, show '%s', dump_dir '%ls'", K.dir.c_str(), K.scale, K.show.c_str(), K.dumpDir.c_str());
}

void UiOnDirect3DCreate(void* d3d) {
    if (!s_on || !d3d) return;
    HookDirectInput();   // deferred when the slot was not snapped at DllMain
    if (!o_CreateDevice || *(void**)(*(void***)d3d + 16) != (void*)hk_CreateDevice)
        VtableHook(*(void***)d3d, 16, (void*)hk_CreateDevice, o_CreateDevice ? nullptr : (void**)&o_CreateDevice, "IDirect3D9::CreateDevice (ui)");
}

bool UiCtl(const std::string& arg, double timeoutS, std::string& result, std::string& why) {
    if (!s_on) { why = "ui.enabled is off (or the plan forbids D3D hooks)"; return false; }
    const UiArgs a = ParseUiArgs(arg);
    if (!a.error.empty()) { why = a.error; return false; }
    if (a.op == "state") {
        const double t0 = MonoS();
        if (a.seconds > 0) Sleep((DWORD)(a.seconds * 1000));
        result = StateJson(a.seconds > 0 ? a.seconds : 5.0, a.seconds > 0 ? t0 : MonoS() - 5.0);
        return true;
    }
    if (a.op == "click" || a.op == "wheel") {
        if (!s_hwnd) { why = "no game window yet"; return false; }
        // client coordinates = back-buffer coordinates on a headless launch; the same messages real input sends, through the subclass
        const LPARAM lp = MAKELPARAM((WORD)(short)a.x, (WORD)(short)a.y);
        LONG64 before[6][2]; for (int e = 0; e < 6; ++e) for (int k = 0; k < 2; ++k) before[e][k] = s_cnt[e][k];
        bool ok = SendInput(WM_MOUSEMOVE, 0, lp, timeoutS);
        if (a.op == "wheel") {
            POINT p{ a.x, a.y }; ClientToScreen(s_hwnd, &p);
            ok = ok && SendInput(WM_MOUSEWHEEL, MAKEWPARAM(0, (WORD)(short)(-a.delta * WHEEL_DELTA)), MAKELPARAM((WORD)(short)p.x, (WORD)(short)p.y), timeoutS);
        } else if (a.phase != "move") {
            const UINT dn[3] = { WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN }, up[3] = { WM_LBUTTONUP, WM_RBUTTONUP, WM_MBUTTONUP };
            const WPARAM mk[3] = { MK_LBUTTON, MK_RBUTTON, MK_MBUTTON };
            if (a.phase == "click" || a.phase == "down") ok = ok && SendInput(dn[a.button], mk[a.button], lp, timeoutS);
            if (a.phase == "click" || a.phase == "up") ok = ok && SendInput(up[a.button], 0, lp, timeoutS);
        }
        if (!ok) { why = "the window did not take the messages within the timeout"; return false; }
        std::string d = "\"delta\": {";
        for (int e = 0; e < 6; ++e) {
            char b[96]; snprintf(b, sizeof b, "%s\"%s\": [%lld, %lld]", e ? ", " : "", UiEvName((UiEv)e), (long long)(s_cnt[e][0] - before[e][0]), (long long)(s_cnt[e][1] - before[e][1]));
            d += b;
        }
        d += "}";
        result = d + ", " + StateJson(0, MonoS());
        return true;
    }
    // show, hide, reload, scale, dump: the next Present runs it
    Req r; r.a = a;
    { Lock l; if (s_req) { why = "another ui request is waiting"; return false; } s_req = &r; ResetEvent(s_reqDone); }
    if (WaitForSingleObject(s_reqDone, (DWORD)(timeoutS * 1000)) != WAIT_OBJECT_0) {
        Lock l;
        if (s_req == &r) { s_req = nullptr; why = "no Present within the timeout"; return false; }
    }
    if (!r.ok) { why = r.why; return false; }
    result = r.result;
    return true;
}

} // namespace wsp
