#pragma once
// Dev control: pure core (no Windows headers; host tests in proxy/tests/test_dev.cpp). Drivers: dev.cpp (state file, control
// channel, autostart, reset), luabridge.cpp (the engine's Lua side), timeline.cpp.
//   - UTC formatting and JSON escaping
//   - the phase timeline (one per launch: logs\timeline.json)
//   - the scene tracker (intro | frontend | loading | campaign | battle_deploy | battle | naval), fed by the Lua pumps, the battle
//     probe, load requests and the movie events; ported from empire-remastered rml_mod/src/devspeed.cpp ComputeScene
//   - the control channel grammar: request ids, verbs, autostart/reset targets, the result JSON, stale requests, the peek probe
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "capture.h"
#include "ui_core.h"
#include "gesture_feed.h"

namespace wsp {

// Which dev threads a config needs (W33, C29). They start at the first Direct3DCreate9, never in DllMain (dev.cpp DevOnDirect3DCreate).
// The state thread clocks the two outputs that need a clock: state.json (dev.state_json, twice a second) and the timeline's
// loading_started / scene_ready marks (dev.timeline: a scene leaves a context only when its pumps stop, kPumpFresh, which only a clocked
// UpdateSceneLocked sees). The ctl thread serves dev.ctl and runs the config autostart. Every other dev key is a hook, or is reached
// through ctl and computes the scene on demand (SceneNow), so it starts no thread.
struct DevThreads { bool state = false, ctl = false; };
inline DevThreads DevThreadsFor(bool stateJson, bool timeline, bool ctl, bool autostart) {
    DevThreads t; t.state = stateJson || timeline; t.ctl = ctl || autostart; return t;
}

inline std::string TrimS2(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && (s[a] == ' ' || s[a] == '\t')) ++a;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t')) --b;
    return s.substr(a, b - a);
}
inline std::vector<std::string> SplitBar(const std::string& s) {
    std::vector<std::string> v; std::string cur;
    for (char c : s) { if (c == '|') { if (!cur.empty()) v.push_back(cur); cur.clear(); } else cur += c; }
    if (!cur.empty()) v.push_back(cur);
    return v;
}

// ---- UTC and JSON ---------------------------------------------------------------------------------------------------------
inline void CivilFromDays(int64_t z, int& y, unsigned& m, unsigned& d) {   // Howard Hinnant's algorithm, days since 1970-01-01
    z += 719468;
    const int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    const unsigned doe = (unsigned)(z - era * 146097);
    const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    y = (int)(yoe + era * 400);
    const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const unsigned mp = (5 * doy + 2) / 153;
    d = doy - (153 * mp + 2) / 5 + 1;
    m = mp < 10 ? mp + 3 : mp - 9;
    if (m <= 2) ++y;
}
inline std::string UtcIso(int64_t unixMs) {   // 2026-10-29T08:01:02.345Z
    if (unixMs < 0) return "";
    int64_t days = unixMs / 86400000; int64_t rem = unixMs % 86400000;
    int y; unsigned mo, d; CivilFromDays(days, y, mo, d);
    char b[40];
    snprintf(b, sizeof b, "%04d-%02u-%02uT%02d:%02d:%02d.%03dZ", y, mo, d, (int)(rem / 3600000), (int)(rem / 60000 % 60), (int)(rem / 1000 % 60), (int)(rem % 1000));
    return b;
}
inline std::string JsonEsc(const std::string& s) {
    std::string o; o.reserve(s.size() + 8);
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
        else if (c == '\n') o += "\\n";
        else if (c == '\r') o += "\\r";
        else if (c == '\t') o += "\\t";
        else if (c < 32) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); o += b; }
        else o += (char)c;
    }
    return o;
}
inline std::string JStr(const std::string& s) { return "\"" + JsonEsc(s) + "\""; }

