// test_display_guard.cpp - host tests for core/display_guard.h (J13 headless runs): target selection in Liam's topologies, the mode
// list, the create/show/style/position gates, the topology guard's decisions, and a millisecond simulation that drives the same
// functions the way headless.cpp does (guard poll every 4 ms, Present every 16 ms) through the display changes seen on the earlier remaster and
// counts the milliseconds a game window is visible, uncloaked and overlapping a REAL monitor. Plus source lints for headless.cpp.
// Built and run by proxy/tools/build.sh tests.
#include "testkit.h"
#include "display_guard.h"
#include "generated/tables.h"
#include <set>

using namespace wsp;
using namespace wsp::dg;

namespace {
const char* kVdd = "Virtual Display Driver";
Monitor Mon(const char* dev, const char* adapter, const char* mon, Rect rc, bool primary) { Monitor m; m.device = dev; m.adapter = adapter; m.monitor = mon; m.rc = rc; m.primary = primary; m.dpi = 96; return m; }
// 2026-10-29 (vdisplay_probe): 4K primary, Dell left, the virtual display touching the primary only at a corner (3839,2160)
std::vector<Monitor> TopoToday() {
    return { Mon("\\\\.\\DISPLAY1", "NVIDIA GeForce RTX 4090", "Generic PnP Monitor", R(0, 0, 3840, 2160), true),
             Mon("\\\\.\\DISPLAY2", "NVIDIA GeForce RTX 4090", "Dell S2721DGF (HDMI2)", R(-2560, 327, 2560, 1440), false),
             Mon("\\\\.\\DISPLAY10", kVdd, "Generic PnP Monitor", R(3839, 2160, 3840, 2160), false) };
}
// the earlier remaster 2026-10-20/28: the 4K monitor not attached, the Dell primary at 0,0, the virtual display at 2560,1440
std::vector<Monitor> TopoDellPrimary() {
    return { Mon("\\\\.\\DISPLAY2", "NVIDIA GeForce RTX 4090", "Dell S2721DGF (HDMI2)", R(0, 0, 2560, 1440), true),
             Mon("\\\\.\\DISPLAY10", kVdd, "Generic PnP Monitor", R(2560, 1440, 3840, 2160), false) };
}
bool IsReal(const Monitor& m) { return !NameMatches(m, kVdd); }

void TestSelect() {
    long w = 0, h = 0;
    CHECK(ParseSize("3840x2160", w, h)); CHECK_EQ(w, 3840L); CHECK_EQ(h, 2160L);
    CHECK(ParseSize("1920X1080", w, h)); CHECK(!ParseSize("3840", w, h)); CHECK(!ParseSize("x2160", w, h)); CHECK(!ParseSize("-1x5", w, h));
    CHECK(!ParseSize("3840x2160 ", w, h)); CHECK(!ParseSize("10x10", w, h));

    Pick p = SelectTarget(TopoToday(), kVdd, 3840, 2160);
    CHECK_EQ(p.index, 2);                                            // by name, not the 4K primary of the same size
    p = SelectTarget(TopoDellPrimary(), kVdd, 3840, 2160); CHECK_EQ(p.index, 1);
    p = SelectTarget(TopoToday(), "virtual display", 3840, 2160); CHECK_EQ(p.index, 2);   // case-insensitive substring
    // wanted size missing on the virtual display (1440p before Liam's driver edit): refused, never the Dell that IS 2560x1440
    p = SelectTarget(TopoToday(), kVdd, 2560, 1440); CHECK_EQ(p.index, -1); CHECK(p.why.find("3840x2160") != std::string::npos);
    p = SelectTarget(TopoToday(), kVdd, 1920, 1080); CHECK_EQ(p.index, -1);
    // no virtual display at all: refused, never the primary or the first non-primary
    auto noV = TopoToday(); noV.pop_back();
    p = SelectTarget(noV, kVdd, 3840, 2160); CHECK_EQ(p.index, -1); CHECK(p.why.find("no display named") != std::string::npos);
    p = SelectTarget(noV, kVdd, 2560, 1440); CHECK_EQ(p.index, -1);
    // the virtual display made primary: refused
    auto vPrim = TopoDellPrimary(); vPrim[0].primary = false; vPrim[1].primary = true;
    p = SelectTarget(vPrim, kVdd, 3840, 2160); CHECK_EQ(p.index, -1); CHECK(p.why.find("primary") != std::string::npos);
    // two virtual displays at the size: ambiguous, refused
    auto two = TopoToday(); two.push_back(Mon("\\\\.\\DISPLAY11", kVdd, "Generic PnP Monitor", R(7679, 2160, 3840, 2160), false));
    p = SelectTarget(two, kVdd, 3840, 2160); CHECK_EQ(p.index, -1); CHECK(p.why.find("ambiguous") != std::string::npos);
    // ... unless only one has the wanted size
    two[3].rc = R(7679, 2160, 1920, 1080);
    CHECK_EQ(SelectTarget(two, kVdd, 3840, 2160).index, 2); CHECK_EQ(SelectTarget(two, kVdd, 1920, 1080).index, 3);
    CHECK_EQ(SelectTarget(TopoToday(), "", 3840, 2160).index, -1);   // no name: refused
    // the GDI number does not matter (the earlier remaster saw 20, 21, 23)
    auto renum = TopoToday(); renum[2].device = "\\\\.\\DISPLAY23"; CHECK_EQ(SelectTarget(renum, kVdd, 3840, 2160).index, 2);
}

void TestModes() {
    std::vector<Mode> raw = { { 3840, 2160, 240 }, { 3840, 2160, 60 }, { 3840, 2160, 60 }, { 1920, 1080, 60 }, { 0, 0, 0 } };
    std::vector<Mode> m = ModeList(raw);
    CHECK_EQ(m.size(), (size_t)3); CHECK_EQ(m[0].w, 1920u); CHECK_EQ(m[1].hz, 60u); CHECK_EQ(m[2].hz, 240u);
    CHECK(ModesStr(m) == "1920x1080@60 3840x2160@60 3840x2160@240"); CHECK(ModesStr({}) == "(none)");
    CHECK(AnswersFormat(kFmtX8R8G8B8)); CHECK(AnswersFormat(kFmtA8R8G8B8)); CHECK(!AnswersFormat(23 /* R5G6B5 */));
}

void TestCreateShowStyle() {
    const Rect t = R(3839, 2160, 3840, 2160);
    CreateIn in; in.x = 0; in.y = 0; in.w = 3840; in.h = 2160; in.style = kWsVisible | kWsCaption | kWsSysMenu; in.exStyle = kWsExAppWindow;
    CreateOut o = GateCreate(in, true, t);
    CHECK(!o.refuse); CHECK(!o.helper); CHECK(o.showAfter);
    CHECK(!(o.v.style & kWsVisible)); CHECK(o.v.style & kWsPopup); CHECK(!(o.v.style & kWsCaption));   // created hidden, borderless
    CHECK(o.v.exStyle & kWsExNoActivate); CHECK(o.v.exStyle & kWsExToolWindow); CHECK(!(o.v.exStyle & kWsExAppWindow));
    CHECK_EQ(o.v.x, 3839L); CHECK_EQ(o.v.y, 2160L); CHECK_EQ(o.v.w, 3840L); CHECK_EQ(o.v.h, 2160L);   // never at 0,0 first
    in.w = kCwUseDefault; in.h = kCwUseDefault; in.x = kCwUseDefault; o = GateCreate(in, true, t); CHECK_EQ(o.v.w, 3840L); CHECK_EQ(o.v.x, 3839L);
    in.w = 5000; in.h = 3000; o = GateCreate(in, true, t); CHECK_EQ(o.v.w, 3840L); CHECK_EQ(o.v.h, 2160L);   // never larger than the target
    in.style = 0; o = GateCreate(in, true, t); CHECK(!o.showAfter);
    in.w = 1; in.h = 1; in.style = kWsVisible; o = GateCreate(in, true, t); CHECK(o.helper); CHECK(o.v.style & kWsVisible);   // 1x1 helper: left alone
    in.w = 800; in.h = 600; o = GateCreate(in, false, Rect{}); CHECK(o.refuse);           // no target: refused
    in.style = kWsChild | kWsVisible; o = GateCreate(in, false, Rect{}); CHECK(!o.refuse); CHECK(o.v.style & kWsVisible);   // child windows untouched

    CHECK(!(GateStyle(kWsVisible | kWsCaption, false) & kWsVisible)); CHECK(GateStyle(kWsVisible | kWsCaption, true) & kWsVisible);
    CHECK(!(GateStyle(kWsCaption | kWsThickFrame, true) & (kWsCaption | kWsThickFrame))); CHECK(GateStyle(0, true) & kWsPopup);
    CHECK(GateExStyle(kWsExAppWindow | kWsExTopmost) == (kWsExNoActivate | kWsExToolWindow));

    CHECK(GateShow(kSwHide, false, false) == Show::Pass);
    for (int c : { kSwShowMinimized, kSwMinimize, kSwShowMinNoActive, kSwForceMinimize }) CHECK(GateShow(c, true, true) == Show::Hide);
    CHECK(GateShow(1 /* SW_SHOWNORMAL */, true, true) == Show::ShowNA);
    CHECK(GateShow(3 /* SW_SHOWMAXIMIZED */, false, true) == Show::PlaceThenShowNA);
    CHECK(GateShow(5 /* SW_SHOW */, true, false) == Show::Refuse);

    CHECK(GateDevice(true, 3840, 2160, 3840, 2160) == Device::Game);
    CHECK(GateDevice(true, 1, 1, 3840, 2160) == Device::Helper);             // the battle loader's 1x1 helper device
    CHECK(GateDevice(false, 1, 1, 3840, 2160) == Device::Refuse);            // fullscreen: never, whatever the size
    CHECK(GateDevice(false, 3840, 2160, 3840, 2160) == Device::Refuse);
    CHECK(GateDevice(true, 2560, 1440, 3840, 2160) == Device::Refuse);
    CHECK(GateDevice(true, 0, 0, 3840, 2160) == Device::Refuse);             // unresolved size: refuse
    for (uint32_t f : { kDisclExclusive | kDisclForeground, kDisclExclusive | kDisclForeground | kDisclNoWinKey, kDisclNonExclusive | kDisclBackground, 0u })
        CHECK(GateCoopLevel(f) == (kDisclNonExclusive | kDisclForeground));   // never exclusive, never background
    CHECK(MessageBoxAnswer(0) == kIdOk); CHECK(MessageBoxAnswer(1) == kIdCancel); CHECK(MessageBoxAnswer(4 | 0x30) == kIdNo); CHECK(MessageBoxAnswer(2) == kIdAbort);
}

void TestGatePos() {
    Pos p; p.x = 0; p.y = 0; p.cx = 3840; p.cy = 2160;                       // the engine moves its window (onto the primary, say)
    PosVerdict v = GatePos(p, false, true, true, false);
    CHECK(v.changed); CHECK((v.out.flags & (kSwpNoMove | kSwpNoSize)) == (kSwpNoMove | kSwpNoSize)); CHECK(v.out.flags & kSwpNoActivate); CHECK(!v.cloak);
    v = GatePos(p, true, true, true, false);                                  // the guard's own relocation passes (activation stripped)
    CHECK(!(v.out.flags & kSwpNoMove)); CHECK(v.out.flags & kSwpNoActivate);
    p.flags = kSwpNoMove | kSwpNoSize | kSwpNoActivate; CHECK(!GatePos(p, false, true, true, false).changed);   // z-order only, already no-activate
    p.flags = kSwpHideWindow; v = GatePos(p, false, false, false, false); CHECK(!(v.out.flags & kSwpNoMove)); CHECK(!v.cloak);   // hiding passes
    p.flags = kSwpNoMove | kSwpNoSize | kSwpShowWindow;
    v = GatePos(p, false, true, true, false); CHECK(v.out.flags & kSwpShowWindow); CHECK(!v.cloak);          // show on the target: fine
    v = GatePos(p, false, true, false, false); CHECK(!(v.out.flags & kSwpShowWindow)); CHECK(v.cloak);       // show off the target: dropped, cloak
    v = GatePos(p, false, false, true, false); CHECK(!(v.out.flags & kSwpShowWindow)); CHECK(v.cloak);       // target being re-resolved: dropped
    v = GatePos(p, false, false, false, true); CHECK(v.out.flags & kSwpShowWindow); CHECK(!v.cloak);         // already cloaked: invisible anyway
    p.flags = kSwpShowWindow; v = GatePos(p, false, true, false, false);                                       // move + show off target: both dropped
    CHECK((v.out.flags & (kSwpNoMove | kSwpNoSize)) == (kSwpNoMove | kSwpNoSize)); CHECK(!(v.out.flags & kSwpShowWindow));
}

void TestOwnMove() {
    OwnMove m; m.armed = true; m.want = R(3840, 0, 3840, 2160); m.at = 10.0;
    Pos p; p.x = 3840; p.y = 0; p.cx = 3840; p.cy = 2160; p.flags = kSwpNoActivate | kSwpNoZOrder | kSwpAsync;
    CHECK(IsOwnMove(m, p, 10.05));                                   // the guard's async move, handled later on the window's thread
    CHECK(!IsOwnMove(m, p, 10.0 + kOwnMoveMs / 1000.0 + 0.01));       // stale record
    CHECK(!IsOwnMove(m, p, 9.0));                                     // before the arming
    Pos q = p; q.x = 0; CHECK(!IsOwnMove(m, q, 10.05));               // the engine's own move elsewhere
    q = p; q.cx = 1920; CHECK(!IsOwnMove(m, q, 10.05));
    q = p; q.flags |= kSwpNoMove; CHECK(!IsOwnMove(m, q, 10.05));     // a z-order-only call is not a placement
    OwnMove off; CHECK(!IsOwnMove(off, p, 0.0));
    // through the gate: recognised -> the move passes; unrecognised (the J13 thread-id test on another thread) -> dropped
    CHECK(!(GatePos(p, IsOwnMove(m, p, 10.05), false, false, true).out.flags & kSwpNoMove));
    CHECK(GatePos(p, false, false, false, true).out.flags & kSwpNoMove);
}

// W18 (B22): at a scaled target a DPI-unaware window thread sees the armed rect in logical pixels
void TestOwnMoveLogical() {
    for (int pct : { 125, 150 }) {
        const Rect phys = R(3839, 2160, 3840, 2160);
        const Rect lg = Rect{ phys.l * 100 / pct, phys.t * 100 / pct, phys.r * 100 / pct, phys.b * 100 / pct };
        OwnMove m; m.armed = true; m.want = phys; m.logical = lg; m.haveLogical = true; m.at = 10.0;
        auto at = [&](const Rect& r) { Pos p; p.x = r.l; p.y = r.t; p.cx = Width(r); p.cy = Height(r); p.flags = kSwpNoActivate | kSwpAsync; return p; };
        CHECK(IsOwnMove(m, at(lg), 10.05));                      // exact logical
        CHECK(IsOwnMove(m, at(phys), 10.05));                    // physical still accepted
        for (int e = 0; e < 4; ++e) for (int d : { -1, 1 }) {    // one pixel off on each edge: rounding
            Rect r = lg; (e == 0 ? r.l : e == 1 ? r.t : e == 2 ? r.r : r.b) += d;
            CHECK(IsOwnMove(m, at(r), 10.05));
        }
        for (int e = 0; e < 4; ++e) for (int d : { -2, 2 }) {    // two pixels off: refused
            Rect r = lg; (e == 0 ? r.l : e == 1 ? r.t : e == 2 ? r.r : r.b) += d;
            CHECK(!IsOwnMove(m, at(r), 10.05));
        }
        CHECK(!IsOwnMove(m, at(lg), 10.0 + kOwnMoveMs / 1000.0 + 0.01));   // expired
        Pos p = at(lg); p.flags |= kSwpNoMove; CHECK(!IsOwnMove(m, p, 10.05));
        p = at(lg); p.flags |= kSwpNoSize; CHECK(!IsOwnMove(m, p, 10.05));
        OwnMove off = m; off.armed = false; CHECK(!IsOwnMove(off, at(lg), 10.05));
        OwnMove nol = m; nol.haveLogical = false; CHECK(!IsOwnMove(nol, at(lg), 10.05));   // no logical rect armed: only the physical one
    }
}

void TestSweep() {
    const Rect t = R(3839, 2160, 3840, 2160);
    CHECK(SweepHides(true, false, R(0, 0, 640, 480), true, t));       // a DLL's dialog on the primary
    CHECK(!SweepHides(true, false, R(4000, 2300, 640, 480), true, t));// on the target: left alone
    CHECK(SweepHides(true, false, R(4000, 2300, 640, 480), false, t));// target being re-resolved: fail closed
    CHECK(!SweepHides(false, false, R(0, 0, 640, 480), true, t));     // not visible
    CHECK(!SweepHides(true, true, R(0, 0, 3840, 2160), true, t));     // guarded: the gates and the guard own it
    CHECK(!SweepHides(true, false, R(0, 0, 1, 1), true, t));          // the engine's helper size
    CHECK(SweepHides(true, false, R(0, 0, 2, 400), true, t));         // thin but tall is not a helper
    CHECK(SweepDue(kSweepPolls)); CHECK(!SweepDue(kSweepPolls + 1)); CHECK(kSweepPolls * 4 <= 250u);
    // timeline: a DLL shows a window at 1500 ms on the primary; the guard polls every 4 ms (n from 1, as GuardThread counts)
    int visibleMs = 0; bool shown = false, hidden = false;
    for (int now = 0, n = 0; now < 3000; ++now) {
        if (now == 1500) shown = true;
        if (now % 4 == 0) { ++n; if (SweepDue((unsigned)n) && shown && !hidden && SweepHides(true, false, R(0, 0, 640, 480), true, t)) hidden = true; }
        if (shown && !hidden) ++visibleMs;
    }
    CHECK(hidden); CHECK(visibleMs <= (int)(kSweepPolls * 4));
    printf("  sweep: a DLL window after start-up hidden after %d ms (sweep every %u ms)\n", visibleMs, kSweepPolls * 4);
}

// W18 (B19): the show-time hook applies the sweep's rule to the one window that was just shown
void TestShowEvent() {
    const Rect t = R(3839, 2160, 3840, 2160), dll = R(0, 0, 640, 480);
    CHECK(ShowEventHides(true, true, true, true, false, dll, true, t));            // a DLL's window on the primary
    CHECK(!ShowEventHides(false, true, true, true, false, dll, true, t));          // not a window object (a caret, a menu)
    CHECK(!ShowEventHides(true, false, true, true, false, dll, true, t));          // a child window
    CHECK(!ShowEventHides(true, true, false, true, false, dll, true, t));          // another process
    CHECK(!ShowEventHides(true, true, true, false, false, dll, true, t));          // not visible
    CHECK(!ShowEventHides(true, true, true, true, true, dll, true, t));            // guarded: the gates own it
    CHECK(!ShowEventHides(true, true, true, true, false, R(0, 0, 1, 1), true, t)); // the engine's helper size
    CHECK(!ShowEventHides(true, true, true, true, false, R(4000, 2300, 640, 480), true, t));   // wholly inside the target
    CHECK(ShowEventHides(true, true, true, true, false, R(3000, 2000, 1000, 800), true, t));   // straddles the target's edge
    CHECK(ShowEventHides(true, true, true, true, false, R(4000, 2300, 640, 480), false, t));   // no target: fail closed
    // the rule is the sweep's, for every shape
    for (const Rect& r : { dll, R(4000, 2300, 640, 480), R(0, 0, 2, 400), R(0, 0, 8, 8) })
        for (int k = 0; k < 8; ++k)
            CHECK_EQ(ShowEventHides(true, true, true, (k & 1) != 0, (k & 2) != 0, r, (k & 4) != 0, t), SweepHides((k & 1) != 0, (k & 2) != 0, r, (k & 4) != 0, t));
    // timeline: shown at 1501 ms; the event hides it at once, the sweep alone would take up to kSweepPolls * 4 ms
    CHECK(kSweepPolls * 4 > 25u);
}

Obs Steady() {
    Obs o; o.haveWindow = true; o.visible = true; o.window = R(3839, 2160, 3840, 2160);
    o.targetKnown = true; o.target = o.window; o.liveOk = true; o.live = o.window;
    o.layoutNow = 42; o.layoutAtResolve = 42; o.metricsNow = 7; o.metricsAtResolve = 7; o.msSinceTrigger = 100000;
    return o;
}
void TestDecide() {
    Obs o = Steady();
    CHECK_EQ(Decide(Event::Tick, o).act, 0u);
    CHECK_EQ(Decide(Event::Tick, Obs{}).act, 0u);
    o.live = R(2560, 1440, 3840, 2160); CHECK_EQ(Decide(Event::Tick, o).act, kCloak | kInvalidate | kRelocate);
    o = Steady(); o.liveOk = false; CHECK_EQ(Decide(Event::Tick, o).act, kCloak | kInvalidate | kRelocate);
    o = Steady(); o.layoutNow = 43; CHECK(std::string(Decide(Event::Tick, o).why) == "monitor layout changed");
    o = Steady(); o.metricsNow = 8; CHECK(std::string(Decide(Event::Tick, o).why) == "virtual-screen metrics changed");
    o = Steady(); o.metricsNow = 0; o.layoutNow = 0; CHECK_EQ(Decide(Event::Tick, o).act, 0u);   // not gathered (Present): no trigger by itself
    for (Event e : { Event::DisplayChange, Event::DpiChanged, Event::SettingChange, Event::DeviceChange }) CHECK_EQ(Decide(e, Steady()).act, kCloak | kInvalidate | kRelocate);
    o = Steady(); o.window = R(0, 0, 3840, 2160); CHECK(std::string(Decide(Event::PosChanged, o).why) == "window not inside the target");
    o.visible = false; CHECK_EQ(Decide(Event::Tick, o).act, 0u);
    o = Steady(); o.cloaked = true; o.placed = true; o.msSinceTrigger = 499; CHECK_EQ(Decide(Event::Tick, o).act, 0u);
    o.msSinceTrigger = 500; CHECK_EQ(Decide(Event::Tick, o).act, kUncloak);
    o.pending = true; CHECK_EQ(Decide(Event::Tick, o).act, 0u);
    o.pending = false; o.layoutNow = 0; CHECK_EQ(Decide(Event::Tick, o).act, 0u);           // never uncloak without a fresh layout
    o.layoutNow = 42; o.placed = false; CHECK_EQ(Decide(Event::Tick, o).act, kRelocate);    // cloaked and nobody working on it
    const Rect t = R(3839, 2160, 3840, 2160);
    CHECK(PlacementVerified(t, t, true, t, 7, 7)); CHECK(!PlacementVerified(t, R(0, 0, 3840, 2160), true, t, 7, 7));
    CHECK(!PlacementVerified(t, t, true, t, 7, 8)); CHECK(!PlacementVerified(t, t, false, t, 7, 7)); CHECK(!PlacementVerified(t, t, true, t, 0, 0));
    CHECK(!RefuseNow(4999, 5000)); CHECK(RefuseNow(5000, 5000));
    CHECK(Layout(TopoToday()) != Layout(TopoDellPrimary()));
    auto a = TopoToday(); std::swap(a[0], a[2]); CHECK(Layout(a) == Layout(TopoToday()));   // order independent
    auto b = TopoToday(); b[2].rc = R(7680, 0, 3840, 2160); CHECK(Layout(b) != Layout(TopoToday()));
    CHECK(MetricsHash(3, -2560, 0, 10239, 4320) != MetricsHash(3, -2560, 0, 10240, 2160)); CHECK(MetricsHash(0, 0, 0, 0, 0) != 0);
}

void TestStatus() {
    Status s; s.pid = 1234; s.launchId = "20261029T120000Z-p1234"; s.state = "on_virtual"; s.detail = "a \"quoted\"\\path\n";
    s.haveTarget = true; s.target = TopoToday()[2]; s.winW = 3840; s.winH = 2160; s.bbW = 3840; s.bbH = 2160; s.utc = "2026-10-29T12:00:00Z";
    const std::string j = StatusJson(s);
    CHECK(j.find("\"state\": \"on_virtual\"") != std::string::npos); CHECK(j.find("\"rect\": [3839, 2160, 7679, 4320]") != std::string::npos);
    CHECK(j.find("\\\"quoted\\\"\\\\path\\u000a") != std::string::npos); CHECK(j.find("\"device\": \"\\\\\\\\.\\\\DISPLAY10\"") != std::string::npos);
    CHECK(j.find("\"exit_code\": 0") != std::string::npos);
    CHECK(j.find("\"relocations\": 0, \"written_utc\"") != std::string::npos);   // W18 (B23): 0 until the first relocation, before written_utc
    s.relocations = 3; const std::string j3 = StatusJson(s);
    CHECK(j3.find("\"relocations\": 3, \"written_utc\"") != std::string::npos);
    CHECK(j3.find("\"exit_code\": 0, \"relocations\"") != std::string::npos);
    Status r; r.state = "refused"; r.exitCode = kRefuseExitCode; CHECK(StatusJson(r).find("\"target\": null") != std::string::npos);
    CHECK(StatusJson(r).find("\"exit_code\": 2160") != std::string::npos);
}

// ---- the simulation -------------------------------------------------------------------------------------------------------------
// One game window, the guard thread (poll every 4 ms: metrics, layout, the target's live rect -> Decide), the render thread (Present
// every 16 ms: the post-check and any pending relocation, which re-resolves by name and size). Topology changes are scheduled.
struct Sim {
    std::vector<Monitor> mons;
    std::vector<std::pair<int, std::vector<Monitor>>> changes;   // at ms, the new monitor list
    long w = 3840, h = 2160;
    Rect window; bool visible = false, cloaked = false, targetKnown = false, pending = false, placed = false, haveWindow = false, refused = false;
    Rect target; std::string targetDev;
    uint64_t layoutAt = 0, metricsAt = 0;
    int lastTrigger = -100000, noTargetSince = -1;
    int onRealMs = 0, cloakedMs = 0, triggers = 0, relocations = 0;
    unsigned settle = 500, grace = 5000;
    // workerPresent: the game presents from a thread that does not own the window, so the guard's move is asynchronous and the
    // window's thread handles WM_WINDOWPOSCHANGING asyncLagMs later (J13 review should-fix 1); byRect = the fix (IsOwnMove), else
    // the J13 test (thread id, which never matches there)
    bool workerPresent = false, byRect = true; int asyncLagMs = 3, asyncAt = -1; Rect asyncWant; OwnMove own;

