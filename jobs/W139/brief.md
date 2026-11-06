# W139: Windows host tests are close to the 1080 s limit

Phase 1 (the pipeline). Top priority: Liam, 2026-11-06. On 2026-11-06 `gates (windows-latest)` timed out at 1080 s on main at `193d091` with no test failing (run 42303468807, attempt 1, job 128187620070), the second such timeout on W45's code. A required check that goes red on a slow runner stalls every merge behind it and teaches people to rerun red. The row suggests sharing the real-judge fixtures. **Measured, that saves almost nothing:** the time is spawned processes run one after another, and the runner's own spread is larger than anything W45 added. So this job runs the test modules concurrently inside the gate, writes the timings into the log so the next person need not guess, and leaves `timeout_s` where it is.

Model: Opus, reason: the `tests` gate is on every branch's required path; a wrong concurrency or kill rule here hangs CI, hides a failed module or drops tests silently, on Windows process semantics (builds run on Opus).
Budget about 120 tool calls: about 10 reading, 25 for the red tests, 25 to build, 15 for the CI measurements, 15 for docs and gates, 10 for the report and the pull request, and 20 for one fix round. Comparable CI and gate jobs: W42 took 90 calls and W43 115, so the median plus a quarter. W45's 240 was four rounds on a new branch kind and is not a comparable.
Semver: minor
No DLL or harness input changes: `warscape/gates.py`, `warscape/repo.py`, `wsc.toml`, tests and docs only, so a game's pin bump to this tag carries no acceptance run for it (napoleon rule 79). `warscape/` and `wsc.toml` are `harness-windows` CI inputs, so that CI job reruns; nothing under `harness/` or `proxy/` changes.
Subagents: none; do the work in this session.
No PC: `needs_pc` is false. Host tests only; the game is never started.

## Start
1. `git pull`; `python3 wsc.py jobs next --id W139` and follow its mechanics. If this session's model is not Opus, stop and say so.
2. `python3 wsc.py gates --fast` for a baseline.
3. Read the row, `jobs/W45/review.md` (Should-fix 1, which raised this), `jobs/W42/report.md` (open question 1, the 20-minute limit), and `jobs/W43/report.md` deviation 7 (why `timeout_s` is 1080).

## Target facts (check each again before relying on it)
- `warscape/gates.py` `gate_tests`: one `python -m unittest discover -v -s <d> -t <d> -p test_*.py` per folder in `[tests] dirs`, output captured, one `timeout_s` per folder. `unittest_skips` parses the skip lines; `tests/test_checks.py` tests it.
- **The Windows logs hold no per-test timing.** The gate captures unittest's output and prints only the gate's total. On a timeout it prints `tests: timed out after 1080 s` and nothing about where the time went. That is why the fixture numbers below come from a local run.
- `warscape/repo.py` `DEFAULTS['tests']` is `{'dirs': ['tests'], 'timeout_s': 600}`; `wsc.toml` `[tests]` sets 1080 and `dirs = ["tests", "discovery/tests"]`. `[tests]` is shared with games, so any new key defaults to today's behaviour.
- `ci/gates.yml.in` renders `.github/workflows/gates.yml`: `gates-windows` has `timeout-minutes: 20`, and `gates (windows-latest)` is in `[ci] required_checks`. Neither changes in this job.
- `tests/_util.py` `core_source()` builds its throwaway core once **per test process**. One process per module rebuilds it in each module that calls it; measure that cost rather than assume it.
- `warscape/policy_base.py` `judge`: each `wsc policy` is a parent, a `git archive` extracted by `_untar`, and a `-I` child on a fresh tree that has no bytecode. This is the behaviour C24 relies on; it is not to change.
- Reading old CI: the `gates` run 42303468807 shows `cancelled` and no jobs because attempt 2 ran nothing. Read `actions/runs/<id>/attempts/1/jobs`. A whole-run `gh run rerun` hits the pass marker and skips Windows; `gh run rerun --job <job id>` really reruns it (W45 attempt 2).

### Measurements (2026-11-06; re-measure your own before and after, these are the reason, not the baseline)
**CI, the `tests` gate on `gates (windows-latest)`, 26 passing jobs and 3 failing from run 42201622245 to 42303468807, plus run 42304857584:**

| Tests in the tree | Jobs | Fastest | Median | Slowest |
| --- | --- | --- | --- | --- |
| 1383 | 9 | 489.9 s | 779.0 s | 907.4 s |
| 1401 | 5 | 838.5 s | 948.6 s | 971.9 s |
| 1543 to 1563 | 3 passed, 2 timed out | 758.9 s | 779.0 s of the passes | over 1080 s |

- Identical test counts vary by 1.85x, so the runner's spread is larger than W45's 160 tests. W45's code passed in 758.9 s (job 128195645261), 779.0 s and 812.7 s, and timed out twice. Median 783 s across all 26 passes.
- A safe target has to survive a runner 1.4x or more above median, and we have no ceiling on that. Ubuntu runs the same 1563 tests in about 180 s.
- `discovery/tests` is 112 tests in 0.5 s. All of the time is in `tests`.

