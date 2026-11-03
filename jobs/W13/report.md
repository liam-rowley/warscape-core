# W13 report: Game-specific gates, and the five hook names as gate modules

Games can now add checks as well as verbs. `wsc.toml` `[gates] dirs` lists folders of **gate modules** (`warscape/gatemods.py`). A gate module has `NAME`, `run(ctx) -> Result`, and optional `STAGES` and `FAST`. It runs at the stages `gates`, `jobs`, `policy` and `view`. The five hook names of C18 (`[jobs] hooks`, `warscape/hooks.py`) are removed with no shim: the loader refuses the key with a message naming the migration. The fixture game and a rehearsal on a copy of napoleon-remastered show the migration keeps every rule, message, `jobs check` line, policy result and the page's PC block. The only difference is the file path in rule 76's own message, which moves deliberately. Decision **C22** (the brief said C21; W11 took it) and VERSION **0.20.0** (W14, W17 and W8 hold 0.17.0 to 0.19.0 on their branches).

## The contract as built
- **Config.** `[gates] dirs = [...]` (default `[]`; must be a list of non-empty strings) sits beside `fast` and `skip`. Every `*.py` in a listed folder whose name does not start with `_` is loaded, in folder order, then file-name order. A missing folder is a load error. Modules are loaded by path with `sys.dont_write_bytecode` set (no `__pycache__`). `gatemods.load(ctx)` is cached per repo root and keyed on each file's mtime and size, so `jobs check` and the `jobs` gate load once, and an edited module is reloaded.
- **Module.** `NAME` must match `[a-z][a-z0-9_]*`. It may not be a core gate name (`gates.NAMES`) or another module's name. `run(ctx)` returns `warscape.gates.Result`. `STAGES` defaults to `('gates',)`; an unknown stage is a load error. `FAST` defaults to True.
  - Load errors are `ConfigError` (`wsc` exits 2) and name the file: a missing `NAME` or `run`, a bad, clashing or core `NAME`, an unknown stage, `STAGES` not a tuple, `FAST` not a bool.
  - A module defining any of `brief_problems`, `queue_problems`, `policy_problems`, `view_panel` or `summary` at top level is a load error. The message names core W13 (C22) and `docs/CONSUMING.md` "Game gates".
- **Context.** `StageCtx` passes through every attribute of the repo `Ctx`, plus `ctx.stage` and the stage's inputs. There is one `run` signature for every stage.
- **Crash and return rules.** `gatemods.call` applies the crash rule of `gates.run` (`gate crashed: <Type>: <msg>`, level error). A return that is not a `Result` with level ok, warn or error is also an error. The Result's `name` is forced to the module's `NAME`, and it is timed. An `error` Result with no details counts as one problem, `<name>: <summary>` (`gatemods.problems`).
- **`gates` stage.** Each module is its own `wsc gates` line, after the core gates, in load order.
  - `--fast` includes a game gate when its `FAST` is true or when `[gates] fast` names it. Core gates keep the old rule.
  - `[gates] fast`, `skip` and `--only` accept `gates`-stage names. The unknown-gate error lists them.
