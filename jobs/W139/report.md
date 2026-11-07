# W139 report: Windows host tests are close to the 1080 s limit

The `tests` gate now runs the test modules from a queue, four at a time on the core, and logs where the time went. On `gates (windows-latest)` the gate took 873.4 s before and 511.1 s, 405.5 s and 464.7 s after on one tree: median 464.7 s against the 540 s line, slowest 511.1 s against 720 s, 1591 tests, no failure. `timeout_s` stays 1080 and the job stays 20 minutes. The fixture sharing the row suggested was not built, as the measurements in the brief show it cannot move the total.

Usage: 66 tool calls; models: opus; 1 session, counted by hand, about, 2026-11-07

## What was built
- `warscape/gates.py`:
  - **Timings on every run:** a `timing: workers <n>, cpu_count <n>` line and each folder's ten slowest modules. At `workers = 1` they come from `unittest --durations 0` inside the one process; `split_durations` takes its block out, so a failure's tail stays the traceback.
  - **`_pool`, `_run_module`, `_parallel`:** `[tests] workers` threads pull modules from one queue, longest first. Each module is one `discover -p <module>.py` with stdout and stderr in files, under one deadline per folder.
  - **The count:** the total is the sum of each module's `Ran N tests` line, read from stderr only, so a test's own print is no result. No such line is an error, at exit 0 too.
  - **`kill_tree`:** `taskkill /F /T` on Windows, `killpg` on POSIX, bounded so it cannot hang. At the deadline the gate names what had not finished and what never started. Ctrl+C also kills the running trees.
  - **`test_modules`:** what one discover loads, including packages, excluding plain subfolders and names that are not identifiers.
  - **Headroom:** a `warn` when a folder took more than `[tests] warn_at` of `timeout_s`, never a failure.
- `warscape/repo.py`: `workers` (1), `first` (`[]`) and `warn_at` (0.75) in `DEFAULTS['tests']`, each validated.
- `wsc.toml`: `workers = 4`, `first` from the before table, the `timeout_s` comment.
- `tests/test_gate_tests.py`: 28 new tests, real `unittest` children on throwaway folders. No existing test changed.
- `docs/CONSUMING_OPTIONS.md` "The `tests` gate" and a section in `docs/UPGRADING.md`. `docs/CONSUMING.md` has 75 bytes left under its cap, so the keys went to the options doc. There is no `tests/` conventions doc, so the note on fixed temp paths is in that section too.

## Evidence
**Tests red, then green.** Deliverable 1: 5 of 5 failed before the code (`failures=2, errors=3`), all 5 pass after. Deliverables 2 to 4: the final file against the code before them (`48693f2`), the three deadline tests left out, gave 25 run, `FAILED (failures=11, errors=6)`, each failing subtest counted once. After: 28 of 28 on Python 3.12 and 3.15. A few of my own test mistakes showed up on the way (a wrong count, a stale `.pyc` from rewriting a module within the second, an assertion that ignored the headroom line) and were fixed in the tests, not the gate. My first red run of the deadline tests did not fail, it hung, see below.

**The deadline test.** A real child spawning a real grandchild that writes a heartbeat file, four modules, two workers, `timeout_s = 4`, on this PC and on both CI legs. The gate returned, named `test_a_hang, test_b_hang` as not finished and `test_c_late, test_d_late` as never started, and both heartbeats stopped. The test fails if the gate takes more than 30 s past the deadline; all 28 tests together take about 16 s here. A process listing on this PC after the runs found none of the test's processes left. On the old code the same test hung for good: `subprocess.run` timed out, killed the child, then waited on the pipe the grandchild held. I stopped that run by hand (see "Open questions" 1).

**Windows, `gates (windows-latest)`, the `tests` gate.** The runner's `cpu_count` is 4, so the kill criterion does not fire.

| | Run, attempt | Job | Commit | Workers | Gate seconds | Tests |
| --- | --- | --- | --- | --- | --- | --- |
| Before | 42311869400 | 128215065048 | `48693f2` | 1 | 873.4 | 1568 |
| After | 42313598068, 1 | 128220772356 | `83f61bf` | 4 | 511.1 | 1591 |
| After | 42313598068, 2 | 128231393935 | `83f61bf` | 4 | 405.5 | 1591 |
| After | 42313598068, 3 | 128233986586 | `83f61bf` | 4 | 464.7 | 1591 |

Ubuntu, one run each: 157.1 s (job 128215004049) before, 73.8 s (job 128220727465) after, the same counts, `cpu_count` 4.

**The first per-module table from a runner, and the after.** The before column is summed test time, the after columns each process's wall time under load, so the two are not comparable row by row.

