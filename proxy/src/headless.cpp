// headless.cpp - headless runs (J13): every game window on the virtual display, never on a real monitor, fail closed. The decisions
// are pure functions in display_guard.h; this file gathers the observations and applies the actions. Game-agnostic (it moves to
// warscape-core); proxy/README.md "Headless" is the owner doc.
//
// Mechanism, in launch order:
//   DllMain (HeadlessInit)    headless.enabled read; refused when the guard's plan forbids hooks; IAT hooks on the exe's user32
//                             imports for window creation, show, move, style, display-mode changes and dialogs.
//   first Direct3DCreate9 or the first game window (Ensure)  the monitor list logged, the target resolved by name + exact size (or
//                             refusal), the guard thread started (never from DllMain); IDirect3D9 vtable hooks: the mode queries
//                             answer from the target's modes on every adapter, CreateDevice/Reset refuse a back buffer that is not
//                             the target's size or a fullscreen device.
//   window creation           top-level windows are created hidden, borderless, non-activating, then placed on the target and
//                             shown with SW_SHOWNA; their geometry belongs to the guard from then on.
//   every Present             post-check (a window visible off the target is cloaked), pending relocation, the on_virtual status.
//   guard thread (~4 ms)      virtual-screen metrics, the target's live rect, the layout signature -> Decide: cloak first,
//                             re-resolve, move, verify, uncloak after a quiet settle; no target for refuse_grace_ms -> refusal.
// Refusal: every window of the process cloaked and hidden, headless_status.json state refused, exit code dg::kRefuseExitCode.
#include "runtime.h"
#include "display_guard.h"
#include <set>

// constants newer than the mingw headers guarantee (winuser.h / dwmapi.h / dbt.h values)
#ifndef WM_DPICHANGED
#define WM_DPICHANGED 0x02E0
#endif
namespace { const DWORD kDwmCloak = 13; const WPARAM kDbtNodes = 0x0007, kDbtArrival = 0x8000, kDbtRemoved = 0x8004; }

