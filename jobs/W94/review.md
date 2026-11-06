# W94 review

## Round 1 (2026-11-06, branch job/W94 at 87babd7)

**Verdict: merge.**

The guard covers the way J32 left the ini. Every brief decision is built, Windows CI ran the new tests, and the branch is clean against the latest main. One gap of the same kind remains: with the watcher stopped, the uninstall still goes ahead. The brief decided that on purpose (decision 4), so it is a later row and not a defect here.

### Machines
- **CI at the head, run 42205504871 (push, `87babd7`).** All required jobs passed: `gates (ubuntu-latest)`, `gates (windows-latest)`, `harness-windows`, `proxy`.
- **Windows coverage: yes, in one job.** `gates (windows-latest)` runs the whole host suite, 1327 passed and 5 skipped. The 5 skips are the hook test and 4 capstone tests, so all 8 `UninstallWaitsForRestore` methods and `SetWaitsForRestore` ran. I checked this because the class skips without Git Bash and `python3`, and `harness-windows` does not run `tests.test_pc_deploy` (see L3). The same suite also passed on this Windows PC: 1327 passed, 5 skipped.
- **At the head, locally.** `wsc gates`: 14 ok, 2 warn, 0 failed. The warnings are `hooks` (a worktree) and the skip line. `wsc policy` refused only for the missing review and the row status, as it should before this round.
- **Against the latest main (`60a0d82`, fetched again after the run).** Main moved twice during this review: W127's row, then W9 and W128. W9 changes `harness/acceptance.py` and `harness/ctl.py`, and neither touches `uninstall` or the restore helpers. No file changed on both sides. Trial merge: clean, tree `43edeaa0`. `wsc gates` on it as throwaway commit `938a254`, never pushed: 14 ok, 2 warn, 0 failed, 1382 host tests passed, 5 skipped. This holds for main at `60a0d82` only.
- **Red then green.** At `f945803` the class gives 5 errors and 4 failures (9 entries, counting two subtests), as the report says, though it has 8 methods and not 10. With the second look removed from `uninstall`, only `test_a_profile_applied_between_the_check_and_the_lock...` fails, so that test does its job.

### Does the guard cover the way J32 left it? Yes.
From `jobs/J32/review.md` round 2 (S6) in napoleon, and read again from the PC, `C:\napoleon_remastered_pc`, read-only:
- **The state at the uninstall.** `watcher.log` has the `headless` overlay for owner `j32` at 09:19:27, again at 09:30:44 and 09:30:52, then `lock: free` and the restore at 09:37:21. `Headless-Overlay` writes `_active.json` before its first change (`harness/watcher.ps1:916`), and `Auto-Restore` runs only once the lock is free, so the file was there at 09:37:18. The file itself is gone, so this is read from the code and the log.
- **The watcher was alive.** It logged within 3 s of the unlock, so the heartbeat was fresh. That matters: the guard is off on a stale heartbeat (L1).
- **Replay.** The same order in a temp folder: `_active.json` in the watcher's own form (BOM, `ConvertTo-Json` layout), the PC's real `watcher.status` with the lock set to `j32`, uninstall with the lock held, then unlock and restore. `game_lock`, `require_closed` and `_uninstall` are stubbed, and the restore is simulated, so this tests the guard's decision and not a real watcher.

| tool | uninstall | after unlock and restore |
|---|---|---|
| main `b4aceec` | returns True, ini moved | ini back, nothing installed: **the J32 stray** |
| W94 `87babd7` | refused, names `headless` and owner `j32`, nothing moved | ini back, still owned by the install; a second uninstall removes it |

- **J32's one-line chain still ends safe.** `uninstall; status; job.sh unlock` now waits 30 s, exits non-zero and moves nothing. The unlock then runs and the restore lands on a folder that is still installed, so no stray is possible.
- **J67** is the same route, by its report ("uninstalling while the watcher's restore was pending").
- **Not fixed by this job, as the brief says:** the 10957-byte `napoleon_remastered.ini` from J32 is still in the game folder (seen 2026-11-06). It is Liam's to clear, or J78's `--move-stray`.

### Claims and brief
- Decisions 1 to 6 hold in `proxy/tools/pc_deploy.py:894` and `:896`, and in `wait_for_restore`. `set`'s text is unchanged, and `SetWaitsForRestore` and `Lock` pass untouched. The order is check, lock, second look, running check.
- The watcher writes no `null` or `{}`: `Write-Atomic` at lines 729 and 916, `Remove-Quiet` at 756. The live `watcher.status` shows `profile_active` null with no `_active.json`, as the report says.
- **Report gaps, both answered here:** it gives no CI run id (it is 42205504871 above), and it leaves the unreadable file "to be checked in `play.py`". Checked: they disagree (L2), so "now agree" holds for the four named shapes only.
- The budget was lifted from 35 to 60 with a reason on the row; 55 calls used. The model matches the brief. The header, the row and the CONSUMING line are present, and the proxy section did move, so the line's new place is a fair deviation.

### Risk-first reading
I read `uninstall`, `pending_restore`, `wait_for_restore` and `watcher_view` in full, and the watcher's overlay and restore, because this code decides whether the game folder ends clean. Everything else is skimmed.

### Blockers
None.

### Should-fix
None.

### Later
**L1. A stopped watcher still lets the uninstall through, with the same result.** `proxy/tools/pc_deploy.py:1006`. `wait_for_restore` returns on an unusable watcher before it reads `_active.json`, so the line says a restore "cannot be seen" even when the file is there to read. To see it: the replay with `watcher.alive` an hour old prints that line, the uninstall returns True, and the next watcher start restores the ini: a stray again. A reboot or a watcher update during a sitting would do it. Brief decision 4 chose this and the builder followed it, but its reason covers a host with no watcher, not a stopped one with the file present. Whether to refuse there needs a way out for a watcher that will not start, so it is a design call. Filed as a `later` row.

**L2. `play.py` and the core disagree on an unreadable `_active.json`, and the report says nothing is needed at the pin bump.** napoleon `upscale/pc/play.py:73`: `profile_active` returns none on a read error, where the core says pending. `play.py` moves the packs before it calls `pc_deploy.uninstall` (line 302), so that file would leave the packs out and the proxy in, with a `SystemExit` where a `Refused` is expected. The watcher's atomic write makes this unlikely. It is the game's to change, in the row.

**L3. Nothing makes Windows CI fail if these tests skip.** `.github/workflows/gates.yml:283`, `ci/gates.yml.in:152`. `tests.test_pc_deploy` needs bash, but only `harness-windows` sets `WSC_REQUIRE_BASH`, and it does not run that module. If `gates (windows-latest)` lost Git Bash or `python3`, the lock and restore tests would turn into a warning on a green check. Add the module to that job, or set the variable on the gates job. In the row.

**L4. The 30 s wait cannot help a caller holding the lock itself.** The restore waits for that very lock, so J32's order spends 30 s for nothing. Refuse at once when the lock's holder is the caller. In the row.

Brief open questions 1 and 2 (`status` line, `install` guard) are still Liam's, default after 2026-11-13. Question 2 matters here: `install` snapshotting a leftover ini as vanilla is how J96 inherited J32's file.

### For anyone merging
No rule changes here, so no other open branch is affected. Rule 79 is the game's call at its pin bump, as the report says.
