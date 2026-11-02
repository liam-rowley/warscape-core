// ui_lua.cpp - the RmlUi host's own Lua state (napoleon J30); the decision is in ui_lua.h. build.sh compiles this file apart from the
// other core sources, partially links it with the host's Lua copy and RmlUi's Lua plugin, and makes every _lua* symbol local.
// It must include nothing that declares the proxy's Lua (luabridge): the source lint in test_ui_core.cpp checks the other ui_ files
// never include a Lua header.
#include "ui_lua.h"
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
#include "ui_lua51_compat.h"
#include <RmlUi/Lua/Lua.h>
#include <cstdio>

// RmlUi's Lua plugin calls luaL_openlibs when it makes its own state; the host passes its state, but the symbol must link. Only the
// libraries a view needs: no io, os or package (a screen reads nothing from disk and loads no DLL).
extern "C" void luaL_openlibs(lua_State* L) {
    static const luaL_Reg libs[] = { { "", luaopen_base }, { LUA_TABLIBNAME, luaopen_table }, { LUA_STRLIBNAME, luaopen_string },
                                     { LUA_MATHLIBNAME, luaopen_math }, { LUA_DBLIBNAME, luaopen_debug }, { nullptr, nullptr } };
    for (const luaL_Reg* l = libs; l->func; ++l) { lua_pushcfunction(L, l->func); lua_pushstring(L, l->name); lua_call(L, 1, 0); }
}

namespace wsp {
namespace { lua_State* s_L = nullptr; }

bool UiLuaStart(std::string& why) {
    if (s_L) return true;
    s_L = luaL_newstate();
    if (!s_L) { why = "luaL_newstate failed"; return false; }
    luaL_openlibs(s_L);
    Rml::Lua::Initialise(s_L);
    return true;
}
void UiLuaStep() { if (s_L) lua_gc(s_L, LUA_GCSTEP, 0); }
void UiLuaStop() { if (s_L) { lua_close(s_L); s_L = nullptr; } }
bool UiLuaUp() { return s_L != nullptr; }
double UiLuaMemKb() { return s_L ? (double)lua_gc(s_L, LUA_GCCOUNT, 0) + lua_gc(s_L, LUA_GCCOUNTB, 0) / 1024.0 : 0.0; }

std::string UiLuaEval(const std::string& code) {
    if (!s_L) return "error: no Lua state";
    const int top = lua_gettop(s_L);
    std::string out;
    if (luaL_loadbuffer(s_L, code.data(), code.size(), "=ui_eval") != 0 || lua_pcall(s_L, 0, 1, 0) != 0) {
        const char* m = lua_tostring(s_L, -1);
        out = std::string("error: ") + (m ? m : "?");
    } else {
        lua_getglobal(s_L, "tostring"); lua_pushvalue(s_L, -2); lua_call(s_L, 1, 1);
        const char* s = lua_tostring(s_L, -1); out = s ? s : "";
    }
    lua_settop(s_L, top);
    return out;
}

} // namespace wsp
