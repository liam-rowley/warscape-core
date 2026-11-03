# W3: jobs next survives an unset [jobs] ledgers

Model: Sonnet. Budget about 25 tool calls; at the cap, stop and report.

## What
`python3 wsc.py jobs next` crashes with `wsc jobs: Unacceptable pattern: ''` whenever it prints brief steps. `brief_steps` in `warscape/jobq.py`
(about line 978) evaluates `sorted(root.glob(S.ledgers))` before its `and S.ledgers` test, and the core leaves `[jobs] ledgers` at `''`
(`warscape/repo.py` DEFAULTS, "'' = off"), so Python 3.12+ raises `ValueError` on `glob('')`. napoleon-remastered sets `ledgers`, so it never hits it.
1. Guard the glob: when `S.ledgers` is empty, do not call `glob` at all (compute the guard first, e.g. `paths = sorted(root.glob(S.ledgers)) if S.ledgers
   else []`). Behaviour with a non-empty `ledgers` is unchanged.
2. A host test in `tests/test_jobs.py` (the `Ledger` class is the place) that fails on today's code and passes after: set `jv.S.ledgers = ''`
   (restore it in `tearDown`/`addCleanup`, `S` is module state) and call `jv.brief_steps(row(...), <a temp dir as Path>)`; assert it returns the
   "needs a brief" text and does not raise. Confirm it fails first: `git stash` the fix or run the test before editing `jobq.py`, and say in the report
   that you did. Add a second case with a non-empty `ledgers` glob and a ledger file in the temp dir if the existing tests do not already cover that path.
3. Sweep `warscape/` for any other `glob(` (and `rglob(`) whose pattern comes from a setting that can be `''`: `grep -n "glob(" -r warscape`. Today's
   hits are `jobq.py:978` and fixed-pattern calls (`cli.py`, `gates.py`, `registry.py`), which need no change; list what you checked in the report, and
   fix any real second case the same way with its own test line.
4. `VERSION`: the next patch after whatever `main` holds when this merges. `main` holds 0.9.0 today and W2 (queued) is bringing 0.10.0; if W2 has
   merged by the time you start, `git pull` and use 0.10.1, otherwise 0.9.1. Re-check `origin/main`'s `VERSION` just before the last commit; if it moved,
   take the next patch of the new value. Tags stay Liam's. The repo keeps no CHANGELOG (README only mentions the version in the `core_pin` text), so
   add no changelog line; say in the report that none exists.

## Must not
- No other behaviour change in `jobq.py`; do not touch the `ledgers` default, `waiting_rules` or napoleon's wiring.
- No new dependencies, no verb changes, nothing under `proxy/` or `harness/`.
- Do not mark W3 `done`; the reviewer does.

## Kill criteria
- The new test does not fail on the unfixed code (the crash is not what this brief says): stop and report what `jobs next` actually does.
- The sweep finds a second empty-setting bug that needs more than a one-line guard, or the fix needs a change to the `[jobs]` settings schema: stop and
  report; do not widen the job.
- `python3 wsc.py gates --fast` still fails after 3 attempts for a cause in this change: stop and report.

## Finish
Run `python3 -m unittest discover -s tests` (or the repo's test command in `wsc.toml`), `python3 wsc.py jobs next` (it must print a brief or "nothing
ready" without a traceback) and `python3 wsc.py gates --fast`. Report in `jobs/W3/report.md` (what was built, the fail-first evidence, the grep
list, deviations, open questions), then `wsc reg set jobs W3 status=review report=jobs/W3/report.md` (`python3 wsc.py`), and push `job/W3`.
