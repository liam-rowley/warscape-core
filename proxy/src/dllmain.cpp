// dllmain.cpp - start-up order of the proxy (game-agnostic; the game supplies Adapter()).
//   1. folders, config file, launch id, the per-launch log (UTC) - nothing engine-side
//   2. crash capture
//   3. the exe-identity guard, ONCE, before any hook, patch or engine read -> Rt().plan (guard.h PlanEngine)
//   4. the runtime patch engine, only when Rt().plan.patches
//   5. the dev side (dev.cpp), only when a dev key is on and the plan allows hooks
//   6. headless runs (headless.cpp), only when headless.enabled; refused (exit) when the plan forbids hooks or the proxy is off
// The backend d3d9 loads later, at the first export call (backend.cpp). Loader lock: Win32 file and memory calls only.
#include "runtime.h"
#include <vector>
#include <algorithm>

#ifndef WSP_BUILD_ID
#define WSP_BUILD_ID "dev"
#endif

namespace wsp {

Runtime& Rt() { static Runtime r; return r; }

namespace {

bool ReadWhole(const std::wstring& path, std::string& out) {
    HANDLE f = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER sz{}; GetFileSizeEx(f, &sz);
    if (sz.QuadPart > (1 << 20)) { CloseHandle(f); return false; }
    out.resize((size_t)sz.QuadPart);
    DWORD got = 0; const BOOL ok = out.empty() || ReadFile(f, &out[0], (DWORD)out.size(), &got, nullptr);
    CloseHandle(f);
    out.resize(got);
    return ok;
}

// Second processes (a launcher, a tool) log to proxy.p<pid>.log; pids never repeat soon, so these files would pile up (J1 "Later").
// Keep the newest kKeep; older ones move to logs\_old\ (nothing is deleted: the uninstall moves the whole mod folder anyway).
void PruneSecondLogs(const std::wstring& dir) {
    const size_t kKeep = 5;
    std::vector<std::pair<unsigned long long, std::wstring>> v;
    WIN32_FIND_DATAW fd; HANDLE h = FindFirstFileW((dir + L"proxy.p*.log").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do v.push_back({ ((unsigned long long)fd.ftLastWriteTime.dwHighDateTime << 32) | fd.ftLastWriteTime.dwLowDateTime, fd.cFileName }); while (FindNextFileW(h, &fd));
    FindClose(h);
    if (v.size() < kKeep) return;
    std::sort(v.begin(), v.end());
    CreateDirectoryW((dir + L"_old").c_str(), nullptr);
    for (size_t i = 0; i + kKeep - 1 < v.size(); ++i) MoveFileExW((dir + v[i].second).c_str(), (dir + L"_old\\" + v[i].second).c_str(), MOVEFILE_REPLACE_EXISTING);
}

LogLevel LevelOf(const std::string& s) {
    return s == "debug" ? LogLevel::Debug : s == "warn" ? LogLevel::Warn : s == "error" ? LogLevel::Error : LogLevel::Info;
}

void Init(HMODULE self) {
    Runtime& rt = Rt();
    const GameAdapter& ad = Adapter();
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(self, path, MAX_PATH);
    std::wstring dll = path;
    rt.gameDir = dll.substr(0, dll.find_last_of(L'\\') + 1);
    rt.modDir = rt.gameDir + ad.modDir + L"\\";
    rt.configPath = rt.gameDir + ad.configFile;
    CreateDirectoryW(rt.modDir.c_str(), nullptr);

    std::string text;
    const bool haveFile = ReadWhole(rt.configPath, text);
    rt.cfg = ParseConfig(haveFile ? text : std::string(), haveFile, ad.keys, ad.nKeys);

    SYSTEMTIME st; GetSystemTime(&st); char id[64];
    snprintf(id, sizeof id, "%04d%02d%02dT%02d%02d%02dZ-p%lu", st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, GetCurrentProcessId());
    rt.launchId = id;

    // One live log per game: a second process (a launcher, a tool) gets its own log and stays a pure system-d3d9 pass-through.
    HANDLE mtx = CreateMutexW(nullptr, FALSE, ad.instanceMutex);
    const bool second = mtx && GetLastError() == ERROR_ALREADY_EXISTS;
    const LogLevel lvl = LevelOf(rt.cfg.Str("proxy.log_level"));
    if (second) {
        wchar_t base[48]; swprintf(base, 48, L"proxy.p%lu", GetCurrentProcessId());
        PruneSecondLogs(rt.modDir + L"logs\\");
        LogOpen(rt.modDir + L"logs\\", base, lvl);
    } else LogOpen(rt.modDir + L"logs\\", L"proxy", lvl);

    wchar_t exe[MAX_PATH]; GetModuleFileNameW(nullptr, exe, MAX_PATH);
    LOGI("launch %s: %s proxy d3d9.dll build %s loaded into %ls (pid %lu, base %p)", rt.launchId.c_str(), ad.gameName, WSP_BUILD_ID, exe,
         GetCurrentProcessId(), (void*)GetModuleHandleW(nullptr));
    LOGI("dll %ls", dll.c_str());
    LOGI("config: %ls %s", rt.configPath.c_str(), haveFile ? "read" : "not found: every key at its default");
    for (size_t i = 0; i < ad.nKeys; ++i)
        LOGI("config:   %-34s = %-12s%s", ad.keys[i].id, rt.cfg.Str(ad.keys[i].id).c_str(), rt.cfg.fromFile[ad.keys[i].id] ? "" : " (default)");
    for (const std::string& w : rt.cfg.warnings) LOGW("config: %s", w.c_str());

    rt.enabled = rt.cfg.Bool("proxy.enabled") && !second;
    if (second) LOGW("another instance holds the main log: this process is a pure pass-through on the system d3d9");
    HeadlessPreflight(second);                    // headless asked with the proxy off: refused, never a visible window
    if (!rt.cfg.Bool("proxy.enabled")) LOGI("proxy.enabled=0: pure pass-through (no guard, no patches, backend only)");
    if (!rt.enabled) { rt.plan = PlanEngine(false, false); return; }

    CrashInstall((int)rt.cfg.Int("proxy.minidump"));
    GuardRun();                                   // once, before anything engine-side
    rt.plan = PlanEngine(rt.enabled, rt.engineOk);
    LOGI("plan: patches=%d engine_hooks=%d d3d_hooks=%d engine_reads=%d", rt.plan.patches, rt.plan.engineHooks, rt.plan.d3dHooks, rt.plan.engineReads);
    PatchesRun();
    DevInit();                                    // dev keys only (all default off): nothing at all when none is set
    HeadlessInit();                               // headless.enabled only (default off)
    LOGI("init done; the %s backend loads at the first d3d9 call", rt.cfg.Str("proxy.backend").c_str());
}

} // namespace
} // namespace wsp

extern "C" BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(inst);
        wsp::Init(inst);
    } else if (reason == DLL_PROCESS_DETACH) {
        if (wsp::Rt().enabled) wsp::CrashCheckFilter("process detach");
        wsp::DevOnDetach();
        wsp::HeadlessOnDetach();
        LOGI("process detach (%s)", reserved ? "process exit" : "FreeLibrary");
    }
    return TRUE;
}
