// Lua 5.2 API (as lua-compat-5.2 defines it) that RmlUi 6.3's Lua bindings call but its own 5.1 shim (Include/RmlUi/Lua/Utilities.h) does not provide.
// Force-included into the rmlui_lua target by viewer/core/CMakeLists.txt, so the pinned RmlUi source stays unpatched.
#pragma once
#ifdef __cplusplus
extern "C" {
#endif
#include <lauxlib.h>
#include <lua.h>
#ifdef __cplusplus
}
#endif
#if LUA_VERSION_NUM < 502
static inline void luaL_setfuncs(lua_State* L, const luaL_Reg* l, int nup) {
	luaL_checkstack(L, nup + 1, "too many upvalues");
	for (; l->name; l++) {
		for (int i = 0; i < nup; i++)
			lua_pushvalue(L, -nup);
		lua_pushcclosure(L, l->func, nup);
		lua_setfield(L, -(nup + 2), l->name);
	}
	lua_pop(L, nup);
}
#define LUA_OK 0
static inline void* luaL_testudata(lua_State* L, int ud, const char* tname) {
	void* p = lua_touserdata(L, ud);
	if (p && lua_getmetatable(L, ud)) {
		luaL_getmetatable(L, tname);
		if (!lua_rawequal(L, -1, -2))
			p = 0;
		lua_pop(L, 2);
		return p;
	}
	return 0;
}
// Through the standard library's debug.traceback (the viewer's states open it); the message alone when it is missing.
static inline void luaL_traceback(lua_State* L, lua_State* L1, const char* msg, int level) {
	(void)L1;
	(void)level;
	lua_getfield(L, LUA_GLOBALSINDEX, "debug");
	if (lua_istable(L, -1)) {
		lua_getfield(L, -1, "traceback");
		lua_remove(L, -2);
		lua_pushstring(L, msg ? msg : "");
		if (lua_isfunction(L, -2) && lua_pcall(L, 1, 1, 0) == 0)
			return;
		lua_pop(L, 1);
	} else {
		lua_pop(L, 1);
	}
	lua_pushstring(L, msg ? msg : "");
}
static inline lua_Integer lua_tointegerx(lua_State* L, int i, int* isnum) {
	if (isnum)
		*isnum = lua_isnumber(L, i);
	return lua_tointeger(L, i);
}
#endif