// ---- phase timeline -------------------------------------------------------------------------------------------------------
struct PhaseMark { std::string phase, detail; int64_t utcMs; };
struct Timeline {
    std::string launchId;
    int64_t processStartMs = -1;   // from the OS (process creation time)
    std::vector<PhaseMark> marks;
    static const size_t kMax = 400;
    bool Add(const std::string& phase, const std::string& detail, int64_t utcMs) {
        if (marks.size() >= kMax) return false;
        marks.push_back({ phase, detail, utcMs });
        return true;
    }
    bool Has(const std::string& phase) const { for (const auto& m : marks) if (m.phase == phase) return true; return false; }
    std::string Json() const {
        std::string j = "{\n  \"launch_id\": " + JStr(launchId) + ",\n  \"process_start_utc\": " + JStr(UtcIso(processStartMs)) +
                        ",\n  \"phases\": [";
        for (size_t i = 0; i < marks.size(); ++i) {
            const auto& m = marks[i];
            char t[32]; snprintf(t, sizeof t, "%lld", (long long)(processStartMs >= 0 ? m.utcMs - processStartMs : -1));
            j += std::string(i ? ",\n" : "\n") + "    {\"phase\": " + JStr(m.phase) + ", \"utc\": " + JStr(UtcIso(m.utcMs)) + ", \"t_ms\": " + t +
                 (m.detail.empty() ? std::string() : ", \"detail\": " + JStr(m.detail)) + "}";
        }
        j += "\n  ]\n}\n";
        return j;
    }
};

// ---- scenes ---------------------------------------------------------------------------------------------------------------
inline const char* const* SceneNames() {
    static const char* const n[] = { "intro", "frontend", "loading", "campaign", "battle_deploy", "battle", "naval", nullptr };
    return n;
}
inline bool IsSceneName(const std::string& s) { for (const char* const* p = SceneNames(); *p; ++p) if (s == *p) return true; return false; }

// Times are seconds on one monotonic clock. Not thread-safe: the driver holds a lock.
struct SceneTracker {
    static constexpr double kPumpFresh = 1.5;     // a context whose pumps stopped for longer reads as not live
    static constexpr double kBattleFresh = 3.0;   // battle probe reports older than this are ignored
    std::string ctx;                              // last pumping context: frontend | campaign | battle ("" = no Lua seen)
    double lastPump = -1, ctxSince = -1;
    bool frontendSeen = false;                    // a front-end pump, or the front-end background movie opened
    bool frontendMovieOpen = false, frontendMovieSeen = false;
    std::string loadTarget;                       // a requested load (autostart, reset) not reached yet: "" none
    int naval = -1, deployPanel = -1; double battleT = -1;
    std::string scene = "intro"; double sceneSince = 0;

    void OnPump(const std::string& c, double now) {
        if (c != ctx) { ctx = c; ctxSince = now; }
        lastPump = now;
        if (c == "frontend") frontendSeen = true;
        if (!loadTarget.empty() && (loadTarget == c)) loadTarget.clear();
    }
    // The front end's background movie opening means the front end is up, whatever pumped last (after a battle the front end may
    // come back on a screen that does not pump: run 20261029_j3pc).
    void OnFrontendMovie(bool open, double) {
        frontendMovieOpen = open;
        if (!open) return;
        frontendMovieSeen = true; frontendSeen = true;
        if (ctx != "frontend") { ctx = "frontend"; lastPump = -1; }
        if (loadTarget == "frontend") loadTarget.clear();
    }
    void OnLoadRequested(const std::string& targetCtx) { loadTarget = targetCtx; }
    void OnBattleState(int nav, int deploy, double now) { naval = nav; deployPanel = deploy; battleT = now; }

    std::string Compute(double now) const {
        if (!frontendSeen) return "intro";
        const bool fresh = lastPump >= 0 && now - lastPump < kPumpFresh;
        if (fresh && loadTarget.empty()) {
            if (ctx == "battle") {
                if (battleT >= 0 && now - battleT < kBattleFresh) {
                    if (naval == 1) return "naval";
                    if (deployPanel == 1) return "battle_deploy";
                }
                return "battle";
            }
            if (ctx == "campaign" || ctx == "frontend") return ctx;
        }
        if (fresh && !loadTarget.empty() && ctx != loadTarget && ctx == "frontend") return "loading";   // asked to leave the front end
        if (!loadTarget.empty()) return "loading";
        if (ctx == "campaign" || ctx == "battle") return "loading";
        if (ctx.empty() || ctx == "frontend") {
            // no live pump: the front end's sub-screens do not pump; the background movie closing means the front end is gone
            if (frontendMovieSeen && !frontendMovieOpen) return "loading";
            return "frontend";
        }
        return "loading";
    }
    // returns true when the scene changed (the driver logs and timelines it)
    bool Update(double now, std::string* from = nullptr) {
        const std::string s = Compute(now);
        if (s == scene) return false;
        if (from) *from = scene;
        scene = s; sceneSince = now;
        return true;
    }
};

