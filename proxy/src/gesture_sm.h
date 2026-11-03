#pragma once
// gesture_sm.h - the gesture layer's input state machine (W6), platform-free; host-tested by proxy/tests/test_gesture.cpp.
// Ported from empire-remastered rml_mod/src/gesture_sm.h (controls-v2..v5), with the key bindings as data: a press starts a gesture
// when its modifier set is exactly the move set or the rotate set the adapter gives (default Alt and Alt+Ctrl).
//
//   Idle    --left press, eligible, mods = move or rotate set------------------> Pending (press swallowed; kind from the set)
//   Pending --move farther than dragPx (squared distance > dragPx^2)----------> Active  (begin + update; moves pass, button flag cleared)
//   Pending --left release-----------------------------------------------------> Idle    (replayClick: a plain click at the press point)
//   Active  --move---------------------------------------------------------------> Active  (update)
//   Active  --left release-------------------------------------------------------> Idle    (commit at the release point)
//   Pending/Active --mods (key or a move's modifier read) now = the other set---> same phase, kindSwitch (the caller rebases the pose)
//   Pending/Active --right press-------------------------------------------------> Drain   (cancel; the right press and its release swallowed)
//   Pending/Active --Esc-----------------------------------------------------------> Drain   (cancel; the key itself passes)
//   Pending/Active --a move without the left button-----------------------------> Idle    (cancel: released outside the window)
//   any     --focus lost--------------------------------------------------------> Idle    (cancel)
//   Drain   --left release------------------------------------------------------> Idle    (swallowed: the engine never sees a lone release)
//   Drain   --left press--------------------------------------------------------> evaluated afresh as from Idle
// Only mouse messages are ever swallowed; key messages always pass (gesture_feed.h enforces it for every key message).
namespace wsp {
namespace gest {

constexpr unsigned kModAlt = 1, kModCtrl = 2, kModShift = 4;   // modifier sets (bit masks)
enum Kind { kNone = 0, kMove = 1, kRotate = 2 };
enum Phase { kIdle = 0, kPending = 1, kActive = 2, kDrain = 3 };
enum EvType { kLDown = 0, kLUp, kMouseMove, kRDown, kRUp, kEsc, kDeactivate, kMods };   // kMods: a modifier key went down or up
enum Action { kPass = 0, kSwallow = 1, kPassNoButton = 2 };   // kPassNoButton: pass the move with the left-button flag cleared

struct Event {
    EvType type = kMouseMove;
    int x = 0, y = 0;
    bool lHeld = true;        // moves: the left-button flag
    unsigned mods = 0;        // presses, kMods and moves with hasMods: the modifier set held now
    bool hasMods = false;     // moves: mods is valid (false = no modifier read: never a switch)
    bool eligible = false;    // presses: the caller's eligibility (scene, selection, camera, ground under the cursor)
    int force = kNone;        // presses: a kind forced by a caller (skips the modifier read, not the eligibility)
};
struct Out {
    Action action = kPass;
    bool begin = false, update = false, commit = false, cancel = false, replayClick = false;
    bool kindSwitch = false;  // the kind changed mid-gesture (Machine::kind is the new one)
    const char* why = "";
};

inline const char* KindName(int k) { return k == kMove ? "move" : k == kRotate ? "rotate" : "none"; }
inline const char* PhaseName(int p) { return p == kIdle ? "idle" : p == kPending ? "pending" : p == kActive ? "active" : p == kDrain ? "drain" : "?"; }

struct Machine {
    int dragPx = 6;
    unsigned moveMods = kModAlt, rotateMods = kModAlt | kModCtrl;
    Phase phase = kIdle;
    Kind kind = kNone;
    int x0 = 0, y0 = 0, x = 0, y = 0;   // press point, latest cursor
    bool swallowRUp = false;            // the right press that cancelled is swallowed, so is its release
    bool forced = false;
    bool modSwitch = true;              // false = the kind is fixed at the press
    int switches = 0;                   // kind switches in this gesture

