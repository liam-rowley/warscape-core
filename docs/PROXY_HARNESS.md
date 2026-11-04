# The proxy, the harness and the save tools (0.4.0)

What the core carries for a game and how a game repo runs it. Moved out of [CONSUMING.md](CONSUMING.md) on 2026-11-04 to keep that doc
under the 30 KB cap; the text is unchanged.

From 0.4.0 the core carries the proxy DLL's core (`proxy/src`), its host tests and tools (`proxy/tests`, `proxy/tools`), the PC
watcher kit (`harness/`) and the ESF save tools (`saves/`). A game keeps its adapters: `proxy/<game>/` (adapter.cpp, identity.json,
the generated tables and config file, lua/) and `harness/<game>/` (adapter.json, profiles/), plus its registries. The tools find
them through `proxy/tools/layout.py`: the game root is the superproject that pins the core (or `$WSP_GAME_ROOT`), and the adapters
are `wsc.toml` `[proxy] adapter` / `[harness] adapter` when set, else the one `proxy/*/adapter.cpp` / `harness/*/adapter.json`.
Run them from the game repo as `core/proxy/tools/build.sh`, `core/harness/job.sh` and so on; `python3 core/proxy/tools/layout.py`
prints what they will use. The DLL build id hashes the inputs' content under role names, read through the gitlink for files in
the core, so moving them here kept every game build id (napoleon J12); the build contract (the roles, the toolchain pin and its check, tracked
sources only, the DLL's `self_hash` log line, the CI step summary) is [PROXY_BUILD.md](PROXY_BUILD.md). The core's CI builds and tests them against the null game
(`proxy/tests/null_game/README.md`); from 0.19.0 the tools' Python host tests run here too (`tests/test_pc_deploy.py`, `test_ctl.py`,
`test_acceptance.py`, `test_saves.py`, `test_job_sh.py`; W8), so a game keeps only the tests over its own data (its scenario rows and
battle presets for rule 78, its save map, recipes and staging, its real identity).
The Git Bash finder is core code from 0.19.0 (`warscape/gitbash.py`: `harness/ctl.py` no longer loads the game's `tools/verbs/setup.py`): a
game's setup verb imports it (`from warscape.gitbash import git_bash, bash_kind, bash_for_tests`; verbs run with the core on `sys.path`)
instead of keeping its own, and a host test that runs a shell script takes its bash from `bash_or_skip(self)` (a skip, or a failure under
`$WSC_REQUIRE_BASH`).
A pending virtual-display restore (`vdisplay_restore.json`) whose saved position can no longer apply restores the saved mode at the display's current origin
(watcher 1.3.0, 0.14.0, W5); a missing virtual display drops the record to `_to_deletedisplay_restore_<utc>.json.dropped` (D38 of the first consumer).
A headless launch whose game writes `refused` and exits before the watcher looks now fails with the proxy's own detail, not "not running after
the start" (watcher 1.4.1, 0.30.1, W38); update the PC's watcher with `update kit=`.

**The UI pin file** (`[proxy] ui_pins`, else `viewer/pins.json`; the `ui_pins` input) needs `rmlui`, `freetype`, `lua`, `stb_image` and
`stb_image_write` (the PNG dump, since 0.10.0); copy a missing entry from the null game's `proxy/tests/null_game/viewer/pins.json`.
From 0.34.0 (W16) it has a schema, `schemas/ui_pins.schema.json`: each git pin a `version`, an https `repo` and a 40-hex lower-case `commit`
(optional `tag`, `licence`, `why`); `lua` and the stb files a `version`, an https `url` and a 64-hex lower-case `sha256` (`lua` also a `licence`;
the stb files an optional `commit`); `_doc` a string; any other key an object (a game's own pins, such as a viewer's image). `fetch_ui.py`
validates before it fetches and names every problem; `fetch_ui.py --check [--pins FILE]` validates only, with no network (a game's test can call it).

**A game's own proxy host tests** (0.34.0, W16): `build.sh tests` compiles and runs the core's `proxy/tests/test_*.cpp`, then the game's, sorted,
with the same flags plus `-I<game tests>`, and prints `core test <name>` / `game test <name>`; a failing game test fails the target. The folder is
`wsc.toml` `[proxy] tests` (repo-relative), else `<game>/proxy/tests` when it holds a `test_*.cpp`, else none (`$WSP_PROXY_TESTS` overrides;
`layout.py proxy-tests` prints it). It must sit outside the adapter folder (a build-id input: a test edit would be a new DLL). A game's console and
camera numbers (opcodes and offsets in its sites' stock bytes, its command tables) live there: `#include "adapter_checks.h"` and `"adapter.cpp"`, run
`adck::ConsoleAdapterProblems` / `adck::CameraAdapterProblems` with `adck::TableLookup(a.sites, a.nSites)` (the contract the core's reads need),
then the literal checks. The null game's `proxy/tests/null_game/proxy/tests/test_null_adapter.cpp` is the smallest example.
`build.sh --docker` mounts the outer of the game root and the core (the game repo holding the core, or the core holding its null game) and refuses
two separate trees; `build_id.py` reads a game root nested in its repository under its prefix, so the null game's id in place is a real one.

Proxy features a game turns on through its adapter and its config_keys rows each have one contract doc: the RmlUi host
([PROXY_UI.md](PROXY_UI.md)), battle unit orders ([PROXY_ORDERS.md](PROXY_ORDERS.md)) and, from 0.13.0, the gesture layer
([PROXY_GESTURES.md](PROXY_GESTURES.md): a `GestureAdapter` in `GameAdapter::gesture`, the `controls.gestures` key, the ctl `gesture` verb;
`GameAdapter` gained that member, so an adapter's aggregate initialiser needs one more entry, `nullptr` for none).
The frame capture (`dev.capture`, the ctl `capture` verb, the `frame.txt` record lines) is [PROXY_CAPTURE.md](PROXY_CAPTURE.md): from 0.21.0 it hooks
37 device slots and 2 state-block slots, fails an abandoned or empty capture with a `state`, records only the thread that took the arm, and writes
`SBCREATE`, `SBCAPTURE`, `SBAPPLY` (with a `STATE` readback), `OTHERTHREAD` and `ABANDONED` lines; a game's own capture docs point there.
Engine sites and their config keys ([PROXY_SITES.md](PROXY_SITES.md)): from 0.16.0 a `patch` row may take its value from a numeric key
(`value_key`, `value_scale`, `value_floor_stock`) and a key may carry `type`, `min` and `max`. Nothing changes for existing rows (their
generated tables are byte-identical); after the pin bump run `python3 core/proxy/tools/gen_tables.py --check`.
The dev control channel ([PROXY_CTL.md](PROXY_CTL.md)): from 0.18.0 a request written before the game process started is refused as
`stale` (job.sh exit 2: resend it), never run; the read-only `peek <site>[+|-<off>] [*[+|-<off>] ...] <len>` reads from an accepted engine site.
