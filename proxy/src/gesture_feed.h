#pragma once
// gesture_feed.h - the gesture layer's feed (W6), platform-free; host-tested by proxy/tests/test_gesture.cpp and test_dev.cpp.
//   - window messages -> state-machine events (the message numbers are Win32's, written out so the host tests feed real ones), and
//     the rule that every key message passes: only mouse messages inside a gesture are ever swallowed (Alt+F4 and Alt+Tab included)
//   - the planner: the pose a gesture shows and commits, with the mid-gesture switch and its rebase (empire-remastered controls-v2:
//     move -> rotate turns the block where it now stands, rotate -> move carries the turned block on, translating it)
//   - the `gesture` control-verb grammar (dev.cpp runs it; gesture.cpp feeds the same window messages real input sends)
#include "gesture_math.h"
#include "gesture_sm.h"
#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>

namespace wsp {
namespace gest {

// ---- window messages ------------------------------------------------------------------------------------------------------------
constexpr uint32_t
    kWmKillFocus = 0x0008, kWmActivateApp = 0x001C, kWmKeyDown = 0x0100, kWmKeyUp = 0x0101, kWmChar = 0x0102, kWmSysKeyDown = 0x0104,
    kWmSysKeyUp = 0x0105, kWmSysChar = 0x0106, kWmMouseMove = 0x0200, kWmLButtonDown = 0x0201, kWmLButtonUp = 0x0202, kWmLButtonDblClk = 0x0203,
    kWmRButtonDown = 0x0204, kWmRButtonUp = 0x0205, kWmRButtonDblClk = 0x0206, kWmMButtonDown = 0x0207, kWmMButtonUp = 0x0208, kWmMouseWheel = 0x020A;
constexpr uint32_t kVkTab = 0x09, kVkShift = 0x10, kVkControl = 0x11, kVkMenu = 0x12, kVkEscape = 0x1B, kVkF4 = 0x73,
                       kVkLShift = 0xA0, kVkRShift = 0xA1, kVkLControl = 0xA2, kVkRControl = 0xA3, kVkLMenu = 0xA4, kVkRMenu = 0xA5;
constexpr uint32_t kMkLButton = 0x0001, kMkRButton = 0x0002, kMkShift = 0x0004, kMkControl = 0x0008;

enum MsgClass { kClsOther = 0, kClsMouse = 1, kClsKey = 2, kClsFocus = 3 };
inline MsgClass Classify(uint32_t msg, uint32_t wp) {
    switch (msg) {
    case kWmMouseMove: case kWmLButtonDown: case kWmLButtonUp: case kWmLButtonDblClk: case kWmRButtonDown: case kWmRButtonUp:
    case kWmRButtonDblClk: case kWmMButtonDown: case kWmMButtonUp: case kWmMouseWheel: return kClsMouse;
    case kWmKeyDown: case kWmKeyUp: case kWmSysKeyDown: case kWmSysKeyUp: case kWmChar: case kWmSysChar: return kClsKey;
    case kWmKillFocus: return kClsFocus;
    case kWmActivateApp: return wp ? kClsOther : kClsFocus;
    default: return kClsOther;
    }
}
inline bool IsModifierKey(uint32_t vk) {
    return vk == kVkShift || vk == kVkControl || vk == kVkMenu || (vk >= kVkLShift && vk <= kVkRMenu);
}

struct FeedOut {
    Out sm;                  // what the state machine said
    Action action = kPass;   // what happens to the message (keys and focus: always kPass)
    bool needsEligibility = false;   // a press that would start a gesture: the caller asks the adapter and calls Feed again with it
    bool fed = false;        // the message reached the state machine
};
// One message. `mods` = the modifier set held now (the window procedure reads the keyboard state; the ctl verb injects its own).
// `mouseToEngine` = the RmlUi stage gave this mouse message to the engine (a message RmlUi took never reaches the gestures).
// A press that would start a gesture returns needsEligibility unless `eligibilityKnown`; the caller then calls again with `eligible`.
inline FeedOut Feed(Machine& m, uint32_t msg, uint32_t wp, int x, int y, unsigned mods, bool mouseToEngine, bool eligibilityKnown = true, bool eligible = false, int force = kNone) {
    FeedOut f;
    const MsgClass c = Classify(msg, wp);
    Event e; e.x = x; e.y = y; e.mods = mods;
    if (c == kClsFocus) { e.type = kDeactivate; f.sm = m.On(e); f.fed = true; f.action = kPass; return f; }
    if (c == kClsKey) {
        const bool down = msg == kWmKeyDown || msg == kWmSysKeyDown, up = msg == kWmKeyUp || msg == kWmSysKeyUp;
        if (down && wp == kVkEscape) { e.type = kEsc; f.sm = m.On(e); f.fed = true; }
        else if ((down || up) && IsModifierKey(wp)) { e.type = kMods; f.sm = m.On(e); f.fed = true; }
        f.action = kPass;   // the rule: a key message is never swallowed
        return f;
    }
    if (c != kClsMouse || !mouseToEngine) return f;
    switch (msg) {
    case kWmMouseMove: e.type = kMouseMove; e.lHeld = (wp & kMkLButton) != 0; e.hasMods = true; break;
    case kWmLButtonDown: case kWmLButtonDblClk:
        e.type = kLDown;
        if (m.WouldStart(mods, force) && !eligibilityKnown) { f.needsEligibility = true; return f; }
        e.eligible = eligible; e.force = force;
        break;
    case kWmLButtonUp: e.type = kLUp; break;
    case kWmRButtonDown: case kWmRButtonDblClk: e.type = kRDown; break;
    case kWmRButtonUp: e.type = kRUp; break;
    default: return f;   // middle button, wheel: never the gestures'
    }
    f.sm = m.On(e); f.fed = true; f.action = f.sm.action;
    return f;
}
// The left-button flag cleared (kPassNoButton): the engine sees hover and edge scroll, never a drag.
inline uint32_t ClearLButton(uint32_t wp) { return wp & ~(uint32_t)kMkLButton; }

// ---- the planner ----------------------------------------------------------------------------------------------------------------
struct PlanParams {
    double shortDragM = 3.0;   // a move line shorter than this keeps the widths and moves the block centre to the press point
    double pivotFwdM = 0.0;    // the rotate pivot, metres ahead of the block centre along its mean facing (0 = in place)
    double rotGain = kRotGainDefault;   // degrees per 1000 px at a 3840-wide client
    int rotSign = 1;           // +1: mouse right turns clockwise from above
    double width = 0;          // the client width the rotate gain scales with
};
struct Planner {
    PlanParams p;
    std::vector<Unit> start;   // the selection at the press
    std::vector<Unit> base;    // the pose the current segment starts from
    int kind = kNone;
    bool line = false;         // the first move segment: the press point is one end of the drawn line
    V2 g0; int px0 = 0;        // the segment's start: ground point and cursor x
    V2 pivot;                  // the rotate segment's fixed pivot
    int segments = 0;

