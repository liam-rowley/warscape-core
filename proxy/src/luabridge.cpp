// luabridge.cpp - the engine's Lua side of the dev control channel (no RmlUi). Ported from empire-remastered
// rml_mod/src/lua_bridge.cpp (loading, sentinel, safety rules); the API is new and small.
//
// Loading: the game's wrapper scripts (proxy/<game>/lua, served to the engine by the file rules of dev.lua_bridge) run
//     package.loadlib(".\\d3d9.dll", "wsp_sentinel")({})      -- an EMPTY table made by the engine's VM: its node pointer is the
//                                                              -- engine's static dummynode, which our Lua core then uses
//     package.loadlib(".\\d3d9.dll", "luaopen_wsp")()          -- registers the global table `wsp` and returns it
// Our copy of the Lua 5.1.1 core (proxy/tools/fetch_lua.py: float numbers, runtime dummynode, no GC step of our own) operates on the
// engine's lua_State directly; 5.1 struct layouts are identical. No state of our own is ever created.
// Rules that keep this safe (empire-remastered, proven there):
//   * never raise a Lua error from C (no luaL_error / luaL_check*): bad arguments are treated as missing, failures return nil, msg
//   * never call back into Lua from C: commands are queued here and the Lua pump takes them with wsp.poll()
//   * the engine thread only (render == UI == Lua); the control thread talks to it through the locked queue below
// API (the table `wsp`; proxy/README.md "Dev control channel"):
//   wsp.log(text)                          a line in proxy.log ("lua: ...")
//   wsp.poll(ctx) -> nil | { {id=, verb=, arg=}, ... }   called by every wrapped OnUpdate/OnUpdatePulse; ctx = frontend|campaign|battle
//   wsp.result(id, ok, text)               the outcome of a polled command
//   wsp.dev_config(key) -> string          target.kind|mode|campaign|faction|save|preset, preset.<key>, lua_dir, ctx, scene
//   wsp.dev_state(naval, deploy_panel)     the battle probe (numbers or booleans; nil = unknown)
//   wsp.report(key, value)                 a fact the Lua side sees (battle.map, autostart.map, ...): state.json "reports", the log
//   wsp.vanilla(entry) -> bytes | nil, err the newest real pack's copy of a pack entry (a wrapper loads the vanilla script with it)
//   wsp.version() -> "wsp 1", build id
//   wsp.cam_set(x, y, z, yaw, pitch) -> true | nil, err   the battle camera (dev.camera, camera.cpp; J43)
//   battle unit orders (dev.orders, orders.cpp; J28). A unit ref is a "0x..." pointer string, a light userdata, a
//   full userdata (the engine's Pointer<UNIT>: its first dword), or a number n = the n-th unit (1-based) of the player's army as the last read saw it (lua numbers are floats here: never a pointer as a number):
//   wsp.unit_state(ref) -> {id, ptr, x, y, z, facing, facing_raw, men, queued, moving, army_index, army_count, front_x/y/z, width} | nil, err
//   wsp.unit_list([ref]) -> { {state}, ... } | nil, err    the army of ref (none: the cached player army)
//   wsp.selection() -> {units = {ptr, ...}, groups = n} | nil, err   the UI's own selection (loose land units)
//   wsp.order_move(ref, x, z, [facing], [width], [run], [queue]) -> true, info | nil, err   one unit, the engine's own command path
//   wsp.order_command(ref, cmd, [arg]) -> true, info | nil, err   the owner's "current selection" dispatcher with a one-unit selection
//                                                          (the codes are the game's: halt, formation toggles, run/walk ...)
//   wsp.peek(addr, n) -> hex | nil, err                     probe: n <= 512 bytes read (never a write)
//   wsp.orders_info() -> text                              install state, owner path, thread ids
//   ship orders (dev.orders, the ship half of orders.cpp; ships.h; J60). A ship ref: a unit ref's forms, or n = the n-th ship of the fleet:
//   wsp.ship_state(ref) -> {id, ptr, x, y, z, heading, heading_raw, m02, m22, sail, sail_level, surrendered, blocked, fleet_index,
//                           fleet_count, wind_x, wind_z, wind_angle} | nil, err   (no speed: two reads give it)
//   wsp.ship_list([ref]) -> { {state}, ... } | nil, err    the fleet of ref (none: the cached player fleet)
//   wsp.ship_selection() -> {ships = {ptr, ...}, groups = n} | nil, err   the UI's own selection, its ships
//   wsp.ship_move(ref, x, z, [heading], [sail], [queue]) -> true, info | nil, err   sail "stationary"|"battle"|"half"|"full"; a heading
//                                                          is a queued facing order after the move (the move has none)
//   wsp.ship_face(ref, heading, [flag], [queue]) -> true, info | nil, err   the engine's rotate command (flag: the engine's own)
//   wsp.ship_halt(ref) -> true, info | nil, err
#include "dev.h"
#include <deque>
#include <map>
#include <set>
#include <cstring>
extern "C" {
#include "lua.h"
#include "lauxlib.h"
#include "lobject.h"
#include "lstate.h"
extern const Node* g_engine_dummynode;
}

