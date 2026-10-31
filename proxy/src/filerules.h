#pragma once
// File-redirection rules: pure core (no Windows headers; host tests in proxy/tests/test_dev.cpp). The in-process driver is files.cpp.
// Design ported from empire-remastered rml_mod/src/devspeed.cpp (FILE REDIRECTION), re-checked on each game by the file survey.
//
// A rule matches a path RELATIVE TO THE GAME FOLDER, lower case, '\' separators (a '/' in a rule or a path counts as '\');
// a trailing '*' makes it a prefix rule. One rule per line, '#' or ';' starts a comment:
//     redirect data\ui\x.lua -> <mod>\lua\x.lua    a read-only open of the left path opens the right one
//     fail     data\some\file.ext                               the open fails with ERROR_FILE_NOT_FOUND
//     add      data\zz_dev.pack -> <mod>\packs\dev.pack   a virtual file: listed by FindFirstFile/FindNextFile in its
//                                                                folder, opened (and its attributes read) from the target
//     movie-fail     movies\intro.bik                           Bink level, matched against the PACK ENTRY name of the movie
//     movie-redirect movies\a.bik -> <mod>\dev\tiny.bik
// Targets are relative to the game folder unless absolute. Only read-only opens (no write access, OPEN_EXISTING) are redirected;
// a missing target leaves the vanilla file in place (warned once). Rules are tried in file order; the first match wins.
#include <string>
#include <vector>

namespace wsp {

enum class RuleSpace { File, Movie };
enum class RuleAct { Redirect, Fail, Add };

struct FileRule {
    RuleSpace space = RuleSpace::File;
    RuleAct act = RuleAct::Redirect;
    std::wstring from;      // normalised (NormRel), without the trailing '*'
    bool prefix = false;
    std::wstring to;        // as written, '\' separators
    std::string origin;     // "rules line 3" | "dev.skip_intro" | ...
    bool hit = false, warned = false;
};

inline wchar_t LowerW(wchar_t c) { return (c >= L'A' && c <= L'Z') ? (wchar_t)(c - L'A' + L'a') : (c == L'/' ? L'\\' : c); }

inline std::wstring NormPath(const std::wstring& s) {
    std::wstring o; o.reserve(s.size());
    for (wchar_t c : s) o += LowerW(c);
    return o;
}
inline bool IsAbsolute(const std::wstring& p) {
    return p.size() > 2 && (p[1] == L':' || (p[0] == L'\\' && p[1] == L'\\') || (p[0] == L'/' && p[1] == L'/'));
}
// path relative to the game folder (lower case, '\'); "" when it is outside the folder. gameLower = NormPath(game folder) with
// a trailing '\'. A relative path is relative to the working folder, which the engine keeps at the game folder.
inline std::wstring RelToGame(const std::wstring& path, const std::wstring& gameLower) {
    if (path.empty()) return L"";
    std::wstring p = NormPath(path);
    if (p.rfind(L"\\\\?\\", 0) == 0) p = p.substr(4);
    if (!IsAbsolute(p)) {
        while (p.rfind(L".\\", 0) == 0) p = p.substr(2);
        return p;
    }
    if (!gameLower.empty() && p.rfind(gameLower, 0) == 0) return p.substr(gameLower.size());
    return L"";
}

inline std::wstring Widen8(const std::string& s) { std::wstring w; for (unsigned char c : s) w += (wchar_t)c; return w; }   // ASCII/latin-1 rules
inline std::string TrimS(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && (s[a] == ' ' || s[a] == '\t' || s[a] == '\r' || s[a] == '\n')) ++a;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t' || s[b - 1] == '\r' || s[b - 1] == '\n')) --b;
    return s.substr(a, b - a);
}

inline FileRule MakeRule(RuleSpace sp, RuleAct act, std::string from, std::string to, const std::string& origin) {
    FileRule r; r.space = sp; r.act = act; r.origin = origin;
    from = TrimS(from); to = TrimS(to);
    r.prefix = !from.empty() && from.back() == '*';
    if (r.prefix) from.pop_back();
    r.from = NormPath(Widen8(from));
    while (r.from.rfind(L".\\", 0) == 0) r.from = r.from.substr(2);
    r.to = Widen8(to);
    for (auto& c : r.to) if (c == L'/') c = L'\\';
    return r;
}

