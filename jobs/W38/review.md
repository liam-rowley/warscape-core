## Round 1 (2026-11-04, branch job/W38 at 20bfcf1)

**Verdict: merge.**

Checked: CI on the head (all 9 passed or skipped), `wsc gates --fast` ok, `tests.test_pc_deploy` 40 OK locally, the watcher, capture-test and restore-test diffs read against the brief, and the quoted run ids opened.

- Watcher: `Headless-Refused` is read in both places, pid-matched or write-time-matched (1 s slack), 1.4.1; matches brief decision 1. Unit cases pin both orders; red-before run 41863085797 shows the integration case alone is not a regression test, as the report says.
- Repeat run 41868892959: both refused integration cases passed 10/10 (log read). The job is red only because of the restore loop's stderr issue the report names; the 50-run proof for that is local and was not re-run by me (one run here passed).
- Restore-wait test and capture stress check changed as the brief decided; `pc_deploy.py` and `capture.h` untouched.
- Kill-Game fix is out of the brief's scope but named in the report with its cause and a failing-then-passing unit case; accepted.

Findings:
- should-fix: none.
- later: the throwaway `scratch/W38-repeat` branch (pushed with --no-verify) should be deleted after merge, as the report says; the `ci_render` warning about the policy template is pre-existing.
