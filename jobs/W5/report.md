# W5 report: watcher virtual display restore whose position is gone

Written by the orchestrator from the build agent's hand-back: the build ran as a subagent, and the harness refuses a subagent's Write of a
report file, so the parent writes it. Same Claude-Session as the build.

## What was built
- `harness/vdisplay_probe.ps1`:
  - New pure functions `Get-RestorePlan` (returns drop, already, saved or current, plus a reason) and `Invoke-RestoreApply` (an injectable apply
    step: try the saved origin, then the saved mode at the current origin). `Test-RectTouches` is the contiguity rule.
  - `-Restore` now runs: display missing, exit 3; already back, exit 0; saved origin legal and applies, the old "VIRTUAL RESTORED" line; otherwise
    the saved w/h/hz applied at the display's current origin (re-read after a failed first try), which prints "VIRTUAL RESTORED (position gone):
    <dev> mode back at WxH@Hz; saved origin X,Y not applicable (<reason>), kept X2,Y2" and exits 0. Exit 5 or 6 only if the mode itself cannot be
    applied at the current origin.
  - `Apply-ToVirtual` no longer calls `exit`; it returns `@{ok; exit; now}`. `-Set` and `-Origin` exit with the same codes and messages as before.
    A `-NoHelp` switch hides the driver-config help on the first (saved-origin) try.
  - `Get-OtherChanges` and the cursor put-back run on every apply, including the fallback. The record format is unchanged. The tool header's
    purpose line says what a restore does when the position is gone (it feeds the tools registry row, updated with `wsc reg add`).
- `harness/watcher.ps1` 1.3.0 (was 1.2.0):
  - `Vdisplay-Restore` on tool exit 3 moves the record to `_to_delete\vdisplay_restore_<utc>.json.dropped` and logs "vdisplay: pending restore
    dropped (no virtual display: <tool summary>); record kept at <path>"; it returns `$null`, so the launch is not refused for it.
  - A repeated identical `RESTORE FAILED` is logged once; a count line ("the RESTORE FAILED above repeated N more times") follows when the message
    changes, the restore succeeds or the record is dropped.
  - The refusal text for exits 5, 6 and 7 names the file and the one safe fix (move it to `_to_delete\`; the display keeps its mode).
- Tests: `harness/tests/Test-Unit.ps1`, 3 new cases and the fixture `harness/tests/fixtures/vdisplay_restore_20261030_j44.json` (the 2026-10-30
  record); `harness/tests/Test-Integration.ps1`, 1 new case.
- `docs/CONSUMING.md`: 2 lines in the harness section. `VERSION` 0.11.0, then 0.14.0 when `main` was merged in after W6 (0.13.0) merged first (2026-11-03).

## Evidence
- The failure as found (from the consumer's J48 brief; the original watcher log was not re-checked here): the record was x=3839, y=2160,
  3840x2160@60, saved 2026-10-30T16:55:49Z. After the 4K primary left, the restore failed with "APPLY FAILED ... not 3840x2160 at 3839,2160 after
  the change (display tool exit 5)" once a minute for 24 minutes and the launch was refused. Cause: `-Restore` applied the saved mode and origin
  together, only an overlap check guarded the origin (so the displays-must-be-contiguous case was never handled), nothing tried the mode alone, and
  the record was never given up.
- Tests red then green (2026-11-03, local, Windows PowerShell 5.1):
  - `Test-Unit.ps1` at commit `d2b3173`: 46 passed, 3 failed, all "Get-RestorePlan is not recognized" (the output is quoted in that commit body).
  - `Test-Unit.ps1` at commit `97cc177`: 49 passed, 0 failed. Rerun by the orchestrator on `97cc177`: "unit : 49 passed, 0 failed".
  - `Test-Integration.ps1 -Only 'headless restore: a pending|virtual display at another size'` at `97cc177`: 2 passed, 0 failed, against a
    temp-root watcher and the fake display tool only.
  - `python3 wsc.py gates` at `97cc177` (2026-11-03): 12 ok, 2 warn (the `hooks` gate: this clone's `core.hooksPath` is an absolute path; the
    `tests` gate's note of 1 skipped host test, the POSIX-sh pre-push hook test), 0 failed.
- Fixture behaviour: the 2026-10-30 record against `$topoA` without the 4K primary (the Dell as primary at 0,0, the virtual display at 2560,1440,
  per the log) picks the current-origin step with the reason "touches no other display". Also tested: an overlapping origin and a far-outside origin
  pick current, a missing display picks drop, an already-restored display picks already.
- Apply fallback: "first apply fails, second succeeds" calls the saved origin first and then 2560,1440 with the same mode; "both fail" gives exit 5
  after exactly two tries; a legal origin that applies makes one call.
- Versions, chosen 2026-11-03: watcher 1.3.0 (a minor bump, so a consumer's rule-79 streak restarts for it); `VERSION` 0.11.0 (`origin/main` is
  0.9.0, `job/W2` claims 0.10.0, W3 takes a patch, W4 is not built).

## Deviations from the brief and why
- The topology after the 4K primary left is not recorded, so it was built from `$topoA` and the log's later origin 2560,1440. The saved origin
  3839,2160 overlaps nothing in it, so the overlap check alone would still pick "saved". The new planner therefore adds a contiguity rule: an origin
  that touches no other display, by edge or corner, is not legal. That is what makes the fixture pick the fallback. `Get-OriginPlan` and the
  `-Origin` path are unchanged; the apply-time fallback covers anything the rule misses.
- `harness/README.md` and a "Headless launch" section do not exist in warscape-core (they live in the game repo), so the doc change is the tool
  header plus two lines in `docs/CONSUMING.md`.
- `fake_vdisplay.ps1` already exited 3 on `-Restore` when its state file says `none`, so it was not extended; the new integration case uses that.
- The integration suite was not run in full: its header says it is never run on the PC (the tz case changes the machine time zone, the installer
  case registers a scheduled task), and the case "no virtual display, or a proxy without the marker" runs the real `vdisplay_probe.ps1` against real
  displays while another job held the PC. Only the two relevant cases ran; the new integration case was not run red before the fix (the red
  evidence is the unit output). The core's Windows CI runs the suite.
- No `git stash` (the stash stack is shared): red first is shown by commit `d2b3173`.
- Game names are banned in tracked core files (the `no_game_names` test), so comments say "a game".
- The branch was built before `brief/W5` (PR #23) merged and starts from that branch; `main` is merged in once the brief is on it.

## Open questions
- The contiguity rule accepts corner contact. If Windows rejects diagonal-only contact on some versions, the apply-time fallback still handles it.
  Is that acceptable, or should the planner and the fallback be tightened?
- A consumer's 20-pass acceptance streak is per watcher version: 1.3.0 starts at zero (napoleon J48 runs it, with the live check and the pin bump).
