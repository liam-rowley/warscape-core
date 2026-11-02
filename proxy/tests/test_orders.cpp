// test_orders.cpp - host tests for the battle unit control route (J28): the unit-state decode against a fake memory image (the armyIndex
// check, the frame refusal, unreadable pointers), the bearing <-> int16 angle conversion, the move arguments' checks, a unit the driver
// will not order, the arrival check (a unit that never moved fails), the adapter's operands against its engine_sites rows' stock bytes,
// and source lints (dev.orders off reads nothing, every call after the checks, no game named in core). Built and run by build.sh tests.
#include "testkit.h"
#include "orders.h"
#include "adapter.cpp"
#include <map>
#include <vector>

using namespace wsp;

namespace {
// A sparse 32-bit address space: only the bytes put there are readable (what VirtualQuery gives the driver).
struct Image {
    std::map<uint32_t, uint8_t> m;
    void put(uint32_t a, const void* p, size_t n) { const uint8_t* b = (const uint8_t*)p; for (size_t i = 0; i < n; ++i) m[a + (uint32_t)i] = b[i]; }
    void u32(uint32_t a, uint32_t v) { put(a, &v, 4); }
    void f32(uint32_t a, float v) { put(a, &v, 4); }
    void i16(uint32_t a, int16_t v) { put(a, &v, 2); }
    bool read(uint32_t a, void* out, size_t n) const {
        uint8_t* o = (uint8_t*)out;
        for (size_t i = 0; i < n; ++i) { auto it = m.find(a + (uint32_t)i); if (it == m.end()) return false; o[i] = it->second; }
        return true;
    }
};
// a layout with the shape the route needs (the numbers are the test's own)
UnitLayout Layout() {
    UnitLayout L;
    L.activeIdx = 0x28; L.entities = 0x20; L.orderCount = 0x60; L.posBlock = 0x100; L.xyz = 0x10; L.frame = 0x10; L.facing = 0x80; L.men = 0x40;
    L.army = 0x10; L.armyCount = 0x30; L.armyList = 0x34; L.frontOff = 0x200; L.widthOff = 0x214;
    return L;
}
constexpr uint32_t kUnit = 0x10000, kEnt = 0x20000, kEnt2 = 0x21000, kArmy = 0x30000, kList = 0x31000;
Image World(const UnitLayout& L, uint32_t frame = 0) {
    Image w;
    w.u32(kUnit + L.army, kArmy);
    w.u32(kArmy + L.armyCount, 3); w.u32(kArmy + L.armyList, kList);
    w.u32(kList, 0x11000); w.u32(kList + 4, kUnit); w.u32(kList + 8, 0x12000);
    w.u32(kUnit + L.entities, kEnt); w.u32(kUnit + L.entities + 4, kEnt2); w.u32(kUnit + L.activeIdx, 1);
    const uint32_t xyz = kEnt + L.posBlock + L.xyz;
    w.f32(xyz, 28.2f); w.f32(xyz + 4, 15.4f); w.f32(xyz + 8, 303.9f); w.u32(xyz + L.frame, frame);
    w.i16(kEnt + L.facing, (int16_t)-32768);
    w.u32(kUnit + L.men, 120);
    w.u32(kEnt2 + L.orderCount, 1);
    w.f32(kUnit + L.frontOff, 28.2f); w.f32(kUnit + L.frontOff + 4, 15.4f); w.f32(kUnit + L.frontOff + 8, 302.1f); w.f32(kUnit + L.widthOff, 31.9f);
    return w;
}
const SiteDef* Site(const char* id) {
    for (size_t i = 0; i < gen::kSiteCount; ++i) if (!strcmp(gen::kSites[i].id, id)) return &gen::kSites[i];
    return nullptr;
}
bool Near(double a, double b, double t = 1e-3) { return std::fabs(a - b) <= t; }
} // namespace

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    {   // angles: 65536 = 360 degrees, the engine's int16 binary angle; [0, 360) out
        CHECK_EQ(RawFromDeg(0), (int16_t)0); CHECK_EQ(RawFromDeg(90), (int16_t)16384); CHECK_EQ(RawFromDeg(180), (int16_t)-32768);
        CHECK_EQ(RawFromDeg(270), (int16_t)-16384); CHECK_EQ(RawFromDeg(-90), (int16_t)-16384); CHECK_EQ(RawFromDeg(450), (int16_t)16384);
        CHECK(Near(DegFromRaw(-32768), 180)); CHECK(Near(DegFromRaw(-16384), 270)); CHECK(Near(DegFromRaw(32559), 178.8519, 1e-3));
        for (int r = -32768; r < 32768; r += 97) CHECK_EQ(RawFromDeg(DegFromRaw((int16_t)r)), (int16_t)r);
        CHECK(Near(Wrap180(359.5 - 0.5), -1)); CHECK(Near(Wrap180(-190), 170));
    }
    {   // the decode on a fake image
        const UnitLayout L = Layout();
        Image w = World(L);
        auto rd = [&](uint32_t a, void* o, size_t n) { return w.read(a, o, n); };
        UnitState s = ReadUnit(kUnit, L, rd);
        CHECK(s.ok); CHECK_EQ(s.armyIndex, 1); CHECK_EQ(s.armyCount, 3); CHECK_EQ(s.entity, kEnt); CHECK_EQ(s.activeEntity, kEnt2);
        CHECK(Near(s.x, 28.2f) && Near(s.z, 303.9f) && Near(s.facing, 180) && s.men == 120 && s.queued == 1);
        CHECK(s.hasFront && Near(s.fz, 302.1f) && s.hasWidth && Near(s.width, 31.9f));
        // not in its army's list: a pointer that is not this army's UNIT (torn down, or a stale pointer)
        Image w2 = World(L); w2.u32(kList + 4, 0x13000);
        auto rd2 = [&](uint32_t a, void* o, size_t n) { return w2.read(a, o, n); };
        s = ReadUnit(kUnit, L, rd2); CHECK(!s.ok && s.why.find("army's list") != std::string::npos);
        // a unit on a moving frame (a ship): refused
        Image w3 = World(L, 0x55000);
        auto rd3 = [&](uint32_t a, void* o, size_t n) { return w3.read(a, o, n); };
        s = ReadUnit(kUnit, L, rd3); CHECK(!s.ok && s.why.find("moving frame") != std::string::npos);
        // unreadable army, entity, a list that is not a list, an active index out of range
        s = ReadUnit(0x99999, L, rd); CHECK(!s.ok && s.why.find("army") != std::string::npos);
        Image w4 = World(L); w4.u32(kUnit + L.entities, 0);
        auto rd4 = [&](uint32_t a, void* o, size_t n) { return w4.read(a, o, n); };
        s = ReadUnit(kUnit, L, rd4); CHECK(!s.ok && s.why.find("no entity") != std::string::npos);
        Image w5 = World(L); w5.u32(kArmy + L.armyCount, 100000);
        auto rd5 = [&](uint32_t a, void* o, size_t n) { return w5.read(a, o, n); };
        s = ReadUnit(kUnit, L, rd5); CHECK(!s.ok && s.why.find("not a list") != std::string::npos);
        Image w6 = World(L); w6.u32(kUnit + L.activeIdx, 900);
        auto rd6 = [&](uint32_t a, void* o, size_t n) { return w6.read(a, o, n); };
        s = ReadUnit(kUnit, L, rd6); CHECK(!s.ok && s.why.find("out of range") != std::string::npos);
        CHECK(!ReadUnit(0, L, rd).ok);
        // no front or width offsets in the layout: the state says so, nothing is read there
        UnitLayout L2 = L; L2.frontOff = -1; L2.widthOff = -1;
        s = ReadUnit(kUnit, L2, rd); CHECK(s.ok && !s.hasFront && !s.hasWidth);
        // a dead unit decodes (men 0); the driver will not order it
        Image w7 = World(L); w7.u32(kUnit + L.men, 0);
        auto rd7 = [&](uint32_t a, void* o, size_t n) { return w7.read(a, o, n); };
        s = ReadUnit(kUnit, L, rd7); std::string why;
        CHECK(s.ok && s.men == 0 && !UnitOrderable(s, why) && why.find("no men alive") != std::string::npos);
        s = ReadUnit(kUnit, L, rd); CHECK(UnitOrderable(s, why));
    }
    {   // move arguments
        std::string why; MoveArgs a; a.x = 1; a.z = 2;
        CHECK(CheckMove(a, why));
        a.x = NAN; CHECK(!CheckMove(a, why) && why.find("finite") != std::string::npos); a.x = 1;
        a.z = 2e5f; CHECK(!CheckMove(a, why)); a.z = 2;
        a.hasWidth = true; a.width = 0.4f; CHECK(!CheckMove(a, why) && why.find("width") != std::string::npos);
        a.width = 2000; CHECK(!CheckMove(a, why)); a.width = 31.9f; CHECK(CheckMove(a, why));
        a.hasFacing = true; a.facing = INFINITY; CHECK(!CheckMove(a, why));
        // the unit's own facing and width when none is given
        MoveArgs b; b.x = 1; b.z = 2; UnitState u; u.facing = 179.8; u.hasWidth = true; u.width = 43.6f;
        ResolveMove(b, u); CHECK(b.hasFacing && Near(b.facing, 179.8) && b.hasWidth && Near(b.width, 43.6f));
    }
    {   // arrival: the front centre on target, facing, width; at rest
        MoveArgs a; a.x = 28.2f; a.z = 292; a.hasFacing = true; a.facing = 180; a.hasWidth = true; a.width = 31.9f;
        UnitState s; s.x = 28.2f; s.z = 293.8f; s.facing = 180.08; s.hasFront = true; s.fx = 28.2f; s.fz = 292; s.hasWidth = true; s.width = 31.9f;
        Tolerance t; Arrival r = CheckArrival(a, s, t);
        CHECK(r.ok && r.posErr < 1e-3 && Near(r.facingErr, 0.08, 1e-3) && r.widthChecked);
        s.facing = 182; CHECK(!CheckArrival(a, s, t).ok); s.facing = 180;
        s.width = 40; CHECK(!CheckArrival(a, s, t).ok); s.width = 31.9f;
        s.hasFront = false; s.z = 300; CHECK(!CheckArrival(a, s, t).ok);   // without a front centre the centre itself must be there
        UnitState p = s, c = s; c.moving = 0; CHECK(AtRest(p, c));
        c.moving = 1; CHECK(!AtRest(p, c));                                // the engine says it moves
        c.moving = -1; c.x += 0.5f; CHECK(!AtRest(p, c));                  // not asked: the centre moved
    }
    if (Adapter().orders) {   // the adapter (when it has the route): every site exists and is keyed, every operand lies inside its stock bytes
        const OrdersAdapter& o = *Adapter().orders;
        struct Op { const char* site; int off; bool imm8; };
        const Op ops[] = { { o.queueSite, o.globalOperand, false }, { o.queueSite, o.battleOperand, false }, { o.queueSite, o.queueOperand, false },
                           { o.uiSelectionSite, o.holderOperand, false }, { o.uiSelectionSite, o.selOperand8, true }, { o.selAddSite, o.selVecOperand8, true },
                           { o.entitySite, o.activeIdxOperand, false }, { o.entitySite, o.entitiesOperand, false }, { o.entityOrdersSite, o.orderCountOperand, false },
                           { o.positionSite, o.posEntityOperand, false }, { o.positionSite, o.posBlockOperand, false }, { o.positionXyzSite, o.xyzOperand, false },
                           { o.frameSite, o.frameOperand8, true }, { o.bearingSite, o.bearingOperand, false }, { o.menSite, o.menOperand, false },
                           { o.armySite, o.armyOperand, false }, { o.armySite, o.armyCountOperand, false }, { o.armySite, o.armyListOperand, false },
                           { o.groundChainSite, o.groundAOperand8, true }, { o.groundChainSite, o.groundBOperand, false }, { o.cmdCellSite, o.cmdCellOperand, false } };
        for (const Op& p : ops) {
            const SiteDef* s = Site(p.site);
            if (!s) { printf("    site %s missing\n", p.site); CHECK(s); continue; }
            CHECK(s->kind == kHook);
            CHECK(p.off >= 1 && p.off + (p.imm8 ? 1 : 4) <= s->len);
            if (!(p.off >= 1 && p.off + (p.imm8 ? 1 : 4) <= s->len)) { printf("    %s operand +%d outside its %u stock bytes\n", p.site, p.off, s->len); continue; }
            const uint32_t v = p.imm8 ? s->stock[p.off] : (uint32_t)s->stock[p.off] | s->stock[p.off + 1] << 8 | s->stock[p.off + 2] << 16 | (uint32_t)s->stock[p.off + 3] << 24;
            CHECK(v != 0);
        }
        for (const char* id : { o.queueSite, o.uiSelectionSite, o.selAddSite, o.entitySite, o.entityOrdersSite, o.positionSite, o.positionXyzSite, o.frameSite,
                                o.bearingSite, o.menSite, o.armySite, o.selCtorSite, o.moveCtorSite, o.movePushSite, o.cmdDtorSite, o.groundChainSite,
                                o.groundFnSite, o.cmdCellSite, o.cmdSite }) {
            const SiteDef* s = Site(id);
            if (!s || !s->configKey || strcmp(s->configKey, "dev.orders")) printf("    site %s is not keyed dev.orders\n", id);
            CHECK(s && s->configKey && !strcmp(s->configKey, "dev.orders"));
        }
        CHECK(Site(o.freeSite) != nullptr);
        CHECK(o.selBytes > 0 && o.selBytes <= 0x80 && o.cmdBytes > 0 && o.cmdBytes <= 0x200);
        for (int off : o.selDataOffs) CHECK(off > 0 && off + 4 <= o.selBytes);
        CHECK(o.vecCountOff >= 0 && o.vecDataOff > o.vecCountOff);
        // the call sites are function entries: the anchor is the int3 padding before them, or the end of the previous function
        for (const char* id : { o.selCtorSite, o.moveCtorSite, o.movePushSite, o.cmdDtorSite, o.groundFnSite, o.cmdSite }) CHECK(Site(id)->anchorLen >= 2);
        // the move ctor's guard is longer than the 16 bytes its sibling ctors share
        CHECK(Site(o.moveCtorSite)->len >= 32);
    }
    {   // source lints
        const std::string cc = tk::ReadFile("core/orders.cpp"), ch = tk::ReadFile("core/orders.h");
        CHECK(!cc.empty() && !ch.empty());
        // key off: install returns before any site address; every entry refuses before any engine read
        const size_t inst = cc.find("void OrdersInstall()"), keyRet = cc.find("if (!s_key || s_installed) return;", inst),
                     plan = cc.find("rt.plan.engineHooks", inst), firstSite = cc.find("SiteAddress(", inst);
        CHECK(inst != std::string::npos && keyRet < plan && plan < firstSite);
        for (const char* fn : { "bool MoveLocked(", "bool CommandLocked(", "bool OrdersUnit(", "bool OrdersArmy(", "bool OrdersSelection(", "bool OrdersPeek(" }) {
            const size_t f = cc.find(fn), k = cc.find("if (!s_key)", f), brace = cc.find("\n}", f);
            if (!(f != std::string::npos && k < brace && k - f < 200)) printf("    %s does not refuse first with dev.orders=0\n", fn);
            CHECK(f != std::string::npos && k < brace && k - f < 200);
        }
        // the move's engine calls come after every check (the last refusal before the first call)
        const size_t mv = cc.find("bool MoveLocked("), firstCall = cc.find("((GroundFn)s_groundFn)(", mv), lastWhy = cc.rfind("return false; }", firstCall),
                     exe = cc.find("Executable(f)", mv);
        CHECK(mv != std::string::npos && exe < firstCall && lastWhy < firstCall && cc.find("UnitOrderable(", mv) < firstCall);
        // the order is refused off the engine thread
        CHECK(cc.find("GetCurrentThreadId() != s_engineTid", mv) < firstCall);
        // nothing is written into engine memory: no memcpy or store into a pointer read from the game
        CHECK(cc.find("WriteProcessMemory") == std::string::npos && cc.find("VirtualProtect") == std::string::npos);
        for (const char* g : { "apoleon", "mpire" }) CHECK(cc.find(g) == std::string::npos && ch.find(g) == std::string::npos);
    }
    return tk::Done("test_orders");
}
