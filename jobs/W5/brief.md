# W5: watcher virtual display restore whose position is gone (napoleon J48's core half)

Model: Sonnet, reason: none needed (Sonnet is the default). PowerShell with host tests; no reverse engineering and no DLL change. Budget about 70 tool
calls for the core part (napoleon-remastered J48 has about 120 in all; the live check and the 20-pass run are the remainder, and run there).

## What
The core half of napoleon-remastered J48 (its brief, `jobs/J48/brief.md` on that repo's `main`, is the full specification: read "The failure", "Decisions
already made" and "Deliverables" 1 and 2). When the display topology changes under a pending `vdisplay_restore.json`, the saved origin cannot apply and
the restore fails every minute while every `launch` is refused. A restore whose saved position cannot apply restores the mode at the display's current
origin; a missing virtual display drops the record (D38).
1. The failing host test first, committed red, then the fix:
   - `harness/tests/Test-Unit.ps1`: a pure restore planner next to `Get-OriginPlan` (dot-sourced through `-LibOnly`) that returns which of the three steps
     applies and why; the 2026-10-30 record as a fixture in `harness/tests/fixtures/` (the napoleon brief names its source), against a topology built from
     `$topoA` without the 4K primary; an overlapping origin; a display that is absent ("drop"). The apply-time fallback behind an injectable apply step
     ("first apply fails, second succeeds" and "both fail").
   - `harness/tests/Test-Integration.ps1`: `fake_vdisplay.ps1` gets an exit-3 restore; the record is moved aside as `.dropped`, the log says so, the next
     launch is not refused. The existing restore cases stay green.
2. The fix in `harness/vdisplay_probe.ps1` (`-Restore`: already back, then legal origin, then current origin; `Apply-ToVirtual` stops calling `exit` inside
   so the fallback can follow; `Get-OtherChanges` and the cursor put-back stay) and `harness/watcher.ps1` (`Vdisplay-Restore`: exit 3 moves the record to
   `_to_delete\` as `vdisplay_restore_<utc>.json.dropped`; a repeated identical `RESTORE FAILED` is logged once with a count; the refusal text names the file
   and the one safe fix). The record format is unchanged.
3. The watcher `$Version` minor bump (the consumer's rule-79 streak is per watcher version), the tool header (`purpose`/`usage`, which feed the tools
   registry row), `harness/README.md` and `docs/` wherever the restore is described, and `VERSION` at the next free minor.
Branch `job/W5` (the core's policy refuses a free-named branch). Use PowerShell test runs on the host; no PC is needed for the core half.

## The consumer's part (not here)
The live check on the real tool, the watcher update on the PC, the 20 consecutive acceptance passes for the new watcher version (rule 79), the pin bump
and the report all run under napoleon-remastered J48, after Liam tags this. The DLL is unchanged.

## Kill criteria
- The host test cannot be made to fail on the 2026-10-30 fixture after about 15 calls: write down what the fixture lacks (the topology after the 4K primary
  left is not recorded), take the apply-time fallback as the fix and test that, and say so in the report.
- The fix would change a Display other than the virtual one, or the record format, or needs a proxy or DLL change: stop and report.
- Core CI red after three fix attempts for a cause in this change: stop and report.
- Version collision: W2 claims 0.10.0, W3 takes the next patch, W4 wants a minor too. Re-read `origin/main` `VERSION` and the open `job/*` branches before the
  last commit; the second to merge takes the next free number and merges `main`. Say in the report which number you took.

## Finish
Report in `jobs/W5/report.md` (the failure as found, the tests red then green, the watcher version, deviations, open questions), then
`wsc reg set jobs W5 status=review report=jobs/W5/report.md` (`python3 wsc.py`). Liam merges and tags the core; stop after the PR.
