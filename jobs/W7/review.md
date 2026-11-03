## Round 1 (2026-11-03, branch job/W7 at eb01cf0)
**Verdict: merge.**

Checked: `wsc gates` 13 ok / 1 warn (environment skips only); `wsc policy` lists only the review and the `done` row (mine to set). CI: gates and proxy on the
code head d0445f9 were green (run 41712246669); the runs on the report-only head eb01cf0 were still running when I reviewed, and auto-merge waits for them.
I had no C++ compiler locally, so the host tests were not re-run by me; I read them and the code instead.

Brief against the branch: every deliverable is present (typed keys with min/max and float, `value_key` rows, `patch_value.h`, driver on the effective copy,
B41 test, null game, docs, version 0.16.0, tool row). `MakePatchPlan`, `ApplyPlanToBuffer` and `WritePlanAtomic` are untouched, so no kill criterion
applies. B41 answer (no `value_offset`, test plus doc paragraph) has its test in `test_patch_engine.cpp`. Deviations in the report are named and reasonable.

Risk-first reading: `patch_value.h` `ResolveSiteValue` / `ResolveSites` (the only new logic that decides what is written to the exe) and
`config.h` `Normalise` / `ClampToRange` (user-controlled text). Order of resolution matches the brief; a refused value disables only its own site; the
float parse is by hand and locale-free.

### Blocker
None.

### Should-fix
None.

### Later
- `proxy/src/patch_value.h` ResolveSiteValue: a tiny non-zero float key (e.g. `1e-50`, valid float text and inside `[min, max]`) passes the
  float32 range check, then `(float)v` underflows to 0.0, which differs from stock, so a row without `value_floor_stock` writes 0 even though only the
  key at 0 should mean "zero/stock" semantics. Suggested: after encoding, refuse when a non-zero written value encodes to 0 (or a denormal). Seen by reading;
  not run (no compiler here). Low risk: `min`/`max` and the floor on distance rows hide it.
- Int rows round ties to even (`nearbyint`); documented in the report, worth one line in `docs/PROXY_SITES.md` if not already there.
