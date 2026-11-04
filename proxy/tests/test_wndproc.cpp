// Host test: the DXVK window-proc guard (wndprocpolicy.h) against a model of DXVK 3.1.1 d3d9_window.cpp and a foreign subclass.
// Regression for J16 (proxy/runs/20261030_j16dumps): without the guard a fullscreen re-entry leaves opengl32!wglWndProc and DXVK's
// proc each calling the other (the WER dumps' 8-frame cycle, 1060 repeats); with it the chain stays acyclic and ends at the game.
#include "testkit.h"
#include "wndprocpolicy.h"

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
    }
    void Hook() {
        Reset();
        saved = Set(DXVK);
        mapped = true;
        w.prevOf[DXVK] = saved;   // D3D9WindowProc calls the map's proc for this window
    }
};
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
    return tk::Done("test_wndproc");
}
