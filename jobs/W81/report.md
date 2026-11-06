# W81 report: `job.sh lock --wait` measures whole seconds

W81 makes `job.sh lock --wait S` wait at least S seconds: the deadline and the clock are now in milliseconds (`now_ms()`, `date +%s%N`), and the last sleep is only the time left (at most 2 s), so `--wait 3` ends at about 3.0 s instead of the second 2 s poll.

Usage: 30 tool calls; models: sonnet; 1 session, call count estimated by the session, no transcript tool

## What was built
- `harness/job.sh`: `now_ms()`; `lock` uses `end_ms`, computes `left_ms` each pass, exits 124 (text unchanged) when none is left, polls every 2 s while more than 2 s remain, else sleeps the remainder. Exit codes, the 100 s cap and the `--wait 0` refusal (2) are unchanged.
- `tests/test_job_sh.py`: the 124 half of the named test now asserts `>= 3.0` and `< 6.0`; new `test_lock_wait_never_ends_early_whenever_in_the_second_it_starts` (6 runs of `--wait 1` at different sub-second offsets, each 124 and >= 1.0 s).
- No doc states the wait in whole seconds (`docs/CONSUMING.md:288` only says "polls (max 100)"); the tools row text needs no change.

## Evidence
- Red before the fix (this PC, Git Bash, 2026-11-06): the new test against the unfixed `job.sh` failed twice: `0.7813723087310791 not greater than or equal to 1.0 : run 1 ended early` and `0.8718643188476562 not greater than or equal to 1.0 : run 0 ended early`.
- Green after the fix (2026-11-06): `python3 -m unittest tests.test_job_sh`, 35 tests OK. `date +%s%N` prints nanoseconds in Git Bash (checked 2026-11-06).
- Full `python3 wsc.py gates`, 2026-11-06: 14 ok, 2 warn (hooks path form, 5 skipped tests needing capstone/POSIX sh), 0 failed, 1383 host tests passed.
- CI run ids and the elapsed time of the `--wait 3` half on each runner: PENDING, not yet verified.

## Deviations from the brief and why
- None in the code. The CI runner timings are not in this report yet (see Evidence).

## Open questions
- `ctl` and job-result waits left alone, as recommended; no `later` row filed.
