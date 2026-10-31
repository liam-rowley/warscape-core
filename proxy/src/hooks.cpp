// hooks.cpp - the proxy's hook machinery: import-address-table (IAT) patching of the game exe and vtable slots of D3D objects.
// Why IAT patching and not MinHook (J3 decision, proxy/README.md "Hooks"): every hook the dev side needs is a call the exe makes
// through its OWN import table: the game exe links the CRT statically, so fopen/CreateFile, FindFirstFile and BinkOpen all go
// through it (fact <game>.exe.static_crt_imports; core files name no game), and swapping one pointer is enough. Nothing is disassembled or relocated, no third-party
// code ships, other modules (DXVK, the driver, Steam) keep the real functions, and a slot is restored by writing the old pointer back.
// empire-remastered used MinHook on KernelBase and its zero-touch build crashed 0.34 s after start without a found cause (LEARNINGS
// "Zero-touch (b) kit and the crash"); a process-wide inline hook is exactly what this avoids. Engine-code detours, if a feature ever
// needs one, go through the engine_sites registry and the patch engine, not here.
// Every hook installed is logged with its slot address and the old and new pointer.
#include "runtime.h"

namespace wsp {

// Returns the number of slots now pointing at the detour, or -1 when the slot is not snapped yet (try again later).
int IatHook(HMODULE module, const char* dll, const char* func, void* detour, void** original) {
    auto* base = reinterpret_cast<BYTE*>(module);
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (!base || dos->e_magic != IMAGE_DOS_SIGNATURE) { LOGW("hook: iat %s!%s: bad module", dll, func); return 0; }
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    const IMAGE_DATA_DIRECTORY& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) { LOGW("hook: iat %s!%s: no import directory", dll, func); return 0; }
    int n = 0;
    for (auto* d = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress); d->Name; ++d) {
        if (lstrcmpiA(reinterpret_cast<const char*>(base + d->Name), dll) != 0 || !d->OriginalFirstThunk) continue;
        auto* names = reinterpret_cast<IMAGE_THUNK_DATA*>(base + d->OriginalFirstThunk);
        auto* slots = reinterpret_cast<IMAGE_THUNK_DATA*>(base + d->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++slots) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            auto* ibn = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + names->u1.AddressOfData);
            if (lstrcmpA(reinterpret_cast<const char*>(ibn->Name), func) != 0) continue;
            void** slot = reinterpret_cast<void**>(&slots->u1.Function);
            if (*slot == detour) { ++n; continue; }   // already ours (a second install pass)
            HMODULE owner = nullptr;   // a snapped slot points into a loaded module; before the loader snaps it holds an RVA
            if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCWSTR)*slot, &owner)) {
                LOGW("hook: iat %s!%s slot %p holds %p (not snapped yet): deferred", dll, func, (void*)slot, *slot);
                return -1;
            }
            DWORD old = 0;
            if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old)) { LOGE("hook: iat %s!%s: VirtualProtect failed %lu", dll, func, GetLastError()); return n; }
            void* prev = InterlockedExchangePointer(slot, detour);
            DWORD tmp; VirtualProtect(slot, sizeof(void*), old, &tmp);
            if (original && (!*original || n == 0)) *original = prev;
            LOGI("hook: iat %s!%s slot %p: %p -> %p", dll, func, (void*)slot, prev, detour);
            ++n;
        }
    }
    if (!n) LOGW("hook: iat %s!%s: not imported by this module", dll, func);
    return n;
}

bool VtableHook(void** vtbl, int index, void* detour, void** original, const char* name) {
    void** slot = vtbl + index;
    if (*slot == detour) return true;   // already ours (a second device of the same class)
    DWORD old = 0;
    if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old)) { LOGE("hook: vtable %s: VirtualProtect failed %lu", name, GetLastError()); return false; }
    void* prev = InterlockedExchangePointer(slot, detour);
    DWORD tmp; VirtualProtect(slot, sizeof(void*), old, &tmp);
    if (original) *original = prev;
    LOGI("hook: vtable %s slot %p [%d]: %p -> %p", name, (void*)slot, index, prev, detour);
    return true;
}

int64_t UnixMs() {
    FILETIME ft; GetSystemTimeAsFileTime(&ft);
    ULARGE_INTEGER u; u.LowPart = ft.dwLowDateTime; u.HighPart = ft.dwHighDateTime;
    return (int64_t)((u.QuadPart - 116444736000000000ULL) / 10000ULL);
}
int64_t FileTimeToUnixMs(const FILETIME& ft) {
    ULARGE_INTEGER u; u.LowPart = ft.dwLowDateTime; u.HighPart = ft.dwHighDateTime;
    return (int64_t)((u.QuadPart - 116444736000000000ULL) / 10000ULL);
}
double MonoS() {
    static LARGE_INTEGER f = [] { LARGE_INTEGER x; QueryPerformanceFrequency(&x); return x; }();
    LARGE_INTEGER c; QueryPerformanceCounter(&c);
    return (double)c.QuadPart / (double)f.QuadPart;
}

std::wstring WidenUtf8(const std::string& s) {
    if (s.empty()) return {};
    const int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0);
    std::wstring w(n, L'\0'); MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), &w[0], n);
    return w;
}
std::wstring WidenAcp(const char* s) {
    if (!s || !*s) return {};
    const int n = MultiByteToWideChar(CP_ACP, 0, s, -1, nullptr, 0);
    std::wstring w(n > 0 ? n - 1 : 0, L'\0');
    if (n > 1) MultiByteToWideChar(CP_ACP, 0, s, -1, &w[0], n);
    return w;
}

bool ReadFileBytes(const std::wstring& path, std::string& out, uint64_t offset, uint32_t size) {
    HANDLE f = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    if (size == 0xffffffffu) { LARGE_INTEGER sz{}; GetFileSizeEx(f, &sz); size = sz.QuadPart > (64 << 20) ? (64u << 20) : (uint32_t)sz.QuadPart; }
    LARGE_INTEGER li; li.QuadPart = (LONGLONG)offset;
    out.assign(size, '\0');
    DWORD got = 0;
    const BOOL ok = SetFilePointerEx(f, li, nullptr, FILE_BEGIN) && (size == 0 || ReadFile(f, &out[0], size, &got, nullptr));
    CloseHandle(f);
    out.resize(got);
    return ok && got == size;
}

bool WriteFileAtomic(const std::wstring& path, const std::string& data) {
    const std::wstring tmp = path + L".tmp";
    HANDLE f = CreateFileW(tmp.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    DWORD wr = 0; const BOOL ok = WriteFile(f, data.data(), (DWORD)data.size(), &wr, nullptr);
    CloseHandle(f);
    if (!ok || wr != data.size()) { DeleteFileW(tmp.c_str()); return false; }
    return MoveFileExW(tmp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING) != 0;
}

} // namespace wsp