**Local, one instrumented serial run of `tests` on this Windows PC (Python 3.15, 1451 tests, 876.9 s, no failures), wall time per class with subprocess time attributed.** Local serial time is close to CI's median, but no per-class figure from a runner exists yet (deliverable 1 gets it).

| Where the time went | Time | Share |
| --- | --- | --- |
| `python` children (278, about 1.2 s each; nearly all `wsc policy` judges) | 346 s | 39% |
| `bash` children (225, about 0.74 s each; `job.sh` and `pc_deploy` lock cases) | 167 s | 19% |
| `git commit`, `add`, `checkout`, `rev-parse` run by fixtures | 150 s | 17% |
| every `git clone` in the suite (60) | 12 s | 1.4% |
| `setUpClass` of `RealJudge`, `CoreMode`, `GrantJudge` | 2.5 s together | 0.3% |

| Fixture or class | Tests | Wall | Cost |
| --- | --- | --- | --- |
| `test_policy_base.CoreMode` | 39 | 159.7 s | 61 judges, 130 s; about 2.1 s each |
| `test_job_sh.JobSh` | 30 | 117.9 s | 110 bash spawns, 104 s |
| `test_proposals_judge.RealJudge` | 35 | 101.0 s | 66 judges, 84 s |
| `test_grant_round.GrantJudge` | 12 | 71.5 s | 24 judges, 58 s; one test alone 31 s |
| `test_policy_base.GameMode` | 5 | 42.6 s | 10 judges 22 s, 22 `git submodule` 18 s |
| `test_pc_deploy.Lock` | 12 | 31.3 s | 52 bash spawns, 27 s |

- Five modules are 70% of the time: `test_policy_base` 202 s, `test_job_sh` 129 s, `test_proposals_judge` 101 s, `test_audit` 95 s, `test_grant_round` 84 s.
- **The row's cause is not the cost.** `RealJudge` already builds one repo per class, and the clones and class fixtures together are under 2% of the run. Sharing them cannot move the total.
- Inside one judge call, measured under load: 19 git processes, about 45% in the base-tree child, about 25% in `_untar`, the rest git reads. A bare `wsc --help` start is about 150 ms warm and 250 ms without bytecode, so interpreter start-up is not the cause either.

**Parallel probe, the same suite as 4 concurrent `python -m unittest <modules>` processes pinned to 4 logical cores (Python 3.12): 464 s against 877 s, 1.9x, 0 failures, all 1451 tests ran.** One run only, on a PC with other work running, and modules dealt into 4 fixed bins: the bins predicted 219 s each and finished between 341 s and 463 s, so a fixed split wastes about a fifth. That is why decision 2 pulls from a queue.

## Decisions already made for this job
1. **Concurrency inside the gate, not a second CI job.** It keeps one required check name, needs no ruleset change, does not double the runner minutes, and helps Ubuntu, a local run and later games. Splitting the job would still leave each half exposed to the same slow runner.
2. **The unit is a module, pulled from a queue.** A pool of `[tests] workers` threads, each running one `python -m unittest discover -v -s <d> -t <d> -p <module>.py` at a time, so imports and process-global state (`os.chdir` in `tests/test_policy.py` and `tests/test_core_pin.py`) stay exactly as isolated as they need to be. Long modules start first: `[tests] first`, a list of module names, the rest in name order. No weights table to go stale.
3. **`[tests] workers` defaults to 1, which is today's single process and code path.** The core sets `workers = 4`. A game opts in after measuring.
4. **`timeout_s` stays 1080 and the job stays 20 minutes.** It remains one deadline per folder, across all workers.
5. **No test is weakened, skipped or moved to get under the line.** The judge tests stay on the real parent and child. `warscape/policy_base.py` does not change.
6. **The fixture sharing on the row is not built**, for the reason under Measurements. Say so in the report.

## Deliverables
1. **Timings in the log, first and alone.** The `tests` gate prints each folder's slowest modules with seconds, whatever the result, and the worker count and `os.cpu_count()` once. Check how an `ok` result prints its details: today only a `warn` or `error` shows them, and these lines must appear on a green run. Push this with `workers` at 1, and record that run's Windows per-module table in the report: it is the **before**, and the first per-module measurement from a runner.
2. **`gate_tests` with workers,** per decisions 2 to 4. Requirements, each with a test written red first in `tests/test_checks.py` or a new `tests/test_gate_tests.py`:
   - A module that fails, errors on import or exits non-zero fails the gate, and the module is named with its output tail, as today.
   - **The sum of the `Ran N tests` lines is the total, and a module reporting no result is an error, never a silent zero.** A test proves a module that dies mid-run does not pass. `discover -p <module>.py` must find what the single discover found: prove on this repo that the count is identical for `workers = 1` and `workers = 4` (neither `tests` nor `discovery/tests` has a package, check that still holds).
   - Skip lines still reach `unittest_skips` from every module.
   - On the deadline, every running module is killed with its whole process tree, the gate says which modules had not finished and which never started, and it returns. A child can leave `bash` or `git` grandchildren on Windows holding a pipe open, and then a read waits forever: write each module's output to a file rather than a pipe, and test the deadline with a real child that spawns a sleeping grandchild. There is no shared kill helper yet (`warscape/jobq.py` only sets process group flags): add one small function, stdlib only.
   - `workers = 1` keeps the single process and gives byte-for-byte the same result lines as today, apart from deliverable 1's.
