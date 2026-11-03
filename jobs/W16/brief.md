# W16: The null game builds and tests on its own

Model: Sonnet, reason: none needed (Sonnet is the default). Build-script, layout and fixture work with host tests: one bash script, two Python tools, a
schema, a test header and the null game's files; no engine change and no PC. Budget about 110 tool calls (the Docker and CI round trips are slow: allow
for them). At the cap, stop, commit, and report what is left.

## Goal
Three backlog items left by moving the proxy into the core (napoleon J12) and by W2 (`docs/BACKLOG.md` B15, B16, B52; all three removed when this merges):
- **B15, a game's adapter checks out of the core's tests.** `proxy/tests/test_console.cpp` (the `if (Adapter().console)` block) and `proxy/tests/test_camera.cpp`
  (`if (Adapter().camera)`) compare the first consumer's offsets, opcodes and command names with literals (`0x9fc`, `0xf4`, `0x281b8`, `0x800`, `all_end_turn`,
  ...). They are skipped for the null adapter, so the core carries one game's facts that it never runs. Give a game its own C++ host tests that `build.sh tests`
  compiles beside the core's, and move the literals there.
- **B16, the null game builds in place.** `build.sh --docker` mounts only the game root, so a game root inside the core (`proxy/tests/null_game`) cannot see
  `proxy/src`; `build_id.py` looks its game-relative inputs up from the repository top, so it cannot hash the null game either. CI and every local run set
  `WSP_BUILD_ID` by hand (`ci/gates.yml.in` `proxy` job; W2 report "Local build id").
- **B52, the null game's pin file names only core things** (W2 review, later item): `proxy/tests/null_game/viewer/pins.json` is a copy of the consumer's, with an
  `emsdk_image` pin and `_doc`/`why` texts pointing at `viewer/core/fetch_sources.py`, `tests/test_viewer.py`, D30/D31 and J31, none in the core;
  `fetch_ui.py` checks only that five keys exist (`main`, the key loop), so a bad commit or sha256 shape is found by the network, not before it.

## Decisions already made (follow them; a deviation goes in the report with its reason)
1. **Game tests live outside the adapter folder.** The build id's `adapter` role hashes the whole adapter folder (`build_id.py` `INPUTS`), so tests inside it would
   make every test edit a new DLL. New key `wsc.toml` `[proxy] tests` (repo-relative folder; `warscape/repo.py` `DEFAULTS`, empty by default) and
   `proxy/tools/layout.py` `proxy_tests(game)` plus `layout.py proxy-tests`: the key when set, else `<game root>/proxy/tests` when that folder holds a
   `test_*.cpp`, else none. `$WSP_PROXY_TESTS` overrides it, like the other `WSP_*` variables. A folder inside the adapter folder, or the core's own `proxy/tests`
   (the game root is the core itself when no superproject pins it), is a `LayoutError` naming the reason.
2. **`build.sh tests` compiles the game's tests with the core's.** After the core's `proxy/tests/test_*.cpp` loop, the same loop over the game's folder (sorted), the
   same flags and include folders plus `-I<game tests>`, the same run arguments; a failing game test fails the target like a core one. `// link: ui` works the
   same. No game folder: the loop is skipped silently. The output names which set each test came from (`core` or `game`).
3. **The contract stays in the core, the literals move.** A new test-side header `proxy/tests/adapter_checks.h` (not a DLL input: `proxy/tests` is not in
   `INPUTS`) with `ConsoleAdapterProblems(const ConsoleAdapter&, lookup)` and `CameraAdapterProblems(const CameraAdapter&, lookup)` returning a list of problem
   strings, where `lookup` maps a site id to its `SiteDef`. They hold every check that follows from how `proxy/src/console.cpp` and `camera.cpp` **read** the
   adapter's sites: each named site exists, is a `kHook` row keyed by `dev.console` / `dev.camera`; each declared operand lies inside its site's stock bytes;
   where the core reads a value at a declared operand, that value agrees with the adapter field that names it (the slot call reads the same slot; the struct
   offsets the core uses equal the dwords at their operands); `cliCtxOff + 4 <= cliSize`. Rule for the builder: read `console.cpp` and `camera.cpp` first, and a
   check stays in the core only when it can be written against the adapter's own fields; a check against a literal number, opcode or command name that only the
   consumer's exe has moves to the consumer (list each moved check in the report, one line each, so the reviewer can match them against the deleted lines).
   `test_console.cpp` and `test_camera.cpp` keep their pure and source-lint blocks, drop the `if (Adapter().console)` / `if (Adapter().camera)` blocks, and gain
   cases that run the two checkers on a **synthetic** adapter and site table (one passing table, and one failing case per rule), so the contract checks run in
   the core's CI for the first time.
