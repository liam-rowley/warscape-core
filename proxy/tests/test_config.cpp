// Host test: config parsing (config.h) and the generated key table against the shipped default config.
#include "testkit.h"
#include "config.h"
#include "generated/tables.h"

using namespace wsp;
static const KeySpec kSpec[] = { { "proxy.enabled", kBool, "1" }, { "proxy.backend", kStr, "dxvk" }, { "proxy.minidump", kInt, "1" } };

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    {   // missing file: defaults, no warnings
        Config c = ParseConfig("", false, kSpec, 3);
        CHECK(!c.fileRead); CHECK(c.warnings.empty()); CHECK(c.Bool("proxy.enabled")); CHECK_EQ(c.Str("proxy.backend"), std::string("dxvk")); CHECK_EQ(c.Int("proxy.minidump"), 1L);
    }
    {   // valid values, CRLF, BOM, comments, case-insensitive section and key, trailing comment
        Config c = ParseConfig("\xEF\xBB\xBF; comment\r\n# other\r\n[Proxy]\r\nEnabled = false\r\nbackend=system ; use the windows d3d9\r\nminidump=2\r\n", true, kSpec, 3);
        CHECK(c.warnings.empty()); CHECK(!c.Bool("proxy.enabled")); CHECK_EQ(c.Str("proxy.backend"), std::string("system")); CHECK_EQ(c.Int("proxy.minidump"), 2L);
        CHECK(c.fromFile["proxy.backend"]);
    }
    {   // unknown key: logged, never fatal; bad bool and bad int fall back to the default
        Config c = ParseConfig("[proxy]\nbogus=1\nenabled=maybe\nminidump=two\n[other]\nx=1\n", true, kSpec, 3);
        CHECK_EQ(c.unknown.size(), (size_t)2); CHECK_EQ(c.unknown[0], std::string("proxy.bogus")); CHECK_EQ(c.unknown[1], std::string("other.x"));
        CHECK_EQ(c.warnings.size(), (size_t)4); CHECK(c.Bool("proxy.enabled")); CHECK_EQ(c.Int("proxy.minidump"), 1L);
        CHECK(!c.fromFile["proxy.enabled"]);
    }
    {   // duplicates (later wins, warned), a key outside any section, a line without '=', a broken section header
        Config c = ParseConfig("backend=system\n[proxy]\nbackend=system\nbackend=dxvk\njunk\n[proxy\n", true, kSpec, 3);
        CHECK_EQ(c.Str("proxy.backend"), std::string("dxvk")); CHECK_EQ(c.warnings.size(), (size_t)4);
    }
    {   // int edge cases
        std::string o;
        CHECK(Normalise(kInt, "-3", o) && o == "-3"); CHECK(Normalise(kInt, "+7", o) && o == "7"); CHECK(!Normalise(kInt, "", o)); CHECK(!Normalise(kInt, "1.5", o));
        CHECK(!Normalise(kInt, "123456789012", o)); CHECK(Normalise(kBool, "ON", o) && o == "1"); CHECK(Normalise(kBool, "off", o) && o == "0");
    }
    {   // W7 float parsing: by hand, locale-free; nan, inf, beyond float32, a comma decimal and empty text refused
        std::string o;
        for (const char* ok : { "600", "600.0", "-75.5", "1e3", "+2.5", "0.25", "1E-3", "3.4e38" }) { const bool r = Normalise(kFloat, ok, o); if (!r) printf("    refused '%s'\n", ok); CHECK(r); }
        CHECK(Normalise(kFloat, "+2.5", o) && o == "2.5");
        for (const char* bad : { "1,5", "nan", "inf", "-inf", "1e39", "", "1.", ".5", "1e", "0x10", "1.5f", " 1", "--1", "1e400" }) { const bool r = Normalise(kFloat, bad, o); if (r) printf("    accepted '%s'\n", bad); CHECK(!r); }
        double v = 0; CHECK(NumberOf("1e3", v) && v == 1000.0); CHECK(NumberOf("-75.5", v) && v == -75.5); CHECK(!NumberOf("1,5", v));
    }
    {   // W7 int32 bounds
        std::string o;
        CHECK(Normalise(kInt, "2147483647", o) && o == "2147483647"); CHECK(Normalise(kInt, "-2147483648", o) && o == "-2147483648");
        CHECK(!Normalise(kInt, "2147483648", o)); CHECK(!Normalise(kInt, "-2147483649", o)); CHECK(!Normalise(kInt, "99999999999", o));
    }
    {   // W7 a typed table with and without a range: clamped to the nearer bound with a warning that says so; an invalid value takes the
        // default with a warning that names the key's real type
        static const KeySpec typed[] = { { "gfx.dist", kFloat, "0", "0", "600.0" }, { "gfx.free", kFloat, "0" }, { "gfx.count", kInt, "0", "-5", "9" },
                                         { "gfx.low", kFloat, "0", "-150", "0" } };
        Config c = ParseConfig("[gfx]\ndist=1000\nfree=-1e6\ncount=12\nlow=-200.5\n", true, typed, 4);
        CHECK_EQ(c.Str("gfx.dist"), std::string("600.0")); CHECK_EQ(c.Float("gfx.dist"), 600.0);
        CHECK_EQ(c.Float("gfx.free"), -1e6);                                  // no range: as written
        CHECK_EQ(c.Int("gfx.count"), 9L); CHECK_EQ(c.Float("gfx.low"), -150.0);
        CHECK_EQ(c.warnings.size(), (size_t)3);
        for (const auto& w : c.warnings) printf("    %s\n", w.c_str());
        CHECK(c.warnings.size() == 3 && c.warnings[0].find("gfx.dist=1000 is above the maximum 600.0, clamped to 600.0") != std::string::npos);
        CHECK(c.warnings.size() == 3 && c.warnings[2].find("below the minimum -150") != std::string::npos);
        Config d = ParseConfig("[gfx]\ndist=-3\ncount=-5\n", true, typed, 4);
        CHECK_EQ(d.Float("gfx.dist"), 0.0); CHECK_EQ(d.Int("gfx.count"), -5L); CHECK_EQ(d.warnings.size(), (size_t)1);   // the bound itself is in range
        Config e = ParseConfig("[gfx]\ndist=1,5\ncount=1.5\nfree=nan\n", true, typed, 4);
        CHECK_EQ(e.Float("gfx.dist"), 0.0); CHECK_EQ(e.Int("gfx.count"), 0L); CHECK_EQ(e.Float("gfx.free"), 0.0);
        CHECK(e.warnings.size() == 3 && e.warnings[0].find("is not a valid number, using the default 0") != std::string::npos);
        CHECK(e.warnings.size() == 3 && e.warnings[1].find("is not a valid integer (int32)") != std::string::npos);
        Config f = ParseConfig("[gfx]\ndist=250.5\n", true, typed, 4);
        CHECK(f.warnings.empty()); CHECK_EQ(f.Float("gfx.dist"), 250.5); CHECK_EQ(f.Float("gfx.missing"), 0.0);
    }
    {   // the generated table parses the shipped default config with no warning, every key from the file, at the release values
        const std::string ini = tk::AdapterIni();
        CHECK(!ini.empty());
        Config c = ParseConfig(ini, true, gen::kKeys, gen::kKeyCount);
        CHECK(c.warnings.empty());
        for (const auto& w : c.warnings) printf("    warning: %s\n", w.c_str());
        for (size_t i = 0; i < gen::kKeyCount; ++i) CHECK(c.fromFile[gen::kKeys[i].id]);
        CHECK(c.Bool("proxy.enabled")); CHECK_EQ(c.Str("proxy.backend"), std::string("dxvk")); CHECK_EQ(c.Int("proxy.exe_guard"), 1L);
        CHECK_EQ(c.Int("proxy.exe_guard_force_mismatch"), 0L);
        // keys the core reads by name exist in the registry (a renamed key would silently read "")
        for (const char* k : { "proxy.enabled", "proxy.backend", "proxy.dxvk_path", "proxy.log_level", "proxy.minidump", "proxy.exe_guard",
                               "proxy.exe_guard_force_mismatch", "proxy.runtime_patches", "proxy.file_rules", "proxy.dxvk_wndproc_fix" }) {
            if (c.values.count(k) != 1) printf("    the core reads %s by name: add its config_keys row (docs/CONSUMING.md)\n", k);
            CHECK(c.values.count(k) == 1);
        }
    }
    return tk::Done("test_config");
}