    Kind KindFor(unsigned mods) const {
        mods &= kModAlt | kModCtrl | kModShift;
        if (rotateMods && mods == rotateMods) return kRotate;
        if (moveMods && mods == moveMods) return kMove;
        return kNone;
    }
    // Would this press start a gesture if it were eligible? (The caller asks the adapter only then.)
    bool WouldStart(unsigned mods, int force = kNone) const { return phase != kPending && phase != kActive && (force != kNone || KindFor(mods) != kNone); }
    void Reset() { phase = kIdle; kind = kNone; forced = false; swallowRUp = false; }
    Out Cancel(Out o, const char* why, Phase next) { o.cancel = phase == kActive || phase == kPending; o.why = why; phase = next; if (next == kIdle) { kind = kNone; forced = false; } return o; }

    void Switch(unsigned mods, Out* o) {
        if (!modSwitch || forced || (phase != kPending && phase != kActive)) return;
        const Kind want = KindFor(mods);
        if (want == kNone || want == kind) return;
        kind = want; ++switches; o->kindSwitch = true;
    }
    Out On(const Event& e) {
        Out o;
        switch (e.type) {
        case kLDown: {
            if (phase == kDrain) { phase = kIdle; kind = kNone; }
            if (phase == kPending || phase == kActive) { o.action = kSwallow; o.why = "second press during a gesture"; return o; }
            const Kind k = e.force != kNone ? (Kind)e.force : KindFor(e.mods);
            if (e.eligible && k != kNone) {
                kind = k; forced = e.force != kNone;
                phase = kPending; x0 = x = e.x; y0 = y = e.y; switches = 0;
                o.action = kSwallow; o.why = "gesture press";
            }
            return o;
        }
        case kMouseMove:
            if (phase == kIdle) return o;
            if (phase == kDrain) { o.action = kPassNoButton; return o; }
            if (!e.lHeld) return Cancel(o, "move without the left button (released outside)", kIdle);
            x = e.x; y = e.y; o.action = kPassNoButton;
            if (e.hasMods) Switch(e.mods, &o);
            if (phase == kPending) {
                const long dx = (long)x - x0, dy = (long)y - y0;
                if (dx * dx + dy * dy > (long)dragPx * dragPx) { phase = kActive; o.begin = true; o.update = true; o.why = "drag threshold"; }
            } else o.update = true;
            return o;
        case kLUp:
            if (phase == kPending) { phase = kIdle; o.action = kSwallow; o.replayClick = true; o.why = "click without a drag: replay"; kind = kNone; forced = false; return o; }
            if (phase == kActive) { x = e.x; y = e.y; phase = kIdle; o.action = kSwallow; o.commit = true; o.why = "release"; return o; }
            if (phase == kDrain) { phase = kIdle; kind = kNone; forced = false; o.action = kSwallow; o.why = "release after cancel"; return o; }
            return o;
        case kRDown:
            if (phase == kPending || phase == kActive) { swallowRUp = true; o = Cancel(o, "right press", kDrain); o.action = kSwallow; return o; }
            if (phase == kDrain) { swallowRUp = true; o.action = kSwallow; return o; }
            return o;
        case kRUp:
            if (swallowRUp) { swallowRUp = false; o.action = kSwallow; }
            return o;
        case kEsc:
            if (phase == kPending || phase == kActive) return Cancel(o, "Esc", kDrain);   // the key itself still reaches the engine
            return o;
        case kMods:
            if (phase == kPending || phase == kActive) { Switch(e.mods, &o); if (o.kindSwitch) { o.update = phase == kActive; o.why = kind == kRotate ? "modifiers: rotate" : "modifiers: move"; } }
            return o;   // the key itself always reaches the engine
        case kDeactivate:
            swallowRUp = false;
            if (phase != kIdle) return Cancel(o, "focus lost", kIdle);
            return o;
        }
        return o;
    }
};

}  // namespace gest
}  // namespace wsp
