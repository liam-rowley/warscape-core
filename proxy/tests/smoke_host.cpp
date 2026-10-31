// Wine smoke host (proxy/tools/build.sh smoke): stands in for the game exe. Loads the proxy d3d9.dll from its own folder through the
// import-free LoadLibrary path, calls the exports the game imports (Direct3DCreate9, D3DPERF_BeginEvent/EndEvent), unloads, exits 0.
// The script then checks the proxy's log: launch line, guard verdict, plan, backend, a clean detach.
// Args: `crash` = an access violation after Direct3DCreate9 (the in-process dump must appear and the log name it);
// `replace crash` = install the host's own top-level filter first, as a game may (the log must say the filter was replaced).
#include <windows.h>
#include <cstdio>
#include <cstring>
typedef void* (WINAPI* Create9)(UINT);
typedef int (WINAPI* Begin)(DWORD, LPCWSTR);
typedef int (WINAPI* End)(void);
static LONG WINAPI HostFilter(EXCEPTION_POINTERS*) { return EXCEPTION_EXECUTE_HANDLER; }   // ends the process like a game handler

int main(int argc, char** argv) {
    bool crash = false, replace = false;
    for (int i = 1; i < argc; ++i) { crash |= !strcmp(argv[i], "crash"); replace |= !strcmp(argv[i], "replace"); }
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
    FreeLibrary(h);
    return 0;
}
