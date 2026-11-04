# W37: The proxy smoke runs for a game without gestures or the null game's sites

Model: Sonnet, reason: none needed (Sonnet is the default). Shell-script changes to one test step list, checked in CI; no DLL source change,
no reverse engineering, no PC. Budget about 40 tool calls.

## Goal
napoleon-remastered J64 (the pin bump to v0.22.0) cannot merge: its required `proxy` job fails in `proxy/tools/build.sh smoke` step 6
(napoleon run 41801657509: `build.sh smoke: 'gesture: on: drag 6 px' not in the log`). Steps 6, 7 and 8 of the smoke assume the null game's
adapter, which no real game matches until it has the same pieces:
- **Step 6** (gestures with the RmlUi host) expects `gesture: on: drag 6 px`. A game whose `GameAdapter::gesture` is null logs
  `gesture: controls.gestures=1 but no adapter (the game has no GestureAdapter): the layer is inert` instead (`proxy/src/gesture.cpp` `GestureInit`).
- **Step 7** (gestures without the host) expects `gesture: the RmlUi host is off (ui.enabled=0)`. With no adapter, `GestureInit` returns at the
  no-adapter check first, so that line never comes.
- **Step 8** (the control channel) peeks `null.dummy_hook`, a site only the null game has, and expects `sites not accepted by the patch engine`.

Make the smoke hold for any consumer: each step asserts what that game's build must do, and the null game keeps every assertion it has today.
The audit calls the smoke the only off-PC check of a consumer's DLL (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md` C5), so a step that a
consumer cannot pass is a hole, not a nuisance.

## What exists
- `proxy/tools/build.sh`: the `smoke` block, steps 1 to 8, and `check` (a grep of the launch's `proxy.log`); the final line
  "build.sh smoke: passed (8 launches under wine, 2 dumps)". The block runs for the null game in the core's CI (`WSP_GAME_ROOT=proxy/tests/null_game`)
  and for each consumer's adapter in that consumer's `proxy` job.
- `proxy/src/gesture.cpp` `GestureInit` (lines 220 to 241): the order of the off reasons (config off, no adapter, no D3D hooks, RmlUi host off,
  a missing callback) and the `gesture: on: ...` line.
- The generated tables for the game being built (`gen_tables.py` output under the adapter's `generated/`) list its engine-site ids.
- `docs/PROXY_GESTURES.md` and `docs/CONSUMING.md` (what a consumer's `proxy` job runs).

## Decisions already made
1. **Branch on what the build has, read from the build's own log, not on the game's name.** Step 6 accepts either
   `gesture: on: drag 6 px` or the no-adapter line, and fails on anything else (a missing callback, a crash, no `gesture:` line at all). When the
   no-adapter line is seen, the smoke prints one line, `build.sh smoke: this game has no GestureAdapter: steps 6 and 7 check the inert path`.
2. **Step 7 with no adapter** checks the no-adapter line and that no UI hook went in; with an adapter it keeps today's checks.
3. **Step 8 peeks a site of the game being built.** It takes the first engine-site id from the game's generated tables (the stand-in exe refuses
   every site, so the expected refusal is the same for any game). A game with no engine sites keeps a stale-request-only step 8.
4. **The null game's assertions are unchanged**, and the final line keeps the count of launches and dumps.

## Steps
1. Reproduce the failure locally where a shell can run the smoke (or in CI on this branch): build with a fixture adapter whose `GameAdapter::gesture`
   is null. The simplest fixture is a copy of the null game with `gesture` set to `nullptr` under `proxy/tests/`; name it as a test fixture, not a
   game. It must be red against today's `build.sh`.
2. Change steps 6, 7 and 8 as the decisions say.
3. Add the fixture to the core's `proxy` CI job (`ci/gates.yml.in`, re-render) as a second smoke run, so both paths are proven in the core's CI.
4. Docs: one paragraph in `docs/CONSUMING.md` ("The proxy job runs the smoke on your adapter; a game without gestures passes steps 6 and 7 on the
   inert path").

## Proof
- The core's CI `proxy` job: the null game's smoke passes unchanged (its log keeps `gesture: on: drag 6 px`), and the no-gesture fixture's smoke
  passes on the inert path. Cite the run id and the two final lines.
- The fixture was red before the change (cite the run or the local output).
- `python3 wsc.py gates` (full) green.

## Open questions (only where Liam must choose)
None. If the builder finds a step that cannot be made game-agnostic without a DLL change, that is a kill criterion, not a question.

## Kill criteria
- A step can only pass with a change to a DLL input (`proxy/src`, the adapter): stop, commit what is done, and report; do not change the DLL.
- CI is still red after three fix attempts, or more than about 40 tool calls: stop, commit, and report what is left.

## Finish
Report in `jobs/W37/report.md` (what was built, the red and green runs, the version taken, deviations, open questions), then
`wsc reg set jobs W37 status=review report=jobs/W37/report.md` (`python3 wsc.py`). Push `job/W37`, open the draft pull request, and stop: an
independent reviewer merges (C18). VERSION: the next free minor above main and every open `job/*` branch at the time; the orchestrator renumbers
at merge.
