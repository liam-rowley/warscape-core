# W8: Harness host tests in the core and its own Git Bash finder

Model: Sonnet, reason: none needed (Sonnet is the default). Porting Python host tests from a consumer onto the null game, plus one small library
module; no DLL change, no reverse engineering, no PC. Budget about 130 tool calls (about 1,600 lines of tests to read, adapt and run on two
platforms); at the cap, stop, commit what is green, and list in the report what is left.

## What
Backlog B17 and B18 (`docs/BACKLOG.md`; both from napoleon J12). The harness and save tools moved here in 0.4.0 (C14), but their Python host tests
stayed in the first consumer, so a core change to `pc_deploy.py`, `ctl.py`, `acceptance.py`, the ESF tools or `job.sh` is tested only when a game bumps
its pin. `tests/test_moved_tools.py` covers layout, the build id and the lock only. And `harness/ctl.py` `bash()` reaches into the game repo
(`ROOT/tools/verbs/setup.py` `git_bash()`) to find Git Bash: a core tool depending on a game's verb. W9 and W10 depend on this job ("host tests
first"), so it goes before them.

Source of the tests: `napoleon-remastered` `main` (read at `562dde6` when this brief was written; record the sha you copy from in the report).
Napoleon pins core v0.9.0, so its tests target 0.9.0's tools; since then only `proxy/tools/pc_deploy.py` changed (+19 lines). A ported test that
fails on `main` is either drift in the test or a regression in the tool: say which in the report, and fix a regression only if it is one line,
otherwise record it as a backlog line.

1. **The Git Bash finder (B18), `warscape/gitbash.py`** (a library module: `wsc.toml` `[tools] library` already covers `warscape/*.py`, so no tool
   row). Port `bash_kind`, `git_bash` and `bash_for_tests` from napoleon `tools/verbs/setup.py` (lines 30 to 75 at `562dde6`) with their injectable
   parameters (`nt`, `which`, `git_exec_path`, `isfile`, `find`), standard library only. Drop the `%LOCALAPPDATA%/Git` probe (napoleon J41 review,
   later item 4: not an install folder; `%LOCALAPPDATA%/Programs/Git` stays). The skip reason of `bash_for_tests` must not name a game command
   (today it says `python3 core/wsc.py setup`): say "no Git Bash found (looked in: ...); the WSL bash on PATH is never used".
2. **`harness/ctl.py` uses it.** `bash()` imports `warscape.gitbash` through the core root it already computes (`_OWN`), not the game's verb; keep the
   fallback to plain `bash` when nothing is found (the call then fails as before) and the module-level cache. `harness/acceptance.py` reaches bash
   only through `ctlmod.bash()` and needs no change. Fix the `bash()` docstring (it names `tools/verbs/setup.py`). `tests/test_moved_tools.py`
   drops its own `git_bash()` (lines 121 to 129) for `warscape.gitbash.bash_for_tests()`.
3. **Host tests for the finder**, `tests/test_gitbash.py`: napoleon `tests/test_setup.py` `test_bash_kind` and `tests/test_proxy_host.py` lines 240 to
   255 (PATH bash, WSL launcher skipped, `git --exec-path` route, nothing found), plus `ctl.bash()` no longer opening any file under the game root
   (assert with a game root that has no `tools/`).
4. **The ported host tests (B17)**, one file per tool under `tests/`, against the null game (`proxy/tests/null_game`: its `proxy/null/identity.json`
   and `harness/null/adapter.json`) or temp folders, never a real game:
   - `tests/test_pc_deploy.py` from napoleon `tests/test_pc_deploy.py` (33 tests): the fake game folder takes its exe name, config file and mod folder
     from the null identity (`Game.exe`, `nullgame.ini`, `nullgame`), and the fake `tasklist` output names that exe.
   - `tests/test_ctl.py` from napoleon `tests/test_ctl.py` (52 tests), except what reads the game's own data: `Rule78` scans napoleon's
     `registries/scenarios.jsonl`, its `proxy/napoleon/lua/battles/*.txt` and the acceptance script; keep its rule as a test over the null game's (or a
     temp) rows and battles folder, and leave the scan of real rows to the game. Scenario ids, map names and the adapter dict become neutral ones.
   - `tests/test_acceptance.py` from napoleon `tests/test_acceptance.py` (19 tests; generic already, only the paths change).
   - `tests/test_saves.py` from napoleon `tests/test_saves.py` classes `Codec`, `Diff` and the synthetic `Tree` builder (the core's `saves/esf_*.py`);
     `NapoleonMap`, `Recipes`, `Staging` and the noise-file case test the game's `saves/<game>/` and stay there.
   - `tests/test_job_sh.py` from napoleon `tests/test_job_sh.py` (15 tests), with `warscape.gitbash.bash_for_tests()` for the bash.
   Every ported file names no game (the `NoGameNames` pattern in `tests/test_moved_tools.py`): add the five files, and `tests/test_gitbash.py`, to
   the files that test scans. Provenance goes in each file's docstring as "ported from the first consumer's `tests/<file>` at `<sha>`".
5. **CI.** The `gates` job on `windows-latest` runs these through the `tests` gate, where `python3` is not on PATH, so the `job.sh` cases skip there (a
   `warn`, as `GameLock` does today). Add `tests.test_job_sh` (and `tests.test_gitbash`) to the `harness-windows` step "moved tools host tests that
   run bash" in `ci/gates.yml.in`, then `python3 wsc.py ci render` and commit the template and `.github/workflows/gates.yml` together (`ci_render`
   gate). Keep the full `tests` gate inside `[tests] timeout_s` (600 s); note the new run time in the report.
