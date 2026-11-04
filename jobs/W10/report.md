# W10 report: Watcher and pc_deploy race fixes; the lock owner is the session

This report was written by the orchestrator from the builder subagent's hand-back, because the harness refuses a subagent's write of a
report file. The text is the builder's own apart from this note, the CI section and the VERSION renumbering: `main` took 0.25.0 with W30,
so the orchestrator's merge of `main` sets 0.26.0.

## What was built
- **H2, the owner rule.**
  - `harness/job.sh` has one helper, `owner_ok`, with the pattern `^[a-z0-9][a-z0-9_-]{0,39}$`. It is used by `scratch`, `lock`, `touch`,
    `unlock`, `holds`, `ctl` and plain jobs. A refusal exits 64 and says to lower-case the owner.
  - The watcher compares owners case-sensitively: `-ceq` in `Check-Owner` and `-cne` in `Auto-Restore`. `Check-Owner` also accepts the
    lock's `session=` as the request owner, and an owner that differs only in case gets its own refusal text.
- **H2, the pair rule.** The same owner with a different session is refused until the lock is stale. `lock -` makes the owner the session
  id. The `game.lock` line format is unchanged.
- **H2, the lock is required.**
  - `job.sh holds <owner>` exits 0 or 2, and prints the reason and the command that takes the lock. `ctl` calls it before writing the
    request, and `shot.sh` calls it before submitting.
  - `touch <owner>` and `unlock <owner>` act only on the holder's lock. A bare `touch` exits 64.
  - `lock --wait S` polls every 2 s, is capped at 100 s, and exits 124 on timeout.
- **H2, defaults.**
  - `ctl.py` and `acceptance.py` default `--owner` and `--session` to the session id. The id comes from `--session`, then
    `$WSC_SESSION_ID`, then `$CLAUDE_CODE_SESSION_ID`; Claude Code exports the last one.
  - With none of these set, both tools refuse with exit 2 and name the fix (`ctl` in its JSON `refused` shape).
  - An explicit `--owner` still works. With no session, the session falls back to the owner.
  - `PcEnv` calls `touch <owner>`.
- **H12, the stale age.** `job.sh` reads `lock_stale_min` from `watcher.ini` (default 20; an absent or unparsable value gives 20). The
  refresh and expiry message is built from that number.
- **B20, stale-lock takeover.**
  - `job.sh` and the watcher both read the lock, move it aside to a unique name, then check what they moved: the same line, and an mtime
    still older than the stale limit.
  - If the check fails, the mover puts the lock back with a no-clobber rename (`mv -n`, and `Move-Item` without `-Force`) and logs it.
    `job.sh` then refuses with exit 2, "refreshed or taken at the same moment".
  - `Expire-StaleLock $seen` takes the record it read as a parameter, and `Get-Lock` carries `raw`.
  - A test seam (`JOB_SH_TEST=1` with `JOB_SH_TEST_HOOK`) runs once between the read and the move.
- **H11, waits.**
  - The plain-job default wait and the `job.sh ctl` default wait are both 100 s.
  - A timed-out plain job is withdrawn as `.request.expired`.
  - `Get-Requests` lists only names that end in exactly `.request`; `Start-NextJob` and `Write-Status` both use it.
- **B21, ps1 exit codes.** `Wrap-Ps1Body` resets `$global:LASTEXITCODE` first and ends with
  `if ((-not $?) -and $LASTEXITCODE) { exit $LASTEXITCODE }`.
- **B27, the kill postcondition.** After `Kill-Game` succeeds, `Wait-NotRunning` loops `Pump`, `Watchdog` and `Write-Status` until no game
  image is listed and the state is `not_running`. It is bounded by `zombie_wait_s`, and a timeout is the existing ZOMBIE failure.
- **B30, duplicate prefs keys.** `Apply-PrefsOverlay` replaces every copy of a key, and `Get-PrefsValue` returns the last copy.
- **B39, a pending restore.**
  - `pc_deploy set`, given `--state` and a usable watcher, polls `<state>/watcher/profiles/_active.json` once a second, up to
    `--wait-restore` (default 30).
  - If the file is still there, `set` refuses, names the profile, owner, lock and game state, and leaves the ini untouched.
  - With no `--state` or no watcher folder, it prints one line saying a pending restore cannot be seen, then writes as before.
- **Watcher version.** `$Version` is 1.4.0.

## Evidence
- **Local, on this PC:**
  - `tests.test_job_sh`: 29 cases, OK.
  - `ctl`, `acceptance`, `pc_deploy` and `moved_tools`: 127 tests, OK.
  - The PowerShell unit suite under Windows PowerShell 5.1: 54 passed, 0 failed.
  - After the orchestrator's merge of `main`, `tests.test_ctl` and `tests.test_job_sh` together: 89 tests, OK.
  - Full `python3 wsc.py gates`: 14 ok, 1 warn (625 host tests passed, 5 skipped), 0 failed.
- **The `Wrap-Ps1Body` unit case** runs the wrapper under 5.1:
  - an early handled `cmd /c exit 3`, then a succeeding last statement: exit 0;
  - a last `cmd /c exit 4`: exit 4;
  - ending in `exit 0`: exit 0;
  - `exit 2`, then `exit 7`: exit 7.
