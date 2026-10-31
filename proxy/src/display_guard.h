#pragma once
// display_guard.h - pure decision logic of headless runs (J13): which display is the target, what the engine is told about display
// modes, and whether a game window may be created, shown, styled or moved. No Windows headers and no state: headless.cpp gathers
// the observations (monitor list, window rects, layout signature) and applies the actions; this file decides. Host-tested by
// proxy/tests/test_display_guard.cpp.
//
// The rule (fail closed): under headless a game window is never visible outside the target display. The target is chosen by name
// (adapter or monitor string) plus an exact size match with the wanted back buffer, never by index, GDI number or origin. On any
// sign of a topology change the window is cloaked FIRST, the target re-resolved by name, the window moved and verified, and only
// after the layout has been quiet for settleMs is it uncloaked. No target means refusal, never a fallback.
// Design ported from empire-remastered rml_mod/src/headless_guard.h (incidents: rml_mod/docs/runs/20261020_headless_fix and
// 20261022_headless_display_change); the blocked-poll watchdog and the WndProc chain ping were left out (see proxy/README.md).
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace wsp {
namespace dg {

// ---- rectangles: physical pixels, right/bottom exclusive (a Win32 RECT) ------------------------------------------------------
struct Rect { long l = 0, t = 0, r = 0, b = 0; };
inline Rect R(long x, long y, long w, long h) { return Rect{ x, y, x + w, y + h }; }
inline long Width(const Rect& x) { return x.r - x.l; }
inline long Height(const Rect& x) { return x.b - x.t; }
inline bool Empty(const Rect& x) { return x.r <= x.l || x.b <= x.t; }
inline bool Same(const Rect& a, const Rect& b) { return a.l == b.l && a.t == b.t && a.r == b.r && a.b == b.b; }
inline bool Inside(const Rect& w, const Rect& t) { return !Empty(t) && w.l >= t.l && w.t >= t.t && w.r <= t.r && w.b <= t.b; }
inline bool Overlap(const Rect& a, const Rect& b) { return a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b; }
inline std::string RectStr(const Rect& x) { char b[80]; snprintf(b, sizeof b, "%ld,%ld %ldx%ld", x.l, x.t, Width(x), Height(x)); return b; }

inline bool ParseSize(const std::string& s, long& w, long& h) {   // "3840x2160"
    const size_t x = s.find_first_of("xX");
    if (x == std::string::npos || x == 0 || x + 1 >= s.size()) return false;
    for (size_t i = 0; i < s.size(); ++i) if (i != x && (s[i] < '0' || s[i] > '9')) return false;
    w = strtol(s.substr(0, x).c_str(), nullptr, 10); h = strtol(s.substr(x + 1).c_str(), nullptr, 10);
    return w >= 320 && h >= 200 && w <= 16384 && h <= 16384;
}

// ---- target selection ----------------------------------------------------------------------------------------------------------
struct Monitor {
    std::string device;    // GDI name, \\.\DISPLAYn (logged only: the number is not stable)
    std::string adapter;   // EnumDisplayDevices adapter string ("Virtual Display Driver", "NVIDIA GeForce RTX 4090")
    std::string monitor;   // the monitor's string ("Generic PnP Monitor", "Dell S2721DGF (HDMI2)")
    Rect rc;               // physical (per-monitor DPI aware V2)
    bool primary = false;
    int dpi = 0;           // 0 = unknown
};
inline std::string LowerS(std::string s) { for (char& c : s) if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a'); return s; }
inline bool NameMatches(const Monitor& m, const std::string& name) {
    const std::string n = LowerS(name);
    return !n.empty() && (LowerS(m.adapter).find(n) != std::string::npos || LowerS(m.monitor).find(n) != std::string::npos);
}
inline std::string MonitorLine(const Monitor& m) {
    char b[400]; snprintf(b, sizeof b, "%s %s%s adapter='%s' monitor='%s' dpi=%d", m.device.c_str(), RectStr(m.rc).c_str(), m.primary ? " PRIMARY" : "",
                          m.adapter.c_str(), m.monitor.c_str(), m.dpi);
    return b;
}

struct Pick { int index = -1; std::string why; };   // index into the list, -1 = refuse (why says it)
// Exactly one attached display whose adapter or monitor string contains `name`, that is not the primary and whose rect is exactly
// w x h. Anything else is a refusal with the reason: no fallback to the primary, to the first non-primary or to a near size.
inline Pick SelectTarget(const std::vector<Monitor>& ms, const std::string& name, long w, long h) {
    Pick p;
    if (name.empty()) { p.why = "no display name configured"; return p; }
    std::vector<int> named, fit;
    for (size_t i = 0; i < ms.size(); ++i) if (NameMatches(ms[i], name)) named.push_back((int)i);
    if (named.empty()) {
        p.why = "no display named '" + name + "' (" + std::to_string(ms.size()) + " displays)";
        return p;
    }
    std::string notes;
    for (int i : named) {
        const Monitor& m = ms[i];
        if (m.primary) { notes += "; " + m.device + " is the primary"; continue; }
        if (Width(m.rc) != w || Height(m.rc) != h) { notes += "; " + m.device + " is " + std::to_string(Width(m.rc)) + "x" + std::to_string(Height(m.rc)); continue; }
        fit.push_back(i);
    }
    char want[40]; snprintf(want, sizeof want, "%ldx%ld", w, h);
    if (fit.size() == 1) {
        p.index = fit[0];
        p.why = ms[fit[0]].device + " matches '" + name + "', is not the primary and is exactly " + want;
        return p;
    }
    if (fit.empty()) p.why = "no non-primary display named '" + name + "' at " + want + notes;
    else p.why = std::to_string(fit.size()) + " non-primary displays named '" + name + "' at " + want + ": ambiguous";
    return p;
}

// ---- the mode list the engine sees ------------------------------------------------------------------------------------------
// Why (found on the earlier remaster, empire-remastered rml_mod/docs/headless_virtual_display.md "Fail closed"): DXVK answers every adapter
// with the PRIMARY monitor's modes, so with a primary of another size the engine would size its device for the primary. Under
// headless every adapter answers from the target's modes instead.
struct Mode { uint32_t w = 0, h = 0, hz = 0; };
inline bool ModeLess(const Mode& a, const Mode& b) { return a.w != b.w ? a.w < b.w : a.h != b.h ? a.h < b.h : a.hz < b.hz; }
// raw = the target's EnumDisplaySettings list (32 bpp entries only, the caller filters); deduplicated and sorted
inline std::vector<Mode> ModeList(std::vector<Mode> raw) {
    std::sort(raw.begin(), raw.end(), ModeLess);
    std::vector<Mode> out;
    for (const Mode& m : raw) if (m.w && m.h && (out.empty() || ModeLess(out.back(), m))) out.push_back(m);
    return out;
}
inline std::string ModesStr(const std::vector<Mode>& v) {
    std::string s; for (const Mode& m : v) { char b[40]; snprintf(b, sizeof b, "%s%ux%u@%u", s.empty() ? "" : " ", m.w, m.h, m.hz); s += b; }
    return s.empty() ? "(none)" : s;
}
enum : uint32_t { kFmtA8R8G8B8 = 21, kFmtX8R8G8B8 = 22 };   // D3DFORMAT values
// The display formats the target's list answers; any other format gets no modes (the engine then has nothing else to pick).
inline bool AnswersFormat(uint32_t fmt) { return fmt == kFmtX8R8G8B8 || fmt == kFmtA8R8G8B8; }

// ---- layout signature and virtual-screen metrics ----------------------------------------------------------------------------
constexpr uint64_t kFnvBasis = 1469598103934665603ull, kFnvPrime = 1099511628211ull;
constexpr uint64_t kLayoutSeed = 0x9e3779b97f4a7c15ull;   // the empty layout is not 0: 0 means "not gathered"
inline uint64_t FnvBytes(uint64_t h, const void* p, size_t n) {
    const unsigned char* c = static_cast<const unsigned char*>(p);
    for (size_t i = 0; i < n; ++i) { h ^= c[i]; h *= kFnvPrime; }
    return h;
}
// one hash per monitor (GDI name, rect, primary flag); the layout is their SUM, so the enumeration order does not matter
inline uint64_t MonitorHash(const std::string& dev, const Rect& rc, bool primary) {
    uint64_t h = FnvBytes(kFnvBasis, dev.data(), dev.size());
    const int32_t v[5] = { (int32_t)rc.l, (int32_t)rc.t, (int32_t)rc.r, (int32_t)rc.b, primary ? 1 : 0 };
    return FnvBytes(h, v, sizeof v);
}
inline uint64_t Layout(const std::vector<Monitor>& ms) {
    uint64_t l = kLayoutSeed; for (const Monitor& m : ms) l += MonitorHash(m.device, m.rc, m.primary); return l;
}
// GetSystemMetrics(SM_CMONITORS, SM_[XY]VIRTUALSCREEN, SM_C[XY]VIRTUALSCREEN): five reads, no enumeration: the guard thread's
// cheapest check, run every poll before anything else
inline uint64_t MetricsHash(int monitors, int x, int y, int cx, int cy) {
    const int32_t v[5] = { monitors, x, y, cx, cy };
    return FnvBytes(kFnvBasis ^ 0x5a5a5a5aull, v, sizeof v) | 1ull;   // never 0 (0 = not gathered)
}

// ---- window creation --------------------------------------------------------------------------------------------------------
// winuser.h values; headless.cpp static_asserts them against the real ones
enum : uint32_t {
    kWsChild = 0x40000000u, kWsVisible = 0x10000000u, kWsPopup = 0x80000000u, kWsMinimize = 0x20000000u, kWsMaximize = 0x01000000u,
    kWsCaption = 0x00C00000u, kWsThickFrame = 0x00040000u, kWsSysMenu = 0x00080000u, kWsMinBox = 0x00020000u, kWsMaxBox = 0x00010000u,
    kWsExNoActivate = 0x08000000u, kWsExToolWindow = 0x00000080u, kWsExAppWindow = 0x00040000u, kWsExTopmost = 0x00000008u,
};
constexpr long kCwUseDefault = (long)0x80000000;
constexpr uint32_t kFrameBits = kWsCaption | kWsThickFrame | kWsSysMenu | kWsMinBox | kWsMaxBox;
constexpr long kHelperMax = 8;   // a top-level window no larger than this (the engine's 1x1 helper, if any) is left alone and logged

struct CreateIn { long x = 0, y = 0, w = 0, h = 0; uint32_t style = 0, exStyle = 0; };
struct CreateOut { CreateIn v; bool helper = false, showAfter = false, refuse = false; std::string why; };
// A top-level game window is created hidden (shown with SW_SHOWNA after it is placed, if WS_VISIBLE was asked), borderless,
// non-activating and out of Alt+Tab, at the target's origin with at most the target's size. Without a target it is refused.
inline CreateOut GateCreate(const CreateIn& in, bool targetKnown, const Rect& target) {
    CreateOut o; o.v = in;
    if (in.style & kWsChild) { o.why = "child window"; return o; }
    if (in.w != kCwUseDefault && in.h != kCwUseDefault && in.w > 0 && in.h > 0 && in.w <= kHelperMax && in.h <= kHelperMax) {
        o.helper = true; o.why = "helper window (left alone)"; return o;
    }
    if (!targetKnown) { o.refuse = true; o.why = "a game window is being created and there is no target display"; return o; }
    o.showAfter = (in.style & kWsVisible) != 0;
    o.v.style = (in.style & ~(kWsVisible | kFrameBits | kWsMinimize | kWsMaximize)) | kWsPopup;
    o.v.exStyle = (in.exStyle & ~(kWsExAppWindow | kWsExTopmost)) | kWsExNoActivate | kWsExToolWindow;
    o.v.x = target.l; o.v.y = target.t;
    o.v.w = (in.w == kCwUseDefault || in.w <= 0 || in.w > Width(target)) ? Width(target) : in.w;
    o.v.h = (in.h == kCwUseDefault || in.h <= 0 || in.h > Height(target)) ? Height(target) : in.h;
    o.why = "created hidden on the target";
    return o;
}
// SetWindowLong(GWL_STYLE / GWL_EXSTYLE) on a guarded window: the frame and activation bits stay off, WS_VISIBLE only on the target
inline uint32_t GateStyle(uint32_t style, bool insideTarget) {
    style = (style & ~(kFrameBits | kWsMaximize)) | kWsPopup;
    if (!insideTarget) style &= ~kWsVisible;
    return style;
}
inline uint32_t GateExStyle(uint32_t ex) { return (ex & ~(kWsExAppWindow | kWsExTopmost)) | kWsExNoActivate | kWsExToolWindow; }

// ---- ShowWindow -------------------------------------------------------------------------------------------------------------
enum : int { kSwHide = 0, kSwShowMinimized = 2, kSwMinimize = 6, kSwShowMinNoActive = 7, kSwShowNA = 8, kSwForceMinimize = 11 };
enum class Show { Pass, Hide, ShowNA, PlaceThenShowNA, Refuse };
// A minimised window would leave the target (it is drawn on the primary's taskbar area): hidden instead. Every other show becomes a
// no-activate show, after the window is moved onto the target if it is not wholly inside it; with no target it is refused.
inline Show GateShow(int cmd, bool insideTarget, bool targetKnown) {
    if (cmd == kSwHide) return Show::Pass;
    if (cmd == kSwShowMinimized || cmd == kSwMinimize || cmd == kSwShowMinNoActive || cmd == kSwForceMinimize) return Show::Hide;
    if (!targetKnown) return Show::Refuse;
    return insideTarget ? Show::ShowNA : Show::PlaceThenShowNA;
}

// ---- SetWindowPos / MoveWindow / WM_WINDOWPOSCHANGING ---------------------------------------------------------------------------
enum : unsigned { kSwpNoSize = 0x0001u, kSwpNoMove = 0x0002u, kSwpNoZOrder = 0x0004u, kSwpNoActivate = 0x0010u, kSwpShowWindow = 0x0040u, kSwpHideWindow = 0x0080u,
                  kSwpNoOwnerZOrder = 0x0200u, kSwpAsync = 0x4000u };
struct Pos { long x = 0, y = 0, cx = 0, cy = 0; unsigned flags = 0; };   // WINDOWPOS fields
struct PosVerdict { Pos out; bool changed = false; bool cloak = false; const char* why = nullptr; };
// A guarded window's geometry belongs to the guard. The engine's coordinates may be DPI-virtualised (a DPI-unaware exe with a scaled
// primary), so they are never compared with the physical target: its moves and sizes are dropped, unless the call is the guard's own
// relocation (own). Activation is always stripped (SWP_NOACTIVATE). A show passes only when the window lies wholly inside a known
// target (or is cloaked); otherwise it is dropped and the caller must cloak and relocate (cloak). Hiding passes.
inline PosVerdict GatePos(const Pos& in, bool own, bool targetKnown, bool insideTarget, bool cloaked) {
    PosVerdict v; v.out = in;
    v.out.flags |= kSwpNoActivate;
    if (!(in.flags & kSwpHideWindow) && !own) {
        if (!(in.flags & kSwpNoMove) || !(in.flags & kSwpNoSize)) { v.out.flags |= kSwpNoMove | kSwpNoSize; v.why = "geometry kept (the guard owns it)"; }
        if ((in.flags & kSwpShowWindow) && !cloaked && !(targetKnown && insideTarget)) {
            v.out.flags &= ~kSwpShowWindow; v.cloak = true; v.why = "show refused: not on the target";
        }
    }
    v.changed = v.out.flags != in.flags;
    return v;
}
// The guard's own relocation, recognised by its target rect (J13 review should-fix 1). When the guard moves a window another thread
// owns (a game that presents from a worker thread), SetWindowPos goes asynchronous and the window's own thread handles
// WM_WINDOWPOSCHANGING later, so the calling thread's id cannot tell the guard's move from the engine's: the move was dropped and the
// window stayed cloaked for good. The guard arms this record before each placement; a position message that moves and sizes to
// exactly that rect within kOwnMoveMs is the guard's (an engine move to the very same rect is harmless). Physical pixels: at a
// scaled target DPI a DPI-unaware window thread sees other numbers, and only the same-thread case is recognised (logged at resolve).
constexpr unsigned kOwnMoveMs = 2000;
struct OwnMove { bool armed = false; Rect want; double at = 0; };   // at: monotonic seconds of the arming
inline bool IsOwnMove(const OwnMove& m, const Pos& in, double now) {
    if (!m.armed || now < m.at || (now - m.at) * 1000.0 > kOwnMoveMs || (in.flags & (kSwpNoMove | kSwpNoSize))) return false;
    return in.x == m.want.l && in.y == m.want.t && in.cx == Width(m.want) && in.cy == Height(m.want);
}

// ---- the window sweep ---------------------------------------------------------------------------------------------------------
// A top-level window of the process that the guard did not create (a DLL's own CreateWindowExW or MessageBoxW, a CRT or loader
// dialog) is not in the guarded set, so no gate sees it. The guard thread sweeps every top-level window of the process every
// kSweepPolls polls (~250 ms; J13 review should-fix 2) and at start-up: a visible unguarded window larger than the helper size is
// hidden unless it lies wholly inside a known target. The sweep runs outside the guard's lock (it takes it per window).
constexpr unsigned kSweepPolls = 62;   // x 4 ms poll
inline bool SweepDue(unsigned poll) { return poll % kSweepPolls == 0; }
inline bool SweepHides(bool visible, bool guarded, const Rect& r, bool targetKnown, const Rect& target) {
    if (!visible || guarded) return false;
    if (Width(r) <= kHelperMax && Height(r) <= kHelperMax) return false;
    return !(targetKnown && Inside(r, target));
}

// ---- devices (CreateDevice / Reset) --------------------------------------------------------------------------------------------
// The game device must be windowed at exactly the wanted size. A windowed device with a tiny back buffer is the engine's offscreen
// helper (PC run 20261029_j13pc: a 1x1 device on a non-game window when a battle loads): it shows nothing, so it passes.
enum class Device { Game, Helper, Refuse };
inline Device GateDevice(bool windowed, long bw, long bh, long w, long h) {
    if (!windowed) return Device::Refuse;
    if (bw > 0 && bh > 0 && bw <= kHelperMax && bh <= kHelperMax) return Device::Helper;
    return bw == w && bh == h ? Device::Game : Device::Refuse;
}

// ---- the topology guard ---------------------------------------------------------------------------------------------------------
enum class Event { Tick, DisplayChange, DpiChanged, SettingChange, PosChanged, DeviceChange };
inline const char* EventName(Event e) {
    switch (e) {
    case Event::DisplayChange: return "WM_DISPLAYCHANGE";
    case Event::DpiChanged: return "WM_DPICHANGED";
    case Event::SettingChange: return "WM_SETTINGCHANGE";
    case Event::PosChanged: return "WM_WINDOWPOSCHANGED";
    case Event::DeviceChange: return "WM_DEVICECHANGE";
    default: return "tick";
    }
}
struct Obs {
    bool haveWindow = false;       // the game window was placed on the target once (before that the create-time gate rules)
    bool visible = false;          // IsWindowVisible
    bool cloaked = false;          // the guard's cloak is in force
    Rect window;                   // GetWindowRect, physical
    bool targetKnown = false;      // false while a change is being re-resolved
    Rect target;                   // the target's rect as of the last resolve
    bool liveOk = false;           // GetMonitorInfo(target HMONITOR) succeeded just now ...
    Rect live;                     // ... and returned this rect
    uint64_t layoutNow = 0, layoutAtResolve = 0;     // 0 = not gathered / unknown
    uint64_t metricsNow = 0, metricsAtResolve = 0;   // 0 = not gathered / unknown
    bool pending = false;          // a relocation is queued for the render thread
    bool placed = false;           // relocated and verified since the last trigger
    unsigned msSinceTrigger = 0;
    unsigned settleMs = 500;       // quiet time before uncloaking (a monitor coming online changes in bursts)
};
enum : unsigned { kCloak = 1u, kInvalidate = 2u, kRelocate = 4u, kUncloak = 8u };
struct Decision { unsigned act = 0; const char* why = nullptr; };
// A trigger (a topology message; metrics or layout differ from the verified ones; the target monitor moved or vanished; the window
// visible, uncloaked and not wholly inside a known target) always means cloak + invalidate + relocate. Without one, a cloaked
// window is uncloaked only when relocated and verified, nothing is pending, the live target equals the cached one, the window lies
// inside it, the layout is fresh and the verified one, and settleMs have passed; a cloaked window nobody is working on is sent to
// relocation again (never left cloaked for good).
inline Decision Decide(Event e, const Obs& o) {
    if (!o.haveWindow) return {};
    const char* why = nullptr;
    if (e == Event::DisplayChange || e == Event::DpiChanged || e == Event::SettingChange || e == Event::DeviceChange) why = EventName(e);
    else if (o.metricsNow && o.metricsAtResolve && o.metricsNow != o.metricsAtResolve) why = "virtual-screen metrics changed";
    else if (o.layoutNow && o.layoutAtResolve && o.layoutNow != o.layoutAtResolve) why = "monitor layout changed";
    else if (o.targetKnown && (!o.liveOk || !Same(o.live, o.target))) why = "the target display moved or vanished";
    else if (o.visible && !o.cloaked && !(o.targetKnown && Inside(o.window, o.target))) why = "window not inside the target";
    if (why) return { kCloak | kInvalidate | kRelocate, why };
    if (!o.cloaked || o.pending) return {};
    const bool onTarget = o.targetKnown && o.liveOk && Same(o.live, o.target) && Inside(o.window, o.target);
    if (!o.placed || !onTarget) return { kRelocate, "cloaked, not verified on the target" };
    if (!o.layoutNow || o.layoutNow != o.layoutAtResolve) return {};
    if (o.msSinceTrigger < o.settleMs) return {};
    return { kUncloak, "verified on the target, layout stable" };
}
// after a relocation: verified when the window IS the freshly resolved target, the monitor still has that rect and the layout did
// not change while it was resolved and moved
inline bool PlacementVerified(const Rect& target, const Rect& window, bool liveOk, const Rect& live, uint64_t layoutBefore, uint64_t layoutAfter) {
    return !Empty(target) && Same(window, target) && liveOk && Same(live, target) && layoutBefore && layoutBefore == layoutAfter;
}
// no target after a change: stay cloaked and retry; refuse after graceMs (a monitor coming online can hide the virtual display from
// the enumeration for a moment)
inline bool RefuseNow(unsigned msWithoutTarget, unsigned graceMs) { return msWithoutTarget >= graceMs; }

// ---- DirectInput cooperative level --------------------------------------------------------------------------------------------
// An exclusive DirectInput mouse hides and recentres the REAL cursor (PC run 20261029_j13pc: Liam's cursor kept jumping to the
// centre of his monitor during a headless battle). Under headless every device is non-exclusive (never captures the cursor) and
// foreground-only (it cannot acquire while another process has the foreground, so the game never reads Liam's mouse or keyboard);
// DISCL_NOWINKEY is dropped. dinput.h values.
enum : uint32_t { kDisclExclusive = 1u, kDisclNonExclusive = 2u, kDisclForeground = 4u, kDisclBackground = 8u, kDisclNoWinKey = 0x10u };
inline uint32_t GateCoopLevel(uint32_t) { return kDisclNonExclusive | kDisclForeground; }

// ---- dialogs ----------------------------------------------------------------------------------------------------------------------
// MessageBox under headless is never shown (it would open on the primary): logged, and answered with its safe button.
enum : int { kIdOk = 1, kIdCancel = 2, kIdAbort = 3, kIdNo = 7 };
inline int MessageBoxAnswer(unsigned type) {
    switch (type & 0xFu) {
    case 0: return kIdOk;          // MB_OK
    case 2: return kIdAbort;       // MB_ABORTRETRYIGNORE
    case 4: return kIdNo;          // MB_YESNO
    default: return kIdCancel;     // MB_OKCANCEL, MB_YESNOCANCEL, MB_RETRYCANCEL, MB_CANCELTRYCONTINUE
    }
}

// ---- headless_status.json ---------------------------------------------------------------------------------------------------------
constexpr int kRefuseExitCode = 2160;   // the process exit code of a refusal (one documented code; proxy/README.md "Headless")
struct Status {
    unsigned long pid = 0;
    std::string launchId, state = "starting", detail, utc;   // state: starting | target_ok | on_virtual | refused
    bool haveTarget = false; Monitor target;
    long winW = 0, winH = 0, clientW = 0, clientH = 0, bbW = 0, bbH = 0;
    int exitCode = 0;
};
inline std::string JsonStr(const std::string& s) {
    std::string o = "\"";
    for (char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += c; }
        else if ((unsigned char)c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", (unsigned char)c); o += b; }
        else o += c;
    }
    return o + "\"";
}
inline std::string StatusJson(const Status& s) {
    char b[160];
    std::string j = "{\"pid\": " + std::to_string(s.pid) + ", \"launch_id\": " + JsonStr(s.launchId) + ", \"state\": " + JsonStr(s.state) +
                    ", \"detail\": " + JsonStr(s.detail) + ", \"target\": ";
    if (s.haveTarget) {
        snprintf(b, sizeof b, "[%ld, %ld, %ld, %ld]", s.target.rc.l, s.target.rc.t, s.target.rc.r, s.target.rc.b);
        j += "{\"device\": " + JsonStr(s.target.device) + ", \"adapter\": " + JsonStr(s.target.adapter) + ", \"monitor\": " + JsonStr(s.target.monitor) +
             ", \"rect\": " + b + "}";
    } else j += "null";
    snprintf(b, sizeof b, ", \"window\": [%ld, %ld], \"client\": [%ld, %ld], \"backbuffer\": [%ld, %ld], \"exit_code\": %d", s.winW, s.winH, s.clientW,
             s.clientH, s.bbW, s.bbH, s.exitCode);
    return j + b + ", \"written_utc\": " + JsonStr(s.utc) + "}\n";
}

}  // namespace dg
}  // namespace wsp
