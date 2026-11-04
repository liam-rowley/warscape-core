// Host test: the DXVK window-proc guard (wndprocpolicy.h) against a model of DXVK 3.1.1 d3d9_window.cpp and a foreign subclass.
// Regression for J16 (proxy/runs/20261030_j16dumps): without the guard a fullscreen re-entry leaves opengl32!wglWndProc and DXVK's
// proc each calling the other (the WER dumps' 8-frame cycle, 1060 repeats); with it the chain stays acyclic and ends at the game.
#include "testkit.h"
#include "wndprocpolicy.h"

#include <algorithm>
#include <set>

namespace {
const uintptr_t W = 1, GAME = 0x100, DXVK = 0x200, GL = 0x300, OVERLAY = 0x400;

// A window: the top proc, and the "previous" each subclasser saved for itself.
struct Window {
    uintptr_t top = GAME;
    std::map<uintptr_t, uintptr_t> prevOf;
    uintptr_t Set(uintptr_t p) { uintptr_t old = top; top = p; return old; }
    // follow the chain from the top: true when it reaches GAME, false on a cycle (the stack overflow)
    bool Reaches(uintptr_t target, std::vector<uintptr_t>* path = nullptr) const {
        std::set<uintptr_t> seen;
        for (uintptr_t p = top;; p = prevOf.at(p)) {
            if (path) path->push_back(p);
            if (p == target) return true;
            if (!seen.insert(p).second || !prevOf.count(p)) return false;
        }
    }
    // the other way not to reach it: true on a cycle only, false when the chain stops at a proc with no previous one (an orphan)
    bool Cyclic() const {
        std::set<uintptr_t> seen;
        for (uintptr_t p = top;; p = prevOf.at(p)) {
            if (!seen.insert(p).second) return true;
            if (!prevOf.count(p)) return false;
        }
    }
};

// Another module subclasses on top (opengl32 for NVIDIA's ICD, or an overlay).
void Subclass(Window& w, uintptr_t proc) { w.prevOf[proc] = w.Set(proc); }

// DXVK 3.1.1 ResetWindowProc / HookWindowProc, verbatim in logic; reads and writes go through the guard when `guard` is set.
struct Dxvk {
    Window& w;
    wsp::WndProcBook* guard;
    bool mapped = false;
    uintptr_t saved = 0;
    uintptr_t Get() { return guard ? guard->OnGet(W, w.top) : w.top; }
    uintptr_t Set(uintptr_t p) { if (guard) guard->OnSet(W, p, p == DXVK); return w.Set(p); }
    void Reset() {
        if (!mapped) return;
        if (Get() == DXVK) Set(saved);
        mapped = false;
        w.prevOf.erase(DXVK);     // g_windowProcMap.erase: D3D9WindowProc now has no proc to call and answers with DefWindowProc
    }
    void Hook() {
        Reset();
        saved = Set(DXVK);
        mapped = true;
        w.prevOf[DXVK] = saved;   // D3D9WindowProc calls the map's proc for this window
    }
};

// One window, DXVK and (when `guarded`) the guard: the re-entry cases below run the same switches both ways.
struct Rig {
    Window w;
    wsp::WndProcBook g;
    Dxvk d;
    explicit Rig(bool guarded) : d{w, guarded ? &g : nullptr} {}
    bool Foreign() const { return g.Foreign(W, w.top); }
    size_t Length() const { std::vector<uintptr_t> p; w.Reaches(GAME, &p); return p.size(); }
};

// The re-entry paths the A/B run crashed on. Unguarded each must end in the dumps' cycle (the model reproduces the bug); guarded it ends at
// the game. `Hook` is DXVK's EnterFullscreenMode, `Reset` its leave.

void DeviceRecreate() {   // 4K to 1440p, then 4K to 1080p: the swapchain is rebuilt, HookWindowProc runs again over the foreign proc
    { Rig r(false); r.d.Hook(); Subclass(r.w, GL); r.d.Hook();
      CHECK(r.w.Cyclic()); CHECK(r.w.prevOf[GL] == DXVK && r.w.prevOf[DXVK] == GL); }
    { Rig r(true); r.d.Hook();
      for (int i = 0; i < 2; ++i) {
          Subclass(r.w, GL); r.d.Hook();
          CHECK(!r.w.Cyclic()); CHECK(r.w.Reaches(GAME)); CHECK(r.w.top == DXVK); CHECK_EQ(r.Length(), size_t(2));
      } }
}

void WindowedToFullscreen() {   // arm e's revert: ResetWindowProc on the way out with the foreign layer on top, HookWindowProc on the way back
    { Rig r(false); r.d.Hook(); Subclass(r.w, GL); r.d.Reset();
      CHECK(!r.w.Reaches(GAME)); CHECK(!r.w.Cyclic());     // windowed: GL -> DXVK -> DefWindowProc, the game hears nothing (arm e lost the mouse here)
      r.d.Hook(); CHECK(r.w.Cyclic()); }                   // the revert: the crash
    { Rig r(true); r.d.Hook(); Subclass(r.w, GL); r.d.Reset();
      CHECK(r.w.top == GAME); CHECK(r.w.Reaches(GAME));    // windowed: the game has its own proc back
      r.d.Hook(); CHECK(r.w.Reaches(GAME)); CHECK_EQ(r.Length(), size_t(2)); }
}

void FullscreenWindowedTwice() {   // fullscreen to windowed and back, twice in a row, for each moment the foreign module can come back
    { Rig r(false); r.d.Hook(); Subclass(r.w, GL);
      for (int i = 0; i < 2; ++i) { r.d.Reset(); CHECK(!r.w.Reaches(GAME)); r.d.Hook(); CHECK(r.w.Cyclic()); } }
    enum { Never, AboveDxvk, WhileWindowed };
    for (int back : { Never, AboveDxvk, WhileWindowed }) {
        Rig r(true); r.d.Hook(); Subclass(r.w, GL);
        for (int i = 0; i < 2; ++i) {
            r.d.Reset();
            CHECK(r.w.Reaches(GAME)); CHECK(!r.w.Cyclic());
            if (back == WhileWindowed && r.w.top == GAME) Subclass(r.w, GL);   // it installs once: GL stays in the chain, below DXVK from here on
            r.d.Hook();
            CHECK(r.w.Reaches(GAME)); CHECK(!r.w.Cyclic()); CHECK(r.w.top == DXVK);
            if (back == AboveDxvk) { Subclass(r.w, GL); CHECK(r.w.Reaches(GAME)); }
        }
    }
}

void ThreeLayers() {   // two foreign subclassers above DXVK, one an overlay
    { Rig r(false); r.d.Hook(); Subclass(r.w, GL); Subclass(r.w, OVERLAY); r.d.Hook(); CHECK(r.w.Cyclic()); }
    { Rig r(true); r.d.Hook(); Subclass(r.w, GL); Subclass(r.w, OVERLAY);
      CHECK(r.Foreign()); r.d.Hook();
      CHECK(r.w.Reaches(GAME)); CHECK_EQ(r.Length(), size_t(2)); }
    { Rig r(true); r.d.Hook(); Subclass(r.w, GL); Subclass(r.w, OVERLAY); r.d.Reset(); CHECK(r.w.top == GAME); }
    // an overlay that was there before DXVK is below it: only what is above DXVK goes
    { Rig r(false); Subclass(r.w, OVERLAY); r.d.Hook(); Subclass(r.w, GL); r.d.Hook(); CHECK(r.w.Cyclic()); }
    { Rig r(true); Subclass(r.w, OVERLAY); r.d.Hook(); Subclass(r.w, GL); r.d.Hook();
      std::vector<uintptr_t> p; CHECK(r.w.Reaches(GAME, &p));
      CHECK(p.size() == 3 && p[0] == DXVK && p[1] == OVERLAY); }
}

void ForeignBetweenSwitches() {   // nothing foreign at the first switch, then a layer arrives before the second
    { Rig r(false); r.d.Hook(); r.d.Hook(); CHECK(r.w.Reaches(GAME)); Subclass(r.w, GL); r.d.Hook(); CHECK(r.w.Cyclic()); }
    { Rig r(true); r.d.Hook(); r.d.Hook(); CHECK(r.w.Reaches(GAME)); CHECK(!r.Foreign());
      Subclass(r.w, GL); CHECK(r.Foreign()); r.d.Hook(); CHECK(r.w.Reaches(GAME)); CHECK(!r.Foreign());
      Subclass(r.w, OVERLAY); CHECK(r.Foreign()); r.d.Hook(); CHECK(r.w.Reaches(GAME)); CHECK_EQ(r.Length(), size_t(2)); }
    // installed while DXVK has no hook: it is below DXVK at the next entry and is kept, however many switches follow
    { Rig r(true); r.d.Hook(); r.d.Reset(); Subclass(r.w, GL); r.d.Hook();
      CHECK(!r.Foreign()); CHECK(r.w.prevOf[DXVK] == GL); CHECK_EQ(r.Length(), size_t(3));
      r.d.Reset(); CHECK(r.w.top == GL); r.d.Hook(); CHECK(r.w.Reaches(GAME)); CHECK_EQ(r.Length(), size_t(3)); }
}

void TenRoundTrips() {   // 10 round trips, both kinds of switch: Foreign is true only while a foreign layer is on top
    { Rig r(false); r.d.Hook();
      for (int i = 0; i < 10; ++i) { Subclass(r.w, GL); r.d.Reset(); CHECK(!r.w.Reaches(GAME)); r.d.Hook(); CHECK(r.w.Cyclic()); } }
    { Rig r(true); r.d.Hook();
      for (int i = 0; i < 10; ++i) {
          CHECK(!r.Foreign());
          Subclass(r.w, GL); CHECK(r.Foreign());
          r.d.Hook(); CHECK(!r.Foreign()); CHECK(r.w.Reaches(GAME)); CHECK(!r.w.Cyclic());       // a device recreate
          Subclass(r.w, GL); CHECK(r.Foreign());
          r.d.Reset(); CHECK(!r.Foreign()); CHECK(r.w.top == GAME);                              // to windowed
          r.d.Hook(); CHECK(!r.Foreign()); CHECK(r.w.Reaches(GAME)); CHECK_EQ(r.Length(), size_t(2));   // and back
      } }
}

void NeverOverReach() {
    const uintptr_t W2 = 2, DXVK2 = 0x210;
    wsp::WndProcBook g;
    CHECK(g.OnGet(W, GL) == GL); CHECK(!g.Foreign(W, GL));          // a window DXVK did not hook
    g.OnSet(W, DXVK, true);
    CHECK(g.OnGet(W, DXVK) == DXVK); CHECK(!g.Foreign(W, DXVK));    // hooked, nothing foreign
    CHECK(g.OnGet(W, GL) == DXVK); CHECK(g.Foreign(W, GL));
    CHECK(g.OnGet(W2, GL) == GL);                                   // an unknown hwnd
    g.OnSet(W2, DXVK, true); g.OnSet(W, GAME, false);               // W restored, W2 still hooked: each on its own
    CHECK(g.OnGet(W, GL) == GL); CHECK(!g.Foreign(W, GL));
    CHECK(g.OnGet(W2, GL) == DXVK);
    g.OnSet(W2, DXVK2, true); CHECK(g.OnGet(W2, GL) == DXVK2);      // the last hook is the one reported
    g.OnDestroy(W2);
    CHECK(g.OnGet(W2, GL) == GL); CHECK(!g.Foreign(W2, GL));        // a recycled hwnd is not told a stale proc
    g.OnDestroy(W2); CHECK(g.OnGet(W2, GL) == GL);                  // forgetting twice is harmless
}

// What the guard cannot do, pinned so the limit is on the record: it sees DXVK's reads and writes and nobody else's. These are not the
// dumps' path (there the foreign module installs once, above DXVK); a change here means the guard's reach changed.
void OutOfReach() {
    // a module with one saved-proc slot that installs again above DXVK while it is already below it closes a cycle of its own
    { Rig r(true); r.d.Hook(); r.d.Reset(); Subclass(r.w, GL); r.d.Hook(); Subclass(r.w, GL); CHECK(r.w.Cyclic()); }
    // a dropped module that later writes back the previous proc it saved puts DXVK's orphan on top: the game hears nothing
    { Rig r(true); r.d.Hook(); Subclass(r.w, GL); r.d.Reset(); r.w.Set(r.w.prevOf[GL]); CHECK(r.w.top == DXVK); CHECK(!r.w.Reaches(GAME)); CHECK(!r.w.Cyclic()); }
}

// a source with its // comments out, so a lint reads code and not the explanation of it
std::string Code(const std::string& rel) {
    std::string s = tk::ReadFile(rel), out;
    CHECK(!s.empty());
    for (size_t i = 0; i < s.size();) {
        const size_t e = std::min(s.find('\n', i), s.size()), c = s.find("//", i);
        out.append(s, i, (c < e ? c : e) - i); out += '\n';
        i = e + 1;
    }
    return out;
}
size_t Count(const std::string& s, const std::string& what) { size_t n = 0; for (size_t k = s.find(what); k != std::string::npos; k = s.find(what, k + 1)) ++n; return n; }

void Lints() {
    const size_t np = std::string::npos;
    const std::string be = Code("core/backend.cpp"), gd = Code("core/dxvk_wndproc.cpp"), dm = Code("core/dllmain.cpp");
    // the guard asks the policy, and what it writes is the loaded backend's import table: nothing else, never the exe or a game module
    CHECK(gd.find("s_book.OnGet(") != np && gd.find("s_book.OnSet(") != np);
    CHECK(gd.find("IMAGE_DIRECTORY_ENTRY_IMPORT") != np && gd.find("reinterpret_cast<uint8_t*>(dxvk)") != np);
    CHECK_EQ(Count(gd, "VirtualProtect("), size_t(2));
    CHECK_EQ(Count(gd, "VirtualProtect(&t->u1.Function, sizeof(DWORD)"), size_t(2));
    CHECK_EQ(Count(gd, "t->u1.Function = "), size_t(1));
    for (const char* bad : { "GetModuleHandleW(nullptr)", "GetModuleHandle(nullptr)", "GetModuleHandleA(nullptr)", "PlanEngine(", "SiteAddress(", "exeBase", "WriteProcessMemory",
                             "memcpy(", "WritePlanAtomic(", "adapter.h", "Adapter(", "CreateThread(", "StartThread(", "LoadLibrary" })
        if (gd.find(bad) != np) { printf("    dxvk_wndproc.cpp has %s\n", bad); CHECK(false); }
    // the module it hooks through: only user32's four, by name
    CHECK_EQ(Count(gd, "GetProcAddress("), size_t(4));
    CHECK_EQ(Count(gd, "GetModuleHandleW("), size_t(1));
    CHECK(gd.find("GetModuleHandleW(L\"user32.dll\")") != np);

    // backend.cpp: under s_real and the DXVK name, after LoadDxvk, before the first export is resolved, and only there
    const size_t load = be.find("BOOL CALLBACK LoadOnce("), call = be.find("DxvkWndProcGuard(s_real)"), under = be.find("if (s_real && !strcmp(s_name, \"dxvk\")) {"),
                 dxvk = be.find("s_real = LoadDxvk();"), system = be.find("if (!s_real) s_real = LoadSystem();"), first = be.find("Resolve<PFN_Create9>(\"Direct3DCreate9\")");
    CHECK(load != np && call != np && under != np && dxvk != np && system != np && first != np);
    CHECK(load < dxvk && dxvk < under && under < call && call < system && system < first);
    CHECK_EQ(Count(be, "DxvkWndProcGuard("), size_t(1));
    CHECK(be.find("rt.cfg.Bool(\"proxy.dxvk_wndproc_fix\")") != np);
    CHECK(be.find("rt.cfg.Bool(\"proxy.dxvk_wndproc_fix\")") < call);
    // the unknown-backend warning is the else of the `want` test and of nothing else: the guard's if may not come between them (J16's shape did)
    const size_t want = be.find("if (want == \"dxvk\") {"), unknown = be.find("else if (want != \"system\")");
    CHECK(want != np && unknown != np && want < unknown);
    const size_t wantEnd = be.find('\n', want);
    CHECK(wantEnd != np && be.find_first_not_of(" \n", wantEnd) == unknown);
    CHECK(unknown < under);
    // never from DllMain or Init: dllmain.cpp does not name it, and the one caller is LoadOnce (the first export call)
    CHECK(dm.find("DxvkWndProcGuard") == np);
    CHECK(be.find("LoadOnce", load + 1) != np);
    CHECK(be.find("DllMain") == np);
}
}