- **Failing fixtures.** Each was applied in a throwaway worktree, since removed, and each turned its test red:
  - `Check-Owner` back to `-eq`;
  - the ps1 tail back to `if ($LASTEXITCODE)`;
  - the prefs `Replace(..., 1)`;
  - `Expire-StaleLock` without the check;
  - `job.sh`'s check-after-move replaced by `if false` (both B20 hook tests);
  - `pending_restore` returning None (three `SetWaitsForRestore` tests).
  - The tests were committed red first, in 95d8917.
- **CI (read by the orchestrator).** Run 41798681947 on 47321f6 is green:
  - `gates` passed on ubuntu and on windows.
  - `proxy` passed.
  - `harness-windows` passed: unit suite 54 passed, 0 failed; integration suite 34 passed, 0 failed.
  - The four W10 integration cases, which had never run before, all PASS:
    - "W10 owner: a request owner equal to the lock's session id is accepted, a different-case owner is refused (exact-case compare)"
    - "W10 B21: a ps1 job exits with its last statement, not an old native code"
    - "W10 B27: when kill is done the status already says not_running with no game image listed"
    - "W10 B30: a profile through a real headless launch sets every copy of a duplicated prefs key"
  - The kill postcondition fixture, which only the integration suite can observe, is the B27 case above.

## Version
0.26.0, with decision C24. The builder had taken 0.25.0 after merging `main` at 0.24.0 (W12). W30 then took 0.25.0, so the orchestrator
merged `main` again and set 0.26.0. W23 also holds 0.26.0 and C24 on its branch, and is renumbered to 0.27.0 and C25.

## Deviations from the brief, and why
1. **C24, not C23.** W12 took C23.
2. **VERSION 0.26.0, not 0.23.0.** See Version above.
3. **The `job.sh` put-back is logged on stderr.** `job.sh` has no log of its own, and concurrent appends to `watcher.log` from another
   process were avoided. The watcher side logs to `watcher.log`.
4. **A moved-file safety check in the B20 protocol.** In a stress run of 4 parallel takers on Git Bash, a moved file once vanished between
   `mv` and `stat`. If the moved file cannot be read or stat'ed, the taker now treats the takeover as unverified and refuses (exit 2).
   - With the check, 4 takers over a stale lock produced exactly one success in 6 of 6 stress runs.
   - The test runs two rounds.
5. **Random suffix on watcher expiry names.** `game.lock.expired_<owner>_<stamp>` gains a 6-character suffix. Without it, a second expiry in
   the same second hit the no-`-Force` move and failed. Filters on the prefix still match.
6. **Existing tests changed, each with its reason:**
   - the scratch-length cases 32/33 became 40/41 (decision 1);
   - the queued-request test now expects the request to be withdrawn (decision 9);
   - a bare `touch` became `touch <owner>`;
   - the "its own lock rewritten" case re-locks with the same session, because the pair rule refuses a different one;
   - the `ctl` tests take the lock first, because `ctl` now requires it.
7. **`ctl.py` `send()` keeps its 170 s default.** The brief keeps the `ctl.py` and `acceptance.py` waits unchanged.
8. **`acceptance.py` resolves its identity late.** `cmd_run` and `cmd_measure` resolve it after the baseline and preflight checks, so the
   rule-74 refusals still come first.
9. **A wrapper limitation, noted in the code.** A ps1 job body that opens with `param()` cannot take the `LASTEXITCODE` reset line first.
10. **The lock requirement now also applies to a hand-run `job.sh ctl` or `shot.sh`.**

## Open questions
- **The brief's questions 1 to 4** were answered as it recommended: free-text owners kept under the pair rule; every prefs copy set;
  `exit 0` documented for robocopy codes; the `ctl` default wait at 100 s.
- **Question 5.** Claude Code exports `CLAUDE_CODE_SESSION_ID`, so no extra hook is needed. Another harness would set `WSC_SESSION_ID`;
  the docs and the refusal text say so.
- **A residual race.** If a displaced fresh lock cannot be put back because a third taker created the name between the move and the
  put-back, two takers could both report success. The put-back leaves the moved file in `_to_delete` and says so. The window is tiny, and
  it was seen only as the vanished-file case above.

## Consumer migration (napoleon-remastered J78; also in `docs/CONSUMING.md` "The game lock is the session's")
- Update the PC's watcher to 1.4.0 first: `pc_deploy.py kit --what harness`, then `send`, then `update kit=<id>`. The pin bump that
  crosses this tag needs acceptance passes on the new build.
- Set `WSC_SESSION_ID`, or pass `--session`, in every PC session, and drop `--owner claude-acceptance` and `--owner claude-ctl`. Owners
  kept explicitly still work under the pair rule, but need a session.
- `job.sh touch` needs the owner.
- Take the lock (`job.sh lock <owner|-> <session> <purpose>`) before a hand-run `job.sh ctl` or `shot.sh`.
- A timed-out `job.sh` request is now withdrawn.
- Owners must be lower case and at most 40 characters.
- Nothing else changes: no adapter, config key or ini change.
