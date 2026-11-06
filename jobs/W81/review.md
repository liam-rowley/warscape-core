# W81 review

## Round 1 (2026-11-06, branch job/W81 at 8a7c76f)

**Verdict: merge.**

No blockers and no should-fix items. One later item, filed as W131 (pull request #162). The reviewer changed nothing outside the job folder and the row.

### Machines
- `python3 wsc.py gates` at 8a7c76f, 2026-11-06: 14 ok, 2 warn, 0 failed, 1383 host tests passed, 5 skipped. The warnings are the clone's hooks path form and the skips that need capstone or a POSIX sh; neither comes from this branch.
- CI on the head 8a7c76f (run 42214811667): `gates (ubuntu-latest)` green; `gates (windows-latest)` and `harness-windows` skipped by the `changes` filter, because only the report and the row moved after the code. `git diff a44a369 8a7c76f` touches only `jobs/W81/report.md` and the row, so run 42213700864 on bef3267 tested the same code: both `gates` jobs and `harness-windows` green. `harness-windows` ran `tests.test_job_sh` with `WSC_REQUIRE_BASH=1` (79 tests OK), so the Windows result is a real run and not a skip.
- Against the latest origin/main (4917d86): `main` moved two commits past the merge base, touching only `VERSION` and `registries/jobs/W130.json`, and `git merge-tree` is clean. On that merged tree `gates --fast` gave 14 ok, 1 warn, 0 failed, and `tests.test_job_sh` passed 35 tests on Git Bash and on Linux. The full gates were not rerun on the merged tree.

### Claims against evidence
- CI figures in the report (2m15s, 8m23s, `harness-windows` pass): match run 42213700864.
- Red before the fix: reproduced. The new test against the unfixed `job.sh` failed 5 of 6 on Git Bash, for the early-deadline reason (`0.41865 not greater than or equal to 1.0 : run 1 ended early`).
- `date +%s%N` gives nanoseconds: the suite passing on both runners shows it, since a literal `N` would break the arithmetic in `now_ms`. Also printed by hand on WSL Ubuntu, 2026-11-06.

### Timing measured by this review (2026-11-06, `lock --wait S` against a held lock)
| Host | Code | S | Runs | Ended early | Range (s) |
|---|---|---|---|---|---|
| PC Git Bash, full gates running alongside | fixed | 1 | 12 | 0 | 1.438 to 2.280 |
| PC Git Bash, full gates running alongside | fixed | 3 | 8 | 0 | 3.163 to 4.128 |
| PC Git Bash, full gates running alongside | old | 1 | 12 | 5 | 0.401 to 3.053 |
| PC Git Bash, full gates running alongside | old | 3 | 8 | 6 | 2.697 to 5.293 |
| WSL Ubuntu | fixed | 1 | 20 | 0 | 1.038 to 1.043 |
| WSL Ubuntu | fixed | 3 | 8 | 0 | 3.037 to 3.039 |
| WSL Ubuntu | old | 1 | 20 | 1 | 0.034 to 2.061 |

The invariant held in all 48 runs of the fixed code. The worst `--wait 3` on a loaded PC was 4.128 s, so the 6.0 s ceiling has room and should not become a new random red; `windows-latest` itself was not timed.

### The brief
- Decisions 1 to 5 followed: millisecond clock from one function (`harness/job.sh:92`), last sleep shortened to the time left (`harness/job.sh:216`), poll stays 2 s, floor `>= 3.0` with a ceiling under 6 s (`tests/test_job_sh.py:303`), no new dependency.
- Exit codes, the stderr text and the 100 s cap are unchanged; `watcher.ps1`, the lock format and the other `date +%s` loops are untouched. No kill criterion was reached.
- Named deviation, accepted: the report has no measured `--wait 3` time per CI runner, because CI does not print it. The assertion window passed on both runners, and the table above gives measured figures from a PC and from Linux, though not from the CI runners themselves.
- The 5.0 s ceiling in the new test (`tests/test_job_sh.py:316`) is not in the brief. It serves the same purpose as decision 4's ceiling, and the worst run here was 2.280 s.

### Risk-first reading
I read the `lock` loop in `harness/job.sh` in depth: it is a harness input and every PC session takes this lock. `lock_attempt` runs once more after the last sleep, so a lock released during that sleep is still taken. `--wait 0` still exits 2. The nanosecond value fits in bash's 64-bit arithmetic and has no leading zero to read as octal. `left_ms` is at least 1 where it reaches `sleep`, and `printf '%d.%03d'` gives a valid duration. The script runs under `set -u` only, so the `&&` line at `harness/job.sh:216` cannot end it. `end_ms` truncates to the millisecond, so the wait measured inside the script can be under 1 ms short of S; a caller's clock starts before bash does, so no caller can see that.

### Findings
**Blocker:** none.

**Should-fix:** none.

**Later:**
1. `tests/test_job_sh.py:310`: the new test does not set where in the second each run starts. Its `time.sleep` calls are fixed gaps, not offsets from the clock, so the old bug shows only when the second ticks during bash's startup. Against the unfixed `job.sh` it was red 5 of 6 on Git Bash and only 2 of 10 on WSL Ubuntu. To see it, restore `harness/job.sh` from origin/main and run that test ten times on Linux. The test is reliably green on correct code, and a change to `job.sh` also runs it on both Windows jobs, so this weakens regression detection and does not hold up the merge. Row W131, pull request #162.

### Repeats
None beyond W131. The other whole-second loops stay out of scope, as the brief's open question recommends.
