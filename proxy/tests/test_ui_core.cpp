// test_ui_core.cpp - host tests for the RmlUi host's pure decisions (J30): the D19 scale model, the input-routing table, the
// device lifecycle as a state machine on fake devices, the `ui` control grammar, the frame-cost percentiles; and source lints (ui.enabled=0
// hooks and allocates nothing, only ui_lua.cpp sees Lua, the compat header carries its five functions, the config keys exist in the
// adapter with release values off). Built and run by proxy/tools/build.sh tests.
#include "testkit.h"
#include "ui_core.h"
#include "devcore.h"
#include <cmath>

using namespace wsp;

static const char* ToName(uint8_t t) { return t == kToRml ? "rml" : t == kToEngine ? "engine" : t == kToBoth ? "both" : "none"; }

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    {   // scale model: 85..125 in steps of 5, clamped and snapped; dp = height / 1080 x percent / 100
        CHECK_EQ(UiClampScale(100).percent, 100); CHECK(!UiClampScale(100).changed);
        CHECK_EQ(UiClampScale(85).percent, 85); CHECK_EQ(UiClampScale(125).percent, 125);
        CHECK_EQ(UiClampScale(80).percent, 85); CHECK(UiClampScale(80).changed);
        CHECK_EQ(UiClampScale(0).percent, 85); CHECK_EQ(UiClampScale(-5).percent, 85);
        CHECK_EQ(UiClampScale(130).percent, 125); CHECK_EQ(UiClampScale(1000).percent, 125);
        CHECK_EQ(UiClampScale(102).percent, 100); CHECK_EQ(UiClampScale(103).percent, 105); CHECK(UiClampScale(103).changed);
        CHECK_EQ(UiClampScale(87).percent, 85); CHECK_EQ(UiClampScale(88).percent, 90);
        struct Row { int h, pct; double dp; } rows[] = {
            { 1080, 100, 1.0 }, { 1440, 100, 4.0 / 3.0 }, { 2160, 100, 2.0 }, { 1080, 85, 0.85 }, { 2160, 125, 2.5 }, { 1440, 125, 5.0 / 3.0 },
            { 1080, 125, 1.25 }, { 2160, 85, 1.7 }, { 1440, 85, 1.1333333 }, { 1200, 100, 1.1111111 }, { 1050, 100, 0.9722222 }, { 900, 110, 0.9166667 },
            { 1600, 95, 1.4074074 }, { 2880, 120, 3.2 }, { 768, 100, 0.7111111 }, { 1081, 100, 1.000926 } };
        for (const Row& r : rows) {
            const float got = UiDpRatio(r.h, UiClampScale(r.pct).percent);
            if (std::fabs(got - r.dp) > 1e-5) printf("  scale %d x %d: %.7f want %.7f\n", r.h, r.pct, got, r.dp);
            CHECK(std::fabs(got - r.dp) <= 1e-5);
        }
        for (int h : { 1080, 1440, 2160, 1050, 1201 }) for (int p = 85; p <= 125; p += 5) CHECK(std::fabs(UiDpRatio(h, p) - h / 1080.0 * p / 100.0) < 1e-5);
        CHECK_EQ(UiDpRatio(0, 100), 1.0f);
        // a 1 dp rule at 1080p x 100 is exactly one pixel; the 2.5x art master maps 1:1 at 4K x 125
        CHECK_EQ(UiDpRatio(1080, 100) * 1.0f, 1.0f); CHECK_EQ(UiDpRatio(2160, 125), 2.5f);
    }
    {   // input routing: the table (event, state before, hover after the move) -> delivery and state after
        struct Row { UiEv ev; int btn; bool hover, scroll, text; unsigned eng, rml; bool wasOwner; uint8_t to; bool leave; unsigned engAfter, rmlAfter; const char* what; } rows[] = {
            { UiEv::Move, -1, false, false, false, 0, 0, false, kToBoth, false, 0, 0, "move over the game: both (RmlUi tracks hover)" },
            { UiEv::Move, -1, true, false, false, 0, 0, false, kToRml, true, 0, 0, "move onto an interactive element: RmlUi, the engine gets one leave" },
            { UiEv::Move, -1, true, false, false, 0, 0, true, kToRml, false, 0, 0, "move over the element again: RmlUi, no second leave" },
            { UiEv::Move, -1, false, false, false, 0, 0, true, kToBoth, false, 0, 0, "the move that ends the hover reaches the engine" },
            { UiEv::Down, 0, false, false, false, 0, 0, false, kToEngine, false, 1, 0, "press over the game: engine, captured" },
            { UiEv::Move, -1, true, false, false, 1, 0, false, kToBoth, false, 1, 0, "engine drag over the document: the engine keeps the moves" },
            { UiEv::Up, 0, true, false, false, 1, 0, false, kToEngine, false, 0, 0, "release over the document after an engine press: engine" },
            { UiEv::Down, 1, true, false, false, 1, 0, false, kToEngine, false, 3, 0, "second button during an engine drag: engine" },
            { UiEv::Down, 0, true, false, false, 0, 0, true, kToRml, false, 0, 1, "press on an interactive element: RmlUi" },
            { UiEv::Move, -1, false, false, false, 0, 1, true, kToRml, false, 0, 1, "RmlUi drag leaving the element: RmlUi keeps it" },
            { UiEv::Up, 0, false, false, false, 0, 1, true, kToRml, false, 0, 0, "release of an RmlUi press off the element: RmlUi" },
            { UiEv::Down, 2, true, false, false, 0, 1, true, kToRml, false, 0, 5, "second button during an RmlUi press: RmlUi" },
            { UiEv::Up, 1, false, false, false, 0, 0, false, kToEngine, false, 0, 0, "release never seen pressed: engine, unchanged" },
            { UiEv::Wheel, -1, true, true, false, 0, 0, true, kToRml, false, 0, 0, "wheel over a scrollable list: RmlUi" },
            { UiEv::Wheel, -1, true, false, false, 0, 0, true, kToEngine, false, 0, 0, "wheel over a non-scrolling element: engine (camera zoom)" },
            { UiEv::Wheel, -1, false, false, false, 0, 0, false, kToEngine, false, 0, 0, "wheel over the game: engine" },
            { UiEv::Wheel, -1, true, true, false, 1, 0, false, kToEngine, false, 1, 0, "wheel during an engine drag: engine" },
            { UiEv::Key, -1, true, false, false, 0, 0, true, kToEngine, false, 0, 0, "key with no text focus: engine" },
            { UiEv::Key, -1, false, false, true, 0, 0, false, kToRml, false, 0, 0, "key with a text field focused: RmlUi" },
            { UiEv::Char, -1, false, false, true, 0, 0, false, kToRml, false, 0, 0, "char with a text field focused: RmlUi" },
            { UiEv::Char, -1, false, false, false, 0, 0, false, kToEngine, false, 0, 0, "char with no focus: engine" },
        };
        for (const Row& r : rows) {
            UiRouteState s; s.hoverInteractive = r.hover; s.overScrollable = r.scroll; s.textFocus = r.text; s.engineButtons = r.eng; s.rmlButtons = r.rml;
            const UiRoute got = UiDecide(r.ev, r.btn, s, r.wasOwner);
            const bool ok = got.to == r.to && got.engineLeave == r.leave && s.engineButtons == r.engAfter && s.rmlButtons == r.rmlAfter;
            if (!ok) printf("  route '%s': to %s leave %d eng %u rml %u\n", r.what, ToName(got.to), got.engineLeave, s.engineButtons, s.rmlButtons);
            CHECK(ok);
        }
        // a whole press-drag-release that began on the engine and ended over the document never reaches RmlUi's buttons
        UiRouteState s; bool owner = false; int toRml = 0;
        auto step = [&](UiEv e, int b, bool hover) { s.hoverInteractive = hover; UiRoute r = UiDecide(e, b, s, owner); owner = UiRmlOwnsPointer(s); if ((e == UiEv::Down || e == UiEv::Up) && (r.to & kToRml)) ++toRml; return r; };
        step(UiEv::Down, 0, false); step(UiEv::Move, -1, true); step(UiEv::Up, 0, true);
        CHECK_EQ(toRml, 0); CHECK_EQ(s.engineButtons, 0u);
        CHECK(step(UiEv::Move, -1, true).to == kToRml);   // after release the hover is RmlUi's again
        // DirectInput arbitration follows the same state
        UiRouteState d; d.hoverInteractive = true; CHECK(UiBlankDiButtons(d)); d.engineButtons = 1; CHECK(!UiBlankDiButtons(d));
        UiRouteState w; w.overScrollable = true; CHECK(UiBlankDiWheel(w)); w.engineButtons = 1; CHECK(!UiBlankDiWheel(w));
        UiRouteState n; CHECK(!UiBlankDiButtons(n) && !UiBlankDiWheel(n));
    }
    {   // device lifecycle on fake devices: main only, Reset releases and rebuilds, a failed Reset stays lost, re-creation re-inits
        int a = 1, b = 2, helper = 3;
        CHECK(UiIsMainDevice(1920, 1080, true)); CHECK(UiIsMainDevice(0, 0, true)); CHECK(!UiIsMainDevice(1, 1, true)); CHECK(!UiIsMainDevice(320, 240, true));
        CHECK(!UiIsMainDevice(1920, 1080, false));
        UiLifecycle L;
        CHECK_EQ((int)L.Present(&a, true), (int)kActNone);
        CHECK_EQ((int)L.Created(&helper, false), (int)kActNone); CHECK(L.state == UiLife::NoDevice);
        CHECK_EQ((int)L.Created(&a, true), (int)kActInit); CHECK(L.state == UiLife::Ready);
        CHECK_EQ((int)L.Created(&a, true), (int)kActNone);                // the same device again: nothing
        CHECK_EQ((int)L.Created(&helper, false), (int)kActNone); CHECK(L.device == &a);   // the loader's helper never takes it over
        CHECK_EQ((int)L.Present(&a, false), (int)kActNone);               // no document: nothing drawn
        CHECK_EQ((int)L.Present(&a, true), (int)kActDraw);
        CHECK_EQ((int)L.Present(&helper, true), (int)kActNone);           // the helper's presents are not ours
        CHECK_EQ((int)L.PreReset(&helper), (int)kActNone);
        CHECK_EQ((int)L.PreReset(&a), (int)kActReleaseDefault); CHECK(L.state == UiLife::Lost);
        CHECK_EQ((int)L.Present(&a, true), (int)kActNone);                // lost: nothing drawn
        CHECK_EQ((int)L.PreReset(&a), (int)kActNone);                     // a second Reset while lost: nothing to release twice
        CHECK_EQ((int)L.PostReset(&a, false), (int)kActNone); CHECK(L.state == UiLife::Lost);
        CHECK_EQ((int)L.PostReset(&a, true), (int)kActRebuild); CHECK(L.state == UiLife::Ready);
        CHECK_EQ((int)L.Created(&b, true), (int)(kActInit | kActShutdown)); CHECK(L.device == &b);   // destroyed and created again
        CHECK_EQ((int)L.Present(&a, true), (int)kActNone); CHECK_EQ((int)L.Present(&b, true), (int)kActDraw);
        L.Fail(); CHECK_EQ((int)L.Present(&b, true), (int)kActNone); CHECK_EQ((int)L.Created(&a, true), (int)kActNone);
    }
    {   // the ui control grammar
        CHECK(ParseUiArgs("show hosttest/hosttest.rml").error.empty()); CHECK_EQ(ParseUiArgs("show hosttest/hosttest.rml").doc, std::string("hosttest/hosttest.rml"));
        CHECK(!ParseUiArgs("show ../x.rml").error.empty()); CHECK(!ParseUiArgs("show /abs.rml").error.empty()); CHECK(!ParseUiArgs("show a b").error.empty());
        CHECK(!ParseUiArgs("show C:\\x.rml").error.empty()); CHECK(!ParseUiArgs("").error.empty()); CHECK(!ParseUiArgs("dance").error.empty());
        CHECK_EQ(ParseUiArgs("scale 125").percent, 125); CHECK(!ParseUiArgs("scale x").error.empty());
        UiArgs c = ParseUiArgs("click 100 200"); CHECK(c.error.empty() && c.x == 100 && c.y == 200 && c.button == 0 && c.phase == "click");
        c = ParseUiArgs("click 5 6 right down"); CHECK(c.error.empty() && c.button == 1 && c.phase == "down");
        c = ParseUiArgs("click 5 6 up"); CHECK(c.error.empty() && c.button == 0 && c.phase == "up");
        CHECK(!ParseUiArgs("click 5").error.empty()); CHECK(!ParseUiArgs("click 5 6 sideways").error.empty());
        c = ParseUiArgs("wheel 10 20 3"); CHECK(c.error.empty() && c.delta == 3.f); CHECK(!ParseUiArgs("wheel 10 20 0").error.empty());
        c = ParseUiArgs("dump fe_1080 10 20 300 40"); CHECK(c.error.empty() && c.rect && c.w == 300 && c.name == "fe_1080");
        CHECK(ParseUiArgs("dump fe_1080").error.empty()); CHECK(!ParseUiArgs("dump ../x").error.empty()); CHECK(!ParseUiArgs("dump .x").error.empty());
        CHECK(!ParseUiArgs("dump x 1 2 0 4").error.empty()); CHECK(!ParseUiArgs("dump x 1 2 3").error.empty());
        CHECK(ParseUiArgs("state").error.empty()); CHECK_EQ(ParseUiArgs("state 20").seconds, 20.f); CHECK(!ParseUiArgs("state 61").error.empty());
        CtlRequest r = ParseCtl("ui state 10"); CHECK(r.error.empty() && r.verb == "ui" && r.timeoutS == 40);
        r = ParseCtl("ui show x.rml"); CHECK(r.error.empty() && r.timeoutS == 30);
        r = ParseCtl("ui frob"); CHECK(r.error.find("unknown operation") != std::string::npos);
        CHECK(std::string(CtlVerbs()).find("ui ") != std::string::npos);
    }
    {   // B53 (W20): the DirectInput hooks read one published word; it agrees with the pure decisions on every route state
        long checked = 0;
        for (int hov = 0; hov < 2; ++hov) for (int scr = 0; scr < 2; ++scr) for (int txt = 0; txt < 2; ++txt)
            for (unsigned eb = 0; eb < 8; ++eb) for (unsigned rb = 0; rb < 8; ++rb) {
                UiRouteState s; s.hoverInteractive = hov; s.overScrollable = scr; s.textFocus = txt; s.engineButtons = eb; s.rmlButtons = rb;
                const uint32_t m = UiDiMask(s);
                CHECK_EQ(((m & kDiBlankButtons) != 0), UiBlankDiButtons(s));
                CHECK_EQ(((m & kDiBlankWheel) != 0), UiBlankDiWheel(s));
                CHECK_EQ(((m & kDiTextFocus) != 0), s.textFocus);
                CHECK_EQ((m & ~(uint32_t)(kDiBlankButtons | kDiBlankWheel | kDiTextFocus)), 0u);
                ++checked;
            }
        CHECK_EQ(checked, 512L);
    }
    {   // B53 (W20): focus loss clears both masks and the owner; the next decision is a fresh start's
        for (int hov = 0; hov < 2; ++hov) for (int scr = 0; scr < 2; ++scr) for (unsigned eb = 0; eb < 8; ++eb) for (unsigned rb = 0; rb < 8; ++rb) for (int own = 0; own < 2; ++own) {
            UiRouteState s; s.hoverInteractive = hov; s.overScrollable = scr; s.textFocus = true; s.engineButtons = eb; s.rmlButtons = rb;
            bool owner = own;
            UiFocusLost(s, owner);
            CHECK(s.engineButtons == 0 && s.rmlButtons == 0 && !owner);
            CHECK(s.hoverInteractive == (bool)hov && s.overScrollable == (bool)scr && s.textFocus);   // what RmlUi sensed is not the router's to clear
            UiRouteState fresh; fresh.hoverInteractive = hov; fresh.overScrollable = scr; fresh.textFocus = true;
            for (UiEv ev : { UiEv::Move, UiEv::Down, UiEv::Up, UiEv::Wheel, UiEv::Key, UiEv::Char }) {
                UiRouteState a = s, b = fresh;
                const UiRoute ra = UiDecide(ev, 0, a, owner), rb2 = UiDecide(ev, 0, b, false);
                CHECK(ra.to == rb2.to && ra.engineLeave == rb2.engineLeave && a.engineButtons == b.engineButtons && a.rmlButtons == b.rmlButtons);
            }
        }
    }
    {   // R1 finding 1: the blank decision over (word, gesture owner), every combination
        for (uint32_t w = 0; w < 8; ++w) for (int g = 0; g < 2; ++g) {
            CHECK(UiDiBlankButtons(w, g) == (((w & kDiBlankButtons) != 0) || g));
            CHECK(UiDiBlankWheel(w) == ((w & kDiBlankWheel) != 0));
        }
        CHECK(!UiDiBlankButtons(0, false) && UiDiBlankButtons(kDiBlankButtons, false) && UiDiBlankButtons(0, true));
        CHECK(!UiDiBlankWheel(kDiBlankButtons | kDiTextFocus) && UiDiBlankWheel(kDiBlankWheel));   // a held left button (bit 0 of the bitmap) is not the route word
    }
    {   // W20 source lints (B53): the DirectInput hooks never touch s_route; every block that writes it publishes before it ends
        const std::string host = tk::ReadFile("core/ui_host.cpp");
        const size_t st = host.find("HRESULT WINAPI hk_DIState("), cr = host.find("HRESULT WINAPI hk_DICreateDevice(");
        CHECK(st != std::string::npos && cr != std::string::npos && st < cr);
        const std::string di = host.substr(st, cr - st);
        CHECK(di.find("s_route") == std::string::npos && di.find("s_cs") == std::string::npos && di.find("Lock l") == std::string::npos);
        CHECK(di.find("s_diMask") != std::string::npos);
        // R1 finding 1: the hooks decide through the pure functions, and no local named `mask` exists to shadow anything
        CHECK(di.find("UiDiBlankButtons(dim, GestureOwnsMouse())") != std::string::npos && di.find("UiDiBlankWheel(dim)") != std::string::npos);
        CHECK(di.find("mask ") == std::string::npos && di.find("mask&") == std::string::npos && di.find("(mask") == std::string::npos);
        CHECK(host.find("void Publish() {") != std::string::npos && host.find("InterlockedExchange(&s_diMask") != std::string::npos);
        const size_t wp = host.find("LRESULT CALLBACK WndProc("), act = host.find("case WM_ACTIVATEAPP:", wp), def = host.find("default:", act);
        CHECK(act != std::string::npos && def != std::string::npos);
        const std::string actBlock = host.substr(act, def - act);
        CHECK(actBlock.find("UiFocusLost(s_route, s_rmlOwner)") != std::string::npos && actBlock.find("Publish();") != std::string::npos);
        const size_t dec = host.find("r = UiDecide(", wp), lend = host.find("Count(ev, r.to);", dec);
        CHECK(dec != std::string::npos && lend != std::string::npos);
        const std::string decBlock = host.substr(dec, lend - dec);
        CHECK(decBlock.find("Publish();") != std::string::npos && decBlock.find("s_rmlOwner = UiRmlOwnsPointer(s_route);") != std::string::npos);
        // the pre-decision write (!live branch) is followed by the decide block's publish in the same lock scope
        const size_t lockOpen = host.rfind("Lock l;", dec);
        CHECK(lockOpen != std::string::npos && lockOpen > wp);
    }
    {   // W34 source lint (C9): a system key never meets UiDecide: WndProc hands it to the engine first, the gesture stage still told, and no case maps it to a Key
        const std::string host = tk::ReadFile("core/ui_host.cpp");
        const size_t np = std::string::npos, wp = host.find("LRESULT CALLBACK WndProc("), sys = host.find("if (UiIsSystemKey(msg)) {", wp), sw = host.find("switch (msg) {", wp), dec = host.find("r = UiDecide(", wp);
        CHECK(wp != np && sw != np && dec != np && sys != np && sys < sw && sw < dec);
        if (sys != np) {
            const std::string block = host.substr(sys, host.find("\n", sys) - sys);
            CHECK(block.find("GestureMessage(h, msg, (uint32_t)wp, (intptr_t)lp, true);") != np && block.find("return Engine(h, msg, wp, lp);") != np);
        }
        const std::string body = host.substr(wp, host.find("// ---- input: DirectInput", wp) - wp);
        CHECK(body.find("WM_SYSKEYDOWN") == np && body.find("WM_SYSKEYUP") == np && body.find("WM_SYSCHAR") == np);
        CHECK(body.find("case WM_KEYDOWN: case WM_KEYUP: ev = UiEv::Key; break;") != np && body.find("case WM_CHAR: ev = UiEv::Char; break;") != np);
    }
    {   // frame-cost percentiles (nearest rank)
        std::vector<double> v; for (int i = 100; i >= 1; --i) v.push_back(i * 0.01);
        UiCost c = UiCostOf(v); CHECK_EQ(c.n, (size_t)100); CHECK(std::fabs(c.p50 - 0.50) < 1e-9 && std::fabs(c.p99 - 0.99) < 1e-9 && std::fabs(c.max - 1.0) < 1e-9);
        CHECK_EQ(UiCostOf({}).n, (size_t)0); CHECK(UiCostOf({ 2.0 }).p99 == 2.0);
    }
    {   // source lints
        const std::string host = tk::ReadFile("core/ui_host.cpp");
        // ui.enabled=0: UiInit returns right after reading the key, before any hook, allocation or RmlUi call
        const size_t init = host.find("void UiInit() {"), ret = host.find("if (!K.enabled) return;", init);
        CHECK(init != std::string::npos && ret != std::string::npos);
        const std::string head = host.substr(init, ret - init);
        for (const char* bad : { "Hook", "new ", "Rml::", "Initialize", "CreateEvent", "reserve" }) CHECK(head.find(bad) == std::string::npos);
        CHECK(host.find("if (!s_on || !d3d) return;") != std::string::npos);   // no CreateDevice hook with the UI off
        // only ui_lua.cpp sees Lua (its symbols are made local by build.sh); the host never calls lua_* itself
        for (const char* f : { "core/ui_host.cpp", "core/ui_render_d3d9.cpp", "core/ui_render_d3d9.h", "core/ui_core.h", "core/ui_host.h", "core/ui_lua.h" }) {
            const std::string s = tk::ReadFile(f);
            CHECK(!s.empty());
            CHECK(s.find("#include <lua") == std::string::npos && s.find("#include \"lua") == std::string::npos && s.find("lua_State") == std::string::npos);
        }
        // a detour already in a slot's chain is never installed again (a second device of the same class re-hooking Present made the dev
        // side and the UI host call each other forever: the battle loader's helper device, run 20261102_j30pc)
        const std::string hooks = tk::ReadFile("core/hooks.cpp");
        CHECK(hooks.find("already in the chain") != std::string::npos && hooks.find("installed.push_back({ slot, detour })") != std::string::npos);
        // the D3DCompile blob is a C-style vtable: a TU-local abstract class made GCC emit "call 0" for every call through it (the first
        // J30 start-up crash, 2026-11-02); no pure virtual in the render interface's own types
        CHECK(tk::ReadFile("core/ui_render_d3d9.cpp").find(") = 0;") == std::string::npos);
        CHECK(tk::ReadFile("core/ui_render_d3d9.cpp").find("struct BlobVtbl") != std::string::npos);
        const std::string compat = tk::ReadFile("core/ui_lua51_compat.h");
        for (const char* fn : { "luaL_setfuncs", "LUA_OK", "luaL_testudata", "luaL_traceback", "lua_tointegerx" }) CHECK(compat.find(fn) != std::string::npos);
        const std::string build = tk::ReadFile("core/../tools/build.sh");
        CHECK(build.find("--localize-symbol='_lua*'") != std::string::npos);
        CHECK(build.find("Lua symbols left global") != std::string::npos);
        // every hook forwards to the original
        for (const char* fwd : { "return o_Present(dev, a, b, w, r);", "const HRESULT hr = o_Reset(dev, pp);", "const HRESULT hr = o_CreateDevice(", "const HRESULT hr = o_DIState(", "const HRESULT hr = o_DIData(", "const HRESULT hr = o_DICreateDevice(", "const HRESULT hr = o_DI8Create(" })
            CHECK(host.find(fwd) != std::string::npos);
        // the adapter declares the keys, off in its shipped ini (a game without them runs the UI off: Bool of a missing key is 0)
        const std::string ini = tk::AdapterIni();
        if (ini.find("[ui]") != std::string::npos) {
            CHECK(ini.find("\nenabled=0") != std::string::npos);
            CHECK(ini.find("scale=100") != std::string::npos);
        } else printf("  (the adapter has no [ui] keys: the UI stays off for this game)\n");
    }
    return tk::Done("test_ui_core");
}
