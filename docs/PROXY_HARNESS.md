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

## Guarded verbs (W35, C35)
Two permissions sessions kept asking for are verbs whose guard holds the judgement; an agent runs them without a one-off ask.
- **`wsc agent-settings allow|remove "<rule>" [...] [--file .claude/settings.json]`** adds a rule to `permissions.allow` only when a
  `[agent_settings] safe = [...]` pattern in `wsc.toml` covers it: the pattern itself, or the pattern extended by whole words
  (`"Bash(git status:*)"` covers `Bash(git status --short:*)` and `Bash(git status)`, never `Bash(git statusx:*)`) with no write- or
  run-capable flag among the added words (`--output`, `--ext-diff`, `--textconv`, `-c`, `--exec` ...: `WRITE_FLAGS` in the verb);
  `exact_only = true` allows only the patterns themselves. No `deny` rule may overlap it (a deny with a `*` inside, `Bash(git * --force)`,
  is read broadly: it blocks every rule its text before the `*` starts), and it has no wildcard but a trailing `:*` and no shell operator
  (`Bash(*)`, `Bash(git:*)`, `PowerShell(*)` refuse). Key order, indentation and line ends are kept; the write is atomic (a temporary file in
  the folder, then a replace) and `settings.json.bak` is replaced the same way with the file as it was before the run (each writing run
  replaces it: two runs keep only the second original). It never edits a hook or a `deny` entry and writes only a `.json` directly in the
  repo's own `<root>/.claude` once links are resolved: `.claude` a symlink or junction, a `--file` in another `.claude` folder, the file or
  its `.bak` a link, or a hard-linked file refuses (no hook line needed: `.claude/` is not a protected folder). It refuses without
  `[agent_settings]`. Exit 0, 1 write failed, 2 refused.
- **`job.sh vdisplay-aside <owner|-> <session> <why>`** moves `vdisplay_restore.json` to `_to_delete\vdisplay_restore_<utc>[_n].json.aside` (a unique
  name, `mv -n`, checked), appends the record to `watcher.log` and prints the saved mode, only when the file exists, the lock is free or
  `<owner>`'s, the watcher runs (`watcher.alive` under 15 s) and `watcher.status` lists no game process, and either the last `vdisplay: `
  line of `watcher.log` (at or after the file's time) is a `RESTORE FAILED` or `pending restore dropped`, or the file is older than
  `lock_stale_min`. Otherwise it refuses (2; 64 for usage or an empty why) with the next step. It never deletes and never sets the display mode.

## Acceptance evidence (W9, minor)
(Here, not in CONSUMING.md: that file is at its 30 KB cap.) `harness/acceptance.py run` writes **schema 2** pass files ([`schemas/acceptance_pass.schema.json`](../schemas/acceptance_pass.schema.json), `acceptance.pass_problems`):
`result` is `pass | fail | flake`, `build_id` is read from the pid-matched load line of *this* launch in `proxy.log` (`Pc.launches`; never the kit id, never the last launch's log),
and `evidence` holds `exe_sha1`, `baseline_sha256`, `shots{step: {sha256, bytes, baseline_sha256}}`, `kit_sha256` (the installed kit's manifest), `dll_sha256` (the installed `d3d9.dll`),
`dll_sha256_logged` (the DLL's `self_hash` line, W24; a mismatch fails step `dll_hash`), `watcher_sha256` (installed `src/watcher.ps1`), `watcher_kit_sha256` (`harness/watcher.ps1` at the core's git HEAD) and `launches`.
A launch whose build differs from the pass's first fails step `build_stable`. The ledger line adds `schema`, `watcher_sha`, `dll_sha256`, `kit_sha256`, `evidence_sha256` (sha256 of the pass file) and `flakes_allowed`.
- **Flake**: a pass whose first failed step carries `cause: headless_launch_lost` (`Pc.launch` retried once, after `ctl.launch.retry_settle_s`, default 10 s, and both attempts ended in a pre-`on_virtual` watcher text) with `exe_sha1` passed.
  A refused launch, a bad size and every later step stay `fail`. `acceptance.max_flakes` in the harness adapter (default 1, at most 3; `--max-flakes` may only lower it) are allowed per run; a flake is never a pass and the run goes on.
  The first attempt's `proxy.log`, `headless_status.json` and job output are kept in `<state>/acceptance/<run>/pass_NN/launch_evidence/attempt_N/`.
- **Refusals before pass 1**: a `--run` id with a pass file, a ledger line or a `<state>/acceptance/<run>/pass_*` folder; an installed `watcher.ps1` whose sha256 differs from the core's (fix: send a harness kit, `job.sh update kit=<id>`),
  or a running watcher whose version is not the installed file's. The pass file is opened with mode `x`.
- **`acceptance.py check-pass FILE... [--ledger F]`** validates files and the line that names each; `streak` takes `--watcher-sha` and `--max-flakes`.
- **Staged saves (B51)**: a `campaign` scenario row may carry `save_file` (path under the game repo) and `save_sha256`; the adapter's `ctl.saves {anchor: appdata|game, dir, ext}` says where `ctl scene` copies it, as `wsc_<id>`, before the autostart and removes it after.
- **A consumer's rule 79** skips `flake` lines while their count is at most `flakes_allowed` (never above 3), requires `evidence_sha256` = the sha256 of the committed file, one `dll_sha256` across the streak, unique `evidence` paths,
  and replaces the `$Version` regex by `watcher_sha` = sha256 of `core/harness/watcher.ps1` at the branch HEAD. Older lines carry no shas and stop counting. A pin past this change touches `harness/`: 20 passes on a PC whose watcher is the kit at that pin.