namespace wsp {

using namespace dg;

static_assert(WS_CHILD == kWsChild && WS_VISIBLE == kWsVisible && WS_POPUP == kWsPopup && WS_CAPTION == kWsCaption && WS_THICKFRAME == kWsThickFrame,
              "winuser.h values");
static_assert(WS_EX_NOACTIVATE == kWsExNoActivate && WS_EX_TOOLWINDOW == kWsExToolWindow && WS_EX_APPWINDOW == kWsExAppWindow, "winuser.h values");
static_assert(SWP_NOSIZE == kSwpNoSize && SWP_NOMOVE == kSwpNoMove && SWP_NOACTIVATE == kSwpNoActivate && SWP_SHOWWINDOW == kSwpShowWindow &&
              SWP_HIDEWINDOW == kSwpHideWindow && SWP_ASYNCWINDOWPOS == kSwpAsync, "winuser.h values");
static_assert(SW_HIDE == kSwHide && SW_SHOWNA == kSwShowNA && SW_MINIMIZE == kSwMinimize, "winuser.h values");

namespace {

// ---- state (s_cs) -----------------------------------------------------------------------------------------------------------------
CRITICAL_SECTION s_cs;
struct Lock { Lock() { EnterCriticalSection(&s_cs); } ~Lock() { LeaveCriticalSection(&s_cs); } };
bool s_on = false;                      // headless.enabled and running
long s_w = 0, s_h = 0;                  // headless.size: the wanted back buffer = the target's size
std::string s_name;                     // headless.display_name
unsigned s_settleMs = 500, s_graceMs = 5000;
Status s_st;                            // headless_status.json
volatile LONG s_ensured = 0, s_refusing = 0;
double s_t0 = 0;

struct Target { Monitor m; HMONITOR hmon = nullptr; std::vector<Mode> modes; Mode cur; };
Target s_t;                             // the last resolved target
bool s_targetKnown = false;             // false while a change is being re-resolved
HWND s_main = nullptr;                  // the game's main window (first guarded window; confirmed by CreateDevice)
std::set<HWND> s_wins;                  // every guarded top-level window
WNDPROC s_next = nullptr;               // the main window's procedure under ours
bool s_cloaked = false, s_hiddenByGuard = false, s_pending = false, s_placed = false, s_haveWindow = false, s_device = false;
uint64_t s_layoutAt = 0, s_metricsAt = 0;
double s_lastTrigger = -1e9, s_noTargetSince = -1;
DWORD s_ownMoveThread = 0;              // the thread inside the guard's own SetWindowPos (its WM_WINDOWPOSCHANGING passes)
OwnMove s_ownMove;                      // the main window's last placement by the guard, matched by rect on any thread (IsOwnMove)
long s_frames = 0;
// PC test hooks (J12, dev only, release 0): off_thread moves every relocation to the guard thread, which does not own the window, so the
// guard's move is asynchronous as in a game that presents from a worker thread (fix 1a); dll_window_ms shows a window this many ms
// after start-up from a thread of the proxy's own, through its own user32 import, as a DLL's dialog would appear (fix 1b).
bool s_testOffThread = false;
unsigned s_testDllWindowMs = 0;
int s_logBudget = 40;                   // per-call log lines (gated calls) before only counting
long s_geomDropped = 0;

// ---- hooked user32 imports of the exe ---------------------------------------------------------------------------------------------
using PFN_CreateWindowExW = HWND(WINAPI*)(DWORD, LPCWSTR, LPCWSTR, DWORD, int, int, int, int, HWND, HMENU, HINSTANCE, LPVOID);
using PFN_ShowWindow = BOOL(WINAPI*)(HWND, int);
using PFN_SetWindowPos = BOOL(WINAPI*)(HWND, HWND, int, int, int, int, UINT);
using PFN_MoveWindow = BOOL(WINAPI*)(HWND, int, int, int, int, BOOL);
using PFN_SetWindowLongW = LONG(WINAPI*)(HWND, int, LONG);
using PFN_ChangeDisplaySettingsW = LONG(WINAPI*)(DEVMODEW*, DWORD);
using PFN_MessageBoxW = int(WINAPI*)(HWND, LPCWSTR, LPCWSTR, UINT);
using PFN_DialogBoxIndirectParamW = INT_PTR(WINAPI*)(HINSTANCE, LPCDLGTEMPLATEW, HWND, DLGPROC, LPARAM);
using PFN_SetFocus = HWND(WINAPI*)(HWND);
PFN_CreateWindowExW o_CreateWindowExW; PFN_ShowWindow o_ShowWindow; PFN_SetWindowPos o_SetWindowPos; PFN_MoveWindow o_MoveWindow;
PFN_SetWindowLongW o_SetWindowLongW; PFN_ChangeDisplaySettingsW o_ChangeDisplaySettingsW; PFN_MessageBoxW o_MessageBoxW;
PFN_DialogBoxIndirectParamW o_DialogBoxIndirectParamW; PFN_SetFocus o_SetFocus;

struct IatSpec { const char* name; void* detour; void** original; bool essential; int state; const char* dll = "user32.dll"; };   // state: 1 hooked, -1 deferred, 0 missing
std::vector<IatSpec>& Iats();

// ---- small helpers ----------------------------------------------------------------------------------------------------------------
// Per-monitor-DPI-aware V2 around every query and move: physical pixels whatever the exe's own awareness is.
using PFN_SetThreadDpiCtx = HANDLE(WINAPI*)(HANDLE);   // SetThreadDpiAwarenessContext (Windows 10 1607+)
const HANDLE kDpiPerMonitorV2 = (HANDLE)(LONG_PTR)-4, kDpiPerMonitor = (HANDLE)(LONG_PTR)-3;
PFN_SetThreadDpiCtx DpiFn() {
    static PFN_SetThreadDpiCtx f = (PFN_SetThreadDpiCtx)(void*)GetProcAddress(GetModuleHandleW(L"user32.dll"), "SetThreadDpiAwarenessContext");
    return f;
}
struct DpiScope {
    HANDLE prev = nullptr;
    DpiScope() { if (auto f = DpiFn()) { prev = f(kDpiPerMonitorV2); if (!prev) prev = f(kDpiPerMonitor); } }
    ~DpiScope() { if (prev) DpiFn()(prev); }
};
Rect FromRECT(const RECT& r) { return Rect{ r.left, r.top, r.right, r.bottom }; }
Rect WinRect(HWND h) { DpiScope d; RECT r{}; GetWindowRect(h, &r); return FromRECT(r); }
bool Guarded(HWND h) { Lock l; return s_wins.count(h) != 0; }
std::string Utf8(const wchar_t* w) { return w ? Narrow(w) : std::string(); }
double Uptime() { return MonoS() - s_t0; }
bool Budget() { Lock l; return s_logBudget > 0 ? (--s_logBudget, true) : false; }

void WriteStatus() {   // s_cs held
    s_st.pid = GetCurrentProcessId(); s_st.launchId = Rt().launchId;
    SYSTEMTIME t; GetSystemTime(&t); char b[40];
    snprintf(b, sizeof b, "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    s_st.utc = b;
    s_st.haveTarget = !s_t.m.device.empty(); s_st.target = s_t.m;
    if (!WriteFileAtomic(Rt().modDir + L"headless_status.json", StatusJson(s_st))) LOGW("headless: could not write headless_status.json (%lu)", GetLastError());
}

// ---- DWM cloak (the fallback is SW_HIDE, shown again on uncloak) ---------------------------------------------------------------------
using PFN_DwmSet = HRESULT(WINAPI*)(HWND, DWORD, LPCVOID, DWORD);
PFN_DwmSet DwmFn() {
    static PFN_DwmSet f = [] { HMODULE m = LoadLibraryW(L"dwmapi.dll"); return m ? (PFN_DwmSet)(void*)GetProcAddress(m, "DwmSetWindowAttribute") : nullptr; }();
    return f;
}
bool CloakWindow(HWND h, bool on) {
    BOOL v = on ? TRUE : FALSE;
    auto f = DwmFn();
    return f && SUCCEEDED(f(h, kDwmCloak, &v, sizeof v));
}
void CloakLocked(const char* why) {
    if (s_cloaked) return;
    s_cloaked = true;
    for (HWND h : s_wins) {
        if (!CloakWindow(h, true) && IsWindowVisible(h)) { ShowWindowAsync(h, SW_HIDE); s_hiddenByGuard = true; LOGW("headless: DWM cloak failed: window %p hidden instead", (void*)h); }
    }
    LOGW("headless: CLOAKED (%s) at %.3f s", why, Uptime());
}
void UncloakLocked(const char* why) {
    if (!s_cloaked) return;
    s_cloaked = false;
    for (HWND h : s_wins) CloakWindow(h, false);
    if (s_hiddenByGuard && s_main) { ShowWindowAsync(s_main, SW_SHOWNA); s_hiddenByGuard = false; }
    LOGI("headless: uncloaked (%s) at %.3f s", why, Uptime());
}

// ---- monitors ---------------------------------------------------------------------------------------------------------------------
struct MonEnum { std::vector<Monitor>* out; std::vector<HMONITOR>* hs; bool names; };
BOOL CALLBACK MonCb(HMONITOR hm, HDC, LPRECT, LPARAM lp) {
    auto* e = reinterpret_cast<MonEnum*>(lp);
    MONITORINFOEXW mi{}; mi.cbSize = sizeof mi;
    if (!GetMonitorInfoW(hm, &mi)) return TRUE;
    Monitor m; m.device = Narrow(mi.szDevice); m.rc = FromRECT(mi.rcMonitor); m.primary = (mi.dwFlags & MONITORINFOF_PRIMARY) != 0;
    if (e->names) {
        DISPLAY_DEVICEW dd{}; dd.cb = sizeof dd;
        for (DWORD i = 0; EnumDisplayDevicesW(nullptr, i, &dd, 0); ++i, dd.cb = sizeof dd)
            if (!lstrcmpiW(dd.DeviceName, mi.szDevice)) { m.adapter = Narrow(dd.DeviceString); break; }
        DISPLAY_DEVICEW md{}; md.cb = sizeof md;
        if (EnumDisplayDevicesW(mi.szDevice, 0, &md, 0)) m.monitor = Narrow(md.DeviceString);
        using PFN_GetDpi = HRESULT(WINAPI*)(HMONITOR, int, UINT*, UINT*);
        static PFN_GetDpi gd = [] { HMODULE s = LoadLibraryW(L"shcore.dll"); return s ? (PFN_GetDpi)(void*)GetProcAddress(s, "GetDpiForMonitor") : nullptr; }();
        UINT dx = 0, dy = 0; if (gd && SUCCEEDED(gd(hm, 0 /* MDT_EFFECTIVE_DPI */, &dx, &dy))) m.dpi = (int)dx;
    }
    e->out->push_back(m); if (e->hs) e->hs->push_back(hm);
    return TRUE;
}
std::vector<Monitor> ListMonitors(bool names, std::vector<HMONITOR>* hs = nullptr) {
    DpiScope d; std::vector<Monitor> v; MonEnum e{ &v, hs, names };
    EnumDisplayMonitors(nullptr, nullptr, MonCb, reinterpret_cast<LPARAM>(&e));
    return v;
}
uint64_t MetricsNow() {
    DpiScope d;
    return MetricsHash(GetSystemMetrics(SM_CMONITORS), GetSystemMetrics(SM_XVIRTUALSCREEN), GetSystemMetrics(SM_YVIRTUALSCREEN),
                       GetSystemMetrics(SM_CXVIRTUALSCREEN), GetSystemMetrics(SM_CYVIRTUALSCREEN));
}
bool LiveRect(Rect& out) {   // the target monitor's rect now
    if (!s_t.hmon) return false;
    DpiScope d; MONITORINFO mi{}; mi.cbSize = sizeof mi;
    if (!GetMonitorInfoW(s_t.hmon, &mi)) return false;
    out = FromRECT(mi.rcMonitor); return true;
}
uint64_t s_loggedLayout = 0;
// Resolve the target by name and exact size. s_cs held. false + why when there is none.
bool ResolveLocked(std::string& why) {
    std::vector<HMONITOR> hs;
    const std::vector<Monitor> ms = ListMonitors(true, &hs);
    const uint64_t lay = Layout(ms);
    if (lay != s_loggedLayout) {
        s_loggedLayout = lay;
        LOGI("headless: %zu displays (physical pixels):", ms.size());
        for (const Monitor& m : ms) LOGI("headless:   %s", MonitorLine(m).c_str());
    }
    const Pick p = SelectTarget(ms, s_name, s_w, s_h);
    if (p.index < 0) { why = p.why; return false; }
    Target t; t.m = ms[p.index]; t.hmon = hs[p.index];
    std::wstring dev = WidenUtf8(t.m.device);
    std::vector<Mode> raw;
    DEVMODEW dm{}; dm.dmSize = sizeof dm;
    for (DWORD i = 0; EnumDisplaySettingsW(dev.c_str(), i, &dm); ++i, dm.dmSize = sizeof dm)
        if (dm.dmBitsPerPel == 32) raw.push_back(Mode{ dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency });
    t.modes = ModeList(raw);
    dm = DEVMODEW{}; dm.dmSize = sizeof dm;
    if (EnumDisplaySettingsW(dev.c_str(), ENUM_CURRENT_SETTINGS, &dm)) t.cur = Mode{ dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency };
    const bool changed = s_t.m.device != t.m.device || !Same(s_t.m.rc, t.m.rc);
    s_t = t; s_targetKnown = true;
    if (changed) LOGI("headless: target %s (%s); modes %s; current %ux%u@%u", RectStr(t.m.rc).c_str(), p.why.c_str(), ModesStr(t.modes).c_str(), t.cur.w, t.cur.h, t.cur.hz);
    if (t.m.dpi && t.m.dpi != 96) LOGW("headless: the target is at %d DPI, not 96 (100 %%): the engine's window may be scaled", t.m.dpi);
    return true;
}

// ---- refusal ----------------------------------------------------------------------------------------------------------------------
BOOL CALLBACK HideCb(HWND h, LPARAM) {
    DWORD pid = 0; GetWindowThreadProcessId(h, &pid);
    if (pid == GetCurrentProcessId()) { CloakWindow(h, true); ShowWindowAsync(h, SW_HIDE); }
    return TRUE;
}
[[noreturn]] void Refuse(const std::string& why) {
    if (InterlockedExchange(&s_refusing, 1)) { Sleep(INFINITE); }   // another thread is already refusing: it terminates the process
    EnumWindows(HideCb, 0);
    LOGE("headless: REFUSED: %s", why.c_str());
    LOGE("headless: every window of the process hidden; exit code %d (proxy/README.md \"Headless\")", kRefuseExitCode);
    {   // the critical section is recursive: a caller holding it may refuse
        Lock l;
        s_st.state = "refused"; s_st.detail = why; s_st.exitCode = kRefuseExitCode;
        WriteStatus();
    }
    TerminateProcess(GetCurrentProcess(), kRefuseExitCode);
    for (;;) Sleep(INFINITE);
}

// ---- placement --------------------------------------------------------------------------------------------------------------------
// Move a guarded window onto the target (s_cs held). The main window covers the target exactly (borderless); another one keeps its
// size, at most the target's. Returns whether it is now wholly inside.
bool PlaceLocked(HWND h) {
    if (!s_targetKnown) return false;
    const Rect cur = WinRect(h), t = s_t.m.rc;
    const bool pin = h == s_main;
    const long w = pin || Width(cur) > Width(t) || Width(cur) <= 0 ? Width(t) : Width(cur);
    const long hh = pin || Height(cur) > Height(t) || Height(cur) <= 0 ? Height(t) : Height(cur);
    UINT fl = SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOOWNERZORDER;
    if (GetWindowThreadProcessId(h, nullptr) != GetCurrentThreadId()) fl |= SWP_ASYNCWINDOWPOS;   // never block on another thread
    {
        DpiScope d;
        s_ownMoveThread = GetCurrentThreadId();
        if (pin) { s_ownMove.armed = true; s_ownMove.want = R(t.l, t.t, w, hh); s_ownMove.at = MonoS(); }
        SetWindowPos(h, nullptr, t.l, t.t, w, hh, fl);
        s_ownMoveThread = 0;
    }
    return Inside(WinRect(h), t);
}
void TriggerLocked(const char* why) {
    if (!s_haveWindow) return;
    CloakLocked(why);
    s_targetKnown = false; s_placed = false; s_pending = true; s_lastTrigger = MonoS();
}
void ApplyLocked(const Decision& d) {
    if (d.act & kCloak) { CloakLocked(d.why); s_lastTrigger = MonoS(); }
    if (d.act & kInvalidate) { s_targetKnown = false; s_placed = false; }
    if (d.act & kRelocate) { if (!s_pending) LOGI("headless: relocation queued (%s)", d.why); s_pending = true; }
    if (d.act & kUncloak) UncloakLocked(d.why);
}
Obs ObserveLocked(bool full) {
    Obs o; o.haveWindow = s_haveWindow && s_main; o.cloaked = s_cloaked; o.targetKnown = s_targetKnown; o.target = s_t.m.rc;
    if (s_main) { o.visible = IsWindowVisible(s_main) != 0; o.window = WinRect(s_main); }
    o.liveOk = LiveRect(o.live);
    if (full) { o.metricsNow = MetricsNow(); o.layoutNow = Layout(ListMonitors(false)); }
    o.layoutAtResolve = s_layoutAt; o.metricsAtResolve = s_metricsAt; o.pending = s_pending; o.placed = s_placed;
    o.msSinceTrigger = (unsigned)((MonoS() - s_lastTrigger) * 1000.0 > 4e9 ? 4e9 : (MonoS() - s_lastTrigger) * 1000.0);
    o.settleMs = s_settleMs;
    return o;
}
// The relocation (render thread at Present, or the window's own thread): re-resolve by name and size, move, verify; no target ->
// retry until refuse_grace_ms, then refuse.
void RelocateLocked() {
    const uint64_t before = Layout(ListMonitors(false));
    std::string why;
    if (!ResolveLocked(why)) {
        s_targetKnown = false;
        if (s_noTargetSince < 0) { s_noTargetSince = MonoS(); LOGW("headless: no target after a display change (%s): cloaked, retrying for %u ms", why.c_str(), s_graceMs); }
        if (RefuseNow((unsigned)((MonoS() - s_noTargetSince) * 1000.0), s_graceMs)) { Refuse("the target display is gone after a display change: " + why); }
        return;
    }
    s_noTargetSince = -1;
    for (HWND h : s_wins) PlaceLocked(h);
    Rect live; const bool liveOk = LiveRect(live);
    const uint64_t after = Layout(ListMonitors(false));
    if (s_main && PlacementVerified(s_t.m.rc, WinRect(s_main), liveOk, live, before, after)) {
        s_placed = true; s_pending = false; s_layoutAt = after; s_metricsAt = MetricsNow();
        LOGI("headless: relocated and verified on %s %s (cloaked until the layout is quiet for %u ms)", s_t.m.device.c_str(), RectStr(s_t.m.rc).c_str(), s_settleMs);
    }
}
// After any gated call and every Present: a guarded window visible off the target (and not cloaked) is cloaked and sent to relocation.
void PostCheckLocked(const char* where) {
    for (HWND h : s_wins) {
        if (!IsWindow(h) || !IsWindowVisible(h) || s_cloaked) continue;
        const Rect r = WinRect(h);
        if (s_targetKnown && Inside(r, s_t.m.rc)) continue;
        LOGW("headless: window %p visible at %s, not inside the target (%s): cloaking", (void*)h, RectStr(r).c_str(), where);
        if (!s_haveWindow) { CloakWindow(h, true); ShowWindowAsync(h, SW_HIDE); continue; }
        TriggerLocked("window not inside the target");
    }
}

// ---- the main window's procedure: topology messages and its own geometry ------------------------------------------------------------
Pos PosOf(const WINDOWPOS* p) { Pos in; in.x = p->x; in.y = p->y; in.cx = p->cx; in.cy = p->cy; in.flags = p->flags; return in; }
bool OwnLocked(const Pos& in) { return s_ownMoveThread == GetCurrentThreadId() || IsOwnMove(s_ownMove, in, MonoS()); }

LRESULT CALLBACK GuardProc(HWND h, UINT msg, WPARAM wp, LPARAM lp) {
    Event ev = Event::Tick; bool trigger = false, ownChanged = false;
    switch (msg) {
    case WM_WINDOWPOSCHANGING: if (lp) {
        auto* p = reinterpret_cast<WINDOWPOS*>(lp);
        Lock l;
        const Pos in = PosOf(p);
        const bool own = OwnLocked(in);
        const PosVerdict v = GatePos(in, own, s_targetKnown, s_targetKnown && Inside(WinRect(h), s_t.m.rc), s_cloaked);
        if (v.changed) { p->flags = v.out.flags; if (v.why && s_logBudget > 0) { --s_logBudget; LOGI("headless: WM_WINDOWPOSCHANGING flags 0x%x -> 0x%x: %s", in.flags, v.out.flags, v.why); } }
        if (v.cloak) TriggerLocked("a show off the target");
    } break;
    case WM_WINDOWPOSCHANGED: ev = Event::PosChanged; trigger = true;
        if (lp) { Lock l; ownChanged = OwnLocked(PosOf(reinterpret_cast<WINDOWPOS*>(lp))); }
        break;
    case WM_DISPLAYCHANGE: ev = Event::DisplayChange; trigger = true; break;
    case WM_DPICHANGED: ev = Event::DpiChanged; trigger = true; break;
    case WM_SETTINGCHANGE: if (wp == SPI_SETWORKAREA) { ev = Event::SettingChange; trigger = true; } break;
    case WM_DEVICECHANGE: if (wp == kDbtNodes || wp == kDbtArrival || wp == kDbtRemoved) { ev = Event::DeviceChange; trigger = true; } break;
    case WM_ACTIVATEAPP: case WM_ACTIVATE: case WM_SETFOCUS: case WM_KILLFOCUS: case WM_NCACTIVATE:
        if (Budget()) LOGI("headless: window message 0x%04x wParam %lu at %.1f s (frame %ld)", msg, (unsigned long)wp, Uptime(), s_frames);
        break;
    default: break;
    }
    if (trigger) {
        Lock l;
        if (ev != Event::PosChanged) LOGI("headless: %s", EventName(ev));
        if (!(ev == Event::PosChanged && ownChanged)) ApplyLocked(Decide(ev, ObserveLocked(ev != Event::PosChanged)));
    }
    WNDPROC next; { Lock l; next = s_next; }
    return next ? CallWindowProcW(next, h, msg, wp, lp) : DefWindowProcW(h, msg, wp, lp);
}

// ---- the guard thread ---------------------------------------------------------------------------------------------------------------
BOOL CALLBACK SweepCb(HWND h, LPARAM);
DWORD WINAPI GuardThread(void*) {
    uint64_t lastMetrics = 0;
    for (unsigned n = 1;; ++n) {
        Sleep(4);
        if (SweepDue(n)) EnumWindows(SweepCb, 0);   // windows no gate saw (SweepHides); outside s_cs, SweepCb locks per window
        Lock l;
        if (!s_haveWindow || !s_main) continue;
        // the cheapest check every poll; the full layout every 25th poll, after any metrics change and while cloaked
        const uint64_t m = MetricsNow();
        const bool full = m != lastMetrics || s_cloaked || n % 25 == 0;
        lastMetrics = m;
        Obs o = ObserveLocked(full);
        o.metricsNow = m;
        ApplyLocked(Decide(Event::Tick, o));
        if (s_testOffThread && s_pending) RelocateLocked();   // test hook: the async placement path (fix 1a)
    }
}

// test hook (fix 1b): a visible 640x480 top-level window at the primary's origin, created and pumped by a thread of our own through our
// own import of CreateWindowExW (not the exe's hooked slot), as a third-party DLL's window would be; the sweep must hide it
DWORD WINAPI TestDllWindowThread(void*) {
    Sleep(s_testDllWindowMs);
    const HWND h = CreateWindowExW(WS_EX_NOACTIVATE, L"STATIC", L"wsp test: a DLL's own window", WS_POPUP | WS_VISIBLE, 0, 0, 640, 480, nullptr, nullptr, nullptr, nullptr);
    LOGW("headless: TEST HOOK headless.test_dll_window_ms: window %p shown at 0,0 640x480 through the proxy's own import", (void*)h);
    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    return 0;
}

void StartGuardThread() {
    static volatile LONG started = 0;
    if (InterlockedExchange(&started, 1)) return;
    if (HANDLE h = CreateThread(nullptr, 0, GuardThread, nullptr, 0, nullptr)) CloseHandle(h);
    else LOGE("headless: guard thread not started (%lu)", GetLastError());
}

// A window created before the hooks were in place, or since by a DLL through its own imports: hidden unless it is on the target.
BOOL CALLBACK SweepCb(HWND h, LPARAM) {
    DWORD pid = 0; GetWindowThreadProcessId(h, &pid);
    if (pid != GetCurrentProcessId() || !IsWindowVisible(h)) return TRUE;
    const Rect r = WinRect(h);
    Lock l;
    if (SweepHides(IsWindowVisible(h) != 0, s_wins.count(h) != 0, r, s_targetKnown, s_t.m.rc)) {
        LOGW("headless: unguarded window %p visible at %s: hidden", (void*)h, RectStr(r).c_str()); CloakWindow(h, true); ShowWindowAsync(h, SW_HIDE);
    }
    return TRUE;
}

// Target resolved and the guard running; called at the first Direct3DCreate9 or the first game window, whichever comes first.
void Ensure(const char* where) {
    if (InterlockedCompareExchange(&s_ensured, 1, 0) != 0) return;
    {
        Lock l;
        for (IatSpec& s : Iats()) if (s.state == -1) {
            s.state = IatHook(GetModuleHandleW(nullptr), s.dll, s.name, s.detour, s.original) > 0 ? 1 : -1;
            if (s.state != 1 && s.essential) { Refuse(std::string("the exe's ") + s.dll + "!" + s.name + " slot is still not snapped at " + where); }
        }
        std::string why;
        if (!ResolveLocked(why)) { Refuse("no target display at " + std::string(where) + ": " + why); }
        s_layoutAt = Layout(ListMonitors(false)); s_metricsAt = MetricsNow();
        s_st.state = "target_ok"; s_st.detail = "target resolved at " + std::string(where); WriteStatus();
    }
    StartGuardThread();
    EnumWindows(SweepCb, 0);
    if (s_testDllWindowMs) { if (HANDLE h = CreateThread(nullptr, 0, TestDllWindowThread, nullptr, 0, nullptr)) CloseHandle(h); }
}

// ---- user32 detours ---------------------------------------------------------------------------------------------------------------
HWND WINAPI hk_CreateWindowExW(DWORD ex, LPCWSTR cls, LPCWSTR name, DWORD style, int x, int y, int w, int h, HWND parent, HMENU menu, HINSTANCE inst, LPVOID param) {
    if (!s_on || (style & WS_CHILD)) return o_CreateWindowExW(ex, cls, name, style, x, y, w, h, parent, menu, inst, param);
    Ensure("CreateWindowExW");
    CreateIn in; in.x = x; in.y = y; in.w = w; in.h = h; in.style = style; in.exStyle = ex;
    CreateOut o; { Lock l; o = GateCreate(in, s_targetKnown, s_t.m.rc); }
    const std::string title = Utf8(name), klass = IS_INTRESOURCE(cls) ? std::string("#atom") : Utf8(cls);
    if (o.refuse) Refuse(o.why + " ('" + title + "')");
    if (o.helper) {
        const HWND hw = o_CreateWindowExW(ex, cls, name, style, x, y, w, h, parent, menu, inst, param);
        LOGI("headless: helper window %p '%s' class '%s' %dx%d at %d,%d style 0x%08lx: left alone", (void*)hw, title.c_str(), klass.c_str(), w, h, x, y, style);
        return hw;
    }
    // created hidden (WS_VISIBLE stripped) with the engine's own DPI context, then placed on the target in physical pixels
    const HWND hw = o_CreateWindowExW(o.v.exStyle, cls, name, o.v.style, (int)o.v.x, (int)o.v.y, (int)o.v.w, (int)o.v.h, parent, menu, inst, param);
    LOGI("headless: window %p '%s' class '%s' asked %dx%d at %d,%d style 0x%08lx ex 0x%08lx -> hidden, borderless, no-activate, style 0x%08lx ex 0x%08lx",
         (void*)hw, title.c_str(), klass.c_str(), w, h, x, y, style, ex, o.v.style, o.v.exStyle);
    if (!hw) return hw;
    bool inside;
    {
        Lock l;
        s_wins.insert(hw);
        if (!s_main) {
            s_main = hw;
            s_next = (WNDPROC)(LONG_PTR)SetWindowLongW(hw, GWL_WNDPROC, (LONG)(LONG_PTR)GuardProc);   // our own import: not the hooked slot
        }
        inside = PlaceLocked(hw);
        if (hw == s_main && inside) { s_haveWindow = true; s_placed = true; }
        LOGI("headless: window %p placed at %s (%s the target)", (void*)hw, RectStr(WinRect(hw)).c_str(), inside ? "inside" : "NOT inside");
    }
    if (o.showAfter && inside) o_ShowWindow(hw, SW_SHOWNA);
    { Lock l; PostCheckLocked("after CreateWindowExW"); }
    return hw;
}

BOOL WINAPI hk_ShowWindow(HWND h, int cmd) {
    if (!s_on || !Guarded(h)) return o_ShowWindow(h, cmd);
    Show act;
    { Lock l; act = GateShow(cmd, s_targetKnown && Inside(WinRect(h), s_t.m.rc), s_targetKnown); }
    BOOL r = FALSE;
    switch (act) {
    case Show::Pass: r = o_ShowWindow(h, cmd); break;
    case Show::Hide: if (Budget()) LOGI("headless: ShowWindow(%p, %d) minimise -> SW_HIDE", (void*)h, cmd); r = o_ShowWindow(h, SW_HIDE); break;
    case Show::ShowNA: r = o_ShowWindow(h, SW_SHOWNA); break;
    case Show::PlaceThenShowNA: {
        bool in; { Lock l; in = PlaceLocked(h); }
        if (in) r = o_ShowWindow(h, SW_SHOWNA);
        else if (Budget()) LOGW("headless: ShowWindow(%p, %d) refused: could not place it on the target", (void*)h, cmd);
    } break;
    case Show::Refuse: if (Budget()) LOGW("headless: ShowWindow(%p, %d) refused: the target is being re-resolved", (void*)h, cmd); break;
    }
    { Lock l; PostCheckLocked("after ShowWindow"); }
    return r;
}

BOOL WINAPI hk_SetWindowPos(HWND h, HWND after, int x, int y, int cx, int cy, UINT flags) {
    if (!s_on || !Guarded(h)) return o_SetWindowPos(h, after, x, y, cx, cy, flags);
    Pos in; in.x = x; in.y = y; in.cx = cx; in.cy = cy; in.flags = flags;
    PosVerdict v;
    { Lock l; v = GatePos(in, false, s_targetKnown, s_targetKnown && Inside(WinRect(h), s_t.m.rc), s_cloaked); if (v.cloak) TriggerLocked("SetWindowPos show off the target"); }
    if (v.why && Budget()) LOGI("headless: SetWindowPos(%p, %d,%d %dx%d, 0x%x) -> flags 0x%x: %s", (void*)h, x, y, cx, cy, flags, v.out.flags, v.why);
    if (v.why) InterlockedIncrement(&s_geomDropped);
    if (after == HWND_TOPMOST) after = HWND_TOP;
    const BOOL r = o_SetWindowPos(h, after, x, y, cx, cy, v.out.flags);
    { Lock l; PostCheckLocked("after SetWindowPos"); }
    return r;
}

BOOL WINAPI hk_MoveWindow(HWND h, int x, int y, int w, int hh, BOOL repaint) {
    if (!s_on || !Guarded(h)) return o_MoveWindow(h, x, y, w, hh, repaint);
    InterlockedIncrement(&s_geomDropped);
    if (Budget()) LOGI("headless: MoveWindow(%p, %d,%d %dx%d) dropped: the guard owns the geometry", (void*)h, x, y, w, hh);
    return TRUE;
}

LONG WINAPI hk_SetWindowLongW(HWND h, int idx, LONG v) {
    if (!s_on || !Guarded(h)) return o_SetWindowLongW(h, idx, v);
    if (idx == GWL_WNDPROC && h == s_main) {   // keep ours outermost: the engine's procedure goes under it
        Lock l; const LONG prev = (LONG)(LONG_PTR)s_next; s_next = (WNDPROC)(LONG_PTR)v;
        LOGI("headless: the engine replaced its window procedure (%p -> %p): kept under the guard's", (void*)(LONG_PTR)prev, (void*)(LONG_PTR)v);
        return prev;
    }
    LONG nv = v;
    if (idx == GWL_STYLE) { Lock l; nv = (LONG)GateStyle((uint32_t)v, s_targetKnown && Inside(WinRect(h), s_t.m.rc)); }
    else if (idx == GWL_EXSTYLE) nv = (LONG)GateExStyle((uint32_t)v);
    if (nv != v && Budget()) LOGI("headless: SetWindowLongW(%p, %d, 0x%08lx) -> 0x%08lx", (void*)h, idx, (unsigned long)v, (unsigned long)nv);
    const LONG r = o_SetWindowLongW(h, idx, nv);
    { Lock l; PostCheckLocked("after SetWindowLongW"); }
    return r;
}

// Never a display-mode change under headless: it would act on a real monitor (the engine passes no device name = the primary).
LONG WINAPI hk_ChangeDisplaySettingsW(DEVMODEW* dm, DWORD flags) {
    if (!s_on) return o_ChangeDisplaySettingsW(dm, flags);
    if (dm) LOGW("headless: ChangeDisplaySettingsW(%lux%lu@%lu, flags 0x%lx) NOT applied (it would change a real monitor): answered DISP_CHANGE_SUCCESSFUL",
                 dm->dmPelsWidth, dm->dmPelsHeight, dm->dmDisplayFrequency, flags);
    else LOGI("headless: ChangeDisplaySettingsW(null, flags 0x%lx) (restore) NOT applied: answered DISP_CHANGE_SUCCESSFUL", flags);
    return DISP_CHANGE_SUCCESSFUL;
}

int WINAPI hk_MessageBoxW(HWND h, LPCWSTR text, LPCWSTR cap, UINT type) {
    if (!s_on) return o_MessageBoxW(h, text, cap, type);
    const int a = MessageBoxAnswer(type);
    LOGW("headless: MessageBoxW not shown (type 0x%x), answered %d: '%s': '%s'", type, a, Utf8(cap).c_str(), Utf8(text).c_str());
    return a;
}

INT_PTR WINAPI hk_DialogBoxIndirectParamW(HINSTANCE inst, LPCDLGTEMPLATEW t, HWND parent, DLGPROC proc, LPARAM lp) {
    if (!s_on) return o_DialogBoxIndirectParamW(inst, t, parent, proc, lp);
    LOGW("headless: DialogBoxIndirectParamW not shown (it would open on a real monitor): answered -1");
    return -1;
}

// SetFocus activates its window even with WS_EX_NOACTIVATE (PC run 20261029_j13pc: WM_ACTIVATE at 1.1 s): while another process
// holds the foreground the engine's SetFocus on a guarded window is dropped, so the game never takes the foreground.
HWND WINAPI hk_SetFocus(HWND h) {
    if (!s_on || !h || !Guarded(GetAncestor(h, GA_ROOT))) return o_SetFocus(h);
    DWORD fg = 0; GetWindowThreadProcessId(GetForegroundWindow(), &fg);
    if (fg == GetCurrentProcessId()) return o_SetFocus(h);
    static volatile LONG n = 0;
    const LONG k = InterlockedIncrement(&n);
    if (k <= 3 || k % 1000 == 0) LOGI("headless: SetFocus(%p) dropped (another process has the foreground; %ld so far)", (void*)h, (long)k);
    return GetFocus();
}

// ---- DirectInput: never exclusive, never in the background (GateCoopLevel) ---------------------------------------------------------
using PFN_DI8Create = HRESULT(WINAPI*)(HINSTANCE, DWORD, REFIID, LPVOID*, void*);
using PFN_DICreateDevice = HRESULT(WINAPI*)(void*, REFGUID, void**, void*);
using PFN_DISetCoop = HRESULT(WINAPI*)(void*, HWND, DWORD);
PFN_DI8Create o_DI8Create; PFN_DICreateDevice o_DICreateDevice; PFN_DISetCoop o_DISetCoop;
HRESULT WINAPI hk_DISetCoop(void* dev, HWND h, DWORD flags) {
    const DWORD f = GateCoopLevel(flags);
    const HRESULT hr = o_DISetCoop(dev, h, f);
    LOGI("headless: DirectInput SetCooperativeLevel(%p, window %p, flags 0x%lx) -> 0x%lx (non-exclusive, foreground only): hr 0x%08lx",
         dev, (void*)h, flags, f, (unsigned long)hr);
    return hr;
}
HRESULT WINAPI hk_DICreateDevice(void* di, REFGUID g, void** out, void* outer) {
    const HRESULT hr = o_DICreateDevice(di, g, out, outer);
    if (SUCCEEDED(hr) && out && *out && !o_DISetCoop) VtableHook(*(void***)*out, 13, (void*)hk_DISetCoop, (void**)&o_DISetCoop, "IDirectInputDevice8::SetCooperativeLevel (headless)");
    return hr;
}
HRESULT WINAPI hk_DI8Create(HINSTANCE inst, DWORD ver, REFIID iid, LPVOID* out, void* outer) {
    const HRESULT hr = o_DI8Create(inst, ver, iid, out, outer);
    if (s_on && SUCCEEDED(hr) && out && *out && !o_DICreateDevice) VtableHook(*(void***)*out, 3, (void*)hk_DICreateDevice, (void**)&o_DICreateDevice, "IDirectInput8::CreateDevice (headless)");
    return hr;
}

std::vector<IatSpec>& Iats() {
    static std::vector<IatSpec> v = {
        { "CreateWindowExW", (void*)hk_CreateWindowExW, (void**)&o_CreateWindowExW, true, 0 },
        { "ShowWindow", (void*)hk_ShowWindow, (void**)&o_ShowWindow, true, 0 },
        { "SetWindowPos", (void*)hk_SetWindowPos, (void**)&o_SetWindowPos, true, 0 },
        { "MoveWindow", (void*)hk_MoveWindow, (void**)&o_MoveWindow, true, 0 },
        { "SetWindowLongW", (void*)hk_SetWindowLongW, (void**)&o_SetWindowLongW, true, 0 },
        { "ChangeDisplaySettingsW", (void*)hk_ChangeDisplaySettingsW, (void**)&o_ChangeDisplaySettingsW, true, 0 },
        { "MessageBoxW", (void*)hk_MessageBoxW, (void**)&o_MessageBoxW, false, 0 },
        { "DialogBoxIndirectParamW", (void*)hk_DialogBoxIndirectParamW, (void**)&o_DialogBoxIndirectParamW, false, 0 },
        { "SetFocus", (void*)hk_SetFocus, (void**)&o_SetFocus, true, 0 },
        { "DirectInput8Create", (void*)hk_DI8Create, (void**)&o_DI8Create, true, 0, "dinput8.dll" },
    };
    return v;
}

// ---- IDirect3D9 / IDirect3DDevice9 vtable hooks ------------------------------------------------------------------------------------
struct DispMode { UINT w, h, hz, fmt; };   // D3DDISPLAYMODE
struct PresentParams { UINT bbW, bbH, bbFmt, bbCount, msType, msQuality, swap; HWND hDev; BOOL windowed; };   // D3DPRESENT_PARAMETERS head
const HRESULT kInvalidCall = (HRESULT)0x8876086CL;   // D3DERR_INVALIDCALL
using PFN_ModeCount = UINT(WINAPI*)(void*, UINT, UINT);
using PFN_EnumModes = HRESULT(WINAPI*)(void*, UINT, UINT, UINT, DispMode*);
using PFN_DispMode = HRESULT(WINAPI*)(void*, UINT, DispMode*);
using PFN_Monitor = HMONITOR(WINAPI*)(void*, UINT);
using PFN_CreateDevice = HRESULT(WINAPI*)(void*, UINT, int, HWND, DWORD, void*, void**);
using PFN_Reset = HRESULT(WINAPI*)(void*, void*);
using PFN_Present = HRESULT(WINAPI*)(void*, const RECT*, const RECT*, HWND, const void*);
PFN_ModeCount o_ModeCount; PFN_EnumModes o_EnumModes; PFN_DispMode o_DispMode; PFN_Monitor o_Monitor; PFN_CreateDevice o_CreateDevice;
PFN_Reset o_Reset; PFN_Present o_Present;
std::set<unsigned> s_logged;   // first call of each (function, adapter, format)
bool FirstCall(unsigned fn, UINT ad, UINT fmt) { Lock l; return s_logged.insert(fn << 24 | (ad & 0xff) << 16 | (fmt & 0xffff)).second; }

UINT WINAPI hk_ModeCount(void* self, UINT ad, UINT fmt) {
    UINT n; { Lock l; n = AnswersFormat(fmt) ? (UINT)s_t.modes.size() : 0; }
    if (FirstCall(1, ad, fmt)) LOGI("headless: GetAdapterModeCount(adapter %u, format %u) -> %u from the target (the backend said %u)", ad, fmt, n, o_ModeCount(self, ad, fmt));
    return n;
}
HRESULT WINAPI hk_EnumModes(void*, UINT ad, UINT fmt, UINT i, DispMode* out) {
    Lock l;
    if (!out || !AnswersFormat(fmt) || i >= s_t.modes.size()) return kInvalidCall;
    const Mode& m = s_t.modes[i];
    *out = DispMode{ m.w, m.h, m.hz, fmt };
    if (s_logged.insert(2u << 24 | (ad & 0xff) << 16 | (fmt & 0xffff)).second) LOGI("headless: EnumAdapterModes(adapter %u, format %u) answered from the target: %s", ad, fmt, ModesStr(s_t.modes).c_str());
    return S_OK;
}
HRESULT WINAPI hk_DispMode(void*, UINT ad, DispMode* out) {
    if (!out) return kInvalidCall;
    Lock l;
    *out = DispMode{ s_t.cur.w, s_t.cur.h, s_t.cur.hz, kFmtX8R8G8B8 };
    if (s_logged.insert(3u << 24 | (ad & 0xff) << 16).second) LOGI("headless: GetAdapterDisplayMode(adapter %u) -> %ux%u@%u (the target)", ad, s_t.cur.w, s_t.cur.h, s_t.cur.hz);
    return S_OK;
}
HMONITOR WINAPI hk_Monitor(void*, UINT ad) {
    Lock l;
    if (s_logged.insert(4u << 24 | (ad & 0xff) << 16).second) LOGI("headless: GetAdapterMonitor(adapter %u) -> the target %s", ad, s_t.m.device.c_str());
    return s_t.hmon;
}

// The device must be windowed with exactly the target's size: anything else is refused before the device exists.
void CheckParams(const char* what, PresentParams* pp, HWND focus) {
    if (!pp) Refuse(std::string(what) + " without present parameters");
    HWND w = pp->hDev ? pp->hDev : focus;
    long bw = (long)pp->bbW, bh = (long)pp->bbH;
    if (pp->windowed && (!bw || !bh) && w) { RECT rc{}; GetClientRect(w, &rc); bw = rc.right; bh = rc.bottom; }
    LOGI("headless: %s: back buffer %ldx%ld, %s, window %p", what, bw, bh, pp->windowed ? "windowed" : "FULLSCREEN", (void*)w);
    const Device kind = GateDevice(pp->windowed != FALSE, bw, bh, s_w, s_h);
    if (kind == Device::Helper) { LOGI("headless: %s: a helper device (back buffer %ldx%ld): allowed, it shows nothing", what, bw, bh); return; }
    if (!pp->windowed) Refuse(std::string(what) + " asked for an exclusive fullscreen device (gfx_fullscreen true?): headless runs windowed borderless on the target only");
    if (kind == Device::Refuse) {
        char b[160]; snprintf(b, sizeof b, "%s back buffer %ldx%ld is not headless.size %ldx%ld (the prefs x_res/y_res and the virtual display's mode must match)", what, bw, bh, s_w, s_h);
        Refuse(b);
    }
    Lock l;
    s_st.bbW = bw; s_st.bbH = bh;
    if (w) {
        HWND root = GetAncestor(w, GA_ROOT);
        if (root && root != s_main) LOGW("headless: the device window %p is not the first game window %p", (void*)root, (void*)s_main);
        if (root && !s_wins.count(root)) Refuse("the device window was not created through the guarded CreateWindowExW");
    }
}
HRESULT WINAPI hk_Present(void* dev, const RECT* a, const RECT* b, HWND w, const void* r) {
    HeadlessPresent();
    return o_Present(dev, a, b, w, r);
}
HRESULT WINAPI hk_Reset(void* dev, void* pp) {
    CheckParams("Reset", (PresentParams*)pp, nullptr);
    return o_Reset(dev, pp);
}
HRESULT WINAPI hk_CreateDevice(void* d3d, UINT ad, int type, HWND focus, DWORD flags, void* pp, void** out) {
    CheckParams("CreateDevice", (PresentParams*)pp, focus);
    const HRESULT hr = o_CreateDevice(d3d, ad, type, focus, flags, pp, out);
    LOGI("headless: CreateDevice(adapter %u, flags 0x%lx) -> 0x%08lx", ad, flags, (unsigned long)hr);
    if (SUCCEEDED(hr) && out && *out) {
        void** vt = *(void***)*out;
        Lock l;
        s_device = true;
        if (!o_Reset) VtableHook(vt, 16, (void*)hk_Reset, (void**)&o_Reset, "IDirect3DDevice9::Reset (headless)");
        if (!o_Present) VtableHook(vt, 17, (void*)hk_Present, (void**)&o_Present, "IDirect3DDevice9::Present (headless)");
    }
    return hr;
}

}  // namespace

void HeadlessPresent() {
    if (!s_on) return;
    Lock l;
    ++s_frames;
    if (s_pending && !s_testOffThread) RelocateLocked();
    PostCheckLocked("Present");
    if (s_st.state != "on_virtual" && s_device && s_main && s_haveWindow && !s_cloaked && IsWindowVisible(s_main)) {
        const Rect r = WinRect(s_main);
        if (s_targetKnown && Inside(r, s_t.m.rc)) {
            RECT c{}; GetClientRect(s_main, &c);
            s_st.state = "on_virtual"; s_st.winW = Width(r); s_st.winH = Height(r); s_st.clientW = c.right; s_st.clientH = c.bottom;
            char b[200]; snprintf(b, sizeof b, "window %s on %s, first frame presented there at %.1f s", RectStr(r).c_str(), s_t.m.device.c_str(), Uptime());
            s_st.detail = b;
            WriteStatus();
            LOGI("headless: ON THE VIRTUAL DISPLAY: %s (client %ldx%ld, back buffer %ldx%ld)", b, s_st.clientW, s_st.clientH, s_st.bbW, s_st.bbH);
        }
    }
}

// DllMain, before the early return of a disabled proxy: headless asked but the proxy is off = nothing could keep the window off the
// real monitors.
void HeadlessPreflight(bool second) {
    const Runtime& rt = Rt();
    if (second || !rt.cfg.Bool("headless.enabled") || rt.enabled) return;
    InitializeCriticalSection(&s_cs);
    s_on = true;
    Refuse("headless.enabled=1 but proxy.enabled=0: nothing could keep the window off the real monitors");
}

// DllMain, after the plan and the dev side.
void HeadlessInit() {
    Runtime& rt = Rt();
    if (!rt.cfg.Bool("headless.enabled")) return;
    InitializeCriticalSection(&s_cs);
    s_t0 = MonoS();
    s_on = true;
    s_name = rt.cfg.Str("headless.display_name");
    s_settleMs = (unsigned)rt.cfg.Int("headless.settle_ms");
    s_graceMs = (unsigned)rt.cfg.Int("headless.refuse_grace_ms");
    s_testOffThread = rt.cfg.Bool("headless.test_off_thread");
    s_testDllWindowMs = (unsigned)rt.cfg.Int("headless.test_dll_window_ms");
    if (s_testOffThread || s_testDllWindowMs) LOGW("headless: TEST HOOKS on: off_thread=%d dll_window_ms=%u (PC proof only, never a release)", s_testOffThread ? 1 : 0, s_testDllWindowMs);
    { Lock l; s_st.state = "starting"; s_st.detail = "DllMain"; WriteStatus(); }
    if (!ParseSize(rt.cfg.Str("headless.size"), s_w, s_h)) Refuse("headless.size '" + rt.cfg.Str("headless.size") + "' is not WxH");
    if (!rt.plan.engineHooks) Refuse("the exe-identity guard put the proxy in pass-through (no hooks): nothing could keep the window off the real monitors");
    LOGI("headless: on: target '%s' at exactly %ldx%ld, settle %u ms, refuse grace %u ms", s_name.c_str(), s_w, s_h, s_settleMs, s_graceMs);
    HMODULE exe = GetModuleHandleW(nullptr);
    for (IatSpec& s : Iats()) {
        const int n = IatHook(exe, s.dll, s.name, s.detour, s.original);
        s.state = n > 0 ? 1 : n < 0 ? -1 : 0;
        if (s.state == 0 && s.essential) Refuse(std::string("the exe does not import ") + s.dll + "!" + s.name + " (an inline hook would be needed)");
        if (s.state == -1 && !*s.original) *s.original = (void*)GetProcAddress(GetModuleHandleA(s.dll), s.name);   // until the retry (null if not loaded yet)
    }
}

void HeadlessOnDirect3DCreate(void* d3d) {
    if (!s_on || !d3d) return;
    Ensure("Direct3DCreate9");
    void** vt = *(void***)d3d;
    Lock l;
    if (!o_ModeCount) VtableHook(vt, 6, (void*)hk_ModeCount, (void**)&o_ModeCount, "IDirect3D9::GetAdapterModeCount (headless)");
    if (!o_EnumModes) VtableHook(vt, 7, (void*)hk_EnumModes, (void**)&o_EnumModes, "IDirect3D9::EnumAdapterModes (headless)");
    if (!o_DispMode) VtableHook(vt, 8, (void*)hk_DispMode, (void**)&o_DispMode, "IDirect3D9::GetAdapterDisplayMode (headless)");
    if (!o_Monitor) VtableHook(vt, 15, (void*)hk_Monitor, (void**)&o_Monitor, "IDirect3D9::GetAdapterMonitor (headless)");
    if (!o_CreateDevice) VtableHook(vt, 16, (void*)hk_CreateDevice, (void**)&o_CreateDevice, "IDirect3D9::CreateDevice (headless)");
}

bool HeadlessOn() { return s_on; }

void HeadlessOnDetach() {
    if (!s_on) return;
    LOGI("headless: detach after %ld frames; %ld engine geometry calls dropped; state %s", s_frames, (long)s_geomDropped, s_st.state.c_str());
}

} // namespace wsp
