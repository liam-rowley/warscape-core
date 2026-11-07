# W139 review

## Round 1 (2026-11-07, branch job/W139 at 901d5f4)

**Verdict: merge.**

The gate does what the brief asked, and the numbers hold. No blocker and no should-fix. Five `later` findings, one of which (1) should land before any game sets `workers` above 1. This round changes nothing outside the job folder and the row.

### What I ran
- **Base:** `origin/main` is `ac59251`, the branch's merge base, read again just before this verdict. The branch is level with main; no test merge was needed.
- **Machines:** `python3 wsc.py gates` on this head, on this PC (2026-11-07): 14 ok, 2 warn, 0 failed, 1591 passed, 5 skipped, 368.7 s at `workers = 4`. The `hooks` warn is this worktree's absolute `core.hooksPath`, nothing of the job's. `policy` before this round refused only for the missing review and the row.
- **CI on `901d5f4`:** run 42319241744 (push) is success, with `changes` and `gates (ubuntu-latest)` really run (job 128239466973: 1591 tests, 82.2 s). `gates (windows-latest)`, `proxy` and `harness-windows` were skipped on markers, and `policy` (run 42319258987) was skipped as the pull request is a draft. Neither skip is counted as a pass here: the markers are checked below, and `policy` runs on the head this round pushes.
- **Pass markers:** `changes` logged a cache hit on each set, naming run 42313598068 at `83f61bf`. Each marker was written by a job that succeeded, and its tree matches:

| Set | Tree | Attempt | Job | Conclusion |
| --- | --- | --- | --- | --- |
| `gates_windows` | `1597f9cf...` | 1 | 128220772356 | success |
| `harness` | `b1fc5987...` | 1 | 128220772349 | success |
| `proxy` | `fdea5e6e...` | 4 | 128236961685 | success |

  `git diff 83f61bf 901d5f4` touches only `jobs/W139/report.md` and `registries/jobs/W139.json`, which match none of the three `[ci.inputs]` patterns, so the skips are sound.

### The CI numbers, from the job logs
| | Job | Commit | Workers | Gate seconds | Tests |
| --- | --- | --- | --- | --- | --- |
| Before | 128215065048 | `48693f2` | 1 | 873.4 | 1568 |
| After 1 | 128220772356 | `83f61bf` | 4 | 511.1 | 1591 |
| After 2 | 128231393935 | `83f61bf` | 4 | 405.5 | 1591 |
| After 3 | 128233986586 | `83f61bf` | 4 | 464.7 | 1591 |

All match the report, and `cpu_count` is 4 on each. Median 464.7 s (line 540), slowest 511.1 s (line 720). The three are real runs: attempt 4's Windows job 128237010286 has attempt 3's exact times, so it is a carried copy and not a fourth run. Ubuntu 157.1 s and 73.8 s also match.

### Risk-first reading: `warscape/gates.py`, the gate on every branch's required path
**Can four workers hide a failure?** Only a contrived one (finding 2). `gate_tests` is red whenever `det` is non-empty, and the module loop leaves it empty only if every module was queued, finished unkilled, printed a `Ran` line and exited 0. I ran modules that exit 0 mid-test, segfault, and fail at import: each was red and named. A segfault was not in the builder's tests.

**Can it drop a module or change the count?** On this repo, no: one discover loads 1479 + 112 = 1591 here, 44 + 9 modules, the same as CI at `workers = 4`, and `test_this_repo_queues_exactly_what_one_discover_loads` pins the list on every run. For a game, narrowly yes: finding 1.

**Shared state between modules.**
- Each module is its own process, so env, cwd and `os.chdir` are private.
- Fixed temp paths: only `SHOT` in `tests/test_acceptance.py`, owned by that one module. `warscape/` has none, and `harness/` and `proxy/tools/` use `mktemp`.
- Ports: no test binds one.
- Locks: `game.lock` is per-test, in throwaway folders.
- The tree: this run started in a fresh worktree, and afterwards `git status --ignored` showed only `_scratch/` and `__pycache__`, none of it in `tests/fixture_game` or `proxy/tests/null_game`, the folders tests copy from. `core_source` copies tracked files only.
- Nine clean `workers = 4` runs so far: 3 Windows, 2 Ubuntu, 3 the builder's local ones, 1 mine. Load-sensitive tests are finding 4.

