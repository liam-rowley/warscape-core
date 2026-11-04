## Round 1 (2026-11-04, branch job/W22 at 23bbe4d)

**Verdict: merge.**

Checked: `wsc gates` 13 ok / 1 warn (the known skips) / 0 failed, run locally on the branch; branch CI run 41796206422 all green with `main_health` and `notify` skipped on the branch push (as the brief requires); no change under `proxy/`.

Risk-first reading: `warscape/ci_render.py` `block_changes` (it decides whether a slow set runs on main; the diff step now uses `base=''` only for `refs/heads/main`, branch logic untouched, `if`/`pass_marker`/`fetch_cache`/`policy`/`notify` text pinned by a new test) and `warscape/ci_main.py` (the only code that writes issues). The idempotency is sound: the whole mark must start the body (`gates` never matches `gates (windows-latest)`), one comment per (run, attempt), a stale run (main's tip differs from the run's head) does nothing, every explainable gh failure returns 0, and the job is `continue-on-error`, not a required check.

### Blocker
none.

### Should-fix
none.

### Later
- The issue calls and the real main-push route were not run live (recorded-answer tests only; the report says so). The first push to main after the merge is the proof: (a) `proxy` and `harness-windows` run and write markers, (b) a docs-only push after it skips both, (c) `main_health` is green or skipped and `gh issue list` shows no "CI is red on main" issue.
- VERSION 0.23.0 is also claimed by W20 and W30; the second to merge takes the next number and merges main.
