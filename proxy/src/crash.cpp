// crash.cpp - in-process crash capture: a minidump into <mod>\dumps\<launch id>_<code>.dmp, named in the log.
// Mode (config proxy.minidump): 0 off; 1 (default) unhandled exceptions only, through the top-level filter, so a first-chance
// exception the engine handles itself never leaves a dump (the PC test counts dumps); 2 also dumps the first fatal first-chance
// exception (the empire-remastered behaviour; for when the engine's own top-level filter replaces ours). In every mode >= 1 the vectored handler
// logs the first few fatal first-chance exceptions with module+offset, as evidence.
// The in-process dump is empty when the heap is corrupt (empire-remastered LEARNINGS lesson 23): WER LocalDumps (proxy/tools/wer_localdumps.ps1)
// is the out-of-process backstop; read WER first.
// Stack rule (crashpolicy.h): on a stack overflow, or with less than 32 KB of stack left, the handlers only record the exception in
// static memory; CrashFlushPending logs it later from a thread with stack (every Direct3DCreate9, the top-level filter, detach).
#include "runtime.h"
#include "crashpolicy.h"
#include <dbghelp.h>

namespace wsp {
namespace {
int s_mode = 0;
LPTOP_LEVEL_EXCEPTION_FILTER s_prev = nullptr;
volatile LONG s_dumped = 0, s_logged = 0;
// Deferred record of the first exception the handlers could not log on its own thread (stack overflow or too little stack left).
volatile LONG s_deferred = 0, s_deferredLogged = 0;
DWORD s_defCode = 0, s_defTid = 0; void* s_defAddr = nullptr; uintptr_t s_defLeft = 0; LONG s_defCount = 0;
typedef VOID(WINAPI* GetLimitsFn)(PULONG_PTR, PULONG_PTR);
GetLimitsFn s_getLimits = nullptr;   // GetCurrentThreadStackLimits (Windows 8+), resolved at install: never GetProcAddress in a handler

// Lowest address of this thread's stack reservation (0 when unknown, which the policy treats as "defer").
uintptr_t StackLow() {
    ULONG_PTR lo = 0, hi = 0;
    if (s_getLimits) { s_getLimits(&lo, &hi); return (uintptr_t)lo; }
#if defined(_M_IX86) || defined(__i386__)
    uintptr_t v; __asm__ volatile("movl %%fs:0xE0C, %0" : "=r"(v));   // TEB.DeallocationStack, x86 layout (Windows 7 has no API)
    return v;
#else
    return 0;
#endif
}

// No locals beyond a few words, no calls but Interlocked*: this runs on a thread that may have no stack left.
void Defer(EXCEPTION_POINTERS* ep, uintptr_t sp, uintptr_t low) {
    InterlockedIncrement(&s_defCount);
    if (InterlockedExchange(&s_deferred, 1)) return;
    s_defCode = ep->ExceptionRecord->ExceptionCode; s_defAddr = ep->ExceptionRecord->ExceptionAddress;
    s_defTid = GetCurrentThreadId(); s_defLeft = (low && sp > low) ? sp - low : 0;
}

bool Fatal(DWORD c) {
    return c == EXCEPTION_ACCESS_VIOLATION || c == EXCEPTION_ILLEGAL_INSTRUCTION || c == EXCEPTION_STACK_OVERFLOW || c == EXCEPTION_INT_DIVIDE_BY_ZERO ||
           c == EXCEPTION_PRIV_INSTRUCTION || c == EXCEPTION_IN_PAGE_ERROR || c == 0xC0000374 /* STATUS_HEAP_CORRUPTION */ || c == 0xC0000409 /* stack buffer overrun */;
}

void Where(void* addr, char* out, size_t n) {
    HMODULE mod = nullptr; wchar_t name[MAX_PATH] = L"?";
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCWSTR)addr, &mod);
    if (mod) GetModuleFileNameW(mod, name, MAX_PATH);
    const wchar_t* base = wcsrchr(name, L'\\');
    snprintf(out, n, "%ls+0x%lx", base ? base + 1 : name, mod ? (unsigned long)((BYTE*)addr - (BYTE*)mod) : 0ul);
}

