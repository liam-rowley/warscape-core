# W3 report: jobs next survives an unset [jobs] ledgers

Written by the orchestrator from the build agent's hand-back: the build ran as a subagent, and the harness refuses a subagent's Write of a
report file, so the parent writes it. Same Claude-Session as the build.

## What was built
- `warscape/jobq.py` `brief_steps` (line 978): the ledger glob is now `sorted(root.glob(S.ledgers)) if S.ledgers else []`. With `[jobs] ledgers`
  at `''` (the core default) `glob` is never called, so `jobs next` no longer crashes with `Unacceptable pattern: ''`. Behaviour with a non-empty
  `ledgers` is unchanged.
- `tests/test_jobs.py`, class `Ledger`: a helper `_brief_steps_with(ledgers, files)` that sets `jv.S.ledgers`, restores it with `addCleanup`, and
  calls `jv.brief_steps(row('J4'), <temp dir>)`. Two tests: `test_brief_steps_with_ledgers_unset_does_not_glob` (asserts the "needs a brief" text
  and no "The brief must cover") and `test_brief_steps_with_ledgers_set_lists_owed_rows` (a `LEDGER*.md` file with a row naming J4; asserts the "The
  brief must cover LEDGER.md row 7: ..." line). Added `import tempfile`. The existing tests did not cover the non-empty-glob path in `brief_steps`,
  so the second case is new.
- `VERSION` 0.9.0 to 0.9.1, then 0.10.1 when `main` was merged in after W2 (0.10.0) merged first (2026-11-03).

## Evidence
- Fail-first (2026-11-03): the test was committed alone as `48b5ee9`, before any change to `jobq.py`, and run on the unfixed code; its failing
  output is quoted in that commit body: `ValueError: Unacceptable pattern: ''` from `jobq.py` line 978 in `brief_steps`, `Ran 3 tests, FAILED
  (errors=1)` (the ledgers-set test passed on the unfixed code). The fix is the separate commit `80fcf55`.
- Full suite, commit `80fcf55`, 2026-11-03: `Ran 223 tests in 49.796s`, `OK (skipped=1)`. Rerun by the orchestrator: `python3 -m unittest
  tests.test_jobs` OK.
- `python3 wsc.py jobs next`, commit `80fcf55`, 2026-11-03: no traceback; it printed the W3 brief steps.
- `python3 wsc.py gates --fast`, commit `80fcf55`, 2026-11-03: 12 ok, 1 warn (the `hooks` gate: this clone's `core.hooksPath` is an absolute path),
  0 failed. Python 3.15.2 locally, which also raises on `glob('')`.
- Glob sweep, `grep -n "glob(" -r warscape`, 2026-11-03, at `48b5ee9`:
  - `warscape/jobq.py:978`: `root.glob(S.ledgers)`, the bug, fixed.
  - `warscape/cli.py:19`: `.glob('*.py')`, fixed pattern, no change.
  - `warscape/gates.py:37`: `.glob('*.schema.json')`, fixed pattern, no change.
  - `warscape/registry.py:170` and `:184`: `.glob('*.json')`, fixed pattern, no change.
  - No `rglob(` calls. No second empty-setting case, so no extra fix or test.
- No CHANGELOG exists in the repo, so no changelog line was added.
- `origin/main` VERSION was 0.9.0 when re-checked just before the last commit (2026-11-03); W2 (0.10.0) has not merged, so 0.9.1.

## Deviations from the brief and why
- No `git stash`: the stash stack is shared with other sessions. Fail-first is shown by commit order instead (`48b5ee9` the red test with its
  failing output in the commit body, `80fcf55` the fix).
- The guard sits inside the comprehension instead of in a separate `paths` variable: the same one-line change; the `and S.ledgers` test after
  `is_file()` was removed as redundant.
- The branch was built before `brief/W3` (PR #21) merged and starts from that branch; `main` is merged in once the brief is on it, so the pull
  request shows only the job's files.

## Open questions
- None for the change itself. If W2 (0.10.0) merges first, this takes 0.10.1 when `main` is merged in.
