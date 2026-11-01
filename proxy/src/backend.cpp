// backend.cpp - the proxy's d3d9 exports, forwarded to the configured backend (ported from empire-remastered rml_mod/src/proxy.cpp).
// proxy.backend:
//   dxvk   -> DXVK's 32-bit d3d9.dll (stock release, pinned: proxy/tools/fetch_dxvk.py), shipped renamed as proxy.dxvk_path
//             (default <mod>\dxvk\d3d9_dxvk.dll) because the proxy owns the d3d9.dll name. DXVK's own files (dxvk.conf, its log,
//             its caches) are pointed into <mod>\dxvk\ through its environment variables unless the user set them: by default DXVK
//             writes <exe>_d3d9.log and caches into the WORKING folder (the game folder), which would break the byte-exact uninstall.
//   system -> %SystemRoot%\System32\d3d9.dll (WOW64 redirects a 32-bit process to SysWOW64).
// Missing or failing DXVK falls back to the system d3d9 with a warning. The backend is loaded at the first export call, never
// from DllMain (LoadLibrary under the loader lock). The backend is not engine memory: it loads in pass-through too.
// No D3D hook is installed here yet; when a feature adds one it must ask Rt().plan.d3dHooks (guard.h PlanEngine).
#include "runtime.h"

namespace wsp {
namespace {
HMODULE s_real = nullptr;
const char* s_name = "none";
INIT_ONCE s_once = INIT_ONCE_STATIC_INIT;

using PFN_Create9   = void* (WINAPI*)(UINT);
using PFN_Create9Ex = HRESULT (WINAPI*)(UINT, void**);
using PFN_Begin     = int (WINAPI*)(DWORD, LPCWSTR);
using PFN_End       = int (WINAPI*)(void);
using PFN_Marker    = void (WINAPI*)(DWORD, LPCWSTR);
using PFN_Query     = BOOL (WINAPI*)(void);
using PFN_Options   = void (WINAPI*)(DWORD);
using PFN_Status    = DWORD (WINAPI*)(void);
PFN_Create9 p_Create9; PFN_Create9Ex p_Create9Ex; PFN_Begin p_Begin; PFN_End p_End; PFN_Marker p_SetMarker, p_SetRegion;
PFN_Query p_Query; PFN_Options p_Options; PFN_Status p_Status;

template <class T> T Resolve(const char* name) {
    T p = reinterpret_cast<T>(reinterpret_cast<void*>(GetProcAddress(s_real, name)));
    if (!p) LOGW("backend: %s d3d9 lacks %s", s_name, name);
    return p;
}

void SetEnvDefault(const wchar_t* name, const std::wstring& value) {
    wchar_t cur[8]; const DWORD n = GetEnvironmentVariableW(name, cur, 8);
    if (n != 0 || GetLastError() != ERROR_ENVVAR_NOT_FOUND) { LOGI("backend: %ls already set by the environment, left alone", name); return; }
    SetEnvironmentVariableW(name, value.c_str());
    LOGI("backend: %ls=%ls", name, value.c_str());
}

std::wstring Widen(const std::string& s) {
    if (s.empty()) return {};
    const int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0);
    std::wstring w(n, L'\0'); MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), &w[0], n);
    return w;
}

HMODULE LoadSystem() {
    wchar_t path[MAX_PATH];
    const UINT n = GetSystemDirectoryW(path, MAX_PATH);
    if (!n || n > MAX_PATH - 12) return nullptr;
    lstrcatW(path, L"\\d3d9.dll");
    HMODULE h = LoadLibraryW(path);
    if (!h) { LOGE("backend: LoadLibrary(%ls) failed: %lu", path, GetLastError()); return nullptr; }
    s_name = "system";
    LOGI("backend: system d3d9 loaded from %ls", path);
    return h;
}

HMODULE LoadDxvk() {
    const Runtime& rt = Rt();
    std::wstring path = Widen(rt.cfg.Str("proxy.dxvk_path"));
    const bool absolute = path.size() > 2 && (path[1] == L':' || (path[0] == L'\\' && path[1] == L'\\'));
    if (!absolute) path = rt.gameDir + path;
    if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) { LOGE("backend: dxvk requested but %ls does not exist", path.c_str()); return nullptr; }
    const std::wstring dir = rt.modDir + L"dxvk\\";
    CreateDirectoryW(dir.c_str(), nullptr);
    CreateDirectoryW((dir + L"cache").c_str(), nullptr);
    SetEnvDefault(L"DXVK_CONFIG_FILE", dir + L"dxvk.conf");
    SetEnvDefault(L"DXVK_LOG_PATH", dir);
    SetEnvDefault(L"DXVK_SHADER_CACHE_PATH", dir + L"cache");
    // No DXVK_STATE_CACHE_PATH: DXVK 2.7 removed the state cache (unused since VK_EXT_graphics_pipeline_library in 2.0), so the
    // pinned 3.1.1 never reads it (J3). DXVK_SHADER_CACHE_PATH stays: it is where DXVK puts the driver's pipeline cache.
    HMODULE h = LoadLibraryW(path.c_str());
    if (!h) { LOGE("backend: LoadLibrary(%ls) failed: %lu", path.c_str(), GetLastError()); return nullptr; }
    s_name = "dxvk";
    WIN32_FILE_ATTRIBUTE_DATA fad{}; GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &fad);
    LOGI("backend: dxvk d3d9 loaded from %ls (%lu bytes); DXVK's log and caches go to %ls", path.c_str(), fad.nFileSizeLow, dir.c_str());
    return h;
}

