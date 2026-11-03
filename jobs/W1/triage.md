# W1 triage: the core backlog into queue rows

One line per open backlog item, in backlog order, with one outcome: **Row P<n>** (a proposed `jobs` row), **Merged into B<n>**, or **Note** (stays a
backlog note, with the reason). A row that covers several items carries its fields on the line of its lowest-numbered item; the other items name it.
`P<n>` is the dependency order (a row depends only on lower numbers or on existing rows); the follow-up `plan/` branch assigns `W<n>` ids and adds every
row as `needs_brief`. Every row is phase 1 (the queue has no later phase yet). Read on main at e047ba0 (VERSION 0.13.0).

## Rows on main

| Item | Outcome | Title | Description | Model | needs_pc | depends_on | phase |
|---|---|---|---|---|---|---|---|
| B1 | Row P7 (B1, B46) | Game-specific gates, and the five hook names as gate modules | `wsc.toml` `[gates] dirs = [...]` and game gate modules with the verb contract (`NAME`, `run(ctx) -> Result`) run by `wsc gates` (B1); then move `brief_problems`, `queue_problems`, `policy_problems`, `view_panel` and `summary` (`warscape/hooks.py`) onto that contract, with a migration path for napoleon's hook module (B46). | opus: a new extension point every game builds on, plus a migration of the pipeline's live hooks (C18) | false | - | 1 |
| B2 | Row P8 (B2, B3) | Core schema extension and modifier-agnostic hotkeys | A game schema with `"x-extends": "core:<name>"` plus extra properties, merged at load, so one extra field no longer means replacing a core schema (B2); a `fires_with_any_modifier` field on vanilla rows of `schemas/hotkeys.schema.json`, and the clash check compares the bare key for those (B3). | sonnet | false | - | 1 |
| B3 | Row P8 (on B2) | | | | | | |
| B4 | Note | | Waits on a game's evidence: its own line defers the decision (whether game-derived rows are committed at all) to napoleon's discovery phase, and 0.6.0 already keeps views out of git. | | | | |
| B6 | Row P9 (B6, B28, B43) | Registry verbs: reg remove, last_used stamping, exe words in find | `wsc reg remove <reg> <id>` deletes a row (its file in `dir` storage) after checking no `x-ref` points at it (B28); the job queue stamps a tool's `last_used` when a job report cites it, and C9 retirement warnings come back on (B6); `wsc find` hands exe-shaped words to the game's exe string index (`exe_strings.py find`) instead of indexing the strings into a registry (B43). | sonnet | false | W4 | 1 |
| B7 | Row P5 (B7, B11, B12) | core_pin: testable, worktree-safe, shallow-safe | `core_pin` reads `VERSION` from `ctx.core_root` and gets the failing-fixture test on a throwaway dirty core (B7); it resolves the core's git status with the core's own `GIT_DIR`, not one leaked from a superproject hook in a linked worktree (B11); on a shallow submodule it compares against the pinned tag's commit instead of failing on "tags exist, none on HEAD" (B12). | sonnet | false | - | 1 |
| B9 | Note | | Low value: its own line says so while upgrades are two lines; revisit with B1 (the policy route) or when a split pin pair bites. | | | | |
| B10 | Row P6 (B10, B13, B24, B49) | Guards: commit-msg trailer hook, run-README references, stale moved paths, committed views beside a jobs registry | A `.githooks/commit-msg` that refuses a commit whose last paragraph has no `Claude-Session:` trailer, opt-in from `wsc.toml` (B10); a gate that every repo path a `runs/**/README.md` names exists (B13); a lint for moved-away `*/core/` paths in core files, fixing `harness/job.sh` line 5 (B24); `wsc jobs check` fails when `[views] commit = true` and a `jobs` registry is declared, naming C19, and `policy` adds a C19 hint to its brief-branch refusal (B49). | sonnet | false | - | 1 |
| B11 | Row P5 (on B7) | | | | | | |
| B12 | Row P5 (on B7) | | | | | | |
| B13 | Row P6 (on B10) | | | | | | |
| B14 | Note | | Waits on B1 (P7) and a second consumer: napoleon has the rule in its own tests, the stalling functions are a game fact, and Empire, the second user, is not on the core yet. | | | | |
| B15 | Row P10 (B15, B16, B52) | The null game builds and tests on its own | Move the first consumer's console and camera checks out of `proxy/tests/test_console.cpp` and `test_camera.cpp` into an `<adapter>/tests/` hook that `build.sh tests` also compiles (B15); `build.sh --docker` and `build_id.py` work with the null game inside the core (B16); the null game's `viewer/pins.json` names only core things and `fetch_ui.py` validates it against a schema (B52). | sonnet | false | W2 | 1 |
| B16 | Row P10 (on B15) | | | | | | |
| B17 | Row P2 (B17, B18) | Harness host tests in the core and its own Git Bash finder | Port the Python host tests of the moved tools (pc_deploy, ctl, acceptance, the ESF tools, job.sh) from napoleon to the null game, so a core change is tested here (B17); give the core a Git Bash finder that `harness/ctl.py` uses instead of loading the game's `tools/verbs/setup.py`, and that a game's setup verb can reuse (B18). | sonnet | false | - | 1 |
| B18 | Row P2 (on B17) | | | | | | |
| B19 | Row P12 (B19, B22, B23) | Headless display guard: show-time hook, scaled-DPI own moves, status after relocation | A WinEvent hook (EVENT_OBJECT_SHOW, pumped on the guard thread) hides a window a DLL opens after start-up at once instead of within a sweep (B19); `display_guard.h` `IsOwnMove` recognises the logical rect at a scaled target DPI, or logs and re-places once (B22); `headless.cpp` rewrites `headless_status.json` after each verified relocation (B23). | sonnet | true | - | 1 |
| B20 | Row P4 (B20, B21, B27, B30, B39) | Watcher and pc_deploy race fixes | Race-free stale lock takeover in `job.sh lock` and the watcher's expiry (B20); a ps1 job's exit code from its last statement, not a stale `$LASTEXITCODE` (B21); the `kill` job returns only at `not_running` (B27); the prefs overlay sets every occurrence of a key or refuses a duplicated one (B30); `pc_deploy.py set` waits for, or refuses on, a pending profile restore (B39). Host tests first. | sonnet | false | P2, W5 | 1 |
| B21 | Row P4 (on B20) | | | | | | |
| B22 | Row P12 (on B19) | | | | | | |
| B23 | Row P12 (on B19) | | | | | | |
| B24 | Row P6 (on B10) | | | | | | |
| B25 | Row P11 (B25, B40) | Dev channel: stale ctl requests and a read-only peek | The proxy drops ctl requests older than its launch (B40); a read-only `peek <site>+<off> <len>` ctl verb, or a `watch` site kind that logs a function's return value, behind the same key and exe-identity guard as the other sites (B25). | sonnet | false | - | 1 |
| B26 | Row P3 (B26, B31, B51, B60) | Acceptance and scene launches: build id after launch, staged saves, hist_nile retry | `acceptance.py` (through `ctl.py` `build_info()`) reads the DLL build id after the launch, or refuses the kit-id fallback, so pass 1 on a fresh install counts (B26, B31); `ctl.py scene` stages a row's named save into the save folder under a harness name and clears it after (B51); find why the hist_nile relaunch sometimes gets no `on_virtual` within 180 s and retry the launch once inside `v_scene`, logged (B60, on plan PR #30). | sonnet | true | P2 | 1 |
| B27 | Row P4 (on B20) | | | | | | |
| B28 | Row P9 (on B6) | | | | | | |
| B30 | Row P4 (on B20) | | | | | | |
| B31 | Merged into B26 | | The same change: `build_info` falling back to the kit id when a fresh install has no `proxy.log` yet (napoleon J8 and J40 found it separately). | | | | |
| B32 | Row P13 (B32, B33, B34) | Capture: timeout path, render thread only, state blocks | `capture.cpp` `CaptureRun` reports `failed` when the second wait times out and lets the render thread close the file (B32); a recording keeps only the arming (render) thread's calls and counts the others (B33); hook `CreateStateBlock` (slot 59) and `IDirect3DStateBlock9::Apply`/`Capture`, at least as record lines (B34). | opus: thread ownership and new state-block vtable hooks in the D3D9 detours, where a mistake is a race or a crash in the game | false | - | 1 |
| B33 | Row P13 (on B32) | | | | | | |
| B34 | Row P13 (on B32) | | | | | | |
| B36 | Note | | A decision first: the backend interface is not in the line, and no consumer runs a DX11 renderer yet (Shogun 2 is not on the core). | | | | |
| B37 | Note | | Waits on a Shogun 2 consumer and sample packs to test against; no current game reads PFH2 or PFH3. | | | | |
| B38 | Note | | Waits on a Shogun 2 consumer and sample ABCF saves; no current game writes ABCF. | | | | |
| B39 | Row P4 (on B20) | | | | | | |
| B40 | Row P11 (on B25) | | | | | | |
| B41 | Row P1 (B41, B59) | Engine-site patch values: value_offset and numeric values from config keys | `engine_sites` rows get `value_offset`, an anchor before an opcode whose value follows an absolute address (B41), and patch rows may name an int or float `config_keys` key (`value_key`) whose value the proxy writes as the immediate, only when it differs from stock, logging it (B59, on plan PR #30). Files: `schemas/engine_sites.schema.json`, `proxy/tools/gen_tables.py`, `proxy/src/patch_engine.h`, `patch_driver.cpp`, a float key type in `config.h`, the patch engine host test. Unblocks napoleon J27. | sonnet | false | - | 1 |
| B42 | Note | | A decision first: a kit role for loose `data\` files needs rules the line does not give (what the install record owns, uninstall and Steam Verify behaviour, clashes with another mod's loose files). | | | | |
| B43 | Row P9 (on B6) | | | | | | |
| B44 | Note | | Low value now: its line says nothing else consumes it, and napoleon must first turn `CLASSES` and `GUARDS` into data. | | | | |
| B45 | Row P15 (B45, B47) | The core's CI: pipeline economies and a settings check | Adopt push-only triggers, pass markers and the `changes` job for the core's `proxy` and `harness-windows` jobs in `ci/gates.yml.in` (B45); a `wsc ci check-settings` verb that reads branch protection with `gh api` and names the missing required checks and auto-merge settings (B47). | sonnet | false | - | 1 |
| B46 | Row P7 (on B1) | | | | | | |
| B47 | Row P15 (on B45) | | | | | | |
| B49 | Row P6 (on B10) | | | | | | |
| B50 | Note | | A decision first: `card_extra` would be a sixth hook name, and C18 caps the hook module at five ("Five names and no more", `CONSUMING.md`); decide whether B46's gate modules, a C18 amendment or `view_panel` carries it. | | | | |
| B51 | Row P3 (on B26) | | | | | | |
| B52 | Row P10 (on B15) | | | | | | |
| B53 | Row P14 (B53, B58) | UI host and gesture driver hardening | `ui_host.cpp` `hk_DIState`/`hk_DIData` read the route state under a lock or as one atomic word, and `WM_ACTIVATEAPP` clears `s_rmlOwner` with the button masks (B53); `gesture.cpp`: no adapter callback under the non-re-entrant `s_lock`, `WM_CAPTURECHANGED` as focus loss, `ctl gesture press` holds only after a begin, one `D3DSBT_ALL` state block reused across preview frames, and a ctl smoke walk (B58 a to e). | sonnet | false | W2, W6 | 1 |
| B57 | Note | | A decision rather than code: whether the host may hook with `ui.enabled=0` (relaxing W2's lint) or gestures keep needing `ui.enabled=1`; Liam's or the consumer's call. | | | | |
| B58 | Row P14 (on B53) | | | | | | |

## Rows on open PRs (re-check after they merge)

These rows are not on main: B54 to B56 are on `job/W4` (PR #28), B59 and B60 on `plan/backlog-numeric-keys-nile-flake` (PR #30), read 2026-11-03.
Re-check each line against main once its PR merges (the text or the number may change in review).

| Item | Outcome | Title | Description | Model | needs_pc | depends_on | phase |
|---|---|---|---|---|---|---|---|
| B54 | Note | | Waits on a second game: its own line says a second game's atlas is the reason to move the tables, no second game has a UI atlas, and W4 (which adds the module) is not merged. | | | | |
| B55 | Note | | Game-repo work, not a core change: a regeneration commit on napoleon's first PC sitting re-stamps committed results; nothing to build in the core. | | | | |
| B56 | Note | | Waits on a second game, as B54: the reference-repo paths and word lists move to `games.json` or an adapter loader when a second reference repo exists; W4 is not merged. | | | | |
| B59 | Row P1 (on B41) | | | | | | |
| B60 | Row P3 (on B26) | | | | | | |
