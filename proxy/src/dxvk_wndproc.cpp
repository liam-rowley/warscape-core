// dxvk_wndproc.cpp - the DXVK window-proc guard (J16, proxy.dxvk_wndproc_fix; the decision is WndProcBook in wndprocpolicy.h).
// Patches only d3d9_dxvk.dll's own import slots for user32 Get/SetWindowLongW/A (on x86 GetWindowLongPtr is GetWindowLong), so
// DXVK 3.1.1's ResetWindowProc/HookWindowProc (d3d9_window.cpp) see their own proc on top and restore the game's instead of saving a
// foreign subclass (opengl32!wglWndProc) that already points back at them. Never touches the exe image (test_wndproc lints it).
#include "runtime.h"
#include "wndprocpolicy.h"

namespace wsp {
namespace {
WndProcBook s_book;
SRWLOCK s_bookLock = SRWLOCK_INIT;
uintptr_t s_dxvkLo = 0, s_dxvkHi = 0;
using PFN_GetWL = LONG (WINAPI*)(HWND, int);
using PFN_SetWL = LONG (WINAPI*)(HWND, int, LONG);
PFN_GetWL r_GetW, r_GetA; PFN_SetWL r_SetW, r_SetA;

bool InDxvk(uintptr_t p) { return p >= s_dxvkLo && p < s_dxvkHi; }

void ModuleOf(uintptr_t p, wchar_t* out, DWORD n) {
    HMODULE m = nullptr; out[0] = 0;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCWSTR)p, &m) ||
        !GetModuleFileNameW(m, out, n)) { lstrcpynW(out, L"?", n); return; }
    const wchar_t* b = out; for (const wchar_t* c = out; *c; ++c) if (*c == L'\\') b = c + 1;
    if (b != out) memmove(out, b, (lstrlenW(b) + 1) * sizeof(wchar_t));
}

LONG GuardGet(HWND h, LONG v) {
    AcquireSRWLockShared(&s_bookLock);
    const uintptr_t told = s_book.OnGet((uintptr_t)h, (uintptr_t)(ULONG)v);
    ReleaseSRWLockShared(&s_bookLock);
    if (told != (uintptr_t)(ULONG)v) {
        wchar_t mod[MAX_PATH]; ModuleOf((uintptr_t)(ULONG)v, mod, MAX_PATH);
        LOGW("wndproc guard: window %p has %p (%ls) above DXVK's proc %p; DXVK is told its own so it restores the game's proc "
             "(the %ls layer is dropped; without this the two procs call each other: J16)", (void*)h, (void*)(uintptr_t)(ULONG)v, mod,
             (void*)told, mod);
    }
    return (LONG)told;
}

void GuardSet(HWND h, LONG proc, LONG old) {
    const bool own = InDxvk((uintptr_t)(ULONG)proc);
    AcquireSRWLockExclusive(&s_bookLock);
    s_book.OnSet((uintptr_t)h, (uintptr_t)(ULONG)proc, own);
    ReleaseSRWLockExclusive(&s_bookLock);
    LOGI("wndproc guard: DXVK %s window %p: proc %p, previous %p", own ? "hooked" : "restored", (void*)h,
         (void*)(uintptr_t)(ULONG)proc, (void*)(uintptr_t)(ULONG)old);
}

LONG WINAPI Hk_GetWindowLongW(HWND h, int i) { const LONG v = r_GetW(h, i); return i == GWL_WNDPROC ? GuardGet(h, v) : v; }
LONG WINAPI Hk_GetWindowLongA(HWND h, int i) { const LONG v = r_GetA(h, i); return i == GWL_WNDPROC ? GuardGet(h, v) : v; }
LONG WINAPI Hk_SetWindowLongW(HWND h, int i, LONG n) { const LONG o = r_SetW(h, i, n); if (i == GWL_WNDPROC) GuardSet(h, n, o); return o; }
LONG WINAPI Hk_SetWindowLongA(HWND h, int i, LONG n) { const LONG o = r_SetA(h, i, n); if (i == GWL_WNDPROC) GuardSet(h, n, o); return o; }

} // namespace

// Point d3d9_dxvk.dll's own import slots for the four user32 functions at the guard. Matching by the resolved address works for
// named and ordinal imports alike; nothing outside DXVK's IAT changes.
int DxvkWndProcGuard(HMODULE dxvk) {
    HMODULE u32 = GetModuleHandleW(L"user32.dll");
    if (!u32) return 0;
    r_GetW = (PFN_GetWL)(void*)GetProcAddress(u32, "GetWindowLongW"); r_GetA = (PFN_GetWL)(void*)GetProcAddress(u32, "GetWindowLongA");
    r_SetW = (PFN_SetWL)(void*)GetProcAddress(u32, "SetWindowLongW"); r_SetA = (PFN_SetWL)(void*)GetProcAddress(u32, "SetWindowLongA");
    const struct { void* real; void* hook; } map[] = {{(void*)r_GetW, (void*)Hk_GetWindowLongW}, {(void*)r_GetA, (void*)Hk_GetWindowLongA},
                                                      {(void*)r_SetW, (void*)Hk_SetWindowLongW}, {(void*)r_SetA, (void*)Hk_SetWindowLongA}};
    auto* base = reinterpret_cast<uint8_t*>(dxvk);
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS32*>(base + dos->e_lfanew);
    s_dxvkLo = (uintptr_t)base; s_dxvkHi = s_dxvkLo + nt->OptionalHeader.SizeOfImage;
    const IMAGE_DATA_DIRECTORY& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return 0;
    int patched = 0;
    for (auto* d = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress); d->Name; ++d) {
        if (lstrcmpiA(reinterpret_cast<const char*>(base + d->Name), "user32.dll")) continue;
        for (auto* t = reinterpret_cast<IMAGE_THUNK_DATA32*>(base + d->FirstThunk); t->u1.Function; ++t)
            for (const auto& m : map)
                if (m.real && (void*)(uintptr_t)t->u1.Function == m.real) {
                    DWORD old;
                    if (!VirtualProtect(&t->u1.Function, sizeof(DWORD), PAGE_READWRITE, &old)) continue;
                    t->u1.Function = (DWORD)(uintptr_t)m.hook;
                    VirtualProtect(&t->u1.Function, sizeof(DWORD), old, &old);
                    ++patched;
                }
    }
    return patched;
}

} // namespace wsp
