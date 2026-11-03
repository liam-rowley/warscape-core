## Round 1 (2026-11-03, branch job/W3 at 26deed7)

**Verdict: merge.**

Checked against the brief, not the report:
- Fix (`warscape/jobq.py:978`): the glob is skipped when `S.ledgers` is empty; the non-empty path is unchanged. The diff is one line.
- Tests (`tests/test_jobs.py`, class `Ledger`): one unset-ledgers case and one set-ledgers case with a ledger file; `S.ledgers` is restored with `addCleanup`.
  `tests.test_jobs`: 76 tests OK on the branch. Fail-first commit `48b5ee9` exists and precedes the fix, as the report says.
- `VERSION` 0.9.1 (origin/main holds 0.9.0, W2 not merged). No CHANGELOG exists. Nothing outside scope; `python3 wsc.py jobs next` prints without a traceback.
- Glob sweep: the report's list matches the code; no `rglob`, no other setting-driven pattern.
- `wsc gates --fast`: 12 ok, 1 warn (`hooks`, a local clone setting), 0 failed. CI on the branch head: gates (ubuntu, windows) and proxy green.
  harness-windows was still running on the newest head when I read it (the previous run was green); this change touches nothing under `harness/`.

Findings: no blocker, no should-fix.
- later: the report deviates from the brief by not using `git stash` (shared stash stack) and by putting the guard inside the comprehension. Both are named, justified and harmless.