void Dump(EXCEPTION_POINTERS* ep, const char* why) {
    if (InterlockedExchange(&s_dumped, 1)) return;   // one dump per launch
    const std::wstring dir = Rt().modDir + L"dumps\\";
    CreateDirectoryW(dir.c_str(), nullptr);
    wchar_t name[MAX_PATH];
    swprintf(name, MAX_PATH, L"%ls%hs_%08lx.dmp", dir.c_str(), Rt().launchId.c_str(), ep->ExceptionRecord->ExceptionCode);
    HANDLE f = CreateFileW(name, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) { LOGE("crash: cannot create %ls (%lu)", name, GetLastError()); return; }
    MINIDUMP_EXCEPTION_INFORMATION mei{ GetCurrentThreadId(), ep, FALSE };
    const BOOL ok = MiniDumpWriteDump(GetCurrentProcess(), GetCurrentProcessId(), f,
                                      (MINIDUMP_TYPE)(MiniDumpWithIndirectlyReferencedMemory | MiniDumpWithDataSegs | MiniDumpWithThreadInfo | MiniDumpWithUnloadedModules),
                                      &mei, nullptr, nullptr);
    CloseHandle(f);
    LOGE("crash: minidump (%s) %s: %ls", why, ok ? "written" : "FAILED", name);
}

LONG WINAPI TopLevel(EXCEPTION_POINTERS* ep) {
    volatile char probe = 0; const uintptr_t sp = (uintptr_t)&probe, low = StackLow();
    const CrashAction a = CrashHandlerAction(ep->ExceptionRecord->ExceptionCode, sp, low, true);
    if (a == CrashAction::Defer) { Defer(ep, sp, low); return s_prev ? s_prev(ep) : EXCEPTION_CONTINUE_SEARCH; }
    CrashFlushPending();
    char w[300]; Where(ep->ExceptionRecord->ExceptionAddress, w, sizeof w);
    LOGE("crash: UNHANDLED exception 0x%08lx at %p = %s (thread %lu)", ep->ExceptionRecord->ExceptionCode, ep->ExceptionRecord->ExceptionAddress, w, GetCurrentThreadId());
    if (a == CrashAction::LogAndDump) Dump(ep, "unhandled");
    else LOGE("crash: in-process minidump skipped: %lu KB of stack left (WER LocalDumps is the backstop)", (unsigned long)((sp - low) / 1024));
    return s_prev ? s_prev(ep) : EXCEPTION_CONTINUE_SEARCH;
}

