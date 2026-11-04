## Round 2 (2026-11-04, branch job/W20 at 4d39110)

**Verdict: merge.**

Machines: `wsc gates` 13 ok after merging main. CI on the reviewed pre-merge head (927df7e) was still running when I read it; the merged head gets its own run and auto-merge waits for every required check on it (including the `-Wshadow` builds, which only CI can compile). Risk-first reading: the round-1 blocker area, `hk_DIState`/`hk_DIData` in `proxy/src/ui_host.cpp`.

Round 1 answered in `## Fix round 1` of the report:
1. Blocker (shadowed `mask`): fixed. The hooks read the published word as `dim`, the button bitmap is `btns`, and the decision is the pure `UiDiBlankButtons(dim, GestureOwnsMouse())` / `UiDiBlankWheel(dim)` in `ui_core.h:93-96`. `test_ui_core.cpp` tests all 16 word/owner combinations, that a held left button is not the route word, and lints the hooks (no `mask` token, the pure calls present). `build.sh` compiles the proxy and the host tests with `-Wshadow`. Read in the diff: the keyboard branch and the `GetDeviceData` hook are consistent.
2. Should-fix (coverage): closed by the same function and test.
3 to 5. Accepted, no action; B58 e stays in `docs/BACKLOG.md`.

Fixed by me on the branch: `VERSION` conflicted with main (0.27.0 after W24); I merged `origin/main` and renumbered 0.23.0 to 0.28.0 (one merge commit). The report's "0.23.0" mentions are a dated record and are left.

Residual risk (not a finding): `-Wshadow` may flag older code that nobody compiled with it; CI would show that as a red `proxy` check and block the auto-merge.

## Round 1 (2026-11-04, branch job/W20 at 83cb39c)

**Verdict: merge after fixes.**

Machines: `wsc gates` 13 ok (run on main's tree, the branch adds no Python); CI on the head (83cb39c) all 8 checks green, with 14 host-test suites; `policy` fails locally only because this review and the row were not yet written. Risk-first reading: the DirectInput hooks in `ui_host.cpp` (they run on the game's input thread, every frame) and the `s_lock` owner logic in `gesture.cpp`. The rest I skimmed against the brief.

### Blocker
1. **`proxy/src/ui_host.cpp:471`: a local `unsigned mask` shadows the published `const uint32_t mask` in `hk_DIState`.** The new line `const uint32_t mask = (uint32_t)s_diMask;` sits at function scope. Inside the `dev == s_diMouse` block the old button-bitmap variable `unsigned mask = 0;` was left in place. The two lines that follow, `(mask & kDiBlankButtons)` and `(mask & kDiBlankWheel)`, therefore test the *DirectInput button bitmap*, not the published route word. Effects on the mouse device in `GetDeviceState`: the left button (bit 0) blanks the buttons whenever it is held, so the game never sees a plain left click through DirectInput; the right button (bit 1) zeroes the wheel; and RmlUi's real blank decision is ignored. The keyboard branch is fine (it is outside the block). The build uses `-Wall -Wextra -Werror` but not `-Wshadow`, so it compiles; no test sees it, because the new lints only check that the hook text contains `s_diMask` and no `s_route`. To see it fail: a build with `-Wshadow`, or read the lines above. The smoke launches do not press a DirectInput button.
   *Fix:* rename the inner variable (`btns`), or the outer (`dim`), in both hooks, and compile the proxy with `-Wshadow` (`build.sh`, two g++ lines) so this cannot recur.
   *Test:* add a source lint to `test_ui_core.cpp` that `hk_DIState` declares `mask`-like names once (no second declaration of the published word's name in the function), or better, move the blank decision into a pure function over (`diMask`, `gestureOwns`, `isBtn`, `isWheel`) in `ui_core.h` and test it; a pure function cannot be shadowed.

### Should-fix
2. **The report claims the DirectInput change is covered by lints and exhaustive `UiDiMask` tests** (true), but nothing covers the use of the word in the hooks beyond text presence. The pure function in finding 1 closes this.
3. **`jobs/W20/report.md` deviation 2** (one commit for B53 and B58 a, b, c, against the brief's "each its own commit") is named and reasoned (no compiler on the builder's PC); accepted, no action.

### Later
4. B58 e (the smoke walk) was not attempted, with a reason the brief allows (no wine or Docker on the builder's PC); the brief says to try it within about 20 calls using CI itself as the compiler. It stays in `docs/BACKLOG.md` as B58, reworded. Not a blocker for this job.
5. Deviation 5 (a re-entrant probe message passes to the game): an unknown registered message, harmless; accepted.

### Checked and fine
- `s_ownsMouse` is published after every message fed, under `s_lock`; the machine is changed only in `GestureMessage` (`WM_CAPTURECHANGED` reaches it through `WndProc`'s default branch).
- `GestureMessage`/`GestureSetWindow` test `s_lockOwner` before taking the lock; the owner is set after acquiring and cleared before releasing; re-entry returns the message untouched.
- `WM_CAPTURECHANGED`: no `SetCapture`/`ReleaseCapture` in `proxy/src`, so the kill criterion does not fire.
- `s_ctlHeld` is set from the phase under the lock after the press messages; `"held"` is in every ctl result.
- No new import or hook; the VERSION bump (0.23.0 over main 0.22.0) is consistent. The version is the builder's choice of "next free": re-read `origin/main` before merging.
