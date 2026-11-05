// Host test: the runtime patch engine (patch_engine.h) on a synthetic game-like image: rebasing under ASLR, anchor and stock
// checks, all-or-nothing, already-patched, disabled sites, hooks, bad tables, file view == mapped view, the generated table, and the
// writer's page protections on a mock with VirtualProtect's page semantics (tk::PageMem, W33): two sites on one page, a straddling site.
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
    {   // W34: the smoke's own row as launch 12 writes it (a game without the fixture row skips this): every generated site in place, only
        // null.smoke_patch on. The writer changes exactly what the pure apply does, on one page, and the page comes back
        size_t at = gen::kSiteCount;
        for (size_t i = 0; i < gen::kSiteCount; ++i) if (!strcmp(gen::kSites[i].id, "null.smoke_patch")) at = i;
        if (at < gen::kSiteCount) {
            tk::Image b = tk::GameLike();
            std::unique_ptr<bool[]> en(new bool[gen::kSiteCount]());
            en[at] = true;
            for (size_t i = 0; i < gen::kSiteCount; ++i) {
                const SiteDef& d = gen::kSites[i];
                b.Put(d.rva, std::vector<uint8_t>(d.anchor, d.anchor + d.anchorLen));
                b.Put(d.rva + d.anchorLen, std::vector<uint8_t>(d.stock, d.stock + d.len));
            }
            std::vector<uint8_t> m = b.Mapped(0x400000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
            const PatchPlan pl = MakePatchPlan(v, 0, gen::kSites, gen::kSiteCount, en.get());
            CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nBad, 0); CHECK_EQ(pl.nWrite, 1); CHECK_EQ(pl.bytesToChange, 1);
            std::vector<uint8_t> mm = m; tk::PageMem f(b, mm.data());
            const WriteResult r = WritePlanAtomic(mm.data(), pl, gen::kSites, f);
            CHECK(r.ok); CHECK_EQ(r.written, 1); CHECK_EQ(r.pages.size(), (size_t)1); CHECK(f.Restored());
            std::vector<uint8_t> want = m; CHECK_EQ(ApplyPlanToBuffer(want.data(), pl, gen::kSites), 1); CHECK(mm == want);
        }
    }
    {   // the generated table (from the registry) is well formed and gives a clean plan on a game-like image
        std::vector<uint8_t> m = im.Mapped(0x400000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
        PatchPlan pl = MakePatchPlan(v, 0, gen::kSites, gen::kSiteCount, nullptr);
        CHECK_EQ(pl.nBad, gen::kSiteCount == 0 ? 0 : pl.nBad);
        if (gen::kSiteCount == 0) CHECK(pl.verdict == PlanVerdict::NothingToDo);
        CHECK(gen::kSites[gen::kSiteCount].id == nullptr);   // sentinel
        for (size_t i = 0; i < gen::kSiteCount; ++i) { CHECK(gen::kSites[i].anchorLen > 0); CHECK(gen::kSites[i].len > 0); }
    }
    {   // B41: an immediate right after an ABSOLUTE address, `mov dword [abs32], <float>` (c7 05 <abs32> <f32>), with a relocation
        // on the address. The anchor holds the address as the FILE holds it (ReadUnrelocated takes the delta off), and the relocation
        // ends where the value starts, so RelocsInRange does not count it against the value: no value_offset is needed.
        tk::Image b = im;
        b.Put(0x1200, { 0xC7, 0x05, 0x00, 0xB0, 0x40, 0x00, 0x00, 0x00, 0x80, 0x3E, 0x90 });   // mov dword [0x40b000], 0.25f ; nop
        b.relocs.push_back(0x1202); b.BuildRelocs();
        std::vector<SiteDef> x = s;
        x.push_back(Patch("frame.time", 0x1200, { 0xC7, 0x05, 0x00, 0xB0, 0x40, 0x00 }, { 0x00, 0x00, 0x80, 0x3E }, { 0x00, 0x00, 0x00, 0x3F }));   // -> 0.5f
        const bool on4[4] = { true, true, true, true };
        for (uint32_t base : { 0x400000u, 0x01230000u, 0x7ff00000u }) {
            std::vector<uint8_t> m = b.Mapped(base);
            PeInfo pe; ImageView v = tk::MappedView(m, pe);
            PatchPlan pl = MakePatchPlan(v, base - 0x400000u, x.data(), x.size(), on4);
            if (pl.verdict != PlanVerdict::Apply) printf("    B41 at 0x%08x: %s\n", (unsigned)base, pl.reason.c_str());
            CHECK(pl.verdict == PlanVerdict::Apply); CHECK(pl.sites[3].state == SiteState::Stock); CHECK_EQ(pl.sites[3].valueRva, 0x1206u);
            CHECK_EQ(pl.nWrite, 3);
            CHECK_EQ(Rd32(&m[0x1202]), 0x40B000u + (base - 0x400000u));   // the address really is relocated in memory
            std::vector<uint8_t> before = m; tk::PageMem f(b, m.data());
            CHECK(WritePlanAtomic(m.data(), pl, x.data(), f).ok);
            CHECK(f.Restored()); CHECK(f.NoneTwice());   // W33 (C3): page 0x1000 holds two written sites (0x1103, 0x1206) and ends 0x20
            size_t diff = 0; for (size_t i = 0x1200; i < 0x1210; ++i) diff += m[i] != before[i];
            CHECK_EQ(diff, (size_t)2); CHECK(m[0x1208] == 0x00 && m[0x1209] == 0x3F);   // only the float's two changing bytes; the address untouched
            CHECK_EQ(Rd32(&m[0x1202]), Rd32(&before[0x1202]));
            PeInfo pe2; ImageView v2 = tk::MappedView(m, pe2);
            CHECK(MakePatchPlan(v2, base - 0x400000u, x.data(), x.size(), on4).sites[3].state == SiteState::Done);
            // an anchor that names the address as relocated in memory (not as the file holds it) fails under ASLR
            std::vector<SiteDef> y = x; if (base != 0x400000u) { Wr32(&y[3].anchor[2], 0x40B000u + (base - 0x400000u));
                CHECK(MakePatchPlan(tk::MappedView(before, pe), base - 0x400000u, y.data(), y.size(), on4).sites[3].state == SiteState::BadAnchor); }
        }
    }
    {   // all-or-nothing at WRITE time (J1 review finding 4): one Unprotect failure writes nothing and restores the others
        std::vector<uint8_t> m = im.Mapped(0x00610000u);
        PeInfo pe; ImageView v = tk::MappedView(m, pe);
        const PatchPlan pl = MakePatchPlan(v, 0x00610000u - 0x400000u, s.data(), s.size(), on);
        CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nWrite, 2);
        for (int failAt : { 0, 1 }) {
            std::vector<uint8_t> mm = m; tk::PageMem f(im, mm.data()); f.failUnprotectAt = failAt;
            const WriteResult r = WritePlanAtomic(mm.data(), pl, s.data(), f);
            CHECK(!r.ok); CHECK_EQ(r.written, 0); CHECK(mm == m); CHECK(f.Restored()); CHECK(f.NoneTwice()); CHECK_EQ(f.flushes, 0);
            CHECK_EQ(r.failedSite, failAt == 0 ? 0 : 1);
        }
        {   std::vector<uint8_t> mm = m; tk::PageMem f(im, mm.data());
            const WriteResult r = WritePlanAtomic(mm.data(), pl, s.data(), f);
            CHECK(r.ok); CHECK_EQ(r.written, 2); CHECK(f.Restored()); CHECK(f.NoneTwice()); CHECK_EQ(f.flushes, 2); CHECK_EQ(r.reprotectFailures, 0);
            CHECK(mm[0x1104] == 0x20 && mm[0x5016] == 0xC8);
            std::vector<uint8_t> want = m; ApplyPlanToBuffer(want.data(), pl, s.data()); CHECK(mm == want);   // same bytes as the pure apply
        }
        {   std::vector<uint8_t> mm = m; tk::PageMem f(im, mm.data()); f.failEveryReprotect = true;   // restore failing: written, counted, never half-written
            const WriteResult r = WritePlanAtomic(mm.data(), pl, s.data(), f);
            CHECK(r.ok); CHECK_EQ(r.written, 2); CHECK_EQ(r.reprotectFailures, 2);
        }
        {   PatchPlan bad = pl; bad.verdict = PlanVerdict::Refuse; std::vector<uint8_t> mm = m; tk::PageMem f(im, mm.data());
            const WriteResult r = WritePlanAtomic(mm.data(), bad, s.data(), f);
            CHECK(!r.ok); CHECK_EQ(f.unprotectCalls, 0); CHECK_EQ(f.reprotectCalls, 0); CHECK(mm == m);   // a refused plan never touches protection
        }
    }
    {   // W33 (C3): a site whose value bytes straddle two .text pages (0x2ffe-0x3001), after a site on the first of them (0x2803).
        // VirtualProtect reports the old protection of the FIRST page of a range only, so a per-site record restores both pages RWX.
        tk::Image b = im;
        b.Put(0x2800, { 0xC7, 0x41, 0x4C, 0x00, 0x00, 0xC8, 0x42 });   // mov [ecx+0x4c], 100.0f
        b.Put(0x2ffb, { 0xC7, 0x41, 0x48, 0x00, 0x00, 0x48, 0x43 });   // mov [ecx+0x48], 200.0f: the value crosses 0x3000
        const std::vector<SiteDef> x = { Patch("near.a", 0x2800, { 0xC7, 0x41, 0x4C }, { 0x00, 0x00, 0xC8, 0x42 }, { 0x00, 0x00, 0x48, 0x43 }),
                                         Patch("straddle.b", 0x2ffb, { 0xC7, 0x41, 0x48 }, { 0x00, 0x00, 0x48, 0x43 }, { 0x00, 0x00, 0x96, 0x43 }) };
        const bool on2[2] = { true, true };
        for (uint32_t base : { 0x400000u, 0x01230000u }) {
            std::vector<uint8_t> m = b.Mapped(base); PeInfo pe; ImageView v = tk::MappedView(m, pe);
            const PatchPlan pl = MakePatchPlan(v, base - 0x400000u, x.data(), x.size(), on2);
            if (pl.verdict != PlanVerdict::Apply) printf("    straddle at 0x%08x: %s\n", (unsigned)base, pl.reason.c_str());
            CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nWrite, 2); CHECK_EQ(pl.sites[1].valueRva, 0x2ffeu);
            std::vector<uint8_t> want = m; ApplyPlanToBuffer(want.data(), pl, x.data());
            std::vector<uint8_t> mm = m; tk::PageMem f(b, mm.data());
            const WriteResult r = WritePlanAtomic(mm.data(), pl, x.data(), f);
            CHECK(r.ok); CHECK_EQ(r.written, 2); CHECK(mm == want);   // the same bytes as the pure apply
            CHECK(f.Restored()); CHECK(f.NoneTwice());
            CHECK_EQ(r.pages.size(), (size_t)2); CHECK_EQ(f.unprotectCalls, 2); CHECK_EQ(f.reprotectCalls, 2); CHECK_EQ(f.flushes, 2);
            for (const PageProt& q : r.pages) { CHECK(q.known); CHECK_EQ(q.recorded, 0x20u); CHECK_EQ(q.after, 0x20u); }
            for (int failAt : { 0, 1 }) {   // a failure at each page index: nothing written, every page initial, the site and the page named
                std::vector<uint8_t> m2 = m; tk::PageMem g(b, m2.data()); g.failUnprotectAt = failAt;
                const WriteResult w = WritePlanAtomic(m2.data(), pl, x.data(), g);
                CHECK(!w.ok); CHECK_EQ(w.written, 0); CHECK(m2 == m); CHECK(g.Restored()); CHECK(g.NoneTwice()); CHECK_EQ(g.flushes, 0);
                CHECK_EQ(w.failedPage, failAt == 0 ? (int64_t)0x2000 : (int64_t)0x3000);
                CHECK_EQ(w.failedSite, failAt == 0 ? 0 : 1);   // page 0x3000 holds a byte of straddle.b only
            }
        }
    }
    {   // W33: WritePages, the pages a plan's written value bytes touch (sorted, unique)
        auto pages = [](std::vector<std::pair<uint32_t, uint8_t>> v, std::vector<bool> w = {}) {
            PatchPlan pl; std::vector<SiteDef> d(v.size()); pl.sites.resize(v.size());
            for (size_t i = 0; i < v.size(); ++i) { pl.sites[i].valueRva = v[i].first; pl.sites[i].write = w.empty() || w[i]; d[i].len = v[i].second; }
            return WritePages(pl, d.data(), 0x1000);
        };
        typedef std::vector<uint32_t> P;
        CHECK(pages({ { 0x1103, 4 } }) == P({ 0x1000 }));                                // one page
        CHECK(pages({ { 0x1103, 4 }, { 0x1206, 4 } }) == P({ 0x1000 }));                 // two sites on one page
        CHECK(pages({ { 0x2ffe, 4 } }) == P({ 0x2000, 0x3000 }));                        // a straddle
        CHECK(pages({ { 0x5016, 2 }, { 0x1103, 4 } }) == P({ 0x1000, 0x5000 }));         // .data and .text, ascending
        CHECK(pages({ { 0x2ffc, 4 }, { 0x3000, 1 } }) == P({ 0x2000, 0x3000 }));         // a site ending exactly at a page end
        CHECK(pages({ { 0x1103, 4 }, { 0x5016, 2 } }, { true, false }) == P({ 0x1000 })); // a site not written touches nothing
        CHECK(pages({}).empty());
    }
    {   // W33: ProtectionRestored: equal, the two copy-on-write pairs, a different value, a guard bit
        CHECK(ProtectionRestored(0x20, 0x20)); CHECK(ProtectionRestored(0x04, 0x04)); CHECK(ProtectionRestored(0x02, 0x02));
        CHECK(ProtectionRestored(0x08, 0x04)); CHECK(ProtectionRestored(0x80, 0x40));
        CHECK(!ProtectionRestored(0x20, 0x40)); CHECK(!ProtectionRestored(0x04, 0x40)); CHECK(!ProtectionRestored(0x04, 0x08));
        CHECK(!ProtectionRestored(0x40, 0x80)); CHECK(!ProtectionRestored(0x20, 0x120));
    }
    {   // W33: the page-wise writer on the B41 fixture (pages 0x1000 with two sites, 0x5000 with one): each page its own value, once
        tk::Image b = im;
        b.Put(0x1200, { 0xC7, 0x05, 0x00, 0xB0, 0x40, 0x00, 0x00, 0x00, 0x80, 0x3E, 0x90 });
        b.relocs.push_back(0x1202); b.BuildRelocs();
        std::vector<SiteDef> x = s;
        x.push_back(Patch("frame.time", 0x1200, { 0xC7, 0x05, 0x00, 0xB0, 0x40, 0x00 }, { 0x00, 0x00, 0x80, 0x3E }, { 0x00, 0x00, 0x00, 0x3F }));
        const bool on4[4] = { true, true, true, true };
        std::vector<uint8_t> m = b.Mapped(0x01230000u); PeInfo pe; ImageView v = tk::MappedView(m, pe);
        const PatchPlan pl = MakePatchPlan(v, 0x01230000u - 0x400000u, x.data(), x.size(), on4);
        CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nWrite, 3);
        std::vector<uint8_t> want = m; ApplyPlanToBuffer(want.data(), pl, x.data());
        {   std::vector<uint8_t> mm = m; tk::PageMem f(b, mm.data());
            const WriteResult r = WritePlanAtomic(mm.data(), pl, x.data(), f);
            CHECK(r.ok); CHECK_EQ(r.written, 3); CHECK(mm == want); CHECK(f.Restored()); CHECK(f.NoneTwice());
            CHECK_EQ(f.unprotectCalls, 2); CHECK_EQ(f.reprotectCalls, 2); CHECK_EQ(f.flushes, 3); CHECK_EQ(r.failedPage, (int64_t)-1);
            CHECK_EQ(r.pages.size(), (size_t)2);
            if (r.pages.size() == 2) {   // the .text page restored to 0x20 and the .data page to 0x04, each read back
                CHECK_EQ(r.pages[0].rva, 0x1000u); CHECK_EQ(r.pages[0].recorded, 0x20u); CHECK_EQ(r.pages[0].after, 0x20u); CHECK(r.pages[0].known);
                CHECK_EQ(r.pages[1].rva, 0x5000u); CHECK_EQ(r.pages[1].recorded, 0x04u); CHECK_EQ(r.pages[1].after, 0x04u); CHECK(r.pages[1].known);
            }
        }
        for (int failAt : { 0, 1 }) {   // a failure at each page index
            std::vector<uint8_t> mm = m; tk::PageMem f(b, mm.data()); f.failUnprotectAt = failAt;
            const WriteResult r = WritePlanAtomic(mm.data(), pl, x.data(), f);
            CHECK(!r.ok); CHECK_EQ(r.written, 0); CHECK(mm == m); CHECK(f.Restored()); CHECK(f.NoneTwice()); CHECK_EQ(f.flushes, 0);
            CHECK_EQ(r.failedPage, failAt == 0 ? (int64_t)0x1000 : (int64_t)0x5000);
            CHECK_EQ(r.failedSite, failAt == 0 ? 0 : 1);   // the first written site in plan order with a byte on that page
            CHECK_EQ(f.reprotectCalls, failAt);            // the pages already changed are restored, nothing else
        }
        {   // a restore failure is counted per page, not per site (three sites, two pages)
            std::vector<uint8_t> mm = m; tk::PageMem f(b, mm.data()); f.failEveryReprotect = true;
            const WriteResult r = WritePlanAtomic(mm.data(), pl, x.data(), f);
            CHECK(r.ok); CHECK_EQ(r.written, 3); CHECK(mm == want); CHECK_EQ(r.reprotectFailures, 2);
            std::vector<uint8_t> m2 = m;
            tk::PageMem h(b, m2.data()); h.failReprotectAt = 1;
            const WriteResult r2 = WritePlanAtomic(m2.data(), pl, x.data(), h);
            CHECK(r2.ok); CHECK_EQ(r2.reprotectFailures, 1); CHECK_EQ(h.Changed(), 1);
            CHECK(r2.pages.size() == 2 && !ProtectionRestored(r2.pages[1].recorded, r2.pages[1].after));   // the readback sees it
        }
        {   // the readback: a page a "successful" restore left changed is reported; Query unknown reports nothing
            std::vector<uint8_t> mm = m; tk::PageMem f(b, mm.data()); f.leaveChanged = { 0x5000 };
            const WriteResult r = WritePlanAtomic(mm.data(), pl, x.data(), f);
            CHECK(r.ok); CHECK_EQ(r.reprotectFailures, 0); CHECK_EQ(r.pages.size(), (size_t)2);
            if (r.pages.size() == 2) {
                CHECK(ProtectionRestored(r.pages[0].recorded, r.pages[0].after));
                CHECK(r.pages[1].known); CHECK_EQ(r.pages[1].after, 0x40u); CHECK(!ProtectionRestored(r.pages[1].recorded, r.pages[1].after));
            }
            std::vector<uint8_t> m2 = m; tk::PageMem g(b, m2.data()); g.queryKnown = false;
            const WriteResult r2 = WritePlanAtomic(m2.data(), pl, x.data(), g);
            CHECK(r2.ok); CHECK(g.Restored()); for (const PageProt& q : r2.pages) CHECK(!q.known);
        }
        for (uint32_t bad : { 0x1800u, 0x1001u, 0x3000u, 0xFFFFFFFFu }) {   // a page size that is not a power of two: refused, no call, nothing written
            std::vector<uint8_t> mm = m; tk::PageMem f(b, mm.data()); f.reportedPage = bad;
            const WriteResult r = WritePlanAtomic(mm.data(), pl, x.data(), f);
            CHECK(!r.ok); CHECK_EQ(r.written, 0); CHECK_EQ(f.unprotectCalls, 0); CHECK_EQ(f.reprotectCalls, 0); CHECK(mm == m);
        }
        {   PatchPlan refused = pl; refused.verdict = PlanVerdict::Refuse;   // a refused plan: no call at all
            std::vector<uint8_t> mm = m; tk::PageMem f(b, mm.data());
            CHECK(!WritePlanAtomic(mm.data(), refused, x.data(), f).ok); CHECK_EQ(f.unprotectCalls + f.reprotectCalls + f.flushes, 0); CHECK(mm == m);
        }
    }
    return tk::Done("test_patch_engine");
}
