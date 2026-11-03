# W2 report: RmlUi host in the proxy

RmlUi 6.3 now lives inside the proxy DLL, off unless a game sets `ui.enabled`. This is the game-agnostic half of napoleon-remastered J30. It
adds the pure decisions in `proxy/src/ui_core.h` (the D19 scale model, input routing, the device lifecycle, the `ui` ctl grammar), the host
in `ui_host.cpp` (device and window hooks, the frame pass, input glue, a lossless PNG dump), the D3D9 render interface ported from
empire-remastered (`ui_render_d3d9.*`), and a second Lua 5.1.1 (float) with RmlUi's Lua plugin whose `lua*` symbols are all made local.
It also adds `ctl ui show|hide|reload|scale|click|wheel|dump|state`, the null game's `ui.*` keys and pins, `proxy/tools/fetch_ui.py` with the
build changes (system-only imports, byte-identical `repro`, the build id covering the fetcher and the pin file), `pc_deploy.py kit_ui`, a
`VtableHook` fix (a detour already in a slot's chain is never installed again), the host tests `test_ui_core.cpp` and `test_ui_rml.cpp`,
`docs/PROXY_UI.md` and `VERSION` 0.10.0. The PC evidence is the consumer's: napoleon-remastered run `proxy/runs/20261102_j30pc/` on
`job/J30`. Core PR https://github.com/liam-rowley/warscape-core/pull/17.

Written by the orchestrator from the finishing agent's hand-back (the harness refuses a subagent's Write of a report file); same
Claude-Session as the build.

## What was built

