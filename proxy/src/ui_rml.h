#pragma once
// ui_rml.h - the RmlUi host's RmlUi-side helpers that need no Windows (J30): what the router asks RmlUi after each pointer event
// (scrollable under the pointer, text focus) and the C++-registered click counter (data-host-counter). Shared by ui_host.cpp and the
// host test proxy/tests/test_ui_rml.cpp, which runs them on a null render interface.
#include <RmlUi/Core.h>
#include <map>
#include <string>

namespace wsp {

// The hover element or an ancestor can scroll vertically (overflow-y auto|scroll and more content than room).
inline bool UiOverScrollable(Rml::Context* ctx) {
    for (Rml::Element* e = ctx ? ctx->GetHoverElement() : nullptr; e; e = e->GetParentNode()) {
        const auto o = e->GetComputedValues().overflow_y();
        if ((o == Rml::Style::Overflow::Auto || o == Rml::Style::Overflow::Scroll) && e->GetScrollHeight() > e->GetClientHeight() + 0.5f) return true;
    }
    return false;
}
// A text field has focus: <textarea>, or <input> of type text or password.
inline bool UiTextFocus(Rml::Context* ctx) {
    Rml::Element* f = ctx ? ctx->GetFocusElement() : nullptr;
    if (!f) return false;
    if (f->GetTagName() == "textarea") return true;
    if (f->GetTagName() != "input") return false;
    const Rml::String t = f->GetAttribute<Rml::String>("type", "text");
    return t == "text" || t == "password";
}

// C++-registered events: a click on an element (or inside one) carrying data-host-counter="<id>" counts it and writes the count into the
// element with that id. Static RML is enough: a test document works with no Lua at all (the front end pumps no screen Lua).
class UiClicks : public Rml::EventListener {
public:
    std::map<std::string, int> counts;   // by the clicked element's id
    std::string last;                    // "<id> <count>" of the last counted click (the host logs it)
    void ProcessEvent(Rml::Event& ev) override {
        for (Rml::Element* e = ev.GetTargetElement(); e; e = e->GetParentNode()) {
            const Rml::String target = e->GetAttribute<Rml::String>("data-host-counter", "");
            if (target.empty()) continue;
            const int n = ++counts[e->GetId()];
            if (Rml::ElementDocument* d = e->GetOwnerDocument()) if (Rml::Element* t = d->GetElementById(target)) t->SetInnerRML(std::to_string(n));
            last = e->GetId() + " " + std::to_string(n);
            return;
        }
    }
};

} // namespace wsp