// Parses a rule file; bad lines go to warnings ("line N: ...") and are skipped.
inline std::vector<FileRule> ParseRules(const std::string& text, std::vector<std::string>& warnings) {
    std::vector<FileRule> out;
    size_t pos = 0; int ln = 0;
    while (pos < text.size()) {
        size_t e = text.find('\n', pos); if (e == std::string::npos) e = text.size();
        const std::string s = TrimS(text.substr(pos, e - pos)); pos = e + 1; ++ln;
        if (s.empty() || s[0] == '#' || s[0] == ';') continue;
        const size_t sp = s.find_first_of(" \t");
        if (sp == std::string::npos) { warnings.push_back("line " + std::to_string(ln) + ": no argument"); continue; }
        const std::string verb = s.substr(0, sp), rest = TrimS(s.substr(sp + 1));
        std::string from = rest, to;
        const size_t arrow = rest.find("->");
        if (arrow != std::string::npos) { from = TrimS(rest.substr(0, arrow)); to = TrimS(rest.substr(arrow + 2)); }
        const std::string origin = "rules line " + std::to_string(ln);
        const bool hasTo = !to.empty();
        if (verb == "redirect" && hasTo) out.push_back(MakeRule(RuleSpace::File, RuleAct::Redirect, from, to, origin));
        else if (verb == "fail" && !hasTo) out.push_back(MakeRule(RuleSpace::File, RuleAct::Fail, from, "", origin));
        else if (verb == "add" && hasTo) out.push_back(MakeRule(RuleSpace::File, RuleAct::Add, from, to, origin));
        else if (verb == "movie-redirect" && hasTo) out.push_back(MakeRule(RuleSpace::Movie, RuleAct::Redirect, from, to, origin));
        else if (verb == "movie-fail" && !hasTo) out.push_back(MakeRule(RuleSpace::Movie, RuleAct::Fail, from, "", origin));
        else { warnings.push_back("line " + std::to_string(ln) + ": unknown or malformed rule '" + s + "'"); continue; }
        if (out.back().from.empty()) { out.pop_back(); warnings.push_back("line " + std::to_string(ln) + ": empty path"); }
    }
    return out;
}

inline FileRule* MatchRule(std::vector<FileRule>& rules, RuleSpace space, const std::wstring& rel) {
    if (rel.empty()) return nullptr;
    for (auto& r : rules) {
        if (r.space != space) continue;
        if (r.prefix ? rel.compare(0, r.from.size(), r.from) == 0 : rel == r.from) return &r;
    }
    return nullptr;
}

// The redirect target for a matched File rule (relative targets are joined to gameDir; a prefix rule keeps the path's tail).
inline std::wstring RuleTarget(const FileRule& r, const std::wstring& rel, const std::wstring& gameDir) {
    std::wstring t = IsAbsolute(r.to) ? r.to : gameDir + r.to;
    if (r.prefix && rel.size() >= r.from.size()) t += rel.substr(r.from.size());
    return t;
}

// Write access or anything but OPEN_EXISTING: never redirected (the engine writing its own files must reach them).
inline bool IsReadOnlyOpen(unsigned long access, unsigned long disposition) {
    const unsigned long kWrite = 0x40000000UL /*GENERIC_WRITE*/ | 0x10000000UL /*GENERIC_ALL*/ | 0x2UL /*FILE_WRITE_DATA*/ | 0x4UL /*APPEND*/;
    return !(access & kWrite) && disposition == 3 /*OPEN_EXISTING*/;
}

// FindFirstFile pattern "dir\spec" relative to the game folder: does an `add` rule's virtual name match it?
inline bool WildMatch(const wchar_t* pat, const wchar_t* s) {   // '*' and '?' only, case already folded
    if (!*pat) return !*s;
    if (*pat == L'*') { for (const wchar_t* t = s;; ++t) { if (WildMatch(pat + 1, t)) return true; if (!*t) return false; } }
    if (!*s) return false;
    return (*pat == L'?' || *pat == *s) && WildMatch(pat + 1, s + 1);
}
inline void SplitDir(const std::wstring& rel, std::wstring& dir, std::wstring& name) {
    const size_t k = rel.find_last_of(L'\\');
    dir = k == std::wstring::npos ? L"" : rel.substr(0, k + 1);
    name = k == std::wstring::npos ? rel : rel.substr(k + 1);
}

} // namespace wsp