- **`jobs` stage.** `jobq.check(ctx, rows, read, folders)` returns `(errors, warnings, summaries)`. `wsc jobs check` and the `jobs` gate both use it.
  - Inputs: `ctx.rows`, `ctx.read(path)`, and `ctx.briefs()` (`jobq.briefs`: `(jid, row, text)` in id order for rows whose brief exists, skipping the legacy file's `brief_hooks` ids).
  - `error` details are problems (printed as `jobs: <d>`, exit 1). `warn` details print as `jobs: warning: <d>` and do not fail.
  - Non-empty summaries are appended to the `jobs check` line. The `jobs` gate is `warn` when only warnings exist.
- **`policy` stage.** Runs from `policy.run_check` only. `ctx.facts` is `collect_facts` plus branch, kind, jid and changed, plus `extra_facts` (renamed from `extra_hook_facts`). `error` details are policy errors, appended after the decisions check, as before. Modules are loaded before any git read, so a load error stops `policy` with exit 2.
- **`view` stage.** Runs from `render_view` with `ctx.rows`.
  - `jobq.panel_html` draws `Result.html` as is when it is non-empty; otherwise the escaped summary and details, joined by `<br>`, as a muted paragraph; an empty Result draws nothing.
  - `Result` gains `html: str = ''`, and `wsc gates --json` writes it.
- **Removed:** `warscape/hooks.py`, `jobq.call_hooks`, `S.hooks`, `DEFAULTS['jobs']['hooks']`, and the `ctx` parameter of `jobq.brief_problems` and `jobq.problems`. `brief_problems(jid, row, text)` keeps the 3-argument form napoleon's `test_discovery_gate.py` uses.
- **The old key.** `repo.REMOVED` maps `('jobs', 'hooks')` to the message `wsc.toml: [jobs] hooks was replaced by [gates] dirs in 0.20.0 (C22): move each hook into a gate module; docs/CONSUMING.md "Game gates"`. The key is checked before the generic unknown-key merge.

**Fixture game** (the second consumer):
- `tests/fixture_game/gates/rules.py` is one module with `STAGES = ('jobs', 'policy', 'view')` dispatching on `ctx.stage`, which is the shape napoleon takes. Every rule and message is the one its hook had; the module now writes the `F2: brief: ` prefix itself.
- `gates/no_todo.py` is a new `gates`-stage module: no file under `docs/` says TODO.
- `wsc.toml` sets `[gates] dirs = ["gates"]`.
- `test_fixture_game.py` changed only the module docstring, three test names and one comment that named hooks. It gained one test (`test_the_fixtures_gates_stage_module_is_a_gate_line`). Every existing assertion is unchanged.

## Tests, red then green
`tests/test_gatemods.py` was committed red (first commit: ImportError on `warscape.gatemods`). After the build all 20 pass:
- **gates stage:** own line after the core gates and fails on error; in `--fast` unless `FAST = False`; `[gates] skip` and `--only` (and the unknown-gate error lists the game gate); a crashing `run` is an error; `_` files are skipped and folder-then-name order holds.
- **load errors:** missing folder; NAME clash with a core gate and with another module; bad NAME; unknown stage; missing `run` or `NAME`; a module that still defines `summary` (the message names W13 and `docs/CONSUMING.md`); the `[jobs] hooks` key gives the migration message, not "unknown key".
- **jobs stage:** `briefs()` skips a `brief_hooks` id; an error fails `jobs check` and the `jobs` gate and its summary lands on the line (`jobs check: 2 rows, 1 problems, 1 of 2 briefs checked`); a jobs-only module is not a gates line; a warn prints without failing.
- **policy stage:** sees `kind` and `changed`, and an extra fact through `run_check(..., extra_facts=...)`; it is never run by `wsc gates`, and `--only` refuses its name.
- **view stage:** the summary is escaped; `html` is drawn raw; an empty Result draws nothing.

The whole suite: 370 host tests pass, 5 skipped (capstone). `python3 wsc.py gates` (full): 13 ok, 1 warn (the skips), 0 failed. Core CI on `c24c53e` (run 41720196478) passed every job (gates on Linux and Windows, proxy, harness-windows).

## Napoleon migration rehearsal
- **Setup.** A scratch clone of napoleon-remastered at origin/main `6cbb9e9`, with a plain clone of warscape-core at `core/`. Nothing was committed or pushed to napoleon-remastered; the scratch copy is deleted.
- **Baselines.** Napoleon's pin v0.9.0 is behind 0.15.0. At the parent core `e89b026`, napoleon's `tools/verbs/discovery.py` is a load error (the C20 verb clash), so both before and after runs delete it in the working tree. "Before" is the parent core `e89b026` with napoleon's old hook module. "After" is `job/W13` with the migration applied by a script (the steps in `docs/CONSUMING.md` "Game gates").
- **`python3 core/wsc.py jobs check`:** `jobs check: 72 rows, ok, 0 registry gaps in briefs` with v0.9.0, with the parent, and after. Identical.
- **Perturbed `jobs check`.** I added a found path and a registry gap to J72's brief and the same to legacy J1, and an unlisted `audio/core/`. Before and after both give `jobs check: 72 rows, 2 problems, 2 registry gaps in briefs`, with the same J72 found-path problem, the same order and no J1 problem. The one difference is the rule 76 message, which names `tools/gates/pipeline.py` instead of `tools/jobs_hooks.py`: the file it tells you to edit moved (deliberate).
- **`gates --only jobs`:** `72 jobs rows, queue ok` before and after.
- **`policy --branch job/J70 --base 1ad7628`:** ok (10 files) before and after.
- **`policy --branch job/J71 --base e495064`:** ok (25 files) before and after.
- **J71 plus a throwaway scratch commit touching `proxy/napoleon/adapter.cpp`:** REFUSED (27 files) before and after, with the identical rule 79 line (`0 consecutive acceptance passes on build a0b9c3ff0bfe, watcher 1.3.0`).
- **`jobs view --offline` page.** 5 diff hunks, all live data between the two runs: the generated time, the PC lock and game state (another session held the game), and the Claude usage counters. The PC block's markup, the usage table and their position are the same.
- **Napoleon's own tests** (`test_jobs_hooks`, `test_build_id`, `test_registry_merge`, `test_repo_rules`, `test_usage_reader`, `test_proxy_host`, `test_discovery_gate`): 136 ran before and after, with the same 17 failures. All come from napoleon's v0.9.0-to-0.15.0 drift (the discovery move, build-id inputs now in the core, the docker proxy build), not from W13.
- **`gates --fast`:** identical before and after (10 ok, 1 warn, 2 failed). Both failures predate W13: the `wsc.discovery` row left over, and `core_pin`. The `tools` gate accepts `tools/gates/pipeline.py` and its row.
- **The removed key works as designed:** the unmigrated napoleon on the W13 core exits 2 with the `[jobs] hooks was replaced by [gates] dirs ...` message.

## Napoleon steps (changed from the brief)
The pin-bump commit must:
1. `wsc.toml`: delete `hooks = ["tools/jobs_hooks.py"]` from `[jobs]`; add `[gates]` with `dirs = ["tools/gates"]`; fix the two comments that name the file or "brief hooks".
2. `git mv tools/jobs_hooks.py tools/gates/pipeline.py`, then in the module:
   - Rename `brief_problems` to `brief_rule`, `summary` to `gap_summary`, `queue_problems` to `queue_rule`, `policy_problems` to `policy_rule`. Delete `view_panel`.
   - Add `NAME = 'pipeline'`, `STAGES = ('jobs', 'policy', 'view')` and a `run(ctx)`. It imports `Result` **inside** `run`, because napoleon's tests load the file without `core/` on `sys.path`.
   - `jobs` stage: `f'{jid}: brief: {e}'` over `ctx.briefs()`, plus `queue_rule(ctx, ctx.rows, ctx.files())`. Summary is `gap_summary(ctx, ctx.rows, ctx.read)`; level is error when there are any problems.
   - `policy` stage: `policy_rule(ctx, ctx.facts)`.
   - `view` stage: `Result('pipeline', 'ok', 'PC state' if pc else '', html=pc_block(pc))`. The summary is empty off the PC so nothing is drawn there.
   - **Not in the brief:** `_usage_reader` must look in `Path(__file__).resolve().parents[1]` instead of `.parent`. `acceptance_active`'s default root becomes `parents[2]`. The rule 76 message names `tools/gates/pipeline.py`.
   - Update the header lines (`[gates] dirs`, `not-a-verb: a gate module, run by wsc gates`).
3. `python3 core/wsc.py reg add tools tools/gates/pipeline.py --id tools.jobs_hooks`, then `reg add tools tools/usage_reader.py discovery/core/briefpaths.py`. Both headers name the file.
4. Tests: `test_jobs_hooks.py` (module path, three source-text reads, the renamed functions). **Not in the brief:** `test_build_id.py` (the `_load` call and one source read), `test_registry_merge.py` (`TOOLS`), `test_repo_rules.py` (the `MOVED_ALLOWED` key and the loader path), `test_usage_reader.py` (add `tools/gates` to `sys.path`, `import pipeline as hk`), and `test_proxy_host.py` and `test_discovery_gate.py` (strings and comments only).
5. Docs: `CLAUDE.md`, `docs/REVIEW.md` (it also says `policy_problems`), `harness/README.md`, `docs/plans/PLAN.md`, and the `tests/test_build_id.py` docstring.
6. Then run gates, `jobs check` and `policy`.

All of this is in `docs/CONSUMING.md` "Game gates".

## Deviations from the brief, and why
- **Decision C22 and VERSION 0.20.0, not C21 and 0.18.0.** W11 took C21; W14, W17 and W8 took 0.17.0, 0.18.0 and 0.19.0 on their branches (the brief's VERSION and Setup rules). Until W11 merges, `policy` reports `new row C22 should be C21`. Whoever merges second merges main; if W11 is dropped, renumber to C21.
- **`--only` help.** It names the core gates and says the repo's game gates come from `[gates] dirs`, rather than listing them: `add_arguments` has no repo context. The unknown-gate error lists the real names.
- **`discovery/briefpaths.py`.** One header line changed (it named napoleon's `tools/jobs_hooks.py` and the `brief_problems` hook), plus its tools row. The brief listed `discovery/` as not touched. This is a comment only, needed for the acceptance grep, and it names no game (the discovery no-game-names rule).
- **Fixture layout.** One fixture module for the jobs, policy and view stages (`gates/rules.py`), plus `gates/no_todo.py` for the gates stage.
- **`jobq.problems` and `brief_problems` lost their `ctx` parameter.** Nothing passes it any more. The 3-argument `brief_problems` napoleon calls still works.
- **Small additions inside the contract:**
  - `jobs check` prints warn details as `jobs: warning: <d>`.
  - An `error` Result without details counts as one problem.
  - A non-Result return is an error.
  - `[gates] fast` may name a game gate whose `FAST` is False.
  - The `jobs` gate is `warn` when a jobs module warns.
- **Rehearsal baseline.** Napoleon's pin v0.9.0 gave the same clean `jobs check` line, but the full comparison used the parent commit `e89b026`. Napoleon at 0.15.0 also needs its `discovery` verb deleted (C20), applied identically to before and after.
- **Report and row:** the build ran as a subagent, which cannot write report files, so the orchestrator wrote this report from the builder's text and set the row to review (same Claude-Session as the build).

## Open questions
1. **B50** stays a note, reworded to a `view`-stage `cards` field on Result (Open question 3 of the brief). Not built.
2. **Policy modules run from the branch's own head**, as hooks did (brief question 5). Unchanged.
3. **Optional napoleon follow-up:** `tests/test_hotkeys.py`'s clash check (J21) could become a `gates`-stage module.
4. **W15's "find hook" (B43)** should reuse `gatemods.load` with its own stage rather than a second loader (brief question 6). A new stage means editing `gatemods.STAGES` and its docstring, which is a contract change for whoever builds it.
5. **Napoleon's pin-bump job** has more to do than the brief's step list: the C20 discovery verb deletion, the 0.9.0-to-0.20.0 drift behind the 17 failing tests, and this migration. It is likely its own sized job, not a two-line bump.
