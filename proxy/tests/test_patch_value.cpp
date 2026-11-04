// Host test: value rows (patch_value.h, W7): float32/int32 encoding against the stock values a game's distance rows hold, the resolution
// order (key at stock, scale, refusals, floor stock, equals stock), the effective copy through MakePatchPlan, ApplyPlanToBuffer and
// WritePlanAtomic at three bases, already-written, all-or-nothing, two rows on one key, the B41 shape, and the generated table.
#include "testkit.h"
#include <cmath>
#include <limits>
#include "patch_value.h"
#include "generated/tables.h"

using namespace wsp;
typedef std::vector<uint8_t> B;

static SiteDef Fixed(const char* id, uint32_t rva, B a, B st, B p, const char* key = nullptr) {
    SiteDef d{}; d.id = id; d.kind = kPatch; d.rva = rva; d.anchorLen = (uint8_t)a.size(); memcpy(d.anchor, a.data(), a.size());
    d.len = (uint8_t)st.size(); memcpy(d.stock, st.data(), st.size()); memcpy(d.patch, p.data(), p.size()); d.configKey = key; return d;
}
static SiteDef Value(const char* id, uint32_t rva, B a, B st, const char* key, uint8_t type, double scale = 1.0, bool floor = false) {
    SiteDef d = Fixed(id, rva, a, st, {}); d.valueKey = key; d.valueType = type; d.valueScale = scale; d.valueFloorStock = floor; return d;
}
static B F32(double v) { B b(4); EncodeF32(v, b.data()); return b; }
static B I32(int32_t v) { B b(4); EncodeI32(v, b.data()); return b; }
static B Bytes(const uint8_t* p) { return B(p, p + 4); }


// A game-like image: two float distances on one key (one followed at a ratio, one floored at stock), an int count, the B41 shape
// (mov dword [abs32], 0.25f with a relocation on the address) and a fixed row in .data.
static tk::Image Fixture() {
    tk::Image im = tk::GameLike();
    im.Put(0x1100, { 0xC7, 0x41, 0x48, 0x00, 0x00, 0xC8, 0x42 });                           // mov [ecx+0x48], 100.0f
    im.Put(0x1180, { 0xC7, 0x41, 0x4C, 0x00, 0x00, 0x48, 0x43 });                           // mov [ecx+0x4c], 200.0f
    im.Put(0x1200, { 0xB9, 0x05, 0x00, 0x00, 0x00 });                                       // mov ecx, 5
    im.Put(0x1300, { 0xC7, 0x05, 0x00, 0xB0, 0x40, 0x00, 0x00, 0x00, 0x80, 0x3E });         // mov dword [0x40b000], 0.25f
    im.Put(0x5010, { 0x11, 0x22, 0x33, 0x44, 0x00, 0x00, 0x48, 0x42 });                     // tag, 50.0f
    im.relocs = { 0x1302 };
    im.BuildRelocs();
    return im;
}
static std::vector<SiteDef> Sites() {
    return { Value("dist.unit", 0x1100, { 0xC7, 0x41, 0x48 }, F32(100), "gfx.dist", kValueF32, 1.0, true),
             Value("dist.rope", 0x1180, { 0xC7, 0x41, 0x4C }, F32(200), "gfx.dist", kValueF32, 2.0),
             Value("grass.n", 0x1200, { 0xB9 }, I32(5), "gfx.grass", kValueI32),
             Value("frame.time", 0x1300, { 0xC7, 0x05, 0x00, 0xB0, 0x40, 0x00 }, F32(0.25), "gfx.frame", kValueF32),
             Fixed("lod.range", 0x5010, { 0x11, 0x22, 0x33, 0x44 }, F32(50), F32(100), "gfx.fixed") };
}
static const KeySpec kKeys[] = { { "gfx.dist", kFloat, "0", "0", "1000" }, { "gfx.grass", kInt, "0", "0", "16" }, { "gfx.frame", kFloat, "0" },
                                 { "gfx.fixed", kBool, "1" } };
