#pragma once
// ui_core.h - the RmlUi host's pure decisions (J30), host-tested by proxy/tests/test_ui_core.cpp; no Windows, no RmlUi here.
//   - the scale model (D19): dp ratio = back-buffer height / 1080 x ui.scale / 100, ui.scale 85..125 in steps of 5
//   - input routing: which events reach RmlUi, the engine or both (the contract a panel host builds on)
//   - the device lifecycle: which device the UI attaches to, and what to release or rebuild on Reset and re-creation
//   - the `ui` control-channel grammar (dev.cpp runs it; ui_host.cpp executes it on the render thread)
#include <string>
#include <vector>
#include <cstdint>
#include <cstdlib>
#include <algorithm>

namespace wsp {

// ---- scale model (D19) --------------------------------------------------------------------------------------------------------
struct UiScale { int percent = 100; bool changed = false; };   // changed: the request was out of range or off the 5 % grid
inline UiScale UiClampScale(long requested) {
    UiScale s;
    long p = requested;
    if (p < 85) p = 85;
    if (p > 125) p = 125;
    p = ((p + 2) / 5) * 5;            // nearest step of 5 (a tie goes up); 85..125 stays inside after rounding
    s.percent = (int)p;
    s.changed = p != requested;
    return s;
}
// The ratio RmlUi's context gets: every dp length and every font size is multiplied by it before layout and rasterising, so text is
// drawn by FreeType at its final pixel size (never a scaled bitmap).
inline float UiDpRatio(int backbufferHeight, int percent) {
    if (backbufferHeight <= 0) return 1.0f;
    return (float)((double)backbufferHeight / 1080.0 * (double)percent / 100.0);
}

// ---- input routing ------------------------------------------------------------------------------------------------------------
// The rule (brief J30): the pointer belongs to RmlUi only while it is over an interactive element; every other mouse event, including the
// move that ends the hover and every event of a press that began on the engine until all its buttons are released (empire-remastered input.cpp's pointer
// capture), reaches the engine unchanged. A press that began on RmlUi keeps RmlUi the owner until released (a scrollbar drag that leaves
// the bar). The wheel goes to RmlUi only over a scrollable element; the keyboard only while a text field has focus.
// RmlUi always sees pointer moves (it needs them for hover), so a move is "both" unless RmlUi owns the pointer.
enum class UiEv : uint8_t { Move, Down, Up, Wheel, Key, Char };
enum UiTo : uint8_t { kToNone = 0, kToRml = 1, kToEngine = 2, kToBoth = 3 };
struct UiRouteState {
    bool hoverInteractive = false;   // after RmlUi saw this event's position: the hover element is interactive (Context::IsMouseInteracting)
    bool overScrollable = false;     // an element under the pointer (or an ancestor) can scroll
    bool textFocus = false;          // a text field has focus
    unsigned engineButtons = 0;      // buttons whose press went to the engine and are still down (pointer capture)
    unsigned rmlButtons = 0;         // buttons whose press went to RmlUi and are still down
};
struct UiRoute { uint8_t to = kToNone; bool engineLeave = false; };
// button: 0 left, 1 right, 2 middle, 3/4 x buttons (only for Down/Up). `wasRmlOwner` is the owner after the previous event: when the
// pointer passes from the engine to RmlUi the engine gets one move far off-screen so its hover and tooltips clear (engineLeave).
inline UiRoute UiDecide(UiEv ev, int button, UiRouteState& s, bool wasRmlOwner) {
    UiRoute r;
    const unsigned bit = (button >= 0 && button < 8) ? (1u << button) : 0u;
    switch (ev) {
    case UiEv::Move:
        if (s.engineButtons) r.to = kToBoth;            // the engine's drag keeps every move; RmlUi still tracks hover
        else if (s.rmlButtons) r.to = kToRml;           // RmlUi's drag
        else if (s.hoverInteractive) { r.to = kToRml; r.engineLeave = !wasRmlOwner; }
        else r.to = kToBoth;                            // includes the move that ends a hover
        break;
    case UiEv::Down:
        if (s.engineButtons) { r.to = kToEngine; s.engineButtons |= bit; }          // a second button during an engine drag
        else if (s.rmlButtons) { r.to = kToRml; s.rmlButtons |= bit; }
        else if (s.hoverInteractive) { r.to = kToRml; s.rmlButtons |= bit; }
        else { r.to = kToEngine; s.engineButtons |= bit; }
        break;
    case UiEv::Up:
        if (s.engineButtons & bit) { r.to = kToEngine; s.engineButtons &= ~bit; }   // released anywhere, even over the document
        else if (s.rmlButtons & bit) { r.to = kToRml; s.rmlButtons &= ~bit; }
        else r.to = kToEngine;                          // a release we never saw pressed (focus change): unchanged
        break;
    case UiEv::Wheel:
        r.to = (!s.engineButtons && s.overScrollable) ? kToRml : kToEngine;
        break;
    case UiEv::Key: case UiEv::Char:
        r.to = s.textFocus ? kToRml : kToEngine;
        break;
    }
    return r;
}
// Who owns the pointer after an event: RmlUi while it holds a press, or hovers an interactive element with no engine capture.
inline bool UiRmlOwnsPointer(const UiRouteState& s) { return !s.engineButtons && (s.rmlButtons || s.hoverInteractive); }
// DirectInput arbitration: the mouse device's buttons (and wheel) are blanked while RmlUi owns them, movement always passes.
inline bool UiBlankDiButtons(const UiRouteState& s) { return UiRmlOwnsPointer(s); }
inline bool UiBlankDiWheel(const UiRouteState& s) { return !s.engineButtons && (s.overScrollable || s.rmlButtons); }
// B53 (W20): what the DirectInput hooks need, as one word the window thread publishes (InterlockedExchange) after every write of the
// route state, so the hooks read it once per call: no lock on the input path, no torn copy of the struct.
constexpr uint32_t kDiBlankButtons = 1, kDiBlankWheel = 2, kDiTextFocus = 4;
inline uint32_t UiDiMask(const UiRouteState& s) {
    return (UiBlankDiButtons(s) ? kDiBlankButtons : 0u) | (UiBlankDiWheel(s) ? kDiBlankWheel : 0u) | (s.textFocus ? kDiTextFocus : 0u);
}
// The DirectInput blank decision as a pure function of the published word (R1 finding 1: an inline `mask` was shadowed by the button
// bitmap in hk_DIState; a function over named inputs cannot be). Buttons: RmlUi owns them, or a gesture holds them. Wheel: RmlUi's word only.
inline bool UiDiBlankButtons(uint32_t diMask, bool gestureOwns) { return (diMask & kDiBlankButtons) != 0 || gestureOwns; }
inline bool UiDiBlankWheel(uint32_t diMask) { return (diMask & kDiBlankWheel) != 0; }
// Focus left the application (WM_ACTIVATEAPP, either value: a release can be lost either way): no button is held any more, and RmlUi
// does not own the pointer until the next event says so.
inline void UiFocusLost(UiRouteState& s, bool& rmlOwner) { s.engineButtons = 0; s.rmlButtons = 0; rmlOwner = false; }
// System keys (W34, C9): the Alt chords are the game's and the system's, never RmlUi's. Alt+F4 arrives as WM_SYSKEYDOWN (there is no
// WM_KEYDOWN for F4 while Alt is held), so the rule is per message, not per key. Plain numbers: this header has no windows.h.
inline bool UiIsSystemKey(uint32_t msg) { return msg == 0x0104 || msg == 0x0105 || msg == 0x0106; }   // WM_SYSKEYDOWN, WM_SYSKEYUP, WM_SYSCHAR
inline const char* UiEvName(UiEv e) {
    switch (e) { case UiEv::Move: return "move"; case UiEv::Down: return "down"; case UiEv::Up: return "up"; case UiEv::Wheel: return "wheel"; case UiEv::Key: return "key"; default: return "char"; }
}

// ---- device lifecycle -----------------------------------------------------------------------------------------------------------
// The UI attaches to the main device only: the game's window and a real back buffer. The battle loader's tiny windowed helper device
// and any other small device are not the UI's (J13). Back-buffer size 0 means "the window's client size" (windowed D3D9).
inline bool UiIsMainDevice(unsigned bbW, unsigned bbH, bool gameWindow) { return gameWindow && (bbW == 0 || bbW >= 640) && (bbH == 0 || bbH >= 480); }

enum class UiLife : uint8_t { NoDevice, Ready, Lost, Off };
enum UiAct : uint8_t { kActNone = 0, kActInit = 1, kActShutdown = 2, kActReleaseDefault = 4, kActRebuild = 8, kActDraw = 16 };
struct UiLifecycle {
    UiLife state = UiLife::NoDevice;
    const void* device = nullptr;
    // A device was created. Main: attach (init), or, when another main device was ours (the old one destroyed), shut down first.
    uint8_t Created(const void* dev, bool main) {
        if (!main || state == UiLife::Off) return kActNone;
        uint8_t a = kActInit;
        if (device && device != dev) a |= kActShutdown;
        if (device == dev && state == UiLife::Ready) return kActNone;
        device = dev; state = UiLife::Ready;
        return a;
    }
    uint8_t PreReset(const void* dev) {   // default-pool resources must go before IDirect3DDevice9::Reset
        if (dev != device || state != UiLife::Ready) return kActNone;
        state = UiLife::Lost; return kActReleaseDefault;
    }
    uint8_t PostReset(const void* dev, bool ok) {   // a failed Reset keeps the device lost: nothing is drawn until one succeeds
        if (dev != device || state != UiLife::Lost) return kActNone;
        if (!ok) return kActNone;
        state = UiLife::Ready; return kActRebuild;
    }
    uint8_t Present(const void* dev, bool anyDocument) const {
        return (dev == device && state == UiLife::Ready && anyDocument) ? kActDraw : kActNone;
    }
    void Fail() { state = UiLife::Off; }   // the render interface could not start (no shader compiler): UI off, never a crash
};

// ---- the `ui` control verb ------------------------------------------------------------------------------------------------------
// ui show <doc> | hide <doc> | reload <doc> | scale <percent> | click <x> <y> [left|right|middle] [down|up|move] | wheel <x> <y> <delta>
//    | dump <name> [x y w h] | state [seconds]
// <doc>: a file under the UI folder (letters, digits, _ - . / only, no ".."); <name>: 1-64 of A-Za-z0-9_-.
struct UiArgs {
    std::string op, doc, name, phase = "click";
    int x = 0, y = 0, w = 0, h = 0, button = 0, percent = 0;
    float delta = 0, seconds = 0;
    bool rect = false;
    std::string error;
};
inline std::vector<std::string> UiSplit(const std::string& s) {
    std::vector<std::string> v; std::string cur;
    for (char c : s) { if (c == ' ' || c == '\t') { if (!cur.empty()) v.push_back(cur); cur.clear(); } else cur += c; }
    if (!cur.empty()) v.push_back(cur);
    return v;
}
inline bool UiInt(const std::string& s, int& out) {
    if (s.empty() || s.size() > 9) return false;
    size_t i = (s[0] == '-') ? 1 : 0;
    if (i == s.size()) return false;
    for (; i < s.size(); ++i) if (s[i] < '0' || s[i] > '9') return false;
    out = atoi(s.c_str()); return true;
}
inline bool UiDocName(const std::string& d) {
    if (d.empty() || d.size() > 120 || d.find("..") != std::string::npos || d[0] == '/') return false;
    for (char c : d) if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.' || c == '/')) return false;
    return true;
}
inline const char* UiVerbs() { return "ui show|hide|reload <doc>, ui scale <percent>, ui click <x> <y> [left|right|middle] [down|up|move], ui wheel <x> <y> <delta>, ui dump <name> [x y w h], ui state [seconds]"; }
inline UiArgs ParseUiArgs(const std::string& arg) {
    UiArgs a; const std::vector<std::string> t = UiSplit(arg);
    if (t.empty()) { a.error = "ui needs an operation (" + std::string(UiVerbs()) + ")"; return a; }
    a.op = t[0];
    const size_t n = t.size();
    if (a.op == "show" || a.op == "hide" || a.op == "reload") {
        if (n != 2 || !UiDocName(t[1])) a.error = "ui " + a.op + " needs one document path under the UI folder (A-Za-z0-9_-./, no ..)";
        else a.doc = t[1];
    } else if (a.op == "scale") {
        if (n != 2 || !UiInt(t[1], a.percent)) a.error = "ui scale needs a percent (85-125, steps of 5)";
    } else if (a.op == "click") {
        if (n < 3 || n > 5 || !UiInt(t[1], a.x) || !UiInt(t[2], a.y)) { a.error = "ui click needs <x> <y> [left|right|middle] [down|up|move]"; return a; }
        for (size_t i = 3; i < n; ++i) {
            if (t[i] == "left") a.button = 0; else if (t[i] == "right") a.button = 1; else if (t[i] == "middle") a.button = 2;
            else if (t[i] == "down" || t[i] == "up" || t[i] == "move") a.phase = t[i];
            else { a.error = "ui click: unknown '" + t[i] + "' (left|right|middle, down|up|move)"; return a; }
        }
    } else if (a.op == "wheel") {
        int d = 0;
        if (n != 4 || !UiInt(t[1], a.x) || !UiInt(t[2], a.y) || !UiInt(t[3], d) || d == 0) a.error = "ui wheel needs <x> <y> <delta> (notches, +down)";
        a.delta = (float)d;
    } else if (a.op == "dump") {
        bool okName = n >= 2 && !t[1].empty() && t[1].size() <= 64;
        if (okName) for (char c : t[1]) if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.')) okName = false;
        if (!okName || t[1][0] == '.' || (n != 2 && n != 6)) { a.error = "ui dump needs <name> (1-64 of A-Za-z0-9_-.) [x y w h]"; return a; }
        a.name = t[1];
        if (n == 6) {
            if (!UiInt(t[2], a.x) || !UiInt(t[3], a.y) || !UiInt(t[4], a.w) || !UiInt(t[5], a.h) || a.x < 0 || a.y < 0 || a.w <= 0 || a.h <= 0) a.error = "ui dump: bad rect (x y w h, positive size)";
            a.rect = true;
        }
    } else if (a.op == "state") {
        int s = 0;
        if (n > 2 || (n == 2 && (!UiInt(t[1], s) || s < 0 || s > 60))) a.error = "ui state takes an optional frame-cost window of 0-60 seconds";
        a.seconds = (float)s;
    } else a.error = "ui: unknown operation '" + a.op + "' (" + std::string(UiVerbs()) + ")";
    return a;
}

// ---- frame-cost statistics: nearest-rank percentiles of a window of samples (ms) ------------------------------------------------
struct UiCost { size_t n = 0; double p50 = 0, p99 = 0, max = 0; };
inline UiCost UiCostOf(std::vector<double> v) {
    UiCost c; c.n = v.size(); if (v.empty()) return c;
    std::sort(v.begin(), v.end());
    auto rank = [&](double q) { size_t k = (size_t)(q * (double)v.size() + 0.999999); if (k < 1) k = 1; if (k > v.size()) k = v.size(); return v[k - 1]; };
    c.p50 = rank(0.50); c.p99 = rank(0.99); c.max = v.back();
    return c;
}

} // namespace wsp
