# W8 report: Harness host tests in the core and its own Git Bash finder

The moved tools' Python host tests now run in the core against the null game or temp folders (B17): `tests/test_pc_deploy.py` (33),
`tests/test_ctl.py` (53), `tests/test_acceptance.py` (19), `tests/test_saves.py` (13) and `tests/test_job_sh.py` (15), ported from the first
consumer's `tests/` at `6cbb9e9` (napoleon-remastered `main`; the seven source files are unchanged since the brief's `562dde6`). The core has its
own Git Bash finder (B18), `warscape/gitbash.py`, which `harness/ctl.py` `bash()` imports from its core root instead of loading the game's
`tools/verbs/setup.py`; `tests/test_gitbash.py` (14) covers both. Host tests in `tests/`: 240 before, 387 after (with `discovery/tests`: 349
before, 496 after). VERSION 0.19.0 (`job/W17` holds 0.18.0).

## What was built
- **`warscape/gitbash.py`** (library module, no tool row): `bash_kind`, `git_bash`, `bash_for_tests` ported with their injectable parameters
  (`nt`, `which`, `git_exec_path`, `isfile`, `find`, plus `environ`), standard library only. The `%LOCALAPPDATA%/Git` probe is gone;
  `%LOCALAPPDATA%/Programs/Git` stays. The skip reason is "no Git Bash found (looked in: ...); the WSL bash on PATH is never used" and lists
  the folders it probed. Two additions: `roots()` (the probed install folders, so the reason and the tests share them) and `bash_or_skip(test)`
  (see CI below).
- **`harness/ctl.py` `bash()`** imports `warscape.gitbash` through `_OWN` (inserted on `sys.path` only if missing), keeps the plain-`bash`
  fallback and the module-level cache; the docstring no longer names the game's verb. `acceptance.py` is unchanged.
- **`tests/test_moved_tools.py`**: its own `git_bash()` is gone (`gitbash.bash_or_skip`), the docstring says the fuller tests run here, and
  `NoGameNames` scans the six new test files (`PORTED`; it also fails if one of them is not tracked). No `ALLOW` entry.
- **CI** (`ci/gates.yml.in`, `.github/workflows/gates.yml` re-rendered): the harness-windows step "moved tools host tests that run bash" runs
  `tests.test_moved_tools tests.test_job_sh tests.test_gitbash` with `WSC_REQUIRE_BASH=1` (timeout 3 to 8 min). The brief expected the job.sh cases
  to skip in the `gates` job on windows-latest (no `python3`); on CI they ran there too (`python3` was on PATH), so nothing skips.
- **Docs**: `docs/CONSUMING.md` "The proxy, the harness and the save tools" says the tests run here from 0.19.0 and that a game's setup verb
  imports `warscape.gitbash` (`from warscape.gitbash import git_bash, bash_kind, bash_for_tests`); B17 and B18 are out of `docs/BACKLOG.md`.

