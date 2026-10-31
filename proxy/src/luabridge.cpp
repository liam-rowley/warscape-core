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

const luaL_Reg s_funcs[] = {
    { "log", l_log }, { "version", l_version }, { "poll", l_poll }, { "result", l_result }, { "dev_config", l_dev_config },
    { "dev_state", l_dev_state }, { "report", l_report }, { "vanilla", l_vanilla }, { "cam_set", l_cam_set }, { nullptr, nullptr }
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
    lua_createtable(L, 0, 12);
    for (const luaL_Reg* f = wsp::s_funcs; f->name; ++f) { lua_pushcclosure(L, f->func, 0); lua_setfield(L, -2, f->name); }
    lua_pushvalue(L, -1);
    lua_setfield(L, LUA_GLOBALSINDEX, "wsp");
    return 1;
}