// ---- control channel --------------------------------------------------------------------------------------------------------
// Request <dir>\<id>.cmd (one line: verb and arguments, UTF-8/ASCII); result <dir>\<id>.done (JSON, written last). Ids: 1-64 of
// [A-Za-z0-9._-], not starting with '.' or '_', never reused (the proxy refuses an id it has seen or whose .done exists).
inline bool ValidCtlId(const std::string& id) {
    if (id.empty() || id.size() > 64 || id[0] == '.' || id[0] == '_') return false;
    for (char c : id) if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-')) return false;
    return true;
}

struct Target {   // autostart / reset target
    std::string kind;           // frontend | campaign | battle
    std::string mode;           // campaign: new | continue | save; battle: the preset name
    std::string campaign, faction, save, preset;
    std::string error;
    std::string Ctx() const { return kind; }   // the Lua context that means "arrived"
};
inline std::vector<std::string> SplitColon(const std::string& s) {
    std::vector<std::string> v; std::string cur;
    for (char c : s) { if (c == ':') { v.push_back(cur); cur.clear(); } else cur += c; }
    v.push_back(cur);
    return v;
}
inline bool SafeToken(const std::string& s) {   // names that go into Lua strings and file names
    if (s.empty() || s.size() > 80) return false;
    for (char c : s) if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.' || c == ' ')) return false;
    return s[0] != '.' && s[0] != ' ';
}
//   frontend | campaign:new:<campaign>:<faction> | campaign:continue | campaign:<save> | battle:<preset>
inline Target ParseTarget(const std::string& t) {
    Target r;
    const std::vector<std::string> p = SplitColon(t);
    if (t == "frontend") { r.kind = "frontend"; return r; }
    if (p[0] == "campaign") {
        r.kind = "campaign";
        if (p.size() == 4 && p[1] == "new") {
            r.mode = "new"; r.campaign = p[2]; r.faction = p[3];
            if (!SafeToken(r.campaign) || !SafeToken(r.faction)) r.error = "campaign:new:<campaign>:<faction> needs two plain names";
            return r;
        }
        if (p.size() == 2 && p[1] == "continue") { r.mode = "continue"; return r; }
        if (p.size() == 2 && p[1] != "new") { r.mode = "save"; r.save = p[1]; if (!SafeToken(r.save)) r.error = "bad save name '" + p[1] + "'"; return r; }
        r.error = "campaign target is campaign:new:<campaign>:<faction>, campaign:continue or campaign:<save>";
        return r;
    }
    if (p[0] == "battle") {
        r.kind = "battle";
        if (p.size() == 2 && SafeToken(p[1])) { r.mode = r.preset = p[1]; return r; }
        r.error = "battle target is battle:<preset>";
        return r;
    }
    r.error = "unknown target '" + t + "' (frontend | campaign:... | battle:<preset>)";
    return r;
}

// Frame-time statistics of a perf capture (J4): deltas in milliseconds between consecutive presents. Nearest-rank percentiles.
struct FrameStats { size_t frames = 0; double p50 = 0, p99 = 0, max = 0, mean = 0; };
// Milliseconds from a QPC tick delta: only the (small) delta becomes floating point, so the result keeps its precision even when the
// thread's x87 FPU runs at 24 bits (D3D9's default; J44). Never form an absolute time in ms as a double first.
inline double PerfDeltaMs(int64_t ticks, int64_t freq) {
    if (freq <= 0 || ticks < 0) return 0.0;
    const int64_t whole = ticks / freq, rest = ticks % freq;
    return 1000.0 * (double)whole + 1000.0 * (double)rest / (double)freq;
}

