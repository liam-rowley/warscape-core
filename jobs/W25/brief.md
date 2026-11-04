# W25: pc_deploy and harness hardening: locks, atomic ini, stray files, small guards

Model: Sonnet, reason: none needed (Sonnet is the default). Every item is a local fix in a script that already has host tests (`tests/test_pc_deploy.py`,
`tests/test_saves.py`, `harness/tests/Test-Unit.ps1`, `Test-Integration.ps1`); the lock work stands on W10's finished API and shells out to it, so there is no
new protocol to invent. No DLL, no reverse engineering, no PC (`needs_pc` false). Budget about 150 tool calls (one Python tool with six changes, one watcher
change with a restart rule, one ESF fix, three test suites). At the cap, stop, commit what is green, and report what is left. Kill criteria are at the end.

## Goal
Audit 2026-11-03 H7, H8, H12 (the items that live in the core), H1's watcher half and G5's `pc_deploy` half (`napoleon-remastered` `docs/audits/AUDIT_2026-11-03.md`,
read-only; the row `registries/jobs/W25.json` lists them), plus backlog B72 (a). Today on a shared PC:
- `pc_deploy install`, `uninstall`, `set` and `sync-lua` take no game lock: another session's job can launch the game between the "closed" check and the write.
  `set` never checks that the game is closed at all and rewrites the ini in place, so a crash or a reader sees half a file. `--assume-closed` is prose.
- A stray `<config_file>` left by an earlier install is invisible to `status` while nothing is installed, and the next `install` snapshots it as vanilla and puts
  it back on every uninstall. (The project PC is in this state now; Liam removes that one by hand, this job makes the tool refuse the next one.)
