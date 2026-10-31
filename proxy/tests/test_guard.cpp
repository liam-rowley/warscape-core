// Host test: the exe-identity guard (guard.h) verdicts, the pass-through plan, the notice and log texts, the generated pin against
// identity.json, and a source lint that keeps every engine-side step behind the guard (the earlier remaster's exe_guard_test idea).
#include "testkit.h"
#include "guard.h"
#include "generated/tables.h"
#include <regex>
#include <set>

using namespace wsp;
static const char* kSha = "9aebcd2172f2878d781b079f7feb45b0e12e0250";

static GuardResult Run(const tk::Image& im, const std::string& sha, const Identity& id, GuardConfig c = {}, const char* err = "") {
    std::vector<uint8_t> m = im.Mapped(0x01230000);   // ASLR: the mapped headers are the same at any base
    PeInfo pe = ParsePe(m.data(), 0x1000);
    Observed o; o.mapped = &pe; o.fileSha1 = sha; o.fileError = err;
    return Evaluate(o, id, c);
}

static std::string Strip(const std::string& s) {   // drop // and /* */ comments and string literals
    std::string o; size_t i = 0;
    while (i < s.size()) {
        if (s.compare(i, 2, "//") == 0) { while (i < s.size() && s[i] != '\n') ++i; }
        else if (s.compare(i, 2, "/*") == 0) { size_t e = s.find("*/", i + 2); i = e == std::string::npos ? s.size() : e + 2; }
        else if (s[i] == '"') { ++i; while (i < s.size() && s[i] != '"') { if (s[i] == '\\') ++i; ++i; } ++i; o += "\"\""; }
        else o += s[i++];
    }
    return o;
}

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    const tk::Image im = tk::GameLike();
    const Identity pin = { "Game.exe", kSha, 0x645e917f, 0xA000 };

    {   GuardResult r = Run(im, kSha, pin);
        CHECK(r.verdict == Verdict::Match); CHECK(r.engineOk); CHECK(r.diffs.empty()); CHECK(r.pinned);
        CHECK(Summary(r).find("match") != std::string::npos); CHECK(Summary(r).find("engine features on") != std::string::npos); }
    {   GuardResult r = Run(im, "0000000000000000000000000000000000000000", pin);   // a Steam update: same header, other bytes
        CHECK(r.verdict == Verdict::Mismatch); CHECK(!r.engineOk); CHECK_EQ(r.diffs.size(), (size_t)1);
        CHECK(r.diffs[0].find("exe sha1 0000") == 0); CHECK(Summary(r).find("PASS-THROUGH") != std::string::npos);
        CHECK(Summary(r).find("first difference: exe sha1") != std::string::npos); }
    {   tk::Image b = im; b.tds = 0x11111111; b.WriteHeaders();
        GuardResult r = Run(b, kSha, pin);
        CHECK(r.verdict == Verdict::Mismatch); CHECK(r.diffs[0].find("TimeDateStamp 0x11111111, pinned 0x645e917f") != std::string::npos); }
    {   tk::Image b = im; b.sizeOfImage = 0xB000; b.WriteHeaders();
        GuardResult r = Run(b, kSha, pin);
        CHECK(r.verdict == Verdict::Mismatch); CHECK(r.diffs[0].find("SizeOfImage") != std::string::npos); }
    {   tk::Image b = im; b.tds = 1; b.sizeOfImage = 0xB000; b.WriteHeaders();   // every difference is listed, first one leads
        GuardResult r = Run(b, "ff", pin);
        CHECK_EQ(r.diffs.size(), (size_t)3); CHECK(r.diffs[0].find("TimeDateStamp") != std::string::npos); }
    {   GuardResult r = Run(im, "", pin, {}, "cannot open the exe (error 5)");   // unreadable exe file = a difference (fail closed)
        CHECK(r.verdict == Verdict::Mismatch); CHECK(r.diffs[0].find("not hashed: cannot open") != std::string::npos); }
    {   tk::Image b = im; b.machine = 0x8664; b.WriteHeaders();
        GuardResult r = Run(b, kSha, pin); CHECK(r.verdict == Verdict::Mismatch); CHECK(r.diffs[0].find("not x86") != std::string::npos); }
    {   PeInfo bad = ParsePe((const uint8_t*)"nope", 4); Observed o; o.mapped = &bad; o.fileSha1 = kSha;
        GuardResult r = Evaluate(o, pin, {}); CHECK(r.verdict == Verdict::Mismatch); CHECK(r.diffs[0].find("PE headers") == 0); }
    {   const Identity none = { "Game.exe", "", 0, 0 };   // unpinned fails CLOSED in the core
        GuardResult r = Run(im, kSha, none); CHECK(r.verdict == Verdict::Unpinned); CHECK(!r.engineOk); CHECK(r.diffs[0].find("pins no") != std::string::npos); }
    {   GuardConfig c; c.exeGuard = 0;   // developer override: on whatever differs
        GuardResult r = Run(im, "ff", pin, c); CHECK(r.verdict == Verdict::Override); CHECK(r.engineOk);
        CHECK(Summary(r).find("differs (ignored)") != std::string::npos); }
    {   GuardConfig c; c.forceMismatch = 1;   // forced: pass-through on a matching exe
        GuardResult r = Run(im, kSha, pin, c); CHECK(r.verdict == Verdict::Forced); CHECK(!r.engineOk); CHECK(r.diffs.empty());
        const std::string n = NoticeText(r, "Some Game", "Game.exe", "game_mod.ini", "Written now.");
        CHECK(n.find("exe_guard_force_mismatch=1") != std::string::npos); CHECK(n.find("did not touch the game's memory") != std::string::npos);
        c.exeGuard = 0; r = Run(im, kSha, pin, c); CHECK(r.verdict == Verdict::Forced); CHECK(!r.engineOk);   // wins over the override
    }
    {   GuardResult r = Run(im, "ff", pin);
        const std::string n = NoticeText(r, "Some Game", "Game.exe", "game_mod.ini", "Written now.");
        CHECK(n.find("Steam update") != std::string::npos); CHECK(n.find("  - exe sha1 ff, pinned") != std::string::npos); }
    {   GuardConfig c; c.exeGuard = 2; c.forceMismatch = -1;
        const std::string w = ValidateGuardConfig(c); CHECK(c.exeGuard == 1); CHECK(c.forceMismatch == 0); CHECK(w.find("exe_guard=2") != std::string::npos); }
    {   // the plan: pass-through and disabled = nothing engine-side; accepted = everything
        EnginePlan p = PlanEngine(true, false); CHECK(!p.patches && !p.engineHooks && !p.d3dHooks && !p.engineReads);
        p = PlanEngine(false, true); CHECK(!p.patches && !p.engineHooks && !p.d3dHooks && !p.engineReads);
        p = PlanEngine(true, true); CHECK(p.patches && p.engineHooks && p.d3dHooks && p.engineReads); }
    {   // the generated pin is identity.json's
        const std::string j = tk::ReadFile("adapter/identity.json");
        CHECK(j.find(std::string("\"sha1\": \"") + gen::kIdentity.sha1 + "\"") != std::string::npos);
        char b[64]; snprintf(b, sizeof b, "\"time_date_stamp\": \"0x%08x\"", (unsigned)gen::kIdentity.timeDateStamp); CHECK(j.find(b) != std::string::npos);
        snprintf(b, sizeof b, "\"size_of_image\": \"0x%08x\"", (unsigned)gen::kIdentity.sizeOfImage); CHECK(j.find(b) != std::string::npos);
        CHECK(strlen(gen::kIdentity.sha1) == 40); }
    {   // source lint: the order in DllMain, and every engine-side step gated by the plan
        const std::string dm = Strip(tk::ReadFile("core/dllmain.cpp"));
        const size_t g = dm.find("GuardRun();"), pl = dm.find("rt.plan = PlanEngine(rt.enabled, rt.engineOk);"), pr = dm.find("PatchesRun();");
        CHECK(g != std::string::npos && pl != std::string::npos && pr != std::string::npos); CHECK(g < pl && pl < pr);
        CHECK(dm.find("rt.plan = PlanEngine(false, false); return;") != std::string::npos && dm.find("rt.plan = PlanEngine(false, false); return;") < g);
        const std::string pd = Strip(tk::ReadFile("core/patch_driver.cpp"));
        CHECK(pd.find("if (!rt.plan.patches)") != std::string::npos && pd.find("if (!rt.plan.patches)") < pd.find("MakePatchPlan"));
        // only the guard and the patch engine touch the exe image; the backend never does; no file but guard.h computes the plan
        for (const char* f : { "backend.cpp", "crash.cpp", "log.cpp" }) {
            const std::string s = Strip(tk::ReadFile(std::string("core/") + f));
            CHECK(s.find("GetModuleHandleW(nullptr)") == std::string::npos); CHECK(s.find("VirtualProtect") == std::string::npos);
            CHECK(s.find("PlanEngine(") == std::string::npos);
        }
        // the core names no game (it moves to warscape-core)
        for (const char* f : { "pe.h", "sha1.h", "guard.h", "patch_engine.h", "config.h", "adapter.h", "runtime.h", "dllmain.cpp", "backend.cpp", "crash.cpp",
                               "log.cpp", "guard_driver.cpp", "patch_driver.cpp", "d3d9.def" }) {
            std::string s = tk::ReadFile(std::string("core/") + f);
            CHECK(!s.empty());
            for (size_t k; (k = s.find("empire-remastered")) != std::string::npos;) s.erase(k, 17);   // provenance links are fine
            const bool named = s.find("apoleon") != std::string::npos || s.find("mpire") != std::string::npos;
            if (named) { printf("    %s names a game\n", f); CHECK(!named); }
        }
        // every config key the core reads by name is in the generated (registry) table
        std::set<std::string> known; for (size_t i = 0; i < gen::kKeyCount; ++i) known.insert(gen::kKeys[i].id);
        const std::regex re("\"(proxy\\.[a-z_]+)\"");
        {   // the rebase delta never comes from the mapped header (the loader rewrites its ImageBase): pe.h LoadDelta with the file's base
            const std::string pd = Strip(tk::ReadFile("core/patch_driver.cpp"));
            CHECK(pd.find("LoadDelta(") != std::string::npos);
            CHECK(pd.find("fileImageBase") != std::string::npos);
            CHECK(pd.find("- pe.preferredBase") == std::string::npos);
            CHECK(pd.find("WritePlanAtomic(") != std::string::npos);   // writes go through the all-or-nothing writer
            CHECK(pd.find("memcpy(") == std::string::npos);            // ... and nowhere else
        }
        for (const char* f : { "dllmain.cpp", "backend.cpp", "crash.cpp", "guard_driver.cpp", "patch_driver.cpp" }) {
            const std::string s = tk::ReadFile(std::string("core/") + f);
            for (std::sregex_iterator it(s.begin(), s.end(), re), e; it != e; ++it)
                if (!known.count((*it)[1])) { printf("    %s reads %s, which is not in config_keys\n", f, (*it)[1].str().c_str()); CHECK(false); }
        }
    }
    return tk::Done("test_guard");
}
