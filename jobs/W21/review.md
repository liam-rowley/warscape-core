## Round 1 (2026-11-03, branch job/W21 at d199eb6)

**Verdict: merge.**

Reviewed cold against `jobs/W21/brief.md`. Gates and policy run locally in a worktree; the report's claims checked against the diff.

### What I ran
- `wsc gates` on the branch merged with current main: 13 ok, 1 failed. The one failure is `test_moved_tools.GameLock.test_failing_fixture_of_racing_takers_exactly_one_wins` (a 60 s timeout of racing `harness/job.sh lock` processes under Git for Windows bash). It fails alone too. The branch does not touch `harness/` or that test, and the report's Linux CI run 41724750581 was green, so I treat it as this reviewer's Windows machine and not a finding (see Later).
- `wsc policy` refused only for the missing review and row before this review; it is checked again after the row is set.
- No DLL input changed: `git diff --name-only origin/main...HEAD` lists none of `fetch_lua.py`, `fetch_ui.py`, `build.sh`, `build_id.py` (decision 4, kill criterion respected).

### Claims against evidence
- B45: `ci/gates.yml.in` has push-only, `changes`, `needs: changes` + `if` + pass markers on both slow jobs, `gates` unconditional, notify needs updated; matches decisions 1-2. `[ci.inputs]` equals the brief's. Rendered workflow committed with the template (`ci_render` gate green).
- Existing blocks byte for byte: golden render hashes in `tests/test_ci.py` taken on main, passing. Satisfies decision 3.
- B45b: `netfetch.py` read in full. `retry` classes, never retrying `SystemExit` or non-transient `HTTPError`, cache holds raw downloads only, cache step `continue-on-error`. The extra `clean_checkouts` step is a named, sensible deviation (a half-fetched `fetch_ui` checkout would never recover) and keeps the sha checks as the judge.
- B47: `ci_settings.py` read in full: only GETs through the injectable runner, 404/403 handling, exit codes 0/1/2 as decided; findings match decision 9.
- Run ids for the push, skip and cache-hit cases are given with commit shas in the report; the skip case (41723537398) and final green run (41724750581) are the strongest evidence. I did not re-open them.

### Merge with main
The branch did not contain main's W11 and W17 commits and `VERSION` conflicted (0.18.0 vs 0.22.0). I merged `origin/main` into the branch (no rebase), kept 0.22.0, and committed it. No other file conflicted.

### Findings
**Blocker:** none.
**Should-fix:** none.
**Later:**
1. The core's allow_auto_merge is still false (the report says so): `gh pr merge --auto` fails until Liam switches it on, and the core's ruleset should then require `policy`, `proxy`, `harness-windows`. `wsc ci check-settings` says exactly this; owner action, not a code change.
2. The `GameLock` racing-takers test timed out on Windows bash here, with this branch and alone. Worth a backlog line if it recurs on other Windows machines.
3. B62 (fold `netfetch.retry` into the fetchers at the next DLL-input change) is already in the backlog.
