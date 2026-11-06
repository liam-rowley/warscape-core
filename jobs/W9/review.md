# W9 review

## Round 2 (2026-11-06, branch job/W9 at c31077a)

**Verdict: merge.**

All eleven findings of round 1 are answered in `## Fix round 1`, and I checked each against the code. Nothing is left at blocker or should-fix level. The host side is proved; the PC part is not, and that is W127, not this job. No code was changed in this round.

### What was run
- **CI on the head, run 42205388934 (c31077a), completed green**: `gates (ubuntu-latest)`, `gates (windows-latest)` and `harness-windows` passed, `proxy` skipped (no `proxy/` input changed). As round 1 asked, I read the new Windows run rather than the check names: `changes` set `gates_windows=true` and `harness=true` with no marker hit, `gates (windows-latest)` ran 1374 host tests with 5 skipped (none W9's: the POSIX hook test and four capstone tests), and `harness-windows` ran 60 unit and 35 integration tests, 0 failed. The `policy` run 42205391892 is skipped because the pull request is a draft, which is expected before this verdict.
- **Local, this PC, Windows, at c31077a**: `wsc gates` 14 ok, 2 warn, 0 failed (1374 host tests, the same 5 skips; the `hooks` warn is this worktree's absolute `core.hooksPath`). `tests.test_w9 tests.test_acceptance tests.test_ctl`: 141 tests, OK.
- **`wsc policy --branch job/W9 --base origin/main` before this round**: refused only for the verdict and the row not being `done`.
- **Against the latest origin/main (0ac0bf6, refetched after the gates finished)**: the branch is one commit behind. That commit (#153) adds only `registries/jobs/W127.json`, no file W9 changes; `git merge-tree` is clean (tree d2f1f5a). W127 `depends_on` W9, so the order is right. I did not merge main into the branch: the squash carries it, and the row cannot affect W9's code.
- **Mutation check of the fixes**: 15 mutants of round 1's items 1 to 5 and 8 to 10, broken one at a time in a scratch copy, 13 caught. Item 5's mode `w` is among the caught, which confirms the fix's own claim. The two survivors are not worth a round: `attempt.json` is written but no test reads it, and `stage_save`'s default `say` going back to stdout survives because both callers pass their own, so production never reaches the default.
- **`check-pass` by hand**: a missing `--ledger` prints the refusal and exits 1 in this core, with no adapter (items 1 and 10).

### Round 1's findings
1. Missing ledger: fixed, `acceptance.py` `cmd_check_pass`. Seen failing closed by hand and held by a test.
2. A pass that proves nothing: fixed as round 1 specified, `pass_proof_problems`, and `run_pass` fails an unhashable shot. Every clause is held by a test (mutants 2a to 2f). See Later for what round 1 did not list.
3. Attempt evidence: fixed, next free `attempt_<k>`, and attempt 2 of a lost launch is kept too (`ctl.py` `Pc.launch`).
4. `reset` on a staged row: fixed, `v_reset` stages around `_reset`, and the settle runs inside the stage. Not run in the game: W127.
5. The pass-file test: fixed, it now goes through `cmd_run`.
6. Backlog rows: the report's correction is right; W98, W99, W100 and W65 are on main and say what it says they do. They stay open until W9 merges (see Later).
7. PC row: W127 is on main (#153), `needs_pc: true`, depends on W9, and carries round 1's open question about a loaded save and `unlink`. The brief's open question 1 has no answer from Liam, and the brief says the recommended answer stands when none comes, so this is not a reason to hold the merge. The step-10 stop was a kill criterion, so the unmet PC proof is a reported stop, not a missed deliverable.
8. Pass label: fixed, `launches[0]`.
9. stdout: fixed for `scene`, which now returns `staged_notes`. See Later for `reset`.
10. Adapter: fixed, resolved only for `run` and `measure`.
11. Header: fixed.

**Also read, which round 1 did not list as covered.** Decision 7's self-hash: W24 is merged, and `SELF_HASH_RE` (`ctl.py:54`) is the exact format of `proxy/src/dllmain.cpp:78` on main. Decision 2's `save_file` root: `ctl.py` `ROOT` is `layout.game_root`, so the path is under the game repo in a consumer too.

### Blockers
None.

### Should-fix
None.

### Later
All in **W128** (`plan/W128-check-pass-consistency`). None of these can be reached by a file `cmd_run` writes, which is why they do not hold the merge.
1. **`pass_problems` does not check that a pass agrees with itself.** `harness/acceptance.py:240`. To see it: a schema-2 doc with `result: pass` and every field of round 1's list returns `[]` with `steps: {}`, with a step `{ok: false}`, with `dll_sha256_logged` differing from `dll_sha256`, with `watcher_sha256` differing from `watcher_kit_sha256`, and with a launch of another build. `cmd_run` cannot write these (`record` clears `passed`, and `build_checks` fails the two launch cases), so it takes a hand-edited file, but a hand-edited ledger line is how H5 began and `check-pass` is the consumer's gate. A `steps` list raises `AttributeError` instead of a problem line; that fails closed.
2. **`v_reset` drops the leftover note.** `harness/ctl.py:1068` passes `say=lambda t: None`, so a leftover is overwritten and not said on this path (decision 2). `v_scene` loses its note too when `_scene` raises. Return it as `staged_notes`, as `v_scene` does.
3. **Close W98, W99 and W100** with this job as evidence once it is on main. Nothing else records that step (W127 covers W65).

## Round 1 (2026-11-06, branch job/W9 at 51bbdad)

**Verdict: merge after fixes.**

The host-side design holds and the machines are green, but `check-pass`, the check a consumer's gate will call, passes evidence it should refuse, and the attempt evidence that B60 depends on is overwritten. No code was changed in this round.

### What was run
- **CI on the head, run 42201622245 (51bbdad), completed green**: `gates (ubuntu-latest)`, `gates (windows-latest)` and `harness-windows` all passed; `proxy` skipped because no `proxy/` input changed.
- **Windows covered the code, not only the last commit.** The head commit is paperwork, but `changes` diffs against the merge base with main (ae802cb), so it set `gates_windows=true` and `harness=true`, and no pass marker skipped either set. Both jobs checked out the full head tree, which holds caae61e and 937a30c. Those two commits had no CI run of their own (the only other run on the branch is 27506b4, a main commit), and none is needed. `tests/test_w9.py` runs on Windows only through `gates (windows-latest)` (1367 host tests passed, 5 skipped, none of the skips W9's; the tests gate discovers `test_*.py`, and the count is not broken down by file). `harness-windows` does not run that file.
- **Local, this PC, Windows, at 51bbdad**: `wsc gates` 14 ok, 2 warn, 0 failed (1367 host tests passed, the same 5 skips; the `hooks` warn is this worktree's absolute `core.hooksPath`). `tests.test_w9 tests.test_acceptance tests.test_ctl`: 134 tests, OK.
- **`wsc policy --branch job/W9 --base origin/main`**: refused only for the missing review and the row not being `done`, as expected before a verdict.
- **Against the latest origin/main (b4aceec, refetched before this verdict)**: the branch is one commit behind. That commit (#151) changes only `jobs/W94/brief.md` and `registries/jobs/W94.json`; `git merge-tree` is clean, so it does not affect W9's code. A later merge round must check this again.
- **Real data, read-only**: the two J24 pass files' failure texts both fit `LOST_RX` inside the 300-character tail. `dllmain.cpp:113` fits `LAUNCH_PID_RE`, and `log.cpp` opens the log with `FILE_SHARE_READ`, so reading it during a launch is safe.
- **Report claims confirmed**: the installed watcher is 1.4.0 and the core's is 1.5.0, so the stop at step 10 was right. The CRLF finding is also right: the installed `C:\napoleon_remastered_pc\watcher\src\watcher.ps1` with LF endings is git blob e6e359e, which is in the core's history (`git log --find-object`, first listed at W10's cbcf7ab), so the LF identity works on real installed bytes.
- **Mutation check of `tests/test_w9.py`**: 15 behaviours broken one at a time in a scratch copy, 14 caught. The survivor is should-fix 5. This stands in for the report's failing-fixture claim, which cites no run or output; that every new test fails on main's code proves little, because they import names main does not have.
- **Risk-first reading**: `Pc.launch` and its retry, `stage_save` (it writes to and deletes from the player's save folder), and the evidence path through `cmd_run`, `classify` and `streak`. Decisions 3 to 6, 8 and 9 are followed apart from the findings below. Decision 10: `touch <owner>` matches `job.sh`.

### Blockers
None in the code. CI is green on the head.

### Should-fix
1. **`check-pass` passes when the ledger is missing.** `harness/acceptance.py:653` sets `lines = None` when `--ledger` names no file, and the ledger check is then skipped. To see it: `check-pass pass_01.json --ledger typo.jsonl` prints `ok` and exits 0. A wrong path in a consumer's gate turns off the line-to-file check (H3). Refuse a named ledger that does not exist.
2. **`pass_problems` accepts a pass that proves nothing.** `harness/acceptance.py:214` checks only that the keys exist. A doc with `result: pass`, `shots: {}`, `launches: []` and every sha null returns `[]`, and so does one with `result: pass, passed: false`. H3 is the reason this check exists. A `pass` needs `passed: true`, non-null exe, baseline, DLL and watcher shas, at least one launch, and one shot entry per shot step. The last is also unguarded at the source: `run_pass` records a shot step as ok with no hash when the file is unreadable (`acceptance.py:285-288`).
3. **Attempt evidence is overwritten.** `harness/ctl.py:477` always writes `attempt_<n>`. Outside a run the folder is `<state>/_scratch/<owner>/attempt_1`, so each retried launch replaces the last: two calls leave only `second loss`. Step 11's B60 loop runs through `ctl.py scene` and must keep each lost launch, so it would keep only the latest. Two retries in one pass collide the same way. Goal 3 of the brief is this exact loss. Give each launch its own folder.
4. **`reset` on a staged row targets a save that is not there.** `harness/ctl.py:1057` returns `campaign:wsc_<id>`, but only `v_scene` stages. `ctl reset <row>` sends `reset campaign:wsc_c1 240` with the save folder empty. `run_pass` reaches this when a staged campaign row is the baseline's first step (`acceptance.py:297`). Stage in `v_reset` too, or refuse.
5. **`test_a_pass_file_is_never_overwritten` does not test `cmd_run`.** `tests/test_w9.py:311-314` opens the file in mode `x` itself, so it passes whatever `cmd_run` does: changing `cmd_run` to mode `w` survives all of `test_w9`. Pre-create the pass file and assert that its bytes are unchanged.
6. **The report's account of the backlog rows is wrong, and those rows stay open.** Deviation 2 says B26, B31, B51 and B60 "live only in this row". They are `later` rows on main: W98 (B26), W99 (B31), W100 (B51) and W65 (B60). Correct the report, and say in it how each row closes. A job branch cannot change them, so that takes a `plan/` pull request.
7. **The PC part has no row.** Stopping at step 10 was correct and is reported, but steps 10 to 12 exist only as prose under "Left for Liam", and the brief's proof section is unmet: none of this has run on a PC. Open question 1 recommends a follow-up row and none exists. W65 cannot carry the work as it stands: it says `needs_pc: false` and still asks for a retry inside the verb, which decision 3 ruled out. File the `needs_pc` row (or rewrite W65) on a `plan/` branch and name it in the report. Liam's answer to open question 1 is still outstanding; his decision on the row belongs with that.
8. **The pass label uses the wrong launch.** Decision 1 says a pass takes its `build_id` from `launches[0]`; `harness/ctl.py:520` reads `launches[-1]`, and the report does not name the deviation. With launches [A, B] the failed pass is labelled B. A passing run is unaffected, since `build_stable` requires one build. Use `launches[0]`, or report why not.
9. **`stage_save` prints to stdout.** `say=print` (`harness/ctl.py:160`) puts `ctl: a leftover ...` ahead of the JSON result that `ctl.py` prints (`ctl.py:1171`), so `ctl.py scene` stdout stops being JSON when a leftover exists. `keep_attempt_evidence` already uses stderr. Better still, put the leftover in the result, so it is kept as evidence.
10. **`check-pass` needs an adapter it never uses.** `harness/acceptance.py:762` resolves the harness adapter before parsing, so `check-pass` stops with `LayoutError` in any repo that does not have exactly one adapter, this core included. `streak` has the same trouble already; W9 adds a pure check that a gate calls. Resolve the adapter only for the verbs that use it.
11. **The header says "byte for byte"** (`harness/acceptance.py:20`), which contradicts the LF rule `lf()` applies and the report describes. Say it compares content with LF endings.

### Later
None.

### For the fix session
Items 1 to 5 and 8 to 11 are on this branch. Items 6 and 7 also need a `plan/` branch. A code fix changes `harness/`, so the next round must read the new CI run on Windows and compare against origin/main again. Not checked here because it needs a PC: whether the game keeps a loaded save open, which would make the `dst.unlink()` in `stage_save`'s `finally` raise and replace the scene's result. Add that to the PC row's staged-save sitting.