inline FrameStats ComputeFrameStats(std::vector<double> d) {
    FrameStats s; s.frames = d.size();
    if (d.empty()) return s;
    std::sort(d.begin(), d.end());
    auto rank = [&](double p) { size_t i = (size_t)(p * (double)d.size() + 0.999999); if (i < 1) i = 1; if (i > d.size()) i = d.size(); return d[i - 1]; };
    s.p50 = rank(0.50); s.p99 = rank(0.99); s.max = d.back();
    double sum = 0; for (double x : d) sum += x;
    s.mean = sum / (double)d.size();
    return s;
}

// ---- stale requests (W17, B40) --------------------------------------------------------------------------------------------
// A request whose file was last written before this process was created comes from an earlier launch (a driver killed while it
// waited leaves its .cmd behind): it is taken and refused, never run. No slack: process creation precedes the DLL's load, and no
// core driver writes a request before its launch returns. An unknown start (< 0, GetProcessTimes failed) accepts everything.
inline bool CtlStale(int64_t writeUnixMs, int64_t processStartMs) { return processStartMs >= 0 && writeUnixMs < processStartMs; }
inline std::string CtlStaleReason(int64_t writeUnixMs, int64_t processStartMs) {
    return "stale: written " + UtcIso(writeUnixMs) + ", before this launch started " + UtcIso(processStartMs) + ": a request from an earlier launch (resend it)";
}