4. **The null game has a game test folder.** `proxy/tests/null_game/proxy/tests/test_null_adapter.cpp`: it includes `adapter_checks.h`, runs the checkers when the
   null adapter has a console or camera (it has neither: assert that, and that `identity.json` names the files `build.sh smoke` uses), so the hook is exercised
   on every CI run. Keep it small.
5. **`build.sh --docker` mounts the outer of the two roots.** `OWN` (the core) inside `ROOT` (a game repo with the core as a submodule): mount `ROOT`, as today.
   `ROOT` inside `OWN` (the null game): mount `OWN` and pass `WSP_GAME_ROOT=/src/<ROOT relative to OWN>`. Neither inside the other: refuse with a message naming the
   two paths (do not add a second mount). The adapter, the UI pins and the game tests go in as paths relative to the mount, as the adapter does now.
6. **`build_id.py` hashes a nested fixture.** When the game root is not its repository's top (`git rev-parse --show-prefix` is not empty), the game-relative
   inputs (the `adapter` and `ui_pins` roles) are looked up as `<rev>:<prefix><path>`; the core roles are found at the top as now. The id still hashes role names
   and object ids only, so the null game's id in place equals the id of the same files laid out as a separate game repo with the core as a submodule (test it).
   The `-dirty` check uses the same paths.
7. **CI uses the real id.** Drop `WSP_BUILD_ID: nullgame-ci` (and its comment) from the `proxy` job in `ci/gates.yml.in`, then `python3 wsc.py ci render` and commit
   both files; the DLL CI builds then carries the null game's real build id, which proves decision 6 on every push.
8. **The pin file has a schema, checked before any download.** `schemas/ui_pins.schema.json` (the `schemas` gate checks every `schemas/*.schema.json` against the
   subset): required `rmlui`, `freetype` (each `version`, `repo` (https URL), `commit` (40 lower-case hex), optional `tag`, `licence`, `why`), `lua` (`version`,
   `url` (https), `sha256` (64 lower-case hex), `licence`, optional `why`), `stb_image` and `stb_image_write` (`version`, `url`, `sha256`, optional `commit`,
   `licence`, `why`); optional `_doc` (string); `additionalProperties: {"type": "object"}`, so a game may pin more for its own tools (napoleon's viewer pins
   `emsdk_image`). `fetch_ui.py` validates with `warscape/schema.py` (`validate`; put the core root on `sys.path` from the script's own place, as `layout.py` is
   found) and exits naming every problem before it fetches; `fetch_ui.py --check [--pins FILE]` validates only and needs no network.
9. **The null game's pin file:** the same five source pins (the DLL must not change), no `emsdk_image`, `_doc` and `why` texts that name only core things
   (`proxy/tools/fetch_ui.py`, `docs/PROXY_UI.md`, `proxy/tools/fetch_lua.py`). A host test asserts the null game's `lua` pin has the same `url` and `sha256` as
   `fetch_lua.py`'s `PIN` (the "same tarball" claim the old `why` made by pointing at the consumer's test).

