## Round 1 (2026-11-04, branch job/W16 at 1d4b0ca, merged with origin/main 6e743da)

**Verdict: merge.**

Machines: `python3 wsc.py gates` (full, after merging main) 12 ok, 3 warn (hooks path, `policy.yml.in` bootstrap trigger, skipped tests), 0 failed. CI on `1d4b0ca`: `proxy` and `harness-windows` green. `git diff --stat origin/main -- proxy/src` is empty.

Done by the reviewer on the branch (one item):
- `main` moved to 0.33.0 (W25), so the branch's `VERSION` 0.32.0 conflicted. The merge takes 0.34.0 (W28 and W29 also claim 0.34.0 on their open branches; the second to merge renumbers) and the two W16 doc headings in `docs/CONSUMING.md` and `docs/PROXY_HARNESS.md` now say 0.34.0. No new C number: W16 adds no decision.

Claims against evidence:
- The 14 console and 12 camera moved checks in the report match the lines deleted from `test_console.cpp` and `test_camera.cpp` in the diff, one for one, and the two "Consumer test files" carry each of them.
- The report's CI proxy log (run 41882301016) shows a real build id with no `WSP_BUILD_ID`, `test_null_adapter` listed as a game test, and `repro` and `self_hash` agreeing. That is the continuous proof of decision 6. The builder's local compile and rehearsal did not run (no Docker or compiler), as the brief allows.
- The byte compare with `WSP_BUILD_ID=x` was not run; same-size DLL, unchanged `proxy/src`, compile line and pins stand in for it. Accepted.

Risk-first reading: `build_id.py` (a wrong prefix would change an existing game's id) and the `build.sh --docker` mounts. The prefix is empty for flat and submodule layouts, so their ids are unchanged (the existing flat versus submodule case passes); the `:(top)` pathspec is right for the dirty check. The mount logic refuses unrelated roots and a tests folder outside the mount. `layout.proxy_tests` refuses a folder inside the adapter and the core's own `proxy/tests`. No findings.

Findings:
- blocker: none.
- should-fix: none.
- later: the consumer files were never compiled against napoleon's adapter; its pin-bump job covers that, and the report's open question 1 says what a failure would mean.