BOOL CALLBACK LoadOnce(PINIT_ONCE, PVOID, PVOID*) {
    const Runtime& rt = Rt();
    const std::string want = rt.enabled ? rt.cfg.Str("proxy.backend") : std::string("system");
    if (!rt.enabled) LOGI("backend: proxy disabled or second instance -> system d3d9");
    if (want == "dxvk") { s_real = LoadDxvk(); if (!s_real) LOGW("backend: dxvk unavailable, falling back to the system d3d9"); }
    else if (want != "system") LOGW("backend: unknown proxy.backend '%s' (system | dxvk), using system", want.c_str());
    if (!s_real) s_real = LoadSystem();
    if (!s_real) { LOGE("backend: no d3d9 could be loaded: the game cannot create a device"); return TRUE; }
    p_Create9 = Resolve<PFN_Create9>("Direct3DCreate9");
    p_Create9Ex = Resolve<PFN_Create9Ex>("Direct3DCreate9Ex");
    p_Begin = Resolve<PFN_Begin>("D3DPERF_BeginEvent");
    p_End = Resolve<PFN_End>("D3DPERF_EndEvent");
    p_SetMarker = Resolve<PFN_Marker>("D3DPERF_SetMarker");
    p_SetRegion = Resolve<PFN_Marker>("D3DPERF_SetRegion");
    p_Query = Resolve<PFN_Query>("D3DPERF_QueryRepeatFrame");
    p_Options = Resolve<PFN_Options>("D3DPERF_SetOptions");
    p_Status = Resolve<PFN_Status>("D3DPERF_GetStatus");
    LOGI("backend: %s ready (Direct3DCreate9=%p)", s_name, (void*)p_Create9);
    return TRUE;
}
} // namespace

bool BackendEnsure() { InitOnceExecuteOnce(&s_once, LoadOnce, nullptr, nullptr); return s_real != nullptr; }
const char* BackendName() { return s_name; }

} // namespace wsp

using namespace wsp;

namespace {
volatile LONG s_filterChecked = 0;
// The game installs its own handlers during start-up; by its first Direct3DCreate9 that is done, so this is where a replaced
// top-level filter shows (J1 review finding 5).
void FirstCreateChecks() {
    if (!InterlockedExchange(&s_filterChecked, 1)) CrashCheckFilter("first Direct3DCreate9");
    else if (Rt().enabled) CrashFlushPending();   // the game recreates its d3d9 object on a resolution change: a deferred record shows here
}
}

extern "C" {

void* WINAPI Direct3DCreate9(UINT sdk) {
    FirstCreateChecks();
    if (!BackendEnsure() || !p_Create9) return nullptr;
    void* d3d = p_Create9(sdk);
    LOGI("Direct3DCreate9(sdk=%u) -> %p [%s]", sdk, d3d, BackendName());
    HeadlessOnDirect3DCreate(d3d);   // headless only: target, mode-list and device hooks (before the dev side wraps CreateDevice)
    DevOnDirect3DCreate(d3d);   // dev side only (frame hooks ask the plan inside)
    return d3d;
}

HRESULT WINAPI Direct3DCreate9Ex(UINT sdk, void** out) {
    FirstCreateChecks();
    if (!BackendEnsure()) return E_FAIL;
    if (!p_Create9Ex) return E_NOTIMPL;
    const HRESULT hr = p_Create9Ex(sdk, out);
    LOGI("Direct3DCreate9Ex(sdk=%u) -> hr=0x%08lx [%s]", sdk, (unsigned long)hr, BackendName());
    if (SUCCEEDED(hr) && out) HeadlessOnDirect3DCreate(*out);   // IDirect3D9Ex keeps IDirect3D9's slots
    return hr;
}

int   WINAPI D3DPERF_BeginEvent(DWORD c, LPCWSTR n) { CaptureEvent(0, n); return BackendEnsure() && p_Begin ? p_Begin(c, n) : 0; }
int   WINAPI D3DPERF_EndEvent(void)                 { CaptureEvent(1, nullptr); return BackendEnsure() && p_End ? p_End() : 0; }
void  WINAPI D3DPERF_SetMarker(DWORD c, LPCWSTR n)  { CaptureEvent(2, n); if (BackendEnsure() && p_SetMarker) p_SetMarker(c, n); }
void  WINAPI D3DPERF_SetRegion(DWORD c, LPCWSTR n)  { if (BackendEnsure() && p_SetRegion) p_SetRegion(c, n); }
BOOL  WINAPI D3DPERF_QueryRepeatFrame(void)         { return BackendEnsure() && p_Query ? p_Query() : FALSE; }
void  WINAPI D3DPERF_SetOptions(DWORD o)            { if (BackendEnsure() && p_Options) p_Options(o); }
DWORD WINAPI D3DPERF_GetStatus(void)                { return BackendEnsure() && p_Status ? p_Status() : 0; }

} // extern "C"
