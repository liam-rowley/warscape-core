#pragma once
// The game adapter contract: everything game-specific the core needs, supplied by proxy/<game>/adapter.cpp (identity pin, engine
// sites, config keys, names and folders). proxy/core never names a game, a path inside a game or an address (it moves to
// warscape-core at the end of phase 1).
#include <cstddef>
#include "guard.h"
#include "patch_engine.h"
#include "config.h"
#include "console.h"
#include "camera.h"

namespace wsp {

// The dev side's game specifics (J3): null-terminated lists. Movie names are pack entry paths, lower case, '\\' separators.
struct DevAdapter {
    const char* const* introMovies;      // start-up movies refused at BinkOpen by dev.skip_intro
    const char* const* frontendMovies;   // the front end's background movies (scene "frontend" before any Lua pump)
    const char* const* luaRules;         // file rules installed with dev.lua_bridge (how the wrapper scripts reach the engine)
    const char* luaDir;                  // the bridge's Lua files, relative to the game folder ("<mod>\\lua\\")
    const char* mapProbe;                // folder whose sub-folder names the battle map while it loads ("data\\battleterrain\\presets\\")
    const char* packGlob;                // where the engine's packs are ("data\\*.pack"): movie names and vanilla script entries
};

struct GameAdapter {
    const char*    gameName;        // shown in the log and the notice
    const wchar_t* configFile;      // file name next to the exe
    const wchar_t* modDir;          // folder name next to the exe (logs, dumps, dxvk, the notice)
    const wchar_t* instanceMutex;   // named mutex: one live log per game
    Identity       identity;        // generated from proxy/<game>/identity.json
    const SiteDef* sites; size_t nSites;     // generated from the engine_sites registry
    const KeySpec* keys;  size_t nKeys;      // generated from the config_keys registry
    const DevAdapter* dev;                   // proxy/<game>/adapter.cpp
    const ConsoleAdapter* console;           // proxy/<game>/adapter.cpp (J15); nullptr = no campaign console
    const CameraAdapter* camera;             // proxy/<game>/adapter.cpp (J43); nullptr = no battle camera setter
};

const GameAdapter& Adapter();   // defined by the game's adapter.cpp

} // namespace wsp
