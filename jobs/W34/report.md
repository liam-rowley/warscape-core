# W34 report: Real-process smoke, offline anchor check, ctl lua limits, Alt+F4 with UI focus

The wine smoke now writes a patch in a real process: a second build of its host carries the null games' sites, so launch 12 sees the write, the page protections, the patched code running, `peek` and a ctl round trip. `gen_tables.py --exe` checks every site against a staged exe offline. The ctl `lua` verb reads only under `luaDir` and the ctl folder, the ctl folder is owner-only and rotates, system keys always reach the game, and `GameAdapter`'s size is asserted. The hook row was dropped (the core has no hook it installs at a site without a game's adapter) and B80 was not built. The folder's ACE names the game's user, not `OW` as the brief said: CI proved `OW` kills the channel under wine. One consumer impact needs action: napoleon's hand probes ran `lua` chunks from `C:/napoleon_remastered_pc/_scratch/`, which is now refused.

## What was built
### A. The stand-in and launch 12 (C5)
- **Stand-in:** a second build of `proxy/tests/smoke_host.cpp` (`-DWSP_SMOKE_SITES`), not a new file. It prints its patched page's `VirtualQuery` protection before and after the DLL loads, and calls the patched code.
- **Fixed RVAs:** top-level asm in the input section `.init`, which mingw's default linker script places first in `.text`, so `.org n` is RVA `0x1000 + n`. No linker flag, no post-link patching, a plain PE, and a real code page (`.text`, `0x60000060`). `gen_tables.py --exe` proves the RVAs before the first launch.
- **Rows, both null games:** `null.smoke_patch` (fixed patch, RVA 0x1180, `90 90 b8` | `01 00 00 00` -> `02 00 00 00`, then `c3`: a callable `mov eax, 1`) and the bool key `null.smoke_patch` (default 0, release 0). Regenerated tables and ini.
- **Launch 12** (11 was taken by W35) runs only for a game whose tables hold `null.smoke_patch`, so a consumer's smoke stays at 11 launches and says so. It also seeds the ctl folder past both rotation limits, so `CtlRotate` runs on real files. The final line is W35's with the count from `$LAUNCHES`.
- **`--docker smoke` now runs as CI does:** a non-root user in a folder of the container (`WSP_SMOKE_DIR`). See Deviations.
- **Hook row dropped (decision 2, kill criterion 3).** The core's only hooks are `IatHook` and `VtableHook` (`hooks.cpp`). Every `SiteAddress` consumer is `camera.cpp`, `console.cpp` or `orders.cpp`, each behind a game adapter the null game sets to `nullptr`; `dev.cpp` only `peek`s. `null.dummy_hook` is still checked by the plan in the real process (an executable section, stock bytes), but nothing detours it. A core-owned test hook is brief open question 5's follow-up row.

### B. `gen_tables.py --exe` (C7)
- `--exe <path>` reads the file with `exe_info.parse_pe`/`rva_to_off`, compares sha1, `TimeDateStamp` and `SizeOfImage` with the identity, and prints `MATCH <id> 0x<rva>` or the brief's `MISMATCH` lines. Exit 0, 1 or 2. It validates the rows first, writes nothing, and with `--check` does both.
- Beyond the brief, because a false `MATCH` is the failure that matters: it applies the DLL's section rule (a site must be in a section's file-backed bytes, so an RVA in a zero-filled tail is `rva not in the file`), and a hook outside an executable section mismatches, as the DLL's `NOT IN CODE` does.
- `--allow-pin-mismatch` (the smaller change of decision 2): one note for the identity; the bytes still decide.
- **B80 not built.** See Deviations.