- An upgrade writes `owned` as the new kit's set, so a path an older kit owned is orphaned and uninstall reports DIFFERS; a re-run after a failed backup skips the backup.
- The watcher reloads `watcher.ini` every pass, so one line `exe_check=warn` switches off the D2 launch gate (exe stays vanilla) with no restart and no trace.
- Small guards: `verify_kit` accepts `..\` and `C:\` paths, the exe sha cache trusts size and mtime, `esf_edit` has two index conventions.

## What exists (read before building)
`CLAUDE.md`, `docs/DECISIONS.md`, `docs/CONSUMING.md` ("The proxy, the harness and the save tools"), `docs/BACKLOG.md` (B72), `jobs/W10/brief.md` and, once merged, W10's
`report.md` and the code: **W10 is built just before this job on the same files** (`harness/job.sh`, `harness/watcher.ps1`, `proxy/tools/pc_deploy.py` `set`). Branch from `main`
**after W10 merged**; if it has not, stop (kill criteria). W10 owns, and this job must not touch: the lock owner = session rule and its pattern `^[a-z0-9][a-z0-9_-]{0,39}$`,
`Check-Owner`, `job.sh holds <owner>`, `touch <owner>`, `unlock <owner>`, `lock --wait <s>`, `lock -`, the B20 stale takeover, `lock_stale_min` from the ini, the 100 s waits,
B21, B27, B30 and B39 (`set --wait-restore`, the `_active.json` check). W10's lock command is `job.sh lock <owner> <session> <purpose> [hang_s] [--wait <s>]`; it exits 0 taken, 2 refused
(one line saying who holds it), 124 on a `--wait` timeout; `holds <owner>` exits 0 when `<owner>` (or its session) holds a fresh lock. Read the merged `job.sh` header for the final spelling.

Citations checked against `origin/main` 0.24.0 (before W10); W10 moves lines in the files it touches, so re-find by name:
- **`proxy/tools/pc_deploy.py`:** `pc_rules` 153-179 (the "nothing installed" branch 177-178); `require_closed` 525-531; `install` 564-627 (the backup block 593-600 runs only when `rec is None`;
  `rec.update({'owned': man['owned'] ...})` at **617** and again at 590; the file loop 604-616); `uninstall` 630-664 (backups 643-647); `edit_ini` 668; `set_keys` 718-738 (the in-place write is 731);
  `status` 741; `sync_lua` 774 (docstring says unowned files are never touched, but 792-806 replaces any file at a dev Lua path: B72 a); `verify_kit` 298-318 (the traversal test 309-312 splits on `/` only;
  `verify_harness_kit` 394 has the same flaw; `kdir / e['staged']` at 304 and 391 is joined unchecked). **The row cites line 598 for owned: it is `save()` inside the backup loop; the overwrite is 617.**
- **`harness/watcher.ps1`:** `Load-Settings` 45-58 (defaults 33-36, `exe_check` 35), the pump's reload 1143 (`LastWriteTimeUtc -ne $IniStamp` then `Load-Settings`), `Exe-Check` 343-360 (**the row cites 351: the cache is
  `$ExeCache` 346 and the key at 351-352, `Length|LastWriteTimeUtc.Ticks`**), `Exe-Gate` 362-368 (`exe_check -eq 'warn'`; any other value already refuses), the `restart` job 1321 (exit 3/4; `watch.cmd` relaunches).
- **`saves/esf_edit.py`:** `set_value(container, index, value)` 240-241 indexes among **Val nodes only** (`vals(container)[index]`); the CLI `set` 420 indexes the **child position** `@N` among all nodes, the number `esf_dump`
  and `esf_diff` print. No caller of `set_value` exists in the core; `tests/test_saves.py:134` drives the CLI.
- **Not in the core (moved):** `stage_save.py` (`save_name`, napoleon `saves/napoleon/stage_save.py:55-62`, the row says line 60) and `load_save.sh` (`JOB="bash $REPO/core/harness/job.sh"` unquoted, napoleon
  `saves/napoleon/load_save.sh:12`) are the first consumer's files; the core cannot change them. They are out of scope here and go to a napoleon job (open question 4; say so in the report).
- **Tests:** `tests/test_pc_deploy.py` (`Deploy` setUp 90-119 patches `windows_images`; `HarnessKit` 389; `test_stray_file_reported` 249, `test_running_check` 336), `tests/test_job_sh.py`
  (bash with `--adapter`/`$WATCHER_ROOT`), `tests/test_saves.py`, `harness/tests/Test-Unit.ps1` (the `exe_check` toggles at 333-335), `Test-Integration.ps1` (CI only).

## What this PC can and cannot run (the builder)
As W10: Windows PowerShell 5.1, Git Bash, Python. **Locally:** `python3 -m unittest tests.test_pc_deploy tests.test_job_sh tests.test_saves tests.test_moved_tools` (if `python3` hangs, use
`C:\Users\liamr\AppData\Local\Python\pythoncore-3.15-64\python.exe`); the unit suite `powershell -NoProfile -ExecutionPolicy Bypass -File harness\tests\Run-HostTests.ps1 -Suite unit`; `python3 wsc.py gates`.
**Never locally:** `-Suite integration` (starts and kills fake games; CI's `harness-windows` job only). Any test that takes the lock uses a temp `$WATCHER_ROOT`; none touches the PC's real state folder or live watcher.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### Locks (H7)
1. **`install`, `uninstall`, `set` and `sync-lua` take the lock themselves, through W10's `job.sh`, and release it when done; they never reimplement the protocol.** Reason: the lock file protocol
   (create, stale takeover, owner and session pair) is W10's and was made race-free there; a second implementation in Python would have its own B20. One helper `game_lock(state, owner, session, purpose)`
   (a context manager) in `pc_deploy.py`: (a) `job.sh holds <owner>` passes (the caller already holds it, e.g. a session that took it for a launch): use it, **do not release it** at the end;
   (b) else `job.sh lock <owner> <session> pc_deploy-<verb>` (no wait): taken, release in `finally` with `unlock <owner>`; refused: `SystemExit` naming the holder (job.sh's line) and `job.sh lock`/`--wait`
   as the way to wait. `touch <owner>` once before the slow part of `install`. `status`, `kit`, `send`, `snapshot`, `diff` and `sync-lua --dry-run` take none (read-only).
2. **Owner and session:** new `--owner` and `--session` on the four verbs; defaults exactly W10's (`--session`, else `$WSC_SESSION_ID`, else the variable Claude Code exports; the owner defaults to the session);
   neither: refuse (exit 2) with the same text W10's `ctl.py` gives. Reason: one rule for every tool, so the session that holds the lock for a launch is the same holder here.
3. **Where `job.sh` and the root come from:** root = `<state>/watcher` passed as `WATCHER_ROOT` in the child's environment (so no adapter is needed). `job.sh` is searched in order: `--job-sh FILE`, beside this
   script (a kit copy), `harness_scripts()/job.sh` (the repo), the copy the installer puts under the watcher root (read `harness/install.ps1`; use it only if it places one). **No `<state>/watcher` folder = no
   watcher, so nothing can launch a game and there is no lock to hold: proceed and print one line saying so** (the same rule W10 uses for `set`). A watcher folder but no `job.sh` found: refuse and say
   `--job-sh`. Reason: refusing on a PC with a watcher is the safe side; refusing on a bare host (CI, a game folder with no watcher) would make the tool unusable there.
4. **`--assume-closed` stays, and means only "skip the process-list check".** It never skips the lock and it still prints the warning. With the lock held, the watcher cannot launch a game, so the only open
   question is a process already running or the process list being unusable; that is the one thing Liam can vouch for. `require_closed` is called after the lock is held, never before.
5. **`set` is brought level:** it calls `require_closed` (refuses while a game runs; `--assume-closed` added to its parser), takes the lock (decision 1), and the order is W10's pending-restore check
   first (a pending restore completes only when the lock is free, so checking after taking the lock would deadlock on ourselves), then lock, then the running check, then the write. Without `--state` it cannot
   lock or see the watcher: it still refuses on `tasklist` (decision 3's no-watcher path is for a *state* with no watcher folder), and prints that no lock was possible.
6. **The ini write is atomic:** `edit_ini` text goes to `<ini>.<stamp>.tmp` in the same folder (same volume, `os.replace` is then atomic on Windows and POSIX), `flush` + `os.fsync`, then `os.replace`. On
   Windows `os.replace` raises `PermissionError` when another process holds the destination without share-delete; retry 5 times 0.2 s apart, then refuse with the ini byte-identical and the temp removed
   (it is the call's own copy made a moment before; say so in a comment: the PC "never delete" rule is about the user's files). One function `write_atomic(path, data)` also used for `install.json`
   (`rec_path.write_text` at 582, 623, 737, 814 becomes it): a half-written install record is a worse failure than a half-written ini. CRLF/LF and the other lines stay byte-for-byte as `edit_ini` keeps them today.

### Stray files, owned, backups (H8, G5)
7. **A path the mod owns by *name* is ours when nothing is installed.** From the kit manifest at install (and from `default_identity()` for `status`): the config file and the mod folder (`mod_dir/`) are named for this
   proxy and exist in no vanilla game folder; `d3d9.dll` is not (a ReShade or DXVK wrapper is legitimately foreign) unless its sha256 equals a staged kit file. **`status` with no install record** lists each of
   those that exists as `stray: <path> (nothing is installed: left by an earlier install or by hand; move it to <state>/_to_delete)` and fails (exit 1), through a new `stray_owned(game, names)` called from
   `pc_rules` beside the `.git` and foreign checks. **`install` with no record refuses before the pre-install snapshot** when one is present, naming the files, and offers `--move-stray` which moves
   them to `<state>/_to_delete/stray_<stamp>/` (never deletes) and then installs. Reason: the failure is a snapshot that contains our own file as vanilla; refusing before the snapshot is the only point where it can
   still be avoided, and a foreign file at `d3d9.dll` keeps today's backup-and-restore.
8. **`owned` is the union of every installed set.** `install` over an existing record sets `rec['owned']` to `old + [new entries not already there]` (order kept, no duplicates) at both places (the early `save()` and the
   `rec.update` at 617), so uninstall moves everything any installed kit owned, `foreign_files` treats it all as ours, and `status` is unchanged. `rec['owned_by']`: `{path: kit_id first installed}` for the report/history only.
9. **Back up on every install, not only the first.** The backup step runs for every owned entry that is *new* to the record (not in the old `owned`) and exists, and for any recorded backup whose move never happened
   (the entry's backup path is missing, the game path exists, and its sha256 equals no kit file: a failed earlier run). Reason: a re-run after a failed backup must not send a foreign file to `_to_delete` as ours (line 607), and a
   newer kit that owns a new path must not eat what is there. `uninstall` already skips backups that never happened; keep that.
10. **B72 (a) with it:** `sync_lua`'s docstring claims unowned files are never touched; the whole `mod_dir` is owned, so every dev Lua path is owned. Correct the docstring to say so (no behaviour change) and
    delete the (a) half of B72, leaving (b) (`ctl.py lua`) in the backlog.

### The watcher and `exe_check` (H1)
11. **A reload never weakens `exe_check`; a start may, but only a start by Liam.** `Load-Settings` reports the value it read; the pump's reload (1143) keeps the previous `exe_check` when the new one is
    anything but `refuse` while the running one is `refuse`: **refuse the reload of that key, keep the previous value, log one line** (`settings: watcher.ini asks exe_check=warn; refused, a running watcher
    never weakens it (stop the watcher and start it by hand)`), once per distinct value, and still apply the other keys. Not "stop launching": a typo or a hostile line must not take the whole PC offline, and
    keeping the strong value is exactly what the gate is for. The status file (`Write-Status`) carries `exe_check_refused` while the ini disagrees, so `job.sh status` and the report show it.
12. **How Liam legitimately changes it:** stop the watcher (the stop request, exit 11, or end the `watch.cmd` window) and start it from the logon task or by double-clicking `watch.cmd`; the start reads the
    ini as written and honours `exe_check=warn` with a loud log line (`exe_check=warn at start`). **A `restart`/`update` job (exit 3/4) must not be the way**: before exiting with 3 or 4 the watcher writes
    `<root>\restart.carry` (`exe_check=<effective>`); the next start reads and removes it and takes the stricter of carry and ini. Reason: an agent that can write the ini and send a `restart` job would otherwise
    undo decision 11 in two steps. The file is written with `Write-Atomic`, ignored if older than 5 minutes, and unit-tested as a pure function `Resolve-ExeCheck($ini, $carry)`.
13. **The exe sha cache keys on more than size and mtime.** `Exe-Gate` (the launch gate) **hashes the exe every launch, no cache** (a launch is a rare event and SHA1 of the exe takes well under a second;
    measure it once and put the number in the report). `Exe-Check` called for status keeps a cache keyed on path, `Length`, `LastWriteTimeUtc.Ticks` and `CreationTimeUtc.Ticks`. Reason: a size-and-mtime key is
    the one thing a replaced exe can be made to match (restore the mtime), and the gate is the control that must not be fooled.

### Small guards
14. **`verify_kit` and `verify_harness_kit` share one `safe_rel(path)`:** replace `\` with `/`, then refuse an empty path, a leading `/`, a drive or stream colon anywhere (`C:`, `x:ads`), any empty, `.` or `..`
    segment, and (harness) a first segment outside `src`/`profiles`; also refuse a `staged` or `kit_files[].name` that contains a separator or `..`. The messages stay "not a relative path inside the game folder".
    Reason: Windows takes `\` as a separator, so `..\x` passes the `/` split.
15. **One ESF index convention: the child position `@N` among all of a container's nodes.** `set_value(container, index, value)` changes to index `container[index]` and refuses (ValueError naming the node) when it is not a
    `Val`. Reason: `esf_dump` and `esf_diff` print `@N` over all children and the CLI `set` already takes it; a person reads `@3` off a dump and types `@3`. The Val-only index is used by no caller, so changing it breaks
    nothing in the core; say in `docs/CONSUMING.md` (one line) that a game's own caller of `set_value` must move from the Val index to `@N`, and grep napoleon (read-only) for callers and name them in the report.

## Out of scope
Everything W10 owns (above); the hook's per-segment exemption and the deny list (a game's `.claude/settings.json`, napoleon J76); `stage_save.py` and `load_save.sh` (napoleon, open question 4); B72 (b), B78, B79, B82;
`rr.ps1` (napoleon J81); making the autopilot serialise `needs_pc` (W26). No game names or paths in core files (`tests/test_moved_tools.py` lints them); the audit's paths are evidence for the report only.

## Scope: files this job touches
`proxy/tools/pc_deploy.py`, `harness/watcher.ps1` (and `$Version`, one minor up from W10's), `harness/tests/Test-Unit.ps1`, `harness/tests/Test-Integration.ps1`, `saves/esf_edit.py`, `tests/test_pc_deploy.py`,
`tests/test_saves.py`, `docs/CONSUMING.md` (a short section "pc_deploy takes the lock", the `--owner/--session/--move-stray/--job-sh` flags, the restart rule, the `@N` line), `docs/DECISIONS.md` (one row, next free `C<n>`:
a running watcher never weakens `exe_check`, proposed, reversible), `docs/BACKLOG.md` (B72 (a)), `VERSION`. `harness/job.sh` is **read-only here**: if the lock call needs a change in it, that is a W10 follow-up (kill criteria).

## Steps (host tests first)
1. Confirm W10 is merged; read its report and `job.sh` header; run the local suites once for a baseline (seconds each).
2. **Failing tests first, committed red (one commit).** `tests/test_pc_deploy.py` with a temp `<state>/watcher`, `WATCHER_ROOT`, and the real `job.sh` under bash for the lock cases (the style of `tests/test_job_sh.py`),
   plus a recorded-calls stub for the rest: `install`, `uninstall`, `set`, `sync-lua` each take and release the lock (lock file gone after; held by another owner: refused with nothing written; held by the caller: used and
   left held; no watcher folder: proceeds with the line; watcher folder and no `job.sh`: refuses naming `--job-sh`); `--assume-closed` with a lock held by another still refuses, and with a running game (fake
   watcher status) and our lock proceeds with the warning; `set` refuses while the fake watcher lists the game and leaves the ini byte-identical; `set` writes through a temp file (assert `os.replace` called with a
   same-folder temp, or the temp seen by a patched `os.replace`; a patched `os.replace` raising `PermissionError` leaves the ini byte-identical and no `.tmp`); **on Windows only (`skipUnless(os.name == 'nt')`), the ini
   open for reading in the test makes `set` retry and then refuse, ini intact**; `install.json` is written atomically. `status` with no install and a stray config file or mod folder: lists it, exit 1, names the
   fix; a foreign `d3d9.dll` alone is not stray; `install` with a stray refuses before any snapshot file exists, `--move-stray` moves it into `_to_delete/stray_*` and installs, and the uninstall then leaves the
   folder identical to the folder *without* the stray. Upgrade: a second kit with an extra owned path and a foreign file at it: union recorded, backup taken, uninstall restores the foreign file and the first
   kit's files go, `diffs` empty; a failed-backup retry (patch `move_out` to raise once on the backup) puts the foreign file in `backup/` on the re-run, never in `_to_delete`. `verify_kit` / `verify_harness_kit`:
   `..\x`, `C:\x`, `a:stream`, `./x`, `a//b`, a `staged` of `..\x` each refused; a normal nested path passes. In `tests/test_saves.py`: `set_value` takes the `@N` position (a record in front shifts nothing), refuses a record,
   and the CLI and the API agree on one fixture. In `Test-Unit.ps1`: `Resolve-ExeCheck` (ini warn at start honoured; carry `refuse` beats ini `warn`; stale carry ignored); the reload keeps `refuse` when the ini says
   `warn` and logs once, applies another key changed in the same edit, and lets `refuse` -> `refuse` and `warn` -> `refuse` through; `Exe-Gate` hashes again after a same-size same-mtime replacement (stub the hasher
   or use a temp file whose bytes change with the timestamps restored); the status cache key includes creation time. In `Test-Integration.ps1` (CI only): a real watcher with `exe_check=refuse`, the ini edited to `warn`,
   a launch still refused with the exe check text and `watcher.status` carrying `exe_check_refused`; a `restart` job then a launch with the ini still `warn`: refused; a watcher started fresh with `warn`: launches with the warning.
