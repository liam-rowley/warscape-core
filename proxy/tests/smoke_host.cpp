// Wine smoke host (proxy/tools/build.sh smoke): stands in for the game exe. Loads the proxy d3d9.dll from its own folder through the
// import-free LoadLibrary path, calls the exports the game imports (Direct3DCreate9, D3DPERF_BeginEvent/EndEvent), unloads, exits 0.
// The script then checks the proxy's log: launch line, guard verdict, plan, backend, a clean detach.
// Args: `crash` = an access violation after Direct3DCreate9 (the in-process dump must appear and the log name it);
// `replace crash` = install the host's own top-level filter first, as a game may (the log must say the filter was replaced).
// `wait <file>` = after Direct3DCreate9, wait up to 60 s for <file> to exist (the control channel's answer, W17), then exit without
// FreeLibrary (the ctl thread is still inside the DLL; the process exit ends it, as a game's exit does).
// `open <path>` = after Direct3DCreate9, open <path> with CreateFileW through this exe's own import table (the proxy's file hooks
// patch it, W33) and print its first bytes: "smoke: open <path>: <text>".
#include <windows.h>
#include <cstdio>
#include <cstring>
typedef void* (WINAPI* Create9)(UINT);
typedef int (WINAPI* Begin)(DWORD, LPCWSTR);
typedef int (WINAPI* End)(void);
static LONG WINAPI HostFilter(EXCEPTION_POINTERS*) { return EXCEPTION_EXECUTE_HANDLER; }   // ends the process like a game handler

int main(int argc, char** argv) {
    bool crash = false, replace = false;
    const char* waitFor = nullptr; const char* openPath = nullptr;
    for (int i = 1; i < argc; ++i) {
        crash |= !strcmp(argv[i], "crash"); replace |= !strcmp(argv[i], "replace");
        if (!strcmp(argv[i], "wait") && i + 1 < argc) waitFor = argv[++i];
        else if (!strcmp(argv[i], "open") && i + 1 < argc) openPath = argv[++i];
    }
    HMODULE h = LoadLibraryW(L".\\d3d9.dll");
    if (!h) { printf("smoke: LoadLibrary failed %lu\n", GetLastError()); return 2; }
    Begin b = (Begin)(void*)GetProcAddress(h, "D3DPERF_BeginEvent"); End e = (End)(void*)GetProcAddress(h, "D3DPERF_EndEvent");
    Create9 c = (Create9)(void*)GetProcAddress(h, "Direct3DCreate9");
    if (!b || !e || !c) { printf("smoke: missing export\n"); return 3; }
    b(0, L"smoke"); e();
    if (replace) SetUnhandledExceptionFilter(HostFilter);
    void* d3d = c(32);
    printf("smoke: Direct3DCreate9 -> %p\n", d3d);
    if (crash) { fflush(stdout); *(volatile int*)0x10 = 1; }   // access violation, writing
    if (d3d) { typedef ULONG (WINAPI* Rel)(void*); ((Rel)(*(void***)d3d)[2])(d3d); }
    if (openPath) {
        wchar_t w[MAX_PATH] = {}; MultiByteToWideChar(CP_UTF8, 0, openPath, -1, w, MAX_PATH);
        HANDLE f = CreateFileW(w, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        char buf[128] = {}; DWORD got = 0;
        if (f != INVALID_HANDLE_VALUE) { ReadFile(f, buf, sizeof buf - 1, &got, nullptr); CloseHandle(f); }
        for (DWORD i = 0; i < got; ++i) if (buf[i] == '\r' || buf[i] == '\n') buf[i] = ' ';
        printf("smoke: open %s: %s\n", openPath, f == INVALID_HANDLE_VALUE ? "(cannot open)" : buf);
        fflush(stdout);
    }
    if (waitFor) {
        for (int i = 0; i < 600 && GetFileAttributesA(waitFor) == INVALID_FILE_ATTRIBUTES; ++i) Sleep(100);
        const bool got = GetFileAttributesA(waitFor) != INVALID_FILE_ATTRIBUTES;
        printf("smoke: %s %s\n", waitFor, got ? "appeared" : "did not appear in 60 s");
        fflush(stdout);
        return got ? 0 : 4;
    }
    FreeLibrary(h);
    return 0;
}