int main(int argc, char** argv) {
    tk::Args(argc, argv);

    // 1) the J16 bug, unguarded: hook, opengl32 on top, then a fullscreen re-entry (device recreate or windowed->fullscreen Reset)
    {
        Window w; Dxvk d{w, nullptr};
        d.Hook(); Subclass(w, GL);
        CHECK(w.Reaches(GAME));
        d.Hook();
        CHECK(!w.Reaches(GAME));                     // the cycle: GL -> DXVK -> GL
        CHECK(w.prevOf[GL] == DXVK && w.prevOf[DXVK] == GL);
    }
    // 2) guarded: the same sequence ends DXVK -> GAME, opengl32's layer dropped, no cycle
    {
        Window w; wsp::WndProcBook g; Dxvk d{w, &g};
        d.Hook(); Subclass(w, GL);
        CHECK(g.Foreign(W, w.top));
        d.Hook();
        std::vector<uintptr_t> path;
        CHECK(w.Reaches(GAME, &path));
        CHECK(path.size() == 2 && path[0] == DXVK);
        // repeated switches stay acyclic, also when the foreign module subclasses again each time
        for (int i = 0; i < 5; ++i) { Subclass(w, GL); d.Hook(); CHECK(w.Reaches(GAME)); }
    }
    // 3) guarded leave-fullscreen (ResetWindowProc only): the game's proc is on top again, not DXVK's orphan
    {
        Window w; wsp::WndProcBook g; Dxvk d{w, &g};
        d.Hook(); Subclass(w, GL); d.Reset();
        CHECK(w.top == GAME);
        // unguarded, the same leave leaves the game behind a DXVK proc with no record (DefWindowProc: the game hears nothing)
        Window u; Dxvk du{u, nullptr};
        du.Hook(); Subclass(u, GL); du.Reset();
        CHECK(u.top == GL && u.prevOf[GL] == DXVK);
    }
    // 4) no foreign layer: the guard changes nothing (vanilla DXVK path), and a subclass made BEFORE DXVK stays in the chain
    {
        Window w; wsp::WndProcBook g; Dxvk d{w, &g};
        Subclass(w, OVERLAY);
        d.Hook();
        CHECK(!g.Foreign(W, w.top));
        d.Hook();
        std::vector<uintptr_t> path;
        CHECK(w.Reaches(GAME, &path));
        CHECK(path.size() == 3 && path[0] == DXVK && path[1] == OVERLAY);
        d.Reset();
        CHECK(w.top == OVERLAY);
    }
    // 5) bookkeeping: other windows and a destroyed window are untouched
    {
        wsp::WndProcBook g;
        g.OnSet(W, DXVK, true);
        CHECK(g.OnGet(2, GL) == GL);
        g.OnDestroy(W);
        CHECK(g.OnGet(W, GL) == GL);
    }

    DeviceRecreate();
    WindowedToFullscreen();
    FullscreenWindowedTwice();
    ThreeLayers();
    ForeignBetweenSwitches();
    TenRoundTrips();
    NeverOverReach();
    OutOfReach();
    Lints();
    return tk::Done("test_wndproc");
}
