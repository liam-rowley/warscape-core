# W94 report: `pc_deploy uninstall` refuses while a profile is active

`pc_deploy uninstall` now does what `set` does about the watcher's pending profile restore (`<state>/watcher/profiles/_active.json`): it waits up to `--wait-restore` seconds (default 30, 0 refuses at once), then refuses with nothing moved and the install record untouched. The check runs first, then the game lock, then a second look with no wait, then the running check. The proxy tool changed, and the pin bump crosses a `proxy/` file; whether napoleon's rule 79 applies to a tool change (its trigger is new DLL bytes and a new build id) is the game's call, not this job's.

## What was built
Decisions as numbered in the brief.
- **1 to 3, 5.** `proxy/tools/pc_deploy.py`: `uninstall(..., wait_restore=30, sleep=time.sleep)` calls `wait_for_restore(state, wait_restore, sleep, 'uninstall')` before `game_lock`, and again inside the lock with `wait=0, quiet=True` (a profile applied between the first look and the lock is refused; `game_lock`'s `finally` releases the lock). `--assume-closed` is untouched: it still skips only `require_closed`. `wait_for_restore` got `verb='set'` and `quiet=False`; `set`'s text is byte for byte what it was. For `uninstall` the text says the uninstall would put the config files back, the mod ini included, and names the way out: release the lock that applied it, wait until `job.sh status` shows `profile_active` null, run uninstall again; it ends "Nothing was moved."
- **4.** No `--state` watcher folder, or an unusable watcher: the existing one-line "cannot be seen" and on. Unchanged branch, now with the verb in it.
- **`--wait-restore N`** on the `uninstall` parser (same help and default as `set`). `run()` passes it.
- **`pending_restore` and the shapes.** `harness/watcher.ps1` records `_active.json` only for an active profile (`Write-Atomic $ActivePath`, lines 729 and 916) and removes it on a good restore (`Remove-Quiet`, line 756); it never writes `null` or `{}`. `Get-Active` returns `$null` for a missing or unparsable file. So the watcher's own writer is already told apart from idle by "file missing". I still made `null` and `{}` read as none (they were pending, and `{}` was even a non-`None` falsy dict), so `pending_restore` now agrees with napoleon's `profile_active`. A named object and an unreadable file stay pending. This is a change to `set` too, but only for two shapes the watcher does not write.
- **Header and row:** `purpose:` has the clause, `usage:` has `[--wait-restore N]` on `uninstall`; the `proxy.tools.pc_deploy` row was re-added (`reg add tools ... --id proxy.tools.pc_deploy`) and committed with the file.
- **`docs/CONSUMING.md`:** the proxy section moved to `PROXY_HARNESS.md` on 2026-11-04, so the line is in the lock section's last bullet (where `set`'s wait already was). Paid for with two cuts of about the same size (a parenthesis on `touch`, another on the Bash timeout); the file is 30712 bytes, under the 30 KiB cap.

## Evidence
- Red first: commit f945803 on `job/W94`: 9 of the 10 new `UninstallWaitsForRestore` cases failed (5 `TypeError: uninstall() got an unexpected keyword argument 'wait_restore'`, `null` and `{}` shapes, no-watcher line, CLI `unrecognized arguments`); 5b26bb0 makes them green. One test had a wording slip of mine ("put back" vs "config files back"), fixed in the same commit.
- Green: `python3 -m unittest tests.test_pc_deploy`: 73 tests OK, `SetWaitsForRestore` and `Lock` unchanged and passing (2026-11-06).
- Refusal as printed (test `test_a_pending_restore_refuses_and_moves_nothing`): `pc_deploy uninstall: refused, the watcher still has profile 'j9-prof' (owner o1) to restore, and a restore that runs after this uninstall would put the config files back, the mod ini included, into the game folder; the lock is held by o1, the game is not running. The restore waits for the game to close and the lock to be released (job.sh unlock <owner>); waited 3 s (--wait-restore N to wait longer). Release the lock that applied it, wait until `job.sh status` shows profile_active null, then run uninstall again. Nothing was moved.`
- What the watcher writes when idle: no `_active.json` at all (file removed; `watcher.status` then carries `profile_active = null`).
- Full `python3 wsc.py gates` (2026-11-06): the first run failed two host tests (a game name in two comments of a core file; the report not yet on the row), fixed; the second run: 1327 host tests passed, 13 ok, 2 warn (hooks not wired in the worktree; the tests line), 1 failed: `jobs`, because the budget lift (55 calls against 35) was recorded while it ran; rerun `--only jobs,registries,tools,doc_size`: all ok.
- Branch CI run id: see the draft pull request (not known when this was written).

## Deviations from the brief and why
- The `null` and `{}` tests assert "none" although the watcher never writes them: the brief asked for one test per shape "with the answer the watcher's writer makes correct"; for these two the correct answer follows the watcher's reader (`Get-Active`) and napoleon's `profile_active`.
- `docs/CONSUMING.md`'s proxy section is a stub now, so the line went to the lock section.
- The first edits were made in the shared checkout before `EnterWorktree`; they were reverted there and re-applied in the worktree as a patch (no content change).

## Open questions
Unchanged from the brief (1 `status` line, 2 `install` guard, 3 default 30: answered yes for 3 by building it that way). Defaults after 2026-11-13.

## Napoleon at its pin bump
Nothing beyond the bump itself. `play.py`'s `profile_active` and the core's `pending_restore` now agree on missing, `null` and `{}` (none), a named object (pending); an unreadable file is pending in the core and is a read error to be checked in `play.py`. The pin bump crosses `proxy/tools/pc_deploy.py`; rule 79 is the game's call.

Usage: 55 tool calls; models: sonnet; 1 session, counted by hand, about, one session, 2026-11-06