// ---- peek (W17, B25): a read-only probe from an accepted engine site ------------------------------------------------------
//   peek <site>[+|-<off>] [*[+|-<off>] ...] <len>
// <site> an engine_sites id (letters, digits, ._:/#-; never a number: no raw address is accepted), its address the patch engine's
// checked one (SiteAddress: rva + anchor). <off> decimal or 0x hex. A '-' may be part of an id: the offset is the number after the
// last '+' or '-' (write +0 to keep a trailing -<n> in the id). Each `*` reads the 4-byte pointer at the current address, refuses a
// null one, then adds its offset; at most 8. <len> 1 to 512 bytes. All arithmetic is 32-bit and wraps.
struct PeekArgs { std::string site; int64_t siteOff = 0; std::vector<int64_t> hops; uint32_t len = 0; std::string error; };
inline const char* PeekGrammar() { return "peek <site>[+|-<off>] [*[+|-<off>] ...] <len>"; }
inline bool ParsePeekNum(const std::string& s, uint64_t& v) {   // decimal or 0x hex, at most 0xffffffff
    v = 0;
    const bool hex = s.size() > 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X');
    const size_t from = hex ? 2 : 0;
    if (s.size() <= from || s.size() - from > (hex ? 8u : 10u)) return false;
    for (size_t i = from; i < s.size(); ++i) {
        const char c = s[i]; int d;
        if (c >= '0' && c <= '9') d = c - '0';
        else if (hex && c >= 'a' && c <= 'f') d = c - 'a' + 10;
        else if (hex && c >= 'A' && c <= 'F') d = c - 'A' + 10;
        else return false;
        v = v * (hex ? 16 : 10) + (uint64_t)d;
    }
    return v <= 0xffffffffull;
}
inline bool ParsePeekOff(const std::string& s, int64_t& off) {   // "" (0), "+N", "-N"
    off = 0;
    if (s.empty()) return true;
    uint64_t v = 0;
    if ((s[0] != '+' && s[0] != '-') || !ParsePeekNum(s.substr(1), v)) return false;
    off = s[0] == '-' ? -(int64_t)v : (int64_t)v;
    return true;
}
inline bool PeekSiteId(const std::string& s) {
    if (s.empty() || s.size() > 120 || !((s[0] >= 'a' && s[0] <= 'z') || (s[0] >= 'A' && s[0] <= 'Z') || (s[0] >= '0' && s[0] <= '9'))) return false;
    for (char c : s)
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '_' || c == ':' || c == '/' || c == '#' || c == '-')) return false;
    return true;
}
inline PeekArgs ParsePeekArgs(const std::string& arg) {
    PeekArgs a;
    std::vector<std::string> t; std::string cur;
    for (char c : arg) { if (c == ' ' || c == '\t') { if (!cur.empty()) t.push_back(cur); cur.clear(); } else cur += c; }
    if (!cur.empty()) t.push_back(cur);
    if (t.size() < 2) { a.error = std::string("peek needs ") + PeekGrammar(); return a; }
    uint64_t n = 0;
    if (!ParsePeekNum(t.back(), n) || n < 1 || n > 512) { a.error = "peek: the length is 1 to 512 bytes (got '" + t.back() + "'; " + PeekGrammar() + ")"; return a; }
    a.len = (uint32_t)n;
    // the site and its offset
    std::string site = t[0];
    const size_t k = site.find_last_of("+-");
    if (k != std::string::npos && k > 0) {
        int64_t off = 0;
        if (ParsePeekOff(site.substr(k), off)) { a.siteOff = off; site = site.substr(0, k); }
        else if (site[k] == '+') { a.error = "peek: bad offset '" + site.substr(k) + "' (decimal or 0x hex)"; return a; }
    }
    if (ParsePeekNum(site, n)) { a.error = "peek reads from an engine site, never a raw address ('" + site + "'): " + PeekGrammar(); return a; }
    if (!PeekSiteId(site)) { a.error = "peek: bad site id '" + site + "' (an engine_sites id: letters, digits, ._:/#-)"; return a; }
    a.site = site;
    for (size_t i = 1; i + 1 < t.size(); ++i) {
        int64_t off = 0;
        if (t[i][0] != '*' || !ParsePeekOff(t[i].substr(1), off)) { a.error = "peek: bad hop '" + t[i] + "' (*, *+<off> or *-<off>; " + PeekGrammar() + ")"; return a; }
        a.hops.push_back(off);
    }
    if (a.hops.size() > 8) { a.error = "peek: at most 8 * hops (got " + std::to_string(a.hops.size()) + ")"; return a; }
    return a;
}
inline std::string Hex32(uint32_t v) { char b[16]; snprintf(b, sizeof b, "0x%08x", v); return b; }
struct PeekHop { uint32_t at = 0, ptr = 0; };
struct PeekPath {
    std::vector<PeekHop> hops;   // every pointer read, in order (a failed null read included)
    uint32_t addr = 0;           // the final address (or where the resolution stopped)
    int failedHop = 0;           // 1-based hop that stopped it, 0 = none
    std::string error;
};
// readU32(uint32_t at, uint32_t& out) -> bool: false = not readable. The final range's readability is the driver's check.
template <class ReadU32>
PeekPath ResolvePeek(uint32_t siteAddr, const PeekArgs& a, ReadU32 readU32) {
    PeekPath p;
    uint32_t cur = siteAddr + (uint32_t)a.siteOff;
    for (size_t i = 0; i < a.hops.size(); ++i) {
        const std::string hop = "hop " + std::to_string(i + 1) + " of " + std::to_string(a.hops.size());
        uint32_t v = 0;
        if (!readU32(cur, v)) { p.addr = cur; p.failedHop = (int)i + 1; p.error = hop + ": the pointer at " + Hex32(cur) + " is not readable"; return p; }
        p.hops.push_back({ cur, v });
        if (!v) { p.addr = cur; p.failedHop = (int)i + 1; p.error = hop + ": null pointer at " + Hex32(cur); return p; }
        cur = v + (uint32_t)a.hops[i];
    }
    p.addr = cur;
    if ((uint64_t)cur + a.len > 0x100000000ull) p.error = "the range " + Hex32(cur) + " + " + std::to_string(a.len) + " wraps past 4 GB";
    return p;
}
// The result's members (ctl .done): bytes = the len bytes read, or nullptr when nothing was read (a stopped resolution).
inline std::string PeekResultJson(const std::string& site, uint32_t siteAddr, const PeekPath& p, uint32_t len, const uint8_t* bytes) {
    std::string j = "\"site\": " + JStr(site) + ", \"site_addr\": " + JStr(Hex32(siteAddr)) + ", \"hops\": [";
    for (size_t i = 0; i < p.hops.size(); ++i) j += std::string(i ? ", " : "") + "{\"at\": " + JStr(Hex32(p.hops[i].at)) + ", \"ptr\": " + JStr(Hex32(p.hops[i].ptr)) + "}";
    j += "], \"addr\": " + JStr(Hex32(p.addr)) + ", \"len\": " + std::to_string(len);
    if (p.failedHop) j += ", \"failed_hop\": " + std::to_string(p.failedHop);
    if (!bytes) return j;
    std::string hex; char b[40];
    for (uint32_t i = 0; i < len; ++i) { snprintf(b, sizeof b, i ? " %02x" : "%02x", bytes[i]); hex += b; }
    j += ", \"hex\": " + JStr(hex);
    if (len >= 4) {   // the whole dwords, little-endian
        std::string u = ", \"u32\": [", f = ", \"f32\": [";
        for (uint32_t i = 0; i + 4 <= len; i += 4) {
            uint32_t v; memcpy(&v, bytes + i, 4);
            float x; memcpy(&x, bytes + i, 4);
            const char* sep = i ? ", " : "";
            u += sep + std::to_string(v);
            if (std::isnan(x)) snprintf(b, sizeof b, "\"nan\"");
            else if (std::isinf(x)) snprintf(b, sizeof b, x > 0 ? "\"inf\"" : "\"-inf\"");
            else snprintf(b, sizeof b, "%.9g", (double)x);
            f += sep; f += b;
        }
        j += u + "]" + f + "]";
    }
    return j;
}