| Part | Files |
|---|---|
| Pure decisions, host-tested | `proxy/src/ui_core.h` (scale model: dp = back-buffer height / 1080 x `ui.scale` / 100, 85-125 in steps of 5, clamped and logged; `UiDecide` input routing; `UiLifecycle` for Reset, re-creation and destroyed devices; `UiIsMainDevice`; the `ui` ctl grammar) |
| Host | `proxy/src/ui_host.cpp`/`.h`: `IDirect3D9::CreateDevice`, device `Reset` and `Present` hooks (chained), a window subclass, DirectInput `GetDeviceState`/`GetDeviceData` blanking while RmlUi owns an event, the frame pass inside a `D3DSBT_ALL` state block, `ui dump` through a plain render target; every RmlUi call under one lock, ctl work deferred to the next Present |
| Render interface | `proxy/src/ui_render_d3d9.*` (ported from empire-remastered: layers, filters, clip masks, gradients, box-shadow), shaders compiled at start through `d3dcompiler_47.dll` then `_43`, loaded at run time; no compiler means a logged "UI off" |
| RmlUi helpers and Lua | `ui_rml.h`, `ui_lua.*`, `ui_lua51_compat.h` (the viewer's 5-function compat header); `build.sh` links `ui_lua.cpp`, RmlUi's Lua plugin and the host's Lua copy with `ld -r`, localises every `lua*` symbol with `objcopy` and fails if one is left global |
| Wiring | `backend.cpp` (`UiOnDirect3DCreate`), `dllmain.cpp`, `dev.cpp`/`devcore.h` (`ctl ui ...`), `ui_d3d9.h`, `hooks.cpp` (`VtableHook` chain rule) |
| Build | `proxy/tools/fetch_ui.py` (RmlUi, FreeType, Lua, stb by the game's one pin file through `layout.py ui-pins`), `build.sh` (RmlUi Core with its FreeType engine and FreeType, TrueType only, cached per compiler under `build/ui/obj/<tag>`), `build_id.py` (roles `fetch_ui`, `ui_pins`), `layout.py ui-pins`, `pc_deploy.py kit_ui`, `warscape/repo.py` (`[proxy] ui_pins` default) |
| Null game | `proxy/tests/null_game`: `ui.*` rows in `registries/config_keys.jsonl`, `nullgame.ini`, regenerated `generated/tables.h`, `viewer/pins.json` with no game names |
| Tests and docs | `proxy/tests/test_ui_core.cpp` (scale table, routing table, lifecycle state machine with a fake device, ctl grammar, the D3DCompile blob vtable lint), `proxy/tests/test_ui_rml.cpp` (a document on a null render interface, event dispatch, the float32 Lua number test, compat-header checks), `tests/test_moved_tools.py`, `docs/PROXY_UI.md`, tools rows `proxy.tools.fetch_ui` and the `layout` usage |

The keys: `ui.enabled` (0 by default and in release: `UiInit` returns after reading it, nothing is hooked, loaded or allocated), `ui.scale`,
`ui.dir`, `ui.show` (dev), `ui.dump_dir`.

## Evidence

- **PC (the consumer's run, napoleon-remastered `proxy/runs/20261102_j30pc/` on `job/J30`).** DXVK, headless at 1920x1080, 2560x1440 and
  3840x2160. Final build id `68a9bc84bb05` (4,224,512 B; 973,312 B before the host; imports advapi32, dbghelp, kernel32, msvcrt, user32).
  `build.sh --docker all` took 415 s fresh and about 155 s with the RmlUi and FreeType objects cached; `repro` was identical.
  - Two start-up faults were found there and fixed in this branch. First, an access violation at EIP 0 in `CompileShaders`: GCC turned
    calls through a TU-local abstract class into `call 0`. It is now a C-style vtable, and `test_ui_core` lints it. Second, every land battle
    load hung: the loader's helper device shares the main device's vtable, and the dev side re-hooked Present in front of the host. That is
    now the `VtableHook` chain rule; with it the battle loaded with the document in 16.1 s.
  - Dumps and checks: rules, box edges and H height are ok at 100% at all three sizes in the front end, campaign, battle and after a warm
    reset. At 1080p x 85 a 1 dp rule on a half pixel vanished (fact `rmlui63.sub_pixel_rule`). At 4K x 125 one of four text sizes is
    1.8 px over the cap-height check. No blended edge rows anywhere.
  - Interaction: all nine routing checks passed in every scene and size, and after a warm reset.
  - Frame cost: host CPU per drawn frame p50 0.06-0.11 ms, p99 0.14-0.18 ms. The idle host is p50 0.000 ms and cannot be told apart
    from off within the 0.3 ms run-to-run spread. Memory: address space +2-8 MB, commit +0-6 MB with the document shown.
- **PR #17 CI on 0dd20b0** (before the merge of main): gates run https://github.com/liam-rowley/warscape-core/actions/runs/41522181461.
  Every job passed: `gates (ubuntu-latest)`, `gates (windows-latest)`, `proxy` (null game `build.sh all`, `repro` and the wine `smoke`) and
  `harness-windows`. The earlier run 41520985266 on the same sha also passed.
- **Local, after merging origin/main (dee4792, 2026-11-02).** The merge touches no DLL input: main's changes since the merge base include no
  `proxy/` file.
  - `python3 wsc.py gates`: 13 ok, 1 warn, 0 failed. The warn is one skipped test,
    `PrePush.test_hook_runs_the_fast_gates_from_a_game_repo`, which needs a POSIX sh and symlinks; 221 host tests passed.
  - The proxy CI job's steps in the pinned ubuntu:24.04 image, null game (`WSP_GAME_ROOT=proxy/tests/null_game`, `WSP_BUILD_ID` set as
    CI does). `build.sh all` passed: every C++ host test, including `test_ui_core` 212 passed and `test_ui_rml` 25 passed. The DLL is
    4,213,248 B with imports advapi32, dbghelp, kernel32, msvcrt, user32. `repro`: identical from another path. `smoke`: passed
    (5 launches under wine, 2 dumps).

## Deviations from the brief and why

- **CI timeout.** The `proxy` CI job's timeout went to 30 minutes in `ci/gates.yml.in`, and `.github/workflows/gates.yml` was rendered from
  it. The brief does not list this. RmlUi and FreeType compile twice (mingw for the DLL, g++ for the host tests), and the old limit was
  too short.
- **Version.** The branch first set 0.9.0; the J62 promotion took 0.9.0 on main, so 0dd20b0 moved this to 0.10.0 as the brief says.
- **Device logging.** A logging-only commit, 282c692, records the main device's depth format, back-buffer format, swap effect and Present
  thread. The consumer's fact rows need these: the depth stencil, and where Present runs.
- **Merge, not rebase.** The branch was merged with origin/main (C19: views are not committed, the brief/W2 row), not rebased, because
  it is pushed with an open PR. The only conflict was `registries/tools.md`: main deleted it and this branch had modified it. It is deleted
  as on main; the branch's rows (`proxy.tools.fetch_ui` and the `layout` usage) are in `registries/tools.jsonl`, and
  `reg render` writes the view to `_scratch/`.

## Open questions

- **Which commit built 68a9bc84bb05?** The consumer built it with core at a local, unpushed branch `napoleon-j30` `f12b56e`. That commit
  is not in this repo, so its DLL inputs could not be checked against job/W2. The later commits 282c692 (device logging, a DLL input) and
  0dd20b0 (VERSION and the CI template) may have come after it. If the build id at the consumer's pin differs, the consumer re-runs on the
  new id (the brief's second kill criterion).
- **Rule 79's 20-pass run.** The acceptance run on the final build id with the host idle is not in `20261102_j30pc`. It is the consumer's
  (J30 deliverable 7), and should run on the build from the tag this PR becomes.
- **System d3d9 backend.** It is not measured: the headless launch with `proxy.backend=system` failed before the front end even with the
  host off (`HEADLESS FAILED: no on_virtual status`). This looks like a headless problem, not a host one (napoleon J61 is that job).
- **Scale edge cases.** The two check failures, 1080p x 85 (the sub-pixel 1 dp rule) and 4K x 125 (14 dp text), need an answer: a
  snapping rule for 1 dp borders in the RCSS (napoleon J34's tokens), or a host-side dp rounding. The crispness verdict is Liam's, from `crops/`.
- **Local build id.** `build_id.py` cannot hash the null game in place: a game root that is a folder inside the repo resolves its paths
  against the repo top (backlog B16). CI and local runs set `WSP_BUILD_ID`, and `build.sh --docker` cannot build the in-repo null game
  (the core sits outside the mounted game root).