3. **Config:** `workers` and `first` in `DEFAULTS['tests']` with a comment each, validated (an integer of at least 1, a list of strings), and `wsc.toml` set: `workers = 4`, `first` from the before table.
4. **A headroom warning, so this cannot creep back silently:** the gate warns when a folder took more than `[tests] warn_at` of `timeout_s` (default `0.75`, `0` is off). A warn, never a failure; a slow runner must not turn red because of this check.
5. **Measure the after:** the same tree on Windows at least 3 times (`gh run rerun --job <job id>`), every run's gate seconds, runner `cpu_count` and slowest modules in the report, next to the before. The core's Ubuntu leg once. Run the suite at `workers = 4` locally 3 times too: each must pass, as a collision between modules would show up here as a flake.
6. **Docs:** the `[tests]` keys in the doc that owns config (`docs/CONSUMING.md` or `docs/CONSUMING_OPTIONS.md`, whichever owns the others), a section in `docs/UPGRADING.md`. Update the comment on `timeout_s` in `wsc.toml`, and `tests/` conventions if a shared fixed temp path turns up: `tests/test_acceptance.py` uses one, safe only while one module owns it.

**Acceptance:** median of the Windows runs under 540 s, half of `timeout_s`; slowest under 720 s; test count identical to serial; no test changed but the new ones. Estimate from the probe: about 420 s. A runner 1.4x the median then lands near 600 s.

## Out of scope
- Raising `timeout_s` or `timeout-minutes`.
- Splitting `gates-windows` into two jobs, or any change to `[ci] required_checks`.
- Changing `warscape/policy_base.py`, or rewriting judge tests as in-process calls.
- Parallelism within a module or class (`CoreMode` alone is the floor of the run, about 160 s).
- Removing the overlap between `gates-windows` and `harness-windows` (open question 3).
- `[tests] workers` in any game.

## Open questions
1. **Should `workers` apply to a local `wsc gates` as well as CI?** recommended: yes, one key and one behaviour, as a local gate at about 8 minutes instead of 15 helps every reviewer; default after: 2026-11-13.
2. **Does napoleon opt in?** recommended: not in this job; leave the default at its pin bump and let it set `workers` once deliverable 1's timings show its own numbers; default after: 2026-11-13.
3. **`test_job_sh` runs on both `gates-windows` and `harness-windows` (about 129 s locally). Drop it from one?** recommended: no, their input sets differ, so a change could reach only one of the two; with workers it is no longer on the critical path; default after: 2026-11-13.
4. **If the acceptance line is missed but the median is under 720 s, is that a pass?** recommended: yes for this job, reported as a deviation with a `later` row for the judge cost, as main stops going red; default after: 2026-11-13. Tag: risk.

## Kill criteria
- Deliverable 1's run shows `cpu_count` below 4 on `windows-latest`: stop, report it, and do not set `workers` above that count without Liam's word.
- The Windows median of deliverable 5 is above 720 s: stop, commit, report the per-module table; do not raise `timeout_s` and do not start splitting the job.
- The total test count at `workers = 4` differs from `workers = 1` in any run: stop and report it until the difference is explained.
- A test fails at `workers = 4` and passes at `workers = 1` twice, with no cause found after two attempts: stop, name the two modules, and move them to run alone only if a one-line `[tests]` rule does it; otherwise report.
- The deadline test leaves a live process or the gate does not return within 30 s of the deadline: stop and report; do not merge a gate that can hang CI.
- An existing assertion in `tests/test_checks.py` or any judge test has to change: stop and report which and why.
- Over about 120 tool calls: stop, commit, report what is left.

## Finish
Report in `jobs/W139/report.md` with `## What was built`, `## Evidence` (the tests red then green with counts; the before and after Windows gate seconds with run and job ids; the first per-module table from a runner; `cpu_count`; the three local `workers = 4` runs; the deadline test's result), `## Deviations from the brief and why`, `## Open questions`. Say whether the local measurements above held on a runner, and which did not.
`python3 wsc.py jobs usage W139 --write`
`wsc reg set jobs W139 status=review report=jobs/W139/report.md` (`python3 wsc.py`)
Push `job/W139`, open the draft pull request, and stop: an independent reviewer merges (C18); the release workflow tags (C27).

## Registry gaps
None.
