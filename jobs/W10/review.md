## Round 1 (2026-11-04, branch job/W10 at bd10fd3)

**Verdict: merge.**

Reviewed cold from the brief and report. Machines first: `wsc gates` full on the branch: 13 ok, 2 warn (hooks path, skipped capstone/POSIX tests), 0 failed, 633 host tests. CI on bd10fd3: `gates` (ubuntu, windows) and `harness-windows` (run 41801988717) green; `proxy` and `policy` skipped while a draft (policy is run locally below). Local `wsc policy` refused only for the missing review and row, which this commit supplies.

### Claims against evidence
- The four W10 integration cases (owner/session, B21 exit codes, B27 kill postcondition, B30 duplicated prefs key) and the report's CI numbers are in the green `harness-windows` job; the report's run 41798681947 was on an earlier head, and the head since then only merged `main` (W30, briefs, `jobq`, `ctl` tests), which I diffed. Nothing is claimed that has no evidence.
- Failing fixtures are named in the report; the kill-postcondition fixture is observable only in the B27 integration case, and the report says so.

### Brief
All nine items and decisions 1-13 are present. Deviations are all named with a reason in the report (C24 not C23, VERSION 0.26.0, unique expiry-name suffix, put-back logged on stderr, vanished-file refusal, `ctl.py send()` keeps 170 s). The scope list was respected; no game names added.

### Risk-first reading
Read in depth: the B20 takeover in `job.sh lock` and `Expire-StaleLock` (a wrong move deletes or doubles a live lock), then `Wrap-Ps1Body`, `Wait-NotRunning`, `pending_restore`/`wait_for_restore`, and `resolve_identity`. The read, move aside, check line and mtime, no-clobber put-back protocol is sound on both sides; `Check-Owner` is exact-case and accepts the lock's session; refusals name the fix.

### Findings
**Blocker:** none. **Should-fix:** none.

**Later**
1. `harness/ctl.py` (`main`, the `resolve_identity` call before `--no-pc` is looked at): an offline `--no-pc` run with no session id is refused though it needs no lock. See it fail: run `ctl.py --no-pc state` with `CLAUDE_CODE_SESSION_ID` and `WSC_SESSION_ID` unset.
2. `harness/watcher.ps1` `Wrap-Ps1Body`: if the last statement is a cmdlet that fails non-terminatingly after an earlier handled native failure, `$?` is false and `$LASTEXITCODE` is the old code, so the job fails with the old code (the B21 shape, much narrower). Ending in `exit 0` avoids it; acceptable per decision 10.
3. The residual B20 window the report names (a third taker creating `game.lock` between the move and the put-back leaves two winners) stays a documented limit; the file is kept in `_to_delete` and logged.
4. Whichever of W10 and W23 merges second renumbers C24 and `VERSION` (the report says so); `wsc gates` (`core_pin`) will show it.
