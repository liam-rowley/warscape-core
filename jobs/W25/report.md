# W25 report: pc_deploy and harness hardening: locks, atomic ini, stray files, small guards

`pc_deploy install`, `uninstall`, `set` and `sync-lua` now take the game lock through W10's `job.sh`, or use the caller's (exit 2 when another session holds it), and run the is-a-game-running check only once the lock is held; `set` checks for a running game too and writes the ini (and every verb writes `install.json`) through a same-folder temp file and `os.replace`. With nothing installed, a stray config file or mod folder fails `status` and makes `install` refuse before its snapshot (`--move-stray` moves it aside). `owned` is the union of every installed kit, and every install backs up what it is about to own for the first time. The watcher (1.5.0) never weakens `exe_check` on a `watcher.ini` reload or across a `restart`/`update` job, and its launch gate hashes the exe on every launch. Kit paths are checked with backslashes as separators, and `esf_edit.set_value` takes the `@N` child position. Version 0.33.0.

## What was built
Decisions as numbered in the brief.
- **1 to 5, the lock (H7).** `proxy/tools/pc_deploy.py` has a `game_lock(state, owner, session, verb, job_sh)` context manager. It runs `job.sh holds <owner>`, and on a pass uses the caller's lock and leaves it held. Otherwise it runs `job.sh lock <owner> <session> pc_deploy-<verb>` and releases the lock in `finally` with `unlock <owner>`. A refusal raises `Refused` (a `SystemExit` the CLI turns into exit 2) with job.sh's line, `job.sh lock --wait` and "Nothing was changed".
  - `install` runs `touch <owner>` once, before the snapshot and the copies.
  - `--owner`, `--session` and `--job-sh FILE` were added to the four verbs. `resolve_identity` follows `ctl.py`'s rule and wording.
  - Where things come from: the watcher root is `<state>/watcher`, passed as `WATCHER_ROOT`. Bash comes from `warscape.gitbash`, or the same search inline in a kit copy (never the WSL launcher). `job.sh` is looked for at `--job-sh`, then beside the script, then in the repo harness. The watcher installer places no `job.sh` under the watcher root: `install.ps1` copies only the manifest's `src/` and `profiles/` files, so that place is not searched.
  - With no `<state>/watcher` folder (or no `--state`), the verb proceeds and prints one line saying no lock is needed or possible.
  - `--assume-closed` now skips only the running check. `require_closed` is called inside the lock.
  - `set` runs in this order: the pending-restore wait (W10's B39), then the lock, then `require_closed` (with `--assume-closed` added to its parser), then the write. It refuses when no record or identity names the exe, unless `--assume-closed` is given.
- **6, atomic writes.** `write_atomic(path, data)` writes `<name>.<stamp>.<pid>.tmp` in the same folder, then flushes, fsyncs and calls `os.replace`. On `PermissionError` it makes 1 attempt plus 5 retries, 0.2 s apart, then refuses: the target is untouched and the temp file is removed (a code comment explains why that removal is not a "never delete" case). It is used for the ini and for every `install.json` write (`save()`, the end of `install`, `set`, `sync-lua`).
- **7, stray files (H8).** `owned_by_name()` returns the config file and `mod_dir/`. `stray_owned(game, names, by_sha)` also counts a `d3d9.dll` as stray, but only when its sha256 matches a kit file.
  - `pc_rules` has no-record branch lines `stray: <path> (nothing is installed: left by an earlier install or by hand; move it to <state>/_to_delete)`, and a stray fails `status` (exit 1). This answers open question 1 as recommended.
  - `install` with no record refuses before any snapshot and names `--move-stray`. With `--move-stray`, the files go to `<state>/_to_delete/stray_<stamp>/` first.
- **8 and 9, owned and backups (G5).** `rec['owned']` becomes the old list plus the new kit's entries that were not in it, with order kept. `rec['owned_by']` records the kit that first owned each path.
  - Backups are taken for every owned entry that is new to the record. A recorded backup whose move never happened is taken on the next run: its backup is missing, the game path exists, and the path holds none of this kit's files byte for byte.
- **10, B72 (a).** The `sync_lua` docstring now says that the mod folder is owned whole, and that a file at a dev Lua path is replaced and its old copy moved to `_to_delete`. Behaviour is unchanged. `docs/BACKLOG.md` B72 now holds only (b).
- **11 to 13, the watcher (H1).** In `harness/watcher.ps1` 1.5.0:
  - `Reload-ExeCheck` is a pure function, and `Load-Settings -Reload` keeps a non-`warn` value when the ini asks for `warn`. The refusal is logged once per distinct value; the other keys still apply.
  - `watcher.status` carries `exe_check` and `exe_check_refused`.
  - Before exit 3 or 4, the watcher writes `restart.carry` with `Write-Atomic`. The next start reads and removes it, and `Resolve-ExeCheck` (pure) takes the stricter of carry and ini, ignoring a carry older than 300 s. A start that honours `warn` logs `exe_check=warn at start`.
  - `Exe-Gate` calls `Exe-Check -Fresh`, so the exe is hashed on every launch. The status cache key is `path|Length|LastWriteTimeUtc.Ticks|CreationTimeUtc.Ticks`.
- **14, `safe_rel` (H12).** Backslashes become `/`. Refused: an empty path, a leading `/`, any `:`, and any empty, `.` or `..` segment. `verify_kit` stores the normalised path in the manifest it returns (so `install` never writes a backslash name on POSIX). `plain_name` refuses a `staged` or `kit_files[].name` that contains a separator. `verify_harness_kit` keeps its "outside src/ and profiles/" message. The proxy kit keeps "not a relative path inside the game folder".
- **15, one ESF index.** `Esf.set_value(container, index, value)` uses `container[index]` and raises `ValueError` naming `@N` when the node is a record or array. `docs/CONSUMING.md` says a caller must move from the old index to `@N`.
  - Napoleon callers: none. `git grep set_value origin/main -- . ':!core'` in `napoleon-remastered` (read-only) finds nothing; the only hits on disk are copies of `esf_edit.py` itself in scratch worktrees.
- **Docs.** `docs/CONSUMING.md` has the new section "pc_deploy takes the lock; exe_check is a start-time setting". `docs/DECISIONS.md` has C29 (proposed, reversible), and `registries/tools.jsonl` has the `pc_deploy` header row.

## Evidence
- Tests, red first: commit fc5f6c2 on `job/W25`.
  - New Python tests: `tests/test_pc_deploy.py` classes `Lock` (12 cases), `AtomicWrite` (4), `StrayAndUpgrade` (6) and `SafeRel` (3), plus `tests/test_saves.py` `OneIndex` (3).
  - New unit cases in `harness/tests/Test-Unit.ps1`: three (exe_check at start, the reload rule, the exe check cache).
  - Integration case rewritten in `harness/tests/Test-Integration.ps1`. It runs a watcher with `refuse`, edits the ini to `warn` (the launch is still refused and `exe_check_refused` appears), sends a `restart` (still refused, and the carry is consumed), then does a fresh stop and start (the launch goes ahead with the warning).
  - Locally on this PC (Windows 11, Python 3, Git Bash, Windows PowerShell 5.1), 2026-11-04:
    - Red: 25 failing Python cases and 3 failing unit cases before the build.
    - Green: `python3 -m unittest tests.test_pc_deploy` 65 OK (including the Windows-only `test_an_ini_open_for_reading_makes_set_retry_then_refuse`); `tests.test_saves` 16 OK; unit suite `57 passed, 0 failed`.
    - `python3 wsc.py gates` (full): 13 ok, 2 warn (ci_render's standing W23 note; 5 skips for capstone and POSIX sh), 0 failed, 737 host tests.
  - In CI only: `-Suite integration` (never run on this PC). CI run 41884383568 on e17cb1c (2026-11-04): `gates (ubuntu-latest)`, `gates (windows-latest)`, `proxy` and `harness-windows` green; `harness-windows` shows the three new unit cases PASS (`unit : 57 passed, 0 failed`) and the rewritten integration case `exe check (J18, W25)` PASS (`integration : 34 passed, 0 failed`). The Windows-only ini case also runs on the `gates (windows-latest)` leg. The lock cases need Git Bash, so on Ubuntu they run with the system bash.
- Failing fixtures: each was a scratch commit in a throwaway worktree (detached from `job/W25`, local branch `scratch-w25-fixtures`, deleted, never pushed), and each turned its test red:
  - a verb that skips the lock (`uninstall` without `game_lock`): red, `Lock.test_another_holder_refuses_every_verb_with_nothing_written`.
  - `--assume-closed` skipping the lock: red, `Lock.test_assume_closed_never_skips_the_lock`.
  - `set` writing in place: red, `AtomicWrite.test_set_writes_through_a_same_folder_temp_file`.
  - `status` ignoring a stray: red, `StrayAndUpgrade.test_status_lists_a_stray_config_file_or_mod_folder_and_fails`.
  - `owned` back to the new set only, and backups only when `rec is None`: both red, `StrayAndUpgrade.test_an_upgrade_owns_the_union_backs_up_a_new_path_and_uninstalls_exactly`.
  - a failed backup never retried: red, `StrayAndUpgrade.test_a_failed_backup_is_taken_on_the_rerun_never_sent_to_to_delete`.
  - `safe_rel` with no backslash conversion: red, `SafeRel.test_safe_rel`.
  - `set_value` back to the Val index: red, `OneIndex.test_set_value_takes_the_child_position_and_a_record_in_front_shifts_nothing`.
  - the reload applying `warn`: red, unit "exe_check reload".
  - the carry ignored by the pure rule: red, unit "exe_check at start". The start-time use of the carry is covered by the integration case (CI).
  - the gate using the cache: red, unit "exe check cache".
- Exe hash timing: `Get-FileHash -Algorithm SHA1` on a 17,895,424-byte file (the size of the project PC's game exe, read from its metadata only; the hashed file was a temp copy of that size in the scratchpad) took 26.9 to 35.8 ms over five warm runs in Windows PowerShell 5.1 on this PC, 2026-11-04. Hashing on every launch costs well under a second.

## Version
0.33.0. On `main` 0.30.0 is current, `job/W15` takes 0.31.0 and `job/W16` 0.32.0, so this job takes the next free number (it was 0.32.0 until W16 took it). Re-checked before the last push. W29 (C27, release tags by workflow) is still `needs_brief`, so job branches still bump `VERSION`.

## Deviations from the brief, and why
- **Retry count.** Decision 6 says "retry 5 times": this is read as 1 attempt plus 5 retries (6 replace calls, about 1 s). The test asserts 6.
- **Which values are "weaker".** Decision 11's rule is "anything but `refuse` while the running one is `refuse`". `Reload-ExeCheck` uses the gate's own test instead: a reload is refused when the running value is not `warn` and the ini asks for `warn`, compared case-insensitively, as `Exe-Gate`'s `-eq 'warn'` is.
  - A bogus value refuses at the gate anyway, so it is let through rather than logged as a refusal.
  - `WARN` would have weakened the gate under a case-sensitive reading, so it is refused.
- **A carry that beats the ini at start.** When the carry is stricter than the ini at start, the watcher also sets `exe_check_refused` and logs the refusal line, so `watcher.status` shows the disagreement after a restart too.
- **The `d3d9.dll` sha rule is applied at `install` only.** `status` has no kit to compare `d3d9.dll` against, so a stray in `status` is only the config file or the mod folder.
- **New wording for bad staged names.** A `staged` or `kit_files[].name` with a separator gets its own message, "not a plain file name in the kit folder". The path messages are unchanged.
- **`set` with neither an install record nor an identity** cannot run the running check, so it refuses unless `--assume-closed` is given. The brief does not cover this case; refusing is the safe side.
- **`SetWaitsForRestore` needs Git Bash now.** Its fake watcher folder means `set` takes the lock, so the class now sets `WSC_SESSION_ID` and skips without Git Bash, the same way `test_job_sh` does.
- **Integration case rewritten.** The existing integration case `exe check (J18)` edited the ini to `warn` and expected the launch to go ahead. That is exactly what decision 11 forbids, so the case was rewritten as described in Evidence.
- **The `docs/CONSUMING.md` section is five lines, not a full section.** `main` is at 28.7 KB of the 30 KB cap and `job/W15` adds 1.8 KB, so a longer section would fail `doc_size` for whichever of the two merges second. The detail is in the `pc_deploy.py` header and docstrings, and in C29.
- **Out of scope, moved to napoleon:** `stage_save.py` refusing `&` in save names and `load_save.sh` quoting `$JOB` live in napoleon-remastered (`saves/napoleon/`), not in the core (open question 4). The napoleon audit's Corrections already moved them to J91. The W25 row's description still names them; the reviewer may trim it (the row text is not this job's to rewrite).

## Open questions
1. **A watcher crash is not a restart.** A watcher that crashes, or whose powershell is killed (any exit but 3, 4, 10 or 11), is restarted by `watch.cmd` after 4 s with no carry, so it reads the ini as written. An agent able to kill the watcher process could still weaken `exe_check`. Recommended: leave this to the agent hook, which already denies most process kills. If not, a later job can keep a refreshed carry while the watcher runs and remove it only on exit 11. The gap is written into C29.
2. **Unchanged recommendations.** Open questions 1 to 5 in the brief were followed as recommended. Question 4 goes to napoleon J91.

## What napoleon must do after the tag
- Bump the pin through the acceptance passes on the new build (train 1, J78). Update the PC's watcher first to **1.5.0** (`pc_deploy.py kit --what harness`, then `send`, then `update kit=<id>`).
- `pc_deploy install|uninstall|set|sync-lua` now need `WSC_SESSION_ID` (or `--session`) and take or use the game lock. `set` refuses while the game runs.
- Before the next install, Liam removes the stray config file on the project PC by hand. Otherwise `status` fails and `install` refuses until it is moved (`--move-stray`). J-checks that read `status` exit 0 will see it.
- Changing `exe_check` now means Liam stops and starts the watcher. An ini edit plus a `restart` job no longer does it.
- A caller of `esf_edit.set_value` passes `@N`. There are none today.
