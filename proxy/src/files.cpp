// files.cpp - file redirection, the file-open survey and the movie hooks (dev side; ported from empire-remastered
// rml_mod/src/devspeed.cpp FILE REDIRECTION + Bink, re-checked on each game). Hooks are IAT slots of the game exe (hooks.cpp):
//   CreateFileA/W            redirect / fail rules; dev.log_files logs every distinct path (logs\files.log)
//   GetFileAttributesW/ExA/ExW  the engine checks a file before opening it (empire-remastered: uied.templates opened with access 0x80 first):
//                            the same rules apply, so the check and the open see the same file
//   FindFirstFileW/ExW, FindNextFileW, FindClose   `add` rules: virtual files listed in their folder (packs in data\)
//   binkw32 BinkOpen/BinkClose  movie rules (matched against the PACK ENTRY behind a Bink file handle), skip-intro, movie timeline
// Nothing is hooked unless a key or rule needs it. The proxy's own file calls go straight to kernel32 (not through the exe's
// import table), so they never meet these hooks.
#include "dev.h"
#include "pack.h"
#include <map>
#include <set>

namespace wsp {
namespace {

std::vector<FileRule> s_rules;
bool s_fileRules = false, s_addRules = false, s_movieRules = false;
CRITICAL_SECTION s_cs;
std::set<std::wstring> s_seen;
HANDLE s_survey = INVALID_HANDLE_VALUE;
size_t s_surveyLines = 0;
const size_t kSurveyMax = 20000;
std::wstring s_gameLower;

void MapProbe(const wchar_t* path);
void Survey(const char* api, const wchar_t* path, const char* what, DWORD a, DWORD b, bool ok, DWORD err) {
    if (api[0] != 'f') MapProbe(path);   // opens and attribute checks, not directory listings
    if (!Dk().logFiles || !path || s_survey == INVALID_HANDLE_VALUE) return;
    std::wstring key = NormPath(path); key += L'|'; key += WidenAcp(api);
    EnterCriticalSection(&s_cs);
    const bool fresh = s_surveyLines < kSurveyMax && s_seen.insert(key).second;
    if (fresh) {
        ++s_surveyLines;
        char line[1400];
        const int n = snprintf(line, sizeof line, "%s\t%s\t%s\t0x%lx\t%lu\t%s\t%lu\t%s\r\n", UtcIso(UnixMs()).c_str(), api, what, a, b,
                               ok ? "ok" : "FAILED", ok ? 0UL : err, Narrow(path).c_str());
        DWORD wr; if (n > 0) WriteFile(s_survey, line, (DWORD)(n < (int)sizeof line ? n : (int)sizeof line - 1), &wr, nullptr);
    }
    LeaveCriticalSection(&s_cs);
}

// The battle map the engine actually loads, from its own file access: while loading a battle it probes loose copies of the map's
// preset folder (<adapter mapProbe><folder>\..., run 20261029_j3pc: data\battleterrain\presets\nap_mp_grassy_flatlands\...).
// Reported as "battle.map_folder" (the control channel's map check compares it with the preset's map folder), with
// "battle.map_folder_ms" = ms after the load request (FilesMapReset). Only a report change is sent, so the front end's map-list walk,
// which probes every map's folder and ends on the selected one, would hide the load's own probe of that folder: FilesMapReset
// clears the dedup when the load is requested (J3 review finding 1, run 20261029_j3pc2 f_resets10).
std::wstring s_lastMap;
ULONGLONG s_mapEpoch = 0;   // GetTickCount64 at the last FilesMapReset; 0 = none yet
void MapProbe(const wchar_t* path) {
    const DevAdapter* ad = Adapter().dev;
    if (!ad || !ad->mapProbe || !path) return;
    static const std::wstring prefix = NormPath(WidenAcp(ad->mapProbe));
    const std::wstring rel = RelToGame(path, s_gameLower);
    if (rel.size() <= prefix.size() || rel.compare(0, prefix.size(), prefix) != 0) return;
    const size_t end = rel.find(L'\\', prefix.size());
    const std::wstring folder = rel.substr(prefix.size(), end == std::wstring::npos ? std::wstring::npos : end - prefix.size());
    if (folder.empty()) return;
    EnterCriticalSection(&s_cs);
    const bool changed = folder != s_lastMap;
    if (changed) s_lastMap = folder;
    const ULONGLONG epoch = s_mapEpoch;
    LeaveCriticalSection(&s_cs);
    if (!changed) return;
    DevReport("battle.map_folder", Narrow(folder));
    DevReport("battle.map_folder_ms", epoch ? std::to_string(GetTickCount64() - epoch) : std::string());
}

// A read-only open or an attribute check of `path`: the redirect target ("" = none) or fail.
bool Apply(const wchar_t* path, bool readOnly, std::wstring& target, bool& fail) {
    fail = false; target.clear();
    if (!s_fileRules || !path || !readOnly) return false;
    const std::wstring rel = RelToGame(path, s_gameLower);
    EnterCriticalSection(&s_cs);
    FileRule* r = MatchRule(s_rules, RuleSpace::File, rel);
    bool handled = false;
    if (r && r->act == RuleAct::Fail) {
        if (!r->hit) LOGI("redirect: fail %ls (%s)", path, r->origin.c_str());
        r->hit = true; fail = true; handled = true;
    } else if (r) {   // Redirect, or Add (a virtual file opens its target)
        const std::wstring t = RuleTarget(*r, rel, Rt().gameDir);
        if (GetFileAttributesW(t.c_str()) == INVALID_FILE_ATTRIBUTES) {
            if (!r->warned) LOGW("redirect: %ls -> %ls: target missing, vanilla file used (%s)", path, t.c_str(), r->origin.c_str());
            r->warned = true;
        } else {
            if (!r->hit) LOGI("redirect: %ls -> %ls (%s)", path, t.c_str(), r->origin.c_str());
            r->hit = true; target = t; handled = true;
        }
    }
    LeaveCriticalSection(&s_cs);
    return handled;
}

// ---- CreateFile ------------------------------------------------------------------------------------------------------------
using PFN_CreateFileW = HANDLE(WINAPI*)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
using PFN_CreateFileA = HANDLE(WINAPI*)(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
PFN_CreateFileW o_CreateFileW; PFN_CreateFileA o_CreateFileA;

HANDLE WINAPI hk_CreateFileW(LPCWSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa, DWORD disp, DWORD flags, HANDLE tmpl) {
    std::wstring to; bool fail = false; HANDLE h;
    if (Apply(name, IsReadOnlyOpen(access, disp), to, fail)) {
        if (fail) { SetLastError(ERROR_FILE_NOT_FOUND); h = INVALID_HANDLE_VALUE; }
        else h = CreateFileW(to.c_str(), access, share, sa, disp, flags, tmpl);
    } else h = o_CreateFileW(name, access, share, sa, disp, flags, tmpl);
    const DWORD err = GetLastError();
    Survey("open.W", name, to.empty() ? "-" : "redirected", access, disp, h != INVALID_HANDLE_VALUE, err);
    SetLastError(err);
    return h;
}
HANDLE WINAPI hk_CreateFileA(LPCSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa, DWORD disp, DWORD flags, HANDLE tmpl) {
    if (!name) return o_CreateFileA(name, access, share, sa, disp, flags, tmpl);
    const std::wstring w = WidenAcp(name);
    std::wstring to; bool fail = false; HANDLE h;
    if (Apply(w.c_str(), IsReadOnlyOpen(access, disp), to, fail)) {
        if (fail) { SetLastError(ERROR_FILE_NOT_FOUND); h = INVALID_HANDLE_VALUE; }
        else h = CreateFileW(to.c_str(), access, share, sa, disp, flags, tmpl);
    } else h = o_CreateFileA(name, access, share, sa, disp, flags, tmpl);
    const DWORD err = GetLastError();
    Survey("open.A", w.c_str(), to.empty() ? "-" : "redirected", access, disp, h != INVALID_HANDLE_VALUE, err);
    SetLastError(err);
    return h;
}

// ---- attributes -----------------------------------------------------------------------------------------------------------
using PFN_GetFileAttributesW = DWORD(WINAPI*)(LPCWSTR);
using PFN_GetFileAttributesExW = BOOL(WINAPI*)(LPCWSTR, GET_FILEEX_INFO_LEVELS, LPVOID);
using PFN_GetFileAttributesExA = BOOL(WINAPI*)(LPCSTR, GET_FILEEX_INFO_LEVELS, LPVOID);
PFN_GetFileAttributesW o_GetFileAttributesW; PFN_GetFileAttributesExW o_GetFileAttributesExW; PFN_GetFileAttributesExA o_GetFileAttributesExA;

DWORD WINAPI hk_GetFileAttributesW(LPCWSTR name) {
    std::wstring to; bool fail = false; DWORD r;
    if (Apply(name, true, to, fail)) { if (fail) { SetLastError(ERROR_FILE_NOT_FOUND); r = INVALID_FILE_ATTRIBUTES; } else r = GetFileAttributesW(to.c_str()); }
    else r = o_GetFileAttributesW(name);
    const DWORD err = GetLastError();
    Survey("attr.W", name, to.empty() ? "-" : "redirected", r, 0, r != INVALID_FILE_ATTRIBUTES, err);
    SetLastError(err);
    return r;
}
BOOL WINAPI hk_GetFileAttributesExW(LPCWSTR name, GET_FILEEX_INFO_LEVELS lvl, LPVOID info) {
    std::wstring to; bool fail = false; BOOL r;
    if (Apply(name, true, to, fail)) { if (fail) { SetLastError(ERROR_FILE_NOT_FOUND); r = FALSE; } else r = GetFileAttributesExW(to.c_str(), lvl, info); }
    else r = o_GetFileAttributesExW(name, lvl, info);
    const DWORD err = GetLastError();
    Survey("attrx.W", name, to.empty() ? "-" : "redirected", 0, 0, r != FALSE, err);
    SetLastError(err);
    return r;
}
BOOL WINAPI hk_GetFileAttributesExA(LPCSTR name, GET_FILEEX_INFO_LEVELS lvl, LPVOID info) {
    if (!name) return o_GetFileAttributesExA(name, lvl, info);
    const std::wstring w = WidenAcp(name);
    std::wstring to; bool fail = false; BOOL r;
    if (Apply(w.c_str(), true, to, fail)) { if (fail) { SetLastError(ERROR_FILE_NOT_FOUND); r = FALSE; } else r = GetFileAttributesExW(to.c_str(), lvl, info); }
    else r = o_GetFileAttributesExA(name, lvl, info);
    const DWORD err = GetLastError();
    Survey("attrx.A", w.c_str(), to.empty() ? "-" : "redirected", 0, 0, r != FALSE, err);
    SetLastError(err);
    return r;
}

// ---- virtual files (`add` rules) -------------------------------------------------------------------------------------------
using PFN_FindFirstFileExW = HANDLE(WINAPI*)(LPCWSTR, FINDEX_INFO_LEVELS, LPVOID, FINDEX_SEARCH_OPS, LPVOID, DWORD);
using PFN_FindFirstFileW = HANDLE(WINAPI*)(LPCWSTR, LPWIN32_FIND_DATAW);
using PFN_FindNextFileW = BOOL(WINAPI*)(HANDLE, LPWIN32_FIND_DATAW);
using PFN_FindClose = BOOL(WINAPI*)(HANDLE);
PFN_FindFirstFileExW o_FindFirstFileExW; PFN_FindFirstFileW o_FindFirstFileW; PFN_FindNextFileW o_FindNextFileW; PFN_FindClose o_FindClose;
struct Virtual { std::wstring name, target; };
std::map<HANDLE, std::vector<Virtual>> s_pending;

bool FillFind(const Virtual& v, WIN32_FIND_DATAW* fd) {
    WIN32_FILE_ATTRIBUTE_DATA a{};
    if (!GetFileAttributesExW(v.target.c_str(), GetFileExInfoStandard, &a)) return false;
    memset(fd, 0, sizeof *fd);
    fd->dwFileAttributes = a.dwFileAttributes; fd->ftCreationTime = a.ftCreationTime; fd->ftLastAccessTime = a.ftLastAccessTime;
    fd->ftLastWriteTime = a.ftLastWriteTime; fd->nFileSizeHigh = a.nFileSizeHigh; fd->nFileSizeLow = a.nFileSizeLow;
    lstrcpynW(fd->cFileName, v.name.c_str(), MAX_PATH);
    return true;
}
std::vector<Virtual> VirtualsFor(const wchar_t* pattern) {
    std::vector<Virtual> out;
    if (!s_addRules || !pattern) return out;
    std::wstring dir, spec; SplitDir(RelToGame(pattern, s_gameLower), dir, spec);
    EnterCriticalSection(&s_cs);
    for (auto& r : s_rules) {
        if (r.space != RuleSpace::File || r.act != RuleAct::Add || r.prefix) continue;
        std::wstring rdir, rname; SplitDir(r.from, rdir, rname);
        if (rdir != dir || !WildMatch(spec.c_str(), rname.c_str())) continue;
        if (GetFileAttributesW((Rt().gameDir + r.from).c_str()) != INVALID_FILE_ATTRIBUTES) continue;   // a real file wins
        const std::wstring t = RuleTarget(r, r.from, Rt().gameDir);
        if (GetFileAttributesW(t.c_str()) == INVALID_FILE_ATTRIBUTES) {
            if (!r.warned) LOGW("redirect: add %ls: target %ls missing", r.from.c_str(), t.c_str());
            r.warned = true; continue;
        }
        if (!r.hit) LOGI("redirect: add %ls (listed for %ls, served from %ls; %s)", r.from.c_str(), pattern, t.c_str(), r.origin.c_str());
        r.hit = true;
        out.push_back({ rname, t });
    }
    LeaveCriticalSection(&s_cs);
    return out;
}
HANDLE FindFirstCommon(HANDLE h, LPCWSTR pattern, WIN32_FIND_DATAW* fd) {
    std::vector<Virtual> v = VirtualsFor(pattern);
    if (v.empty()) return h;
    if (h == INVALID_HANDLE_VALUE) {   // nothing real matched: a genuine handle from the first virtual file's target, renamed
        h = o_FindFirstFileW ? o_FindFirstFileW(v[0].target.c_str(), fd) : FindFirstFileW(v[0].target.c_str(), fd);
        if (h == INVALID_HANDLE_VALUE) return h;
        lstrcpynW(fd->cFileName, v[0].name.c_str(), MAX_PATH); fd->cAlternateFileName[0] = 0;
        v.erase(v.begin());
    }
    if (!v.empty()) { EnterCriticalSection(&s_cs); s_pending[h] = v; LeaveCriticalSection(&s_cs); }
    return h;
}
HANDLE WINAPI hk_FindFirstFileExW(LPCWSTR name, FINDEX_INFO_LEVELS lvl, LPVOID data, FINDEX_SEARCH_OPS op, LPVOID filter, DWORD flags) {
    HANDLE h = o_FindFirstFileExW(name, lvl, data, op, filter, flags);
    const DWORD err = GetLastError();
    Survey("find.ExW", name, "-", (DWORD)lvl, (DWORD)op, h != INVALID_HANDLE_VALUE, err);
    if (op == FindExSearchNameMatch && lvl == FindExInfoStandard) h = FindFirstCommon(h, name, (WIN32_FIND_DATAW*)data);
    if (h == INVALID_HANDLE_VALUE) SetLastError(err);
    return h;
}
HANDLE WINAPI hk_FindFirstFileW(LPCWSTR name, LPWIN32_FIND_DATAW data) {
    HANDLE h = o_FindFirstFileW(name, data);
    const DWORD err = GetLastError();
    Survey("find.W", name, "-", 0, 0, h != INVALID_HANDLE_VALUE, err);
    h = FindFirstCommon(h, name, data);
    if (h == INVALID_HANDLE_VALUE) SetLastError(err);
    return h;
}
BOOL WINAPI hk_FindNextFileW(HANDLE h, LPWIN32_FIND_DATAW data) {
    BOOL ok = o_FindNextFileW(h, data);
    if (ok || GetLastError() != ERROR_NO_MORE_FILES) return ok;
    EnterCriticalSection(&s_cs);
    auto it = s_pending.find(h);
    while (it != s_pending.end() && !it->second.empty()) {
        Virtual v = it->second.front(); it->second.erase(it->second.begin());
        if (FillFind(v, data)) { LeaveCriticalSection(&s_cs); return TRUE; }
    }
    LeaveCriticalSection(&s_cs);
    SetLastError(ERROR_NO_MORE_FILES);
    return FALSE;
}
BOOL WINAPI hk_FindClose(HANDLE h) {
    EnterCriticalSection(&s_cs); s_pending.erase(h); LeaveCriticalSection(&s_cs);
    return o_FindClose(h);
}

// ---- packs: movie names and vanilla entries --------------------------------------------------------------------------------
struct PackFile { std::wstring path, pathLower; PackIndex idx; };
std::vector<PackFile> s_packs;    // every real PFH0 pack in the adapter's pack folder, in listing order
bool s_packsRead = false;

void ReadPacks() {
    if (s_packsRead) return;
    s_packsRead = true;
    const DevAdapter* ad = Adapter().dev;
    const std::wstring glob = Rt().gameDir + WidenAcp(ad && ad->packGlob ? ad->packGlob : "data\\*.pack");
    const std::wstring dir = glob.substr(0, glob.find_last_of(L'\\') + 1);
    WIN32_FIND_DATAW fd; HANDLE h = FindFirstFileW(glob.c_str(), &fd);   // kernel32 directly: real files only
    if (h == INVALID_HANDLE_VALUE) { LOGW("packs: nothing matches %ls", glob.c_str()); return; }
    do {
        PackFile pf; pf.path = dir + fd.cFileName; pf.pathLower = NormPath(pf.path);
        std::string hdr;
        if (!ReadFileBytes(pf.path, hdr, 0, 24)) continue;
        const uint64_t more = PackIndexBytes((const unsigned char*)hdr.data(), hdr.size());
        if (!more || more > (64u << 20)) continue;
        std::string all;
        if (!ReadFileBytes(pf.path, all, 0, (uint32_t)(24 + more))) continue;
        pf.idx = ParsePackIndex((const unsigned char*)all.data(), all.size());
        if (!pf.idx.error.empty()) { LOGW("packs: %ls: %s", fd.cFileName, pf.idx.error.c_str()); continue; }
        s_packs.push_back(std::move(pf));
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    size_t n = 0; for (auto& p : s_packs) n += p.idx.entries.size();
    LOGI("packs: %zu packs, %zu entries indexed (%ls)", s_packs.size(), n, glob.c_str());
}

const unsigned kBinkFileHandle = 0x00800000;
using PFN_BinkOpen = void*(__stdcall*)(const char*, unsigned);
using PFN_BinkClose = void(__stdcall*)(void*);
PFN_BinkOpen o_BinkOpen; PFN_BinkClose o_BinkClose;
volatile LONG s_skipped = 0, s_opened = 0;
std::map<void*, std::string> s_open;   // HBINK -> movie name

bool IsIn(const char* const* list, const std::string& name) { for (; list && *list; ++list) if (name == *list) return true; return false; }

std::string BinkName(const char* name, unsigned flags, std::string& detail) {
    if (!(flags & kBinkFileHandle)) {
        detail = std::string("path ") + (name ? name : "");
        std::wstring rel = RelToGame(WidenAcp(name), s_gameLower);
        std::string r = Narrow(rel);
        if (r.rfind("data\\", 0) == 0) r = r.substr(5);
        return r;
    }
    HANDLE fh = (HANDLE)name;
    wchar_t buf[MAX_PATH * 2] = L"";
    GetFinalPathNameByHandleW(fh, buf, MAX_PATH * 2, FILE_NAME_NORMALIZED);
    LARGE_INTEGER zero{}, pos{}; SetFilePointerEx(fh, zero, &pos, FILE_CURRENT);
    char d[700]; snprintf(d, sizeof d, "handle %p = %s @ %lld", (void*)fh, Narrow(buf).c_str(), (long long)pos.QuadPart);
    detail = d;
    EnterCriticalSection(&s_cs); ReadPacks(); LeaveCriticalSection(&s_cs);
    std::wstring p = NormPath(buf);
    if (p.rfind(L"\\\\?\\", 0) == 0) p = p.substr(4);
    for (const auto& pf : s_packs) {
        if (pf.pathLower != p) continue;
        if (const PackEntry* e = PackAt(pf.idx, (uint64_t)pos.QuadPart)) return e->path;
    }
    return "";
}

void* __stdcall hk_BinkOpen(const char* name, unsigned flags) {
    std::string detail;
    const std::string movie = BinkName(name, flags, detail);
    const DevAdapter* ad = Adapter().dev;
    FileRule* r = nullptr;
    if (s_movieRules) { EnterCriticalSection(&s_cs); r = MatchRule(s_rules, RuleSpace::Movie, NormPath(WidenAcp(movie.c_str()))); LeaveCriticalSection(&s_cs); }
    if (r && r->act == RuleAct::Fail) {
        InterlockedIncrement(&s_skipped);
        LOGI("movies: BinkOpen %s refused (%s) [%s, flags 0x%x]", movie.c_str(), r->origin.c_str(), detail.c_str(), flags);
        TlMark("movie_refused", movie);
        return nullptr;
    }
    if (r && r->act == RuleAct::Redirect) {
        const std::wstring t = IsAbsolute(r->to) ? r->to : Rt().gameDir + r->to;
        if (GetFileAttributesW(t.c_str()) != INVALID_FILE_ATTRIBUTES) {
            LOGI("movies: BinkOpen %s -> %ls (%s)", movie.c_str(), t.c_str(), r->origin.c_str());
            void* b = o_BinkOpen(Narrow(t).c_str(), flags & ~kBinkFileHandle);
            TlMark("movie_open", movie + " -> " + Narrow(t));
            return b;
        }
        LOGW("movies: BinkOpen %s: redirect target %ls missing", movie.c_str(), t.c_str());
    }
    TlMark("movie_open", movie.empty() ? "?" : movie);
    void* b = o_BinkOpen(name, flags);
    InterlockedIncrement(&s_opened);
    LOGI("movies: BinkOpen %s [%s, flags 0x%x] -> %p", movie.empty() ? "?" : movie.c_str(), detail.c_str(), flags, b);
    if (b) { EnterCriticalSection(&s_cs); s_open[b] = movie; LeaveCriticalSection(&s_cs); }
    if (b && ad && IsIn(ad->frontendMovies, movie)) DevFrontendMovie(true);
    return b;
}
void __stdcall hk_BinkClose(void* b) {
    std::string movie;
    EnterCriticalSection(&s_cs);
    auto it = s_open.find(b);
    if (it != s_open.end()) { movie = it->second; s_open.erase(it); }
    LeaveCriticalSection(&s_cs);
    o_BinkClose(b);
    if (!movie.empty()) {
        LOGI("movies: BinkClose %s", movie.c_str());
        TlMark("movie_close", movie);
        const DevAdapter* ad = Adapter().dev;
        if (ad && IsIn(ad->frontendMovies, movie)) DevFrontendMovie(false);
    }
}

bool s_deferred = false;
void Hook(HMODULE m, const char* dll, const char* fn, void* det, void** orig) { if (IatHook(m, dll, fn, det, orig) < 0) s_deferred = true; }
void InstallHooks() {
    s_deferred = false;
    HMODULE exe = GetModuleHandleW(nullptr);
    const char* k32 = "KERNEL32.dll";
    if (s_fileRules || Dk().logFiles) {
        Hook(exe, k32, "CreateFileW", (void*)hk_CreateFileW, (void**)&o_CreateFileW);
        Hook(exe, k32, "CreateFileA", (void*)hk_CreateFileA, (void**)&o_CreateFileA);
        Hook(exe, k32, "GetFileAttributesW", (void*)hk_GetFileAttributesW, (void**)&o_GetFileAttributesW);
        Hook(exe, k32, "GetFileAttributesExW", (void*)hk_GetFileAttributesExW, (void**)&o_GetFileAttributesExW);
        Hook(exe, k32, "GetFileAttributesExA", (void*)hk_GetFileAttributesExA, (void**)&o_GetFileAttributesExA);
    }
    if (s_addRules || Dk().logFiles) {
        Hook(exe, k32, "FindFirstFileExW", (void*)hk_FindFirstFileExW, (void**)&o_FindFirstFileExW);
        Hook(exe, k32, "FindFirstFileW", (void*)hk_FindFirstFileW, (void**)&o_FindFirstFileW);
        Hook(exe, k32, "FindNextFileW", (void*)hk_FindNextFileW, (void**)&o_FindNextFileW);
        Hook(exe, k32, "FindClose", (void*)hk_FindClose, (void**)&o_FindClose);
    }
    // a slot the exe does not import (or not hooked) keeps a null original: never call through it
    if (!o_CreateFileW) o_CreateFileW = CreateFileW;
    if (!o_CreateFileA) o_CreateFileA = CreateFileA;
    if (!o_GetFileAttributesW) o_GetFileAttributesW = GetFileAttributesW;
    if (!o_GetFileAttributesExW) o_GetFileAttributesExW = GetFileAttributesExW;
    if (!o_GetFileAttributesExA) o_GetFileAttributesExA = GetFileAttributesExA;
    if (!o_FindFirstFileExW) o_FindFirstFileExW = FindFirstFileExW;
    if (!o_FindFirstFileW) o_FindFirstFileW = FindFirstFileW;
    if (!o_FindNextFileW) o_FindNextFileW = FindNextFileW;
    if (!o_FindClose) o_FindClose = FindClose;
    // Bink: the exe imports binkw32 statically, so its IAT slots exist already; hooked now, before any movie
    Hook(exe, "binkw32.dll", "_BinkOpen@8", (void*)hk_BinkOpen, (void**)&o_BinkOpen);
    Hook(exe, "binkw32.dll", "_BinkClose@4", (void*)hk_BinkClose, (void**)&o_BinkClose);
}

} // namespace

void FilesInit(std::vector<FileRule> rules) {
    InitializeCriticalSection(&s_cs);
    s_gameLower = NormPath(Rt().gameDir);
    s_rules = std::move(rules);
    for (const auto& r : s_rules) {
        if (r.space == RuleSpace::File) s_fileRules = true; else s_movieRules = true;
        if (r.act == RuleAct::Add) s_addRules = true;
        LOGI("redirect: rule %s %s %ls%s%s%ls (%s)", r.space == RuleSpace::Movie ? "movie" : "file",
             r.act == RuleAct::Fail ? "fail" : r.act == RuleAct::Add ? "add" : "redirect", r.from.c_str(), r.prefix ? "*" : "",
             r.to.empty() ? "" : " -> ", r.to.c_str(), r.origin.c_str());
    }
    if (Dk().logFiles) {
        const std::wstring p = Rt().modDir + L"logs\\files.log";
        MoveFileExW(p.c_str(), (Rt().modDir + L"logs\\files.prev.log").c_str(), MOVEFILE_REPLACE_EXISTING);
        s_survey = CreateFileW(p.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        const char* hdr = "utc\tapi\tredirect\taccess_or_attr\tdisposition\tresult\terror\tpath\r\n";
        DWORD wr; if (s_survey != INVALID_HANDLE_VALUE) WriteFile(s_survey, hdr, (DWORD)strlen(hdr), &wr, nullptr);
        LOGI("files: survey of every distinct path into %ls", p.c_str());
    }
    InstallHooks();
    if (!o_BinkClose) LOGW("movies: no BinkClose slot: movie close times are not in the timeline");
}

void FilesMapReset() {
    EnterCriticalSection(&s_cs);
    s_lastMap.clear(); s_mapEpoch = GetTickCount64();
    LeaveCriticalSection(&s_cs);
}

void FilesOnDirect3DCreate() {   // the exe is running its own code: every IAT slot is snapped; slots deferred at DllMain go in now
    if (!s_deferred) return;
    LOGI("hook: second pass at the first Direct3DCreate9 for the slots deferred at start-up");
    InstallHooks();
}

bool FilesVanillaEntry(const std::string& lowerPath, std::string& bytes, std::string& err) {
    EnterCriticalSection(&s_cs); ReadPacks(); LeaveCriticalSection(&s_cs);
    std::string key = lowerPath;
    for (char& c : key) { if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a'); if (c == '/') c = '\\'; }
    for (size_t i = s_packs.size(); i-- > 0;) {   // the last real pack in listing order that holds it
        if (const PackEntry* e = PackFind(s_packs[i].idx, key)) {
            if (!ReadFileBytes(s_packs[i].path, bytes, e->offset, e->size)) { err = "read failed: " + Narrow(s_packs[i].path); return false; }
            return true;
        }
    }
    err = "no real pack holds " + key;
    return false;
}

int FilesMoviesSkipped() { return (int)s_skipped; }
int FilesMoviesOpened() { return (int)s_opened; }

} // namespace wsp
