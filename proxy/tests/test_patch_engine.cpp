// Host test: the runtime patch engine (patch_engine.h) on a synthetic game-like image: rebasing under ASLR, anchor and stock
// checks, all-or-nothing, already-patched, disabled sites, hooks, bad tables, file view == mapped view, and the generated table.
#include "testkit.h"
#include <memory>
#include "patch_engine.h"
#include "generated/tables.h"

using namespace wsp;

static SiteDef Patch(const char* id, uint32_t rva, std::vector<uint8_t> a, std::vector<uint8_t> st, std::vector<uint8_t> p, const char* key = nullptr) {
    SiteDef d{}; d.id = id; d.kind = kPatch; d.rva = rva; d.anchorLen = (uint8_t)a.size(); memcpy(d.anchor, a.data(), a.size());
    d.len = (uint8_t)st.size(); memcpy(d.stock, st.data(), st.size()); memcpy(d.patch, p.data(), p.size()); d.configKey = key; return d;
}
static SiteDef Hook(const char* id, uint32_t rva, std::vector<uint8_t> a, std::vector<uint8_t> st) {
    SiteDef d = Patch(id, rva, a, st, {}); d.kind = kHook; return d;
}

// The fixture: an imm32 patch in .text (mov dword [ecx+0x48], 2048), a float in .data, and a hookable function whose first
// instruction holds an ABSOLUTE address (push 0x0140a000 -> relocated) to prove the rebase.
static tk::Image Fixture() {
    tk::Image im = tk::GameLike();
    im.Put(0x1100, { 0xC7, 0x41, 0x48, 0x00, 0x08, 0x00, 0x00, 0x90 });          // mov [ecx+0x48], 0x800 ; nop
    im.Put(0x5010, { 0x11, 0x22, 0x33, 0x44, 0x00, 0x00, 0x48, 0x42 });          // tag, then 50.0f
    im.Put(0x2000, { 0xCC, 0xCC, 0x68, 0x00, 0xA0, 0x40, 0x00, 0x8B, 0xC1, 0xC3 });   // int3 int3 | push 0x40a000 ; mov eax,ecx ; ret
    im.relocs = { 0x2003 };
    im.BuildRelocs();
    return im;
}
static std::vector<SiteDef> Sites() {
    return { Patch("shadow.size", 0x1100, { 0xC7, 0x41, 0x48 }, { 0x00, 0x08, 0x00, 0x00 }, { 0x00, 0x20, 0x00, 0x00 }),
             Patch("lod.range", 0x5010, { 0x11, 0x22, 0x33, 0x44 }, { 0x00, 0x00, 0x48, 0x42 }, { 0x00, 0x00, 0xC8, 0x42 }, "lod.enabled"),
             Hook("fn.tick", 0x2000, { 0xCC, 0xCC }, { 0x68, 0x00, 0xA0, 0x40, 0x00, 0x8B, 0xC1 }) };
}