## Scope: files this job touches
- Changed: `proxy/tools/build.sh` (decisions 2, 5; header `usage:` if it changes), `proxy/tools/build_id.py` (decision 6), `proxy/tools/layout.py`
  (`proxy_tests`, `proxy-tests`), `proxy/tools/fetch_ui.py` (decision 8), `warscape/repo.py` (`[proxy] tests`), `proxy/tests/test_console.cpp`,
  `proxy/tests/test_camera.cpp`, `ci/gates.yml.in` and the rendered `.github/workflows/gates.yml`, `proxy/tests/null_game/viewer/pins.json`,
  `proxy/tests/null_game/README.md`, `tests/test_moved_tools.py` (layout, build id, pin file cases).
- New: `proxy/tests/adapter_checks.h`, `proxy/tests/null_game/proxy/tests/test_null_adapter.cpp`, `schemas/ui_pins.schema.json`.
- Rows: `python3 wsc.py reg add tools proxy/tools/build.sh proxy/tools/build_id.py proxy/tools/layout.py proxy/tools/fetch_ui.py` for any whose header changed
  (ids kept).
- Docs: `docs/CONSUMING.md` ("The proxy, the harness and the save tools": the game tests folder and `[proxy] tests`, the pin file schema, `fetch_ui.py --check`),
  `docs/PROXY_UI.md` (the pin file's schema, one line), `README.md` (schemas table only if you list the new schema there), `docs/BACKLOG.md` (remove B15, B16, B52),
  `VERSION`. No game names in core files (`tests/test_moved_tools.py` `NoGameNames` covers `proxy/`): say "the first consumer".
- Not touched: `proxy/src/` (the DLL's sources do not change; its bytes change only by the build id string the build embeds).

## Steps
1. Read `proxy/tools/build.sh` (the tests loop, `--docker`), `build_id.py`, `layout.py`, `fetch_ui.py`, `fetch_lua.py` (`PIN`), `proxy/tests/testkit.h`,
   `test_console.cpp`, `test_camera.cpp`, `proxy/src/console.h`, `console.cpp`, `camera.h`, `camera.cpp`, `proxy/tests/null_game/` (all of it),
   `tests/test_moved_tools.py`, the `proxy` job in `ci/gates.yml.in`, `jobs/W2/report.md` ("Local build id"). Check whether this session can build: Docker
   (`docker info`) for `build.sh --docker`, or a native `g++` and `i686-w64-mingw32-g++`; if neither, the C++ tests run in CI's `proxy` job: push early and read its log.
2. **Failing tests first**, committed red, in `tests/test_moved_tools.py`: `layout.py proxy_tests` (the key, the default folder, none, a folder inside the adapter
   refused, the core's own `proxy/tests` refused, `$WSP_PROXY_TESTS`); `build_id` of a fixture nested in a throwaway repo equals the flat layout's id (extend the
   existing flat versus submodule case); `fetch_ui.py --check` passes the null game's pins and fails, naming the key, on a 39-hex commit, an upper-case sha256, a
   missing `stb_image_write` and an `http://` URL; the null game's `lua` pin equals `fetch_lua.py`'s; the null game's pin file names no `emsdk_image`. In
   `proxy/tests`: the synthetic checker cases (decision 3).
3. Build B16 (decisions 5 to 7), then B52 (8, 9), then B15 (1 to 4).
4. **Local proofs** (each recorded in the report with its output's last lines): with `WSP_GAME_ROOT=proxy/tests/null_game` and no `WSP_BUILD_ID`,
   `proxy/tools/build.sh id` prints a real id (no `nogit`, no error), `build.sh --docker tests` and `build.sh --docker all` pass, and the DLL's id equals `build.sh id`.
   If Docker is not answering, say so and run what the native toolchain allows; CI's `proxy` job (decision 7) is the fallback proof for decision 6.
5. **Consumer rehearsal** (evidence only, about 15 calls, nothing committed or pushed to napoleon-remastered): copy its tree to a scratch folder outside both repos,
   put this branch's core at `core/`, write `proxy/tests/test_console_adapter.cpp` and `test_camera_adapter.cpp` there with the checks you moved (decision 3)
   and the two checker calls, and run `core/proxy/tools/build.sh --docker tests`. Napoleon pins v0.9.0, so its adapter may need the pin-bump edits of 0.10.0 to
   0.15.0 (`docs/CONSUMING.md`; e.g. the `gesture` member of `GameAdapter`, 0.13.0) to compile: make only those, in the copy. If it does not build within the
   budget, stop the rehearsal and say so. Either way put the two files' full text in the report under "## Consumer test files" so napoleon's pin-bump job can
   copy them.
6. Docs, backlog, rows, `VERSION`; then `python3 wsc.py gates` (full), CI's `proxy` and `harness-windows` jobs green, and
   `python3 wsc.py policy --branch job/W16 --base origin/main`.

## Tests and acceptance
- The step 2 cases red first, then green; every existing test green; CI's `gates` (Linux and Windows), `proxy` (null game `build.sh all`, `repro`, `smoke`, now
  with the real build id) and `harness-windows` green.
- `build.sh tests` output lists `test_null_adapter` as a game test and every core test as before; the core's tests name no consumer number or command (grep
  `test_console.cpp` and `test_camera.cpp` for the literals listed in the report: none left).
- The null game's DLL is byte-identical before and after this change except for the build id string (compare a `build.sh all` with `WSP_BUILD_ID=x` on `main` and on
  the branch, or say why it could not run); the five source pins are unchanged.
- No `proxy/src` file changes (`git diff --stat origin/main -- proxy/src` empty).

## VERSION
A minor bump: a new `wsc.toml` key (`[proxy] tests`), a new `fetch_ui.py` mode and stricter pin-file checking (consumer-visible, pre-1.0). Take the next free
minor at merge time: `origin/main` says 0.15.0 when this brief was written, `job/W7` claims 0.16.0, and other W rows (W7 to W21) may claim minors first. Re-read
`origin/main` `VERSION` and the open `job/*` branches before the last commit; the second to merge takes the next free number and merges `main` (never rebase).
Say in the report which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered; also goes into `docs/CONSUMING.md`)
In the pin-bump commit, or the job that carries it:
1. **Move the checks the core dropped**: add `proxy/tests/test_console_adapter.cpp` and `proxy/tests/test_camera_adapter.cpp` (the text in this job's report,
   "Consumer test files"; `#include "adapter_checks.h"`, `#include "adapter.cpp"`, call both checkers, then the literal checks). Without them the console and camera
   offsets of its exe are checked by nothing. `core/proxy/tools/build.sh tests` must list both as game tests and pass.