LONG WINAPI Vectored(EXCEPTION_POINTERS* ep) {
    const DWORD code = ep->ExceptionRecord->ExceptionCode;
    if (!Fatal(code)) return EXCEPTION_CONTINUE_SEARCH;
    volatile char probe = 0; const uintptr_t sp = (uintptr_t)&probe, low = StackLow();
    const CrashAction a = CrashHandlerAction(code, sp, low, s_mode >= 2 && !s_dumped);
    if (a == CrashAction::Defer) { Defer(ep, sp, low); return EXCEPTION_CONTINUE_SEARCH; }
    if (InterlockedIncrement(&s_logged) <= 5) {
        char w[300]; Where(ep->ExceptionRecord->ExceptionAddress, w, sizeof w);
        LOGW("crash: first-chance exception 0x%08lx at %s (thread %lu)%s - may be handled by the game", code, w, GetCurrentThreadId(),
             code == EXCEPTION_ACCESS_VIOLATION ? (ep->ExceptionRecord->ExceptionInformation[0] ? ", writing" : ", reading") : "");
        if (code == EXCEPTION_ACCESS_VIOLATION) LOGW("crash:   faulting address %p", (void*)ep->ExceptionRecord->ExceptionInformation[1]);
    }
    if (a == CrashAction::LogAndDump) Dump(ep, "first-chance");
    return EXCEPTION_CONTINUE_SEARCH;
}
// WER LocalDumps (out of process, works on a corrupt heap) is set per exe name under HKLM, 64-bit view; logged so a run report
// can say where a crash dump would be.
void LogWer() {
    wchar_t exe[MAX_PATH]; GetModuleFileNameW(nullptr, exe, MAX_PATH);
    const wchar_t* name = wcsrchr(exe, L'\\'); name = name ? name + 1 : exe;
    std::wstring key = std::wstring(L"SOFTWARE\\Microsoft\\Windows\\Windows Error Reporting\\LocalDumps\\") + name;
    HKEY k = nullptr;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, key.c_str(), 0, KEY_READ | KEY_WOW64_64KEY, &k) != ERROR_SUCCESS) {
        LOGI("crash: WER LocalDumps for %ls: off (proxy/tools/wer/Enable crash dumps.cmd turns it on)", name); return;
    }
    wchar_t folder[MAX_PATH] = L"(default %LOCALAPPDATA%\\CrashDumps)"; DWORD type = 0, sz = sizeof folder, dt = 0, dsz = sizeof dt;
    RegQueryValueExW(k, L"DumpFolder", nullptr, &type, (LPBYTE)folder, &sz);
    RegQueryValueExW(k, L"DumpType", nullptr, nullptr, (LPBYTE)&dt, &dsz);
    RegCloseKey(k);
    LOGI("crash: WER LocalDumps for %ls: on, DumpType %lu, folder %ls", name, dt, folder);
}
} // namespace

// Mode 1 relies on our top-level filter. If the game (or an overlay) replaces it after DllMain, mode 1 silently never dumps (the
// empire-remastered trap that mode 2 exists for), so this reads the current filter and says who owns it. Set-and-restore: never changes behaviour.
void CrashFlushPending() {
    if (!s_deferred || InterlockedExchange(&s_deferredLogged, 1)) return;
    char w[300]; Where(s_defAddr, w, sizeof w);
    LOGE("crash: %s 0x%08lx at %s (thread %lu) was NOT logged when it happened: %lu KB of stack left on that thread%s; %ld deferred in all"
         " (crashpolicy.h). WER LocalDumps has the stack if the process died.", s_defCode == kStatusStackOverflow ? "STACK OVERFLOW" : "exception",
         (unsigned long)s_defCode, w, (unsigned long)s_defTid, (unsigned long)(s_defLeft / 1024),
         s_defCode == kStatusStackOverflow ? " (first-chance; the game may still recover)" : "", (long)s_defCount);
}

void CrashCheckFilter(const char* when) {
    if (s_mode <= 0) return;
    CrashFlushPending();
    LPTOP_LEVEL_EXCEPTION_FILTER cur = SetUnhandledExceptionFilter(TopLevel);
    if (cur == TopLevel) { LOGI("crash: top-level filter at %s: still ours", when); return; }
    SetUnhandledExceptionFilter(cur);   // put theirs back
    char w[300] = "none"; if (cur) Where((void*)cur, w, sizeof w);
    LOGW("crash: top-level filter at %s: REPLACED by %s - mode %d %s", when, w, s_mode,
         s_mode >= 2 ? "still dumps the first fatal first-chance exception" : "will not dump an unhandled crash in-process (set proxy.minidump=2; WER LocalDumps still works)");
}

void CrashInstall(int mode) {
    LogWer();
    s_mode = mode;
    s_getLimits = (GetLimitsFn)(void*)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "GetCurrentThreadStackLimits");
    if (mode <= 0) { LOGI("crash: in-process minidumps off (proxy.minidump=0); WER LocalDumps still applies if enabled"); return; }
    s_prev = SetUnhandledExceptionFilter(TopLevel);
    AddVectoredExceptionHandler(1, Vectored);
    LOGI("crash: minidump mode %d (%s), dumps go to %ls", mode, mode >= 2 ? "unhandled + first fatal first-chance" : "unhandled only",
         (Rt().modDir + L"dumps\\").c_str());
}

} // namespace wsp
