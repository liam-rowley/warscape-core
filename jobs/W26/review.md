## Round 1 (2026-11-04, branch job/W26 at dd382d3)

**Verdict: merge.**

Checked: CI green on the head (gates ubuntu and windows, harness-windows); local run of tests.test_jobs and tests.test_worktrees: 126 OK; the branch is
up to date with origin/main (0.33.0, last decision C28), so VERSION 0.34.0 and C29 are the next free numbers. `policy` refuses only for the missing review
and the row not being done, which this round supplies.

Risk-first reading: the claim push, the autopilot's defer rules and the worktree prune.
- Claim cannot be won twice: `jobq.claim_argv` pushes `origin/main` with `--force-with-lease=refs/heads/<b>:` (empty expected value = create-only, the
  server's compare-and-swap). An existing ref gives `=` or `! [rejected]`, both read as "taken"; `*` is the only claim; any other output is exit 1 with
  nothing claimed. No `--force`. The report's deviation from a plain push (which fast-forwards an old empty claim) is justified and has a red fixture.
- Never deletes a remote branch: no code path runs a delete push; the stale-claim line only prints `git push origin --delete <b>` as text for the owner.
- `--prune` / `prune_tick` only run `git worktree prune`, which removes registrations whose folder is missing and skips locked ones. It never removes a
  folder, and a branch's commits stay in the repository, so no unpushed commits are lost. Merged worktrees are only reported. A dry run does nothing.
- Autopilot: review waits for green, fix waits while CI is running or none, one `needs_pc` row at a time, a deferral is logged once per (head, reason)
  and never sets started.

Findings:
- later: a worktree whose folder is on an unmounted drive also counts as "missing" and its registration is pruned (branch and commits survive;
  `git worktree repair` restores it). `git worktree lock` protects such a worktree.
- later: the stale-claim age is the head commit date (report open question 2); fine as worded ("or less").
