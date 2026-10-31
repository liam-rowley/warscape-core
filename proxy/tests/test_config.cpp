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
                               "proxy.exe_guard_force_mismatch", "proxy.runtime_patches" }) CHECK(c.values.count(k) == 1);
    }
    return tk::Done("test_config");
}
