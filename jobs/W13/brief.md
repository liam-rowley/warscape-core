# W13: Game-specific gates, and the five hook names as gate modules

Model: Opus, reason: a new extension point every game builds on (B1), plus a migration of the job pipeline's live hooks (C18) that napoleon's
`jobs check`, `policy` and status page run on every push; a wrong contract here is paid for by every game and every later job. Budget about 140 tool
calls (about 90 for the core change and its tests, 25 for the napoleon migration rehearsal, the rest for docs, gates and the report). At the cap,
stop, commit, and report what is left.

## Goal
Games can add verbs (`[cli] verb_dirs`) but not checks. Today their only extension point is the hook module of C18 (`warscape/hooks.py`), capped at five
fixed names with five different signatures, each wired into one call site. This job builds general **game gate modules** (B1) and moves the five hook
names onto them (B46), so a game has one extension contract: a module with `NAME` and `run(ctx) -> Result`, the same shape as a verb. Backlog lines:
`docs/BACKLOG.md` B1, B46 (both removed when this merges) and B50 (stays a note, reworded: see Open questions).

## Decisions already made (follow them; a deviation goes in the report with its reason)
1. **Config:** `wsc.toml` `[gates] dirs = [...]` (repo-relative folders, default `[]`), beside the existing `fast` and `skip`. Every `*.py` in a listed folder
   whose name does not start with `_` is a gate module, loaded in folder order then file-name order (the same rule as `cli._load_verbs`). A listed folder that
   does not exist is a load error.
