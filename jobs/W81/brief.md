# W81: `job.sh lock --wait` measures whole seconds

Model: Sonnet, reason: none needed (Sonnet is the default). One shell loop and one host test, checked in CI; no DLL source, no reverse engineering. Budget about 40 tool calls.
Subagents: none needed.

Semver: patch

Rule 79 exposure: `harness/job.sh` is a harness input, so a consumer that bumps its pin to the tag with this change carries 20 passes (rule 79) in that bump. This job itself
changes no DLL and no `proxy/` file, and needs no PC: the behaviour is a timing in a shell loop that `tests/test_job_sh.py` runs under Git Bash on `windows-latest` and under
bash on `ubuntu-latest`. `needs_pc` stays false.

## Goal
`tests/test_job_sh.py` `test_lock_wait_takes_a_lock_released_meanwhile_and_times_out_with_124` fails at random on the required `gates` check, on branches that never touched
`harness/job.sh` (W34 run 41934314012; W31 run 42075839757, `2.0673 not greater than or equal to 2.5`; W44 run 42138672224, `2.0649`). A red there can stop an auto-merge.
Cause (`jobs/W44/review.md`, round 2, "The failure on ubuntu"): the `lock` verb sets `end=$(( $(date +%s) + wait_s ))` and compares with `date +%s`, whole seconds, and polls
with `sleep 2`. A call started late in a second sees `date +%s` tick over early, so `--wait 3` reaches the deadline at its second poll after about 2 s, not 3 s. The reviewer's
partial reproduction on a PC (20 runs, started at set points in the second) gave two bands, 2.65 to 2.88 s and 5.04 to 5.14 s; the early band is this bug, and it stays above the
test's 2.5 floor there only because Git Bash starts slowly. The Linux rate was not measured. Fix the deadline so `--wait S` waits S seconds, and prove it.

## Start
1. `git pull`; check out `job/W81` (`python3 wsc.py jobs next` names the branch). If this session's model is not Sonnet, stop and say so.
2. Read `jobs/W44/review.md` (the section named above), then `harness/job.sh` `lock` (search for `--wait` and `wait_s`) and the test. Check each line number you rely on again.

## Target facts (check each again before relying on it)
- `wsc find "job.sh lock"`: the tools row `harness.job` and the decision `C26` (the lock is the session's) are the contract; do not change what a lock means.
- Exit codes are part of that contract and stay: 0 taken, 2 refused without `--wait`, 124 `--wait` expired, 64 bad usage. The stderr text `job.sh lock: no lock after ${wait_s}s` stays.
- `--wait` is capped at 100 s in `job.sh`; keep the cap.
- The same whole-second pattern appears in other loops of `job.sh` (`ctl` wait, the job-result wait). They poll at 0.5 s or 1 s and compare against a seconds deadline, so
  they end up to 1 s early. They are not part of this failure; see Open questions.
- `date +%s%N` must work on both CI runners and on the PC's Git Bash (GNU date). Check it on `ubuntu-latest` and `windows-latest` in CI; if `%N` prints literally on either
  (it does on BSD/macOS date), that is the kill criterion below, not a guess.

## Decisions already made for this job
1. **Fix the deadline, not the floor.** Compute the deadline and the clock in milliseconds from one small function in `job.sh` (for example `now_ms()` from `date +%s%N`), use it for
   `end` and the comparison in `lock`, and shorten the last sleep to the time left (the smaller of 2 s and the remainder) so a `--wait 3` ends at about 3.0 s, not at the next 2 s poll.
2. **Never earlier than asked.** A `--wait S` call that exits 124 has waited at least S seconds. That is the invariant the test pins.
3. **The poll stays 2 s** while time remains (a lock attempt touches the watcher folder; do not poll faster without a reason).
4. **The test asserts the invariant, with no slack to hide a regression.** In the 124 half of the test the floor becomes `>= 3.0` (the requested wait) and a ceiling of about 6 s is added so
   a hang fails too. Do not widen or lower the floor to get green.
5. No new dependency; Python stdlib and bash only.

## Deliverables
1. `harness/job.sh`: the millisecond clock and the corrected `lock` loop as in decisions 1 to 3. Keep the header lines (`purpose:`, `usage:`, `when:`, `verb:`) valid and the tool's registry
   row current (`wsc find "job.sh lock"`; update it with `wsc reg set tools harness.job ...` only if its text says whole seconds).
2. `tests/test_job_sh.py`: tighten the assertions of the named test as in decision 4. Add one deterministic test that does not depend on when in a second it starts: run `lock --wait 1` against a held lock
   several times (for example 6 runs, started at different sub-second offsets with `time.sleep` between them, each timed) and assert every run takes at least 1.0 s and exits 124.
3. **Prove the old code was red.** Before the fix, run the new test against the unfixed `job.sh` (in a throwaway copy) and say what it printed; it must fail for the early-deadline reason.
   If it cannot be made to fail locally, say so and cite what did fail it (the three runs above are the only red evidence).
4. `docs/` only if a doc states the wait in whole seconds (`grep -rn "lock --wait" docs`); otherwise none.
5. `python3 wsc.py gates` green, then CI green on the pull request on both runners. Cite the run id and the elapsed time of the `--wait 3` half on each.

## Out of scope
- The other `date +%s` loops in `job.sh` and `watcher.ps1`, the `ctl` verb, the lock's stale expiry (`stale_min`) and its ages in whole seconds (a lock age in whole seconds is fine).
- Any change to `proxy/`, the DLL, the acceptance harness or the pin; the consumer's pin bump (a separate job in the game repo, which carries rule 79).
- Skipping, retrying or marking the test flaky in CI.

## Open questions
- Fix the same early end in the `ctl` and job-result waits (up to 1 s early)? recommended: no, leave them; they are timeouts of tens of seconds where 1 s early is harmless, and the fix would touch the watcher protocol's timing; default after: 2026-11-20. If the builder disagrees, file a `later` row, do not widen this job.

## Kill criteria
- `date +%s%N` does not give nanoseconds on either runner or on Git Bash (a literal `N` in the output): stop, commit what exists and report; do not write a Python or PowerShell fallback inside `job.sh`.
- The fix needs a change to `watcher.ps1`, the lock file format, or any exit code: stop and report.
- The tightened test is red in CI for a reason other than the deadline, after two fix attempts: stop, commit, report the run id.
- Over about 40 tool calls: stop, commit, report what is left.

## Finish
Report in `jobs/W81/report.md` with the sections `## What was built`, `## Evidence`, `## Deviations from the brief and why`, `## Open questions`. Evidence must hold: the output of the new test against
the unfixed `job.sh` (or the statement that it cannot fail locally), the CI run id with both runners green and the measured elapsed time of the `--wait 3` half on each, and a date on every "verified".
Run `python3 wsc.py jobs usage W81 --write` where it applies, push `job/W81`, open the draft pull request, then
`wsc reg set jobs W81 status=review report=jobs/W81/report.md`. An independent reviewer merges (C18); never mark your own job `done`.

## Registry gaps
- path: tests/test_job_sh.py; owner: liam; reason: a host test file, not a tool (wsc.toml `[tools]`)
- path: jobs/W44/review.md; owner: liam; reason: a dated review record, cited for the cause
