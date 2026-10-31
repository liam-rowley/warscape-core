#pragma once
// Exe-identity guard: pure core (no Windows headers, no globals; host tests in proxy/tests/test_guard.cpp). The in-process driver
// is guard_driver.cpp. Same contract as empire-remastered rml_mod/docs/exe_guard.md, adapted (proxy/README.md "Exe-identity guard"):
//
// Evaluated ONCE in DllMain, after the config and the log and BEFORE any hook, patch or engine read. Identity = the exe FILE's
// sha1 (the exact build) + the mapped image's PE TimeDateStamp and SizeOfImage (cheap, and they catch an in-memory surprise).
//   Match      pinned, nothing differs                      -> engine features on
//   Unpinned   the adapter pins nothing                     -> PASS-THROUGH (fail closed; empire-remastered allowed it, the core does not)
//   Override   exe_guard=0 (developer)                      -> engine features on whatever differs; a warning every start
//   Mismatch   pinned and anything differs                  -> PASS-THROUGH + notice file + log line naming the first difference
//   Forced     exe_guard_force_mismatch=1 (test key)        -> the pass-through path on a matching exe (wins over exe_guard=0)
// Pass-through = the configured backend only: no hook, no patch, no engine read, ever (PlanEngine below is the one switch).
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
#include "pe.h"