static Config Cfg(const std::string& ini) { return ParseConfig(ini, true, kKeys, 4); }

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    {   // encode/decode vectors for the stock values distance rows hold
        struct V { double v; B b; } fv[] = { { 50, { 0x00, 0x00, 0x48, 0x42 } }, { 100, { 0x00, 0x00, 0xC8, 0x42 } }, { 150, { 0x00, 0x00, 0x16, 0x43 } },
                                             { 200, { 0x00, 0x00, 0x48, 0x43 } }, { 0.25, { 0x00, 0x00, 0x80, 0x3E } }, { -75, { 0x00, 0x00, 0x96, 0xC2 } } };
        for (auto& x : fv) { CHECK(F32(x.v) == x.b); CHECK_EQ(DecodeF32(x.b.data()), x.v); }
        CHECK(I32(5) == B({ 0x05, 0x00, 0x00, 0x00 })); CHECK(I32(9) == B({ 0x09, 0x00, 0x00, 0x00 })); CHECK(I32(-1) == B({ 0xFF, 0xFF, 0xFF, 0xFF }));
        CHECK_EQ(DecodeI32(I32(9).data()), 9.0); CHECK_EQ(DecodeI32(I32(-150).data()), -150.0);
    }
    const std::vector<SiteDef> s = Sites();
    {   // the resolution order
        const SiteDef& unit = s[0]; const SiteDef& rope = s[1]; const SiteDef& grass = s[2];
        SiteValue v = ResolveSiteValue(rope, 0); CHECK(v.action == ValueAction::Stock); CHECK_EQ(v.why, std::string("key at stock")); CHECK(Bytes(v.bytes) == F32(200));
        v = ResolveSiteValue(rope, 100); CHECK(v.action == ValueAction::Stock); CHECK_EQ(v.why, std::string("equals stock"));   // 100 x 2 = stock 200
        SiteDef sc = rope; sc.valueScale = 0.75;
        v = ResolveSiteValue(sc, 400); CHECK(v.action == ValueAction::Write); CHECK_EQ(v.written, 300.0); CHECK(Bytes(v.bytes) == F32(300));
        v = ResolveSiteValue(unit, 80); CHECK(v.action == ValueAction::Stock); CHECK_EQ(v.why, std::string("equals stock")); CHECK(Bytes(v.bytes) == F32(100));   // floor
        v = ResolveSiteValue(unit, 600); CHECK(v.action == ValueAction::Write); CHECK_EQ(v.written, 600.0); CHECK(Bytes(v.bytes) == F32(600));
        SiteDef nofloor = unit; nofloor.valueFloorStock = 0;
        v = ResolveSiteValue(nofloor, 80); CHECK(v.action == ValueAction::Write); CHECK(Bytes(v.bytes) == F32(80));   // below stock without the floor
        v = ResolveSiteValue(nofloor, -75); CHECK(v.action == ValueAction::Write); CHECK(Bytes(v.bytes) == F32(-75));
        v = ResolveSiteValue(grass, 9); CHECK(v.action == ValueAction::Write); CHECK(Bytes(v.bytes) == I32(9));
        v = ResolveSiteValue(grass, 6.5); CHECK(Bytes(v.bytes) == I32(6)); v = ResolveSiteValue(grass, 7.5); CHECK(Bytes(v.bytes) == I32(8));   // nearest, ties even
        v = ResolveSiteValue(grass, 7.4); CHECK(Bytes(v.bytes) == I32(7)); CHECK_EQ(v.written, 7.0);
        for (double bad : { std::numeric_limits<double>::quiet_NaN(), std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity() }) {
            v = ResolveSiteValue(unit, bad); CHECK(v.action == ValueAction::Refused); CHECK(Bytes(v.bytes) == F32(100));
        }
        SiteDef big = grass; big.valueScale = 1000;
        v = ResolveSiteValue(big, 3e6); CHECK(v.action == ValueAction::Refused); CHECK(v.why.find("outside int32") != std::string::npos); CHECK(Bytes(v.bytes) == I32(5));
        v = ResolveSiteValue(big, 2147483.0); CHECK(v.action == ValueAction::Write); CHECK(Bytes(v.bytes) == I32(2147483000));
        SiteDef fbig = rope; fbig.valueScale = 1e10;
        v = ResolveSiteValue(fbig, 1e30); CHECK(v.action == ValueAction::Refused); CHECK(v.why.find("outside float32") != std::string::npos);
        SiteDef three = rope; three.len = 3;
        CHECK(ResolveSiteValue(three, 5).action == ValueAction::Refused);
    }
    const tk::Image im = Fixture();
    const Config cfg = Cfg("[gfx]\ndist=600\ngrass=9\nframe=0.5\n");
    CHECK(cfg.warnings.empty());
    {   // the effective copy: the plan, the pure apply and the atomic write at three bases; only the value bytes change
        const EffectiveSites e = ResolveSites(s.data(), s.size(), cfg);
        CHECK_EQ(e.nValueRows, 4); CHECK_EQ(e.nValueWrites, 4); CHECK_EQ(e.nValueRefused, 0);
        CHECK(Bytes(e.sites[0].patch) == F32(600)); CHECK(Bytes(e.sites[1].patch) == F32(1200));   // two rows, one key, the second at x2
        CHECK(Bytes(e.sites[2].patch) == I32(9)); CHECK(Bytes(e.sites[3].patch) == F32(0.5)); CHECK(Bytes(e.sites[4].patch) == F32(100));
        for (size_t i = 0; i < s.size(); ++i) { CHECK(e.enabled[i]); CHECK(Bytes(s[i].stock) == Bytes(e.sites[i].stock)); }
        CHECK(Bytes(s[0].patch) == B(4, 0));                                                        // the generated table is never changed
        CHECK(ValueLine(e.sites[0], e.values[0], cfg) == "patch_engine: value dist.unit <- gfx.dist=600 (x1, floor stock 100): 600 f32 [00 00 16 44]");
        for (uint32_t base : { 0x400000u, 0x01230000u, 0x7ff00000u }) {
            std::vector<uint8_t> m = im.Mapped(base);
            PeInfo pe; ImageView v = tk::MappedView(m, pe);
            const PatchPlan pl = MakePatchPlan(v, base - 0x400000u, e.sites.data(), e.sites.size(), e.enabled.get());
            if (pl.verdict != PlanVerdict::Apply) printf("    at 0x%08x: %s\n", (unsigned)base, pl.reason.c_str());
            CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nWrite, 5);
            std::vector<uint8_t> pure = m; ApplyPlanToBuffer(pure.data(), pl, e.sites.data());
            std::vector<uint8_t> mm = m; tk::PageMem f(im, mm.data());
            const WriteResult w = WritePlanAtomic(mm.data(), pl, e.sites.data(), f);
            CHECK(w.ok); CHECK_EQ(w.written, 5); CHECK(mm == pure);
            CHECK(f.Restored()); CHECK(f.NoneTwice());   // W33 (C3): four of the five sites share page 0x1000
            for (size_t i = 0; i < m.size(); ++i) {   // every changed byte is inside a site's 4 value bytes
                if (mm[i] == m[i]) continue;
                bool in = false; for (auto& c : pl.sites) in |= i >= c.valueRva && i < c.valueRva + 4u;
                CHECK(in);
            }
            CHECK(Bytes(&mm[0x1103]) == F32(600)); CHECK(Bytes(&mm[0x1183]) == F32(1200)); CHECK(Bytes(&mm[0x1201]) == I32(9));
            CHECK(Bytes(&mm[0x1306]) == F32(0.5)); CHECK_EQ(Rd32(&mm[0x1302]), 0x40B000u + (base - 0x400000u));   // B41: the address untouched
            // the same plan again on the written image: every value row is done
            PeInfo pe2; ImageView v2 = tk::MappedView(mm, pe2);
            const PatchPlan again = MakePatchPlan(v2, base - 0x400000u, e.sites.data(), e.sites.size(), e.enabled.get());
            CHECK(again.verdict == PlanVerdict::NothingToDo); CHECK_EQ(again.nDone, 5);
        }
    }
    {   // keys at stock: every value row checked, none written; the fixed row still written
        const Config c0 = Cfg("");
        const EffectiveSites e = ResolveSites(s.data(), s.size(), c0);
        CHECK_EQ(e.nValueWrites, 0);
        std::vector<uint8_t> m = im.Mapped(0x01230000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
        const PatchPlan pl = MakePatchPlan(v, 0x01230000 - 0x400000, e.sites.data(), e.sites.size(), e.enabled.get());
        CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nWrite, 1); CHECK(pl.sites[4].write);
        for (int i = 0; i < 4; ++i) CHECK(pl.sites[i].state == SiteState::Stock && !pl.sites[i].write);
        CHECK(ValueLine(e.sites[0], e.values[0], c0) == "patch_engine: value dist.unit <- gfx.dist=0 (x1, floor stock 100): stock (key at stock)");
        // ... and a stock value row whose bytes are not stock (another build) still refuses the plan: it is part of the exe's identity
        tk::Image b = im; b.Put(0x1201, { 0x07 });
        std::vector<uint8_t> mb = b.Mapped(0x01230000); PeInfo peb; ImageView vb = tk::MappedView(mb, peb);
        CHECK(MakePatchPlan(vb, 0x01230000 - 0x400000, e.sites.data(), e.sites.size(), e.enabled.get()).verdict == PlanVerdict::Refuse);
    }
    {   // a refused value: that site stays stock, the other sites are still written
        std::vector<SiteDef> x = s; x[2].valueScale = 1e9;   // grass 9 x 1e9: outside int32
        const EffectiveSites e = ResolveSites(x.data(), x.size(), cfg);
        CHECK_EQ(e.nValueRefused, 1); CHECK(e.values[2].action == ValueAction::Refused); CHECK(!e.enabled[2]); CHECK(Bytes(e.sites[2].patch) == I32(5));
        CHECK(ValueLine(e.sites[2], e.values[2], cfg).find("REFUSED 9000000000 is outside int32, site left stock") != std::string::npos);
        std::vector<uint8_t> m = im.Mapped(0x7ff00000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
        const PatchPlan pl = MakePatchPlan(v, 0x7ff00000 - 0x400000, e.sites.data(), e.sites.size(), e.enabled.get());
        CHECK(pl.verdict == PlanVerdict::Apply); CHECK_EQ(pl.nWrite, 4); CHECK(!pl.sites[2].write); CHECK(pl.sites[2].state == SiteState::Stock);
        std::vector<uint8_t> mm = m; tk::PageMem f(im, mm.data()); CHECK(WritePlanAtomic(mm.data(), pl, e.sites.data(), f).ok);
        CHECK(f.Restored()); CHECK(f.NoneTwice());
        CHECK(Bytes(&mm[0x1201]) == I32(5)); CHECK(Bytes(&mm[0x1103]) == F32(600));
    }
    {   // a bad anchor on any row (a value row or the fixed row) still refuses everything
        const EffectiveSites e = ResolveSites(s.data(), s.size(), cfg);
        for (uint32_t at : { 0x1101u, 0x1300u, 0x5011u }) {
            tk::Image b = im; b.Put(at, { 0x99 });
            std::vector<uint8_t> m = b.Mapped(0x01230000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
            const PatchPlan pl = MakePatchPlan(v, 0x01230000 - 0x400000, e.sites.data(), e.sites.size(), e.enabled.get());
            CHECK(pl.verdict == PlanVerdict::Refuse); CHECK_EQ(pl.nWrite, 0);
            std::vector<uint8_t> mm = m; tk::PageMem f(b, mm.data()); CHECK(!WritePlanAtomic(mm.data(), pl, e.sites.data(), f).ok); CHECK(mm == m);
            CHECK_EQ(f.unprotectCalls, 0);
        }
    }
    {   // a value row whose current bytes already hold the resolved value counts as done; one holding neither stock nor it refuses
        const EffectiveSites e = ResolveSites(s.data(), s.size(), cfg);
        tk::Image b = im; b.Put(0x1201, I32(9));
        std::vector<uint8_t> m = b.Mapped(0x400000); PeInfo pe; ImageView v = tk::MappedView(m, pe);
        PatchPlan pl = MakePatchPlan(v, 0, e.sites.data(), e.sites.size(), e.enabled.get());
        CHECK(pl.verdict == PlanVerdict::Apply); CHECK(pl.sites[2].state == SiteState::Done); CHECK_EQ(pl.nWrite, 4); CHECK_EQ(pl.nDone, 1);
        b.Put(0x1201, I32(11)); m = b.Mapped(0x400000); PeInfo pe2; ImageView v2 = tk::MappedView(m, pe2);
        pl = MakePatchPlan(v2, 0, e.sites.data(), e.sites.size(), e.enabled.get());
        CHECK(pl.verdict == PlanVerdict::Refuse); CHECK(pl.sites[2].state == SiteState::BadStock);
    }
    {   // the generated table: every value row is a 4-byte patch whose stock round-trips through its encoding (gen_tables checks it too)
        int rows = 0;
        for (size_t i = 0; i < gen::kSiteCount; ++i) {
            const SiteDef& d = gen::kSites[i];
            if (!d.valueKey) { CHECK(d.valueType == kValueNone); continue; }
            ++rows;
            CHECK(d.kind == kPatch); CHECK_EQ((int)d.len, 4); CHECK(d.valueType == kValueF32 || d.valueType == kValueI32); CHECK(d.valueScale > 0);
            double sv = 0; CHECK(StockValue(d, sv));
            B back(4); if (d.valueType == kValueF32) EncodeF32(sv, back.data()); else EncodeI32((int32_t)sv, back.data());
            CHECK(back == Bytes(d.stock));
            bool keyed = false; for (size_t k = 0; k < gen::kKeyCount; ++k) keyed |= !strcmp(gen::kKeys[k].id, d.valueKey) && (gen::kKeys[k].type == kFloat || gen::kKeys[k].type == kInt);
            CHECK(keyed);
            const Config c = ParseConfig(tk::AdapterIni(), true, gen::kKeys, gen::kKeyCount);   // the shipped ini resolves it without a refusal
            CHECK(ResolveSiteValue(d, c.Float(d.valueKey)).action != ValueAction::Refused);
        }
        printf("    generated table: %d value row(s)\n", rows);
    }
    return tk::Done("test_patch_value");
}
