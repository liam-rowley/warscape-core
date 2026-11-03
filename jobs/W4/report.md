# W4 report: discovery/core in the core

Written by the orchestrator from the build agent's hand-back: the build ran as a subagent, and the harness refuses a subagent's Write of a
report file, so the parent writes it. Same Claude-Session as the build.

## What was built
- The 31 `discovery/core` modules of napoleon-remastered (copied from its `main` at 0ead7b9, which holds J65's `ui_atlas.py` fix) are flat in
  `discovery/`, with their tools ids kept (`discovery.core.*`, plus `proxy.tools.exe_info` and `wsc.discovery`); old path to core path table:
  `discovery/README.md` "Where things moved".
- New `discovery/paths.py` (id `discovery.paths`) gives the modules the game root, the adapter folder and the two game names, from `layout.py`
  and `games.json` `target` and `reference`, never from a module's own location. Without an adapter, `ADAPTER` is a path that names the fix.
- `proxy/tools/layout.py` `discovery_adapter()` and `$WSP_DISCOVERY_ADAPTER`: it reads `[discovery] adapter` or the one `discovery/*/games.json`;
  `layout.py discovery-adapter` prints it.
- `warscape/repo.py` `DEFAULTS` has the `[discovery]` table (tested in `tests/test_discovery_verb.py`: the key is accepted, a misspelt
  `discovery.adaptr` is refused).
- `warscape/verbs/discovery.py` is a core verb (in `CORE_VERBS`, id `wsc.discovery`); it loads the discovery modules with `importlib`.
- `exe_info.py` is in `proxy/tools/`; `--def` and `--identity` with no value take `layout.py`'s defaults, and with no flag it behaves as before.
- Host tests in `discovery/tests/` on a fixture adapter of made-up games `tgt` and `ref` (`_env.py`, `null_adapter/`), wired into `wsc.toml`
  `[tests] dirs` and `[tools] exempt`; core CI runs them on Linux and Windows through `wsc gates`.
- `NoGameNames` (`tests/test_moved_tools.py`) now covers `discovery/`, with an empty `ALLOW`. Provenance links to `empire-remastered` stay, as the
  lint allows.
- Docs: `discovery/README.md`, a "Discovery (optional extras)" section in `docs/CONSUMING.md`, the README row, decision C20, backlog B54 to B56.
  The Pillow pin (`discovery/requirements.txt`) and the capstone and pefile pins (`re_env.py`) moved unchanged. `VERSION` 0.12.0.

## Evidence
- Gates, verified 2026-11-03 on commit a759704: `python3 wsc.py gates` 12 ok, 2 warn, 0 failed (the `hooks` gate: this clone's `core.hooksPath`
  is an absolute path; the `tests` gate: 332 host tests passed, 5 skipped: the pre-push hook test needs a POSIX sh and symlinks, and four `x86re`
  Walk tests need capstone).
- Rerun by the orchestrator, 2026-11-03 on a759704: `python3 -m unittest discover -s discovery/tests` OK (skipped=4); `gates --fast` 12 ok,
  1 warn, 0 failed.
- Test counts: `discovery/tests` 107 run, 4 skipped; the old napoleon files held 117 in 8 files. Moved to the consumer's thin test (they read the
  consumer's real repo): committed diff-file schema, diff README current, committed assets-registry ids, `discovery.j7_problems` on the real repo,
  stale-README copy, offline gate warning, the legacy set at `c674fb1`, three `ThisRepo` tests, `engine_api` probe_safe and table current,
  `exe_strings` committed table. Added: one row-field test in `test_discovery.py` and 4 in `tests/test_discovery_verb.py` (config, layout,
  `render`, `check`).
- Byte identity, verified 2026-11-03 on commit a759704, on a scratch copy of the consumer's committed results (its `discovery/` without `core/`,
  `registries/`, `jobs/`, `proxy/napoleon/identity.json`; only `"target"` and `"reference"` added to the copy's `games.json`, plus a `wsc.toml` and
  the captures); the consumer's checkout was only read:
  - the six generated READMEs (`diff`, `assets`, `db`, `loc`, `ui`, `gate`) are byte-identical to the committed files;
  - `_load` (6 area files), `j7_problems` and `ui_problems` report no problems;
  - `gate.run_gate` (floors, row shapes, index pin, ratchet, gate summary) reports no failures and the same findings as the committed gate
    summary (3711, 106, 10272, 23, 1, 0); `--install` was not run;
  - `engine_api.py probe-safe --check` ok (45 getters); `shader_catalog.py build --check` ok (171 shaders, 166 mapped).
