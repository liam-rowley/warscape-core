## Round 2 (2026-11-04, branch job/W30 at df38cb1)

**Verdict: merge.**

Round 1 answered: the `RUN_CITE` blocker is fixed (`warscape/jobq.py:153` now ends on `\w`, test `test_citation_followed_by_punctuation` covers `.`, `)`, `,`, `:`), the blank line is
fixed, and `VERSION` is 0.25.0 against `origin/main` 0.24.0. Local `wsc gates`: 14 ok, 1 warn (skipped POSIX/capstone tests), 0 failed. CI `gates (ubuntu-latest)` and
`gates (windows-latest)` are green at df38cb1; `harness-windows` was still running when I read it (auto-merge waits on it). The yaw fix (`angle_diff`, yaw only, pitch plain `abs`) and the off-by-default
`failed_results` rule match the brief; the call site is one line and `report_problems` is unchanged. Risk-first read: `failed_results_problems` (reads files under a cited path;
the `root not in folder.parents` guard blocks `..` escapes). No findings.

### Later
- If another job takes 0.25.0 first, the later one must bump `VERSION` (`core_pin` gate).

## Round 1 (2026-11-04, branch job/W30 at 85d0040)

**Verdict: merge after fixes.**

Local gates pass (13 ok, 1 warn: skipped POSIX/capstone tests). CI `gates (ubuntu-latest)` is red, a blocker (run 41795487866): `FailedResults.test_unnamed_failure_is_one_problem`,
`test_named_only_elsewhere_fails` and `test_problems_calls_it_only_when_configured` each get 0 problems instead of 1. The yaw half is correct and matches the brief's proof table.

### Blocker
1. `warscape/jobq.py:144` `RUN_CITE = (?:[\w.-]+/)*runs/[\w.-]+` captures a trailing sentence period: `Evidence: runs/r1.` yields `runs/r1.`. Windows
   strips the trailing dot when resolving the path, so `is_dir()` is true there and the tests pass locally; on Linux `runs/r1.` is not a directory, the folder is
   skipped and the rule silently reports nothing. See it fail:
   `python3 -c "import re; print(re.findall(r'(?:[\w.-]+/)*runs/[\w.-]+', 'see runs/r1. and runs/r2,'))"` gives `['runs/r1.', 'runs/r2']`.
   This is also a real defect for consumers on Linux CI. Fix: strip trailing `.` (and `-`) from the match before resolving (or end the pattern on `[\w]`), and add a
   test whose citation is followed by `.`, `)` and `,` so a platform cannot hide it. The `test_*` fixtures already cite `runs/r1.`, so they will go green on CI once fixed.

### Should-fix
2. The report says VERSION 0.23.0 collides with W20 on `job/W20` and "the orchestrator renumbers at merge". Whichever merges second must bump; make sure the fix
   session re-checks `VERSION` against `main` (the `core_pin` gate) after the rebase.
3. `tests/test_jobs.py` has a stray extra blank line before `class Check` (three blank lines).

### Later
- The new tests were not run red first (admitted in the report); the Linux failure is exactly what a red-first run on a second platform would have caught.
