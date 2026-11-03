#pragma once
// ships.h - the battle ship control route's pure parts (J60): the ship-state decode (against any memory reader, so the host
// tests run it on a fake memory image), the heading as the engine's own bearing getter computes it, the sail setting, the order
// arguments' checks and the arrival check. Ships are their own objects with their own fleet list (not the land UNIT of orders.h), so
// they have their own decode; the queue, the Selection and the command dtor are the land route's (OrdersAdapter). The driver is the
// ship section of orders.cpp; the game's sites and offsets come from the adapter (ShipsAdapter). No Windows headers, no globals.
// Host tests: proxy/tests/test_ships.cpp.
#include <cmath>
#include <cstdint>
#include <string>
#include "orders.h"

namespace wsp {

// The game's ship layout and ship order route (proxy/<game>/adapter.cpp). Every offset is read at install time from the stock bytes of
// the named engine_sites row (operand = byte offset in the row's checked bytes; "8" = an imm8 operand, else a dword): nothing here or
// in orders.cpp names a game or an address. test_ships.cpp checks each operand against the generated site table.
struct ShipsAdapter {
    // the ship ctor's vtable store: mov [edi], <ship vtable>  (every read checks [ship] == it: a stale or foreign pointer is refused)
    const char* vtableSite; int vtableOperand;
    // the ship vtable's slot 0 (the engine's position getter): lea eax, [ecx + <imm8 pos>]; ret  (install checks [vtable] == this site)
    const char* positionSite; int posOperand8;
    // the engine's bearing getter: fld [eax + m02]; fld [eax + m22]; fpatan  (heading = atan2(m02, m22))
    const char* bearingSite; int m02Operand, m22Operand;
    // ship -> army -> its fleet list: mov eax, [ecx + army]; mov edx, [eax + count]; ... mov eax, [eax + list]
    const char* fleetSite; int armyOperand, countOperand, listOperand;
    // the live sail level: movss xmm0, [ecx + sail]
    const char* sailSite; int sailOperand;
    // the engine's own "can be ordered" check: cmp byte [ecx + a], 0; ...; cmp byte [ecx + b], 0; ...; cmp [ecx + state], <imm8 bad>
    const char* orderableSite; int blockAOperand, blockBOperand, stateOperand, stateBadOperand8;
    // surrendered: cmp dword [ecx + surr], <imm8 value>
    const char* surrenderSite; int surrenderOperand, surrenderValueOperand8;
    // the wind: W = [[[ship + a] + <imm8 b>] + c]; prevailing wind x = [W + <imm8 x>], z = [W + <imm8 z>]; the ship's wind angle int16
    const char* windChainSite; int windAOperand, windBOperand8, windCOperand;
    const char* windVectorSite; int windXOperand8, windZOperand8;
    const char* windAngleSite; int windAngleOperand;
    // Selection AddShip (pushes into the ship vector: lea ecx, [edi + <imm8 vec>]); the vector's count/data are the land vector's
    const char* selAddShipSite; int shipVecOperand8;
    // the order calls (thiscall, called only, never patched)
    const char* locationSite;    // Location(loc[5] out, float xz[2] in): the ship target (sea level)
    const char* moveCtorSite;    // ShipMove(sel*, loc[5]*, int sail, int mode, bool queue)
    const char* movePushSite;    // queue->Push(cmd*) -> al
    const char* faceCtorSite;    // Rotate(sel*, int16 angle, bool flag, bool queue)
    const char* facePushSite;
    const char* haltCtorSite;    // Halt(sel*)
    const char* haltPushSite;
    int cmdBytes;                // the largest ship command object (checked against the driver's buffer)
    int moveSail;                // the sail a move carries when the caller names none (the engine's own default)
    int moveMode;                // the move's mode argument (the script path's value)
    int sails[4];                // the engine's sail values: stationary, battle, half, full
    float sailAbove[3];          // the engine's level -> setting thresholds: full above [0], half above [1], battle above [2]
};

// ---- layout ------------------------------------------------------------------------------------------------------------------------
struct ShipLayout {
    uint32_t vtable = 0, pos = 0, m02 = 0, m22 = 0, army = 0, count = 0, list = 0, sail = 0;
    uint32_t blockA = 0, blockB = 0, state = 0, stateBad = 0, surr = 0, surrValue = 0;
    uint32_t windA = 0, windB = 0, windC = 0, windX = 0, windZ = 0, windAngle = 0;
    int sails[4] = { 1, 2, 4, 8 };
    float sailAbove[3] = { 0.5f, 0.25f, 0.0f };
    int maxFleet = 256;   // a list longer than this is not a fleet list
};

// ---- sails -------------------------------------------------------------------------------------------------------------------------
// The setting the engine reports for a sail level (its own getter's thresholds): 0 stationary, 1 battle, 2 half, 3 full (index into sails).
inline int SailIndex(float level, const ShipLayout& L) {
    if (level > L.sailAbove[0]) return 3;
    if (level > L.sailAbove[1]) return 2;
    if (level > L.sailAbove[2]) return 1;
    return 0;
}
inline const char* SailName(int index) {
    static const char* const n[] = { "stationary", "battle", "half", "full" };
    return index >= 0 && index < 4 ? n[index] : "?";
}
// "stationary", "battle", "half", "full" (also "battle sail", "half sail", "full sail") -> index; -1 = not a sail name
inline int SailFromName(const std::string& s) {
    for (int i = 0; i < 4; ++i) {
        const std::string n = SailName(i);
        if (s == n || (i > 0 && s == n + " sail")) return i;
    }
    return -1;
}

// ---- state -------------------------------------------------------------------------------------------------------------------------
struct ShipState {
    bool ok = false; std::string why;
    uint32_t ship = 0, army = 0;
    int fleetIndex = -1, fleetCount = 0;
    float x = 0, y = 0, z = 0;
    float m02 = 0, m22 = 0; int16_t headingRaw = 0; double heading = 0;   // the engine getter's int16, then degrees [0, 360)
    float sailLevel = 0; int sail = -1;                                    // the live level and the setting index the engine reports
    bool blocked = false, surrendered = false; std::string blockedWhy;
    bool hasWind = false; float windX = 0, windZ = 0; int16_t windAngleRaw = 0; double windAngle = 0;   // windAngle in (-180, 180]
};

// The engine's own bearing getter: atan2(m02, m22) * 32768/pi -> int16 (fistp: round to nearest) -> degrees.
inline int16_t HeadingRaw(float m02, float m22) {
    const float a = (float)std::atan2((double)m02, (double)m22) * 10430.378f;
    return (int16_t)(uint16_t)((long)std::lrint(a) & 0xffff);
}

// Read is a callable: bool(uint32_t address, void* out, size_t n) that refuses unreadable memory. The ship must carry the ship vtable
// and be in its own army's fleet list (fleetIndex >= 0); the wind is optional (hasWind).
template <class Read>
ShipState ReadShip(uint32_t ship, const ShipLayout& L, Read read) {
    ShipState s; s.ship = ship;
    auto u32 = [&](uint32_t a, uint32_t& v) { return read(a, &v, 4); };
    auto f32 = [&](uint32_t a, float& v) { return read(a, &v, 4); };
    if (!ship) { s.why = "no ship"; return s; }
    uint32_t vt = 0;
    if (!u32(ship, vt)) { s.why = "the ship is not readable"; return s; }
    if (!L.vtable || vt != L.vtable) { s.why = "not a ship (its vtable is not the ship vtable: stale or foreign pointer)"; return s; }
    if (!u32(ship + L.army, s.army) || !s.army) { s.why = "the ship's army is not readable"; return s; }
    uint32_t cnt = 0, list = 0;
    if (!u32(s.army + L.count, cnt) || !u32(s.army + L.list, list)) { s.why = "the army's fleet list is not readable"; return s; }
    if ((int)cnt < 0 || (int)cnt > L.maxFleet || (cnt && !list)) { s.why = "the army's fleet list is not a list"; return s; }
    s.fleetCount = (int)cnt;
    for (uint32_t i = 0; i < cnt; ++i) {
        uint32_t p = 0;
        if (!u32(list + 4 * i, p)) { s.why = "the army's fleet list is not readable"; return s; }
        if (p == ship) { s.fleetIndex = (int)i; break; }
    }
    if (s.fleetIndex < 0) { s.why = "the ship is not in its army's fleet list (torn down)"; return s; }
    if (!f32(ship + L.pos, s.x) || !f32(ship + L.pos + 4, s.y) || !f32(ship + L.pos + 8, s.z)) { s.why = "the ship's position is not readable"; return s; }
    if (!std::isfinite(s.x) || !std::isfinite(s.y) || !std::isfinite(s.z)) { s.why = "the ship's position is not finite"; return s; }
    if (!f32(ship + L.m02, s.m02) || !f32(ship + L.m22, s.m22)) { s.why = "the ship's orientation is not readable"; return s; }
    if (!std::isfinite(s.m02) || !std::isfinite(s.m22) || std::hypot(s.m02, s.m22) < 1e-3) { s.why = "the ship's orientation is not a rotation"; return s; }
    s.headingRaw = HeadingRaw(s.m02, s.m22);
    s.heading = DegFromRaw(s.headingRaw);
    if (!f32(ship + L.sail, s.sailLevel) || !std::isfinite(s.sailLevel)) { s.why = "the ship's sail level is not readable"; return s; }
    s.sail = SailIndex(s.sailLevel, L);
    uint8_t a = 0, b = 0; uint32_t st = 0, surr = 0;
    if (!read(ship + L.blockA, &a, 1) || !read(ship + L.blockB, &b, 1) || !u32(ship + L.state, st) || !u32(ship + L.surr, surr)) {
        s.why = "the ship's state flags are not readable"; return s;
    }
    s.surrendered = surr == L.surrValue;
    if (a) s.blockedWhy = "the ship is out of action (flag A)";
    else if (b) s.blockedWhy = "the ship is out of action (flag B)";
    else if (st == L.stateBad) s.blockedWhy = "the ship's state refuses orders";
    s.blocked = !s.blockedWhy.empty();
    uint32_t w1 = 0, w2 = 0, W = 0;
    if (u32(ship + L.windA, w1) && w1 && u32(w1 + L.windB, w2) && w2 && u32(w2 + L.windC, W) && W && f32(W + L.windX, s.windX) &&
        f32(W + L.windZ, s.windZ) && std::isfinite(s.windX) && std::isfinite(s.windZ) && read(ship + L.windAngle, &s.windAngleRaw, 2)) {
        s.hasWind = true;
        s.windAngle = Wrap180(s.windAngleRaw * (360.0 / 65536.0));
    }
    s.ok = true;
    return s;
}

// A decoded ship the driver will order (the engine's AddShip check refuses routing ships on its own: the driver checks it took one).
inline bool ShipOrderable(const ShipState& s, std::string& why) {
    if (!s.ok) { why = s.why.empty() ? "the ship is not readable" : s.why; return false; }
    if (s.surrendered) { why = "the ship has surrendered"; return false; }
    if (s.blocked) { why = s.blockedWhy; return false; }
    return true;
}

// ---- order arguments ---------------------------------------------------------------------------------------------------------------
struct ShipMoveArgs {
    float x = 0, z = 0;
    bool hasHeading = false; double heading = 0;   // degrees; a queued facing order after the move (the move has no heading of its own)
    int sail = -1;                                 // setting index 0..3; -1 = the engine's default for a move
    bool queue = false;
};
inline bool CheckShipMove(const ShipMoveArgs& a, std::string& why) {
    if (!std::isfinite(a.x) || !std::isfinite(a.z)) { why = "x and z must be finite numbers"; return false; }
    if (std::fabs(a.x) > 1e5f || std::fabs(a.z) > 1e5f) { why = "x or z is outside +-100 km"; return false; }
    if (a.hasHeading && !std::isfinite(a.heading)) { why = "heading must be a finite number of degrees"; return false; }
    if (a.sail < -1 || a.sail > 3) { why = "sail is stationary, battle, half or full"; return false; }
    return true;
}
inline bool CheckFace(double heading, std::string& why) {
    if (!std::isfinite(heading)) { why = "heading must be a finite number of degrees"; return false; }
    return true;
}

// ---- arrival -----------------------------------------------------------------------------------------------------------------------
// Thresholds come from the game's route block (measured on the PC); these defaults are J28's land numbers widened, not measurements.
struct ShipTolerance { double posM = 25.0, headingDeg = 10.0, settleSpeed = 0.3, settleTurn = 1.0, minMoveFrac = 0.5; };
struct ShipArrival { bool ok = false; double posErr = 0, headingErr = 0, moved = 0; bool headingChecked = false, sailChecked = false; std::string why; };
// Compares the ordered move with a live reading (never with what the order wrote, C17): position against the target, heading when one
// was ordered, sail when one was ordered, and that the ship moved at least minMoveFrac of the distance it was asked to cover (a ship that
// never moved fails even when it started near the target, unless it started inside the tolerance).
inline ShipArrival CheckShipArrival(const ShipMoveArgs& a, const ShipState& start, const ShipState& cur, const ShipTolerance& t) {
    ShipArrival r;
    if (!cur.ok) { r.why = cur.why.empty() ? "the ship is not readable" : cur.why; return r; }
    r.posErr = std::hypot(cur.x - a.x, cur.z - a.z);
    r.moved = std::hypot(cur.x - start.x, cur.z - start.z);
    const double asked = std::hypot(a.x - start.x, a.z - start.z);
    r.headingChecked = a.hasHeading;
    r.headingErr = a.hasHeading ? std::fabs(Wrap180(cur.heading - a.heading)) : 0;
    r.sailChecked = a.sail >= 0;
    if (asked > t.posM && r.moved < t.minMoveFrac * asked) r.why = "the ship did not move towards the target";
    else if (r.posErr > t.posM) r.why = "position off by more than the tolerance";
    else if (r.headingChecked && r.headingErr > t.headingDeg) r.why = "heading off by more than the tolerance";
    else if (r.sailChecked && cur.sail != a.sail) r.why = std::string("sail is ") + SailName(cur.sail) + ", not " + SailName(a.sail);
    r.ok = r.why.empty();
    return r;
}
// Settled: between two reads dt seconds apart the ship moved slower than settleSpeed m/s and turned slower than settleTurn deg/s. The
// engine offers no live speed or moving flag (the game repo's engine_facts): the speed is the reading's own.
inline double ShipSpeed(const ShipState& prev, const ShipState& cur, double dt) { return dt > 0 ? std::hypot(cur.x - prev.x, cur.z - prev.z) / dt : 0; }
inline bool ShipSettled(const ShipState& prev, const ShipState& cur, double dt, const ShipTolerance& t) {
    if (!(dt > 0) || !prev.ok || !cur.ok) return false;
    return ShipSpeed(prev, cur, dt) < t.settleSpeed && std::fabs(Wrap180(cur.heading - prev.heading)) / dt < t.settleTurn;
}

} // namespace wsp
