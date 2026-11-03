## Round 1 (2026-11-03, branch job/W8 at 51a40a4)

**Verdict: merge.**

Reviewed cold from the brief and report. Gates 13 ok / 1 warn / 0 failed (529 host tests, 5 known skips); CI on 498e59a green (gates on both OSes, proxy, harness-windows).

**Fixed by the reviewer** (1 commit): `main` had moved (W14 0.17.0, W11 0.17.1) and `VERSION` conflicted, so auto-merge could not land. Merged `main` into the branch, kept 0.19.0 (W17 holds 0.18.0), re-ran the gates green.

**Claims against evidence:** the report's counts, provenance, deviations and six failing fixtures match the diff. `bash_or_skip` / `WSC_REQUIRE_BASH` is a sound addition (unittest passes a skip, so harness-windows would otherwise pass silently). Risk-first reading: `harness/ctl.py` `bash()` (nothing under the game root is read any more; plain-`bash` fallback and cache kept) and `warscape/gitbash.py` (injectable probes, `%LOCALAPPDATA%/Git` dropped, skip reason names no game command). No blocker or should-fix.

**Later**
- `VERSION` 0.19.0 skips 0.18.0 until job/W17 merges; whichever of W17 and this merges second takes a free number and merges main (brief's version-collision rule).
- Report open question 2 (`acceptance.py main()` resolves the adapter before parsing args) belongs to W9/W10; the `Baseline` patch in `tests/test_acceptance.py` can go then.
- `C:\nullgame_pc` was left on Liam's PC by early local runs; delete by hand.