struct CtlRequest {
    std::string verb, arg;     // arg = the rest of the line (log text, file, scenes, target)
    double timeoutS = 0;       // 0 = the verb's default
    std::string error;         // set = refuse with this reason
    Target target;             // autostart / reset
    std::vector<std::string> scenes;   // waitfor
    std::string luaArgs;       // lua: the text after " -- ", read by the chunk as wsp.dev_config("lua_args") (J4)
};
inline const char* CtlVerbs() { return "ping, state, log <text>, lua <file> [timeout_s] [-- args], perf <seconds>, waitfor <scene>[|<scene>] [timeout_s], autostart <target> [timeout_s], reset <target> [timeout_s], console <line>|status|on|off, capture <name> [frames], ui show|hide|reload|scale|click|wheel|dump|state ..., gesture press|move|release|cancel|plan|info ..., peek <site>[+|-<off>] [*[+|-<off>] ...] <len>, exit"; }
inline double CtlDefaultTimeout(const std::string& verb) {
    return verb == "lua" || verb == "console" ? 30 : verb == "perf" ? 70 : verb == "capture" ? 60 : verb == "ui" || verb == "gesture" ? 30 : verb == "waitfor" ? 180 : (verb == "autostart" || verb == "reset") ? 240 : 10;
}

inline bool ParseTrailingTimeout(std::string& rest, double& t) {   // "x y 30" -> rest "x y", t 30; false when no number at the end
    const size_t sp = rest.find_last_of(' ');
    if (sp == std::string::npos) return false;
    const std::string tail = rest.substr(sp + 1);
    if (tail.empty()) return false;
    for (char c : tail) if (!((c >= '0' && c <= '9') || c == '.')) return false;
    t = atof(tail.c_str());
    rest = TrimS2(rest.substr(0, sp));
    return true;
}