**A timeout or crashed worker.** A hung module with a live grandchild at `workers = 4` and `timeout_s = 3`: red, named, back in 3.2 s. Output goes to files, so no pipe can hold the gate; `_join` and the bounded `kill_tree` bound the rest. A module popped from the queue with no result counts as never started, which is red. A worker's exception is a failed module.

**`workers = 1` unchanged.** Run side by side against `origin/main`'s `warscape/` on six fixtures (pass, fail, skip, import error, empty, `os._exit(0)`): level, summary and details are identical once the `timing:` and `slowest` lines are set aside. On a timeout the new gate adds the headroom line, as deliverable 4 asks. The claim holds, and so do the old path's two faults, which are not regressions:
- **The Windows hang:** with `timeout_s = 2` and a grandchild living 12 s, old and new both returned at 12.1 s and 12.2 s. It lasts as long as the grandchild, red at the end or at the CI job's limit, never green. The report's "hung for good" means a grandchild that never exits.
- **A silent zero:** `os._exit(0)` in a test gives `ok, 0 host tests passed` at `workers = 1`, on main too. The report does not mention this one.

**Games at the default.** `load_config` merges a partial `[tests]` and keeps the three defaults, so nothing crashes. `napoleon-remastered/wsc.toml` has no `[tests]` table, and `empire-remastered` has no `wsc.toml`. What a game does see: two or more log lines on every run, and a `warn` over 75% of `timeout_s`. Exit codes and test results do not change, and `warn` fails nothing. `--durations` needs Python 3.12, which is the core's stated version and what both games' CI pins; below it the gate is red, not quiet. `docs/UPGRADING.md` states all of this, so "no change" means no change of result.

### The brief
All six deliverables are present, and the kill criteria did not fire. `policy_base.py`, `timeout_s`, `timeout-minutes` and `required_checks` are unchanged, no existing test changed, and no workflow changed. The report names deviations 1 to 6 with reasons; I accept them. Deviation 4 (a module with no tests fails above 1 worker) is the right side to err on.

### Findings
**Blocker:** none. **Should-fix:** none.

**Later** (filed as one `later` row through a `plan/` pull request):
1. `warscape/gates.py:443`: **a capitalised module is dropped silently above 1 worker, on Windows.** `test_modules` compares names case-sensitively, but discover's `fnmatch` does not on Windows. To see it: `test_a.py` and `Test_b.py` give `2 host tests passed` at `workers = 1` and `1` at `workers = 4`. Not a blocker because no game opts in and the core's pin test would go red on such a file, but a game has no such guard. Fix it before a game sets `workers` above 1: match with `fnmatch.fnmatch(f, 'test_*.py')`.
2. `warscape/gates.py:540`: **any stderr line counts as the module's result.** The report's "a test's own print is no result" holds for stdout only: a test writing `Ran 99 tests in 0.1s` to stderr and then calling `os._exit(0)` gave `ok, 100 host tests passed`. It takes a deliberate exit 0, and the old gate passes that case too. Fix: require unittest's closing `OK` or `FAILED` line.
3. `warscape/gates.py:508`: **`_serial` keeps the hang and the silent zero** (above). The builder's open question 1 recommends moving it onto `_run_module`; I agree, and it should close both, but a game's output then changes, so it needs its own host tests. Decision 3 of the brief kept the path, so this is not a fault of this job.
4. **Load-sensitive tests.** `test_job_sh.py:304` and `:316` allow 6 s and 5 s, and two `Deadline` tests in `tests/test_gate_tests.py` need a child up within `timeout_s = 4`. The long modules about double under load on a 4-core runner. None has failed in nine runs, but a slow runner is what this job exists for; widen them if one ever flakes.
5. `warscape/gates.py:502` (read, not run): **a Ctrl+C can leave one child.** A worker between `popleft` and `live[mod] = p` starts a child after the kill loop, and its non-daemon thread then waits to the deadline. Local runs only.

`test_policy_base` is now the whole Windows run, 405 s to 510 s, so any further gain has to come from that one module, as the report says. A runner 1.4x the median lands near 650 s, well under 1080 s.
