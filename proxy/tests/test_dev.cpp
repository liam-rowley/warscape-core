// test_dev.cpp - host tests for the dev side's pure core (J3): file rules, the pack index, the scene state machine, the control
// channel grammar (verbs, ids, targets), the timeline JSON; plus source lints that keep the dev drivers inside the guard's plan,
// game-agnostic and on registered config keys. Built and run by proxy/tools/build.sh tests.
#include "testkit.h"
#include "filerules.h"
#include "pack.h"
#include "devcore.h"
#include "generated/tables.h"
#include <cmath>
#include <regex>
#include <set>

using namespace wsp;

static std::string Strip(const std::string& s) {   // drop // and /* */ comments and string literals
    std::string o; size_t i = 0;
    while (i < s.size()) {
        if (s.compare(i, 2, "//") == 0) { while (i < s.size() && s[i] != '\n') ++i; continue; }
        if (s.compare(i, 2, "/*") == 0) { size_t e = s.find("*/", i + 2); i = e == std::string::npos ? s.size() : e + 2; continue; }
        if (s[i] == '"') { ++i; while (i < s.size() && s[i] != '"') { if (s[i] == '\\') ++i; ++i; } ++i; o += "\"\""; continue; }
        o += s[i++];
    }
    return o;
}

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    const std::wstring game = L"c:\\games\\some game\\";
    {   // paths relative to the game folder
        CHECK(RelToGame(L"C:\\Games\\Some Game\\data\\UI\\X.lua", game) == L"data\\ui\\x.lua");
        CHECK(RelToGame(L"\\\\?\\C:\\Games\\Some Game\\data\\a.pack", game) == L"data\\a.pack");
        CHECK(RelToGame(L".\\data/ui/templates/rml.lua", game) == L"data\\ui\\templates\\rml.lua");
        CHECK(RelToGame(L"D:\\elsewhere\\a.txt", game) == L"");
        CHECK(RelToGame(L"", game) == L"");
    }
    {   // rule parsing and matching
        std::vector<std::string> w;
        auto r = ParseRules("# c\nredirect data\\ui\\x.lua -> mod\\x.lua\nfail data/bad.txt\nadd data\\zz.pack -> mod\\packs\\zz.pack\n"
                            "movie-fail movies\\intro.bik\nredirect data\\pre\\* -> mod\\pre\\\nbogus x\nredirect onlyleft\nfail\n", w);
        CHECK_EQ(r.size(), (size_t)5); CHECK_EQ(w.size(), (size_t)3);
        CHECK(r[0].act == RuleAct::Redirect && r[0].from == L"data\\ui\\x.lua" && r[0].to == L"mod\\x.lua");
        CHECK(r[1].act == RuleAct::Fail && r[1].from == L"data\\bad.txt");
        CHECK(r[2].act == RuleAct::Add); CHECK(r[3].space == RuleSpace::Movie); CHECK(r[4].prefix && r[4].from == L"data\\pre\\");
        CHECK(MatchRule(r, RuleSpace::File, L"data\\ui\\x.lua") == &r[0]);
        CHECK(MatchRule(r, RuleSpace::File, L"data\\ui\\x.luac") == nullptr);
        CHECK(MatchRule(r, RuleSpace::File, L"movies\\intro.bik") == nullptr);   // a movie rule never matches a file open
        CHECK(MatchRule(r, RuleSpace::Movie, L"movies\\intro.bik") == &r[3]);
        CHECK(MatchRule(r, RuleSpace::File, L"data\\pre\\a\\b.txt") == &r[4]);
        CHECK(RuleTarget(r[4], L"data\\pre\\a\\b.txt", L"G:\\") == L"G:\\mod\\pre\\a\\b.txt");
        CHECK(RuleTarget(r[0], L"data\\ui\\x.lua", L"G:\\") == L"G:\\mod\\x.lua");
        FileRule abs = MakeRule(RuleSpace::File, RuleAct::Redirect, "a.txt", "C:\\x\\a.txt", "t");
        CHECK(RuleTarget(abs, L"a.txt", L"G:\\") == L"C:\\x\\a.txt");
        CHECK(IsReadOnlyOpen(0x80000000UL, 3)); CHECK(IsReadOnlyOpen(0x80, 3));
        CHECK(!IsReadOnlyOpen(0x40000000UL, 3)); CHECK(!IsReadOnlyOpen(0x80000000UL, 2)); CHECK(!IsReadOnlyOpen(0x80000000UL | 0x2, 3));
        CHECK(WildMatch(L"*.pack", L"zz_dev.pack")); CHECK(WildMatch(L"*", L"x")); CHECK(!WildMatch(L"*.pack", L"zz.pak")); CHECK(WildMatch(L"z?.pack", L"zz.pack"));
        std::wstring d, n; SplitDir(L"data\\zz.pack", d, n); CHECK(d == L"data\\" && n == L"zz.pack");
        SplitDir(L"top.pack", d, n); CHECK(d == L"" && n == L"top.pack");
    }
    {   // pack index (the same bytes build_dev_pack.py / pack_list.py read and write)
        std::string idx; auto add = [&](const char* name, uint32_t sz) { idx.append((const char*)&sz, 4); idx += name; idx += '\0'; };
        add("Movies/A.bik", 10); add("movies\\b.bik", 5);
        std::string buf = "PFH0"; uint32_t h[5] = { 4, 0, 0, 2, (uint32_t)idx.size() }; buf.append((const char*)h, 20); buf += idx;
        CHECK_EQ(PackIndexBytes((const unsigned char*)buf.data(), buf.size()), (uint64_t)idx.size());
        PackIndex px = ParsePackIndex((const unsigned char*)buf.data(), buf.size());
        CHECK(px.error.empty()); CHECK_EQ(px.type, 4u); CHECK_EQ(px.entries.size(), (size_t)2);
        CHECK(px.entries[0].path == "movies\\a.bik"); CHECK_EQ(px.entries[0].offset, (uint64_t)(24 + idx.size()));
        CHECK_EQ(px.entries[1].offset, (uint64_t)(24 + idx.size() + 10));
        CHECK(PackAt(px, 24 + idx.size() + 12) == &px.entries[1]); CHECK(PackAt(px, 5) == nullptr);
        CHECK(PackFind(px, "movies\\b.bik") == &px.entries[1]);
        CHECK(!ParsePackIndex((const unsigned char*)"PFH1xxxxxxxxxxxxxxxxxxxxxx", 26).error.empty());
        CHECK(!ParsePackIndex((const unsigned char*)buf.data(), buf.size() - 3).error.empty());   // truncated index
    }
    {   // scene state machine
        SceneTracker s;
        CHECK(s.Compute(0) == "intro");
        s.OnFrontendMovie(true, 1); CHECK(s.Compute(1) == "frontend");            // background movie, no Lua yet
        s.OnPump("frontend", 2); CHECK(s.Compute(2.5) == "frontend");
        CHECK(s.Compute(10) == "frontend");                                        // sub-screens do not pump: still front end
        s.OnLoadRequested("battle"); CHECK(s.Compute(10.1) == "loading");
        s.OnFrontendMovie(false, 11); CHECK(s.Compute(11) == "loading");
        s.OnPump("battle", 20); CHECK(s.Compute(20) == "battle"); CHECK(s.loadTarget.empty());
        s.OnBattleState(0, 1, 20); CHECK(s.Compute(20.1) == "battle_deploy");
        s.OnBattleState(0, 0, 21); s.OnPump("battle", 21); CHECK(s.Compute(21) == "battle");
        s.OnBattleState(1, 0, 22); s.OnPump("battle", 22); CHECK(s.Compute(22) == "naval");
        CHECK(s.Compute(26) == "loading");                                         // battle pumps stopped
        s.OnLoadRequested("frontend"); s.OnPump("battle", 30); CHECK(s.Compute(30) == "loading");   // asked to leave: not battle any more
        s.OnPump("frontend", 40); CHECK(s.Compute(40) == "frontend");
        std::string from; SceneTracker t; CHECK(!t.Update(0)); t.OnPump("frontend", 1); CHECK(t.Update(1, &from)); CHECK(from == "intro" && t.scene == "frontend");
        SceneTracker u; u.OnFrontendMovie(true, 0); u.OnFrontendMovie(false, 5); CHECK(u.Compute(5) == "loading");   // no Lua, movie gone
        SceneTracker c; c.OnPump("frontend", 0); c.OnLoadRequested("campaign"); c.OnPump("frontend", 1); CHECK(c.Compute(1) == "loading");
        c.OnPump("campaign", 9); CHECK(c.Compute(9) == "campaign");
        SceneTracker b; b.OnPump("frontend", 0); b.OnPump("battle", 5); b.OnLoadRequested("frontend"); CHECK(b.Compute(6) == "loading");
        b.OnFrontendMovie(true, 7); CHECK(b.Compute(30) == "frontend"); CHECK(b.loadTarget.empty());   // back from battle on a non-pumping screen
        CHECK(IsSceneName("battle_deploy")); CHECK(!IsSceneName("menu"));
    }
    {   // control grammar
        CHECK(ValidCtlId("j3-20261029T080000Z-1234")); CHECK(ValidCtlId("a.b_c")); CHECK(!ValidCtlId("")); CHECK(!ValidCtlId("_x"));
        CHECK(!ValidCtlId(".x")); CHECK(!ValidCtlId("a b")); CHECK(!ValidCtlId("a/b")); CHECK(!ValidCtlId(std::string(65, 'a')));
        CtlRequest r = ParseCtl("ping\r\n"); CHECK(r.error.empty() && r.verb == "ping");
        r = ParseCtl("ping now"); CHECK(!r.error.empty());
        r = ParseCtl("\xEF\xBB\xBFstate"); CHECK(r.error.empty() && r.verb == "state");
        r = ParseCtl("log hello world 30"); CHECK(r.error.empty() && r.arg == "hello world 30");
        r = ParseCtl("log"); CHECK(!r.error.empty());
        r = ParseCtl("lua game_mod/lua/probes/list_maps.lua 45"); CHECK(r.error.empty() && r.arg == "game_mod/lua/probes/list_maps.lua" && r.timeoutS == 45);
        r = ParseCtl("lua C:\\x y\\p.lua"); CHECK(r.error.empty() && r.arg == "C:\\x y\\p.lua" && r.timeoutS == 0);
        r = ParseCtl("lua"); CHECK(!r.error.empty());
        r = ParseCtl("lua p.lua 20 -- pose=a;x=1"); CHECK(r.error.empty() && r.arg == "p.lua" && r.timeoutS == 20 && r.luaArgs == "pose=a;x=1");
        r = ParseCtl("lua p.lua"); CHECK(r.error.empty() && r.luaArgs.empty());
        r = ParseCtl("lua a.lua 30 --"); CHECK(r.error.empty() && r.arg == "a.lua" && r.luaArgs.empty() && r.timeoutS == 30);   // empty args (J43)
        r = ParseCtl("lua a.lua 30 -- x=1"); CHECK(r.error.empty() && r.arg == "a.lua" && r.luaArgs == "x=1");
        r = ParseCtl("perf 10"); CHECK(r.error.empty() && r.arg == "10" && r.timeoutS == 20);
        r = ParseCtl("perf 0"); CHECK(!r.error.empty());
        r = ParseCtl("perf 61"); CHECK(!r.error.empty());
        r = ParseCtl("perf"); CHECK(!r.error.empty());
        r = ParseCtl("perf x 10"); CHECK(!r.error.empty());
        { FrameStats e = ComputeFrameStats({}); CHECK(e.frames == 0 && e.p50 == 0); }
        // J44: a 1.5 ms frame at an uptime of 1e12 ticks (10 MHz QPC, ~28 h) keeps its precision; negative and zero freq give 0
        { const int64_t f = 10000000, t0 = 1000000000000LL; CHECK(std::fabs(PerfDeltaMs((t0 + 15000) - t0, f) - 1.5) < 1e-9);
          CHECK(std::fabs(PerfDeltaMs(25000000, f) - 2500.0) < 1e-9); CHECK(PerfDeltaMs(-1, f) == 0.0 && PerfDeltaMs(5, 0) == 0.0); }
        { std::vector<double> d; for (int i = 1; i <= 100; ++i) d.push_back((double)i); FrameStats s = ComputeFrameStats(d);
          CHECK(s.frames == 100 && s.p50 == 50 && s.p99 == 99 && s.max == 100 && s.mean == 50.5); }
        { FrameStats s = ComputeFrameStats({16.0, 17.0, 90.0}); CHECK(s.p50 == 17.0 && s.p99 == 90.0 && s.max == 90.0); }
        r = ParseCtl("waitfor battle_deploy|naval 120"); CHECK(r.error.empty() && r.scenes.size() == 2 && r.timeoutS == 120);
        r = ParseCtl("waitfor frontend"); CHECK(r.error.empty() && r.scenes.size() == 1 && r.timeoutS == 0);
        r = ParseCtl("waitfor menu 10"); CHECK(r.error.find("unknown scene 'menu'") != std::string::npos);
        r = ParseCtl("autostart battle:land_small 90"); CHECK(r.error.empty() && r.target.kind == "battle" && r.target.preset == "land_small" && r.timeoutS == 90);
        r = ParseCtl("autostart campaign:new:europe:france"); CHECK(r.error.empty() && r.target.mode == "new" && r.target.campaign == "europe" && r.target.faction == "france");
        r = ParseCtl("autostart campaign:continue"); CHECK(r.error.empty() && r.target.mode == "continue");
        r = ParseCtl("reset campaign:Autosave 1 60"); CHECK(r.error.empty() && r.target.mode == "save" && r.target.save == "Autosave 1" && r.timeoutS == 60);
        r = ParseCtl("reset frontend"); CHECK(r.error.empty() && r.target.kind == "frontend");
        r = ParseCtl("autostart battle:"); CHECK(!r.error.empty());
        r = ParseCtl("autostart battle:../x"); CHECK(!r.error.empty());
        r = ParseCtl("autostart campaign:new:europe"); CHECK(!r.error.empty());
        r = ParseCtl("autostart moon"); CHECK(r.error.find("unknown target") != std::string::npos);
        r = ParseCtl("dance"); CHECK(r.error.find("unknown verb 'dance'") != std::string::npos && r.error.find("waitfor") != std::string::npos);
        r = ParseCtl(""); CHECK(!r.error.empty());
        r = ParseCtl("exit"); CHECK(r.error.empty());
        CHECK_EQ(CtlDefaultTimeout("lua"), 30.0); CHECK_EQ(CtlDefaultTimeout("ping"), 10.0);
    }
    {   // timeline and JSON
        CHECK(UtcIso(0) == "1970-01-01T00:00:00.000Z");
        CHECK(UtcIso(1793260276862LL) == "2026-10-29T07:51:16.862Z");
        CHECK(UtcIso(951782400000LL) == "2000-02-29T00:00:00.000Z");
        CHECK(JsonEsc("a\"b\\c\nd\x01") == "a\\\"b\\\\c\\nd\\u0001");
        Timeline t; t.launchId = "L"; t.processStartMs = 1000;
        CHECK(t.Add("dllmain", "", 1500)); CHECK(t.Add("movie_open", "movies\\a.bik", 2000)); CHECK(t.Has("dllmain")); CHECK(!t.Has("exit"));
        const std::string j = t.Json();
        CHECK(j.find("\"t_ms\": 500") != std::string::npos); CHECK(j.find("movies\\\\a.bik") != std::string::npos);
        CHECK(j.find("\"process_start_utc\": \"1970-01-01T00:00:01.000Z\"") != std::string::npos);
        for (size_t i = 0; i < Timeline::kMax; ++i) t.Add("x", "", 0);
        CHECK_EQ(t.marks.size(), Timeline::kMax);
    }
    {   // source lints
        // the dev side starts after the plan, and only runs when the plan allows hooks (pass-through: nothing)
        const std::string dm = Strip(tk::ReadFile("core/dllmain.cpp"));
        CHECK(dm.find("PatchesRun();") < dm.find("DevInit();"));
        const std::string dv = Strip(tk::ReadFile("core/dev.cpp"));
        const size_t gate = dv.find("if (!rt.plan.engineHooks || !rt.plan.d3dHooks)"), act = dv.find("s_active = true;");
        CHECK(gate != std::string::npos && act != std::string::npos && gate < act);
        CHECK(dv.find("if (!k.Any()) return;") < gate);   // no dev key: return before anything (the skeleton's behaviour)
        const std::string lb = Strip(tk::ReadFile("core/luabridge.cpp"));
        CHECK(lb.find("Rt().plan.engineReads") != std::string::npos);
        CHECK(lb.find("luaL_error") == std::string::npos && lb.find("luaL_check") == std::string::npos);   // never raise from C
        CHECK(lb.find("lua_call") == std::string::npos && lb.find("lua_pcall") == std::string::npos);    // never call into Lua from C
        const std::string fl = Strip(tk::ReadFile("core/files.cpp"));
        CHECK(fl.find("VirtualProtect") == std::string::npos);   // slots are written by hooks.cpp only
        // the new core files name no game (they move to warscape-core)
        for (const char* f : { "dev.cpp", "dev.h", "devcore.h", "files.cpp", "filerules.h", "pack.h", "hooks.cpp", "luabridge.cpp" }) {
            std::string s = tk::ReadFile(std::string("core/") + f);
            CHECK(!s.empty());
            for (size_t k; (k = s.find("empire-remastered")) != std::string::npos;) s.erase(k, 17);
            const bool named = s.find("apoleon") != std::string::npos || s.find("mpire") != std::string::npos;
            if (named) { printf("    %s names a game\n", f); CHECK(!named); }
        }
        // every dev.* key the drivers read is a registered config key, and every registered dev key is read
        std::set<std::string> known; for (size_t i = 0; i < gen::kKeyCount; ++i) known.insert(gen::kKeys[i].id);
        const std::string raw = tk::ReadFile("core/dev.cpp");
        const std::regex re("cfg\\.(Bool|Str|Int)\\(\"(dev\\.[a-z_]+)\"\\)");
        std::set<std::string> read;
        for (std::sregex_iterator it(raw.begin(), raw.end(), re), e; it != e; ++it) read.insert((*it)[2]);
        CHECK(read.size() >= 10);
        // the map check counts only the LOAD's probes (J3 review finding 1): Autostart forgets the front end's map-list walk after
        // autostart.lua returns and before it waits for the battle, and the result carries how long after the request the probe came
        {
            const size_t a = raw.find("Outcome Autostart("), lua = raw.find("autostart.lua", a), reset = raw.find("FilesMapReset();", a),
                         wait = raw.find("WaitScene(want", a);
            CHECK(a != std::string::npos && lua != std::string::npos && reset != std::string::npos && wait != std::string::npos);
            CHECK(lua < reset && reset < wait);
            CHECK(raw.find("map_folder_loaded_after_request_ms") != std::string::npos);
            const std::string fl = tk::ReadFile("core/files.cpp");
            CHECK(fl.find("void FilesMapReset()") != std::string::npos && fl.find("s_lastMap.clear()") != std::string::npos);
        }
        for (const std::string& k : read) if (!known.count(k)) { printf("    dev.cpp reads %s, not in config_keys\n", k.c_str()); CHECK(false); }
        for (const std::string& k : known) if (k.rfind("dev.", 0) == 0 && !read.count(k)) { printf("    %s is registered but dev.cpp never reads it\n", k.c_str()); CHECK(false); }
        // every dev key defaults off and ships off (release value = default for the non-switch keys)
        for (size_t i = 0; i < gen::kKeyCount; ++i) {
            const std::string id = gen::kKeys[i].id;
            if (id.rfind("dev.", 0) != 0 || gen::kKeys[i].type != kBool) continue;
            CHECK(std::string(gen::kKeys[i].def) == "0");
        }
        const std::string ini = tk::AdapterIni();
        for (const char* k : { "timeline=0", "log_files=0", "skip_intro=0", "state_json=0", "lua_bridge=0", "ctl=0", "console=0", "perf=0", "camera=0", "autostart=\r\n" }) {
            const bool has = ini.find(std::string("\n") + k) != std::string::npos || ini.find(std::string("\n") + std::string(k).substr(0, strlen(k) - 2) + "\n") != std::string::npos;
            if (!has) { printf("    shipped ini lacks %s\n", k); CHECK(has); }
        }
    }
    return tk::Done("test_dev");
}
