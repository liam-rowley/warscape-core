// dev.cpp - the dev side of the proxy (J3): phase timeline, scene tracking and state file, D3D frame hooks, the control channel,
// autostart and warm reset. Game-agnostic; the game's specifics come from Adapter().dev and the Lua files in its lua folder.
// Every key defaults off (config_keys rows, release value off). With no dev key on, DevInit returns before doing anything and the
// proxy behaves exactly as the skeleton; nothing here runs in pass-through (plan.engineHooks / plan.d3dHooks false).
//
// Threads: the engine thread (Lua pumps, Present: one thread, empire-remastered fact), the state thread (state.json ~2/s, scene
// updates, the config autostart), the control thread (one request at a time, FIFO by file time). Shared state is under s_cs.
// Control protocol (proxy/README.md "Dev control channel"): <ctl_dir>\<id>.cmd -> <ctl_dir>\<id>.done (JSON, written last).
#include "dev.h"
#ifndef PSAPI_VERSION
#define PSAPI_VERSION 2
#endif
#include <psapi.h>
#include <map>
#include <set>
#include <algorithm>

namespace wsp {

DevKeys& Dk() { static DevKeys k; return k; }

namespace {
CRITICAL_SECTION s_cs;
bool s_active = false, s_frames = false;
Timeline s_tl;
SceneTracker s_scene;
double s_t0 = 0;                       // MonoS at DllMain
double s_firstFrontendT = -1;
volatile LONG s_frameCount = 0;
int64_t s_lastPresentMs = -1;
std::string s_luaArgs;                 // the running ctl lua request's arguments (J4)
bool s_afterReady = false;             // the next Present closes a "scene ready"
std::map<std::string, std::string> s_reports;   // wsp.report()
Target s_target;                       // the autostart / reset target in progress (wsp.dev_config target.*)
std::vector<std::pair<std::string, std::string>> s_preset;   // its battle preset (preset.*)
std::string s_autostartStatus = "off"; // the config autostart: off | waiting | running | ok ... | failed ...
bool s_autostartFired = false;
bool s_resetting = false;              // a warm reset runs: the front end's root goes on to the main menu (wsp frontend.to_main)
HANDLE s_ctlWake = nullptr;

struct Lock { Lock() { EnterCriticalSection(&s_cs); } ~Lock() { LeaveCriticalSection(&s_cs); } };

void WriteTimeline() { WriteFileAtomic(Rt().modDir + L"logs\\timeline.json", s_tl.Json()); }

// ---- memory (address space used by the process and its commit) ---------------------------------------------------------------
struct Mem { double vaMb = 0, commitMb = 0; };
Mem MemNow() {
    Mem m; MEMORYSTATUSEX ms{}; ms.dwLength = sizeof ms;
    if (GlobalMemoryStatusEx(&ms)) m.vaMb = (double)(ms.ullTotalVirtual - ms.ullAvailVirtual) / 1048576.0;
    PROCESS_MEMORY_COUNTERS_EX pmc{}; pmc.cb = sizeof pmc;
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), (PROCESS_MEMORY_COUNTERS*)&pmc, sizeof pmc)) m.commitMb = (double)pmc.PrivateUsage / 1048576.0;
    return m;
}

// ---- perf capture (J4, dev.perf): the Present path records the time between presents while `perf <s>` runs ------------------------
// The delta is taken in integer ticks and only then made a double: D3D9 drops the engine thread's x87 FPU to 24-bit precision (no
// D3DCREATE_FPU_PRESERVE), and an absolute QPC time in ms near 1e8 then rounds to 8 ms steps (J44 run 20261030_j44pc: p50 0.0, max 16.0).
int64_t s_perfLastQpc = 0; bool s_perfOn = false; std::vector<double> s_perfDeltas;
void PerfFrame() {   // engine thread, once per Present: no allocation while the reserved capacity lasts
    static const int64_t freq = [] { LARGE_INTEGER x; QueryPerformanceFrequency(&x); return (int64_t)x.QuadPart; }();
    LARGE_INTEGER c; QueryPerformanceCounter(&c);
    const int64_t now = (int64_t)c.QuadPart;
    Lock l;
    if (!s_perfOn) { s_perfLastQpc = 0; return; }
    if (s_perfLastQpc > 0 && s_perfDeltas.size() < s_perfDeltas.capacity()) s_perfDeltas.push_back(PerfDeltaMs(now - s_perfLastQpc, freq));
    s_perfLastQpc = now;
}

