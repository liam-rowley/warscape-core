# W30: Yaw wrap in ctl readback, and failed ctl results named in the report

Model: Sonnet, reason: none needed (Sonnet is the default). One pure-function fix with host tests, and one small text-file rule in the job queue; no
reverse engineering, no PC. Budget about 40 tool calls.

## Goal
Audit 2026-11-03 R1 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, row 12 of its job table). `harness/ctl.py` `pose_check` compares the yaw
read back with the yaw asked as `min(d, 360 - d) if d <= 360 else d`. Asking for yaw 270 and reading back -90.00001 gives `d = 360.00001`, so the
`else` keeps it and the pose is `failed` with a 0.0002 px fit. Evidence (a consumer's run, cited only as evidence): napoleon-remastered
`harness/runs/20261103_j24pc/raw/f2_stock/y_270_cam.json` has `status: failed`, `reason: readback outside tolerance`, asked yaw 270, got -90.0, rms_px 0.0002.
Two jobs explained it away in their reports and two reviews missed it. Two halves:
1. **Fix the wrap** so equal angles compare equal in any representation.
2. **A jobs check rule** (off by default, a game switches it on): every result with `status` `failed` in a run folder that a report cites must be named
   in that report's `## Deviations` section, so a failure cannot be explained away in prose elsewhere or not at all.

## What exists
- `harness/ctl.py:146-160` `pose_check(expected, got, tol)`: the only place that compares a readback angle by tolerance (lines 154-156). The audit said "one
  line, in both core views"; there is no second copy in this repo (checked: `grep -nE "360|% ?360" harness warscape`). The other angle compares are already
  correct and stay: `ctl.py:825` (unit facing change) and `ctl.py:949` (order facing) use `abs((a - b + 180) % 360 - 180)`; `harness/acceptance.py:418` builds a
  wrapped yaw for the pose it sends. Say in the report that the "second view" is the consumer's pinned copy of this file (it gets the fix by bumping the pin).
- `tests/test_ctl.py` ~line 160: existing `pose_check` tests (1 vs 359 passes).
- `warscape/jobq.py`: `report_problems(jid, text)` (about line 130) checks a report's first heading and that `## Deviations` and `## Open questions`
  exist; it is called per report at about line 230 (`errs += [f'{jid}: report: {e}' ...]`). Settings are in `class Settings` / `configure_from` from the
  `[jobs]` table; defaults live in `warscape/repo.py` `DEFAULTS['jobs']`; documented in `docs/CONSUMING.md` ("The job pipeline", the `[jobs]` toml block).
- No code today reads run folders from a report. Reports cite evidence as repo-relative paths in prose (for example W2's report names a consumer's
  `proxy/runs/20261102_j30pc/`); there is no structured citation.

## Decisions already made
- **Wrap yaw only; pitch stays a plain `abs` difference.** Pitch is bounded to +-90, so a wrap can only hide a real error; yaw is a circle. (The
  old code wrapped both; no existing test depends on pitch wrapping. If one does, keep that test's expectation and say so.)
- **One shared helper**: add `angle_diff(a, b)` in `harness/ctl.py` returning `abs((a - b + 180) % 360 - 180)` and use it in `pose_check`; leave 825 and
  949 alone (inline, working, out of scope). Result lies in [0, 180]; 180 vs -180 gives 0 and 0 vs 359.9999 gives 0.0001.
- **How a report cites a run folder**: any path in the report text matching `(?:[\w.-]+/)*runs/[\w.-]+` that resolves to a directory under the repo root.
  No new syntax for authors. The rule scans files in that directory by a game-set glob.
- **Config, off by default**: new `[jobs]` key `failed_results = ""` (a glob relative to the cited run folder, for example `raw/**/*.json`; `""` = rule off,
  so the plain queue and every existing consumer are unchanged). Add it to `DEFAULTS['jobs']` and the `[jobs]` block in `docs/CONSUMING.md`.
- **What counts as a failed result**: a JSON file matched by the glob whose top-level `status` equals `"failed"`. Unreadable or non-JSON matches are skipped
  silently (a run folder holds many files).
- **What "named" means**: the report's `## Deviations` section (up to the next `## ` heading) contains the result's path relative to the run folder, or its
  file name. Matching on the file name is deliberate: a report that writes `y_270_cam.json` or `raw/f2_stock/y_270_cam.json` both pass; a bare "some failed"
  does not. The problem text names the report, the run folder and each unnamed file: `W30: report: failed ctl result runs/x/raw/a.json is not named in ## Deviations`.
- Missing/uncited folders are not errors (a report that cites none passes). Reports in `legacy_rounds`-style exemption are not needed: the rule is off until a game sets the key.

## Steps
1. Add `angle_diff` and use it for yaw in `pose_check`; pitch uses plain `abs`. Update the docstring in one line.
2. Tests in `tests/test_ctl.py` (host, no game): `angle_diff`/`pose_check` yaw cases below, plus pitch not wrapped (expected 80 vs -100 is a failure).
3. In `warscape/jobq.py` add `failed_results_problems(jid, text, root, glob)` returning problem strings per the decisions above (pure apart from reading
   files under `root`), add the `failed_results` setting to `Settings`/`configure_from`/`DEFAULTS['jobs']`, and call it where `report_problems` is called when the
   glob is non-empty. `ctx.root` is the repo root; follow how the existing call site gets what it needs and keep `report_problems` itself unchanged.
4. Tests in `tests/test_jobs.py` using a temp-dir fixture (see how existing jobs tests build `jobs/<id>/report.md`): a run folder `runs/r1/raw/a/ok.json` (`status: ok`)
   and `runs/r1/raw/a/bad.json` (`status: failed`).
5. Docs: `docs/CONSUMING.md` documents the key (one bullet) and that the pin bump of `harness/ctl.py` needs the consumer's acceptance passes (a harness input).
   Append a `proposed` row `C<next>` to `docs/DECISIONS.md` only if the file's convention for a W job requires one (read its tail first); otherwise skip.
6. Bump `VERSION` 0.22.0 to 0.23.0 (a new setting and a behaviour fix; earlier W jobs set the new version in the job's own commit, for example W21 set 0.22.0),
   and put "VERSION 0.23.0" in the report as W21's did. Run the repo's gates the way `CLAUDE.md` says (at least `python3 wsc.py gates` and the pytest files
   above; `python3 wsc.py jobs check`).
7. Write `jobs/W30/report.md` (sections: what was built, `## Deviations`, `## Open questions`, `## Finish`) and finish as `CLAUDE.md` and
   `docs/REVIEW.md` say (`reg set jobs W30 status=review report=jobs/W30/report.md`, push, draft PR). Do not merge.

## Proof
- `pose_check` host tests (default tolerance 0.5, yaw tolerance as the test sets): expected 270 vs got -90.00001 passes; 0 vs 359.9999 passes; 180 vs -180
  passes; 90 vs -90 fails (diff 180); 359 vs 1 with tolerance 3 passes (the existing case); a pitch 80 vs -100 fails.
- Fixture run folder test: a report citing `runs/r1` with `failed_results = "raw/**/*.json"` and `bad.json` absent from Deviations gives exactly one
  problem naming `bad.json`; naming it (bare name or relative path) in `## Deviations` gives none; naming it only in another section still fails; a report
  citing no run folder gives none; with the key empty the same report gives none.
- Full pytest for the touched files and the gates pass; paste the counts in the report.

## Open questions (only where Liam must choose)
1. **Turn the rule on in napoleon-remastered?** The consumer sets `failed_results = "raw/**/*.json"` (its ctl results live under `raw/<scene>/*.json`). That
   is a consumer change that rides J78 (audit train 1), not this job. Recommended: yes, with the pin bump, after the yaw fix is in so old false failures
   do not fire; the old J8 and J24 reports are exempt by never being re-checked unless they are edited.
2. **Should the match be stricter (full relative path only)?** Recommended: no, file name is enough; the point is that the failure is named, not the exact spelling.

## Kill criteria
- The report rule needs more than the one setting, one function in `warscape/jobq.py` and its call site (for example a new gate stage or a registry change): stop, commit what is done, and report; do not widen.
- More than about 40 tool calls: stop, commit, and report what is left.

## Finish
Report in `jobs/W30/report.md` (what was built, tests red then green, the version taken, deviations, open questions), then
`wsc reg set jobs W30 status=review report=jobs/W30/report.md` (`python3 wsc.py`). Push `job/W30`, open the draft pull request, and stop: an
independent reviewer merges (C18); Liam tags.
