## Round 1 (2026-11-04, branch job/W15 at 795d948)

**Verdict: merge.**

Reviewer: a fresh session. The report was written by the orchestrating session from the builder's hand-back (same session id as the builder), so its claims were checked against the branch, not taken on trust.

- Machines: `wsc gates` (full) run locally: 12 ok, 3 warn, 0 failed. The warns are this worktree's hooks path, the existing ci_render note, and `tests` (737 passed, 5 skipped, as the report says). CI on the head: gates (ubuntu) pass, changes pass; gates (windows) and proxy were still running when this was written. `wsc policy` refused only for the missing review and the row not `done`, which this commit fixes. It notes that the branch changes `registry.py`, `tools.py`, `find.py`, `reg.py` and `wsc.toml`; none of these is a policy rule file.
- Claims against the branch: they match.
  - `wsc reg remove tools wsc.reg` refuses with rc 1 and `git status` stays clean (run here).
  - The `exe_strings.find` split keeps its output.
  - `last_uses`, `cite_pattern`, `done_job_date`, `Registry.remove`, `refs_to`, and the verb's referrers and backstop are present as described.
  - The deviations are named in the report and are sound: the `.bak` and `/` citation rule, `--in exe_strings` searching plain words, and `--missing` paths resolved to the repo root.
- Risk-first reading: `reg remove` (it deletes row files) and its refusal rules. Nothing is saved before every check passes, an unknown id raises before any change, and the backstop ignores only the target registry's canonical-form and stale-view lines. Second, `find` in a repo with no table: no extra output, and the exit code is unchanged.
- Not verified by me: the scratch napoleon numbers (57 done jobs, 59 of 119 tools with a derived date). They need a napoleon clone with local edits.

### later
- The `warscape/repo.py` `DEFAULTS` comment still says retirement waits until the queue stamps (report open question 1). Reword it the next time `repo.py` is touched.
- VERSION 0.31.0: `origin/main` says 0.30.0 at review time. If another job lands first, the second merges `main` and takes the next number.
