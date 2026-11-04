## Round 1 (2026-11-04, branch job/W12 at ed10db8)

**Verdict: merge.**

Checked: `python3 wsc.py gates` on the branch: 14 ok, 1 warn (5 existing skips), 0 failed. CI on `ed10db8`: gates (ubuntu, windows), proxy and harness-windows green;
the only red is the `ready_for_review` policy run, which has no verdict by design. I merged `origin/main` (a6d4872, briefs only) into the branch: no conflict.

Read in depth: `warscape/trailer.py`, `verbs/policy.py`, `.githooks/commit-msg` (the hook runs on every commit and blocks work if wrong), then `jobq.views_problems`, the policy hint and the `repo.py` key checks.
The hook mirrors `pre-push`'s finder, skips merges and is opt-in. Trailers are read with `git interpret-trailers --parse`, and the builder's agreement test (11 messages against `%(trailers)`) satisfies the kill criterion.
The B49 check has one implementation (`jobq.check`), used by both the verb and the gate. Every brief deliverable is present; the report names its deviations (extra reference shapes, `ALLOW` with counts, `tests/test_extends.py`, `shader_catalog.py:721`).

### Blocker
none.

### Should-fix
none.

### Later
- `run_refs` flags a test class such as `tests/test_ctl.PcLaunch` (an upper-case "extension"; report open question 2). Fix napoleon's README at the pin bump, or tighten the token rule then.
- Version order: `VERSION` is 0.24.0 while `job/W20` holds 0.23.0 and is unmerged. If W20 merges later it must take the next free number and merge main; the same goes for the C23 row.
- The commit-msg hook also fires on rebase and cherry-pick commits that carry no trailer; `--no-verify` covers it. Mention it in CONSUMING.md if it bites.