    void Begin(const std::vector<Unit>& sel, int k, V2 press, int pressX) {
        start = base = sel; kind = k; line = k == kMove; g0 = press; px0 = pressX; segments = 1;
        pivot = RotatePivotFwd(base, p.pivotFwdM);
    }
    // The pose for the cursor at ground point g, screen x px.
    std::vector<Unit> Pose(V2 g, int px) const {
        if (kind == kRotate) return OrbitPose(base, pivot, Theta(px));
        if (line) return LineLayout(base, g0, g, p.shortDragM).t;
        return BlockMove(base, g0, g);
    }
    double Theta(int px) const { return kind == kRotate ? DxAngleSigned((double)(px - px0), p.width, p.rotGain, p.rotSign) : 0.0; }
    // The kind switched with the cursor at (g, px). Active: the pose so far becomes the new base (the rebase). Pending (nothing shown
    // yet): only the kind changes; the press point stays the segment start.
    void Switch(int newKind, V2 g, int px, bool active) {
        if (active) { base = Pose(g, px); g0 = g; px0 = px; line = false; ++segments; }
        else line = newKind == kMove && segments == 1;
        kind = newKind;
        pivot = RotatePivotFwd(base, p.pivotFwdM);
    }
};

// ---- the `gesture` control verb ---------------------------------------------------------------------------------------------------
// gesture press|move|release <x> <y> [mods] | cancel [esc|right] | plan | info
//   x y: client pixels; mods: none or a '+'-joined set of alt, ctrl, shift (default none).
struct GestureArgs { std::string op, how = "esc"; int x = 0, y = 0; unsigned mods = 0; std::string error; };
inline bool GestureInt(const std::string& s, int& out) {
    if (s.empty() || s.size() > 7) return false;
    size_t i = s[0] == '-' ? 1 : 0;
    if (i == s.size()) return false;
    for (; i < s.size(); ++i) if (s[i] < '0' || s[i] > '9') return false;
    out = atoi(s.c_str()); return true;
}
inline bool ParseMods(const std::string& s, unsigned& out) {
    out = 0;
    if (s == "none") return true;
    size_t a = 0;
    while (a <= s.size()) {
        size_t b = s.find('+', a); if (b == std::string::npos) b = s.size();
        const std::string t = s.substr(a, b - a);
        if (t == "alt") out |= kModAlt; else if (t == "ctrl") out |= kModCtrl; else if (t == "shift") out |= kModShift; else return false;
        a = b + 1;
    }
    return out != 0;
}
inline const char* GestureVerbs() { return "gesture press|move|release <x> <y> [none|alt|ctrl|shift joined by +], gesture cancel [esc|right], gesture plan, gesture info"; }
inline GestureArgs ParseGestureArgs(const std::string& arg) {
    GestureArgs a;
    std::vector<std::string> t; std::string cur;
    for (char c : arg) { if (c == ' ' || c == '\t') { if (!cur.empty()) t.push_back(cur); cur.clear(); } else cur += c; }
    if (!cur.empty()) t.push_back(cur);
    if (t.empty()) { a.error = std::string("gesture needs an operation (") + GestureVerbs() + ")"; return a; }
    a.op = t[0];
    const size_t n = t.size();
    if (a.op == "press" || a.op == "move" || a.op == "release") {
        if (n < 3 || n > 4 || !GestureInt(t[1], a.x) || !GestureInt(t[2], a.y)) { a.error = "gesture " + a.op + " needs <x> <y> [mods]"; return a; }
        if (a.x < 0 || a.y < 0 || a.x > 32767 || a.y > 32767) { a.error = "gesture " + a.op + ": x and y are client pixels (0-32767)"; return a; }
        if (n == 4 && !ParseMods(t[3], a.mods)) { a.error = "gesture " + a.op + ": mods are none or alt, ctrl, shift joined by + (e.g. alt+ctrl)"; return a; }
    } else if (a.op == "cancel") {
        if (n > 2) { a.error = "gesture cancel takes esc or right"; return a; }
        if (n == 2) { if (t[1] != "esc" && t[1] != "right") { a.error = "gesture cancel takes esc or right"; return a; } a.how = t[1]; }
    } else if (a.op == "plan" || a.op == "info") {
        if (n != 1) a.error = "gesture " + a.op + " takes no argument";
    } else a.error = "gesture: unknown operation '" + a.op + "' (" + GestureVerbs() + ")";
    return a;
}

}  // namespace gest
}  // namespace wsp