// ---- scene ----------------------------------------------------------------------------------------------------------------
void UpdateSceneLocked(double now) {
    const double prevSince = s_scene.sceneSince;
    std::string from;
    if (!s_scene.Update(now, &from)) return;
    const std::string& to = s_scene.scene;
    LOGI("scene: %s -> %s after %.1f s (uptime %.1f s, frame %ld, lua %s)", from.c_str(), to.c_str(), now - prevSince, now - s_t0,
         (long)s_frameCount, s_scene.ctx.empty() ? "none" : s_scene.ctx.c_str());
    if (!Dk().timeline) return;
    const int64_t ms = UnixMs();
    if (to == "loading") s_tl.Add("loading_started", from, ms);
    else if (to != "intro") { s_tl.Add("scene_ready", to, ms); s_afterReady = true; }
    WriteTimeline();
}
std::string SceneNow() { Lock l; UpdateSceneLocked(MonoS()); return s_scene.scene; }
} // namespace
std::string DevSceneNow() { return s_active ? SceneNow() : std::string(); }
namespace {

// ---- state.json -------------------------------------------------------------------------------------------------------------
std::string StateJson() {   // s_cs held
    const double now = MonoS();
    const Mem m = MemNow();
    const double pumpAge = BridgeLastPumpS() >= 0 ? now - BridgeLastPumpS() : -1;
    char b[1200];
    snprintf(b, sizeof b,
        "{\"launch_id\": \"%s\", \"pid\": %lu, \"frame\": %ld, \"scene\": \"%s\", \"scene_s\": %.1f, \"uptime_s\": %.1f, \"written_utc\": \"%s\", "
        "\"last_present_utc\": \"%s\", \"lua\": {\"loaded\": %s, \"context\": \"%s\", \"pump_age_s\": %.1f}, \"battle\": {\"naval\": %d, \"deploy_panel\": %d, "
        "\"age_s\": %.1f}, \"load_target\": \"%s\", \"autostart\": \"%s\", \"movies_refused\": %d, \"movies_opened\": %d, \"mem\": {\"va_mb\": %.0f, \"commit_mb\": %.0f}",
        Rt().launchId.c_str(), GetCurrentProcessId(), (long)s_frameCount, s_scene.scene.c_str(), now - s_scene.sceneSince, now - s_t0, UtcIso(UnixMs()).c_str(),
        UtcIso(s_lastPresentMs).c_str(), BridgeLoaded() ? "true" : "false", JsonEsc(s_scene.ctx).c_str(), pumpAge, s_scene.naval, s_scene.deployPanel,
        s_scene.battleT >= 0 ? now - s_scene.battleT : -1.0, JsonEsc(s_scene.loadTarget).c_str(), JsonEsc(s_autostartStatus).c_str(),
        FilesMoviesSkipped(), FilesMoviesOpened(), m.vaMb, m.commitMb);
    std::string j = b;
    j += ", \"reports\": {";
    bool first = true;
    for (const auto& kv : s_reports) { j += (first ? "" : ", ") + JStr(kv.first) + ": " + JStr(kv.second); first = false; }
    j += "}}";
    return j;
}

// ---- D3D frame hooks ----------------------------------------------------------------------------------------------------------
using PFN_CreateDevice = HRESULT(WINAPI*)(void*, UINT, int, HWND, DWORD, void*, void**);
using PFN_Present = HRESULT(WINAPI*)(void*, const RECT*, const RECT*, HWND, const void*);
PFN_CreateDevice o_CreateDevice; PFN_Present o_Present;
HRESULT WINAPI hk_Present(void* dev, const RECT* a, const RECT* b, HWND w, const void* r) { DevPresent(); return o_Present(dev, a, b, w, r); }
HRESULT WINAPI hk_CreateDevice(void* d3d, UINT ad, int type, HWND w, DWORD flags, void* pp, void** out) {
    const HRESULT hr = o_CreateDevice(d3d, ad, type, w, flags, pp, out);
    char d[80]; snprintf(d, sizeof d, "hr 0x%08lx flags 0x%lx", (unsigned long)hr, flags);
    TlMarkOnce("device_created", d);
    if (SUCCEEDED(hr) && out && *out) VtableHook(*(void***)*out, 17, (void*)hk_Present, (void**)&o_Present, "IDirect3DDevice9::Present");
    return hr;
}

// ---- Lua commands (through the bridge) -----------------------------------------------------------------------------------------
volatile LONG s_internalId = 0;
std::string NewInternalId(const char* what) { char b[64]; snprintf(b, sizeof b, "_%s%ld", what, (long)InterlockedIncrement(&s_internalId)); return b; }

// Queue `lua <file>` for the next pump and wait for its result. false + why on timeout / no pump.
bool RunLua(const std::string& id, const std::string& file, double timeoutS, std::string& text, bool& timedOut, const std::string& ctx = std::string()) {
    timedOut = false;
    const double t0 = MonoS();
    BridgeQueue({ id, "lua", file, ctx });
    for (;;) {
        bool ok = false;
        if (BridgeTakeResult(id, ok, text)) return ok;
        if (MonoS() - t0 > timeoutS) {
            BridgeDrop(id);
            const double age = BridgeLastPumpS() >= 0 ? MonoS() - BridgeLastPumpS() : -1;
            char b[200]; snprintf(b, sizeof b, "no result after %.0f s (last Lua pump %.1f s ago, context %s)", timeoutS, age, BridgeLastCtx().c_str());
            text = b; timedOut = true; return false;
        }
        Sleep(10);
    }
}

std::string LuaDir() { const DevAdapter* ad = Adapter().dev; std::string d = ad && ad->luaDir ? ad->luaDir : ""; for (char& c : d) if (c == '\\') c = '/'; return d; }

bool LoadPreset(const std::string& name, std::string& err) {   // <lua dir>\battles\<name>.txt, key=value lines
    s_preset.clear();
    std::string text;
    const std::wstring p = Rt().gameDir + WidenAcp(Adapter().dev->luaDir) + L"battles\\" + WidenUtf8(name) + L".txt";
    if (!ReadFileBytes(p, text)) { err = "battle preset " + Narrow(p) + " not found"; return false; }
    size_t pos = 0;
    while (pos < text.size()) {
        size_t e = text.find('\n', pos); if (e == std::string::npos) e = text.size();
        const std::string s = TrimS(text.substr(pos, e - pos)); pos = e + 1;
        if (s.empty() || s[0] == '#') continue;
        const size_t eq = s.find('='); if (eq == std::string::npos) continue;
        s_preset.push_back({ TrimS(s.substr(0, eq)), TrimS(s.substr(eq + 1)) });
    }
    return true;
}
std::string PresetValue(const std::string& k) { for (auto& kv : s_preset) if (kv.first == k) return kv.second; return ""; }

struct Outcome { std::string status = "ok", reason, result; };   // result = JSON object members (", "-joined)

bool WaitScene(const std::vector<std::string>& want, double timeoutS, std::string& got, double& waited) {
    const double t0 = MonoS();
    for (;;) {
        got = SceneNow();
        waited = MonoS() - t0;
        if (std::find(want.begin(), want.end(), got) != want.end()) return true;
        if (waited > timeoutS) return false;
        Sleep(50);
    }
}

std::string MemJson(const Mem& m) { char b[96]; snprintf(b, sizeof b, "{\"va_mb\": %.0f, \"commit_mb\": %.0f}", m.vaMb, m.commitMb); return b; }

Outcome Autostart(const Target& t, double timeoutS) {
    Outcome o; char b[400];
    const double t0 = MonoS();
    std::string sc; double waited = 0;
    if (!WaitScene({ "frontend" }, timeoutS, sc, waited)) { o.status = "timeout"; o.reason = "the front end was not reached (scene " + sc + ")"; return o; }
    if (t.kind == "frontend") { o.result = "\"scene\": \"frontend\""; return o; }
    // a front-end pump must be live: the autostart Lua runs in the pumping script's environment
    while (BridgeLastPumpS() < 0 || MonoS() - BridgeLastPumpS() > 1.0 || BridgeLastCtx() != "frontend") {
        if (MonoS() - t0 > timeoutS) { o.status = "failed"; o.reason = "no front-end Lua pump (is dev.lua_bridge on and the wrapper loaded?)"; return o; }
        Sleep(50);
    }
    {
        Lock l;
        s_target = t;
        if (t.kind == "battle") { std::string err; if (!LoadPreset(t.preset, err)) { o.status = "failed"; o.reason = err; return o; } }
        s_reports.erase("battle.map_folder"); s_reports.erase("battle.map_folder_ms"); s_reports.erase("autostart.map"); s_reports.erase("autostart.map_folder");
    }
    TlMark("autostart_issued", t.kind + ":" + (t.kind == "battle" ? t.preset : t.mode == "new" ? t.campaign + ":" + t.faction : t.mode == "save" ? t.save : t.mode));
    std::string text; bool to = false;
    const bool ok = RunLua(NewInternalId("autostart"), LuaDir() + "autostart.lua", 30, text, to);
    LOGI("autostart: lua %s: %s", ok ? "ok" : "FAILED", text.c_str());
    if (!ok) { o.status = to ? "timeout" : "failed"; o.reason = "autostart.lua: " + text; return o; }
    // The map check must see the LOAD's probe of the map folder, not the front end's map-list walk (which ends on the selected
    // map's folder and would hide the load's probe of the same folder): forget everything probed so far.
    FilesMapReset();
    { Lock l; s_reports.erase("battle.map_folder"); s_reports.erase("battle.map_folder_ms"); s_scene.OnLoadRequested(t.kind); }
    const std::vector<std::string> want = t.kind == "campaign" ? std::vector<std::string>{ "campaign" } : std::vector<std::string>{ "battle_deploy", "battle", "naval" };
    const double left = timeoutS - (MonoS() - t0);
    if (!WaitScene(want, left > 5 ? left : 5, sc, waited)) {
        { Lock l; s_scene.loadTarget.clear(); }
        o.status = "timeout"; o.reason = "scene " + sc + " after the load request (" + text + ")"; return o;
    }
    if (t.kind == "battle") { Sleep(1000); sc = SceneNow(); }   // the battle probe needs a pump or two to see the deployment panel
    snprintf(b, sizeof b, "\"scene\": \"%s\", \"lua\": %s, \"load_s\": %.1f, \"total_s\": %.1f", sc.c_str(), JStr(text).c_str(), waited, MonoS() - t0);
    o.result = b;
    if (t.kind == "battle") {   // the map check: the folder the engine loaded (its own file probes) against the preset's map
        auto rep = [](const char* k) { Lock l; auto it = s_reports.find(k); return it == s_reports.end() ? std::string() : it->second; };
        const std::string loaded = rep("battle.map_folder"), wantFolder = rep("autostart.map_folder"), selected = rep("autostart.map");
        const std::string loadedMs = rep("battle.map_folder_ms"), want_map = PresetValue("map");
        o.result += ", \"map\": " + JStr(selected) + ", \"map_folder_loaded\": " + JStr(loaded) + ", \"map_folder_loaded_after_request_ms\": " +
                    (!loadedMs.empty() && loadedMs.find_first_not_of("0123456789") == std::string::npos ? loadedMs : std::string("null")) + ", \"map_folder_selected\": " + JStr(wantFolder) + ", \"preset_map\": " + JStr(want_map);
        std::string a = loaded, c = wantFolder;
        for (auto& ch : a) ch = (char)tolower((unsigned char)ch);
        for (auto& ch : c) ch = (char)tolower((unsigned char)ch);
        std::string sk = selected, pk = want_map;
        for (auto& ch : sk) ch = (char)tolower((unsigned char)ch);
        for (auto& ch : pk) ch = (char)tolower((unsigned char)ch);
        if (loaded.empty()) { o.status = "failed"; o.reason = "the engine opened no map preset folder while loading: the map is not checked"; }
        else if (sk != pk) { o.status = "failed"; o.reason = "WRONG MAP: the front end selected '" + selected + "', the preset wants '" + want_map + "'"; }
        else if (a != c) { o.status = "failed"; o.reason = "WRONG MAP: the engine loaded '" + loaded + "', the selected map's folder is '" + wantFolder + "'"; }
    }
    return o;
}

Outcome Reset(const Target& t, double timeoutS) {
    struct ClearFlag { ~ClearFlag() { Lock l; s_resetting = false; } } clearOnReturn;
    Outcome o; char b[600];
    const double t0 = MonoS();
    // A battle left 1.2 s after it appeared crashed the game in mss32.dll (first-chance AV, dump 20261029T091233Z-p14812, run
    // 20261029_j3pc): let a battle settle for kBattleSettleS before quitting it.
    const double kBattleSettleS = 8.0;
    for (;;) {
        double since; std::string sc;
        { Lock l; UpdateSceneLocked(MonoS()); sc = s_scene.scene; since = MonoS() - s_scene.sceneSince; }
        const bool battle = sc == "battle" || sc == "battle_deploy" || sc == "naval";
        if (!battle || since >= kBattleSettleS || MonoS() - t0 > timeoutS) break;
        Sleep(100);
    }
    const Mem before = MemNow();
    const std::string from = SceneNow();
    if (from != "frontend") {
        if (from != "campaign" && from != "battle" && from != "battle_deploy" && from != "naval") { o.status = "failed"; o.reason = "reset from scene " + from + " (needs campaign, battle or the front end)"; return o; }
        // reset.lua does one step per call (battle: ExitBattle, then the summary, then the post-battle screen; "wait" while the next
        // popup is not up yet); repeat every 0.5 s while the context we leave still pumps, at most 120 calls (60 s)
        const std::string src = BridgeLastCtx();
        { Lock l; s_scene.OnLoadRequested("frontend"); s_resetting = true; }
        int steps = 0; std::string last;
        for (int calls = 0; calls < 120; ++calls) {
            if (BridgeLastCtx() != src || MonoS() - BridgeLastPumpS() > 2.0) break;   // it stopped: the engine is leaving
            std::string text; bool to = false;
            // only the context we leave may take the step (a front-end pump must never run it: run 20261029_j3pc)
            if (!RunLua(NewInternalId("reset"), LuaDir() + "reset.lua", 5, text, to, src)) {
                if (to && (BridgeLastCtx() != src || MonoS() - BridgeLastPumpS() > 2.0)) break;   // it stopped pumping meanwhile: leaving
                { Lock l; s_scene.loadTarget.clear(); } o.status = to ? "timeout" : "failed"; o.reason = "reset.lua after step " + std::to_string(steps) + ": " + text; return o;
            }
            if (text != "wait") { ++steps; LOGI("reset: step %d: %s", steps, text.c_str()); last += (last.empty() ? "" : "; ") + text; }
            const double tw = MonoS();
            while (MonoS() - tw < 0.5 && BridgeLastCtx() == src && MonoS() - BridgeLastPumpS() < 2.0) Sleep(50);
        }
        o.result = "\"steps\": " + JStr(last);   // the timeout returns below must still give valid JSON
        std::string sc; double waited = 0;
        if (!WaitScene({ "frontend" }, timeoutS, sc, waited)) { { Lock l; s_scene.loadTarget.clear(); } o.status = "timeout"; o.reason = "scene " + sc + " after the reset request"; return o; }
        // the front end must pump again before the next autostart
        const double tw = MonoS();
        while ((BridgeLastCtx() != "frontend" || MonoS() - BridgeLastPumpS() > 1.0) && MonoS() - tw < 30) Sleep(50);
        { Lock l; s_resetting = false; }
    }
    const double toFrontend = MonoS() - t0;
    const Mem mid = MemNow();
    Outcome a;
    if (t.kind != "frontend") {
        const double left = timeoutS - toFrontend;
        a = Autostart(t, left > 30 ? left : 30);
        if (a.status != "ok") { o.status = a.status; o.reason = "after the reset: " + a.reason; }
    }
    const Mem after = MemNow();
    snprintf(b, sizeof b, "\"from\": \"%s\", \"to_frontend_s\": %.1f, \"total_s\": %.1f, \"mem_before\": %s, \"mem_frontend\": %s, \"mem_after\": %s",
             from.c_str(), toFrontend, MonoS() - t0, MemJson(before).c_str(), MemJson(mid).c_str(), MemJson(after).c_str());
    o.result += (o.result.empty() ? "" : ", ") + std::string(b);
    if (!a.result.empty()) o.result += ", \"autostart\": {" + a.result + "}";
    LOGI("reset: %s -> %s: %s (address space %.0f -> %.0f MB, commit %.0f -> %.0f MB)", from.c_str(), t.kind.c_str(), o.status.c_str(), before.vaMb, after.vaMb, before.commitMb, after.commitMb);
    return o;
}

// ---- control channel ----------------------------------------------------------------------------------------------------------
std::set<std::string> s_ids;

// console <line>|status|on|off (J15): a line runs through the engine's own Lua CliExecute (executor: system dictionary, tweaks,
// script file, then our slot), so it takes exactly the path game Lua takes; the forwarder's record says whether the slot saw it.
Outcome Console(const std::string& id, const CtlRequest& r, double timeout) {
    Outcome o; char b[300];
    const ConsoleAdapter* ad = ConsoleAd();
    if (r.arg == "status") { o.result = ConsoleStatusJson(); if (!Dk().console) { o.status = "refused"; o.reason = "dev.console=0"; } return o; }
    if (r.arg == "on" || r.arg == "off") {
        std::string why;
        if (!ConsoleSet(r.arg == "on", why)) { o.status = "refused"; o.reason = why; }
        o.result = ConsoleStatusJson(); return o;
    }
    const ConsoleLine l = ParseConsoleLine(r.arg);
    ConsolePre p = ConsolePrecheck(l.error.empty() ? l.name : std::string());
    p.scene = SceneNow();
    const std::string ref = ConsoleRefusal(p, l, ad ? ad->noOps : nullptr);
    const std::string common = "\"command\": " + JStr(l.name) + ", \"args\": " + JStr(l.args);
    if (!ref.empty()) {
        LOGW("console: verb refused '%s': %s", r.arg.c_str(), ref.c_str());
        o.status = "refused"; o.reason = ref; o.result = "\"path\": \"refused\", " + common + ", \"forwarded\": false, \"hits\": 0"; return o;
    }
    // the chunk: one generated file per request under <mod>\lua\_console\ (the bridge loads files by path)
    const std::string rel = LuaDir() + "_console/" + id + ".lua";
    CreateDirectoryW((Rt().gameDir + WidenUtf8(LuaDir()) + L"_console").c_str(), nullptr);
    if (!WriteFileAtomic(Rt().gameDir + WidenUtf8(rel), "return CliExecute(" + LuaQuote(l.line) + ")\n")) { o.status = "failed"; o.reason = "could not write " + rel; return o; }
    const long seq = ConsoleSeq();
    LOGI("console: run '%s' (request %s)", l.line.c_str(), id.c_str());
    std::string text; bool to = false;
    const bool ok = RunLua(id, rel, timeout, text, to);
    FwdResult fr = FwdResult::None; std::string fname, fwhy; int hits = 0;
    const bool any = ConsoleLastSince(seq, fr, fname, fwhy, hits);
    const bool seen = RecordIsForLine(any, fname, l.name);
    if (any && !seen) { fr = FwdResult::None; hits = 0; fwhy = "no record for this line (the latest is for '" + fname + "')"; }
    const char* path = ConsolePath(ad && ConsoleInList(ad->systemNames, l.name), fr);
    snprintf(b, sizeof b, "\"path\": \"%s\", %s, \"forwarded\": %s, \"hits\": %d, \"chunk\": ", path, common.c_str(),
             seen && fr != FwdResult::Refused ? "true" : "false", hits);
    o.result = b + JStr(text);
    LOGI("console: '%s' -> path %s%s%s", l.line.c_str(), path, fwhy.empty() ? "" : ": ", fwhy.c_str());
    if (!ok) { o.status = to ? "timeout" : "failed"; o.reason = text; }
    else if (fr == FwdResult::Refused) { o.status = "refused"; o.reason = "forwarder: " + fwhy; }
    else if (fr == FwdResult::Unknown) { o.status = "failed"; o.reason = "'" + l.name + "' is unknown to the campaign dictionary"; }
    return o;
}

Outcome Execute(const std::string& id, const CtlRequest& r) {
    Outcome o; char b[300];
    const double timeout = r.timeoutS > 0 ? r.timeoutS : CtlDefaultTimeout(r.verb);
    if (r.verb == "ping") { o.result = "\"pong\": true"; return o; }
    if (r.verb == "state") { Lock l; UpdateSceneLocked(MonoS()); o.result = "\"state\": " + StateJson(); return o; }
    if (r.verb == "log") { LOGI("ctl: log: %s", r.arg.c_str()); return o; }
    if (r.verb == "lua") {
        std::string text; bool to = false;
        { Lock l; s_luaArgs = r.luaArgs; }
        const bool ok = RunLua(id, r.arg, timeout, text, to);
        o.result = "\"chunk\": " + JStr(text);
        if (!ok) { o.status = to ? "timeout" : "failed"; o.reason = text; }
        return o;
    }
    if (r.verb == "waitfor") {
        std::string sc; double waited = 0;
        const bool ok = WaitScene(r.scenes, timeout, sc, waited);
        snprintf(b, sizeof b, "\"scene\": \"%s\", \"waited_s\": %.1f", sc.c_str(), waited);
        o.result = b;
        if (!ok) { o.status = "timeout"; o.reason = "scene is " + sc + " after " + std::to_string((int)timeout) + " s"; }
        return o;
    }
    if (r.verb == "perf") {
        if (!Dk().perf) { o.status = "refused"; o.reason = "dev.perf is off"; return o; }
        const int secs = atoi(r.arg.c_str());
        { Lock l; s_perfDeltas.clear(); s_perfDeltas.reserve((size_t)secs * 4000 + 1000); s_perfLastQpc = 0; s_perfOn = true; }
        Sleep((DWORD)secs * 1000);
        std::vector<double> d; { Lock l; s_perfOn = false; d = s_perfDeltas; }
        const FrameStats fs = ComputeFrameStats(d);
        const Mem m = MemNow();
        MEMORYSTATUSEX ms{}; ms.dwLength = sizeof ms; double totalVaMb = 0, freeVaMb = 0;
        if (GlobalMemoryStatusEx(&ms)) { totalVaMb = (double)ms.ullTotalVirtual / 1048576.0; freeVaMb = (double)ms.ullAvailVirtual / 1048576.0; }
        PROCESS_MEMORY_COUNTERS_EX pmc{}; pmc.cb = sizeof pmc; double wsMb = 0, peakWsMb = 0;
        if (K32GetProcessMemoryInfo(GetCurrentProcess(), (PROCESS_MEMORY_COUNTERS*)&pmc, sizeof pmc)) { wsMb = (double)pmc.WorkingSetSize / 1048576.0; peakWsMb = (double)pmc.PeakWorkingSetSize / 1048576.0; }
        snprintf(b, sizeof b, "\"seconds\": %d, \"frames\": %zu, \"frame_ms\": {\"p50\": %.3f, \"p99\": %.3f, \"max\": %.3f, \"mean\": %.3f}, "
                 "\"mem\": {\"va_used_mb\": %.0f, \"va_total_mb\": %.0f, \"va_free_mb\": %.0f, \"commit_mb\": %.0f, \"working_set_mb\": %.0f, \"peak_working_set_mb\": %.0f}",
                 secs, fs.frames, fs.p50, fs.p99, fs.max, fs.mean, m.vaMb, totalVaMb, freeVaMb, m.commitMb, wsMb, peakWsMb);
        o.result = b;
        if (fs.frames == 0) { o.status = "failed"; o.reason = "no frames presented during the capture"; }
        return o;
    }
    if (r.verb == "autostart") return Autostart(r.target, timeout);
    if (r.verb == "reset") return Reset(r.target, timeout);
    if (r.verb == "console") return Console(id, r, timeout);
    if (r.verb == "exit") return o;   // the caller exits after writing the result
    o.status = "failed"; o.reason = "unknown verb"; return o;
}

std::string ResultJson(const std::string& id, const std::string& line, const Outcome& o, int64_t startMs, int64_t endMs, const std::vector<std::string>& log) {
    std::string j = "{\"id\": " + JStr(id) + ", \"request\": " + JStr(line) + ", \"status\": " + JStr(o.status) + ", \"reason\": " + JStr(o.reason) +
                    ", \"start_utc\": " + JStr(UtcIso(startMs)) + ", \"end_utc\": " + JStr(UtcIso(endMs)) + ", \"launch_id\": " + JStr(Rt().launchId);
    if (!o.result.empty()) j += ", " + o.result;
    { Lock l; UpdateSceneLocked(MonoS()); j += ", \"state_at_end\": " + StateJson(); }
    j += ", \"log\": [";
    for (size_t i = 0; i < log.size(); ++i) j += (i ? ", " : "") + JStr(log[i]);
    j += "]}\n";
    return j;
}

void HandleRequest(const std::wstring& dir, const std::wstring& file) {
    const std::wstring stem = file.substr(0, file.size() - 4);   // without ".cmd"
    const std::string id = Narrow(stem);
    const std::wstring cmd = dir + file, taken = dir + stem + L".cmd.taken", done = dir + stem + L".done";
    if (!MoveFileExW(cmd.c_str(), taken.c_str(), 0)) return;   // being written still, or gone: next pass
    std::string text; ReadFileBytes(taken, text);
    const int64_t start = UnixMs();
    Outcome o;
    CtlRequest r;
    bool exitAfter = false;
    if (!ValidCtlId(id)) { o.status = "refused"; o.reason = "bad id (1-64 of A-Za-z0-9._-, not starting with . or _)"; }
    else if (s_ids.count(id) || GetFileAttributesW(done.c_str()) != INVALID_FILE_ATTRIBUTES) { o.status = "refused"; o.reason = "id already used (ids are never reused)"; }
    else {
        s_ids.insert(id);
        std::string idl = id + "\r\n"; HANDLE f = CreateFileW((dir + L"_ids.txt").c_str(), FILE_APPEND_DATA, FILE_SHARE_READ, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (f != INVALID_HANDLE_VALUE) { DWORD wr; WriteFile(f, idl.data(), (DWORD)idl.size(), &wr, nullptr); CloseHandle(f); }
        r = ParseCtl(text);
        if (!r.error.empty()) { o.status = "failed"; o.reason = r.error; }
        else {
            LOGI("ctl: %s: %s", id.c_str(), TrimS(text).c_str());
            LogCaptureBegin();
            o = Execute(id, r);
            std::vector<std::string> log = LogCaptureEnd();
            exitAfter = r.verb == "exit";
            LOGI("ctl: %s: %s%s%s", id.c_str(), o.status.c_str(), o.reason.empty() ? "" : ": ", o.reason.c_str());
            WriteFileAtomic(done, ResultJson(id, TrimS(text), o, start, UnixMs(), log));
            if (exitAfter) { TlMark("exit_requested", id); LOGI("ctl: exit requested by %s", id.c_str()); ExitProcess(0); }
            return;
        }
    }
    LOGW("ctl: %s: %s: %s", id.c_str(), o.status.c_str(), o.reason.c_str());
    WriteFileAtomic(done, ResultJson(id, TrimS(text), o, start, UnixMs(), {}));
}

DWORD WINAPI CtlThread(LPVOID) {
    const std::wstring dir = Dk().ctlDir.back() == L'\\' ? Dk().ctlDir : Dk().ctlDir + L"\\";
    CreateDirectoryW(dir.c_str(), nullptr);
    { std::string ids; if (ReadFileBytes(dir + L"_ids.txt", ids)) { size_t p = 0; while (p < ids.size()) { size_t e = ids.find('\n', p); if (e == std::string::npos) e = ids.size(); std::string s = TrimS(ids.substr(p, e - p)); if (!s.empty()) s_ids.insert(s); p = e + 1; } } }
    LOGI("ctl: watching %ls (%zu ids already used)", dir.c_str(), s_ids.size());
    for (;;) {
        WaitForSingleObject(s_ctlWake, 100);
        // the config autostart runs here too (one thing at a time)
        bool fire = false;
        { Lock l; if (!Dk().autostart.empty() && !s_autostartFired && s_firstFrontendT >= 0 && MonoS() - s_firstFrontendT >= Dk().autostartDelayMs / 1000.0) { s_autostartFired = true; fire = true; s_autostartStatus = "running"; } }
        if (fire) {
            const Target t = ParseTarget(Dk().autostart);
            Outcome o;
            if (!t.error.empty()) { o.status = "failed"; o.reason = t.error; } else o = Autostart(t, 300);
            Lock l; s_autostartStatus = o.status + (o.reason.empty() ? "" : ": " + o.reason);
            LOGI("autostart (dev.autostart=%s): %s", Dk().autostart.c_str(), s_autostartStatus.c_str());
            TlMark("autostart_result", s_autostartStatus);
        }
        if (!Dk().ctl) continue;
        WIN32_FIND_DATAW fd; HANDLE h = FindFirstFileW((dir + L"*.cmd").c_str(), &fd);
        if (h == INVALID_HANDLE_VALUE) continue;
        std::vector<std::pair<uint64_t, std::wstring>> files;
        do {
            const std::wstring n = fd.cFileName;
            if (n.size() > 4 && !(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) files.push_back({ ((uint64_t)fd.ftLastWriteTime.dwHighDateTime << 32) | fd.ftLastWriteTime.dwLowDateTime, n });
        } while (FindNextFileW(h, &fd));
        FindClose(h);
        std::sort(files.begin(), files.end());
        for (auto& f : files) HandleRequest(dir, f.second);
    }
}

DWORD WINAPI StateThread(LPVOID) {
    const std::wstring path = Rt().modDir + L"state.json";
    for (;;) {
        Sleep(500);
        std::string j;
        { Lock l; UpdateSceneLocked(MonoS()); if (Dk().stateJson) j = StateJson() + "\n"; }
        if (!j.empty()) WriteFileAtomic(path, j);
    }
}

} // namespace

bool DevActive() { return s_active; }

void TlMark(const char* phase, const std::string& detail) {
    if (!s_active || !Dk().timeline) return;
    Lock l;
    const int64_t ms = UnixMs();
    if (!s_tl.Add(phase, detail, ms)) return;
    LOGI("timeline: %s +%lld ms%s%s", phase, (long long)(ms - s_tl.processStartMs), detail.empty() ? "" : " ", detail.c_str());
    WriteTimeline();
}
void TlMarkOnce(const char* phase, const std::string& detail) {
    if (!s_active || !Dk().timeline) return;
    { Lock l; if (s_tl.Has(phase)) return; }
    TlMark(phase, detail);
}

void DevPump(const std::string& ctx) {
    if (!s_active) return;
    const double now = MonoS();
    bool first = false;
    {
        Lock l;
        if (ctx == "frontend" && s_firstFrontendT < 0) { s_firstFrontendT = now; first = true; }
        s_scene.OnPump(ctx, now);
        UpdateSceneLocked(now);
    }
    if (first) { TlMark("frontend_first_pump"); if (s_ctlWake) SetEvent(s_ctlWake); }
}
void DevBattleState(int naval, int deployPanel) {
    if (!s_active) return;
    Lock l;
    if (naval != s_scene.naval || deployPanel != s_scene.deployPanel) LOGI("scene: battle probe naval=%d deploy_panel=%d", naval, deployPanel);
    s_scene.OnBattleState(naval, deployPanel, MonoS());
    UpdateSceneLocked(MonoS());
}
void DevFrontendMovie(bool open) {
    if (!s_active) return;
    Lock l; s_scene.OnFrontendMovie(open, MonoS()); UpdateSceneLocked(MonoS());
}
void DevReport(const std::string& key, const std::string& value) {
    if (!s_active) return;
    Lock l;
    auto it = s_reports.find(key);
    if (it != s_reports.end() && it->second == value) return;
    if (s_reports.size() >= 64 && it == s_reports.end()) return;
    s_reports[key] = value;
    LOGI("lua report: %s = %s", key.c_str(), value.c_str());
}
std::string DevConfigValue(const std::string& key) {
    Lock l;
    if (key == "lua_dir") return LuaDir();
    if (key == "lua_args") return s_luaArgs;
    if (key == "ctx") return s_scene.ctx;
    if (key == "scene") return s_scene.scene;
    if (key == "frontend.to_main") return s_resetting ? "1" : "";
    if (key == "target.kind") return s_target.kind;
    if (key == "target.mode") return s_target.mode;
    if (key == "target.campaign") return s_target.campaign;
    if (key == "target.faction") return s_target.faction;
    if (key == "target.save") return s_target.save;
    if (key == "target.preset") return s_target.preset;
    if (key.rfind("preset.", 0) == 0) return PresetValue(key.substr(7));
    return "";
}
void DevPresent() {
    InterlockedIncrement(&s_frameCount);
    const int64_t ms = UnixMs();
    if (Dk().perf) PerfFrame();
    bool first = false, ready = false;
    { Lock l; first = s_lastPresentMs < 0; s_lastPresentMs = ms; ready = s_afterReady; s_afterReady = false; }
    if (first) TlMark("first_present");
    if (ready) { std::string sc; { Lock l; sc = s_scene.scene; } TlMark("first_present_after_ready", sc); }
}

void DevInit() {
    Runtime& rt = Rt();
    DevKeys& k = Dk();
    k.timeline = rt.cfg.Bool("dev.timeline");
    k.logFiles = rt.cfg.Bool("dev.log_files");
    k.skipIntro = rt.cfg.Bool("dev.skip_intro");
    k.stateJson = rt.cfg.Bool("dev.state_json");
    k.luaBridge = rt.cfg.Bool("dev.lua_bridge");
    k.ctl = rt.cfg.Bool("dev.ctl");
    k.console = rt.cfg.Bool("dev.console");
    k.perf = rt.cfg.Bool("dev.perf");
    k.camera = rt.cfg.Bool("dev.camera");
    k.fileRules = WidenUtf8(rt.cfg.Str("dev.file_rules"));
    k.ctlDir = WidenUtf8(rt.cfg.Str("dev.ctl_dir"));
    k.autostart = rt.cfg.Str("dev.autostart");
    k.autostartDelayMs = (int)rt.cfg.Int("dev.autostart_delay_ms");
    if (!k.Any()) return;   // the skeleton's behaviour, exactly
    if (!rt.plan.engineHooks || !rt.plan.d3dHooks) { LOGW("dev: dev keys are set but the plan forbids hooks (pass-through): dev side off"); return; }
    const DevAdapter* ad = Adapter().dev;
    if (!ad) { LOGW("dev: the adapter has no dev specifics: dev side off"); return; }
    InitializeCriticalSection(&s_cs);
    s_active = true;
    s_t0 = MonoS();
    // the timeline starts at process creation (from the OS) and the proxy's DllMain
    FILETIME c, e, kt, u;
    s_tl.launchId = rt.launchId;
    if (GetProcessTimes(GetCurrentProcess(), &c, &e, &kt, &u)) s_tl.processStartMs = FileTimeToUnixMs(c);
    LOGI("dev: timeline=%d log_files=%d skip_intro=%d state_json=%d lua_bridge=%d ctl=%d file_rules='%ls' ctl_dir='%ls' autostart='%s' delay=%d ms",
         k.timeline, k.logFiles, k.skipIntro, k.stateJson, k.luaBridge, k.ctl, k.fileRules.c_str(), k.ctlDir.c_str(), k.autostart.c_str(), k.autostartDelayMs);
    if (k.timeline) { s_tl.Add("process_start", "", s_tl.processStartMs); TlMark("dllmain"); }
    ConsoleInit(k.console, Adapter().console);
    CameraInit(k.camera, Adapter().camera);

    std::vector<FileRule> rules;
    if (k.skipIntro) for (const char* const* m = ad->introMovies; m && *m; ++m) rules.push_back(MakeRule(RuleSpace::Movie, RuleAct::Fail, *m, "", "dev.skip_intro"));
    if (k.luaBridge) {
        std::string text; for (const char* const* r = ad->luaRules; r && *r; ++r) { text += *r; text += '\n'; }
        std::vector<std::string> w; for (auto& r : ParseRules(text, w)) { r.origin = "dev.lua_bridge"; rules.push_back(r); }
        for (auto& x : w) LOGE("dev: adapter lua rule: %s", x.c_str());
    }
    if (!k.fileRules.empty()) {
        const std::wstring p = IsAbsolute(k.fileRules) ? k.fileRules : rt.gameDir + k.fileRules;
        std::string text;
        if (!ReadFileBytes(p, text)) LOGW("redirect: rule file %ls not found", p.c_str());
        else { std::vector<std::string> w; auto more = ParseRules(text, w); for (auto& x : w) LOGW("redirect: %ls: %s", p.c_str(), x.c_str()); rules.insert(rules.end(), more.begin(), more.end()); LOGI("redirect: %zu rules from %ls", more.size(), p.c_str()); }
    }
    FilesInit(rules);
    s_frames = k.timeline || k.stateJson || k.ctl || !k.autostart.empty();
    if (k.autostart.size()) s_autostartStatus = "waiting for the front end";
    if (HANDLE h = CreateThread(nullptr, 0, StateThread, nullptr, 0, nullptr)) CloseHandle(h);
    if (k.ctl || !k.autostart.empty()) {
        if (k.ctl && k.ctlDir.empty()) LOGW("ctl: dev.ctl=1 but dev.ctl_dir is empty: no control channel");
        if (k.ctlDir.empty()) k.ctlDir = rt.modDir + L"ctl";   // the config autostart alone needs no folder; keep the thread's path valid
        s_ctlWake = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (HANDLE h = CreateThread(nullptr, 0, CtlThread, nullptr, 0, nullptr)) CloseHandle(h);
    }
}

void DevOnDirect3DCreate(void* d3d) {
    if (!s_active) return;
    FilesOnDirect3DCreate();
    TlMarkOnce("d3d_create");
    ConsoleInstall();   // once, before any campaign (no-op with dev.console=0)
    CameraInstall();    // once (no-op with dev.camera=0)
    if (s_frames && d3d && !o_CreateDevice) VtableHook(*(void***)d3d, 16, (void*)hk_CreateDevice, (void**)&o_CreateDevice, "IDirect3D9::CreateDevice");
}

void DevOnDetach() {
    if (!s_active) return;
    if (Dk().timeline) { s_tl.Add("exit", "", UnixMs()); WriteTimeline(); }
}

} // namespace wsp
