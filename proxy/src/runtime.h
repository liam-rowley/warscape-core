#pragma once
// In-process shared state and services of the proxy core (Windows only; the pure parts live in pe.h, sha1.h, guard.h,
// patch_engine.h and config.h). One Runtime per process, filled by dllmain.cpp Init.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <string>
#include <vector>
#include <cstdint>
#include "adapter.h"

namespace wsp {

enum class LogLevel : int { Debug = 0, Info = 1, Warn = 2, Error = 3 };

struct Runtime {
    std::wstring gameDir;      // folder of the exe, with a trailing backslash
    std::wstring modDir;       // gameDir + adapter modDir + "\"
    std::wstring configPath;   // gameDir + adapter configFile
    std::string  launchId;     // "20261028T195944Z-p1234": names the log header and every dump of this launch
    Config       cfg;
    bool         enabled = false;     // proxy.enabled and not a second instance
    bool         engineOk = false;    // exe-identity guard verdict (false until it ran)
    uint32_t     fileImageBase = 0;   // OptionalHeader.ImageBase from the exe FILE (guard_driver); the mapped header holds the actual base
    EnginePlan   plan;                // PlanEngine(enabled, engineOk): the only switch engine-side code asks
    bool         sitesAccepted = false;   // the patch engine ran and refused no site (patch_driver.cpp)
    std::string  sitesWhy;                // why not, for the features that need a site
    std::vector<uintptr_t> siteAddr;      // per adapter site: its checked address (rva + anchor, rebased), 0 when not checked ok
    bool         inDllMain = false;       // DllMain's PROCESS_ATTACH / PROCESS_DETACH work is running (StartThread refuses, W33)
};
Runtime& Rt();
// dllmain.cpp: the one way a proxy thread starts (W33, C29). It refuses inside DllMain (one LOGE naming the thread): a thread started
// under the loader lock runs beside a game that may still be single-threaded on an unserialised heap. Otherwise CreateThread,
// CloseHandle and "thread: <name> started (tid N)". headless.cpp's two starts run off DllMain through its Ensure (the source lint).
bool StartThread(LPTHREAD_START_ROUTINE fn, const char* name);

// log.cpp
void LogOpen(const std::wstring& dir, const std::wstring& baseName, LogLevel minLevel);   // rotates <base>.log -> <base>.prev.log
void LogWrite(LogLevel lvl, const char* fmt, ...);
std::wstring LogPath();
#define LOGD(...) ::wsp::LogWrite(::wsp::LogLevel::Debug, __VA_ARGS__)
#define LOGI(...) ::wsp::LogWrite(::wsp::LogLevel::Info, __VA_ARGS__)
#define LOGW(...) ::wsp::LogWrite(::wsp::LogLevel::Warn, __VA_ARGS__)
#define LOGE(...) ::wsp::LogWrite(::wsp::LogLevel::Error, __VA_ARGS__)

// crash.cpp
void CrashInstall(int mode);
void CrashFlushPending();   // logs an exception the handlers deferred (stack overflow, too little stack): call from a thread with stack
void CrashCheckFilter(const char* when);   // logs whether the top-level filter is still ours (first export call, detach)   // 0 off, 1 unhandled exceptions (default), 2 also the first fatal first-chance exception

// guard_driver.cpp
void GuardRun();               // sets Rt().engineOk and writes or removes the notice
// The file-hash read loop of the guard (the exe) and of the DLL's self-hash (W24): 1 MiB ReadFiles, each chunk to eat(ctx, data, n) in order;
// bytes = the total read; err = the open or read error and its code ("cannot open <what> (error N)", "read error N"). Loader-lock safe.
bool ReadChunks(const std::wstring& path, const char* what, void (*eat)(void* ctx, const uint8_t* data, size_t n), void* ctx,
                uint64_t& bytes, std::string& err);

// patch_driver.cpp
void PatchesRun();             // only when Rt().plan.patches
uintptr_t SiteAddress(const char* id);   // a checked site's address (hooks: the entry or instruction), 0 = not accepted
bool MemReadable(const void* p, size_t n);   // every page committed, not PAGE_NOACCESS / PAGE_GUARD (VirtualQuery; the ctl peek uses it)

// capture.cpp (J8): the D3DPERF exports report the engine's named events to a running frame capture (a flag test otherwise)
void CaptureEvent(int kind, const wchar_t* name);   // 0 BeginEvent, 1 EndEvent, 2 SetMarker

// backend.cpp
bool BackendEnsure();          // loads the configured backend once (never from DllMain); false = no d3d9 at all
const char* BackendName();
int DxvkWndProcGuard(HMODULE dxvk);   // J16: guard DXVK's window-proc reads/writes (dxvk_wndproc.cpp); returns the patched import slots
constexpr int kDxvkWndProcSlots = 4;  // Get/SetWindowLongW/A: fewer patched means DXVK reaches user32 past the guard, and backend.cpp warns

std::string Narrow(const std::wstring& w);

// log.cpp: evidence capture for the control channel (every line written while a capture is open, capped)
void LogCaptureBegin();
std::vector<std::string> LogCaptureEnd();

// hooks.cpp: hook machinery (IAT slots of a module, vtable slots) and small Win32 helpers
int  IatHook(HMODULE module, const char* dll, const char* func, void* detour, void** original);   // number of slots patched
bool VtableHook(void** vtbl, int index, void* detour, void** original, const char* name);
int64_t UnixMs();
int64_t FileTimeToUnixMs(const FILETIME& ft);
double MonoS();                                             // monotonic seconds (QPC)
std::wstring WidenUtf8(const std::string& s);
std::wstring WidenAcp(const char* s);
bool ReadFileBytes(const std::wstring& path, std::string& out, uint64_t offset = 0, uint32_t size = 0xffffffffu);
bool WriteFileAtomic(const std::wstring& path, const std::string& data);   // temp name + MoveFileEx

// dev.cpp: the dev side (timeline, file rules, state file, control channel, autostart, reset); nothing runs unless a dev key is on
void DevInit();                          // DllMain, after the plan (also reads proxy.file_rules, W33); starts no thread
void DevOnDirect3DCreate(void* d3d);     // the Direct3DCreate9 export, after the backend returned an object; the dev threads start here
void DevOnDetach();

// headless.cpp: headless runs on the virtual display (J13); nothing runs unless headless.enabled
void HeadlessPreflight(bool second);     // DllMain, before the disabled-proxy return: headless asked with the proxy off = refusal
void HeadlessInit();                     // DllMain, after the dev side
void HeadlessOnDirect3DCreate(void* d3d);// the Direct3DCreate9 export, before the dev side's hooks
void HeadlessPresent();                  // every Present (its own vtable hook)
void HeadlessOnDetach();

} // namespace wsp
