// test_ui_rml.cpp - host test of the RmlUi host's document side on a null render interface (napoleon J30; the pattern of
// empire-remastered tips_rmlui_check.cpp): RmlUi 6.3 with FreeType initialises, a document loads with no Lua, hover and click
// dispatch reach the C++ counter (data-host-counter), the router's questions (interactive, scrollable, text focus) answer as the
// router expects, the wheel scrolls the list; then the host's own Lua state (ui_lua.cpp, the localised copy build.sh makes) runs a
// document's onload and the float32 number test (the viewer's: floor(2550 x 0.319999992) = 816; a double Lua gives 815).
// link: ui   (build.sh links RmlUi, FreeType and the localised ui_lua object; WSP_UI_SRC names the fetched sources for the font)
#include "testkit.h"
#include "ui_core.h"
#include "ui_rml.h"
#include "ui_lua.h"
#include <RmlUi/Core.h>
#include <cstdlib>
#include <cmath>

using namespace wsp;

namespace {
struct NullRender : Rml::RenderInterface {
    int geometries = 0, draws = 0, textures = 0;
    Rml::CompiledGeometryHandle CompileGeometry(Rml::Span<const Rml::Vertex>, Rml::Span<const int>) override { return (Rml::CompiledGeometryHandle)++geometries; }
    void RenderGeometry(Rml::CompiledGeometryHandle, Rml::Vector2f, Rml::TextureHandle) override { ++draws; }
    void ReleaseGeometry(Rml::CompiledGeometryHandle) override {}
    Rml::TextureHandle LoadTexture(Rml::Vector2i& d, const Rml::String&) override { d = { 4, 4 }; return (Rml::TextureHandle)++textures; }
    Rml::TextureHandle GenerateTexture(Rml::Span<const Rml::byte>, Rml::Vector2i) override { return (Rml::TextureHandle)++textures; }
    void ReleaseTexture(Rml::TextureHandle) override {}
    void EnableScissorRegion(bool) override {}
    void SetScissorRegion(Rml::Rectanglei) override {}
};
struct Sys : Rml::SystemInterface {
    double t = 0; int errors = 0;
    double GetElapsedTime() override { return t; }
    bool LogMessage(Rml::Log::Type type, const Rml::String& m) override { if (type == Rml::Log::LT_ERROR) { ++errors; printf("  rml error: %s\n", m.c_str()); } return true; }
};
const char* kDoc = R"(<rml><head><style>
body { font-family: "Lato"; font-size: 16dp; position: absolute; left: 0; top: 0; width: 400dp; height: 400dp; display: block; }
div { display: block; }
#btn { position: absolute; left: 10dp; top: 10dp; width: 100dp; height: 40dp; background-color: #c8a050; }
#list { position: absolute; left: 10dp; top: 100dp; width: 200dp; height: 100dp; overflow-y: auto; }
.item { height: 30dp; }
#field { position: absolute; left: 250dp; top: 10dp; width: 100dp; height: 30dp; display: inline-block; }
</style></head><body>
<div id="btn" data-host-counter="count">Click</div><div id="count">0</div>
<div id="list"><div class="item">1</div><div class="item">2</div><div class="item">3</div><div class="item">4</div><div class="item">5</div><div class="item">6</div></div>
<input id="field" type="text"/>
</body></rml>)";
}