6. **Docs and release.** `docs/CONSUMING.md` "The proxy, the harness and the save tools": one sentence that a game's setup verb imports
   `warscape.gitbash` (`from warscape.gitbash import git_bash, bash_kind, bash_for_tests`; verbs run with the core on `sys.path`) instead of keeping
   its own; the `tests/test_moved_tools.py` docstring stops saying the fuller tests run only in the game repo. Remove B17 and B18 from
   `docs/BACKLOG.md`. `VERSION`: the next free minor (a new library module games import; `main` holds 0.15.0 when this was written).

Files this job touches: `warscape/gitbash.py` (new), `harness/ctl.py`, `tests/test_gitbash.py`, `tests/test_pc_deploy.py`, `tests/test_ctl.py`,
`tests/test_acceptance.py`, `tests/test_saves.py`, `tests/test_job_sh.py` (all new), `tests/test_moved_tools.py`, `ci/gates.yml.in`,
`.github/workflows/gates.yml`, `docs/CONSUMING.md`, `docs/BACKLOG.md`, `VERSION`. No tool under `harness/`, `proxy/` or `saves/` changes behaviour
except `ctl.bash()`; `proxy/src` and `proxy/tools/build.sh` are DLL inputs and are not touched. Branch `job/W8`.

## Acceptance
- `python3 wsc.py gates` green on this PC (Windows) and in CI on both `ubuntu-latest` and `windows-latest`; `harness-windows` runs `tests.test_job_sh`
  with a real Git Bash and no skip.
- The report lists every napoleon test ported, adapted or left in the game (with the reason), and the count: tests before and after in the core.
- Failing fixture: break one thing in each tool on a scratch commit (for example make `pc_deploy.py` uninstall leave one byte, make `job.sh`
  exit 0 on refusal) and show the matching ported test going red, then revert. One line each in the report; the scratch commits are not pushed.

## The consumer's part (not here)
Nothing breaks at the pin bump: `ctl.py` stops loading `tools/verbs/setup.py`, and the game's verb keeps working. A later napoleon job may make
`setup.py` import `warscape.gitbash`, point its bare-bash lint (`tests/test_repo_rules.py`) at it, and drop the tests now ported here, keeping the
ones over its own data (`Rule78` over its scenario rows and battles, `NapoleonMap`, `Recipes`, `Staging`, the real identity). Propose that as a
napoleon `needs_brief` row in the report's open questions; do not touch napoleon here.

## Open questions (recommendation for each)
1. **Where the finder lives.** Recommended: `warscape/gitbash.py`, a library module, because a game's verbs import `warscape` with no path tricks
   and library modules need no tool row. The alternative, `harness/gitbash.py` beside `campose.py` (ctl.py already has `harness/` on `sys.path`),
   needs a tool header and row and a by-path import from a game verb. Take the recommendation unless importing `warscape` from `ctl.py` fails in a
   context where `ctl.py` runs without the core root (it never does today: it is not in the watcher kit).
2. **Tests that exercise the game's data** (Rule78's scan of real rows, the save map, recipes, staging): recommended to leave them in the game, as
   above; the core tests the rule on fixture data.
3. **File overlap with W11 and W12** (the three are likely built one after another; base on the latest `main`, merge `main` in, never rebase):
   - W12 edits the header comments of `harness/ctl.py` (lines 7 and 20) and `harness/acceptance.py` (line 7) and adds a stale-path lint class to
     `tests/test_moved_tools.py`; this job edits `ctl.py` `bash()` and `test_moved_tools.py` lines 121 to 129 and the `NoGameNames` file list. Small,
     separate hunks; whoever merges second resolves them by hand.
   - All three edit `VERSION`, `docs/BACKLOG.md` and `docs/CONSUMING.md`; W11 and W12 also `README.md`. W10 (depends on this job) edits
     `harness/job.sh` and will extend `tests/test_job_sh.py`.

## Kill criteria
- A ported test cannot be made name-free or game-free without losing what it checks: leave it in the game, say which and why in the report; do not
  add a `NoGameNames` allow entry for a test file.
- A ported test shows a real regression in a tool that is more than a one-line fix: mark it `skip` with the reason and the new backlog line, do not
  fix the tool here (W9 and W10 own those tools' next changes).
- `job.sh` tests flaky on Windows CI (a pass and a fail on the same commit) after two attempts at the cause: keep them in `harness-windows` only,
  skipped in the `gates` job, and report.
- The full `tests` gate goes over 600 s on CI: stop adding cases, report the timings.
- CI red after three fix attempts for a cause in this change: stop and report.
- Version collision: W11 and W12 also bump `VERSION`. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit; the
  second to merge takes the next free number and merges `main`. Say in the report which number you took.

## Finish
Report in `jobs/W8/report.md` (the test list with provenance and counts, the failing fixtures, CI timings, deviations, open questions), then
`wsc reg set jobs W8 status=review report=jobs/W8/report.md` (`python3 wsc.py`). Liam tags the core after the merge; stop after the PR.
