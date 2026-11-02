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