### C. `GameAdapter` (C6, core half)
- One `static_assert` in `adapter.h`: `sizeof(GameAdapter) == (sizeof(void*) == 4 ? 68 : 128)`, both numbers read from the two compilers. I chose this over the `#if` form because the 64-bit host tests fail too, not only the DLL build.
- **The null adapters stay positional** (decision 11's branch: the build is `-std=c++17`) and each says why. See Open questions.
- `docs/CONSUMING.md` "DLL changes from W34's tag"; the `pc_deploy` paragraph moved to `docs/UPGRADING.md` for the cap.

### E. ctl `lua`, the folder, rotation (C8)
- `LuaPathAllowed` (`devcore.h`, pure): one spelling per path, then a prefix compare on a segment boundary. It runs in `Execute` before `RunLua`, so a refused path never reaches the bridge. Beyond the brief's list it refuses a rooted path with no drive, `C:x`, a segment ending in a dot or a space (Windows drops those, so `.. ` would mean `..`) and reserved device names.
- `CtlRestrictFolder` (`dev.cpp`): a protected DACL with one ACE, called from `CtlThread` for a new or existing folder. The ACE names the process user's SID (`ProcessUserSid`), not `OW`: see Deviations. No new import.
- `RotatePlan`, `CountIds`, `TrimIds` and the constants in `devcore.h`; `CtlRotate` in `dev.cpp` at ctl start and every 500 handled requests. `.done` files are never touched.

### F. System keys (C9)
- `UiIsSystemKey` in `ui_core.h`; `WndProc` hands the three messages to the engine before the `switch`, the gesture stage still told. `WM_SYSKEYDOWN` and `WM_SYSKEYUP` left the `Key` case. `UiDecide` and `WM_CHAR` are unchanged; no W20 lint needed a change.

## Tests, red then green
**Red first.**
- `tests/test_gen_tables.py`: `FAILED (failures=11)`, each `gen_tables.py: error: unrecognized arguments: --exe ...`.
- `test_ui_core`: `6402 passed, 3 failed`, at run time against today's `WndProc`.
- `test_dev`: red at compile time (`'LuaPathAllowed' was not declared in this scope`), as W33's were.

**A test that earned its place.** `TrimIds` first kept a `\r` on every id (`TrimS2` strips only spaces and tabs). `test_dev` caught it, on a file that is CRLF.

**Green,** on the merged head 2ec5d15, 2026-11-04:
- `build.sh --docker all`: `host tests passed (16 core, 1 game)`: `test_dev` 500, `test_ui_core` 6416, `test_patch_engine` 382, `test_guard` 93, `test_config` 131. Imports unchanged: advapi32, dbghelp, kernel32, msvcrt, user32.
- `build.sh --docker smoke`, non-root: `passed (12 launches under wine, 3 dumps; the DLL fault named from the map)`.
- `tests.test_gen_tables`: 25 tests OK.
- CI, run 41934314012 (head 2ec5d15): `proxy` (both null games), `gates (windows-latest)` and `harness-windows` green. `gates (ubuntu-latest)` red on one test outside this job: see Open questions.

**CI was red once, on my change.** Run 41930770967 (head 7e4c0d5): `proxy` failed at launch 8 with `ctl/peek1.tmp: Permission denied`. Fixed in aad008b; run 41932696093 was green on every job. One fix attempt of the brief's three.

**Each new check was shown to fail** (temporary changes, reverted, none committed):
- A `Reprotect` that does nothing, the C3 regression: the smoke fails with `reads 0x80 after the restore, recorded 0x20: left changed`.
- `OW` back in the ACE: the real `--docker smoke` fails with CI's `Permission denied`.
- A field inserted mid-`GameAdapter`: `static assertion failed` on g++ and on the pinned mingw.

**The ACL on real NTFS** (this PC, 2026-11-04, the DLL's two calls on a scratch folder, no game): `D:P(A;OICI;FA;;;<user SID>)`, one ACE. The owner creates, renames, reads and lists; a second restrict on the existing folder returns 0; a new file inherits the ACE. A file made before the restrict keeps its old ACL, which here included read access for another local account.

**Not run anywhere:** Alt+F4 in a real window with a focused field. Only the source lint and the pure rule cover F; the consumer's PC run is the proof.

## The smoke: launch 12
From `build.sh --docker smoke`, run on 2026-11-04 at head 2ec5d15:
```
build.sh smoke: MATCH null.dummy_hook 0x1000
build.sh smoke: MATCH null.value_distance 0x1100
build.sh smoke: MATCH null.smoke_patch 0x1180
patch_engine: apply - 3 sites: 3 ok, 0 bad, 1 to write (1 bytes), 0 already patched, 1 hooks verified
patch_engine: wrote null.smoke_patch at 00401183: [01 00 00 00] -> [02 00 00 00]
patch_engine: protections restored on 1 page(s): 0x00001000=0x20
ctl: folder ctl\ is owner-only
smoke: page 0x00001000 protect 0x20 before 0x20
smoke: patched code returned 2
peek1.done:"hex": "02 00 00 00"
peek2.done:"hex": "55 8b ec 83"
```
Also checked, with no line printed: `ctl: ping1: ok` and `"pong": true`; a `lua` outside its folders answered `refused`; no `left changed` or `left writable` line; `ctl: rotated: 5 taken files deleted, 4097 old ids dropped from _ids.txt`, leaving 204 taken files and 4100 ids (200 and 4096, plus the launch's four requests).

The page protection reads `0x20` under wine both before the DLL loads and after, so the check compares two real reads. The hook row was dropped: see "What was built", A.

## Decision
C37 (`docs/DECISIONS.md`), proposed. W35 merged C35 first, so this job took the next number at the final merge (C36 went to W36 meanwhile, so C37). W35 also took launch 11, so the brief's launch 11 is launch 12 here.

## Deviations from the brief and why
- **The ACE names the user's SID, not `OW` (decision 15).** The brief expected wine either to accept the DACL or to refuse it. It does neither: it reports success and maps the `OW` ACE to mode 000 (`d---------`), so for a non-root user the folder is shut, to the DLL's own wine process too (`old1.cmd` was never taken). A `chmod` shim in the smoke would not hold, since new files would be mode 000 as well, and skipping the ACL under wine would put test-shaped code in the shipped DLL. Naming the user keeps one protected ACE and advapi32 only (`OpenProcessToken`, `GetTokenInformation`, `ConvertSidToStringSidW`). It also removes a Windows risk: with `OW`, a non-elevated game would lock itself out of a folder an elevated process made, as the owner would be Administrators. **Liam may want to look at this one:** it changes a stated decision. The meaning differs only when the folder's owner is not the game's user.
- **`--docker smoke` changed (not in the brief).** It passed while CI was red: root ignores mode bits, and a Windows bind mount has none. By the repo's "a learning becomes code first" rule it now runs non-root in a folder of the container. Red with `OW`, as shown above.
- **The final line is not the brief's.** W35 changed it to 3 dumps and the map text; this job keeps that and takes the count from `$LAUNCHES`.
- **The two old rows do not stay refused in launch 12.** Decision 2 keeps them "refused", and decision 3 expects `1 to write`. Both cannot hold: `MakePatchPlan` is all-or-nothing (`patch_engine.h`: any bad site, nothing written) and `SiteAddress` answers only after an accepted plan. `patch_engine.h` is out of scope, so the stand-in carries all three rows. They stay refused in launches 2 to 11, where the plain host runs.
- **`peek <site> 4`, not `peek <site> * 4`.** The `*` is a pointer hop: it would read the patched bytes as an address and fail. Launch 8's `* 4` is only ever refused, so it never showed.
- **Mechanism: `.init`, not a `.wsp` section with `--section-start`.** The rows at RVA 0x1000 and 0x1100 stay, and `.text` starts at 0x1000, so a section there would have to displace `.text`. `.init` needs no flag and gives a real code page.
- **Launch 2's count line is unchanged.** Its regex already takes any count (since J15), which a game's smoke needs.
- **The stand-in is checked at `$OUT/smoke/standin.exe`, then copied to `$G/$EXE` for launch 12,** rather than checked at `$G/$EXE`: the plain host must stay there for launches 1 to 11. Same bytes.
- **Launch 11 waits for the answers one at a time** (`ask`), because requests with one write time run in name order, so `peek2` could end the launch before `ping1`.
- **Additions:** the stand-in calls the patched code (`smoke: patched code returned 2`), launch 12 sends a `lua` outside its folders and checks rotation on real files, and a `test_patch_engine.cpp` case runs the real generated row (the brief's acceptance says the `ApplyPlanToBuffer` comparison covers it; only synthetic sites did). That file was not in the scope list.
- **B80 not built.** The filter is a few lines, but as worded it would break napoleon: 14 of its keys are owned by jobs (`J24`, `J27`), not `proxy`, they are live `gfx.*` keys its `engine_sites` rows name, and three ship on. `gen_tables` would refuse those rows, or a looser filter would drop them. The B80 row now says so and waits for napoleon to re-own them.
- **The `CONSUMING.md` section is headed "from W34's tag",** because the version depends on which open jobs release first.
- **One commit has no `Claude-Session` trailer:** the merge 7e4c0d5 took git's default message. It is pushed, and a pushed branch is not rewritten. Every other commit has it.

## Open questions
- **A flaky test, not from this job.** `test_job_sh.py` `test_lock_wait_takes_a_lock_released_meanwhile_and_times_out_with_124` failed in run 41934314012 with `2.06 not greater than or equal to 2.5`. `job.sh lock --wait` sets its deadline from `date +%s`, in whole seconds, so `--wait 3` started late in a second can end after about 2.06 s. The code dates from W10; neither the test nor `job.sh` is changed here, and the test passed on the run before the merge and on `main`. A floor of 2.0 would fix it. Left alone as out of scope.
- **Designated initialisers need a call (decision 11, open question 4).** The brief's branch says stay positional below C++20, and I followed it. But the premise is weaker than it reads: under the build's real flags `.field = x` compiles as a GNU extension, and a missing member still fails `-Wextra -Werror` (checked with the pinned mingw). So the core's adapters could show the rule today. Switching means changing CI's `sed 's/, &kGesture };/ };/'` guard too, which is a workflow edit. A later row can do it.
- **Files already in an existing ctl folder keep their ACL** (measured, above): `SetFileSecurityW` does not walk the folder, as decision 15 specified. On the PC's existing `ctl` folder, old `.done` files stay as readable as they were; the folder itself and everything new are the user's alone. Clearing the folder once at the pin bump closes that.
- **An elevated driver:** it runs with the same user SID, so it keeps access. A driver under another account does not.
- **`--exe` does not read relocations:** a patch value the DLL refuses as `RELOCATED VALUE` still reads `MATCH`. `docs/UPGRADING.md` says so. A row could add it.
- **Junctions under a root** are not covered: a link there is the folder owner's to make. Rotation is run once, at ctl start; the every-500 path is a lint, not a run.

## What napoleon must do (the pin-bump job after J78)
- **`lua` chunks (action needed).** Harness routes are fine: every `adapter.json` chunk is `napoleon_remastered/lua/ctl/...`, under its `luaDir`. But recorded PC probes used `lua C:/napoleon_remastered_pc/_scratch/j40/*.lua` (napoleon-remastered's run 20261031_j40pc), outside both folders, and will now be refused. Put such chunks in `C:\napoleon_remastered_pc\ctl\`. I searched its working copy, not `origin/main`: this session's isolation refuses `git -C` on another repo, so re-check there.
- **Build id:** `gen_tables.py`, `build.sh`, `proxy/src` changed; rule 79's 20 passes. Its smoke stays at 11 launches (no `null.smoke_patch` row) and now runs non-root under `--docker`.
- **`GameAdapter`:** its positional list keeps compiling (no field added); J64 switches it. The tag brings the size assert.
- **Checklist:** add `python3 core/proxy/tools/gen_tables.py --exe <staged copy>` after `exe_info.py`, before a PC run.
- **Say if** the harness driver runs elevated or as another user: an owner-only folder would stop another user.
- **Record with the run id:** (1) no `could not restrict` line; (2) Alt+F4 with a focused text field closes the game; (3) the ctl folder's ACL shows one ACE; (4) the harness's `lua` chunks still run.