2. **Pin file:** `python3 core/proxy/tools/fetch_ui.py --check` must pass on `viewer/pins.json`. Today the file has no `stb_image_write` pin, which `fetch_ui.py` has
   required since 0.10.0 (W2): add it as the core's null game pins it. Its `emsdk_image` and other viewer pins stay (they are allowed extra keys). Its viewer
   test may call `--check` instead of its own key loop.
3. **Rule 79 (acceptance passes):** this tag changes three DLL-input roles (`build_sh`, `build_id`, `fetch_ui`), so the DLL build id changes even though no
   `proxy/src` line does: the pin bump that crosses it needs 20 consecutive acceptance passes on the new build id (`python3 core/harness/acceptance.py run`),
   like any `proxy/` change of the core (J58). Combine it with the pin bump's other passes; one 20-pass run covers every tag crossed.
4. **Rule 79 scope (napoleon's choice):** its `rule79_path` counts every `proxy/` path, so edits to its new `proxy/tests/` folder would need passes too although they
   are not DLL inputs; adding `proxy/tests/` to its `acc_exempt` is a one-line change in its own gate module. Recommended, not required by this tag.
5. `build.sh --docker` from the game repo works as before (the game root still contains the core, so the game root is mounted).
Napoleon pins v0.9.0 today: the commit that crosses this tag also follows each earlier version's notes in this file (0.10.0 to 0.15.0).

## Kill criteria
- The null game's DLL changes beyond its build id string, or a `proxy/src` file has to change: stop and report (this job must not change the DLL).
- A check in the core's console or camera block can be neither written against the adapter's own fields nor moved to the consumer without losing it (for
  example, it needs the consumer's exe bytes beyond its `stock_bytes`): stop that check after about 10 calls, keep it in the core under its `if`, and list it in
  the report.
- `build_id.py` cannot give the nested null game the same id as the flat layout without changing the id of an existing game layout (the flat and submodule
  cases in `tests/test_moved_tools.py` must keep their ids): stop decision 6 and 7 after about 20 calls, keep `WSP_BUILD_ID` in CI, ship the rest.
- Docker is unavailable and the native toolchain is missing: do not install system packages or start Docker Desktop yourself; prove what CI can prove and say
  what was not run.
- Core CI red after three fix attempts for a cause in this change: stop and report.
- Version collision handled as in VERSION above; never rebase a pushed branch.

## Open questions (with recommendations; the brief follows the recommendation unless Liam says otherwise)
1. **Where the game tests live: `<adapter>/tests/` (the backlog line) or outside the adapter?** Recommended: outside (decision 1), because the adapter folder is one
   build-id input and a test edit must not make a new DLL; `proxy/tests/` in the game mirrors the core's layout. Alternative: inside the adapter, with
   `build_id.py` excluding `tests/` from the adapter tree hash; rejected because it changes how the id is computed for every game (a new id for napoleon with no
   input change).
2. **A test-side `adapter_checks.h`, or the checks in `proxy/src`?** Recommended: test side (`proxy/tests`), so they are not DLL inputs and the DLL does not change.
3. **`[proxy] tests` key, or the default folder only?** Recommended: both (the key defaults to empty, `proxy/tests` is found when it exists), like `[proxy] adapter`
   and `ui_pins`; a game with an unusual layout sets the key.
4. **Drop `WSP_BUILD_ID` in CI?** Recommended: yes (decision 7): it is the only continuous proof that the nested id works. If the real id would make the `repro` or
   `smoke` steps depend on the checkout (it should not: the id is content-only), keep the variable and report why.
5. **Docker: two mounts for separate trees?** Recommended: no, refuse (decision 5): no current layout needs it, and a game root outside both a superproject and
   the core is only reachable with `WSP_GAME_ROOT` by hand.
6. **File overlap with the other core rows (W7 to W21)**, for whoever merges second (merge `main`, never rebase):
   - **W17** (dev channel; queued): `proxy/tools/build.sh` (an optional smoke launch) and `tests/test_moved_tools.py`.
   - **W12** (guards; queued): `proxy/tools/build.sh` comments (the stale moved-path lint, B24) and `tests/test_moved_tools.py`.
   - **W7** (engine-site patch values; `job/W7` open): the null game's `registries/` and generated `tables.h`, `proxy/tools/gen_tables.py`; W16 touches the null game's
     `viewer/pins.json`, README and a new `proxy/tests/` folder only, so no line overlaps, but `build.sh`'s `gen_tables.py --check` runs on both.
   - **W21** (the core's CI economies; needs a brief): `ci/gates.yml.in` and the rendered workflow; re-run `wsc ci render` after merging `main`.
   - **W8** (harness host tests in the core): the null game's `harness/` side and `tests/test_moved_tools.py`.
   - **W18** (headless guard) and **W19**, **W20** (capture, UI host): `proxy/src` and `proxy/tests/test_*.cpp`, but not the files above.
   - All rows: `docs/BACKLOG.md`, `docs/CONSUMING.md`, `warscape/repo.py` `DEFAULTS` (W13 and W11 change other tables) and `VERSION`.

## Finish
Report in `jobs/W16/report.md` (what was built, the tests red then green, the local proofs and where they ran, the moved checks one per line, the rehearsal's
result, "## Consumer test files", the version taken, deviations, open questions, what napoleon must do), then
`wsc reg set jobs W16 status=review report=jobs/W16/report.md` (`python3 wsc.py`). Push `job/W16`, open the draft pull request, and stop: an independent
reviewer merges (C18); Liam tags.