#ifndef WSP_BUILD_ID
#define WSP_BUILD_ID "dev"
#endif

namespace wsp {
namespace {
CRITICAL_SECTION s_cs;
INIT_ONCE s_once = INIT_ONCE_STATIC_INIT;
BOOL CALLBACK InitCs(PINIT_ONCE, PVOID, PVOID*) { InitializeCriticalSection(&s_cs); return TRUE; }
struct Lock { Lock() { InitOnceExecuteOnce(&s_once, InitCs, nullptr, nullptr); EnterCriticalSection(&s_cs); } ~Lock() { LeaveCriticalSection(&s_cs); } };

std::deque<LuaCmd> s_queue;
std::map<std::string, std::pair<bool, std::string>> s_results;
std::set<std::string> s_dropped;
volatile LONG s_loaded = 0;
double s_lastPump = -1;
std::string s_lastCtx;
std::set<std::string> s_ctxSeen;

bool Allowed() { return DevActive() && Dk().luaBridge && Rt().plan.engineReads; }

int Fail(lua_State* L, const char* msg) { lua_pushnil(L); lua_pushstring(L, msg); return 2; }
const char* Str(lua_State* L, int i, const char* def = nullptr) { return lua_type(L, i) == LUA_TSTRING ? lua_tostring(L, i) : def; }
int Tri(lua_State* L, int i) {
    if (lua_type(L, i) == LUA_TNUMBER) return (int)lua_tonumber(L, i);
    if (lua_type(L, i) == LUA_TBOOLEAN) return lua_toboolean(L, i) ? 1 : 0;
    return -1;
}

int l_log(lua_State* L) { LOGI("lua: %s", Str(L, 1, "(not a string)")); return 0; }
int l_version(lua_State* L) { lua_pushstring(L, "wsp 1"); lua_pushstring(L, WSP_BUILD_ID); return 2; }

int l_poll(lua_State* L) {
    const char* ctx = Str(L, 1, "?");
    {
        Lock l;
        s_lastPump = MonoS(); s_lastCtx = ctx;
        if (s_ctxSeen.insert(ctx).second) LOGI("lua: first pump from context '%s' (thread %lu)", ctx, GetCurrentThreadId());
    }
    DevPump(ctx);
    std::deque<LuaCmd> take;
    {
        Lock l;
        if (s_queue.empty()) { lua_pushnil(L); return 1; }   // no allocation on idle pumps
        for (auto it = s_queue.begin(); it != s_queue.end();) {
            if (it->ctx.empty() || it->ctx == ctx) { take.push_back(*it); it = s_queue.erase(it); } else ++it;
        }
        if (take.empty()) { lua_pushnil(L); return 1; }
    }
    lua_createtable(L, (int)take.size(), 0);
    int i = 1;
    for (const LuaCmd& c : take) {
        lua_createtable(L, 0, 3);
        lua_pushstring(L, c.id.c_str()); lua_setfield(L, -2, "id");
        lua_pushstring(L, c.verb.c_str()); lua_setfield(L, -2, "verb");
        lua_pushstring(L, c.arg.c_str()); lua_setfield(L, -2, "arg");
        lua_rawseti(L, -2, i++);
    }
    return 1;
}
int l_result(lua_State* L) {
    const char* id = Str(L, 1);
    if (!id) return Fail(L, "expected (id, ok, text)");
    const bool ok = lua_toboolean(L, 2) != 0;
    std::string text = Str(L, 3, "");
    Lock l;
    if (s_dropped.erase(id)) { LOGW("lua: late result for %s (timed out already): %s %s", id, ok ? "ok" : "failed", text.c_str()); return 0; }
    s_results[id] = { ok, text };
    return 0;
}
int l_dev_config(lua_State* L) { lua_pushstring(L, DevConfigValue(Str(L, 1, "")).c_str()); return 1; }
int l_dev_state(lua_State* L) { DevBattleState(Tri(L, 1), Tri(L, 2)); return 0; }
int l_report(lua_State* L) {
    const char* k = Str(L, 1);
    if (!k) return Fail(L, "expected (key, value)");
    std::string v;
    if (lua_type(L, 2) == LUA_TSTRING || lua_type(L, 2) == LUA_TNUMBER) v = lua_tostring(L, 2);
    else if (lua_type(L, 2) == LUA_TBOOLEAN) v = lua_toboolean(L, 2) ? "true" : "false";
    DevReport(k, v);
    return 0;
}
int l_vanilla(lua_State* L) {
    const char* e = Str(L, 1);
    if (!e) return Fail(L, "expected a pack entry path");
    std::string bytes, err;
    if (!FilesVanillaEntry(e, bytes, err)) { LOGE("lua: wsp.vanilla(%s): %s", e, err.c_str()); return Fail(L, err.c_str()); }
    lua_pushlstring(L, bytes.data(), bytes.size());
    return 1;
}

int l_cam_set(lua_State* L) {
    for (int i = 1; i <= 5; ++i) if (lua_type(L, i) != LUA_TNUMBER) return Fail(L, "expected (x, y, z, yaw, pitch) numbers");
    CamPose p; p.x = (float)lua_tonumber(L, 1); p.y = (float)lua_tonumber(L, 2); p.z = (float)lua_tonumber(L, 3);
    p.yaw = (float)lua_tonumber(L, 4); p.pitch = (float)lua_tonumber(L, 5);
    std::string why;
    if (!CameraSet(p, why)) return Fail(L, why.c_str());
    lua_pushboolean(L, 1);
    return 1;
}

// ---- orders (J28)
bool UnitRef(lua_State* L, int i, uint32_t& unit, std::string& why) {
    if (lua_type(L, i) == LUA_TSTRING) {
        const char* t = lua_tostring(L, i); char* end = nullptr;
        unit = (uint32_t)strtoul(t, &end, 16);
        if (!unit || !end || *end) { why = "a unit ref string is a hex pointer (0x...)"; return false; }
        return true;
    }
    if (lua_type(L, i) == LUA_TLIGHTUSERDATA) { unit = (uint32_t)(uintptr_t)lua_touserdata(L, i); if (!unit) { why = "null unit"; return false; } return true; }
    if (lua_type(L, i) == LUA_TUSERDATA) {   // the engine's Pointer<T> userdata (BattleUI.UnitListForBattleIds): the pointer is its first dword
        const void* b = lua_touserdata(L, i);
        if (!b || lua_objlen(L, i) < 4) { why = "a userdata unit ref is smaller than a pointer"; return false; }
        memcpy(&unit, b, 4);
        if (!unit) { why = "null unit"; return false; }
        return true;
    }
    if (lua_type(L, i) == LUA_TNUMBER) {
        const int n = (int)lua_tonumber(L, i);
        std::vector<uint32_t> units;
        if (!OrdersArmy(0, units, why)) return false;
        if (n < 1 || n > (int)units.size()) { why = "unit number " + std::to_string(n) + " is not in the army (1.." + std::to_string(units.size()) + ")"; return false; }
        unit = units[n - 1]; return true;
    }
    why = "expected a unit ref (\"0x...\", a light userdata or the unit's number in the army)"; return false;
}
std::string HexPtr(uint32_t v) { char b[16]; snprintf(b, sizeof b, "0x%08x", v); return b; }
void SetNum(lua_State* L, const char* k, double v) { lua_pushnumber(L, (lua_Number)v); lua_setfield(L, -2, k); }
void PushState(lua_State* L, const UnitState& u) {
    lua_createtable(L, 0, 18);
    lua_pushstring(L, HexPtr(u.unit).c_str()); lua_setfield(L, -2, "ptr");
    SetNum(L, "id", u.armyIndex + 1); SetNum(L, "army_index", u.armyIndex); SetNum(L, "army_count", u.armyCount);
    lua_pushstring(L, HexPtr(u.army).c_str()); lua_setfield(L, -2, "army");
    SetNum(L, "x", u.x); SetNum(L, "y", u.y); SetNum(L, "z", u.z); SetNum(L, "facing", u.facing); SetNum(L, "facing_raw", u.facingRaw);
    SetNum(L, "men", u.men); SetNum(L, "queued", u.queued); SetNum(L, "moving", u.moving);
    if (u.hasFront) { SetNum(L, "front_x", u.fx); SetNum(L, "front_y", u.fy); SetNum(L, "front_z", u.fz); }
    if (u.hasWidth) SetNum(L, "width", u.width);
}
int l_unit_state(lua_State* L) {
    uint32_t unit = 0; std::string why; UnitState u;
    if (!UnitRef(L, 1, unit, why) || !OrdersUnit(unit, u, why)) return Fail(L, why.c_str());
    PushState(L, u);
    return 1;
}
int l_unit_list(lua_State* L) {
    uint32_t unit = 0; std::string why; std::vector<uint32_t> units;
    if (lua_gettop(L) >= 1 && !lua_isnil(L, 1) && !UnitRef(L, 1, unit, why)) return Fail(L, why.c_str());
    if (!OrdersArmy(unit, units, why)) return Fail(L, why.c_str());
    lua_createtable(L, (int)units.size(), 0);
    int i = 1;
    for (uint32_t p : units) {
        UnitState u; std::string w;
        if (OrdersUnit(p, u, w)) PushState(L, u);
        else { lua_createtable(L, 0, 2); lua_pushstring(L, HexPtr(p).c_str()); lua_setfield(L, -2, "ptr"); lua_pushstring(L, w.c_str()); lua_setfield(L, -2, "why"); }
        lua_rawseti(L, -2, i++);
    }
    return 1;
}
int l_selection(lua_State* L) {
    std::vector<uint32_t> loose; int groups = 0; std::string why;
    if (!OrdersSelection(loose, groups, why)) return Fail(L, why.c_str());
    lua_createtable(L, 0, 2);
    lua_createtable(L, (int)loose.size(), 0);
    int i = 1; for (uint32_t p : loose) { lua_pushstring(L, HexPtr(p).c_str()); lua_rawseti(L, -2, i++); }
    lua_setfield(L, -2, "units");
    SetNum(L, "groups", groups);
    return 1;
}
int l_order_move(lua_State* L) {
    uint32_t unit = 0; std::string why, info;
    if (!UnitRef(L, 1, unit, why)) return Fail(L, why.c_str());
    if (lua_type(L, 2) != LUA_TNUMBER || lua_type(L, 3) != LUA_TNUMBER) return Fail(L, "expected (unit, x, z, [facing], [width], [run], [queue])");
    MoveArgs a; a.x = (float)lua_tonumber(L, 2); a.z = (float)lua_tonumber(L, 3);
    if (lua_type(L, 4) == LUA_TNUMBER) { a.hasFacing = true; a.facing = lua_tonumber(L, 4); }
    if (lua_type(L, 5) == LUA_TNUMBER) { a.hasWidth = true; a.width = (float)lua_tonumber(L, 5); }
    a.run = lua_toboolean(L, 6) != 0; a.queue = lua_toboolean(L, 7) != 0;
    if (!OrdersMove(unit, a, info, why)) return Fail(L, why.c_str());
    lua_pushboolean(L, 1); lua_pushstring(L, info.c_str());
    return 2;
}
int l_order_command(lua_State* L) {
    uint32_t unit = 0; std::string why, info;
    if (!UnitRef(L, 1, unit, why)) return Fail(L, why.c_str());
    if (lua_type(L, 2) != LUA_TNUMBER) return Fail(L, "expected (unit, cmd, [arg])");
    const float arg = lua_type(L, 3) == LUA_TNUMBER ? (float)lua_tonumber(L, 3) : 0.0f;
    if (!OrdersCommand(unit, (int)lua_tonumber(L, 2), arg, info, why)) return Fail(L, why.c_str());
    lua_pushboolean(L, 1); lua_pushstring(L, info.c_str());
    return 2;
}
int l_peek(lua_State* L) {
    uint32_t a = 0; std::string why, hex;
    if (!UnitRef(L, 1, a, why)) return Fail(L, why.c_str());
    const int n = lua_type(L, 2) == LUA_TNUMBER ? (int)lua_tonumber(L, 2) : 64;
    if (!OrdersPeek(a, (size_t)(n < 0 ? 0 : n), hex, why)) return Fail(L, why.c_str());
    lua_pushstring(L, hex.c_str());
    return 1;
}
int l_orders_info(lua_State* L) { lua_pushstring(L, OrdersInfo().c_str()); return 1; }

// ---- ship orders (J60): a ship ref is a unit ref's forms, a number n being the n-th ship of the player's fleet
bool ShipRef(lua_State* L, int i, uint32_t& ship, std::string& why) {
    if (lua_type(L, i) != LUA_TNUMBER) return UnitRef(L, i, ship, why);
    const int n = (int)lua_tonumber(L, i);
    std::vector<uint32_t> ships;
    if (!OrdersFleet(0, ships, why)) return false;
    if (n < 1 || n > (int)ships.size()) { why = "ship number " + std::to_string(n) + " is not in the fleet (1.." + std::to_string(ships.size()) + ")"; return false; }
    ship = ships[n - 1]; return true;
}
void PushShip(lua_State* L, const ShipState& s) {
    lua_createtable(L, 0, 20);
    lua_pushstring(L, HexPtr(s.ship).c_str()); lua_setfield(L, -2, "ptr");
    SetNum(L, "id", s.fleetIndex + 1); SetNum(L, "fleet_index", s.fleetIndex); SetNum(L, "fleet_count", s.fleetCount);
    lua_pushstring(L, HexPtr(s.army).c_str()); lua_setfield(L, -2, "army");
    SetNum(L, "x", s.x); SetNum(L, "y", s.y); SetNum(L, "z", s.z); SetNum(L, "heading", s.heading); SetNum(L, "heading_raw", s.headingRaw);
    SetNum(L, "m02", s.m02); SetNum(L, "m22", s.m22); SetNum(L, "sail_level", s.sailLevel);
    lua_pushstring(L, SailName(s.sail)); lua_setfield(L, -2, "sail");
    lua_pushboolean(L, s.surrendered); lua_setfield(L, -2, "surrendered");
    lua_pushboolean(L, s.blocked); lua_setfield(L, -2, "blocked");
    if (s.blocked) { lua_pushstring(L, s.blockedWhy.c_str()); lua_setfield(L, -2, "blocked_why"); }
    if (s.hasWind) { SetNum(L, "wind_x", s.windX); SetNum(L, "wind_z", s.windZ); SetNum(L, "wind_angle", s.windAngle); }
}
int l_ship_state(lua_State* L) {
    uint32_t ship = 0; std::string why; ShipState s;
    if (!ShipRef(L, 1, ship, why) || !OrdersShip(ship, s, why)) return Fail(L, why.c_str());
    PushShip(L, s);
    return 1;
}
int l_ship_list(lua_State* L) {
    uint32_t ship = 0; std::string why; std::vector<uint32_t> ships;
    if (lua_gettop(L) >= 1 && !lua_isnil(L, 1) && !ShipRef(L, 1, ship, why)) return Fail(L, why.c_str());
    if (!OrdersFleet(ship, ships, why)) return Fail(L, why.c_str());
    lua_createtable(L, (int)ships.size(), 0);
    int i = 1;
    for (uint32_t p : ships) {
        ShipState s; std::string w;
        if (OrdersShip(p, s, w)) PushShip(L, s);
        else { lua_createtable(L, 0, 2); lua_pushstring(L, HexPtr(p).c_str()); lua_setfield(L, -2, "ptr"); lua_pushstring(L, w.c_str()); lua_setfield(L, -2, "why"); }
        lua_rawseti(L, -2, i++);
    }
    return 1;
}
int l_ship_selection(lua_State* L) {
    std::vector<uint32_t> ships; int groups = 0; std::string why;
    if (!OrdersShipSelection(ships, groups, why)) return Fail(L, why.c_str());
    lua_createtable(L, 0, 2);
    lua_createtable(L, (int)ships.size(), 0);
    int i = 1; for (uint32_t p : ships) { lua_pushstring(L, HexPtr(p).c_str()); lua_rawseti(L, -2, i++); }
    lua_setfield(L, -2, "ships");
    SetNum(L, "groups", groups);
    return 1;
}
int l_ship_move(lua_State* L) {
    uint32_t ship = 0; std::string why, info;
    if (!ShipRef(L, 1, ship, why)) return Fail(L, why.c_str());
    if (lua_type(L, 2) != LUA_TNUMBER || lua_type(L, 3) != LUA_TNUMBER) return Fail(L, "expected (ship, x, z, [heading], [sail], [queue])");
    ShipMoveArgs a; a.x = (float)lua_tonumber(L, 2); a.z = (float)lua_tonumber(L, 3);
    if (lua_type(L, 4) == LUA_TNUMBER) { a.hasHeading = true; a.heading = lua_tonumber(L, 4); }
    if (lua_type(L, 5) == LUA_TSTRING) { a.sail = SailFromName(lua_tostring(L, 5)); if (a.sail < 0) return Fail(L, "sail is stationary, battle, half or full"); }
    a.queue = lua_toboolean(L, 6) != 0;
    if (!OrdersShipMove(ship, a, info, why)) return Fail(L, why.c_str());
    lua_pushboolean(L, 1); lua_pushstring(L, info.c_str());
    return 2;
}
int l_ship_face(lua_State* L) {
    uint32_t ship = 0; std::string why, info;
    if (!ShipRef(L, 1, ship, why)) return Fail(L, why.c_str());
    if (lua_type(L, 2) != LUA_TNUMBER) return Fail(L, "expected (ship, heading, [flag], [queue])");
    if (!OrdersShipFace(ship, lua_tonumber(L, 2), lua_toboolean(L, 3) ? 1 : 0, lua_toboolean(L, 4) != 0, info, why)) return Fail(L, why.c_str());
    lua_pushboolean(L, 1); lua_pushstring(L, info.c_str());
    return 2;
}
int l_ship_halt(lua_State* L) {
    uint32_t ship = 0; std::string why, info;
    if (!ShipRef(L, 1, ship, why) || !OrdersShipHalt(ship, info, why)) return Fail(L, why.c_str());
    lua_pushboolean(L, 1); lua_pushstring(L, info.c_str());
    return 2;
}

const luaL_Reg s_funcs[] = {
    { "log", l_log }, { "version", l_version }, { "poll", l_poll }, { "result", l_result }, { "dev_config", l_dev_config },
    { "dev_state", l_dev_state }, { "report", l_report }, { "vanilla", l_vanilla }, { "cam_set", l_cam_set },
    { "unit_state", l_unit_state }, { "unit_list", l_unit_list }, { "selection", l_selection }, { "order_move", l_order_move }, { "order_command", l_order_command },
    { "peek", l_peek }, { "orders_info", l_orders_info },
    { "ship_state", l_ship_state }, { "ship_list", l_ship_list }, { "ship_selection", l_ship_selection }, { "ship_move", l_ship_move },
    { "ship_face", l_ship_face }, { "ship_halt", l_ship_halt }, { nullptr, nullptr }
};
} // namespace

void BridgeQueue(const LuaCmd& c) { Lock l; s_queue.push_back(c); }
bool BridgeTakeResult(const std::string& id, bool& ok, std::string& text) {
    Lock l;
    auto it = s_results.find(id);
    if (it == s_results.end()) return false;
    ok = it->second.first; text = it->second.second; s_results.erase(it);
    return true;
}
void BridgeDrop(const std::string& id) {
    Lock l;
    for (auto it = s_queue.begin(); it != s_queue.end(); ++it) if (it->id == id) { s_queue.erase(it); return; }   // never handed out
    s_dropped.insert(id);
}
bool BridgeLoaded() { return s_loaded != 0; }
double BridgeLastPumpS() { Lock l; return s_lastPump; }
std::string BridgeLastCtx() { Lock l; return s_lastCtx; }

} // namespace wsp