    uint64_t Metrics() const {   // count + bounding box of the desktop
        long l = 1 << 30, t = 1 << 30, r = -(1 << 30), b = -(1 << 30);
        for (auto& m : mons) { l = std::min(l, m.rc.l); t = std::min(t, m.rc.t); r = std::max(r, m.rc.r); b = std::max(b, m.rc.b); }
        return mons.empty() ? MetricsHash(0, 0, 0, 0, 0) : MetricsHash((int)mons.size(), (int)l, (int)t, (int)(r - l), (int)(b - t));
    }
    const Monitor* Live() const { for (auto& m : mons) if (m.device == targetDev) return &m; return nullptr; }
    Obs Observe(bool full) const {
        Obs o; o.haveWindow = haveWindow; o.visible = visible; o.cloaked = cloaked; o.window = window; o.targetKnown = targetKnown; o.target = target;
        const Monitor* l = Live(); o.liveOk = l != nullptr; if (l) o.live = l->rc;
        if (full) { o.layoutNow = Layout(mons); o.metricsNow = Metrics(); }
        o.layoutAtResolve = layoutAt; o.metricsAtResolve = metricsAt; o.pending = pending; o.placed = placed; o.settleMs = settle;
        return o;
    }
    void Apply(const Decision& d, int now) {
        if (d.act & kCloak) cloaked = true;
        if (d.act & kInvalidate) { targetKnown = false; placed = false; }
        if (d.act & kRelocate) pending = true;
        if (d.act & kCloak) { lastTrigger = now; ++triggers; }
        if (d.act & kUncloak) cloaked = false;
    }
    bool Resolve() {
        const Pick p = SelectTarget(mons, kVdd, w, h);
        if (p.index < 0) return false;
        target = mons[p.index].rc; targetDev = mons[p.index].device; return true;
    }
    void Relocate(int now) {
        const uint64_t before = Layout(mons);
        if (!Resolve()) { if (noTargetSince < 0) noTargetSince = now; if (RefuseNow((unsigned)(now - noTargetSince), grace)) { refused = true; visible = false; } return; }
        noTargetSince = -1;
        ++relocations;
        if (workerPresent) { own.armed = true; own.want = target; own.at = now / 1000.0; asyncWant = target; asyncAt = now + asyncLagMs; }
        else window = target;
        const Monitor* l = Live();
        if (PlacementVerified(target, window, l != nullptr, l ? l->rc : Rect{}, before, Layout(mons))) {
            placed = true; targetKnown = true; pending = false; layoutAt = before; metricsAt = Metrics();
        }
    }
    void Run(int endMs) {
        // start-up: target at Direct3DCreate9, window created hidden on it, shown with SW_SHOWNA
        if (!Resolve()) { refused = true; return; }
        window = target; targetKnown = true; placed = true; haveWindow = true; visible = true; layoutAt = Layout(mons); metricsAt = Metrics();
        size_t next = 0;
        for (int now = 0; now < endMs && !refused; ++now) {
            while (next < changes.size() && changes[next].first == now) mons = changes[next++].second;   // Windows changes the topology; the window stays put
            if (now == asyncAt) {   // the window's thread handles the guard's queued move (GuardProc's WM_WINDOWPOSCHANGING)
                Pos in; in.x = asyncWant.l; in.y = asyncWant.t; in.cx = Width(asyncWant); in.cy = Height(asyncWant); in.flags = kSwpNoActivate | kSwpAsync;
                const PosVerdict v = GatePos(in, byRect && IsOwnMove(own, in, now / 1000.0), targetKnown, targetKnown && Inside(window, target), cloaked);
                if (!(v.out.flags & kSwpNoMove)) window = asyncWant;
            }
            if (now % 4 == 0) { Obs o = Observe(true); o.msSinceTrigger = (unsigned)(now - lastTrigger); Apply(Decide(Event::Tick, o), now); }
            if (now % 16 == 0) {
                Obs o = Observe(false); o.msSinceTrigger = (unsigned)(now - lastTrigger); Apply(Decide(Event::Tick, o), now);
                if (pending) Relocate(now);
            }
            if (cloaked) ++cloakedMs;
            if (visible && !cloaked) for (auto& m : mons) if (IsReal(m) && Overlap(window, m.rc)) { ++onRealMs; break; }
        }
    }
};

void TestSimulation() {
    {   // steady: nothing happens, nothing is ever cloaked
        Sim s; s.mons = TopoToday(); s.Run(3000);
        CHECK(!s.refused); CHECK_EQ(s.onRealMs, 0); CHECK_EQ(s.cloakedMs, 0); CHECK_EQ(s.triggers, 0);
    }
    {   // the earlier remaster's incident (2026-10-22): Dell primary, the 4K monitor comes online as primary, Windows moves the virtual display;
        // the window's old rect (2560,1440) now overlaps the 4K monitor
        Sim s; s.mons = TopoDellPrimary(); s.changes.push_back({ 1001, TopoToday() }); s.Run(4000);
        CHECK(!s.refused); CHECK(s.onRealMs <= 4);                    // at most one poll interval, cloaked from the next poll on
        CHECK(Same(s.window, R(3839, 2160, 3840, 2160))); CHECK(!s.cloaked); CHECK(s.relocations >= 1);
        printf("  sim incident: %d ms visible on a real monitor (poll 4 ms), cloaked %d ms\n", s.onRealMs, s.cloakedMs);
    }
    {   // the mode tool moves the virtual display's origin mid-run (PC test d): never over a real monitor, ends uncloaked on it
        Sim s; s.mons = TopoToday(); auto moved = TopoToday(); moved[2].rc = R(3840, 0, 3840, 2160);
        s.changes.push_back({ 1000, moved }); s.Run(3000);
        CHECK(!s.refused); CHECK_EQ(s.onRealMs, 0); CHECK(Same(s.window, R(3840, 0, 3840, 2160))); CHECK(!s.cloaked);
        CHECK(s.cloakedMs >= 500);                                    // settled before uncloaking
    }
    {   // J13 should-fix 1: the same move with Present on a worker thread. Fixed: the async move is recognised by its rect, ends uncloaked
        Sim s; s.mons = TopoToday(); s.workerPresent = true; auto moved = TopoToday(); moved[2].rc = R(3840, 0, 3840, 2160);
        s.changes.push_back({ 1000, moved }); s.Run(3000);
        CHECK(!s.refused); CHECK_EQ(s.onRealMs, 0); CHECK(Same(s.window, R(3840, 0, 3840, 2160))); CHECK(!s.cloaked);
        // the J13 behaviour (own = same thread): the move is dropped every time and the window stays cloaked for good
        Sim o; o.mons = TopoToday(); o.workerPresent = true; o.byRect = false; o.changes.push_back({ 1000, moved }); o.Run(3000);
        CHECK(o.cloaked); CHECK(!Same(o.window, R(3840, 0, 3840, 2160))); CHECK_EQ(o.onRealMs, 0);
        printf("  sim worker-thread present: fixed ends on the target uncloaked; thread-id test still cloaked after %d ms\n", o.cloakedMs);
    }
    {   // a burst: the virtual display vanishes for 1.2 s (a monitor coming online) and returns elsewhere: recovers, never refuses
        Sim s; s.mons = TopoToday(); auto gone = TopoToday(); gone.pop_back(); auto back = TopoToday(); back[2].rc = R(-6400, 0, 3840, 2160);
        s.changes.push_back({ 1000, gone }); s.changes.push_back({ 2200, back }); s.Run(5000);
        CHECK(!s.refused); CHECK_EQ(s.onRealMs, 0); CHECK(Same(s.window, R(-6400, 0, 3840, 2160))); CHECK(!s.cloaked);
    }
    {   // the virtual display is disabled for good: cloaked at once, refused after the grace time, never on a real monitor
        Sim s; s.mons = TopoToday(); auto gone = TopoToday(); gone.pop_back();
        s.changes.push_back({ 1000, gone }); s.Run(9000);
        CHECK(s.refused); CHECK_EQ(s.onRealMs, 0);
    }
    {   // the virtual display changes to another size than the back buffer: no target at the size, refused
        Sim s; s.mons = TopoToday(); auto small = TopoToday(); small[2].rc = R(3839, 2160, 1920, 1080);
        s.changes.push_back({ 1000, small }); s.Run(9000);
        CHECK(s.refused); CHECK_EQ(s.onRealMs, 0);
    }
    {   // a refresh-rate-only switch (WM_DISPLAYCHANGE with nothing moved) is handled by the event path; here: the layout signature
        // of a primary switch (the Dell made primary while the 4K stays): the window is re-verified and stays on the target
        Sim s; s.mons = TopoToday(); auto sw = TopoToday(); sw[0].primary = false; sw[1].primary = true;
        s.changes.push_back({ 1000, sw }); s.Run(3000);
        CHECK(!s.refused); CHECK_EQ(s.onRealMs, 0); CHECK(!s.cloaked); CHECK(s.triggers >= 1);
    }
    {   // start-up in a topology without the virtual display: refused before any window exists
        Sim s; s.mons = TopoToday(); s.mons.pop_back(); s.Run(1000); CHECK(s.refused); CHECK_EQ(s.onRealMs, 0);
    }
}

std::string Strip(const std::string& s) {   // drop comments and string literals
    std::string o; size_t i = 0;
    while (i < s.size()) {
        if (s.compare(i, 2, "//") == 0) { while (i < s.size() && s[i] != '\n') ++i; continue; }
        if (s.compare(i, 2, "/*") == 0) { size_t e = s.find("*/", i + 2); i = e == std::string::npos ? s.size() : e + 2; continue; }
        if (s[i] == '"') { ++i; while (i < s.size() && s[i] != '"') { if (s[i] == '\\') ++i; ++i; } ++i; o += "\"\""; continue; }
        o += s[i++];
    }
    return o;
}

void TestLints() {
    const std::string raw = tk::ReadFile("core/headless.cpp"), hl = Strip(raw);
    CHECK(!raw.empty());
    // the driver is game-agnostic (it moves to warscape-core)
    for (const std::string& f : { std::string("core/headless.cpp"), std::string("core/display_guard.h") }) {
        std::string s = tk::ReadFile(f);
        for (size_t k; (k = s.find("empire-remastered")) != std::string::npos;) s.erase(k, 17);
        CHECK(s.find("apoleon") == std::string::npos); CHECK(s.find("mpire") == std::string::npos);
    }
    // hooks only through the existing machinery (IAT slots and vtable slots), never an inline detour
    CHECK(hl.find("MH_") == std::string::npos); CHECK(hl.find("VirtualProtect") == std::string::npos);
    // never takes the foreground or activation
    CHECK(raw.find("SetForegroundWindow(") == std::string::npos); CHECK(raw.find("SetActiveWindow(") == std::string::npos);
    CHECK(raw.find("BringWindowToTop(") == std::string::npos);
    // no display selector by index or GDI name, no fallback to the primary
    CHECK(raw.find("DISPLAY1") == std::string::npos); CHECK(raw.find("MonitorFromPoint(") == std::string::npos);
    // the headless driver runs only when the guard's plan allows hooks, and refuses (fails closed) otherwise
    CHECK(hl.find("rt.plan.engineHooks") != std::string::npos);
    // every key it reads by name is registered
    std::set<std::string> known; for (size_t i = 0; i < gen::kKeyCount; ++i) known.insert(gen::kKeys[i].id);
    for (const char* k : { "headless.enabled", "headless.size", "headless.display_name", "headless.settle_ms", "headless.refuse_grace_ms",
                           "headless.test_off_thread", "headless.test_dll_window_ms" }) {
        CHECK(known.count(k)); CHECK(raw.find(std::string("\"") + k + "\"") != std::string::npos);
    }
    // W18: the show hook is set up on the guard thread before its loop, the message drain sits outside the lock, and the status is rewritten after a verified relocation
    {
        const size_t gt = hl.find("DWORD WINAPI GuardThread"), loop = hl.find("for (unsigned n = 1", gt), hook = hl.find("SetWinEventHook(", gt);
        CHECK(gt != std::string::npos && loop != std::string::npos);
        CHECK(hook != std::string::npos && hook < loop);
        CHECK(hl.find("WINEVENT_OUTOFCONTEXT", hook) < loop);
        const size_t lk = hl.find("Lock l;", loop), mw = hl.find("MsgWaitForMultipleObjects(", loop), pm = hl.find("PeekMessageW(", loop);
        CHECK(mw != std::string::npos && pm != std::string::npos && lk != std::string::npos);
        CHECK(mw < lk && pm < lk);                                  // drained before the loop body takes the lock
        const size_t rl = hl.find("void RelocateLocked()"), ok = hl.find("PlacementVerified(", rl), end = hl.find("
}
", ok);
        CHECK(rl != std::string::npos && ok != std::string::npos && end != std::string::npos);
        const std::string succ = hl.substr(ok, end - ok);
        CHECK(succ.find("WriteStatus()") != std::string::npos);
        CHECK(succ.find("s_st.state") == std::string::npos);        // the state stays what it was
        CHECK(succ.find("++s_st.relocations") != std::string::npos);
    }
    // the release value is off: a normal install never runs headless
    for (size_t i = 0; i < gen::kKeyCount; ++i)
        for (const char* off : { "headless.enabled", "headless.test_off_thread", "headless.test_dll_window_ms" })   // test hooks too
            if (std::string(gen::kKeys[i].id) == off) CHECK(std::string(gen::kKeys[i].def) == "0");
}
}  // namespace

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    TestSelect(); TestModes(); TestCreateShowStyle(); TestGatePos(); TestOwnMove(); TestOwnMoveLogical(); TestSweep(); TestShowEvent(); TestDecide(); TestStatus(); TestSimulation(); TestLints();
    return tk::Done("test_display_guard");
}
