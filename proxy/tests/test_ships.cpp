// test_ships.cpp - host tests for the ship half of the battle control route (J60): the ship-state decode against a fake memory image
// (the vtable check, the fleet membership, unreadable and non-finite fields, the engine's blocking flags, the wind), the heading as the
// engine's bearing getter computes it, the sail thresholds and names, the move arguments' checks, the failing fixtures of the arrival
// check (a ship that never moved, a target it did not reach, a wrong heading or sail, a sunk, surrendered or stale ship), the settle,
// the adapter's operands against its engine_sites rows' stock bytes, and source lints (key off refuses first, every call after the
// checks, the land route's frame refusal unchanged, no game named). Built and run by build.sh tests.
#include "testkit.h"
#include "ships.h"
#include "adapter.cpp"
#include <map>
#include <vector>

using namespace wsp;

namespace {
struct Image {
    std::map<uint32_t, uint8_t> m;
    void put(uint32_t a, const void* p, size_t n) { const uint8_t* b = (const uint8_t*)p; for (size_t i = 0; i < n; ++i) m[a + (uint32_t)i] = b[i]; }
    void u8(uint32_t a, uint8_t v) { put(a, &v, 1); }
    void u32(uint32_t a, uint32_t v) { put(a, &v, 4); }
    void f32(uint32_t a, float v) { put(a, &v, 4); }
    void i16(uint32_t a, int16_t v) { put(a, &v, 2); }
    void drop(uint32_t a, size_t n) { for (size_t i = 0; i < n; ++i) m.erase(a + (uint32_t)i); }
    bool read(uint32_t a, void* out, size_t n) const {
        uint8_t* o = (uint8_t*)out;
        for (size_t i = 0; i < n; ++i) { auto it = m.find(a + (uint32_t)i); if (it == m.end()) return false; o[i] = it->second; }
        return true;
    }
};
// a layout with the shape the route needs (the numbers are the test's own)
ShipLayout Layout() {
    ShipLayout L;
    L.vtable = 0x00abc000; L.pos = 0x54; L.m02 = 0x50c; L.m22 = 0x524; L.army = 0x43c; L.count = 0x108; L.list = 0x10c; L.sail = 0x1b88;
    L.blockA = 0x20dd; L.blockB = 0x20de; L.state = 0x1c58; L.stateBad = 2; L.surr = 0x1f00; L.surrValue = 4;
    L.windA = 0x1e0; L.windB = 8; L.windC = 0xd8; L.windX = 0x48; L.windZ = 0x4c; L.windAngle = 0x5a8;
    return L;
}
constexpr uint32_t kShip = 0x100000, kShip2 = 0x110000, kArmy = 0x200000, kList = 0x210000, kW1 = 0x220000, kW2 = 0x230000, kW = 0x240000;
// a ship heading `deg` (0 = +z, 90 = +x when m02 = sin, m22 = cos)
Image World(const ShipLayout& L, double deg = 90) {
    Image w;
    for (uint32_t s : { kShip, kShip2 }) {
        w.u32(s, L.vtable); w.u32(s + L.army, kArmy);
        w.f32(s + L.pos, 120.5f); w.f32(s + L.pos + 4, 0.0f); w.f32(s + L.pos + 8, -340.25f);
        const double r = deg * 3.14159265358979 / 180;
        w.f32(s + L.m02, (float)std::sin(r)); w.f32(s + L.m22, (float)std::cos(r));
        w.f32(s + L.sail, 0.3f);
        w.u8(s + L.blockA, 0); w.u8(s + L.blockB, 0); w.u32(s + L.state, 0); w.u32(s + L.surr, 0);
    }
    w.u32(kArmy + L.count, 2); w.u32(kArmy + L.list, kList); w.u32(kList, kShip2); w.u32(kList + 4, kShip);
    w.u32(kShip + L.windA, kW1); w.u32(kW1 + L.windB, kW2); w.u32(kW2 + L.windC, kW); w.f32(kW + L.windX, -3.0f); w.f32(kW + L.windZ, 4.0f);
    w.i16(kShip + L.windAngle, (int16_t)30038);
    return w;
}
const SiteDef* Site(const char* id) {
    for (size_t i = 0; i < gen::kSiteCount; ++i) if (!strcmp(gen::kSites[i].id, id)) return &gen::kSites[i];
    return nullptr;
}
bool Near(double a, double b, double t = 1e-3) { return std::fabs(a - b) <= t; }
ShipState Read(const Image& w, uint32_t ship, const ShipLayout& L) { return ReadShip(ship, L, [&](uint32_t a, void* o, size_t n) { return w.read(a, o, n); }); }
} // namespace

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    const ShipLayout L = Layout();
    {   // heading: the engine getter's atan2(m02, m22) -> int16 -> degrees; the four quadrants and the wrap
        CHECK_EQ(HeadingRaw(0, 1), (int16_t)0); CHECK_EQ(HeadingRaw(1, 0), (int16_t)16384); CHECK_EQ(HeadingRaw(0, -1), (int16_t)-32768);
        CHECK_EQ(HeadingRaw(-1, 0), (int16_t)-16384);
        CHECK(Near(DegFromRaw(HeadingRaw(0.5f, 0.8660254f)), 30, 0.01)); CHECK(Near(DegFromRaw(HeadingRaw(-0.5f, 0.8660254f)), 330, 0.01));
        CHECK(Near(DegFromRaw(HeadingRaw(2.0f, 0.0f)), 90, 0.01));   // scale-free (the getter does not normalise)
    }
    {   // sails: the engine's thresholds, names both ways
        CHECK_EQ(SailIndex(0.0f, L), 0); CHECK_EQ(SailIndex(0.1f, L), 1); CHECK_EQ(SailIndex(0.25f, L), 1); CHECK_EQ(SailIndex(0.3f, L), 2);
        CHECK_EQ(SailIndex(0.5f, L), 2); CHECK_EQ(SailIndex(0.51f, L), 3); CHECK_EQ(SailIndex(1.0f, L), 3);
        CHECK_EQ(SailFromName("full"), 3); CHECK_EQ(SailFromName("full sail"), 3); CHECK_EQ(SailFromName("battle sail"), 1);
        CHECK_EQ(SailFromName("stationary"), 0); CHECK_EQ(SailFromName("stationary sail"), -1); CHECK_EQ(SailFromName(""), -1); CHECK_EQ(SailFromName("Full"), -1);
        CHECK(!strcmp(SailName(2), "half")); CHECK(!strcmp(SailName(7), "?"));
    }
    {   // decode: a good ship
        const Image w = World(L, 90);
        const ShipState s = Read(w, kShip, L);
        CHECK(s.ok); CHECK_EQ(s.fleetIndex, 1); CHECK_EQ(s.fleetCount, 2); CHECK_EQ(s.army, kArmy);
        CHECK(Near(s.x, 120.5) && Near(s.y, 0) && Near(s.z, -340.25)); CHECK(Near(s.heading, 90, 0.01)); CHECK_EQ(s.sail, 2);
        CHECK(!s.blocked && !s.surrendered); CHECK(s.hasWind); CHECK(Near(s.windX, -3) && Near(s.windZ, 4)); CHECK(Near(s.windAngle, 165.0, 0.01));
        std::string why; CHECK(ShipOrderable(s, why));
        const ShipState s2 = Read(w, kShip2, L);   // no wind chain on this one: still a ship, wind just absent
        CHECK(s2.ok && !s2.hasWind && s2.fleetIndex == 0);
    }
    {   // decode refusals: each one names why, nothing is ok
        struct Case { const char* name; void (*spoil)(Image&, const ShipLayout&); const char* why; };
        const Case cases[] = {
            { "stale pointer (no memory)", [](Image& w, const ShipLayout&) { w.drop(kShip, 4); }, "not readable" },
            { "foreign object (another vtable)", [](Image& w, const ShipLayout&) { w.u32(kShip, 0x00def000); }, "vtable" },
            { "a UNIT or freed memory (vtable 0)", [](Image& w, const ShipLayout&) { w.u32(kShip, 0); }, "vtable" },
            { "no army", [](Image& w, const ShipLayout& L) { w.u32(kShip + L.army, 0); }, "army" },
            { "not in its fleet (torn down)", [](Image& w, const ShipLayout&) { w.u32(kList + 4, 0x999000); }, "fleet list" },
            { "fleet list too long", [](Image& w, const ShipLayout& L) { w.u32(kArmy + L.count, 100000); }, "not a list" },
            { "fleet list unreadable", [](Image& w, const ShipLayout&) { w.drop(kList, 4); }, "not readable" },
            { "position not finite", [](Image& w, const ShipLayout& L) { w.f32(kShip + L.pos + 8, NAN); }, "not finite" },
            { "position unreadable", [](Image& w, const ShipLayout& L) { w.drop(kShip + L.pos, 12); }, "position" },
            { "orientation degenerate", [](Image& w, const ShipLayout& L) { w.f32(kShip + L.m02, 0); w.f32(kShip + L.m22, 0); }, "rotation" },
            { "sail unreadable", [](Image& w, const ShipLayout& L) { w.drop(kShip + L.sail, 4); }, "sail" },
            { "flags unreadable", [](Image& w, const ShipLayout& L) { w.drop(kShip + L.surr, 4); }, "flags" },
            { "null", [](Image&, const ShipLayout&) {}, "no ship" },
        };
        for (const Case& c : cases) {
            Image w = World(L); c.spoil(w, L);
            const ShipState s = Read(w, strcmp(c.name, "null") ? kShip : 0, L);
            if (s.ok || s.why.find(c.why) == std::string::npos) printf("    case '%s': ok=%d why='%s'\n", c.name, s.ok, s.why.c_str());
            CHECK(!s.ok && s.why.find(c.why) != std::string::npos);
        }
    }
    {   // the engine's blocking flags and surrender: decoded, then the driver will not order the ship
        struct Case { const char* name; void (*spoil)(Image&, const ShipLayout&); };
        const Case cases[] = {
            { "sunk or out of action (flag A)", [](Image& w, const ShipLayout& L) { w.u8(kShip + L.blockA, 1); } },
            { "out of action (flag B)", [](Image& w, const ShipLayout& L) { w.u8(kShip + L.blockB, 1); } },
            { "state refuses orders", [](Image& w, const ShipLayout& L) { w.u32(kShip + L.state, 2); } },
            { "surrendered", [](Image& w, const ShipLayout& L) { w.u32(kShip + L.surr, 4); } },
        };
        for (const Case& c : cases) {
            Image w = World(L); c.spoil(w, L);
            const ShipState s = Read(w, kShip, L);
            std::string why;
            CHECK(s.ok); CHECK(!ShipOrderable(s, why)); CHECK(!why.empty());
        }
        ShipState bad; bad.why = "x"; std::string why; CHECK(!ShipOrderable(bad, why) && why == "x");
    }
    {   // move arguments
        std::string why; ShipMoveArgs a; a.x = 10; a.z = -20;
        CHECK(CheckShipMove(a, why));
        a.x = NAN; CHECK(!CheckShipMove(a, why)); a.x = 10;
        a.z = 2e5f; CHECK(!CheckShipMove(a, why)); a.z = -20;
        a.hasHeading = true; a.heading = INFINITY; CHECK(!CheckShipMove(a, why)); a.heading = 45; CHECK(CheckShipMove(a, why));
        a.sail = 4; CHECK(!CheckShipMove(a, why)); a.sail = -2; CHECK(!CheckShipMove(a, why)); a.sail = 3; CHECK(CheckShipMove(a, why));
        CHECK(CheckFace(370, why)); CHECK(!CheckFace(NAN, why));
    }
    {   // arrival (C17: a live reading against what was ordered, never what the order wrote) and the failing fixtures
        const ShipTolerance t;   // the defaults; the game's route block sets the measured ones
        ShipState start; start.ok = true; start.x = 0; start.z = 0; start.heading = 0; start.sail = 2;
        ShipMoveArgs a; a.x = 0; a.z = 400; a.hasHeading = true; a.heading = 90; a.sail = 3;
        ShipState cur = start; cur.x = 3; cur.z = 390; cur.heading = 85; cur.sail = 3;
        ShipArrival r = CheckShipArrival(a, start, cur, t);
        CHECK(r.ok); CHECK(Near(r.posErr, std::hypot(3.0, 10.0))); CHECK(r.headingChecked && Near(r.headingErr, 5)); CHECK(r.sailChecked);
        ShipState never = start;                                     // the push returned true but the ship never moved
        r = CheckShipArrival(a, start, never, t); CHECK(!r.ok && r.why.find("did not move") != std::string::npos);
        ShipState half = start; half.z = 250;                        // moved, but stopped short (upwind, aground, on land)
        r = CheckShipArrival(a, start, half, t); CHECK(!r.ok && r.why.find("position") != std::string::npos);
        ShipState wrongHeading = cur; wrongHeading.heading = 120;
        r = CheckShipArrival(a, start, wrongHeading, t); CHECK(!r.ok && r.why.find("heading") != std::string::npos);
        ShipState wrap = cur; wrap.heading = 95; a.heading = 90; CHECK(CheckShipArrival(a, start, wrap, t).ok);
        a.heading = 359; wrap.heading = 2; CHECK(CheckShipArrival(a, start, wrap, t).ok); a.heading = 90;
        ShipState wrongSail = cur; wrongSail.sail = 1;
        r = CheckShipArrival(a, start, wrongSail, t); CHECK(!r.ok && r.why.find("sail") != std::string::npos);
        ShipState gone; gone.why = "the ship is not in its army's fleet list (torn down)";   // sunk and removed, or a stale pointer
        r = CheckShipArrival(a, start, gone, t); CHECK(!r.ok && r.why.find("fleet") != std::string::npos);
        ShipMoveArgs near; near.x = 5; near.z = 5;                   // a target inside the tolerance needs no movement
        CHECK(CheckShipArrival(near, start, start, t).ok);
        ShipMoveArgs noHeading; noHeading.x = 0; noHeading.z = 400;  // no heading or sail ordered: neither is compared
        ShipState anyHeading = cur; anyHeading.heading = 200; anyHeading.sail = 0;
        r = CheckShipArrival(noHeading, start, anyHeading, t); CHECK(r.ok && !r.headingChecked && !r.sailChecked);
    }
    {   // settle and speed: from two reads (the engine has no speed field)
        const ShipTolerance t;
        ShipState p; p.ok = true; p.x = 0; p.z = 0; p.heading = 10;
        ShipState c = p; c.z = 2;
        CHECK(Near(ShipSpeed(p, c, 1.0), 2)); CHECK(!ShipSettled(p, c, 1.0, t));
        c.z = 0.1f; CHECK(ShipSettled(p, c, 1.0, t));
        c.heading = 13; CHECK(!ShipSettled(p, c, 1.0, t));            // still turning
        c.heading = 10; CHECK(!ShipSettled(p, c, 0, t));              // no interval: never settled
        ShipState bad; CHECK(!ShipSettled(p, bad, 1.0, t));
    }
    if (Adapter().ships) {   // the adapter (when it has the ship route): every site exists and is keyed, every operand lies inside its stock bytes
        const ShipsAdapter& o = *Adapter().ships;
        struct Op { const char* site; int off; bool imm8; };
        const Op ops[] = { { o.vtableSite, o.vtableOperand, false }, { o.positionSite, o.posOperand8, true }, { o.bearingSite, o.m02Operand, false },
                           { o.bearingSite, o.m22Operand, false }, { o.fleetSite, o.armyOperand, false }, { o.fleetSite, o.countOperand, false },
                           { o.fleetSite, o.listOperand, false }, { o.sailSite, o.sailOperand, false }, { o.orderableSite, o.blockAOperand, false },
                           { o.orderableSite, o.blockBOperand, false }, { o.orderableSite, o.stateOperand, false }, { o.orderableSite, o.stateBadOperand8, true },
                           { o.surrenderSite, o.surrenderOperand, false }, { o.surrenderSite, o.surrenderValueOperand8, true },
                           { o.windChainSite, o.windAOperand, false }, { o.windChainSite, o.windBOperand8, true }, { o.windChainSite, o.windCOperand, false },
                           { o.windVectorSite, o.windXOperand8, true }, { o.windVectorSite, o.windZOperand8, true }, { o.windAngleSite, o.windAngleOperand, false },
                           { o.selAddShipSite, o.shipVecOperand8, true } };
        for (const Op& p : ops) {
            const SiteDef* s = Site(p.site);
            if (!s) { printf("    site %s missing\n", p.site); CHECK(s); continue; }
            CHECK(s->kind == kHook);
            const bool inside = p.off >= 1 && p.off + (p.imm8 ? 1 : 4) <= (int)s->len;
            if (!inside) { printf("    %s operand +%d outside its %u stock bytes\n", p.site, p.off, s->len); CHECK(inside); continue; }
            const uint32_t v = p.imm8 ? s->stock[p.off] : (uint32_t)s->stock[p.off] | s->stock[p.off + 1] << 8 | s->stock[p.off + 2] << 16 | (uint32_t)s->stock[p.off + 3] << 24;
            if (!v) printf("    %s operand +%d is 0\n", p.site, p.off);
            CHECK(v != 0);
        }
        for (const char* id : { o.vtableSite, o.positionSite, o.bearingSite, o.fleetSite, o.sailSite, o.orderableSite, o.surrenderSite, o.windChainSite,
                                o.windVectorSite, o.windAngleSite, o.selAddShipSite, o.locationSite, o.moveCtorSite, o.movePushSite, o.faceCtorSite,
                                o.facePushSite, o.haltCtorSite, o.haltPushSite }) {
            const SiteDef* s = Site(id);
            if (!s || !s->configKey || strcmp(s->configKey, "dev.orders")) printf("    site %s is missing or not keyed dev.orders\n", id);
            CHECK(s && s->configKey && !strcmp(s->configKey, "dev.orders"));
        }
        // the position offset's proof is the vtable slot 0 check at install: the site is the whole getter (lea eax, [ecx + imm8]; ret)
        const SiteDef* pos = Site(o.positionSite);
        CHECK(pos && pos->len >= 4 && pos->stock[0] == 0x8d && pos->stock[1] == 0x41 && pos->stock[3] == 0xc3);
        // the bearing operands are the two fld loads (d9 80 disp32) the getter feeds to fpatan
        const SiteDef* br = Site(o.bearingSite);
        CHECK(br && br->stock[o.m02Operand - 2] == 0xd9 && br->stock[o.m02Operand - 1] == 0x80 && br->stock[o.m22Operand - 2] == 0xd9 && br->stock[o.m22Operand - 1] == 0x80);
        // the ship vector and the land vector are the same container shape, 0x20 apart (loose units, then ship groups, then ships)
        if (Adapter().orders) {
            const SiteDef* landAdd = Site(Adapter().orders->selAddSite), *shipAdd = Site(o.selAddShipSite);
            CHECK(landAdd && shipAdd && shipAdd->stock[o.shipVecOperand8] == landAdd->stock[Adapter().orders->selVecOperand8] + 0x20);
        }
        CHECK(o.cmdBytes > 0 && o.cmdBytes <= 0x200);
        for (int i = 0; i < 4; ++i) CHECK(o.sails[i] > 0);
        CHECK(o.sailAbove[0] > o.sailAbove[1] && o.sailAbove[1] > o.sailAbove[2]);
        CHECK(o.moveSail == o.sails[2] || o.moveSail == o.sails[0] || o.moveSail == o.sails[1] || o.moveSail == o.sails[3]);
        // the call sites are function entries (int3 padding or a previous function before them); the ctor guards are 32 bytes
        for (const char* id : { o.selAddShipSite, o.locationSite, o.moveCtorSite, o.movePushSite, o.faceCtorSite, o.facePushSite, o.haltCtorSite, o.haltPushSite })
            CHECK(Site(id)->anchorLen >= 2);
        for (const char* id : { o.moveCtorSite, o.faceCtorSite, o.haltCtorSite }) CHECK(Site(id)->len >= 32);
    }
    {   // source lints
        const std::string cc = tk::ReadFile("core/orders.cpp"), sh = tk::ReadFile("core/ships.h"), oh = tk::ReadFile("core/orders.h");
        CHECK(!cc.empty() && !sh.empty() && !oh.empty());
        // key off: the ship install returns before any site address; every entry refuses before any engine read
        const size_t inst = cc.find("void OrdersShipsInstall()"), keyRet = cc.find("if (!s_key || !s_sad || s_shipsInstalled) return;", inst),
                     firstSite = cc.find("SiteAddress(", inst);
        CHECK(inst != std::string::npos && keyRet < firstSite);
        for (const char* fn : { "bool ShipLocked(", "bool ShipOrderLocked(", "bool OrdersShipSelection(" }) {
            const size_t f = cc.find(fn), k = cc.find("if (!s_key)", f), brace = cc.find("\n}", f);
            if (!(f != std::string::npos && k < brace && k - f < 200)) printf("    %s does not refuse first with dev.orders=0\n", fn);
            CHECK(f != std::string::npos && k < brace && k - f < 200);
        }
        // the ship orders' engine calls come after every check, and off the engine thread they are refused
        const size_t so = cc.find("bool ShipOrderLocked("), firstCall = cc.find("((CtorFn)s_selCtor)(sel);", so);
        CHECK(so != std::string::npos && cc.find("GetCurrentThreadId() != s_engineTid", so) < firstCall && cc.find("ShipOrderable(", so) < firstCall &&
              cc.find("Executable(f)", so) < firstCall && cc.find("Battle(battle, queue, why)", so) < firstCall);
        // the land route still refuses a unit on a moving frame (ships go through their own entry points)
        CHECK(oh.find("if (s.frame) { s.why = \"the unit is on a moving frame") != std::string::npos);
        // nothing is written into engine memory
        CHECK(cc.find("WriteProcessMemory") == std::string::npos && cc.find("VirtualProtect") == std::string::npos);
        for (const char* g : { "apoleon", "mpire" }) CHECK(sh.find(g) == std::string::npos && cc.find(g) == std::string::npos);
    }
    return tk::Done("test_ships");
}
