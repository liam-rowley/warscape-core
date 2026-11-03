// orders.cpp - the battle unit control route (J28): live unit state read from engine memory, the UI's own selection, and move/face
// orders built and pushed through the engine's own command path (Selection ctor, AddUnit, the move command ctor, the queue push, the
// command dtor), as the engine's script binding and its ground-order handler do; other unit commands (halt, formation toggles, ...)
// through the owner's own "current selection" dispatcher with the same one-unit selection (OrdersCommand). Nothing is patched or detoured: the functions are
// called, every address and offset comes from a checked engine_sites row (OrdersAdapter), every pointer is checked with VirtualQuery
// before it is read or called through (the mingw build has no SEH), and all preconditions are checked before the first engine call.
// dev.orders off: nothing here reads engine memory and every entry refuses. Decisions are pure (orders.h, host-tested).
// Threads: the order calls and the reads run on the engine thread only (the Lua pump: OrdersMove refuses any other thread); another
// thread posts with OrdersPost and the pump drains it (OrdersPump). Install runs at the first Direct3DCreate9. State under s_cs.
#include "runtime.h"
#include "dev.h"
#include "orders.h"
#include "ships.h"
#include <cstring>
#include <deque>
#include <map>

namespace wsp {
namespace {
CRITICAL_SECTION s_cs;
INIT_ONCE s_once = INIT_ONCE_STATIC_INIT;
BOOL CALLBACK InitCs(PINIT_ONCE, PVOID, PVOID*) { InitializeCriticalSection(&s_cs); return TRUE; }
struct Lock { Lock() { InitOnceExecuteOnce(&s_once, InitCs, nullptr, nullptr); EnterCriticalSection(&s_cs); } ~Lock() { LeaveCriticalSection(&s_cs); } };

bool s_key = false, s_installed = false;
std::string s_sitesWhy = "not installed yet";
const OrdersAdapter* s_ad = nullptr;
UnitLayout s_L;
uintptr_t s_global = 0;
uint32_t s_cellOff = 0, s_battleOff = 0, s_queueOff = 0, s_holderOff = 0, s_selOff = 0, s_selVec = 0, s_groundA = 0, s_groundB = 0;
uintptr_t s_cmd = 0, s_moving = 0, s_selCtor = 0, s_selAdd = 0, s_moveCtor = 0, s_movePush = 0, s_cmdDtor = 0, s_free = 0, s_groundFn = 0;
DWORD s_engineTid = 0, s_presentTid = 0, s_wndTid = 0;
uint32_t s_army = 0;          // the player's army, cached from the UI selection or the last unit a caller named
int s_orders = 0;
struct Posted { long id; uint32_t unit; MoveArgs a; };
std::deque<Posted> s_posted;
std::map<long, std::pair<bool, std::string>> s_postedResults;
long s_postSeq = 0;

constexpr size_t kSelBuf = 0x80, kCmdBuf = 0x200;   // larger than the adapter's object sizes (checked at install)

bool Readable(uintptr_t p, size_t n) {
    if (!p) return false;
    MEMORY_BASIC_INFORMATION mbi{};
    if (!VirtualQuery((const void*)p, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
    return p + n <= (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
}
bool Read(uint32_t a, void* out, size_t n) { if (!Readable(a, n)) return false; memcpy(out, (const void*)(uintptr_t)a, n); return true; }
bool ReadPtr(uintptr_t p, uint32_t& out) { return Read((uint32_t)p, &out, 4); }
uint32_t Operand(const char* site, int off) { const uintptr_t a = SiteAddress(site); return a ? *(const uint32_t*)(a + off) : 0; }
uint32_t Operand8(const char* site, int off) { const uintptr_t a = SiteAddress(site); return a ? *(const uint8_t*)(a + off) : 0; }
bool Executable(uintptr_t p) {
    MEMORY_BASIC_INFORMATION mbi{};
    return p && VirtualQuery((const void*)p, &mbi, sizeof mbi) && mbi.AllocationBase == (void*)GetModuleHandleW(nullptr) &&
           (mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY));
}
std::string Hex(uint32_t v) { char b[16]; snprintf(b, sizeof b, "0x%08x", v); return b; }

// owner = *global; battle = *(owner + a); queue = *(battle + b). s_cs held.
bool Battle(uint32_t& battle, uint32_t& queue, std::string& why) {
    uint32_t owner = 0;
    if (!ReadPtr(s_global, owner) || !owner) { why = "battle owner global empty (not in a battle?)"; return false; }
    if (!ReadPtr(owner + s_battleOff, battle) || !battle) { why = "no battle (not in a battle?)"; return false; }
    if (!ReadPtr(battle + s_queueOff, queue) || !queue || !Readable(queue, 16)) { why = "the battle has no command queue"; return false; }
    return true;
}

using CtorFn = void*(__thiscall*)(void* self);
using AddFn = void(__thiscall*)(void* sel, uint32_t unit);
using MoveFn = void*(__thiscall*)(void* self, void* sel, const uint32_t* loc, int angle, float width, int run, int queue);
using PushFn = uint32_t(__thiscall*)(void* queue, void* cmd);
using DtorFn = void(__thiscall*)(void* self);
using FreeFn = void(__cdecl*)(void* p);
using MovingFn = uint32_t(__thiscall*)(void* unit);
using DispatchFn = void(__thiscall*)(void* cell, void* sel, int cmd, float arg, int flag);
using GroundFn = void*(__thiscall*)(void* terrain, uint32_t* locOut, const float* xz, int a, int b, int c);

bool UnitLocked(uint32_t unit, UnitState& s, std::string& why) {
    s = ReadUnit(unit, s_L, Read);
    if (!s.ok) { why = s.why; return false; }
    s_army = s.army;
    // the engine's own is_moving (battle.unit.is_moving's callee: the entity table site is its entry), on the engine thread only, once
    // the decode proved the unit is a live UNIT of its army
    if (GetCurrentThreadId() == s_engineTid && Executable(s_moving)) s.moving = (((MovingFn)s_moving)((void*)(uintptr_t)unit) & 0xff) ? 1 : 0;
    return true;
}

bool MoveLocked(uint32_t unit, MoveArgs a, std::string& info, std::string& why) {
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (!s_installed) { why = "orders not installed: " + s_sitesWhy; return false; }
    if (GetCurrentThreadId() != s_engineTid) { why = "not the engine thread (post the order with OrdersPost)"; return false; }
    if (!CheckMove(a, why)) return false;
    UnitState s;
    if (!UnitLocked(unit, s, why)) return false;
    if (!UnitOrderable(s, why)) return false;
    ResolveMove(a, s);
    if (!a.hasWidth) { why = "no width given and the unit's own width is not readable"; return false; }
    uint32_t battle = 0, queue = 0, t1 = 0, terrain = 0;
    if (!Battle(battle, queue, why)) return false;
    if (!ReadPtr(battle + s_groundA, t1) || !t1 || !ReadPtr(t1 + s_groundB, terrain) || !terrain || !Readable(terrain, 16)) { why = "the battle has no ground projector"; return false; }
    for (uintptr_t f : { s_selCtor, s_selAdd, s_moveCtor, s_movePush, s_cmdDtor, s_free, s_groundFn })
        if (!Executable(f)) { why = "an order function is not executable code in the exe"; return false; }
    // every precondition holds: the engine calls
    uint32_t loc[5] = {};
    const float xz[2] = { a.x, a.z };
    ((GroundFn)s_groundFn)((void*)(uintptr_t)terrain, loc, xz, 0, 1, 0);   // the script path's projection: {x, ground y, z, frame, id}
    float lx, ly, lz; memcpy(&lx, &loc[0], 4); memcpy(&ly, &loc[1], 4); memcpy(&lz, &loc[2], 4);
    if (!std::isfinite(ly) || std::fabs(lx - a.x) > 0.01f || std::fabs(lz - a.z) > 0.01f) {
        char b[160]; snprintf(b, sizeof b, "the ground projection gave (%.3f, %.3f, %.3f) for (%.3f, %.3f)", lx, ly, lz, a.x, a.z);
        why = b; return false;
    }
    alignas(16) uint8_t sel[kSelBuf] = {}; alignas(16) uint8_t cmd[kCmdBuf] = {};
    ((CtorFn)s_selCtor)(sel);
    ((AddFn)s_selAdd)(sel, unit);
    uint32_t taken = 0; memcpy(&taken, sel + s_selVec + s_ad->vecCountOff, 4);
    bool pushed = false;
    const int16_t angle = RawFromDeg(a.facing);
    if (taken == 1) {
        ((MoveFn)s_moveCtor)(cmd, sel, loc, (int)angle, a.width, a.run ? 1 : 0, a.queue ? 1 : 0);
        pushed = (((PushFn)s_movePush)((void*)(uintptr_t)queue, cmd) & 0xff) != 0;
        ((DtorFn)s_cmdDtor)(cmd);
    }
    for (int off : s_ad->selDataOffs) { uint32_t p = 0; memcpy(&p, sel + off, 4); if (p) ((FreeFn)s_free)((void*)(uintptr_t)p); }
    if (taken != 1) { char b[96]; snprintf(b, sizeof b, "the engine refused the unit (AddUnit took %u: routing, dead or withdrawing)", taken); why = b; return false; }
    ++s_orders;
    char b[320];
    snprintf(b, sizeof b, "order #%d unit %s to (%.3f, %.3f, %.3f) facing %.3f (raw %d) width %.3f run %d queue %d pushed %d (was at %.3f, %.3f, %.3f facing %.3f, queued %d)",
             s_orders, Hex(unit).c_str(), lx, ly, lz, a.facing, (int)angle, a.width, a.run, a.queue, pushed ? 1 : 0, s.x, s.y, s.z, s.facing, s.queued);
    info = b;
    LOGI("orders: %s", b);
    if (!pushed) { why = "the queue push returned false"; return false; }
    return true;
}

// One unit through the owner's own "current selection" dispatcher (as every BattleUI.Current_Selection_* call does with the UI's
// selection), with a one-unit selection of our own: the engine builds and pushes the command for `cmd` (and drops it when it would).
bool CommandLocked(uint32_t unit, int cmd, float arg, std::string& info, std::string& why) {
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (!s_installed) { why = "orders not installed: " + s_sitesWhy; return false; }
    if (GetCurrentThreadId() != s_engineTid) { why = "not the engine thread"; return false; }
    if (cmd < 0 || cmd > 0xff || !std::isfinite(arg)) { why = "a command code is 0..255 and its argument a finite number"; return false; }
    UnitState s;
    if (!UnitLocked(unit, s, why)) return false;
    if (!UnitOrderable(s, why)) return false;
    uint32_t battle = 0, queue = 0, owner = 0, cellBattle = 0;
    if (!Battle(battle, queue, why)) return false;
    if (!ReadPtr(s_global, owner) || !ReadPtr(owner + s_cellOff, cellBattle) || cellBattle != battle) { why = "the owner's command cell does not hold the battle"; return false; }
    for (uintptr_t f : { s_selCtor, s_selAdd, s_free, s_cmd })
        if (!Executable(f)) { why = "an order function is not executable code in the exe"; return false; }
    alignas(16) uint8_t sel[kSelBuf] = {};
    ((CtorFn)s_selCtor)(sel);
    ((AddFn)s_selAdd)(sel, unit);
    uint32_t taken = 0; memcpy(&taken, sel + s_selVec + s_ad->vecCountOff, 4);
    if (taken == 1) ((DispatchFn)s_cmd)((void*)(uintptr_t)(owner + s_cellOff), sel, cmd, arg, 0);
    for (int off : s_ad->selDataOffs) { uint32_t p = 0; memcpy(&p, sel + off, 4); if (p) ((FreeFn)s_free)((void*)(uintptr_t)p); }
    if (taken != 1) { char b[96]; snprintf(b, sizeof b, "the engine refused the unit (AddUnit took %u: routing, dead or withdrawing)", taken); why = b; return false; }
    ++s_orders;
    char b[200];
    snprintf(b, sizeof b, "command #%d unit %s cmd %d (0x%x) arg %.3f dispatched (was at %.3f, %.3f facing %.3f, moving %d)", s_orders, Hex(unit).c_str(), cmd, cmd, arg,
             s.x, s.z, s.facing, s.moving);
    info = b;
    LOGI("orders: %s", b);
    return true;
}

// ---- ships (J60): their own decode (ships.h) and calls; the queue, Selection, dtor and free are the land route's above. The
// ship half installs only after the land half and turns off alone on a site mismatch (land unaffected).
const ShipsAdapter* s_sad = nullptr;
bool s_shipsInstalled = false;
std::string s_shipsWhy = "not installed yet";
ShipLayout s_SL;
uint32_t s_shipVec = 0, s_shipArmy = 0;
uintptr_t s_shipAdd = 0, s_shipLoc = 0, s_shipMoveCtor = 0, s_shipMovePush = 0, s_faceCtor = 0, s_facePush = 0, s_haltCtor = 0, s_haltPush = 0;

using LocFn = void*(__thiscall*)(void* self, uint32_t* locOut, const float* xz);
using ShipMoveFn = void*(__thiscall*)(void* self, void* sel, const uint32_t* loc, int sail, int mode, int queue);
using FaceFn = void*(__thiscall*)(void* self, void* sel, int angle, int flag, int queue);
using HaltFn = void*(__thiscall*)(void* self, void* sel);

bool ShipLocked(uint32_t ship, ShipState& s, std::string& why) {
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (!s_shipsInstalled) { why = "ship orders not installed: " + s_shipsWhy; return false; }
    s = ReadShip(ship, s_SL, Read);
    if (!s.ok) { why = s.why; return false; }
    s_shipArmy = s.army;
    return true;
}

// Every precondition of a ship order, in order: the key, the install, the thread, the ship's decode and the engine's own blocking flags,
// the battle and its queue, every call target. Then the one-ship Selection; `build` constructs the command into cmd and returns the push.
template <class Build>
bool ShipOrderLocked(uint32_t ship, const char* what, std::string& info, std::string& why, Build build) {
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (!s_shipsInstalled) { why = "ship orders not installed: " + s_shipsWhy; return false; }
    if (GetCurrentThreadId() != s_engineTid) { why = "not the engine thread"; return false; }
    ShipState s;
    if (!ShipLocked(ship, s, why) || !ShipOrderable(s, why)) return false;
    uint32_t battle = 0, queue = 0;
    if (!Battle(battle, queue, why)) return false;
    for (uintptr_t f : { s_selCtor, s_shipAdd, s_cmdDtor, s_free, s_shipLoc, s_shipMoveCtor, s_shipMovePush, s_faceCtor, s_facePush, s_haltCtor, s_haltPush })
        if (!Executable(f)) { why = "a ship order function is not executable code in the exe"; return false; }
    alignas(16) uint8_t sel[kSelBuf] = {};
    ((CtorFn)s_selCtor)(sel);
    ((AddFn)s_shipAdd)(sel, ship);
    uint32_t taken = 0; memcpy(&taken, sel + s_shipVec + s_ad->vecCountOff, 4);
    std::string detail; bool pushed = false;
    if (taken == 1) pushed = build((void*)(uintptr_t)queue, sel, detail);
    for (int off : s_ad->selDataOffs) { uint32_t p = 0; memcpy(&p, sel + off, 4); if (p) ((FreeFn)s_free)((void*)(uintptr_t)p); }
    if (taken != 1) { char b[96]; snprintf(b, sizeof b, "the engine refused the ship (AddShip took %u: routing, sinking or withdrawing)", taken); why = b; return false; }
    ++s_orders;
    char b[384];
    snprintf(b, sizeof b, "%s #%d ship %s %s pushed %d (was at %.3f, %.3f, %.3f heading %.3f, sail %s %.3f)", what, s_orders, Hex(ship).c_str(),
             detail.c_str(), pushed ? 1 : 0, s.x, s.y, s.z, s.heading, SailName(s.sail), s.sailLevel);
    info = b;
    LOGI("orders: %s", b);
    if (!pushed) { why = "the queue push returned false: " + detail; return false; }
    return true;
}

// Push one command already built in cmd, then its dtor. s_cs held.
bool PushCmd(uintptr_t push, void* queue, uint8_t* cmd) {
    const bool ok = (((PushFn)push)(queue, cmd) & 0xff) != 0;
    ((DtorFn)s_cmdDtor)(cmd);
    return ok;
}

bool ShipFaceBuild(void* queue, uint8_t* sel, double heading, int flag, bool q, std::string& detail) {
    alignas(16) uint8_t cmd[kCmdBuf] = {};
    const int16_t angle = RawFromDeg(heading);
    ((FaceFn)s_faceCtor)(cmd, sel, (int)angle, flag ? 1 : 0, q ? 1 : 0);
    char b[96]; snprintf(b, sizeof b, "face %.3f (raw %d) flag %d queue %d", heading, (int)angle, flag ? 1 : 0, q ? 1 : 0); detail += b;
    return PushCmd(s_facePush, queue, cmd);
}

bool ShipMoveLocked(uint32_t ship, const ShipMoveArgs& a, std::string& info, std::string& why) {
    if (!CheckShipMove(a, why)) return false;
    uint32_t loc[5] = {};
    return ShipOrderLocked(ship, "ship move", info, why, [&](void* queue, uint8_t* sel, std::string& detail) {
        const float xz[2] = { a.x, a.z };
        ((LocFn)s_shipLoc)(nullptr, loc, xz);   // the script path's target: (x, sea level, z); `this` is not read
        float lx, ly, lz; memcpy(&lx, &loc[0], 4); memcpy(&ly, &loc[1], 4); memcpy(&lz, &loc[2], 4);
        char b[192];
        if (!std::isfinite(ly) || std::fabs(lx - a.x) > 0.01f || std::fabs(lz - a.z) > 0.01f) {
            snprintf(b, sizeof b, "the ship location gave (%.3f, %.3f, %.3f) for (%.3f, %.3f): not pushed", lx, ly, lz, a.x, a.z); detail = b; return false;
        }
        const int sail = a.sail >= 0 ? s_SL.sails[a.sail] : s_sad->moveSail;
        alignas(16) uint8_t cmd[kCmdBuf] = {};
        ((ShipMoveFn)s_shipMoveCtor)(cmd, sel, loc, sail, s_sad->moveMode, a.queue ? 1 : 0);
        snprintf(b, sizeof b, "to (%.3f, %.3f, %.3f) sail %d mode %d queue %d", lx, ly, lz, sail, s_sad->moveMode, a.queue ? 1 : 0); detail = b;
        if (!PushCmd(s_shipMovePush, queue, cmd)) return false;
        if (!a.hasHeading) return true;
        detail += "; then ";
        return ShipFaceBuild(queue, sel, a.heading, 0, true, detail);   // the move has no heading: a queued facing order after it
    });
}

BOOL CALLBACK FindWnd(HWND h, LPARAM p) {
    DWORD pid = 0; const DWORD tid = GetWindowThreadProcessId(h, &pid);
    if (pid == GetCurrentProcessId() && IsWindowVisible(h) && !GetWindow(h, GW_OWNER)) { *(DWORD*)p = tid; return FALSE; }
    return TRUE;
}
} // namespace

void OrdersInit(bool key, const OrdersAdapter* ad) {
    Lock l;
    s_key = key && ad; s_ad = ad;
    LOGI("orders: dev.orders=%d%s", key ? 1 : 0, key && !ad ? " but the adapter has no orders route: off" : "");
}

void OrdersInstall() {
    Lock l;
    if (!s_key || s_installed) return;
    const Runtime& rt = Rt();
    if (!rt.plan.engineHooks || !rt.plan.engineReads) { s_sitesWhy = "the exe guard's plan allows no engine calls"; LOGW("orders: not installed: %s", s_sitesWhy.c_str()); return; }
    const OrdersAdapter& a = *s_ad;
    for (const char* s : { a.queueSite, a.uiSelectionSite, a.selAddSite, a.entitySite, a.entityOrdersSite, a.positionSite, a.positionXyzSite,
                           a.frameSite, a.bearingSite, a.menSite, a.armySite, a.selCtorSite, a.moveCtorSite, a.movePushSite, a.cmdDtorSite,
                           a.freeSite, a.groundChainSite, a.groundFnSite, a.cmdCellSite, a.cmdSite })
        if (!SiteAddress(s)) { s_sitesWhy = std::string("site ") + s + " not accepted by the patch engine" + (rt.sitesWhy.empty() ? "" : ": " + rt.sitesWhy); LOGE("orders: not installed: %s", s_sitesWhy.c_str()); return; }
    if (a.selBytes <= 0 || (size_t)a.selBytes > kSelBuf || a.cmdBytes <= 0 || (size_t)a.cmdBytes > kCmdBuf) { s_sitesWhy = "the adapter's object sizes exceed the driver's buffers"; LOGE("orders: not installed: %s", s_sitesWhy.c_str()); return; }
    s_global = Operand(a.queueSite, a.globalOperand);
    s_battleOff = Operand(a.queueSite, a.battleOperand);
    s_queueOff = Operand(a.queueSite, a.queueOperand);
    s_holderOff = Operand(a.uiSelectionSite, a.holderOperand);
    s_selOff = Operand8(a.uiSelectionSite, a.selOperand8);
    s_selVec = Operand8(a.selAddSite, a.selVecOperand8);
    s_L.activeIdx = Operand(a.entitySite, a.activeIdxOperand);
    s_L.entities = Operand(a.entitySite, a.entitiesOperand);
    s_L.orderCount = Operand(a.entityOrdersSite, a.orderCountOperand);
    s_L.posBlock = Operand(a.positionSite, a.posBlockOperand);
    s_L.xyz = Operand(a.positionXyzSite, a.xyzOperand);
    s_L.frame = Operand8(a.frameSite, a.frameOperand8);
    s_L.facing = Operand(a.bearingSite, a.bearingOperand);
    s_L.men = Operand(a.menSite, a.menOperand);
    s_L.army = Operand(a.armySite, a.armyOperand);
    s_L.armyCount = Operand(a.armySite, a.armyCountOperand);
    s_L.armyList = Operand(a.armySite, a.armyListOperand);
    s_L.frontOff = a.frontOff; s_L.widthOff = a.widthOff;
    const uint32_t posEntity = Operand(a.positionSite, a.posEntityOperand);
    if (posEntity != s_L.entities) { s_sitesWhy = "the position getter's entity offset differs from the entity table's"; LOGE("orders: not installed: %s", s_sitesWhy.c_str()); return; }
    s_cellOff = Operand(a.cmdCellSite, a.cmdCellOperand);
    s_cmd = SiteAddress(a.cmdSite);
    s_groundA = Operand8(a.groundChainSite, a.groundAOperand8);
    s_groundB = Operand(a.groundChainSite, a.groundBOperand);
    s_moving = SiteAddress(a.entitySite);
    s_selCtor = SiteAddress(a.selCtorSite); s_selAdd = SiteAddress(a.selAddSite); s_moveCtor = SiteAddress(a.moveCtorSite);
    s_movePush = SiteAddress(a.movePushSite); s_cmdDtor = SiteAddress(a.cmdDtorSite); s_free = SiteAddress(a.freeSite); s_groundFn = SiteAddress(a.groundFnSite);
    s_installed = true; s_sitesWhy.clear();
    LOGI("orders: install: owner global %p, battle +0x%x, queue +0x%x, ui selection [owner+0x%x]+0x%x, selection vector +0x%x; UNIT: entities +0x%x, "
         "active +0x%x, army +0x%x (count +0x%x, list +0x%x), men +0x%x; entity: block +0x%x xyz +0x%x frame +0x%x, facing +0x%x, orders +0x%x; "
         "front +0x%x width +0x%x (readback-proven); ground [[battle+0x%x]+0x%x]; calls sel %p add %p move %p push %p dtor %p free %p ground %p",
         (void*)s_global, s_battleOff, s_queueOff, s_holderOff, s_selOff, s_selVec, s_L.entities, s_L.activeIdx, s_L.army, s_L.armyCount, s_L.armyList,
         s_L.men, s_L.posBlock, s_L.xyz, s_L.frame, s_L.facing, s_L.orderCount, s_L.frontOff, s_L.widthOff, s_groundA, s_groundB, (void*)s_selCtor,
         (void*)s_selAdd, (void*)s_moveCtor, (void*)s_movePush, (void*)s_cmdDtor, (void*)s_free, (void*)s_groundFn);
}

void OrdersPump() {
    if (!s_key) return;
    std::deque<Posted> take;
    {
        Lock l;
        if (!s_engineTid) { s_engineTid = GetCurrentThreadId(); LOGI("orders: engine thread (the Lua pump) is %lu", s_engineTid); }
        if (s_posted.empty()) return;
        take.swap(s_posted);
    }
    for (Posted& p : take) {
        std::string info, why;
        Lock l;
        const bool ok = MoveLocked(p.unit, p.a, info, why);
        s_postedResults[p.id] = { ok, ok ? info : why };
        while (s_postedResults.size() > 256) s_postedResults.erase(s_postedResults.begin());
    }
}

void OrdersPresent() {
    if (!s_key || s_presentTid) return;
    Lock l;
    if (s_presentTid) return;
    s_presentTid = GetCurrentThreadId();
    EnumWindows(FindWnd, (LPARAM)&s_wndTid);
    LOGI("orders: threads: Present %lu, the game window's procedure %lu, the Lua pump %lu (0 = no pump yet)", s_presentTid, s_wndTid, s_engineTid);
}

bool OrdersMove(uint32_t unit, const MoveArgs& a, std::string& info, std::string& why) { Lock l; return MoveLocked(unit, a, info, why); }
bool OrdersCommand(uint32_t unit, int cmd, float arg, std::string& info, std::string& why) { Lock l; return CommandLocked(unit, cmd, arg, info, why); }

long OrdersPost(uint32_t unit, const MoveArgs& a) {
    Lock l;
    if (!s_key) return 0;
    s_posted.push_back({ ++s_postSeq, unit, a });
    return s_postSeq;
}
bool OrdersPostResult(long id, bool& ok, std::string& text) {
    Lock l;
    auto it = s_postedResults.find(id);
    if (it == s_postedResults.end()) return false;
    ok = it->second.first; text = it->second.second; s_postedResults.erase(it);
    return true;
}

bool OrdersUnit(uint32_t unit, UnitState& s, std::string& why) {
    Lock l;
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (!s_installed) { why = "orders not installed: " + s_sitesWhy; return false; }
    return UnitLocked(unit, s, why);
}

bool OrdersArmy(uint32_t unit, std::vector<uint32_t>& units, std::string& why) {
    Lock l;
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (!s_installed) { why = "orders not installed: " + s_sitesWhy; return false; }
    if (unit) { UnitState s; if (!UnitLocked(unit, s, why)) return false; }
    if (!s_army) { why = "no army known yet: name a unit, or select one in the UI and read the selection first"; return false; }
    uint32_t cnt = 0, list = 0;
    if (!ReadPtr(s_army + s_L.armyCount, cnt) || !ReadPtr(s_army + s_L.armyList, list) || (int)cnt < 0 || (int)cnt > s_L.maxArmy) { why = "the army's unit list is not readable"; s_army = 0; return false; }
    units.clear();
    for (uint32_t i = 0; i < cnt; ++i) { uint32_t p = 0; if (!ReadPtr(list + 4 * i, p)) { why = "the army's unit list is not readable"; return false; } units.push_back(p); }
    return true;
}

bool OrdersSelection(std::vector<uint32_t>& loose, int& groups, std::string& why) {
    Lock l;
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (!s_installed) { why = "orders not installed: " + s_sitesWhy; return false; }
    uint32_t owner = 0, holder = 0, cnt = 0, data = 0, gcnt = 0;
    if (!ReadPtr(s_global, owner) || !owner || !ReadPtr(owner + s_holderOff, holder) || !holder) { why = "no UI selection holder (not in a battle?)"; return false; }
    const uint32_t S = holder + s_selOff, vec = S + s_selVec;
    if (!ReadPtr(vec + s_ad->vecCountOff, cnt) || !ReadPtr(vec + s_ad->vecDataOff, data) || (int)cnt < 0 || (int)cnt > s_L.maxArmy) { why = "the UI selection is not readable"; return false; }
    // the land groups' vector is the one before the loose units' (the same container shape, 0x10 bytes earlier)
    if (!ReadPtr(vec - 0x10 + s_ad->vecCountOff, gcnt) || (int)gcnt < 0 || (int)gcnt > s_L.maxArmy) { why = "the UI selection's groups are not readable"; return false; }
    groups = (int)gcnt;
    loose.clear();
    for (uint32_t i = 0; i < cnt; ++i) { uint32_t p = 0; if (!ReadPtr(data + 4 * i, p)) { why = "the UI selection is not readable"; return false; } loose.push_back(p); }
    if (!loose.empty()) { UnitState s; std::string w; UnitLocked(loose[0], s, w); }   // caches the army
    return true;
}

bool OrdersPeek(uint32_t a, size_t n, std::string& hex, std::string& why) {
    Lock l;
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (n == 0 || n > 512) { why = "peek reads 1 to 512 bytes"; return false; }
    std::string buf(n, '\0');
    if (!Read(a, &buf[0], n)) { why = "not readable"; return false; }
    hex.clear(); char b[4];
    for (size_t i = 0; i < n; ++i) { snprintf(b, sizeof b, "%02x", (uint8_t)buf[i]); hex += b; }
    return true;
}

// W6: the ground height the move order would use at (x, z): the same projector call as MoveLocked, nothing else. It calls engine code,
// so only on the thread that runs the Lua pump or Present (one thread in the games proven so far; a gesture press arrives on it).
bool OrdersGroundAt(float x, float z, float& y, std::string& why) {
    Lock l;
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (!s_installed) { why = "orders not installed: " + s_sitesWhy; return false; }
    const DWORD tid = GetCurrentThreadId();
    if (tid != s_engineTid && tid != s_presentTid) { why = "not the engine or Present thread"; return false; }
    if (!std::isfinite(x) || !std::isfinite(z)) { why = "a ground point has finite numbers only"; return false; }
    uint32_t battle = 0, queue = 0, t1 = 0, terrain = 0;
    if (!Battle(battle, queue, why)) return false;
    if (!ReadPtr(battle + s_groundA, t1) || !t1 || !ReadPtr(t1 + s_groundB, terrain) || !terrain || !Readable(terrain, 16)) { why = "the battle has no ground projector"; return false; }
    if (!Executable(s_groundFn)) { why = "the ground projector is not executable code in the exe"; return false; }
    uint32_t loc[5] = {};
    const float xz[2] = { x, z };
    ((GroundFn)s_groundFn)((void*)(uintptr_t)terrain, loc, xz, 0, 1, 0);
    float lx, ly, lz; memcpy(&lx, &loc[0], 4); memcpy(&ly, &loc[1], 4); memcpy(&lz, &loc[2], 4);
    if (!std::isfinite(ly) || std::fabs(lx - x) > 0.01f || std::fabs(lz - z) > 0.01f) { why = "no ground there (the projection moved the point)"; return false; }
    y = ly;
    return true;
}

// ---- ships (J60)
void OrdersShipsInit(const ShipsAdapter* ad) {
    Lock l;
    s_sad = ad;
    if (s_key && !ad) LOGI("orders: the adapter has no ship route: ships off");
}

// After OrdersInstall: verify the ship sites and read their operands. Off alone on a mismatch.
void OrdersShipsInstall() {
    Lock l;
    if (!s_key || !s_sad || s_shipsInstalled) return;
    if (!s_installed) { s_shipsWhy = "the land route is not installed: " + s_sitesWhy; LOGW("orders: ships not installed: %s", s_shipsWhy.c_str()); return; }
    const ShipsAdapter& a = *s_sad;
    for (const char* s : { a.vtableSite, a.positionSite, a.bearingSite, a.fleetSite, a.sailSite, a.orderableSite, a.surrenderSite, a.windChainSite,
                           a.windVectorSite, a.windAngleSite, a.selAddShipSite, a.locationSite, a.moveCtorSite, a.movePushSite, a.faceCtorSite,
                           a.facePushSite, a.haltCtorSite, a.haltPushSite })
        if (!SiteAddress(s)) { s_shipsWhy = std::string("site ") + s + " not accepted by the patch engine"; LOGE("orders: ships not installed: %s", s_shipsWhy.c_str()); return; }
    if (a.cmdBytes <= 0 || (size_t)a.cmdBytes > kCmdBuf) { s_shipsWhy = "the adapter's ship command size exceeds the driver's buffer"; LOGE("orders: ships not installed: %s", s_shipsWhy.c_str()); return; }
    ShipLayout L;
    L.vtable = Operand(a.vtableSite, a.vtableOperand);   // the loader relocated it: the live vtable address
    L.pos = Operand8(a.positionSite, a.posOperand8);
    L.m02 = Operand(a.bearingSite, a.m02Operand); L.m22 = Operand(a.bearingSite, a.m22Operand);
    L.army = Operand(a.fleetSite, a.armyOperand); L.count = Operand(a.fleetSite, a.countOperand); L.list = Operand(a.fleetSite, a.listOperand);
    L.sail = Operand(a.sailSite, a.sailOperand);
    L.blockA = Operand(a.orderableSite, a.blockAOperand); L.blockB = Operand(a.orderableSite, a.blockBOperand);
    L.state = Operand(a.orderableSite, a.stateOperand); L.stateBad = Operand8(a.orderableSite, a.stateBadOperand8);
    L.surr = Operand(a.surrenderSite, a.surrenderOperand); L.surrValue = Operand8(a.surrenderSite, a.surrenderValueOperand8);
    L.windA = Operand(a.windChainSite, a.windAOperand); L.windB = Operand8(a.windChainSite, a.windBOperand8); L.windC = Operand(a.windChainSite, a.windCOperand);
    L.windX = Operand8(a.windVectorSite, a.windXOperand8); L.windZ = Operand8(a.windVectorSite, a.windZOperand8);
    L.windAngle = Operand(a.windAngleSite, a.windAngleOperand);
    for (int i = 0; i < 4; ++i) L.sails[i] = a.sails[i];
    for (int i = 0; i < 3; ++i) L.sailAbove[i] = a.sailAbove[i];
    // the position offset is the ship vtable's slot 0: prove the vtable's first entry is the position site's function
    uint32_t slot0 = 0;
    if (!ReadPtr(L.vtable, slot0) || slot0 != (uint32_t)SiteAddress(a.positionSite)) {
        s_shipsWhy = "the ship vtable's slot 0 is not the position getter site"; LOGE("orders: ships not installed: %s", s_shipsWhy.c_str()); return;
    }
    s_shipVec = Operand8(a.selAddShipSite, a.shipVecOperand8);
    s_shipAdd = SiteAddress(a.selAddShipSite); s_shipLoc = SiteAddress(a.locationSite);
    s_shipMoveCtor = SiteAddress(a.moveCtorSite); s_shipMovePush = SiteAddress(a.movePushSite);
    s_faceCtor = SiteAddress(a.faceCtorSite); s_facePush = SiteAddress(a.facePushSite);
    s_haltCtor = SiteAddress(a.haltCtorSite); s_haltPush = SiteAddress(a.haltPushSite);
    s_SL = L; s_shipsInstalled = true; s_shipsWhy.clear();
    LOGI("orders: ships install: vtable 0x%08x pos +0x%x heading atan2(+0x%x, +0x%x) army +0x%x (count +0x%x, list +0x%x) sail +0x%x (above %.3f/%.3f/%.3f) "
         "blocked +0x%x/+0x%x/+0x%x==%u surrendered +0x%x==%u wind [[[ship+0x%x]+0x%x]+0x%x] (+0x%x, +0x%x) angle +0x%x; selection ship vector +0x%x; "
         "calls add %p loc %p move %p/%p face %p/%p halt %p/%p",
         L.vtable, L.pos, L.m02, L.m22, L.army, L.count, L.list, L.sail, L.sailAbove[0], L.sailAbove[1], L.sailAbove[2], L.blockA, L.blockB, L.state, L.stateBad,
         L.surr, L.surrValue, L.windA, L.windB, L.windC, L.windX, L.windZ, L.windAngle, s_shipVec, (void*)s_shipAdd, (void*)s_shipLoc, (void*)s_shipMoveCtor,
         (void*)s_shipMovePush, (void*)s_faceCtor, (void*)s_facePush, (void*)s_haltCtor, (void*)s_haltPush);
}

bool OrdersShip(uint32_t ship, ShipState& s, std::string& why) { Lock l; return ShipLocked(ship, s, why); }

bool OrdersFleet(uint32_t ship, std::vector<uint32_t>& ships, std::string& why) {
    Lock l;
    if (ship) { ShipState s; if (!ShipLocked(ship, s, why)) return false; }
    else if (!s_key) { why = "dev.orders=0"; return false; }
    else if (!s_shipsInstalled) { why = "ship orders not installed: " + s_shipsWhy; return false; }
    if (!s_shipArmy) { why = "no fleet known yet: name a ship, or select one in the UI and read the ship selection first"; return false; }
    uint32_t cnt = 0, list = 0;
    if (!ReadPtr(s_shipArmy + s_SL.count, cnt) || !ReadPtr(s_shipArmy + s_SL.list, list) || (int)cnt < 0 || (int)cnt > s_SL.maxFleet) { why = "the army's fleet list is not readable"; s_shipArmy = 0; return false; }
    ships.clear();
    for (uint32_t i = 0; i < cnt; ++i) { uint32_t p = 0; if (!ReadPtr(list + 4 * i, p)) { why = "the army's fleet list is not readable"; return false; } ships.push_back(p); }
    return true;
}

// The UI's own selection S, its ship part (the same Selection layout: the ship vector at the AddShip site's offset, groups 0x10 before).
bool OrdersShipSelection(std::vector<uint32_t>& ships, int& groups, std::string& why) {
    Lock l;
    if (!s_key) { why = "dev.orders=0"; return false; }
    if (!s_shipsInstalled) { why = "ship orders not installed: " + s_shipsWhy; return false; }
    uint32_t owner = 0, holder = 0, cnt = 0, data = 0, gcnt = 0;
    if (!ReadPtr(s_global, owner) || !owner || !ReadPtr(owner + s_holderOff, holder) || !holder) { why = "no UI selection holder (not in a battle?)"; return false; }
    const uint32_t vec = holder + s_selOff + s_shipVec;
    if (!ReadPtr(vec + s_ad->vecCountOff, cnt) || !ReadPtr(vec + s_ad->vecDataOff, data) || (int)cnt < 0 || (int)cnt > s_SL.maxFleet) { why = "the UI selection's ships are not readable"; return false; }
    if (!ReadPtr(vec - 0x10 + s_ad->vecCountOff, gcnt) || (int)gcnt < 0 || (int)gcnt > s_SL.maxFleet) { why = "the UI selection's ship groups are not readable"; return false; }
    groups = (int)gcnt;
    ships.clear();
    for (uint32_t i = 0; i < cnt; ++i) { uint32_t p = 0; if (!ReadPtr(data + 4 * i, p)) { why = "the UI selection is not readable"; return false; } ships.push_back(p); }
    if (!ships.empty()) { ShipState s; std::string w; ShipLocked(ships[0], s, w); }   // caches the fleet
    return true;
}

bool OrdersShipMove(uint32_t ship, const ShipMoveArgs& a, std::string& info, std::string& why) { Lock l; return ShipMoveLocked(ship, a, info, why); }

bool OrdersShipFace(uint32_t ship, double heading, int flag, bool queue, std::string& info, std::string& why) {
    Lock l;
    if (!CheckFace(heading, why)) return false;
    return ShipOrderLocked(ship, "ship face", info, why, [&](void* q, uint8_t* sel, std::string& detail) { return ShipFaceBuild(q, sel, heading, flag, queue, detail); });
}

bool OrdersShipHalt(uint32_t ship, std::string& info, std::string& why) {
    Lock l;
    return ShipOrderLocked(ship, "ship halt", info, why, [&](void* q, uint8_t* sel, std::string& detail) {
        alignas(16) uint8_t cmd[kCmdBuf] = {};
        ((HaltFn)s_haltCtor)(cmd, sel);
        detail = "halt";
        return PushCmd(s_haltPush, q, cmd);
    });
}

std::string OrdersInfo() {
    Lock l;
    char b[512];
    uint32_t owner = 0, battle = 0, queue = 0, holder = 0; std::string w;
    if (s_installed) { ReadPtr(s_global, owner); if (owner) { ReadPtr(owner + s_battleOff, battle); ReadPtr(owner + s_holderOff, holder); } if (battle) ReadPtr(battle + s_queueOff, queue); }
    snprintf(b, sizeof b, "key=%d installed=%d why=%s owner=%s battle=%s queue=%s holder=%s army=%s orders=%d threads: pump=%lu present=%lu wnd=%lu caller=%lu",
             s_key, s_installed, s_installed ? "" : s_sitesWhy.c_str(), Hex(owner).c_str(), Hex(battle).c_str(), Hex(queue).c_str(), Hex(holder).c_str(),
             Hex(s_army).c_str(), s_orders, s_engineTid, s_presentTid, s_wndTid, GetCurrentThreadId());
    return b;
}

} // namespace wsp
