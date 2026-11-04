# W30 report: Yaw wrap in ctl readback, and failed ctl results named in the report

Written by the orchestrator from the builder subagent's hand-back (the harness refuses a subagent's write of a report file). The text is
the builder's own apart from this note. Branch `job/W30`, one commit (2d39a1d). VERSION 0.23.0, the number the brief names; W20 on
`job/W20` also took 0.23.0, so the orchestrator renumbers at merge.

## What was built
1. **Yaw wrap.**
   - `harness/ctl.py` gains `angle_diff(a, b) = abs((a - b + 180) % 360 - 180)`, with a result in [0, 180].
   - `pose_check` uses it for yaw only. Pitch stays a plain `abs` difference, so a wrap cannot hide a real pitch error; the docstring
     says so.
   - Asking for yaw 270 and reading back -90.00001 now passes. That was napoleon-remastered's false failure in
     `f2_stock/y_270_cam.json`.
   - The inline `abs((a - b + 180) % 360 - 180)` compares at lines 825 and 949 are untouched, as the brief says.
   - `grep` found no second copy in this repo. The "second view" the audit mentions is the consumer's pinned copy of `harness/ctl.py`.
     It gets the fix by bumping the pin, and since `ctl.py` is a harness input, that bump needs the consumer's acceptance passes.
2. **The failed-results report rule, off by default.**
   - `warscape/jobq.py` gains `failed_results_problems(jid, text, root, glob)` and a `RUN_CITE` regex.
   - It scans every path in the report text that matches `(?:[\w.-]+/)*runs/[\w.-]+` and resolves to a directory under the repo
     root; a `..` escape is ignored.
   - Inside each such folder it globs `[jobs] failed_results` and loads each JSON file. A file with a top-level `status` of `"failed"`
     must be named in the `## Deviations` section (up to the next `## `), by its path relative to the run folder or by its file name.
   - Unreadable and non-JSON files are skipped. A missing folder, an uncited folder or an empty glob gives no problems.
   - The message reads: `W30: report: failed ctl result runs/r1/raw/a/bad.json is not named in ## Deviations`.
   - `Settings` gains `failed_results` and `root`, filled in `configure_from`. `warscape/repo.py` has
     `DEFAULTS['jobs']['failed_results'] = ''`, and the `[jobs]` toml block in `docs/CONSUMING.md` documents the key.
   - The only call site is one line in `problems()`, right after the `report_problems` line. It runs only when `S.failed_results` is
     set and `S.root` is not None. `report_problems` is unchanged, which keeps the merge with W22's edits to `red_prs` and the
     readiness output clean.

## Evidence
- `tests/test_ctl.py` gains `test_yaw_wrap_any_representation` and `test_pitch_does_not_wrap`:
  - yaw 270 vs -90.00001 passes;
  - yaw 0 vs 359.9999 passes (`angle_diff` = 0.0001);
  - yaw 180 vs -180 passes;
  - yaw 90 vs -90 fails;
  - yaw 359 vs 1 with tolerance 3 passes;
  - pitch 80 vs -100 fails.
- `tests/test_jobs.py` gains the class `FailedResults`, with a temp-dir fixture: `runs/r1/raw/a/ok.json` (ok), `bad.json` (failed),
  `junk.json` (not JSON).
  - An unnamed failure gives exactly one problem, naming `bad.json` and `runs/r1`.
  - Naming the failure by file name or by relative path passes.
  - Naming it only in another section still fails.
  - A report that cites no folder, an empty glob and a missing folder each give no problems.
  - `problems()` runs the rule only when it is configured, and its message starts with `J1: report: failed ctl result`.
- `python3 -m unittest tests.test_jobs tests.test_ctl`: 136 tests OK (pytest is not installed on this PC).
- `python3 wsc.py gates` (full): 13 ok, 1 warn, 0 failed. The warn is `tests`: 582 passed and 5 skipped (one PrePush test needs POSIX
  sh and symlinks; four discovery Walk tests need capstone).
- `jobs check`: 35 rows, ok.
- The new tests were not run red before the fix: the code came first, then the tests. The old code's failure is the
  napoleon-remastered evidence above.

## Deviations from the brief, and why
- **No `docs/DECISIONS.md` row.** The brief made that step conditional on the file's convention for a W job. W21 added none; only W4,
  W11 and W13 added C rows, and those were design changes. This is a bug fix plus an off-by-default setting.
- **`S.root` added to `Settings`.** `problems()` has no `root` parameter and the brief keeps `report_problems` unchanged, while
  `configure_from` already receives `root`.
- **Tests ran under `python3 -m unittest`**, because pytest is not installed. The repo's own test command is unchanged.
- **Not red first** (see Evidence).

## Open questions
1. Should napoleon-remastered turn the rule on? Recommended: yes. Set `failed_results = "raw/**/*.json"` in its `wsc.toml` as part
   of J78 (audit train 1), with the pin bump, once this yaw fix is in, so the old false failures do not fire. The J8 and J24 reports
   are not re-checked unless they are edited.
2. Should the match be stricter (full relative path only)? Recommended: no. The point is that the failure is named, and its file name
   is enough.
