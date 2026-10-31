#pragma once
// Internal interface between the dev-side drivers (dev.cpp, files.cpp, luabridge.cpp). Game-agnostic: the game's specifics come
// from Adapter().dev. Everything here is inert unless DevActive(): a dev key is on AND the guard's plan allows engine hooks.
#include "runtime.h"
#include "devcore.h"
#include "filerules.h"
#include "console.h"
#include "camera.h"

namespace wsp {

struct DevKeys {
    bool timeline = false, logFiles = false, skipIntro = false, stateJson = false, luaBridge = false, ctl = false, console = false, perf = false, camera = false;
    std::wstring fileRules, ctlDir;
    std::string autostart;
    int autostartDelayMs = 1500;
    bool Any() const { return timeline || logFiles || skipIntro || stateJson || luaBridge || ctl || console || perf || camera || !fileRules.empty() || !autostart.empty(); }
};
DevKeys& Dk();
bool DevActive();

// dev.cpp
void TlMark(const char* phase, const std::string& detail = std::string());
void TlMarkOnce(const char* phase, const std::string& detail = std::string());
void DevPump(const std::string& ctx);                 // the engine's Lua thread, every wrapped OnUpdate/OnUpdatePulse
void DevBattleState(int naval, int deployPanel);
void DevFrontendMovie(bool open);
void DevReport(const std::string& key, const std::string& value);   // wsp.report(): facts the Lua side sees (map, campaign, ...)
std::string DevConfigValue(const std::string& key);   // wsp.dev_config(): target.*, preset.*, lua_dir
void DevPresent();                                    // the render thread, every Present
std::string DevSceneNow();                            // the scene tracker's scene (takes the dev lock: never call it under another lock)

// console.cpp (J15): the campaign console behind dev.console; decisions in console.h
void ConsoleInit(bool key, const ConsoleAdapter* ad); // DevInit
void ConsoleInstall();                                // first Direct3DCreate9 (before any campaign): verify sites, claim the empty slot
bool ConsoleSet(bool on, std::string& why);           // ctl console on|off: claim or release the slot (never a foreign one)
ConsolePre ConsolePrecheck(const std::string& name);  // the verb's facts (scene filled in by the caller)
const ConsoleAdapter* ConsoleAd();
long ConsoleSeq();                                    // forwarder calls so far (a verb compares before/after)
bool ConsoleLastSince(long seq, FwdResult& res, std::string& name, std::string& why, int& hits);
std::string ConsoleStatusJson();                      // result members of ctl console status

// camera.cpp (J43): the battle camera setter behind dev.camera; decisions in camera.h
void CameraInit(bool key, const CameraAdapter* ad);   // DevInit
void CameraInstall();                                 // first Direct3DCreate9: verify the sites, read the chain's offsets
bool CameraSet(const CamPose& p, std::string& why);   // the engine thread (wsp.cam_set): the active mode's SetTargetAndPosition

// files.cpp
void FilesInit(std::vector<FileRule> rules);          // installs the exe's IAT hooks the rules and keys need
bool FilesVanillaEntry(const std::string& lowerPath, std::string& bytes, std::string& err);   // newest real pack holding it
int  FilesMoviesSkipped();
int  FilesMoviesOpened();
void FilesOnDirect3DCreate();                         // binkw32 is loaded by then
void FilesMapReset();                                 // forget the last map folder: only probes after this count (the load's)

// luabridge.cpp
struct LuaCmd { std::string id, verb, arg, ctx; };   // ctx: only a pump of this context takes it ("" = any)
void BridgeQueue(const LuaCmd& c);
bool BridgeTakeResult(const std::string& id, bool& ok, std::string& text);
void BridgeDrop(const std::string& id);               // a timed-out command: forget its result if it ever arrives
bool BridgeLoaded();                                  // luaopen ran on an engine state
double BridgeLastPumpS();                             // MonoS of the last pump (-1 none)
std::string BridgeLastCtx();

} // namespace wsp