2. **The module contract** (one docstring owns it: the new loader module's):
   - `NAME` (str): the gate's name. Refused when it equals a core gate name (`warscape/gates.py` `NAMES`), another module's `NAME`, or is not `[a-z][a-z0-9_]*`.
   - `run(ctx) -> Result`: `Result` is `warscape.gates.Result` (`name`, `level` ok|warn|error, `summary`, `details`). A module imports it with
     `from warscape.gates import Result` (the module runs inside the `wsc` process, as hook modules and verbs do).
   - `STAGES` (optional tuple, default `('gates',)`): where the core runs it, any of `gates`, `jobs`, `policy`, `view`. An unknown stage is a load error (a typo
     must never switch a rule off silently, the same rule `hooks.load` has today).
   - `FAST` (optional bool, default `True`): a `gates`-stage module in the `--fast` set. `[gates] fast`, `[gates] skip` and `--only` accept game gate names;
     the unknown-name check in `gates.selected` covers them.
   - A module that defines none of the old hook names and lacks `NAME` or `run` is a load error naming the missing attribute. A module that still defines one of
     the five old names (`brief_problems`, `queue_problems`, `policy_problems`, `view_panel`, `summary`) at top level is a load error that names this job and the
     migration section of `docs/CONSUMING.md` (so a half-migrated module fails loudly, not silently).
3. **Stages** (the core passes `run` a context wrapper: every attribute of the repo `Ctx`, plus `ctx.stage` and the stage's inputs; never a second signature):
   - `gates`: run by `wsc gates` as its own line, after the core gates, in the order loaded. Crash = `error` (the existing `gates.run` rule).
   - `jobs`: run by the core's `jobs` gate and by `wsc jobs check`. Inputs: `ctx.rows` (the main rows, `jobq.main_rows`), `ctx.read(path)` (text or None) and
     `ctx.briefs()`, which yields `(jid, row, text)` for every row whose brief exists, **skipping ids in the legacy file's `brief_hooks` list** (the exemption the
     brief hooks have today; the JSON key keeps its name so napoleon's `jobs/legacy.json` needs no edit). An `error` Result's details are queue problems (printed as
     `jobs: <detail>`, counted, exit 1); a `warn` Result's details print but do not fail; a non-empty `summary` is appended to the `jobs check` last line (`, <summary>`),
     which is what the `summary` hook does now. This one stage replaces `brief_problems`, `queue_problems` and `summary`.
   - `policy`: run by `wsc policy` (and CI's `policy` job) only, never by `wsc gates`. Input: `ctx.facts`, the dict `policy_problems` gets today (`collect_facts` plus
     `kind`, `jid`, `changed` and any extra facts a caller passes: keep `run_check`'s extra-facts parameter working, rename it `extra_facts` if you like). An `error`
     Result's details are policy errors, appended after the decisions check, as now.
   - `view`: run by `wsc jobs view` (and `--serve` snapshots). Input: `ctx.rows`. The Result is drawn at the top of the page where `view_panel` is drawn now: the
     escaped `summary` and `details` as a muted paragraph, **or**, when the Result carries a non-empty `html` string, that HTML as is. `Result` gains one optional
     field, `html: str = ''`, read by the view only (`wsc gates --json` writes it like the other fields). This keeps napoleon's PC and usage block byte for byte
     (see Open questions 2).
4. **`[jobs] hooks` goes away in this release, with no shim.** The key is removed from `warscape/repo.py` `DEFAULTS`; a `wsc.toml` that still sets it fails to load
   with a message written for it (not the generic "unknown key"): `[jobs] hooks was replaced by [gates] dirs in <version> (C21): move each hook into a gate module;
   docs/CONSUMING.md "Game gates"`. `warscape/hooks.py` is deleted; its loader logic (load by path, `sys.dont_write_bytecode` around `exec_module` so no
   `__pycache__` lands in the checked repo) moves into the new loader. Reason: one consumer, migrated in its pin-bump commit as napoleon did for the `discovery`
   verb clash (C20); a shim would be a second code path the next job has to remove.
5. **Name of the loader module:** `warscape/gatemods.py` (library code, no tool row, covered by `[tools] library = ["warscape/*.py"]`). It exports `load(ctx)`
   (cached per `ctx.root`, so `jobs check` and the `jobs` gate do not load twice in one process) and `run_stage(ctx, stage, **inputs) -> [Result]`, which wraps each
   call in the same crash rule as `gates.run`.
6. **Gate modules in a game are tools like any script:** a header with `not-a-verb: a gate module, run by wsc gates` and a row in the game's `tools` registry. No
   special case in `warscape/tools.py` (napoleon's `tools/jobs_hooks.py` already has such a header).
7. **Decision line:** append `C21` to `docs/DECISIONS.md` as `proposed (Claude, core W13)`: game gate modules (`[gates] dirs`, `NAME`, `run(ctx) -> Result`,
   `STAGES`) replace the five-name hook module of C18; C18 otherwise stands. Reversible: yes.

## Scope: files this job touches
- New: `warscape/gatemods.py`; `tests/test_gatemods.py`; `tests/fixture_game/gates/*.py` (replacing `tests/fixture_game/hooks/rules.py`).
- Changed: `warscape/gates.py` (game gates in `selected` and `run`; `gate_jobs` runs the `jobs` stage; `Result.html`), `warscape/jobq.py` (drop `hooks`,
  `call_hooks`, `S.hooks`; `brief_problems(..., ctx)` no longer calls hooks; `render_view` draws `view`-stage Results; a `briefs()` helper that applies
  `S.legacy_briefs`), `warscape/policy.py` (`run_check` runs the `policy` stage; docstring line 14), `warscape/repo.py` (`[gates] dirs`, drop `[jobs] hooks`, the
  migration message), `warscape/verbs/jobs.py` (`check` runs the `jobs` stage instead of `queue_problems` and `summary`), `warscape/verbs/gates.py` (`--only` help
  lists game gates), `tests/fixture_game/wsc.toml`, `tests/test_fixture_game.py`, `tests/test_jobs.py` and `tests/test_policy.py` where they touch hooks.
- Deleted: `warscape/hooks.py`, `tests/fixture_game/hooks/rules.py`.
- Docs: `docs/CONSUMING.md` (a "Game gates" section replacing the "Hook points" bullet and the `hooks = [...]` line of the `[jobs]` example, with the napoleon
  migration steps below), `README.md` ("Gates": one sentence on game gates; "Use it" if needed), `docs/DECISIONS.md` (C21), `docs/BACKLOG.md` (remove B1 and B46;
  reword B50 per Open questions 3; in B9 and B14, say B1 is built), `VERSION`.
- Not touched: `proxy/`, `harness/`, `discovery/`, `saves/` (so no consumer acceptance passes are needed for this change on its own).

## Steps
1. Read `warscape/hooks.py`, every call site (`grep -n "call_hooks\|hooks.load\|policy_problems\|view_panel" warscape`), `tests/fixture_game/` and
   `tests/test_fixture_game.py`, napoleon's `tools/jobs_hooks.py` and `tests/test_jobs_hooks.py` (read-only, `C:\Users\liamr\repos\napoleon-remastered` or a fresh clone).
2. **Failing tests first**, committed red: `tests/test_gatemods.py` with a throwaway repo (`tests/_util.py` has the helper the CLI tests use) for: a `gates`-stage module
   shows as its own line in `wsc gates`, fails the run on `error`, is in `--fast` unless `FAST = False`, obeys `[gates] skip` and `--only`; a crashing `run` is
   `error`; load errors for a missing folder, a `NAME` clash with a core gate and with another module, a bad `NAME`, an unknown stage, a missing `run`, and a module
   that still defines an old hook name; the `[jobs] hooks` key gives the migration message; `ctx.briefs()` skips a `brief_hooks` id; a `jobs` module's error fails
   `jobs check` and the `jobs` gate and its summary lands on the `jobs check` line; a `policy` module sees `facts['kind']` and `facts['changed']` and an extra fact
   passed by the caller, and is not run by `wsc gates`; a `view` module's summary is escaped and its `html` is drawn raw.
3. Build `warscape/gatemods.py`, then wire the four stages (decisions 3 to 5). Delete `warscape/hooks.py`.
4. **The fixture game is the second consumer:** replace `tests/fixture_game/hooks/rules.py` by gate modules that keep every existing fixture rule and message (one
   module per stage, or one module with `STAGES = ('jobs', 'policy', 'view')`: your choice, say which), set `[gates] dirs = ["gates"]` in its `wsc.toml`, add one
   `gates`-stage fixture module, and keep `tests/test_fixture_game.py` green with the same assertions on output (change only what names the old hooks).
5. **Napoleon migration rehearsal** (evidence, nothing committed or pushed to napoleon; about 25 calls): copy napoleon-remastered's working tree to a scratch folder
   outside both repos, put this branch's core at `core/`, apply the migration below to the copy, and compare before (napoleon's pinned core) and after for:
   `python3 core/wsc.py jobs check` (problems and the last line), `python3 core/wsc.py policy --branch <a recent merged job branch> --base <its merge base>` (or the
   napoleon `tests/test_jobs_hooks.py` cases that call `policy_problems`, run against the migrated module), and the `jobs view` page's panel HTML. Record the
   commands and a diff summary in the report. If napoleon's pin is so far behind that other core changes make the "before" incomparable, compare against this
   branch's parent commit with napoleon's old hook module instead, and say so.
6. Docs, `C21`, the backlog edits, `VERSION`; then `python3 wsc.py gates` (full) and `python3 wsc.py policy --branch job/W13 --base origin/main`.

## Tests and acceptance
- `tests/test_gatemods.py` (above) and the fixture game's suite green; every existing test green; `wsc gates` full green on Linux and Windows CI.
- No line of the core still names `hooks.py`, `call_hooks` or `[jobs] hooks` except the migration message, its test, C18 (history) and dated records
  (`grep -rn "call_hooks\|hooks\.py\|\[jobs\] hooks" --include=*.py --include=*.md .`).
- The rehearsal (step 5) shows napoleon's `jobs check` problems and line, its policy result and its panel HTML unchanged by the migration.

## VERSION
A minor bump: a new `wsc.toml` key and a removed one (consumer-visible, pre-1.0). Take the next free minor at merge time: `origin/main` says 0.15.0 when this
brief was written and other W rows (W7 to W21) may claim minors first. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit; the
second to merge takes the next free number and merges `main` (never rebase). Say in the report which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered; also goes into `docs/CONSUMING.md`)
In the **pin-bump commit** itself (B9: the `core` gitlink and `[core] version` together), because the new core refuses the old key:
1. `wsc.toml`: delete `hooks = ["tools/jobs_hooks.py"]` from `[jobs]`; add `[gates]` with `dirs = ["tools/gates"]`.
2. `git mv tools/jobs_hooks.py tools/gates/pipeline.py` (a folder of its own: `[gates] dirs` loads every `*.py` in it, and `tools/` holds other tools).
   Add `NAME = 'pipeline'`, `STAGES = ('jobs', 'policy', 'view')` and `run(ctx)` dispatching on `ctx.stage`:
   - `jobs`: `found path` problems from `ctx.briefs()` with the same messages as now (the core used to prefix `<jid>: brief: `; the module now writes that prefix
     itself), plus `promotion_problems(ctx.rows, ...)` from `ctx.files()`; `summary` = `'<n> registry gaps in briefs'`; level `error` when any problem.
   - `policy`: `acceptance_problems` from `ctx.facts` exactly as `policy_problems` does now (the `facts['acceptance']` override stays).
   - `view`: `Result('pipeline', 'ok', <one-line text>, html=pc_block(pc_state(ctx.root)))`.
   Rename the five old top-level functions (or make them private): the core refuses a module that still defines them.
3. `python3 core/wsc.py reg add tools tools/gates/pipeline.py --id <the old row's id>` so the tools row keeps its id; update the header's `usage:`/`when:` lines.
4. `tests/test_jobs_hooks.py`: the module path (`ROOT / 'tools' / 'gates' / 'pipeline.py'`), the two tests that read the module's source text by path, and
   `test_check_wires_it_into_job_branches` (call `run` with a `policy`-stage context, or keep testing the helper it wraps).
5. Living docs that name `tools/jobs_hooks.py` or "hook module": `CLAUDE.md` (Jobs), `docs/REVIEW.md`, `harness/README.md`, the header of
   `discovery/core/briefpaths.py` (or its moved copy), `docs/plans/PLAN.md`. Dated job reports stay as they are.
6. Run `python3 core/wsc.py gates`, `jobs check` and `policy --branch <the pin-bump branch>`; the `jobs check` line and the status page's PC block must read as
   before. Napoleon's pin is v0.9.0 today: if it bumps to an earlier tag first, none of this applies until it crosses this one.
Optional, later: napoleon's `tests/test_hotkeys.py` clash check (J21: "this test is the gate until the core grows them") can become a `gates`-stage module.

## Kill criteria
- A napoleon rule cannot be expressed through the four stages without a fifth stage or a second `run` signature: stop and report which rule and what it needs;
  do not add a stage on your own.
- The rehearsal shows a napoleon behaviour change (a problem appears or disappears, a message changes, the panel differs) that is not a deliberate prefix move:
  fix it within about 20 calls, else stop and report the diff.
- The fixture game's existing assertions have to change beyond the names of the old hooks to stay green: stop and report (the contract would be leaking).
- Core CI red after three fix attempts for a cause in this change: stop and report.
- Version collision handled as in VERSION above; never rebase a pushed branch.

## Open questions (with recommendations; the brief follows the recommendation unless Liam says otherwise)
1. **No shim for `[jobs] hooks`?** Recommended: none (decision 4). One consumer, migrated in its pin-bump commit; a deprecation path would keep `hooks.py` alive for
   a release and need its own removal job. Alternative: load `[jobs] hooks` with a warning for one minor.
2. **`Result.html` for the view stage?** Recommended: yes. Without it napoleon's PC block and J49's usage table become escaped text, a visible regression of
   delivered work. The page is local and the module is the repo's own code, as the hook was. Alternative: text only, and B50 brings the usage back per card.
3. **B50 `card_extra` (a sixth hook name) in this design** (open, not built here): it fits as a `view`-stage feature, not a name: a `view` module's Result may carry
   `cards: dict[job id -> str]` (escaped text, or HTML by the same rule as `html`), drawn on each card by `render_view`'s `card()`. Recommended: W13 rewords B50 to
   that design and leaves it a backlog note; a later row builds it (small: one Result field, one line in `card()`, one fixture case) once napoleon wants per-card
   usage (J49's open question). Not built here because it is a new feature, not a migration, and the cap on hook names it was blocked by is gone with this job.
4. **Should `queue_problems`-style rules be plain `gates` modules instead of the `jobs` stage?** Recommended: `jobs`, so `jobs check` (which napoleon's `tests` gate
   runs) keeps reporting them; a module may list both stages if a repo wants a separate gates line.
5. **Policy modules run from the branch's own head**, as hook modules do today, so a branch can edit the rule that judges it. Not changed here (napoleon's rule 79
   reads its inputs from the base for this reason). Recommended: leave it; if wanted, a later row loads `policy`-stage modules from the merge base.
6. **File overlap with the other core rows (W7 to W21)**, for whoever merges second (merge `main`, never rebase):
   - **W12** (guards: `wsc jobs check` refuses committed views beside a jobs registry; a `policy` hint; a run-README gate; a commit-msg hook): `warscape/jobq.py`,
     `warscape/policy.py`, `warscape/gates.py`, `warscape/repo.py`, `warscape/verbs/jobs.py`, `tests/test_jobs.py`, `tests/test_policy.py`. The heaviest overlap.
     Recommended: build W13 first if both are queued; W12's new core gate is a core gate either way, but its B13 run-README gate could be a game gate if a game wants it.
   - **W11** (`core_pin`): `warscape/gates.py` (`gate_core_pin`) and `tests/test_cli.py`. Small, separate functions.
   - **W14** (schema `x-extends`): `warscape/gates.py` `gate_schemas` and `README.md`. Small.
   - **W15** (registry verbs; `last_used` stamping from the job queue; a `wsc find` hand-off to a game's exe index): `warscape/jobq.py` and maybe `warscape/repo.py`.
     B43's "find hook" is another per-game extension: recommended that W15 does not invent a second loader but reuses `gatemods.load` with its own stage, or a
     `[find]` key naming a command, and says which.
   - **W21** (CI economies, `ci check-settings`): `warscape/repo.py` `[ci]` only. Others (W7 to W10, W16 to W20): no shared files.
   - All rows: `docs/BACKLOG.md`, `docs/DECISIONS.md` (append-only, next free `C<n>`) and `VERSION`.

## Finish
Report in `jobs/W13/report.md` (the contract as built, the test list red then green, the rehearsal's commands and diffs, the version taken, deviations, open
questions, and the napoleon steps if they changed), then `wsc reg set jobs W13 status=review report=jobs/W13/report.md` (`python3 wsc.py`). Push `job/W13`,
open the draft pull request, and stop: an independent reviewer merges (C18); Liam tags.