inline CtlRequest ParseCtl(const std::string& lineIn) {
    CtlRequest r;
    std::string line = lineIn;
    const size_t nl = line.find_first_of("\r\n"); if (nl != std::string::npos) line = line.substr(0, nl);
    if (line.size() >= 3 && (unsigned char)line[0] == 0xEF && (unsigned char)line[1] == 0xBB && (unsigned char)line[2] == 0xBF) line = line.substr(3);
    line = TrimS2(line);
    const size_t sp = line.find(' ');
    r.verb = line.substr(0, sp);
    r.arg = sp == std::string::npos ? "" : TrimS2(line.substr(sp + 1));
    const std::string& v = r.verb;
    if (v.empty()) { r.error = "empty request (verbs: " + std::string(CtlVerbs()) + ")"; return r; }
    if (v == "ping" || v == "state" || v == "exit") { if (!r.arg.empty()) r.error = v + " takes no argument"; return r; }
    if (v == "log") { if (r.arg.empty()) r.error = "log needs a text"; return r; }
    if (v == "perf") {   // perf <seconds>: 1..60, the frame-time and memory capture (J4, dev.perf)
        double s = 0; bool digits = !r.arg.empty();
        for (char c : r.arg) if (!((c >= '0' && c <= '9') || c == '.')) digits = false;
        if (digits) s = atof(r.arg.c_str());
        if (!digits || s < 1 || s > 60) { r.error = "perf needs a duration of 1 to 60 seconds"; return r; }
        r.timeoutS = s + 10; r.arg = std::to_string((int)s);
        return r;
    }
    if (v == "lua") {
        const size_t dd = r.arg.find(" -- ");
        if (dd != std::string::npos) { r.luaArgs = TrimS2(r.arg.substr(dd + 4)); r.arg = TrimS2(r.arg.substr(0, dd)); }
        else if (r.arg.size() >= 3 && r.arg.compare(r.arg.size() - 3, 3, " --") == 0) r.arg = TrimS2(r.arg.substr(0, r.arg.size() - 3));   // empty args (J43)
        ParseTrailingTimeout(r.arg, r.timeoutS);
        if (r.arg.empty()) r.error = "lua needs a file (relative to the game folder or absolute)";
        else if (r.arg.find('"') != std::string::npos || r.arg.find('\n') != std::string::npos) r.error = "bad file name";
        return r;
    }
    if (v == "waitfor") {
        ParseTrailingTimeout(r.arg, r.timeoutS);
        for (const std::string& s : SplitBar(r.arg)) {
            if (!IsSceneName(s)) { r.error = "waitfor: unknown scene '" + s + "' (intro frontend loading campaign battle_deploy battle naval)"; return r; }
            r.scenes.push_back(s);
        }
        if (r.scenes.empty()) r.error = "waitfor needs a scene";
        return r;
    }
    if (v == "autostart" || v == "reset") {
        ParseTrailingTimeout(r.arg, r.timeoutS);
        r.target = ParseTarget(r.arg);
        if (!r.target.error.empty()) r.error = v + ": " + r.target.error;
        return r;
    }
    if (v == "console") {   // the line itself is checked by ParseConsoleLine (console.h); no trailing timeout: numbers are arguments
        if (r.arg.empty()) r.error = "console needs a command line or status|on|off";
        return r;
    }
    if (v == "capture") {   // capture <name> [frames] (J8): the name and count rules are capture.h ParseCaptureArgs; no trailing timeout
        const CaptureArgs a = ParseCaptureArgs(r.arg);
        if (!a.error.empty()) r.error = a.error;
        else r.timeoutS = 30 + 5.0 * a.frames;
        return r;
    }
    if (v == "ui") {   // the RmlUi host (J30): grammar in ui_core.h ParseUiArgs; `ui state <s>` waits s seconds; no trailing timeout
        const UiArgs a = ParseUiArgs(r.arg);
        if (!a.error.empty()) r.error = a.error;
        else r.timeoutS = 30 + a.seconds;
        return r;
    }
    if (v == "gesture") {   // the gesture layer (W6): grammar in gesture_feed.h ParseGestureArgs; no trailing timeout (numbers are pixels)
        const gest::GestureArgs a = gest::ParseGestureArgs(r.arg);
        if (!a.error.empty()) r.error = a.error;
        return r;
    }
    if (v == "peek") {   // the read-only probe (W17): grammar above (ParsePeekArgs); default timeout 10 s, no trailing timeout (numbers are offsets)
        const PeekArgs a = ParsePeekArgs(r.arg);
        if (!a.error.empty()) r.error = a.error;
        return r;
    }
    r.error = "unknown verb '" + v + "' (verbs: " + std::string(CtlVerbs()) + ")";
    return r;
}


} // namespace wsp
