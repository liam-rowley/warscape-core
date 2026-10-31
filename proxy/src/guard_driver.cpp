// guard_driver.cpp - in-process driver of the exe-identity guard (pure core: guard.h; contract: proxy/README.md).
// Runs ONCE from DllMain after the config and the log, before anything engine-side. Loader lock: GetModuleHandle, VirtualQuery,
// CreateFile/ReadFile (the exe file, hashed in 1 MiB reads) only: no LoadLibrary, no threads, no waits.
#include "runtime.h"
#include "sha1.h"
#include <vector>

namespace wsp {
namespace {

bool Readable(const void* p, size_t n) {
    const uint8_t* a = (const uint8_t*)p; const uint8_t* end = a + n;
    while (a < end) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (!VirtualQuery(a, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
        a = (const uint8_t*)mbi.BaseAddress + mbi.RegionSize;
    }
    return true;
}

// Also parses the PE header from the file's first read: the only place the preferred ImageBase survives (pe.h LoadDelta).
bool HashFile(const std::wstring& path, std::string& hex, std::string& err, uint32_t& fileImageBase) {
    HANDLE f = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
                           FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (f == INVALID_HANDLE_VALUE) { err = "cannot open the exe (error " + std::to_string(GetLastError()) + ")"; return false; }
    Sha1 h; std::vector<uint8_t> buf(1 << 20); DWORD got = 0;
    bool ok = true, first = true;
    for (;;) {
        if (!ReadFile(f, buf.data(), (DWORD)buf.size(), &got, nullptr)) { err = "read error " + std::to_string(GetLastError()); ok = false; break; }
        if (!got) break;
        if (first) { const PeInfo fp = ParsePe(buf.data(), got); if (fp.ok) fileImageBase = fp.preferredBase; first = false; }
        h.Update(buf.data(), got);
    }
    CloseHandle(f);
    if (ok) hex = h.HexDigest();
    return ok;
}

void WriteNotice(const std::wstring& path, const std::string& text) {
    std::string crlf; crlf.reserve(text.size() + 64);
    for (char c : text) { if (c == '\n') crlf += '\r'; crlf += c; }
    HANDLE f = CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) { LOGE("exe_guard: cannot write %ls (%lu)", path.c_str(), GetLastError()); return; }
    DWORD wr = 0; WriteFile(f, crlf.data(), (DWORD)crlf.size(), &wr, nullptr); CloseHandle(f);
    LOGI("exe_guard: notice written: %ls", path.c_str());
}

} // namespace

void GuardRun() {
    Runtime& rt = Rt();
    const GameAdapter& ad = Adapter();
    GuardConfig c;
    c.exeGuard = (int)rt.cfg.Int("proxy.exe_guard");
    c.forceMismatch = (int)rt.cfg.Int("proxy.exe_guard_force_mismatch");
    const std::string bad = ValidateGuardConfig(c);
    if (!bad.empty()) LOGW("exe_guard: %s", bad.c_str());

    PeInfo pe;
    const uint8_t* base = (const uint8_t*)GetModuleHandleW(nullptr);
    if (base && Readable(base, 0x1000)) pe = ParsePe(base, 0x1000);
    else pe.error = "the exe's first page is not readable";
    Observed o; o.mapped = &pe;
    wchar_t exe[MAX_PATH]; GetModuleFileNameW(nullptr, exe, MAX_PATH);
    const DWORD t0 = GetTickCount();
    HashFile(exe, o.fileSha1, o.fileError, rt.fileImageBase);
    const GuardResult r = Evaluate(o, ad.identity, c);
    rt.engineOk = r.engineOk;

    const std::string sum = Summary(r);
    if (r.verdict == Verdict::Match) LOGI("%s (hashed in %lu ms)", sum.c_str(), GetTickCount() - t0);
    else if (r.verdict == Verdict::Mismatch || r.verdict == Verdict::Unpinned) LOGE("%s", sum.c_str());
    else LOGW("%s", sum.c_str());
    if (r.verdict == Verdict::Override) LOGW("exe_guard: exe_guard=0 is a DEVELOPER override: engine features run without the identity check");
    for (size_t i = 0; i < r.diffs.size() && i < 12; ++i) LOGI("exe_guard:   %s", r.diffs[i].c_str());

    const std::wstring notice = rt.modDir + L"EXE_MISMATCH.txt";
    if (!r.engineOk) {
        SYSTEMTIME st; GetSystemTime(&st); char when[128];
        snprintf(when, sizeof when, "Written %04d-%02d-%02dT%02d:%02d:%02dZ by launch %s.", st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
                 rt.launchId.c_str());
        WriteNotice(notice, NoticeText(r, ad.gameName, ad.identity.exeName, Narrow(ad.configFile).c_str(), when));
    } else if (GetFileAttributesW(notice.c_str()) != INVALID_FILE_ATTRIBUTES) {
        if (DeleteFileW(notice.c_str())) LOGI("exe_guard: removed the stale %ls (this start's exe is accepted)", notice.c_str());
    }
}

} // namespace wsp