- Not run here: the gate's `reg check`, `hotkeys check` and `gen_tables --check` sub-commands (the consumer's own `discovery` verb would clash),
  `engine_api.py build --check` (the run folders' raw logs are absent), the passes that read the install and the extract (their pure logic is
  covered by host tests; the consumer's follow-up is `discovery all` then an empty `git diff --stat`), and the PE masks and signature search against
  real exes since the rename (host tests cover them).

## Deviations from the brief and why
- Output field names, titles and README prose are built from `games.json` `target` and `reference` (`empire_va`, `napoleon_rva`, `empire_files`
  and so on); with the consumer's names they come out as the same bytes.
- `console_cmds.py --empire` became `--reference` (a CLI flag rename); `shader_catalog.py import` takes `--captures` or
  `games.json[<target>].captures` instead of a hard-coded PC path; `briefpaths` refuses the extract store of any game (`/?extract/<name>/`), not
  only the consumer's.
- `ui_atlas.py` still holds the target game's `UNITS`, `PIECES`, `NAMES`, `ENGINE` and art-rule tables inline (name-free but not game-agnostic;
  B54), where the brief said the `STATIC_ONLY` reasons and art rules become adapter JSON. `exe.py` still reads the reference repo's `rml_mod` and
  `perf_mod` files and a C header, and `engine_api.py` keeps its probe-safe word lists (B56). Provenance strings written into results keep the old
  `discovery/core/<tool>.py` text so that no committed byte moves (`generator` fields, the README "written by" lines, one `lua_api` evidence
  cell; B55).
- Tests that read the consumer's real registries move to the consumer's thin test file; the real asset roles are replaced by a 16-rule fixture
  (`discovery/tests/null_adapter/asset_roles.json`, copied from the consumer's rules).
- The verb imports the discovery modules with `importlib` (the stdlib-only test rejects `import assets`).
- Decision C20 (the last row on `origin/main` and `job/W2` is C19) and `VERSION` 0.12.0 (`origin/main` 0.9.0; W3 0.9.1, W2 0.10.0, W5 0.11.0).
  Backlog rows are B54 to B56: `plan/2026-11-03-napoleon-backlog` holds B50 and B51, and W2 (merged first) took B52 and B53;
  renumbered when `main` was merged in on 2026-11-03 (`review.md` still says B52 to B54, meaning these rows).
- The branch was built before `brief/W4` (PR #22) merged and starts from that branch; `main` is merged in once the brief is on it.

## Open questions
- B54: move the `ui_atlas` tables to adapter JSON now or in a follow-up job? Recommend a follow-up.
- B55: when to regenerate the provenance strings? Recommend the first PC sitting after napoleon J64, in one commit.
- The consumer's half (napoleon J64): pin bump plus `[discovery] adapter = "discovery/napoleon"` in one commit (the pinned core refuses unknown
  keys), delete its `tools/verbs/discovery.py` (a game verb named `discovery` is a load error), add `target` and `reference` to its `games.json`,
  repoint the importers to `core/discovery`, delete `discovery/core/` and the moved tests, add the thin repo test, and run the byte-identity proof
  (`before.sha256` before the switch, `sha256sum -c` and `discovery render` with a clean `git status` after).