extern "C" __declspec(dllexport) int wsp_sentinel(lua_State* L) {
    if (!wsp::Allowed()) return 0;   // pass-through or the key off: the engine's table is never read
    if (lua_gettop(L) < 1 || lua_type(L, 1) != LUA_TTABLE) { LOGE("wsp_sentinel: expected an empty table"); return 0; }
    const Table* t = hvalue(L->top - 1);
    if (g_engine_dummynode && g_engine_dummynode != t->node) LOGW("wsp_sentinel: a second engine dummynode %p (had %p)", (const void*)t->node, (const void*)g_engine_dummynode);
    if (!g_engine_dummynode) LOGI("wsp_sentinel: engine dummynode = %p (sizearray %d, lsizenode %d)", (const void*)t->node, t->sizearray, t->lsizenode);
    g_engine_dummynode = t->node;
    return 0;
}

extern "C" __declspec(dllexport) int luaopen_wsp(lua_State* L) {
    if (!wsp::Allowed()) { LOGW("luaopen_wsp: refused (pass-through, or dev.lua_bridge off)"); return 0; }
    if (!g_engine_dummynode) { LOGE("luaopen_wsp: wsp_sentinel was not called first: refusing to register"); return 0; }
    const bool first = InterlockedExchange(&wsp::s_loaded, 1) == 0;
    LOGI("luaopen_wsp: engine lua_State %p, global state %p (thread %lu)%s", (void*)L, (void*)G(L), GetCurrentThreadId(), first ? "" : " (again)");
    if (first) wsp::TlMark("lua_bridge_loaded");
    lua_createtable(L, 0, 18);
    for (const luaL_Reg* f = wsp::s_funcs; f->name; ++f) { lua_pushcclosure(L, f->func, 0); lua_setfield(L, -2, f->name); }
    lua_pushvalue(L, -1);
    lua_setfield(L, LUA_GLOBALSINDEX, "wsp");
    return 1;
}