3. Build `pc_deploy.py`: `safe_rel`, `write_atomic`, `game_lock`, the four verbs and their flags, `set`'s closed check, `stray_owned`, the union, the every-install backups, the docstring and header lines
   (`purpose/usage/when` name the new flags). 4. Build the watcher: reload rule, `Resolve-ExeCheck`, `restart.carry`, the uncached gate, the status field, `$Version`. 5. `esf_edit.py`.
6. Docs, `DECISIONS.md` row, `BACKLOG.md`, `VERSION`. Push early; read CI's `harness-windows` and Windows `gates` logs; copy any failing case's log tail into the report.
7. `python3 wsc.py gates` (full), `python3 wsc.py policy --branch job/W25 --base origin/main`.

## Tests and acceptance
- Every new case red first, then green; every existing case in the suites still green, or changed with a stated reason (tests that called `install`/`uninstall`/`set` now run under the lock seam: use the
  no-watcher path so they need no change).
- Failing fixtures, scratch commits in a throwaway worktree (not pushed), each turning its test red: a verb that skips the lock; `--assume-closed` skipping the lock; `set` writing in place; `status` ignoring
  a stray; `owned` back to the new set only; backups only when `rec is None`; `safe_rel` splitting on `/` only; the reload applying `warn`; the carry ignored; the gate using the cache; `set_value` back to the Val
  index. Name them in the report.
