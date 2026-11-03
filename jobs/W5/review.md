## Round 1 (2026-11-03, branch job/W5 at 4192223)

**Verdict: merge.**

Checked: `wsc gates` 13 ok / 1 warn (the known POSIX-sh skip), 0 failed; `Test-Unit.ps1` 49 passed, 0 failed; CI on the head all green (gates ubuntu and windows, harness-windows with the full integration suite, proxy). The red-then-green claim is backed by commit d2b3173 (3 unit cases red) and 97cc177. The policy check's only complaints before this review were the missing review and the row not yet `done`.

Brief: planner, apply fallback, exit-3 drop to `.dropped`, repeated-failure count, refusal text, watcher 1.3.0, tool header and registry row, docs and VERSION are all present; the record format and Apply-ToVirtual's other callers (-Set, -Origin) keep their exit codes. Deviations (contiguity rule added because the fixture's topology is unrecorded, no fake_vdisplay change, no README in the core) are named in the report with reasons.

Risk-first reading: `Invoke-RestoreApply` and `-Restore` in vdisplay_probe.ps1 (they change a display's mode). Only the selected virtual display is touched, the current origin is re-read before the fallback, and a failed fallback returns the real exit code and keeps the record. No blocker.

### Later
- watcher.ps1 `Vdisplay-Restore`: the dedupe key includes the tool summary, so a summary that embeds a changing value would log every minute. Harmless; watch the first live log.
- Corner-only contact counts as touching (open question in the report). The apply-time fallback covers a rejection; the napoleon J48 live check should confirm.
- VERSION 0.11.0 while main is 0.9.0 and W2 (0.10.0) is unmerged: whichever of W2 and W5 merges second must re-check VERSION against main.