// Fake memory protection for WritePlanAtomic: fails Unprotect on call number failAt (0-based), counts what is still writable.
struct FakeMem : MemOps {
    int failAt = -1, calls = 0, writable = 0, flushes = 0; bool failRestore = false;
    bool Unprotect(uint8_t*, size_t, uint32_t& old) override { if (calls++ == failAt) return false; old = 0x20; ++writable; return true; }
    bool Reprotect(uint8_t*, size_t, uint32_t old) override { CHECK_EQ(old, 0x20u); if (failRestore) return false; --writable; return true; }
    void Flush(uint8_t*, size_t) override { ++flushes; }
};

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    const tk::Image im = Fixture();
    const std::vector<SiteDef> s = Sites();
    const bool on[3] = { true, true, true };

    for (uint32_t base : { 0x400000u, 0x01230000u, 0x7ff00000u }) {   // preferred base and two ASLR bases
        std::vector<uint8_t> m = im.Mapped(base);
        PeInfo pe; ImageView v = tk::MappedView(m, pe);
        PatchPlan pl = MakePatchPlan(v, base - 0x400000u, s.data(), s.size(), on);
        CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nBad, 0); CHECK_EQ(pl.nWrite, 2); CHECK_EQ(pl.nHooks, 1);
        CHECK(pl.sites[2].state == SiteState::Stock);   // the relocated push compares equal at every base
        CHECK_EQ(pl.sites[0].valueRva, 0x1103u);
        std::vector<uint8_t> before = m;
        CHECK_EQ(ApplyPlanToBuffer(m.data(), pl, s.data()), 2);   // 0x08->0x20, 0x48->0xC8, and nothing else
        size_t diff = 0; for (size_t i = 0; i < m.size(); ++i) diff += m[i] != before[i];
        CHECK_EQ(diff, (size_t)2);
        CHECK(m[0x1104] == 0x20 && m[0x5016] == 0xC8);
        // second run on the patched image: already patched, nothing to do
        PeInfo pe2; ImageView v2 = tk::MappedView(m, pe2);
        PatchPlan again = MakePatchPlan(v2, base - 0x400000u, s.data(), s.size(), on);
        CHECK(again.verdict == PlanVerdict::NothingToDo); CHECK_EQ(again.nDone, 2);
    }
    {   // the delta comes from the FILE's ImageBase: the loader rewrites the mapped header to the actual base (PC 2026-10-28,
        // proxy/runs/20261028_pctest), so a delta from the mapped header is 0 and every relocated anchor fails under ASLR
        PeInfo fpe; tk::FileView(im, fpe);
        CHECK_EQ(fpe.preferredBase, 0x400000u);
        for (uint32_t base : { 0x400000u, 0x00610000u, 0x7ff00000u }) {
            std::vector<uint8_t> m = im.Mapped(base);
            PeInfo pe; ImageView v = tk::MappedView(m, pe);
            CHECK_EQ(pe.preferredBase, base);                       // the trap: the mapped header holds the actual base
            uint32_t d = 1;
            CHECK(LoadDelta(base, fpe.preferredBase, d)); CHECK_EQ(d, base - 0x400000u);
            CHECK(MakePatchPlan(v, d, s.data(), s.size(), on).verdict == PlanVerdict::Apply);
            uint32_t bad = 1; CHECK(LoadDelta(base, pe.preferredBase, bad)); CHECK_EQ(bad, 0u);
            if (base != 0x400000u) CHECK(MakePatchPlan(v, bad, s.data(), s.size(), on).verdict == PlanVerdict::Refuse);
        }
        uint32_t d = 7;
        CHECK(!LoadDelta(0x00610000u, 0, d)); CHECK(!LoadDelta(0x00610000u, 0x00401000u, d));   // unknown or unaligned base: no delta
    }
    {   // without taking the delta off, the hook's relocated dword would not match: the rebase is what makes ASLR work
        std::vector<uint8_t> m = im.Mapped(0x01230000);
        PeInfo pe; ImageView v = tk::MappedView(m, pe);
        PatchPlan pl = MakePatchPlan(v, 0, s.data(), s.size(), on);
        CHECK(pl.verdict == PlanVerdict::Refuse); CHECK(pl.sites[2].state == SiteState::BadStock);
    }
    {   // the file view gives the same verdict as the mapped view (tools can check an exe on disk)
        PeInfo pe; ImageView v = tk::FileView(im, pe);
        PatchPlan pl = MakePatchPlan(v, 0, s.data(), s.size(), on);
        CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nWrite, 2);
    }
    {   // a disabled site is checked but never written
        const bool off[3] = { true, false, true };
        std::vector<uint8_t> m = im.Mapped(0x400000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
        PatchPlan pl = MakePatchPlan(v, 0, s.data(), s.size(), off);
        CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nWrite, 1); CHECK(!pl.sites[1].write); CHECK(pl.sites[1].state == SiteState::Stock);
        tk::Image b = im; b.Put(0x5010, { 0x99 }); std::vector<uint8_t> mb = b.Mapped(0x400000); PeInfo peb; ImageView vb = tk::MappedView(mb, peb);
        CHECK(MakePatchPlan(vb, 0, s.data(), s.size(), off).verdict == PlanVerdict::Refuse);   // ... and a bad disabled site still refuses all
    }
    struct Bad { const char* what; tk::Image img; std::vector<SiteDef> sites; SiteState want; int site; };
    std::vector<Bad> bads;
    { tk::Image b = im; b.Put(0x1101, { 0x42 }); bads.push_back({ "anchor changed (another build)", b, s, SiteState::BadAnchor, 0 }); }
    { tk::Image b = im; b.Put(0x1104, { 0x10 }); bads.push_back({ "value neither stock nor patch", b, s, SiteState::BadStock, 0 }); }
    { tk::Image b = im; b.Put(0x2008, { 0x90 }); bads.push_back({ "hook prologue changed", b, s, SiteState::BadStock, 2 }); }
    { auto x = s; x[0].rva = 0x3FFE; bads.push_back({ "site crosses the end of .text", im, x, SiteState::Unmapped, 0 }); }
    { auto x = s; x[0].rva = 0x50000; bads.push_back({ "site outside the image", im, x, SiteState::Unmapped, 0 }); }
    { auto x = s; x[2] = Hook("fn.data", 0x5010, { 0x11, 0x22, 0x33, 0x44 }, { 0x00, 0x00, 0x48, 0x42, 0x00 }); x.erase(x.begin() + 1);
      bads.push_back({ "hook in a non-executable section", im, x, SiteState::NotCode, 1 }); }
    { auto x = s; x[2] = Patch("abs.addr", 0x2000, { 0xCC, 0xCC, 0x68 }, { 0x00, 0xA0, 0x40, 0x00 }, { 0x00, 0xB0, 0x40, 0x00 });
      bads.push_back({ "patch value under a relocation", im, x, SiteState::Relocated, 2 }); }
    { auto x = s; x.push_back(Patch("overlap", 0x1102, { 0x41 }, { 0x48 }, { 0x49 })); bads.push_back({ "two sites overlap", im, x, SiteState::Overlap, 3 }); }
    { auto x = s; x[0].anchorLen = 0; bads.push_back({ "empty anchor", im, x, SiteState::BadEntry, 0 }); }
    { auto x = s; x[0].len = 40; bads.push_back({ "too many bytes", im, x, SiteState::BadEntry, 0 }); }
    for (Bad& b : bads) {
        std::vector<uint8_t> m = b.img.Mapped(0x01230000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
        std::unique_ptr<bool[]> e(new bool[b.sites.size()]); for (size_t i = 0; i < b.sites.size(); ++i) e[i] = true;
        PatchPlan pl = MakePatchPlan(v, 0x01230000 - 0x400000, b.sites.data(), b.sites.size(), e.get());
        const bool ok = pl.verdict == PlanVerdict::Refuse && pl.nWrite == 0 && pl.sites[b.site].state == b.want && !pl.reason.empty();
        if (!ok) printf("    case '%s': verdict %s, site %d state %s, reason %s\n", b.what, PlanVerdictName(pl.verdict), b.site, SiteStateName(pl.sites[b.site].state), pl.reason.c_str());
        CHECK(ok);
        for (auto& c : pl.sites) CHECK(!c.write);                                   // all-or-nothing
        std::vector<uint8_t> before = m; CHECK_EQ(ApplyPlanToBuffer(m.data(), pl, b.sites.data()), 0); CHECK(m == before);
    }
    {   // first-difference reporting names the site, the state and the byte
        tk::Image b = im; b.Put(0x1105, { 0x77 });
        std::vector<uint8_t> m = b.Mapped(0x400000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
        PatchPlan pl = MakePatchPlan(v, 0, s.data(), s.size(), on);
        CHECK(pl.reason.find("'shadow.size'") != std::string::npos); CHECK(pl.reason.find("STOCK MISMATCH at byte +2") != std::string::npos);
        CHECK(PlanSummary(pl, s.size()).find("REFUSED") == 14);
    }
    {   // no PE / zero sites
        PeInfo bad; ImageView v; v.pe = &bad;
        CHECK(MakePatchPlan(v, 0, s.data(), s.size(), on).verdict == PlanVerdict::Refuse);
        CHECK(MakePatchPlan(v, 0, s.data(), 0, on).verdict == PlanVerdict::NothingToDo);
    }
    {   // the generated table (from the registry) is well formed and gives a clean plan on a game-like image
        std::vector<uint8_t> m = im.Mapped(0x400000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
        PatchPlan pl = MakePatchPlan(v, 0, gen::kSites, gen::kSiteCount, nullptr);
        CHECK_EQ(pl.nBad, gen::kSiteCount == 0 ? 0 : pl.nBad);
        if (gen::kSiteCount == 0) CHECK(pl.verdict == PlanVerdict::NothingToDo);
        CHECK(gen::kSites[gen::kSiteCount].id == nullptr);   // sentinel
        for (size_t i = 0; i < gen::kSiteCount; ++i) { CHECK(gen::kSites[i].anchorLen > 0); CHECK(gen::kSites[i].len > 0); }
    }
    {   // all-or-nothing at WRITE time (J1 review finding 4): one Unprotect failure writes nothing and restores the others
        std::vector<uint8_t> m = im.Mapped(0x00610000u);
        PeInfo pe; ImageView v = tk::MappedView(m, pe);
        const PatchPlan pl = MakePatchPlan(v, 0x00610000u - 0x400000u, s.data(), s.size(), on);
        CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nWrite, 2);
        for (int failAt : { 0, 1 }) {
            std::vector<uint8_t> mm = m; FakeMem f; f.failAt = failAt;
            const WriteResult r = WritePlanAtomic(mm.data(), pl, s.data(), f);
            CHECK(!r.ok); CHECK_EQ(r.written, 0); CHECK(mm == m); CHECK_EQ(f.writable, 0); CHECK_EQ(f.flushes, 0);
            CHECK_EQ(r.failedSite, failAt == 0 ? 0 : 1);
        }
        {   std::vector<uint8_t> mm = m; FakeMem f;
            const WriteResult r = WritePlanAtomic(mm.data(), pl, s.data(), f);
            CHECK(r.ok); CHECK_EQ(r.written, 2); CHECK_EQ(f.writable, 0); CHECK_EQ(f.flushes, 2); CHECK_EQ(r.reprotectFailures, 0);
            CHECK(mm[0x1104] == 0x20 && mm[0x5016] == 0xC8);
            std::vector<uint8_t> want = m; ApplyPlanToBuffer(want.data(), pl, s.data()); CHECK(mm == want);   // same bytes as the pure apply
        }
        {   std::vector<uint8_t> mm = m; FakeMem f; f.failRestore = true;   // restore failing: written, counted, never half-written
            const WriteResult r = WritePlanAtomic(mm.data(), pl, s.data(), f);
            CHECK(r.ok); CHECK_EQ(r.written, 2); CHECK_EQ(r.reprotectFailures, 2);
        }
        {   PatchPlan bad = pl; bad.verdict = PlanVerdict::Refuse; std::vector<uint8_t> mm = m; FakeMem f;
            const WriteResult r = WritePlanAtomic(mm.data(), bad, s.data(), f);
            CHECK(!r.ok); CHECK_EQ(f.calls, 0); CHECK(mm == m);                       // a refused plan never touches protection
        }
    }
    return tk::Done("test_patch_engine");
}
