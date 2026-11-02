#pragma once
// orders.h - the battle unit control route's pure parts (J28): the unit-state decode (against any memory reader, so the host
// tests run it on a fake memory image), the bearing <-> int16 binary angle conversion, the order arguments' checks, and the arrival
// check the control API and a gesture layer compare a readback with. No Windows headers, no globals: host tests in
// proxy/tests/test_orders.cpp. The driver is orders.cpp; the game's sites and offsets come from the adapter (OrdersAdapter).
// Conventions: world y up; a bearing is degrees in [0, 360), as the engine's own bearing getter returns it; the engine stores it as an
// int16 binary angle (65536 = 360 degrees). Which world direction bearing 0 points to is a game fact (the game repo's engine_facts).
#include <cmath>
#include <cstdint>
#include <string>

namespace wsp {

// The game's unit layout and order route (proxy/<game>/adapter.cpp). Every offset and global is read at install time from the stock
// bytes of the named engine_sites row (operand = byte offset in the row's checked bytes; "8" = an imm8 operand, else a dword):
// nothing here or in orders.cpp names a game or an address. test_orders.cpp checks each operand against the generated site table.
struct OrdersAdapter {
    // owner -> battle -> command queue: mov eax, [owner global]; ...; mov eax, [eax + battle]; mov esi, [eax + queue]
    const char* queueSite; int globalOperand, battleOperand, queueOperand;
    // owner -> the UI's selection holder H -> the UI selection S: mov eax, [ecx + holder]; ...; add eax, <imm8 sel>
    const char* uiSelectionSite; int holderOperand, selOperand8;
    // a Selection: loose land units at +looseCount (count) / +looseData (UNIT*[]); AddUnit pushes there: lea ecx, [edi + <imm8 vec>]
    const char* selAddSite; int selVecOperand8; int vecCountOff, vecDataOff;   // the vector's count and data, relative to the vector
    // UNIT -> entity: cmp [ecx + activeIdx], 0; ...; mov ecx, [ecx + eax*4 + entities]  (entity i = [UNIT + entities + 4*i])
    const char* entitySite; int activeIdxOperand, entitiesOperand;
    // entity -> queued orders: cmp [ecx + count], 0
    const char* entityOrdersSite; int orderCountOperand;
    // UNIT -> entity 0 -> position block: mov ecx, [eax + entities]; lea ecx, [ecx + block]
    const char* positionSite; int posEntityOperand, posBlockOperand;
    // position block -> world xyz: lea eax, [ecx + xyz]
    const char* positionXyzSite; int xyzOperand;
    // world xyz -> frame pointer (0 = world/land): mov eax, [ecx + <imm8 frame>]
    const char* frameSite; int frameOperand8;
    // UNIT -> entity 0 -> facing: movsx eax, word [eax + facing]
    const char* bearingSite; int bearingOperand;
    // UNIT -> men alive: push [ecx + men]
    const char* menSite; int menOperand;
    // UNIT -> army -> its unit list: mov eax, [ecx + army]; mov edx, [eax + count]; ... mov eax, [eax + list]
    const char* armySite; int armyOperand, armyCountOperand, armyListOperand;
    // no engine accessor found: proven by ordering a unit and reading back (the run id is in the adapter's comment); -1 = not known
    int frontOff;    // 3 floats: the formation's destination front centre
    int widthOff;    // float: the formation's frontage in metres
    // the order calls (thiscall, called only, never patched)
    const char* selCtorSite;       // Selection::Selection()
    const char* moveCtorSite;      // MoveCommand(sel*, loc[5]*, int16 angle, float width, bool run, bool queue)
    const char* movePushSite;      // queue->Push(cmd*) -> al
    const char* cmdDtorSite;       // Command::~Command()
    const char* freeSite;          // the engine's free(p) (cdecl)
    int selBytes, cmdBytes;        // object sizes (the driver's buffers are larger; checked at install)
    int selDataOffs[4];            // the Selection's four vector data pointers, freed with the engine free after the order (no dtor)
    // the ground projection the script path uses: terrain = [[battle + <imm8 a>] + b]; terrain->Project(loc out, xz in, 0, 1, 0)
    const char* groundChainSite; int groundAOperand8, groundBOperand;
    const char* groundFnSite;
};

// ---- angles ------------------------------------------------------------------------------------------------------------------------
inline double DegFromRaw(int16_t raw) { double d = raw * (360.0 / 65536.0); return d < 0 ? d + 360.0 : d; }
inline int16_t RawFromDeg(double deg) {
    double d = std::fmod(deg, 360.0); if (d < 0) d += 360.0;
    long r = std::lround(d * (65536.0 / 360.0));
    return (int16_t)(uint16_t)(r & 0xffff);
}
inline double Wrap180(double d) { d = std::fmod(d + 180.0, 360.0); if (d < 0) d += 360.0; return d - 180.0; }

// ---- unit state --------------------------------------------------------------------------------------------------------------------
// Offsets resolved from the adapter's sites (orders.cpp fills it at install; the tests fill it by hand).
struct UnitLayout {
    uint32_t activeIdx = 0, entities = 0, orderCount = 0, posBlock = 0, xyz = 0, frame = 0, facing = 0, men = 0;
    uint32_t army = 0, armyCount = 0, armyList = 0;
    int frontOff = -1, widthOff = -1;
    int maxArmy = 512;   // a list longer than this is not a unit list (torn down or wrong pointer)
};

struct UnitState {
    bool ok = false; std::string why;
    uint32_t unit = 0, entity = 0, activeEntity = 0, army = 0;
    int armyIndex = -1, armyCount = 0;
    float x = 0, y = 0, z = 0;
    int16_t facingRaw = 0; double facing = 0;
    int men = 0, queued = 0;
    uint32_t frame = 0;
    bool hasFront = false, hasWidth = false;
    float fx = 0, fy = 0, fz = 0, width = 0;
};

// Read is a callable: bool(uint32_t address, void* out, size_t n) that refuses unreadable memory. Every pointer is checked by it
// before it is used; the unit must be in its own army's list (armyIndex >= 0), and a unit on a moving frame (ships) is refused.
template <class Read>
UnitState ReadUnit(uint32_t unit, const UnitLayout& L, Read read) {
    UnitState s; s.unit = unit;
    auto u32 = [&](uint32_t a, uint32_t& v) { return read(a, &v, 4); };
    auto f32 = [&](uint32_t a, float& v) { return read(a, &v, 4); };
    if (!unit) { s.why = "no unit"; return s; }
    if (!u32(unit + L.army, s.army) || !s.army) { s.why = "the unit's army is not readable"; return s; }
    uint32_t cnt = 0, list = 0;
    if (!u32(s.army + L.armyCount, cnt) || !u32(s.army + L.armyList, list)) { s.why = "the army's unit list is not readable"; return s; }
    if ((int)cnt < 0 || (int)cnt > L.maxArmy || (cnt && !list)) { s.why = "the army's unit list is not a list"; return s; }
    s.armyCount = (int)cnt;
    for (uint32_t i = 0; i < cnt; ++i) {
        uint32_t p = 0;
        if (!u32(list + 4 * i, p)) { s.why = "the army's unit list is not readable"; return s; }
        if (p == unit) { s.armyIndex = (int)i; break; }
    }
    if (s.armyIndex < 0) { s.why = "the unit is not in its army's list (not a UNIT, or torn down)"; return s; }
    uint32_t idx = 0;
    if (!u32(unit + L.entities, s.entity) || !s.entity) { s.why = "the unit has no entity"; return s; }
    if (!u32(unit + L.activeIdx, idx)) { s.why = "the unit's active entity index is not readable"; return s; }
    if (idx > 64) { s.why = "the unit's active entity index is out of range"; return s; }
    if (!u32(unit + L.entities + 4 * idx, s.activeEntity) || !s.activeEntity) { s.why = "the unit's active entity is not readable"; return s; }
    const uint32_t xyz = s.entity + L.posBlock + L.xyz;
    if (!f32(xyz, s.x) || !f32(xyz + 4, s.y) || !f32(xyz + 8, s.z)) { s.why = "the unit's position is not readable"; return s; }
    if (!u32(xyz + L.frame, s.frame)) { s.why = "the unit's frame is not readable"; return s; }
    if (s.frame) { s.why = "the unit is on a moving frame (a ship or a building): out of scope"; return s; }
    if (!std::isfinite(s.x) || !std::isfinite(s.y) || !std::isfinite(s.z)) { s.why = "the unit's position is not finite"; return s; }
    if (!read(s.entity + L.facing, &s.facingRaw, 2)) { s.why = "the unit's facing is not readable"; return s; }
    s.facing = DegFromRaw(s.facingRaw);
    uint32_t men = 0, q = 0;
    if (!u32(unit + L.men, men)) { s.why = "the unit's men count is not readable"; return s; }
    if (!u32(s.activeEntity + L.orderCount, q)) { s.why = "the unit's queued orders are not readable"; return s; }
    s.men = (int)men; s.queued = (int)q;
    if (L.frontOff >= 0 && f32(unit + L.frontOff, s.fx) && f32(unit + L.frontOff + 4, s.fy) && f32(unit + L.frontOff + 8, s.fz)) s.hasFront = true;
    if (L.widthOff >= 0 && f32(unit + L.widthOff, s.width)) s.hasWidth = true;
    s.ok = true;
    return s;
}

// ---- order arguments ---------------------------------------------------------------------------------------------------------------
struct MoveArgs {
    float x = 0, z = 0;
    bool hasFacing = false; double facing = 0;   // degrees; none = keep the unit's facing
    bool hasWidth = false; float width = 0;      // metres; none = keep the unit's width
    bool run = false, queue = false;
};
inline bool CheckMove(const MoveArgs& a, std::string& why) {
    if (!std::isfinite(a.x) || !std::isfinite(a.z)) { why = "x and z must be finite numbers"; return false; }
    if (std::fabs(a.x) > 1e5f || std::fabs(a.z) > 1e5f) { why = "x or z is outside +-100 km"; return false; }
    if (a.hasFacing && !std::isfinite(a.facing)) { why = "facing must be a finite number of degrees"; return false; }
    if (a.hasWidth && (!std::isfinite(a.width) || a.width <= 0.5f || a.width > 1000.0f)) { why = "width must be in (0.5, 1000] metres"; return false; }
    return true;
}
// The facing and width actually ordered: the unit's own when the caller gave none (an order always carries both).
inline void ResolveMove(MoveArgs& a, const UnitState& s) {
    if (!a.hasFacing) { a.facing = s.facing; a.hasFacing = true; }
    if (!a.hasWidth && s.hasWidth && s.width > 0.5f) { a.width = s.width; a.hasWidth = true; }
}

// ---- arrival -----------------------------------------------------------------------------------------------------------------------
struct Tolerance { double posM = 1.0, facingDeg = 1.0, widthM = 0.5; };
struct Arrival { bool ok = false; double posErr = 0, facingErr = 0, widthErr = 0; bool widthChecked = false; std::string why; };
// Compares what was ordered with a unit at rest: position is the formation's destination front centre when the layout has it (the
// point an order names), else the unit's centre; facing is the bearing; width the frontage when known.
inline Arrival CheckArrival(const MoveArgs& a, const UnitState& s, const Tolerance& t) {
    Arrival r;
    const double px = s.hasFront ? s.fx : s.x, pz = s.hasFront ? s.fz : s.z;
    r.posErr = std::hypot(px - a.x, pz - a.z);
    r.facingErr = a.hasFacing ? std::fabs(Wrap180(s.facing - a.facing)) : 0;
    r.widthChecked = a.hasWidth && s.hasWidth;
    r.widthErr = r.widthChecked ? std::fabs(s.width - a.width) : 0;
    if (r.posErr > t.posM) r.why = "position off by more than the tolerance";
    else if (r.facingErr > t.facingDeg) r.why = "facing off by more than the tolerance";
    else if (r.widthChecked && r.widthErr > t.widthM) r.why = "width off by more than the tolerance";
    r.ok = r.why.empty();
    return r;
}
// At rest: no queued orders and the centre moved less than eps metres and turned less than epsDeg since the previous read.
inline bool AtRest(const UnitState& prev, const UnitState& cur, double eps = 0.02, double epsDeg = 0.05) {
    return cur.queued == 0 && std::hypot(cur.x - prev.x, cur.z - prev.z) < eps && std::fabs(Wrap180(cur.facing - prev.facing)) < epsDeg;
}

} // namespace wsp