| Module | Before, 1 worker | After 1 | After 2 | After 3 |
| --- | --- | --- | --- | --- |
| `test_policy_base` | 229.8 | 509.7 | 405.0 | 464.0 |
| `test_proposals_judge` | 106.1 | 242.5 | 193.4 | 240.4 |
| `test_audit` | 92.0 | 221.1 | 183.9 | 194.1 |
| `test_grant_round` | 89.3 | 241.1 | 194.6 | 223.1 |
| `test_job_sh` | 78.4 | 115.1 | 100.5 | 122.0 |
| `test_jobs` | 35.8 | 61.6 | 57.0 | 59.8 |
| `test_fixture_game` | 30.7 | 101.0 | 88.4 | 90.9 |
| `test_pc_deploy` | 30.7 | 58.5 | 49.0 | 62.1 |
| `test_moved_tools` | 27.8 | 56.3 | 47.4 | 59.2 |
| `test_policy` | 13.5 | under 56.3 | under 47.4 | under 47.8 |
| `test_core_bump` | under 13.5 | 62.5 | 51.7 | 47.8 |

**`test_policy_base` is now the whole run:** in all three the gate's seconds equal that module's within 1.4 s. The other 43 modules fit beside it on three workers. More workers cannot help, and the long modules about double under load on 4 cores. Further gains have to come from that one module, which the brief puts out of scope.

**Test count.** `workers = 4` gave 1591 on Windows, Ubuntu and locally. One discover loads the same on that tree, on Python 3.12: 1479 in `tests`, 112 in `discovery/tests`. The before's 1568 plus the 23 tests added since is 1591. Neither folder has a package. `test_this_repo_queues_exactly_what_one_discover_loads` pins the module list, on every run.

**Locally at `workers = 4`,** Python 3.12, this PC with `cpu_count` 16, 2026-11-06, at the workers code with an earlier order of `first`: 360.9 s, 362.4 s, 352.7 s, each 1591 passed and 5 skipped, no flake. The 5 skips are the known ones.

**Did the brief's local measurements hold on a runner?**
- Held: serial total (877 s here, 873.4 s there); the five long modules are the same five, 595.6 s of 873.4 s, 68% against 70%; the probe's order of gain (1.9x; 1.9x at the median here).
- Did not hold: the probe's estimate of about 420 s (median 464.7 s). `test_job_sh` is cheaper on a runner, 78.4 s against 129 s. The floor is not `CoreMode`'s 160 s: `test_policy_base` runs as one process, and 405 s to 510 s under load.
- Two target facts were not quite right: an `ok` result does print details, the verb only hides them under `-q`, so only the gate had to change. And `wsc.toml` is a `proxy` CI input as well as a `harness-windows` one, see Deviations.

**Gates and CI.** Fast gates before each push: 15 ok, 0 failed. Run 42313598068: `gates (ubuntu-latest)` and `harness-windows` success on attempt 1, `proxy` on attempt 4 (Deviations 1), and the run's conclusion is success.

## Deviations from the brief and why
1. **`proxy` ran, which the brief did not expect, and timed out once.** `wsc.toml` matches `[ci.inputs] proxy`, so this job's config change ran it. On attempt 1 its apt toolchain step took 28 minutes 22 seconds of the job's 30, and the job was cancelled in `build.sh`. No code of this job is in that step. Rerun on the same commit (attempt 4, job 128236961685), the step took 13 seconds and the job passed in 6 minutes 14 seconds, so the run is green with no change.
2. **`first` lists nine modules, not five,** as the before table shows the next four are worth starting early. It changes only the order.
3. **`workers = 1` keeps `subprocess.run`,** as decision 3 says, so it keeps the pipe hang above. See open question 1.
4. **A module with no tests fails the gate above 1 worker,** where one process passes over it (`unittest` exits 5). The brief did not name this case; a silent zero seemed the wrong side to err on. No module of the core is affected, and a game opting in would see it by name. The doc says so.
5. **A failed module's tail is shorter when several fail** (40 lines shared, at least 8 each), and all failed modules are named in the summary line, because the verb prints only 60 detail lines. At `workers = 1` nothing changes.
6. **`--durations` needs Python 3.12** at `workers = 1` too, the core's stated version. A game's tests on an older Python would fail at its pin bump. `docs/UPGRADING.md` says so.

## Open questions
1. **Should `workers = 1` get the file output and tree kill too?** Today a hung test with a grandchild on Windows hangs the gate until the CI job's limit, for any game at the default. The brief kept that path as it was, so I did. recommended: yes, a small later job, by moving `_serial` onto `_run_module`; default after: 2026-11-14. It has no row yet; I did not add one on this branch.
2. **Brief questions 1 to 3 took their recommended defaults:** `workers` applies to a local `wsc gates`; napoleon does not opt in here; `test_job_sh` stays on both Windows jobs. Question 4 took its default too, and was not needed, as the acceptance line was met.
3. **The proxy job's limit.** A slow apt mirror used 28 of its 30 minutes. Not this job's to change; worth a look if it happens again.
