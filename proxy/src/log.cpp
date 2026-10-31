// log.cpp - one log file per launch, UTC timestamps (empire-remastered's local-time logs caused misreads), previous launch kept.
// <dir>\<base>.log is this launch; the previous one is moved to <base>.prev.log at open. Win32 file API only (callable from
// DllMain and from the crash handler), unbuffered writes so a crash loses nothing, one lock.
#include "runtime.h"
#include <cstdarg>
#include <cstdio>

namespace wsp {
namespace {
HANDLE s_file = INVALID_HANDLE_VALUE;
LogLevel s_min = LogLevel::Info;
CRITICAL_SECTION s_cs;
bool s_csInit = false;
std::wstring s_path;
std::vector<std::string>* s_cap = nullptr;   // open evidence capture (control channel), under s_cs
int s_capDepth = 0;
const size_t kCapMax = 120;
}

void LogCaptureBegin() {
    if (!s_csInit) return;
    EnterCriticalSection(&s_cs);
    if (!s_cap) s_cap = new std::vector<std::string>();
    ++s_capDepth;
    LeaveCriticalSection(&s_cs);
}
std::vector<std::string> LogCaptureEnd() {
    std::vector<std::string> out;
    if (!s_csInit) return out;
    EnterCriticalSection(&s_cs);
    if (s_cap) { out = *s_cap; if (--s_capDepth <= 0) { delete s_cap; s_cap = nullptr; s_capDepth = 0; } else s_cap->clear(); }
    LeaveCriticalSection(&s_cs);
    return out;
}

std::wstring LogPath() { return s_path; }

void LogOpen(const std::wstring& dir, const std::wstring& baseName, LogLevel minLevel) {
    if (!s_csInit) { InitializeCriticalSection(&s_cs); s_csInit = true; }
    s_min = minLevel;
    CreateDirectoryW(dir.c_str(), nullptr);
    s_path = dir + baseName + L".log";
    const std::wstring prev = dir + baseName + L".prev.log";
    MoveFileExW(s_path.c_str(), prev.c_str(), MOVEFILE_REPLACE_EXISTING);   // fails harmlessly on the first launch
    s_file = CreateFileW(s_path.c_str(), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
}

void LogWrite(LogLevel lvl, const char* fmt, ...) {
    if ((int)lvl < (int)s_min) return;
    char msg[2048];
    va_list ap; va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);
    static const char* names[] = { "DEBUG", "INFO ", "WARN ", "ERROR" };
    SYSTEMTIME st; GetSystemTime(&st);
    char line[2200];
    const int n = snprintf(line, sizeof line, "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ [%s] [t%lu] %s\r\n", st.wYear, st.wMonth, st.wDay,
                           st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, names[(int)lvl], GetCurrentThreadId(), msg);
    if (!s_csInit) return;
    EnterCriticalSection(&s_cs);
    if (s_file != INVALID_HANDLE_VALUE && n > 0) { DWORD wr = 0; WriteFile(s_file, line, (DWORD)(n < (int)sizeof line ? n : (int)sizeof line - 1), &wr, nullptr); }
    if (s_cap && s_cap->size() < kCapMax && n > 2) s_cap->push_back(std::string(line, (size_t)(n < (int)sizeof line ? n - 2 : (int)sizeof line - 3)));
    LeaveCriticalSection(&s_cs);
    OutputDebugStringA(line);
}

std::string Narrow(const std::wstring& w) {
    if (w.empty()) return {};
    const int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string s(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), &s[0], n, nullptr, nullptr);
    return s;
}

} // namespace wsp