- Done means: CI's `gates` (both OS), `proxy`, `harness-windows` and `policy` green on `job/W25`; the report says which cases ran locally, which only in CI, and which only on the Windows leg; nothing outside
  "Scope" changed; no game name added; the exe hash timing is in the report.

## VERSION
A minor bump (new flags, `status` exit code on a stray, watcher behaviour): **0.26.0 expected** (`main` is 0.24.0 when this is written and W10 takes the next free minor first). Re-read `origin/main` `VERSION` and
the open `job/*` branches before the last commit; the second to merge takes the next free number and merges `main` (never rebase). Say which number you took. Tags are not yours.

## What consumers must do after the tag (napoleon-remastered)
- These are harness inputs: the pin bump that crosses this tag needs acceptance passes on the new build (train 1, J78), and the PC's watcher must be updated first (`pc_deploy.py kit --what harness`, `send`, `update kit=<id>`).
- `pc_deploy install|uninstall|set|sync-lua` now need a session (`WSC_SESSION_ID` or `--session`, as W10) and take or use the game lock; `set` refuses while the game runs; a stray config file or mod folder makes `status`
  fail and `install` refuse until it is moved (`--move-stray`); `status` is part of J-checks that read exit 0.
- Changing `exe_check` is a stop and start by Liam, not an ini edit plus `restart`.
- `stage_save.py` refusing `&` and `load_save.sh` quoting `$JOB` are napoleon's own change (its row).
- A caller of `esf_edit.set_value` passes `@N`, not the Val index.

