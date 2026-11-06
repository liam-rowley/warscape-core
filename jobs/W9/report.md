# W9 report: acceptance and scene launches (host side done; PC steps 10-12 not run)

Built 2026-11-06 on `job/W9` (session daa219ea), semver level **minor** (row `semver=minor`; `VERSION` is not edited by jobs). Steps 1-9 (everything host-testable) are done; the PC part (steps 10-12) was **stopped at step 10 by a kill criterion**: the installed watcher is not the core's. B60 therefore stays open, with no new evidence, and nothing about the hist_nile flake is claimed fixed.

## What changed
- **Build id after the launch (B26/B31/H5)**: `Pc.launches` records `{pid, build, dll_sha256_logged, utc}` per launch (`Pc.read_launch_line`, pid-matched against the `proxy.log` load line, polls 10 s). `build_info(strict=True)` reads only that and raises without a line; acceptance labels a pass with it, a later launch on another build fails step `build_stable`, no line means `build_id: null` and no pass. `build_info()` keeps its old fallback for perf labels.
- **Launch retry as evidence (B60/H4)**: before the retry `Pc.launch` copies attempt 1's `proxy.log`, the adapter's `headless.status_file` and the job output to `<evidence_dir>/attempt_1/`, waits `ctl.launch.retry_settle_s` (default 10), and returns `attempts`. If both attempts end in one of the three pre-`on_virtual` texts it raises `HeadlessLaunchLost` (`cause: headless_launch_lost`; `Ctl.run` turns it into a `failed` result with that cause). `the proxy refused` twice stays a plain `RuntimeError`.
- **Flakes (H4)**: `classify()` gives `flake` only when the first failed step carries that cause and `exe_sha1` passed. `streak(..., max_flakes, watcher_sha)` skips flakes of the same build or `null` without counting them. Adapter `acceptance.max_flakes` (default 1, cap `MAX_FLAKES_CAP = 3`; `--max-flakes` may only lower). `cmd_run` loops over attempts until `--passes` passes, stops on a fail or when the allowance is spent. A cleanup failure now makes the pass fail (before, `passed` stayed true).
- **Evidence (H3), schema 2**: `schemas/acceptance_pass.schema.json`, `pass_problems`, `ledger_line_matches`, `acceptance.py check-pass FILE... [--ledger F]`; shot sha256/bytes per shot step; evidence block with exe, baseline, kit manifest, DLL (file and logged), watcher (installed and core) shas; ledger line gains `schema, watcher_sha, dll_sha256, kit_sha256, evidence_sha256, flakes_allowed`; pass file opened with mode `x`.
- **Run-id refusal (H5)** and **watcher preflight (H10)** in `cmd_run` before pass 1 (`run_id_problems`, `watcher_problems`; no override). The installed copy is opened `rb` only.
- **Staged saves (B51)**: row fields `save_file`/`save_sha256` (campaign only, in `scenarios.schema.json`), adapter block `ctl.saves {anchor, dir, ext}`, `ctl.stage_save` (sha check, temp file + `os.replace`, only `wsc_*` is removed), used by `v_scene` with a `finally`.
- **Lock (decision 10)**: W10 is merged; owner/session defaults already came from `who()`. The bare `touch` calls are now `PcEnv.touch()` = `touch <owner>`.

## Findings worth knowing
- **CRLF trap, fixed in the preflight**: `.gitattributes` makes `*.ps1` CRLF on disk (and in kits) and LF in git. Comparing `git show HEAD:harness/watcher.ps1` with the installed file byte for byte would refuse every correct install. Both sides are hashed with line endings normalised to LF (`lf()`), so `watcher_sha256` = sha256 of the LF content = the git blob's sha256. A consumer computes `watcher_sha` the same way (`git show <head>:core/harness/watcher.ps1 | sha256sum`). Test: `test_failing_fixture_crlf_in_the_working_tree_is_the_same_watcher_as_lf_in_git`.
- **The installed watcher on this PC is older than the core**: `C:\napoleon_remastered_pc\watcher\src\watcher.ps1` has `$Version = '1.4.0'`; `harness/watcher.ps1` at this core says `1.5.0`. This is step 10's stop condition, so no PC run happened, no lock was taken, and the game and the game folders were not touched. Napoleon's leftover `napoleon_remastered.ini` (10957 bytes, J32) is Liam's; no snapshot was made, so it did not matter, and it was neither read nor touched.

## Deviations from the brief
1. **Docs**: `docs/CONSUMING.md` is at 30688 bytes (cap 30 KB), so "Acceptance evidence" is in `docs/PROXY_HARNESS.md` and `docs/UPGRADING.md` instead (CONSUMING already points there for the harness).
2. **No VERSION bump and no BACKLOG edit**: the core's rules say jobs no longer edit `VERSION`, and `docs/BACKLOG.md` no longer exists (B26, B31, B51, B60 live only in this row, which Liam/the reviewer closes; B60 stays open: see above).
3. **`max_flakes` default is 1** (decision 5), so a game with no `acceptance.max_flakes` that hits a launch loss now continues instead of stopping; a game with no flakes behaves as before apart from the preflight, the shas and the run-id refusal.
4. `test_schema.py` counts 12 shipped schemas (was 11).

## What a consumer must change (rule 79; napoleon J75/J78)
Skip `result: flake` lines while at most `flakes_allowed` (never above 3) and of the line's build or null; require schema-2 evidence on counted passes (`evidence_sha256` = sha256 of the committed file, `check-pass`, unique `evidence` and `(run, pass)`, one `dll_sha256`, `baseline_sha256` = the committed baseline); replace the `$Version` regex by `watcher_sha` = sha256 of `core/harness/watcher.ps1` (LF content) at the branch head. Add `acceptance.max_flakes` (suggest 1) and, for staged rows, `ctl.saves` to the adapter. Pre-W9 lines carry no shas and stop counting for a pin past this job; `harness/` changes at this pin, so rule 79 asks for 20 passes on a PC whose installed watcher is the kit at that pin.

## Proof
- New host tests `tests/test_w9.py` (48): all pass; against `origin/main`'s code every one errors or fails (throwaway worktree, not pushed), including the fixtures for steps 1 (stale log), 3 (flake streak), 4 (run loop) and 7 (staged save cleared / leftover).
- `tests.test_acceptance`, `tests.test_ctl`, `tests.test_job_sh` unchanged and green; `python3 wsc.py gates --fast` green.

## Left for Liam / the orchestrator (PC, steps 10-12)
1. Update the installed watcher to this core's kit (send a harness kit, `job.sh update kit=<id>`); then the preflight can be run against the real copy.
2. Then B60: the 30-cycle `hist_dresden` -> `hist_nile` loop at gaps 0/5/15 s with the attempt evidence now kept, the staged-save sitting (J46's saves) and a 3-pass `acceptance.py run` into a scratch ledger plus `check-pass`. None of it was run.

## Open questions
1. **PC part (steps 10-12)**: update the installed watcher (1.4.0 on disk, 1.5.0 in the core) and have a PC session run steps 10-12, or accept this job for review with B60 open and the PC evidence as a follow-up row? Recommended: follow-up row (`needs_pc`), since the host side is independent and the new evidence copy will catch the next real flake anyway.
2. **`max_flakes` default**: kept at 1 per decision 5; 0 would leave a game without the key exactly as before. Recommended: keep 1.
