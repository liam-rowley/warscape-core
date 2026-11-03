#pragma once
// ui_lua.h - the RmlUi host's own Lua state (J30). No Lua type crosses this header: only ui_lua.cpp sees Lua.
//
// Decision (engine_facts <game>.ui.lua_state): the host does NOT run on the proxy's engine-patched Lua core (fetch_lua.py: the engine's
// dummynode as a runtime variable, no GC step), whose tables are only valid once the bridge's sentinel has read the engine's dummynode
// and whose collector never runs: a host state there would depend on a dev key (the bridge) and never collect. It links a second Lua
// 5.1.1, the review viewer's (fetch_ui.py: float lua_Number, nothing else patched), with every C symbol of that copy made local to one
// object by build.sh (ld -r + objcopy --localize-symbol '_lua*'), so the bridge's lua_* and the host's never meet and the engine's state
// is never touched. RmlUi's Lua plugin is linked into the same object, so a screen's view code runs as it does in the viewer.
#include <string>

namespace wsp {

bool UiLuaStart(std::string& why);          // after Rml::Initialise: own state, base/string/table/math/debug, Rml::Lua::Initialise(L)
void UiLuaStep();                           // one incremental collector step (every drawn frame)
void UiLuaStop();                           // after Rml::Shutdown
bool UiLuaUp();
std::string UiLuaEval(const std::string& code);   // runs a chunk, returns tostring(first result) or "error: ..." (tests, ctl state)
double UiLuaMemKb();

} // namespace wsp
