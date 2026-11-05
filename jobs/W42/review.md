# W42 review

## Round 1 (2026-11-05, branch job/W42 at 85ede27)

**Verdict: merge.**

W42 does what the brief asked. Windows gates now skip paperwork, both gates jobs have a 20-minute limit, and the fetch cache keys on what the fetchers read. No blocker and no should-fix; two later items go to `docs/BACKLOG.md` through a `plan/` pull request.

### Machines
- `python3 wsc.py gates`, session bd308022, this PC, at 85ede27: 15 ok, 1 warn, 0 failed; 1147 host tests passed, 5 skipped (the POSIX hook test and four capstone tests).
- `python3 wsc.py policy --branch job/W42 --base origin/main` before this round: refused only for the missing review and the row not yet `done`, as expected. It notes that the branch changes `warscape/ci_settings.py` and `wsc.toml`, so those rules are proven by host tests, not by this run (C24).
- `python3 wsc.py ci check-settings`: 0 problems, 1 note (`release` is not a required check). No ruleset change was needed.
- CI on the head, run 42122066737: `gates (ubuntu-latest)` success; `gates (windows-latest)`, `proxy` and `harness-windows` skipped on pass markers. `policy` is skipped on a draft. The pull request reads `CLEAN`.

### Claims against evidence
- **Probe:** run 42118898100, `probe/W42-skip` at cfbd2de. The job list matches the report: `gates (windows-latest)` skipped under its exact name, `probe-matrix` skipped under its bare id with no per-value check. The branch is gone.
- **Windows ran on code:** run 42120432266 at 095da04, success, `gates (windows-latest)` 22:19:10 to 22:29:04.
- **Skipped required checks merge:** pull request #126 merged with `proxy` and `harness-windows` `SKIPPED`.
- **Red first:** commit 310fbb8 re-run here gives 74 tests, 6 failures and 2 errors, the number the report states.
- **B99 repro:** rerun on napoleon's `viewer/pins.json` from its working copy, with and without `playwright`: both keys `9f11b25d...e213cd`, the report's value.
- **Workflow files:** the brief on the base names `ci/gates.yml.in` and `.github/workflows/gates.yml`, so the W36 rule has nothing to clear.

Two items the report lists as not proved now have evidence:
- **The pass marker skipping Windows, on a branch:** run 42122066737 restored `ci-pass-1-gates_windows-f3e12831...` and skipped the job, with `gates_windows=true` from the diff. The tree hash ignored the two paperwork commits, and the pull request stayed `CLEAN` with the check skipped. The same skip on `main` is still to come.
- **The cache miss:** proxy job of run 42120432266: `Cache not found` for `fetch-1-9f11b25d...`, then `Cache saved` under that key. `netfetch 2` was a one-time miss, as predicted.

### The brief
All six decisions are followed and every changed file is in scope. Decision 5's "absent, never dropped" holds: a missing field is left out of its entry and a missing key is `null`, and `test_ci_cache_moves_on_what_a_fetcher_reads` shows each moves the key. `fetch_ui.py` reads `repo`, `commit`, `url` and `sha256`, plus `version` only to print it, and nothing else reads the pin file for a download.

Three deviations are named in the report and acceptable. One is not listed under Deviations: the probe used a two-value matrix where the brief said one-value. The report's probe section says so, and it does not change the result.

### Risk-first reading
I picked what stalls or weakens every merge: the `if:` and marker of `gates-windows`, the consumers of the check names, and the `gates_windows` regex.
- **Fail-safe:** `block_if` is unchanged and gives `!cancelled() && ... (needs.changes.result != 'success' || ...gates_windows == 'true')`. `classify(None)` runs everything. `changes` failing runs Windows.
- **Check names:** `ci.required_jobs`, `release.green_problems` and `ci_settings.produced` all match on the name, and `GREEN` and `green_problems` accept `skipped`. Nothing has `needs: gates` other than `notify` and `main_health`, and both now wait for `gates-windows`.
- **The marker:** `enableCrossOsArchive` is on for both sides, so a Windows save restores on ubuntu (proved by the head run).
- **`netfetch.py`:** `import fetch_ui` is circular with `fetch_ui`'s `import netfetch`, but inside a function, so it is safe; the real CLI prints a clean `$GITHUB_OUTPUT` text and the proxy job ran it.

### Findings
No blockers. No should-fix.

**Later 1: a rename into paperwork reads as paperwork.** `warscape/ci.py:64` `changed_files` runs `git diff --name-only` without `--no-renames`, so a rename lists only its new path. To see it: `git mv warscape/ci_render.py docs/zz_moved.md`, then `git diff --name-only --cached` prints only `docs/zz_moved.md`; with `--no-renames` it prints both. A branch whose only code change is such a move skips `gates (windows-latest)`. This is a later item and not a should-fix because ubuntu still runs every gate on it, and the merge changes the tree, so `main` runs Windows (decision 4's backstop). `proxy` and `harness` have the same gap today. `policy` already passes the flag for this reason (`warscape/policy.py:287`). The fix is that flag and a test on a real repository.

**Later 2: a release pays for Windows twice more.** `VERSION` is outside the paperwork set (`test_gates_windows_skips_paperwork_only` lists it as code), so each `release/vX.Y.Z` branch runs Windows and so does its merge: run times on `release/v0.41.0` and `release/v0.39.0` were about 8 and 6 minutes. `VERSION` is one line of text that both systems read the same way, and ubuntu's `core_pin` checks it. Adding `VERSION` to the set's exclusions would remove both runs. It is outside this brief, and it serves the same goal.

### Note, not a finding of this job
Release run 42122113762 on `a18c586` failed with `gates (windows-latest): in_progress`. The check was from the run on `job/W43`, a claim branch created at `main`'s tip, so the same commit carried two runs. W42 should remove most of this: a claim branch has an empty diff, so it now skips Windows.
