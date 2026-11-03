#pragma once
// The game adapter contract: everything game-specific the core needs, supplied by proxy/<game>/adapter.cpp (identity pin, engine
// sites, config keys, names and folders). proxy/core never names a game, a path inside a game or an address (it moves to
// warscape-core at the end of phase 1).
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
#include "guard.h"
#include "patch_engine.h"
#include "config.h"
#include "console.h"
#include "camera.h"
#include "orders.h"
#include "ships.h"

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

// The gesture layer's game specifics (W6; contract in docs/PROXY_GESTURES.md). The callbacks run on the thread of the game's window
// procedure (a press, a move, the ctl verb's messages) and of Present (commit); a game whose window procedure and Present are not one
// thread makes its callbacks safe for that. Bearings are degrees in the core's convention (gesture_math.h: 0 = +z, clockwise from above).
enum class GestureScene : uint8_t { Eligible = 0, Ineligible = 1, Deployment = 2 };
struct GestureCam { double pos[3], target[3]; double fovYDeg; };      // the camera's eye and look-at target (world), vertical field of view
struct GestureUnitIn {                                                 // one selected unit, as its move order would take it
    uint32_t id; double x, y, z, bearing, width, depth;                // (x, z) the order point; depth 0 = unknown
    double minWidth, maxWidth;                                         // its frontage clamps (0 = none)
    bool frontRef;                                                     // (x, z) is the front edge's middle, not the block's centre
};
struct GestureOrderOut { uint32_t id; double x, z, bearing, width; };
struct GestureAdapter {
    GestureScene (*scene)(std::string& why);                                          // a battle that takes gestures, deployment, or neither
    bool (*cameraRead)(GestureCam& cam, std::string& why);                            // the pose the game draws with (e.g. CameraRead)
    bool (*groundAt)(double x, double z, double& y);                                  // the game's ground height (e.g. OrdersGroundAt)
    bool (*selection)(std::vector<GestureUnitIn>& units, std::string& why);           // the orderable selected units, the game's order
    bool (*placeable)(const GestureOrderOut& o, std::string& why);                    // would the game refuse it? nullptr = no extra test
    int (*commit)(const GestureOrderOut* orders, size_t n, std::string& why);         // once per release, from Present: orders sent
    int dragPx;              // a press becomes a drag beyond this many client pixels (the click threshold)
    double shortDragM;       // a move line shorter than this keeps the widths and moves the block's centre to the press point
    unsigned moveMods, rotateMods;   // the bindings: modifier sets (1 Alt, 2 Ctrl, 4 Shift) of a left drag that moves / rotates
    double pivotFwdM;        // the rotate pivot, metres ahead of the block's centre (0 = in place)
    double rotGain;          // degrees of turn per 1000 px of horizontal travel at a 3840-wide client (0 = 225)
    int rotSign;             // +1: mouse right turns clockwise from above
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
    const OrdersAdapter* orders;             // proxy/<game>/adapter.cpp (J28); nullptr = no battle unit orders
    const GestureAdapter* gesture;           // proxy/<game>/adapter.cpp (W6); nullptr = no gestures (the layer is inert)
    const ShipsAdapter* ships;               // proxy/<game>/adapter.cpp (J60); nullptr = no ship orders (land unaffected)
};

const GameAdapter& Adapter();   // defined by the game's adapter.cpp

} // namespace wsp
