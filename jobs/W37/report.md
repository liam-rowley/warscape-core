# W37 report: The proxy smoke runs for a game without gestures or the null game's sites

Written by the orchestrator from the builder subagent's hand-back (the harness refuses a subagent's write of a report file); the text is
the builder's own apart from this note and the VERSION, which the orchestrator set to 0.27.0. The builder took 0.28.0, while W24 holds
0.27.0 on its branch; W37 is the one that unblocks napoleon J64 and is expected to merge first. Branch `job/W37`, no DLL input changed.

## What was built
- **`proxy/tools/build.sh` smoke.** Steps 6, 7 and 8 now branch on what the build's own log shows, never on the game's name.
  - **Step 6** accepts either `gesture: on: drag 6 px` or the no-adapter line
    (`gesture: controls.gestures=1 but no adapter (the game has no GestureAdapter): the layer is inert`).
    - Anything else fails: a missing callback, a crash, or no `gesture:` line at all.
    - On the no-adapter line it prints `build.sh smoke: this game has no GestureAdapter: steps 6 and 7 check the inert path`.
  - **Step 7** keeps `gesture: the RmlUi host is off (ui.enabled=0)` when there is an adapter, and checks the no-adapter line when there is
    none. The "no UI hook went in" check stays for both.
  - **Step 8** peeks the first engine-site id from `$ADIR/generated/tables.h` and expects the same refusal. A game with no engine sites
    prints a note, waits on `old1.done` and checks the stale request only.
  - The final line is unchanged: `build.sh smoke: passed (8 launches under wine, 2 dumps)`.
- **A new fixture, `proxy/tests/null_game_no_gesture/`**: a copy of the null game with `GameAdapter::gesture = nullptr`.
  - It holds `proxy/null/` (the adapter without the gesture callbacks, its identity, ini and generated tables), `registries/` and
    `viewer/pins.json`.
  - `gen_tables.py --check` is current for it.
- **CI.** The `proxy` job in `ci/gates.yml.in` gains a second smoke step, with `WSP_GAME_ROOT=proxy/tests/null_game_no_gesture` (`build.sh dll`,
  then `build.sh smoke`). `.github/workflows/gates.yml` is re-rendered.
- **Docs.** `docs/CONSUMING.md` gains one paragraph in "The job pipeline": the proxy job runs the smoke on your adapter, and a game without
  gestures passes steps 6 and 7 on the inert path.

## Evidence
- **Red: local Docker, before the build.sh change.** `build.sh --docker all`, then `--docker smoke` on the fixture, printed
  `build.sh smoke: 'gesture: on: drag 6 px' not in the log`. The log showed the no-adapter warning. This is the same failure as napoleon run
  41801657509.
- **Green: local Docker, after the change.** `--docker smoke` on the fixture returned 0 and printed
  `build.sh smoke: this game has no GestureAdapter: steps 6 and 7 check the inert path`, then `build.sh smoke: passed (8 launches under wine, 2 dumps)`.
- **Green: CI run 41810276745** on `job/W37`. `changes`, both `gates` jobs, `harness-windows` and `proxy` passed. In the `proxy` job:
  - The null game's smoke printed only `build.sh smoke: passed (8 launches under wine, 2 dumps)`, so it took the `gesture: on` path.
  - The fixture's smoke printed the inert-path line, then `build.sh smoke: passed (8 launches under wine, 2 dumps)`.
- **Local gates.** `python3 wsc.py gates` (full): 13 ok, 2 warn, 0 failed. The warnings are W23's bootstrap trigger (W27's to remove) and the
  usual skipped tests: 625 host tests passed, 5 skipped.

## Deviations from the brief and why
1. **The local Docker run used a scratch tree, not the worktree directly.** `build.sh --docker` mounts only the game root, so a fixture folder
   inside the repo cannot reach `proxy/tools/build.sh`. A scratch tree put the core as `core/` beside the fixture's folders; the build.sh logic
   it ran is identical. A follow-up could let `--docker` mount its own root when the game root is inside it.
2. **The null game's smoke was not re-run locally on the new build.sh.** CI proved it (run 41810276745).
3. **Push history.**
   - The first workflow run had an unquoted `: ` in the new step name, which made the YAML invalid (run 41810176502, "workflow file issue",
     0 s). The next commit fixed it.
   - The fixture also needed `viewer/pins.json`, because the DLL build fetches RmlUi by its pins.
   - One push got a transient GitHub 500 and succeeded on retry.
4. **The fixture copies the null game's files** (about six small files) rather than sharing a tree. Its adapter's header says how to regenerate
   its tables.

## Open questions
None for Liam. Once napoleon J64 pins the tag cut from this merge, its `proxy` job takes the inert path in steps 6 and 7.
