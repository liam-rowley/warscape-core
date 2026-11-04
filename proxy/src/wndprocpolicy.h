// wndprocpolicy.h - what DXVK sees when it reads a window's GWL_WNDPROC (pure logic: host-tested in tests/test_wndproc.cpp).
// J16 (proxy/runs/20261030_j16dumps): DXVK 3.1.1 d3d9_window.cpp subclasses the game window on entering fullscreen. When another
// module subclasses it afterwards (opengl32!wglWndProc, installed for NVIDIA's ICD), DXVK's ResetWindowProc finds a foreign proc on
// top, so it erases its record without unhooking; the next HookWindowProc then saves the foreign proc as its previous one while the
// foreign proc still has DXVK's as its previous: the two call each other until the 1 MB main stack overflows (both WER dumps).
// The guard: on a window DXVK hooked, a GWL_WNDPROC read made by DXVK reports DXVK's own proc, so DXVK restores the proc it saved
// (the game's): the chain goes back to what it was before DXVK, the layers stacked above DXVK are dropped, and no cycle can form.
#pragma once
#include <cstdint>
#include <map>

namespace wsp {

class WndProcBook {
public:
    // DXVK set GWL_WNDPROC on `hwnd` to `proc`; `ownedByDxvk` = proc lies in DXVK's image (its hook) rather than a restore.
    void OnSet(uintptr_t hwnd, uintptr_t proc, bool ownedByDxvk) {
        if (ownedByDxvk) hooked_[hwnd] = proc;
        else hooked_.erase(hwnd);
    }
    // DXVK reads GWL_WNDPROC; `actual` is the real top of the chain. Returns what DXVK is told.
    uintptr_t OnGet(uintptr_t hwnd, uintptr_t actual) const {
        auto it = hooked_.find(hwnd);
        return it != hooked_.end() && actual != it->second ? it->second : actual;
    }
    bool Foreign(uintptr_t hwnd, uintptr_t actual) const { return OnGet(hwnd, actual) != actual; }
    void OnDestroy(uintptr_t hwnd) { hooked_.erase(hwnd); }

private:
    std::map<uintptr_t, uintptr_t> hooked_;
};

} // namespace wsp
