// test_null_adapter.cpp - the null game's own host test (W16): a game's proxy/tests folder (proxy/tools/layout.py proxy-tests) is compiled
// and run by proxy/tools/build.sh tests beside the core's, so this file exercises that hook on every CI run. It runs the core's adapter
// contract checkers (proxy/tests/adapter_checks.h) when the adapter has a console or a camera (the null adapter has neither: asserted),
// and checks that identity.json names the files build.sh smoke uses. A real game's tests here also hold its own console and camera numbers.
#include "testkit.h"
#include "adapter_checks.h"
#include "adapter.cpp"

using namespace wsp;

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    const GameAdapter& a = Adapter();
    const adck::SiteLookup site = adck::TableLookup(a.sites, a.nSites);
    CHECK(!a.console && !a.camera);   // the null game has neither; a game that has one runs the checker below
    if (a.console) for (const std::string& p : adck::ConsoleAdapterProblems(*a.console, site)) { printf("    %s\n", p.c_str()); CHECK(p.empty()); }
    if (a.camera) for (const std::string& p : adck::CameraAdapterProblems(*a.camera, site)) { printf("    %s\n", p.c_str()); CHECK(p.empty()); }
    // build.sh smoke names the stand-in exe, the mod folder and the config file from these three fields
    const std::string id = tk::ReadFile("adapter/identity.json");
    CHECK_EQ(tk::JsonField(id, "exe_name"), std::string("Game.exe"));
    CHECK_EQ(tk::JsonField(id, "mod_dir"), std::string("nullgame"));
    CHECK_EQ(tk::JsonField(id, "config_file"), std::string("nullgame.ini"));
    CHECK(!tk::AdapterIni().empty());   // the shipped config file is where identity.json says
    return tk::Done("test_null_adapter");
}