int main(int argc, char** argv) {
    tk::Args(argc, argv);
    const char* uisrc = getenv("WSP_UI_SRC");
    NullRender ri; Sys sys;
    Rml::SetRenderInterface(&ri); Rml::SetSystemInterface(&sys);
    CHECK(Rml::Initialise());
    if (uisrc) CHECK(Rml::LoadFontFace(std::string(uisrc) + "/rmlui/Samples/assets/LatoLatin-Regular.ttf"));
    else printf("  (WSP_UI_SRC unset: no font, text not laid out)\n");
    Rml::Context* ctx = Rml::CreateContext("main", { 1920, 1080 });
    CHECK(ctx != nullptr);
    ctx->SetDensityIndependentPixelRatio(UiDpRatio(1080, 100));
    UiClicks clicks;
    Rml::ElementDocument* doc = ctx->LoadDocumentFromMemory(kDoc);
    CHECK(doc != nullptr);
    if (doc) {
        doc->AddEventListener(Rml::EventId::Click, &clicks);
        doc->Show();
        ctx->Update(); ctx->Render();
        CHECK(ri.draws > 0);
        // pointer over the button: interactive; a click counts in C++ and writes the counter element
        ctx->ProcessMouseMove(50, 30, 0); ctx->Update();
        CHECK(ctx->IsMouseInteracting());
        CHECK(!UiOverScrollable(ctx));
        ctx->ProcessMouseButtonDown(0, 0); ctx->ProcessMouseButtonUp(0, 0); ctx->Update();
        CHECK_EQ(clicks.counts["btn"], 1);
        CHECK_EQ(doc->GetElementById("count")->GetInnerRML(), std::string("1"));
        // over the list: scrollable; the wheel scrolls it
        ctx->ProcessMouseMove(60, 150, 0); ctx->Update();
        CHECK(UiOverScrollable(ctx));
        Rml::Element* list = doc->GetElementById("list");
        const float before = list->GetScrollTop();
        ctx->SetDefaultScrollBehavior(Rml::ScrollBehavior::Instant, 1.0f);
        ctx->ProcessMouseWheel(Rml::Vector2f(0.f, 2.f), 0); ctx->Update();
        CHECK(list->GetScrollTop() > before);
        // the router with RmlUi's answers: wheel over the list -> RmlUi; a click over the list (interactive body) -> RmlUi
        UiRouteState s; s.hoverInteractive = ctx->IsMouseInteracting(); s.overScrollable = UiOverScrollable(ctx);
        CHECK(UiDecide(UiEv::Wheel, -1, s, true).to == kToRml);
        // the text field takes focus on click; keys then belong to RmlUi
        ctx->ProcessMouseMove(300, 20, 0); ctx->ProcessMouseButtonDown(0, 0); ctx->ProcessMouseButtonUp(0, 0); ctx->Update();
        CHECK(UiTextFocus(ctx));
        // the counter is C++ only: no Lua state exists yet, and the document still worked
        CHECK(!UiLuaUp());
        // dp scaling: the button's box follows the ratio (4K x 125 = 2.5)
        ctx->SetDensityIndependentPixelRatio(UiDpRatio(2160, 125)); ctx->Update();
        CHECK(std::fabs(doc->GetElementById("btn")->GetBox().GetSize().x - 250.f) < 0.01f);
        doc->Close();
    }
    // the host's own Lua (float32), RmlUi's Lua plugin on it, and a document whose onload uses it
    std::string why;
    CHECK(UiLuaStart(why));
    CHECK_EQ(UiLuaEval("return math.floor(2550 * 0.319999992)"), std::string("816"));
    CHECK_EQ(UiLuaEval("return 16777217 - 16777216"), std::string("0"));
    CHECK_EQ(UiLuaEval("return tostring(1/3)"), std::string("0.3333333"));
    CHECK(UiLuaEval("error('x')").rfind("error: ", 0) == 0);
    CHECK_EQ(UiLuaEval("return type(rmlui)"), std::string("userdata"));   // the plugin registered its global
    Rml::ElementDocument* d2 = ctx->LoadDocumentFromMemory("<rml><body onload=\"document:GetElementById('l').inner_rml = 'n=' .. math.floor(2550 * 0.319999992)\"><div id=\"l\">off</div></body></rml>");
    CHECK(d2 != nullptr);
    if (d2) { d2->Show(); ctx->Update(); CHECK_EQ(d2->GetElementById("l")->GetInnerRML(), std::string("n=816")); d2->Close(); }
    UiLuaStep();
    CHECK(sys.errors == 0);
    Rml::Shutdown();
    UiLuaStop();
    CHECK(!UiLuaUp());
    return tk::Done("test_ui_rml");
}