namespace wsp {

// What the adapter pins (proxy/<game>/identity.json -> generated header). Empty sha1 / 0 = that part is not pinned.
struct Identity { const char* exeName; const char* sha1; uint32_t timeDateStamp; uint32_t sizeOfImage; };

struct GuardConfig { int exeGuard = 1; int forceMismatch = 0; };

enum class Verdict : uint8_t { Match, Unpinned, Override, Mismatch, Forced };
inline const char* VerdictName(Verdict v) {
    switch (v) {
    case Verdict::Match: return "match";
    case Verdict::Unpinned: return "NOT PINNED";
    case Verdict::Override: return "OVERRIDE (exe_guard=0)";
    case Verdict::Mismatch: return "MISMATCH";
    default: return "FORCED MISMATCH (exe_guard_force_mismatch=1)";
    }
}

// What the driver measured. fileSha1 empty + fileError set = the exe file could not be read (counts as a difference).
struct Observed {
    const PeInfo* mapped = nullptr;   // headers of the running image (first page)
    std::string fileSha1, fileError;
};

struct GuardResult {
    Verdict verdict = Verdict::Mismatch;
    bool engineOk = false;            // the one answer every caller needs: may the DLL hook, patch or read the engine?
    bool pinned = false;
    std::vector<std::string> diffs;   // every difference, in check order; diffs[0] is the one the log line and the notice lead with
    uint32_t timeDateStamp = 0, sizeOfImage = 0;
    std::string sha1;
};

inline GuardResult Evaluate(const Observed& o, const Identity& id, const GuardConfig& c) {
    GuardResult r; char b[240];
    r.pinned = (id.sha1 && *id.sha1) || id.timeDateStamp || id.sizeOfImage;
    r.sha1 = o.fileSha1;
    if (!o.mapped || !o.mapped->ok) r.diffs.push_back("PE headers of the running image: " + (o.mapped ? o.mapped->error : std::string("not read")));
    else if (o.mapped->machine != kMachineI386) r.diffs.push_back("the running image is not x86");
    else {
        r.timeDateStamp = o.mapped->timeDateStamp; r.sizeOfImage = o.mapped->sizeOfImage;
        if (id.timeDateStamp && r.timeDateStamp != id.timeDateStamp) {
            snprintf(b, sizeof b, "PE TimeDateStamp 0x%08x, pinned 0x%08x", (unsigned)r.timeDateStamp, (unsigned)id.timeDateStamp); r.diffs.push_back(b);
        }
        if (id.sizeOfImage && r.sizeOfImage != id.sizeOfImage) {
            snprintf(b, sizeof b, "PE SizeOfImage 0x%08x, pinned 0x%08x", (unsigned)r.sizeOfImage, (unsigned)id.sizeOfImage); r.diffs.push_back(b);
        }
    }
    if (id.sha1 && *id.sha1) {
        if (o.fileSha1.empty()) r.diffs.push_back("exe file not hashed: " + (o.fileError.empty() ? std::string("unknown error") : o.fileError));
        else if (o.fileSha1 != id.sha1) r.diffs.push_back("exe sha1 " + o.fileSha1 + ", pinned " + id.sha1);
    }
    if (c.forceMismatch) { r.verdict = Verdict::Forced; r.engineOk = false; }
    else if (!c.exeGuard) { r.verdict = Verdict::Override; r.engineOk = true; }
    else if (!r.pinned) { r.verdict = Verdict::Unpinned; r.engineOk = false; r.diffs.insert(r.diffs.begin(), "the adapter pins no exe identity"); }
    else if (!r.diffs.empty()) { r.verdict = Verdict::Mismatch; r.engineOk = false; }
    else { r.verdict = Verdict::Match; r.engineOk = true; }
    return r;
}

// THE pass-through switch (empire-remastered PlanD3DHooks, generalised). Every engine-side module asks this plan, never the verdict:
// dllmain (patch engine), proxy exports (D3D hooks), and later features. Pass-through = all false; the backend always loads.
// The skeleton has no hooks yet: the fields exist so the first feature cannot be wired around the guard (test_guard.cpp lints
// the sources for it).
struct EnginePlan {
    bool patches = false;      // runtime patch engine (engine_sites, kind=patch)
    bool engineHooks = false;  // detours of engine code (engine_sites, kind=hook)
    bool d3dHooks = false;     // vtable hooks on the backend's IDirect3D9 / device (features: overlay, controls, ...)
    bool engineReads = false;  // reads of engine memory through an engine address or layout
};
inline EnginePlan PlanEngine(bool dllEnabled, bool engineOk) {
    EnginePlan p;
    if (!dllEnabled || !engineOk) return p;
    p.patches = p.engineHooks = p.d3dHooks = p.engineReads = true;
    return p;
}

// The one summary log line (the driver adds one line per difference after it).
inline std::string Summary(const GuardResult& r) {
    char b[400];
    snprintf(b, sizeof b, "exe_guard: %s - sha1 %s TimeDateStamp 0x%08x SizeOfImage 0x%08x -> %s", VerdictName(r.verdict),
             r.sha1.empty() ? "(not read)" : r.sha1.c_str(), (unsigned)r.timeDateStamp, (unsigned)r.sizeOfImage,
             r.engineOk ? "engine features on" : "PASS-THROUGH: backend only, no hooks, no patches, no engine reads");
    std::string s = b;
    if (!r.diffs.empty()) s += std::string(r.engineOk ? "; differs (ignored): " : "; first difference: ") + r.diffs[0];
    return s;
}

// The player notice (the driver writes it with CRLF). Never a dialog: unattended runs must not block.
inline std::string NoticeText(const GuardResult& r, const char* game, const char* exeName, const char* configName, const char* when) {
    std::string t;
    t += std::string(game) + " Remastered: the mod's d3d9.dll is running as a plain pass-through.\n";
    t += when; t += "\n\n";
    if (r.verdict == Verdict::Forced) t += std::string("Why: the test key exe_guard_force_mismatch=1 is set in ") + configName + " (nothing is wrong with " + exeName + ").\n";
    else if (r.verdict == Verdict::Unpinned) t += "Why: this build of the mod pins no game version (a development build).\n";
    else t += std::string("Why: ") + exeName + " is not the build this d3d9.dll was made for (most likely a Steam update).\n";
    for (const std::string& d : r.diffs) t += "  - " + d + "\n";
    t += "\nThe game runs as vanilla. Nothing on disk was changed, and the mod did not touch the game's memory.\n"
         "What to do: install a mod build made for this game version, or uninstall the mod (the game is then exactly vanilla).\n"
         "This file is rewritten at every pass-through start and removed at the next start whose exe matches.\n";
    return t;
}

inline std::string ValidateGuardConfig(GuardConfig& c) {
    std::string w; char b[120];
    if (c.exeGuard != 0 && c.exeGuard != 1) { snprintf(b, sizeof b, "exe_guard=%d is not 0 or 1, using 1; ", c.exeGuard); w += b; c.exeGuard = 1; }
    if (c.forceMismatch != 0 && c.forceMismatch != 1) { snprintf(b, sizeof b, "exe_guard_force_mismatch=%d is not 0 or 1, using 0; ", c.forceMismatch); w += b; c.forceMismatch = 0; }
    return w;
}

} // namespace wsp
