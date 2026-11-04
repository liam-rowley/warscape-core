## Round 1 (2026-11-04, branch job/W33 at ee0e6e4)
**Verdict: merge.**

Machines: `wsc gates --fast` 12 ok, 2 warn (hooks path, existing ci_render note), 0 failed on the merged head. The full `gates` run hung locally (several other sessions busy), so the C++ host tests and the wine smoke rest on CI: all 9 checks on df97c48 passed (`wsc jobs review`). After that head only docs numbers, comments and VERSION changed (the merge below). A red check on PR #87 (plan branch) is not this job's.

Merge done by the reviewer: `main` had moved (W25 merged and took C28 and 0.33.0). I merged `origin/main` in (never rebased), renumbered W33's decision to **C29** and took **VERSION 0.34.0**; the comments/docs that cite "W33, C28" now say C29, and CONSUMING's heading says 0.34.0. `jobs/W33/report.md` still says C28 / 0.33.0 (the builder's file, not edited; it records the number at build time).

Risk-first reading: `patch_engine.h` `WritePlanAtomic`/`WritePages` (writes the game's code pages under the loader lock) and `StartThread`/`DevOnDirect3DCreate`/`DevInit` (thread start points, gate order).
- Page arithmetic is right: first-to-last page of each written site, sorted and unique, one Unprotect per page with its own recorded value, failure path restores per page and writes nothing, non-power-of-two size refuses with no call. Bytes written come from the same `patch` arrays as `ApplyPlanToBuffer`.
- `StartThread` refuses under `inDllMain`; the flag is set around attach and detach; threads start once (interlocked) after all installs. `DevInit` gate: release key alone leaves `s_active` false, no thread; dev rules precede `proxy.file_rules`.
- Claims vs evidence: red-at-run-time commit 1df13fc exists before the fix (69651b0); deviations (suspended create, DevSideInit split, GetSystemInfo, no_gesture null game row) are named in the report and are sound.

Findings
- blocker: none.
- should-fix: none.
- later: the `GetSystemInfo` call at write time is outside the brief's kill-criteria list but is prescribed by decision 2 and is lock-free; no action. The `open` smoke mode and the real-page checks wait for napoleon J78 and W34 as the report says.
