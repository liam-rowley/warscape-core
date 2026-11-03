## Round 1 (2026-11-03, branch job/W2 at aba08da)

**Verdict: merge.**

Reviewer session f0fb4d22 (did not build or fix this branch). Read: `jobs/W2/brief.md`, `jobs/W2/report.md`, `docs/DECISIONS.md`,
`git diff --stat origin/main...job/W2` (35 files), the consumer's run `proxy/runs/20261102_j30pc/README.md` on napoleon-remastered `job/J30`.

### Machines
- `python3 wsc.py gates` (2026-11-03, worktree review-W2): 12 ok, 2 warn, 0 failed. The warns are the local hook path and the POSIX-only
  pre-push test skip, both environment, neither from this branch.
- CI on aba08da (PR #17): `gates` (ubuntu, windows), `proxy` (null game `build.sh all`, `repro`, wine `smoke`) and `harness-windows` all
  pass (runs 41540972413, 41540978650). `policy` is red (run 41540978560) only because there was no review and the row was not `done`;
  this review is that answer, so it is not a blocker.
- `python3 wsc.py policy --branch job/W2 --base origin/main` before the review: the same two refusals and nothing else.

### Claims against evidence
- The PC claims (two start-up faults and their fixes, the dump checks at three sizes and two scale edges, the nine routing checks, the
  frame cost and memory) are all in the consumer's run README with step records (`results.jsonl`), checks and crops. They match the report.
- The build-id provenance is stated honestly as open: `68a9bc84bb05` was built from an unpushed core commit `f12b56e`, and 282c692 (device
  logging) plus this review's `hooks.cpp` commit change DLL inputs after it. The brief's second kill criterion covers this: the consumer
  re-runs on the build id of the tag this becomes (J30 deliverable 7, rule 79's 20-pass run). Not a core blocker.
- The host-test counts (`test_ui_core` 212, `test_ui_rml` 25) are not in a committed log, but CI's `proxy` job runs `build.sh all` with
  every host test on the reviewed head and passes, which is the evidence that matters.

### The brief
Every deliverable is present: `ui_core.h`, `ui_host.*`, `ui_render_d3d9.*`, `ui_rml.h`, `ui_lua.*` (symbols localised and checked in
`build.sh`), `ctl ui ...` in `devcore.h`/`dev.cpp`, the five `ui.*` keys in the null game, `fetch_ui.py` (git commits checked against the
pin, downloads checked by sha256, the Lua tarball extracted by base name only), `build_id.py` roles, `layout.py ui-pins`,
`pc_deploy.py kit_ui`, the `VtableHook` chain rule, both host tests, `docs/PROXY_UI.md`, `VERSION` 0.10.0. The deviations (CI timeout
30 min, the logging commit, merge not rebase) are named with reasons. Nothing out of scope. No game names in the core.

### Risk-first reading
Picked `proxy/src/hooks.cpp` `VtableHook` (it changes every game's hooks, ui on or off) and `proxy/src/ui_host.cpp` (engine device, window
procedure and DirectInput on the game's threads), read in full. The off path is clean: `UiInit` returns after reading `ui.enabled`, and
`UiOnDirect3DCreate` and `UiCtl` check `s_on`. Reset releases default-pool resources before the engine's Reset and never holds the lock
across it; helper devices neither hook nor resize; the ctl thread queues work for the next Present and only touches RmlUi through it;
`ui dump` rejects bad rects in the parser (`ui_core.h:182`) and the back-buffer bounds in the host.

### Findings
- **should-fix (fixed in this review, 649c290)** `proxy/src/hooks.cpp:61-64` (as reviewed): `VtableHook` recorded a detour as installed
  before `VirtualProtect`; when that failed, every later call for the same slot and detour logged "already in the chain" and returned
  true for a hook that never went in. Now one lock covers the check, the install and the record, and a detour is recorded only after it is
  in the slot. Compiled with `-Wall -Wextra -Werror` by `i686-w64-mingw32-g++` (ubuntu:24.04, 2026-11-03); CI's `proxy` job builds it on
  push. It is a DLL input: the consumer's re-run (above) covers it.
- **later (backlog B52)** `proxy/tests/null_game/viewer/pins.json:2`: the core's fixture is a copy of napoleon's pin file; its `_doc`,
  `emsdk_image` and `why` texts point at `viewer/core/fetch_sources.py`, `tests/test_viewer.py`, D30/D31 and J31, none in the core.
  `fetch_ui.py:110` checks only that five keys exist; a pin-file schema would catch a bad commit or sha256 shape before the network.
- **later (backlog B53)** `proxy/src/ui_host.cpp:449,464`: the DirectInput hooks copy `s_route` without the lock while the window thread
  writes it (a torn read can blank or pass one frame wrongly); `WM_ACTIVATEAPP` (`ui_host.cpp:399`) clears the button masks but not
  `s_rmlOwner`. Nothing seen in the run's interaction cells.

### Other commits by this review
- 3823c7e merges origin/main (briefs W1, W3-W6, backlog B50-B51; no DLL input) so the backlog rows do not conflict.
- 251eeef backlog B52, B53.
