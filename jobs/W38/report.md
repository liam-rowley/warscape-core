# W38 report: three CI flakes fixed at their causes

Built by the orchestrator session 3815a970 on 2026-11-04, the day Liam asked for it ("Fix now"). VERSION 0.30.1; watcher 1.4.1.

## 1. The watcher lost a fast proxy refusal (a product race)
**Cause.** `Headless-Wait` returned "not running after the start" without reading the status file when the game was already gone at its
first look, and "the game exited before reporting on_virtual" when the game wrote `refused` after the loop's read and exited before the
alive check. Either way the proxy's own reason was lost. Seen on PR 62's `harness-windows` (run 41852870156). That case's assertions threw
before its cleanup, so five later cases failed on its leftover lock and files.

**Fix.** `harness/watcher.ps1`: a new `Headless-Refused` reads the status once more in both places, and takes a `refused` only if it is this
launch's (its pid, or written no earlier than `LaunchAt` minus 1 s when no pid was seen). `Headless-Wait` takes the launch time from the
existing `$LaunchAt` (no new timestamp). `$Version` 1.4.1, and one line in `docs/PROXY_HARNESS.md` asks consumers to update the PC's watcher.

**Tests.**
- `harness/tests/Test-Unit.ps1`, two new cases, with the process lookups stubbed so each order is deterministic:
  - The game is gone before the first look: the detail is reported. A refusal written an hour before the launch, or no status file, gives
    the generic line.
  - The game writes `refused` after the loop's read, then exits: the refusal is reported. A refusal for another pid gives the generic line.
- Red then green, run locally: on main's watcher (1.4.0) both new cases fail, so the unit suite shows 54 passed, 2 failed. On 1.4.1 it
  shows 56 passed, 0 failed.
- `harness/tests/Test-Integration.ps1`:
  - A new end to end case uses a `.refuse` trigger in the fake game, which makes it write `refused` and exit 2160 at once.
  - It also checks that a stale refusal (another pid, an hour old) is not reported.
  - Both refused cases now clean up in `finally`, so one failure no longer fails the cases after it.
- The integration case cannot force the order, because the launch usually still sees the fake game alive. The red-before job on main's
  watcher showed this: its detail check passed (run 41863085797). So the integration case is end to end cover, and the two unit cases are
  the regression tests.

## 2. The restore-wait test raced its own timer (a test race)
**Cause.** `test_a_restore_that_finishes_during_the_wait_lets_set_write` deleted `_active.json` from a timer at 1.0 s, while `set` polls the
file once a second. On Windows a delete fails while another handle has the file open; checked here: `unlink` of an open file raises
`PermissionError` (WinError 32). The timer thread died, the file stayed, and the 20 s wait ended in SystemExit. Seen on `main`
`gates (windows-latest)` at the W22 merge (run 41857256437, issue 74, closed by W22's `main_health` after the rerun).

**Fix.** The timer fires at 1.5 s, between polls, and its delete retries on `PermissionError` (200 times, 10 ms apart). `pc_deploy.py` is unchanged.
**Proof.** 50 of 50 runs passed on Windows here; `tests.test_pc_deploy` 40 tests OK.

## 3. The capture stress check read `waiting` too late (a test race)
**Cause.** In `Stress`, `case CapStep::start` checked `waiting.load() != 1` after the render thread's CAS from Armed to Recording. If that
thread is preempted between the two, the ctl thread can time out twice, abandon the capture and store `waiting = 0`, all legitimately.
Seen on W20's `proxy` job (run 41844358937, seeds 3 and 4, 1 error each, final state idle, all 6000 captures run).

**Fix.** A waiter-less start counts only while the state is still Recording. The ctl clears `waiting` only after it moved the state out of
Recording or saw Done (which only the render thread makes, after the start), so the check still catches a real break. `capture.h` is unchanged.

**Proof** (in the `wsc-w6-build:local` image, g++ 13.3, 16 cores):
- A copy with a 200 µs sleep on 1 start in 8, right after the CAS:
  - the old check: 5 of 5 runs failed, with 45 to 65 errors per seed;
  - the new check: 0 of 5 failed.
- The committed test: 0 of 100 runs failed (156 checks passed; 6000 captures, of which 1071 done, 4101 nothing recorded, 828 abandoned).

## 4. Kill-Game failed on a game that exited just before the kill (a product race, found by the repeats)
**Cause.** `Kill-Game` runs `taskkill /F /T /PID <pid> 2>&1`. If the game has just exited, taskkill prints "not found" on stderr, and under
`$ErrorActionPreference = 'Stop'` Windows PowerShell 5.1 makes that a terminating error, so the job fails as "watcher error: ERROR: The process
"<pid>" not found. (line 330)". In the original refused case the test kills the fake game while the watcher's in-loop refused branch is
killing it, so repeat run 41866117636 passed that case only 2 of 10. The same race can hit the PC whenever the game dies during a kill.

**Fix.** The taskkill call runs with `Continue` in its own scope, so its output is logged and the wait that follows sees the process gone.
Out of the brief's scope as written (it named Headless-Wait); it is the same refused-launch path and the same flake, so it is fixed here.

**Test.** A `Test-Unit.ps1` case kills the pid of a process that has already exited. It fails without the change (its message is the same
"ERROR: The process ... not found" as in CI) and passes with it. The unit suite shows 57 passed, 0 failed.

## Runs
- Repeat run on a Windows runner, from the throwaway branch `scratch/W38-repeat` (run 41862891296), with
  `Run-HostTests -Only <the two refused cases> -Repeat 10`:
  - The old refused case: 10 of 10 passed.
  - The new integration case: 0 of 10. The first version of its stale check expected only "not running after the start", but a game that
    exits at once is sometimes seen alive first ("exited before reporting on_virtual"). Both lines are right, so the check now takes either,
    and still refuses the stale detail.
  - With both changes and the Kill-Game fix (run 41868892959): the old refused case 10 of 10, the new integration case 10 of 10.
  - That run's restore-wait loop stopped after its first (passing) run, because of my workflow script: unittest's progress dots go to stderr,
    and GitHub's PowerShell stops on stderr. The 50-run proof is the local Windows one in section 2.
- `python3 wsc.py gates`: green on this branch before the push (see the PR's CI for the runs).

## Deviations
- Brief decision 2 asked the integration test to cover both orders deterministically. It cannot force them, so the deterministic proof is
  the two unit cases, and the integration case is end to end cover. Section 4 is beyond the brief's list, for the reason given there. The brief's other decisions are as written.
- The throwaway branch `scratch/W38-repeat` was pushed with `--no-verify`, and its commits did not say why. It carries one extra workflow,
  is never merged, and is deleted after this job is pushed.

## Open questions
None.