## Kill criteria
- W10 is not merged, or its `job.sh` has no `holds`/`lock` with an owner and session as its brief defines: stop and report; do not write a second lock protocol.
- The lock call cannot be made without changing `job.sh` (an output or exit code that cannot be told apart): stop and report what you need; a W10 follow-up row is Liam's call.
- `os.replace` over an open ini behaves differently in CI than documented in decision 6 after two designs: stop and report with the observed errors; do not ship an unchecked write.
- The restart carry cannot be made to survive `watch.cmd`'s relaunch under 5.1 after two designs: ship decisions 11 and 13 only, report the gap, and say so in the DECISIONS row.
- An integration case is red in CI after three fix attempts for a cause in this change: stop and report; never run the integration suite on this PC.
- A local test touches the real state folder or the live watcher: stop at once and report what it touched.
- Version collision as in VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Does a stray config file make `status` fail (exit 1), or only warn?** Recommended: fail. It is the state that corrupts the next install, and every J-check that runs `status` is the place to catch it.
2. **Should `pc_deploy` take the lock itself, or only require that the caller holds it?** Recommended: take it when free and use it when held (decision 1); requiring it would add a `job.sh lock` step to every
   hand-run install for no safety gain.
3. **A running watcher refuses a weaker `exe_check`: keep the previous value (chosen) or stop launching?** Recommended: keep the previous value; stopping launching turns a typo into an outage.
4. **`stage_save.py` and `load_save.sh` live in napoleon.** Recommended: add them to a napoleon row (`&` and the other shell metacharacters out of save names; `JOB="bash \"$REPO/core/harness/job.sh\""`), not to
   the core; the W25 row text then loses those two items when the job is reviewed.
5. **Delete the `exe_check` carry file approach in favour of "restart never honours a weakened ini at all"?** Recommended: keep the carry (decision 12); the simpler rule would make Liam's legitimate change
   impossible without a reinstall.

## Finish
Report in `jobs/W25/report.md` (what was built per decision, tests red then green and where each ran, the failing fixtures, the exe hash timing, the version taken, deviations, the napoleon callers of `set_value`, open
questions, what napoleon must do), then `wsc reg set jobs W25 status=review report=jobs/W25/report.md` (`python3 wsc.py`). Push `job/W25`, open the draft pull request, and stop: an independent reviewer merges (C18); tags follow the merge.