### Every napoleon test, and where it went (source `6cbb9e9`)
| Napoleon file (tests) | In the core | Ported (same assertions) | Adapted | Left in the game, and why |
|---|---|---|---|---|
| `test_pc_deploy.py` (33) | `tests/test_pc_deploy.py` (33) | 33 | names only: exe, config file and mod folder from the null identity (`Game.exe`, `nullgame.ini`, `nullgame`), the second title's exe is the null adapter's `Other.exe`, the fake `tasklist` names `Game.exe`; every case runs on a temp copy of the null game with a `lua/` folder and a `kit_packs` builder added (the null game has neither, so the kit's dev side would go untested), `pd.ROOT` and `build_dev_pack.ROOT` patched to it | none |
| `test_ctl.py` (52) | `tests/test_ctl.py` (53) | 50 (on the neutral fixture data below) | `Rule78` (2): the rule over fixture rows, a temp preset folder and the core's `harness/acceptance.py`; scenario ids kept, maps (`NULL_MP_Flatlands`, `null_campaign`), the campaign target and the adapter (`nullgame`) neutral; `PcLaunch` sky cases use `nullgame` paths | the scan of the game's `registries/scenarios.jsonl` and `proxy/<game>/lua/battles/*.txt` (its data) |
| `test_acceptance.py` (19) | `tests/test_acceptance.py` (19) | 19 | the 2 `Baseline` cases that call `main()`: `acc.ROOT` points at the null game, because `main()` resolves the harness adapter before parsing arguments and the core alone has none (test drift, not a regression) | none |
| `test_saves.py` (20) | `tests/test_saves.py` (13) | `Codec` (7), `Diff` (3), the `Tree` builder | new `Walker` (3): the generic half of `NapoleonMap` (record paths, array items, @N values, `grep_id` finding both ends and skipping `CAI_INTERFACE`) over a neutral synthetic save | `test_napoleon_noise_file_parses` (the game's `noise.txt`), `NapoleonMap` (3: `save_map.py`), `Recipes` (3), `Staging` (3): the game's `saves/<game>/` |
| `test_job_sh.py` (15) | `tests/test_job_sh.py` (15) | 14 | the default-adapter root (same assertions, null names) (`/c/nullgame_pc/watcher` through `$WSP_GAME_ROOT` = the null game); the registered `dev.ctl_dir` default read from a temp repo whose default is a temp folder (124 on every OS) instead of the null game's `C:\nullgame_pc\ctl`, which a run on a PC creates and leaves behind | none |
| `test_setup.py` `test_bash_kind`, `test_bash_for_tests`; `test_proxy_host.py` `GitBash` (4) | `tests/test_gitbash.py` (14) | `test_bash_kind`, the 4 `GitBash` cases | `test_bash_for_tests` (the reason names no game command) | the rest of `test_setup.py` and `test_proxy_host.py` test the game's verb and CI classifier |

New in `tests/test_gitbash.py`: the install folders without `%LOCALAPPDATA%/Git`, this host's bash is Git's, `bash_or_skip` (3), and `CtlBash` (3:
a game root without `tools/` still gets the finder's bash; a game's `tools/verbs/setup.py` is never executed; nothing found is `bash`, cached).

No ported test failed on `main`: everything above is test drift (paths, names, the core having no adapter of its own); no tool regressed and
no tool under `harness/`, `proxy/` or `saves/` changed except `ctl.bash()`.

## Evidence
- `python3 wsc.py gates` on this PC (Windows 11, Python 3.15 as `python3`): 13 ok, 1 warn, 0 failed in 203 s at `45c48c5` (the warn: the `tests` gate's 5 skips, none of them new: the POSIX-sh hook test and four capstone cases). The `tests` gate ran 496 tests in 202 s. The first run failed one existing test, `test_checks.StdlibOnly`: the ported files imported `build_dev_pack` and the `esf_*` modules by statement, which that scan counts as third-party; they now load through `importlib.import_module` (`45c48c5`).
- `python3 wsc.py policy --branch job/W8 --base origin/main`: refused only for the missing report, review and `done` row.
- CI on `job/W8`: green at `839933a` (run 41719502224) and at `508a09b` (run 41720732399): `gates` on ubuntu-latest and
  windows-latest, `proxy`, `harness-windows`. The `tests` gate: 496 tests, 30 s on ubuntu-latest (4 capstone skips), 84 s on windows-latest
  (those plus the POSIX-sh hook test), far inside 600 s. harness-windows ran `tests.test_moved_tools tests.test_job_sh tests.test_gitbash`:
  34 tests in 44 s, OK with no skip (under `WSC_REQUIRE_BASH` a skip would fail).
- Run times on this PC: the new test files take about 95 s together, 90 s of them `test_job_sh.py` (bash process start-up on Windows); the
  whole `tests` gate runs in about 200 s, inside `[tests] timeout_s` (600 s).
- Failing fixtures, each a scratch commit in a throwaway worktree of this branch (not pushed), the matching test red, then green after the revert:
  - `pc_deploy.py` uninstall appends one byte to a restored file: `test_pc_deploy.Deploy.test_foreign_file_backed_up_and_restored` failed.
  - `job.sh` exits 0 on a refused job: `test_job_sh.JobSh.test_exit_codes` failed.
  - `ctl.py` `make_result` lets `ok` through without a check: `test_ctl.Contract.test_row77_ok_without_a_check_becomes_failed` failed.
  - `acceptance.py` `load_time_ok` ignores the tolerance: `test_acceptance.Compare.test_load_time_tolerance` failed.
  - `esf_map.py` `grep_id` walks into the skipped records: `test_saves.Walker.test_grep_id_finds_both_ends_outside_the_skipped_records` failed.
  - `ctl.py` `bash()` back to the pre-W8 code: all three `test_gitbash.CtlBash` cases failed (`'bash' != 'found-bash'`, `'game-bash' != 'found-bash'`, cache).

## Deviations from the brief and why
- **`bash_or_skip` and `WSC_REQUIRE_BASH`** (not in the brief): the acceptance asks that harness-windows run `test_job_sh` "with a real Git Bash
  and no skip", but `unittest` passes a skipped run, so a lost Git Bash or `python3` would have passed silently. The helper skips as before
  everywhere else and fails under the variable, which only that step sets. `test_moved_tools.GameLock` uses it too.
- **`roots()`** probes `%LOCALAPPDATA%/Programs/Git` only when `LOCALAPPDATA` is set; the original appended `/Programs/Git` (a relative path)
  when it was not.
- **`test_ctl.py` has 53 tests**, one more than the source: a failing fixture for the rule-78 scan, since the scan now runs over fixtures.
- **`test_saves.py` `Walker`** replaces the generic part of `NapoleonMap` rather than leaving `Tree` unused.
- **`test_job_sh.py` registered-default case** uses a temp folder: the null game's default is a drive path, and the first two local runs created
  `C:\nullgame_pc\ctl` (holding two `.cmd.expired` files) on this PC. The folder is still there: removing it was refused by the
  harness's safety check, so Liam may delete `C:\nullgame_pc` by hand.
- The harness-windows step's timeout rose from 3 to 8 minutes for the 15 job.sh cases.
- `test_lock_is_an_exclusive_create` reads the racing processes with `communicate()` instead of `wait()`, which closes their pipes (the
  source left `ResourceWarning`s).
- `main` was merged in twice (W7 at 0.16.0, then the W19 and W20 briefs), never rebased.
- Built on Opus by Liam's choice (the brief names Sonnet).
- **Report and row:** the build ran as a subagent, which cannot write report files, so the orchestrator wrote this report from the builder's
  text and set the row to review (same Claude-Session as the build).

## Open questions
1. **Napoleon follow-up** (proposed as a napoleon `needs_brief` row; nothing in napoleon was touched): after the pin bump to 0.19.0, make
   `tools/verbs/setup.py` import `warscape.gitbash` (`git_bash`, `bash_kind`, `bash_for_tests`; `bash_or_skip` for its own tests), point its
   bare-bash lint in `tests/test_repo_rules.py` at it, and drop the tests now ported here (`test_pc_deploy.py`, `test_ctl.py` except `Rule78`
   over its rows and battles, `test_acceptance.py`, `test_saves.py` `Codec` and `Diff`, `test_job_sh.py`, `test_setup.py` `test_bash_kind` and
   `test_bash_for_tests`, `test_proxy_host.py` `GitBash`), keeping `Rule78`, `NapoleonMap`, `Recipes`, `Staging`, the noise file and its real
   identity. Recommendation: do it in the napoleon job that bumps the pin.
2. **`acceptance.py main()` resolves the harness adapter before parsing its arguments**, so `check-baseline` and `streak` (which need no
   adapter) fail with a `LayoutError` in a repo without one. Not a regression and more than one line, so not fixed here; recommendation: a
   later harness job (W9 or W10) makes the adapter lookup lazy, after which the `Baseline` patch in `tests/test_acceptance.py` can go.
3. **W10** (extends `tests/test_job_sh.py`) inherits the harness-windows step and `bash_or_skip`. Recommendation: keep new shell-running
   cases on `bash_or_skip(self)` so harness-windows keeps refusing a skip.
