# W34: Real-process smoke, offline anchor check, ctl lua limits, Alt+F4 with UI focus

Model: Opus, reason: DLL work. It changes what the shipped proxy lets through the ctl channel, how the UI host routes system keys and how the control folder is created
(an owner-only ACL under advapi32), and it builds a stand-in exe whose patch is the first write a CI run makes to real code pages. A mistake in the DLL shows only in the
consumer's 20-pass acceptance run (napoleon rule 79) or on the PC, not in a host test. Budget about 150 tool calls (the stand-in exe in step 6 has its own cap of about 40).
At the cap, stop, commit, push and report what is left.

Semver: minor

## Goal
Audit 2026-11-03 (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, read-only; read it with
`git -C /c/Users/liamr/repos/napoleon-remastered show origin/main:docs/audits/AUDIT_2026-11-03.md`), findings C5, C6 (core half), C7, C8 and the rest of C9:
- **C5, no real process runs a hook.** The wine smoke exe refuses every site (none of the adapter's `engine_sites` exist in it) and gets a null `Direct3DCreate9`, so
  launches 1 to 10 test logging, pass-through, threads and the file hooks only. No CI run ever sees a patch write, a hook install or a ctl answer that needs a
  site. W33 made the writer restore protections once per page and read them back (`patch_engine: protections restored on <n> page(s)`), but only the consumer's PC run
  sees that line. This job adds a stand-in exe with one patch site and one hook site at known RVAs, and a smoke that checks the write, the hook, a ctl `ping`
  round trip and the pages' protections.
- **C7, no offline anchor check.** `gen_tables.py` never reads an exe: anchor and stock bytes meet the real image only in-process on the PC. Empire had an offline
  MATCH/MISMATCH tool. `gen_tables.py --exe <staged copy>` does that check in the cloud, so a new engine site is checked before a PC run.
- **C6, positional initialisers (core half).** `GameAdapter` has 10 to 40 positional values per adapter; inserting a field mid-struct shifts them silently, and
  `-Werror` catches only a missing tail. The core half is a `static_assert` on the struct's size and a rule in `docs/CONSUMING.md` (designated initialisers).
  The game half (napoleon J64) is not this job.
- **C8, ctl `lua` and the ctl folder.** `devcore.h` `ParseCtl` accepts any absolute path for `lua <file>` (the error text itself says "relative to the game folder or
  absolute"), the ctl folder inherits the ACL of its parent, and `.cmd.taken` files and `_ids.txt` grow for ever. Dev builds only (`dev.ctl` is 0 in release), but
  the harness runs on the PC with the player's account.
- **C9 (rest), Alt+F4 with UI focus.** With text focus `UiDecide` sends `UiEv::Key` to RmlUi only (`proxy/src/ui_core.h:76-77`), and `WndProc` maps
  `WM_SYSKEYDOWN` and `WM_SYSKEYUP` to that same `Key` event (`proxy/src/ui_host.cpp:400`; the swallow is the final `return 0` at 447). `DefWindowProc` never sees
  the Alt+F4, so the game cannot be closed while an RmlUi field has focus. B53, B58 a, b and c were W20 and are done.

## What exists (read before building)
- **Reports:** `jobs/W33/report.md` (page protections, `StartThread`, `proxy.file_rules`, smoke launches 1-10 and the `open` mode), `jobs/W20/report.md` (the UI host's
  threading: `s_diMask`, `Publish()`, `UiFocusLost`, the lints in `test_ui_core.cpp`), `jobs/W16/report.md` (the null game builds and tests on its own; game host tests;
  `build.sh --docker` mounts). Read the `Deviations` sections: W33 changed `StartThread` to create suspended, and added the row to `null_game_no_gesture` as well.
- **Docs:** `docs/PROXY_SITES.md` (the site contract), `docs/PROXY_CTL.md` (the verbs and the request protocol), `docs/PROXY_UI.md`, `docs/CONSUMING.md`,
  `docs/UPGRADING.md` (where `gen_tables.py` is documented since the 30 KB cap), `docs/BACKLOG.md` (B80 below).
- **The smoke:** `proxy/tools/build.sh` `smoke` (the step list from line 256; launch 8 is the ctl launch with `SITE` from the generated tables, the `at()` helper and
  `nothread()`; launches 9 and 10 are W33's). The exe is `proxy/tests/smoke_host.cpp` (55 lines; args `crash`, `replace`, `wait <file>`, `open <path>`), compiled with
  `"$CXX" -O1 -static` into `$G/$EXE`, where `EXE`, `MOD` and `INI` come from the adapter's `identity.json`. Launch 2 shows the engine path with `exe_guard=0`:
  `patch_engine: REFUSED - N sites: 0 ok, N bad, 0 to write` (anchor bytes are not there).
- **The null game:** `proxy/tests/null_game/` (and `null_game_no_gesture/`, which CI also builds and smokes). Its `registries/engine_sites.jsonl` has two rows that no
  real exe satisfies: `null.dummy_hook` (hook, RVA 0x1000, `dev.camera`, "never installed") and `null.value_distance` (a value row at 0x1100). Its `registries/config_keys.jsonl`
  holds the keys. Regenerate with `WSP_GAME_ROOT=proxy/tests/null_game python3 proxy/tools/gen_tables.py` (same for the no-gesture game).
- **Patch engine:** `proxy/src/patch_engine.h` (`MakePatchPlan`, `WritePlanAtomic`, `WritePages`, `ProtectionRestored`), `proxy/src/patch_driver.cpp` (`WinMem`, the log
  lines). The site layout: anchor at `rva`, stock at `rva + len(anchor)`, a hook detours at `valueRva`; one exe pin per row (`exe: sha1:...`) is checked by `gen_tables.py`
  against the identity, and by the DLL's exe guard at run time (`exe_guard=0` skips it, as launch 2 does).
- **The exe helpers:** `proxy/tools/exe_info.py` has `parse_pe(b)` (sections, image base, `time_date_stamp`, `size_of_image`) and `rva_to_off(pe, rva)`; `discovery/exe.py`
  imports them. `gen_tables.py` (370 lines) has `registry_rows`, `hexbytes`, `validate_sites`, `render_header` and `main` with `--adapter` and `--check`. It is a
  **build-id input** (W24, C25), so the DLL's build id changes with this job even before the C++ does.
- **ctl:** `proxy/src/devcore.h` `ParseCtl` (the `lua` branch at about 424-431, the verb list `CtlVerbs()` at 387) and `proxy/src/dev.cpp`: `RunLua` (138), `LuaDir()` (155),
  the `lua` handler (388-395), the request pass (`MoveFileExW` to `.cmd.taken` at 461-462, `_ids.txt` append at 472), `CtlThread` start (`CreateDirectoryW` and the `_ids.txt` read at
  495-498), the `dev.ctl_dir` default `rt.modDir + L"ctl"` (706). The Lua file itself is opened by the engine side in `proxy/src/luabridge.cpp`.
- **UI:** `ui_core.h` (`UiEv`, `UiDecide`, `UiRouteState`; pure, host-tested in `test_ui_core.cpp`), `ui_host.cpp` `WndProc` (390-447; W20's lints there pin text, so read
  them before editing: some match exact source lines).
- **GameAdapter:** `proxy/src/adapter.h:54`; the null game's `adapter.cpp` and `null_game_no_gesture/proxy/.../adapter.cpp` initialise it positionally.
- **Imports:** the DLL imports advapi32, dbghelp, kernel32, msvcrt and user32 (W33). The ACL call (`ConvertStringSecurityDescriptorToSecurityDescriptorW`, `SetFileSecurityW`) is
  advapi32 and adds no DLL. Anything from another DLL is a kill criterion.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### A. The stand-in exe and the real-process smoke (C5)
1. **A stand-in that carries the sites.** Add `proxy/tests/smoke_standin.cpp` (or extend `smoke_host.cpp` with a second build of itself; the builder chooses, and says which)
   that contains, at fixed RVAs, the byte strings the null game's new site rows name. The mechanism is a linker-placed section: `__attribute__((section(".wsp")))` data plus
   `-Wl,--section-start=.wsp=<VA>` (or a linker script) so the section's RVA is the one in the registry; the build then **checks the RVA** by reading its own PE with
   `exe_info.parse_pe` and fails the smoke setup if the two differ (a Python helper in the smoke is fine, the build image has python3). If mingw's linker cannot pin an
   RVA, patch the built exe's section table and bytes with a short Python script instead; say which.
2. **Null-game rows (both null games).** Add to `engine_sites.jsonl`, with rva, anchor, stock and patch bytes the stand-in carries:
   - `null.smoke_patch`: a **fixed patch** row (`kind: patch`, `patch_bytes` of the same length as `stock_bytes`), keyed by a **new** null config key `null.smoke_patch` (bool,
     default 0, release value 0). The smoke turns it on in its own ini; no other test turns it on.
   - `null.smoke_hook`: a **hook** row (`kind: hook`, at least 5 stock bytes) keyed by an existing key whose hook the core installs without a game callback. **Check
     first which one that is** (read `dev.cpp`, `files.cpp`, `headless.cpp` and the null adapter for a hook the core installs at a site address without the adapter). If the
     core has none, the hook row is **dropped** and the smoke covers the patch and the `peek` only; the report says so and why (kill criterion 3, not a failure).
   - Both rows pin `exe: sha1:1111...` like today's. The smoke runs with `exe_guard=0`, so the pin is not checked at run time, and `gen_tables.py --exe` (decision 5) is told
     to skip the sha1 pin when the stand-in's identity is the null one (a flag `--allow-pin-mismatch`, or the stand-in is built with the null identity's `time_date_stamp`
     and `size_of_image`: the builder chooses the smaller change).
   - The two existing null rows (`dummy_hook`, `value_distance`) stay: they remain refused (the wine smoke still counts them: launch 2's "N bad" line is rewritten to match).
3. **The smoke launch (new launch 11, after W33's 10):**
   `[proxy] backend=system exe_guard=0` and `[dev] ctl=1 ctl_dir=ctl state_json=0` plus `null.smoke_patch=1`; the stand-in `wait`s for `ctl\ping1.done` and
   `ctl\peek1.done`. The script writes `ping` and `peek <null.smoke_patch site> * 4` after `ctl: watching` (the launch 8 pattern; the ctl thread starts at the first
   `Direct3DCreate9`, W33). Checks, all by `check`/`at`:
   - the patch engine accepted the row: `patch_engine: ... 1 to write` (match the real format; do not invent), `patch_engine: protections restored on 1 page(s)` and **no**
     `left changed` line;
   - the hook row (if kept) installed: the log's own install line;
   - `ctl: ping1: ok` and `ping1.done` has `"pong": true`;
   - the peek of the patch site returns the **patch** bytes (the write is live in memory, in the real process), and a peek of an untouched stock site returns stock bytes;
   - the stand-in itself verifies the page protections with `VirtualQuery` on the patched page after the write and prints `smoke: page 0x... protect 0x..`; the script checks it
     equals the section's initial protection (0x20 for code, 0x02 for read-only data; **under wine a section's protection reads back as VirtualProtect set it, check it before
     relying on it**). This is the C3 regression check that W33's report said only a stand-in with a patch can make;
   - `process detach` is **not** required (the host exits without `FreeLibrary` while the ctl thread runs, as launch 8 does).
4. **The new launch's cap.** If after about 40 calls wine does not show the write, the readback line or the peek of patched bytes, **stop the stand-in work**, keep decisions
   B to F (they do not depend on it), commit the null rows and the tool as far as they are green, and report the log. Never weaken the check to "refused" to make it pass.
5. **The final smoke line** becomes `passed (11 launches under wine, 2 dumps)`; the `nothread()` and thread-order checks of W33 are untouched.

### B. `gen_tables.py --exe` (C7)
6. **`--exe <path>`** checks every engine-site row against a staged exe copy, offline:
   - it reads the PE with `exe_info.parse_pe` / `rva_to_off` (import them the way `discovery/exe.py` does; do not copy the parser), compares `time_date_stamp` and
     `size_of_image` with the identity, and the file's sha1 with `identity.json` (`sha1`) and each row's `exe:` pin;
   - for every row it reads `len(anchor) + len(stock)` bytes at `rva` and prints one line per site: `MATCH <id> 0x<rva>`, or `MISMATCH <id> 0x<rva>: <anchor|stock> byte <i>
     is <got>, the row says <want>`; an RVA outside every section is `MISMATCH <id>: rva not in the file`;
   - **relocated dwords:** the DLL compares after taking the load delta off relocated dwords (`ReadUnrelocated`). The file on disk is unrelocated, so the plain compare is
     right; say that in the output header and add a test where the anchor holds an absolute address;
   - exit 0 when all match, 1 on any MISMATCH or identity disagreement, 2 on an unreadable file; it writes nothing (like `--check`, and it runs the same row validation first);
   - with `--exe` and no `--check`, the generated files are not rewritten.
7. **Tests:** `tests/test_gen_tables.py` gets a synthetic PE (a few sections, one site per kind, one value row, one absolute address in an anchor) built in the test, and cases for
   MATCH, a wrong anchor byte, a wrong stock byte, an RVA outside the file, a wrong identity, an unreadable file. The stand-in exe of step 1 is the end-to-end check: the
   smoke runs `gen_tables.py --exe "$G/$EXE"` on it before the first launch, expecting its sites to MATCH (this is also the proof the stand-in carries the RVAs).
8. **B80 rides along** (it says "in the next job that changes `gen_tables.py` anyway"): only rows whose `owner` is `proxy` belong in the generated tables. Do it only if it is
   a few lines with a test that shows a non-proxy owner is skipped and a proxy one is kept; otherwise leave B80 where it is and say so. Remove its row from `BACKLOG.md` if built.
9. **Docs:** a short `--exe` paragraph where `gen_tables.py` is documented (`docs/UPGRADING.md`; `docs/PROXY_SITES.md`'s last lines say how a new site is added: add the
   `--exe` step there). The tools row for `gen_tables.py` in `registries/tools.jsonl` keeps its id; update the `usage:` line in its header and run `python3 wsc.py reg render`.

### C. `GameAdapter` initialisation (C6, core half)
10. **A `static_assert` on `sizeof(GameAdapter)`** in `proxy/src/adapter.h` after the struct, with a message that says what to do: "GameAdapter changed size: initialise it with
    designated initialisers (docs/CONSUMING.md) and update this size in the same change". Pick the size from the 32-bit build, since the DLL is 32-bit; the host tests compile
    on 64-bit hosts and would see a different size, so guard with `#if defined(_WIN32) && !defined(_WIN64)` or assert the **field count** another way (a `constexpr` count
    next to the struct, tested in `test_guard.cpp` against the source's member lines); the builder chooses and says why. The point is a failing build when the struct changes.
11. **The null games' adapters** switch to designated initialisers (C++20 allows them in order; the DLL builds as C++20 already? check the flags in `build.sh` and use `-std`
    that the build uses). If the build is below C++20, keep the positional list and add the comment, and the CONSUMING rule still holds.
12. **`docs/CONSUMING.md`:** a section "DLL changes in <the tag> (W34, C35)": the designated-initialiser rule (a new field is added at the **end** of `GameAdapter`, with a default,
    and the core's own adapters name every field they set), the ctl `lua` limit (E), the ACL (E) and the system-key rule (F). Keep the file under 30 KB: it is at about 29.9 KB, so
    **move or shorten** an older paragraph into `docs/UPGRADING.md` when the section does not fit; add no net bytes beyond the cap.

### D. (reserved) Decision record
13. **`docs/DECISIONS.md`:** one line at the next free C number (read `main`; C35 when written, C34 is taken), "proposed (Claude, core W34)": the smoke exercises a patch and a
    hook in a real process; the ctl `lua` verb reads only under `luaDir` and the ctl folder; the ctl folder is owner-only; system keys always reach the game; `GameAdapter` is
    initialised by name. `wsc policy` asks for the next free number on `main`: re-read it before the last commit (a collision with another open branch: the second to merge renumbers).

### E. ctl `lua` limits, the ctl folder, rotation (C8)
14. **Which paths `lua` accepts.** A pure `LuaPathAllowed(path, gameDir, luaDir, ctlDir, why)` in `devcore.h` (host-tested; no I/O, so it works on the Linux host):
    - normalise: forward and back slashes alike, strip a `\\?\` prefix, **refuse** any `..` segment, any `:` after the drive letter (alternate data streams), a UNC path
      (`\\server\share`), a device path, an embedded NUL;
    - relative paths resolve against the game folder (as today); absolute paths are compared with `gameDir + luaDir` and `ctlDir` after normalisation, case-insensitively;
    - **accept** only a file under `luaDir` or under the ctl folder; the refusal text names the allowed roots: `lua: <path> is outside the lua folder <luaDir> and the ctl folder`;
    - it runs in `ParseCtl`'s caller (it needs the roots; `ParseCtl` stays pure of config) before `RunLua`, so a refused path never reaches the bridge, and the `ctl:` log line
      says `refused`. `CtlVerbs()` and `docs/PROXY_CTL.md` say the new rule; the `lua needs a file (relative to the game folder or absolute)` message changes with it.
    - **Why a roots check and not a hash allowlist:** the harness writes its own chunks into the ctl folder and the game's Lua files live under `luaDir`; both are known paths,
      and a per-file allowlist would need a registry row per chunk.
    - **A consumer risk to name in the report:** napoleon's harness may pass an absolute path outside both folders (a scratch chunk). Search the null game's harness fixture and
      `docs/PROXY_HARNESS.md` for such a use; if one exists in the core, fix it here. For consumers, `CONSUMING.md` says the new rule and the fix (put the chunk under `luaDir` or
      the ctl folder); napoleon J-job follows the pin bump.
15. **Owner-only ctl folder.** After `CreateDirectoryW` in `CtlThread` (and for an existing folder), apply a protected DACL granting full control to the **owner** only, with
    `ConvertStringSecurityDescriptorToSecurityDescriptorW` (`"D:PAI(A;OICI;FA;;;OW)"`) and `SetFileSecurityW` (`DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION`),
    then `LocalFree`. These are advapi32 and kernel32. One log line: `ctl: folder <dir> is owner-only` or `ctl: could not restrict <dir> (error N): continuing`. A failure never
    stops the thread (wine and FAT folders may refuse); the smoke checks the line is one of the two.
    - **Do not** call it from DllMain (the ctl thread starts at the first `Direct3DCreate9` since W33; the call is in `CtlThread`, so the lint "DevInit has no StartThread" stays true).
    - The harness driver runs as the same user, so an owner-only folder does not stop it; a consumer whose driver runs elevated or as another user must say so in the report.
16. **Rotation of `.cmd.taken`, `.done` and `_ids.txt`.** A pure `RotatePlan(names, keepNewest)` (and for `_ids.txt` a pure `TrimIds(text, keepLast)`) in `devcore.h`:
    - at ctl start, after reading `_ids.txt`, delete all but the newest **200** `*.cmd.taken` files (by last write time, ties by name) and rewrite `_ids.txt` to its last
      **4096** ids when it holds more than 8192 (write to a temp name and `MoveFileExW` over it, so a crash never leaves a half file);
    - during the run, do the same every 500 handled requests;
    - **ids are still never reused within a launch**: `s_ids` keeps every id seen in memory, rotation only trims the disk; an id older than the kept window can be reused across launches,
      and a request from an earlier launch is already refused as stale (B40), so that is safe; say so in `docs/PROXY_CTL.md`;
    - `.done` files are **not** deleted (a driver may be reading one); only `.cmd.taken` and `_ids.txt`.
    - The caps are constants in `devcore.h` with a comment, not config keys (no new key; a rotating ctl folder is not a feature a game tunes).

### F. System keys reach the game (C9, Alt+F4)
17. **Pure rule in `ui_core.h`.** Add `UiIsSystemKey(uint32_t msg)`: true for `WM_SYSKEYDOWN` (0x104), `WM_SYSKEYUP` (0x105) and `WM_SYSCHAR` (0x106). The constants are plain numbers in the
    header (no `windows.h` in a pure header), as `gesture_feed.h` does for `kWmCaptureChanged`.
18. **Route.** In `WndProc`, a system-key message is handed to the engine **before** `UiDecide` and never to RmlUi: `return Engine(h, msg, wp, lp)` for the three messages,
    with `GestureMessage` still told (the gesture stage observes every key message and they always pass). `WM_SYSKEYDOWN` stays out of the `Key` case; a plain `WM_KEYDOWN` for
    F4 while Alt is held does not exist (Windows sends `WM_SYSKEYDOWN` with the context bit), so the rule is per message, not per VK.
    - **Why not "only Alt+F4":** menu keys, Alt+Enter and Alt+Tab handling are the game's and the system's too; RmlUi has no use for an Alt-chord. A text field still gets every
      plain key and every `WM_CHAR` (Alt+numpad characters arrive as `WM_CHAR`/`WM_SYSCHAR` pairs: if RmlUi needs them, keep `WM_CHAR` routed as it is and do not touch it).
19. **Tests:** `test_ui_core.cpp`: `UiIsSystemKey` over the three messages and a handful of neighbours (`WM_KEYDOWN`, `WM_CHAR`, 0); the route in `UiDecide` is unchanged (it never
    sees system keys), so test the decision as a pure function `UiRouteMsg(route, msg)` if the builder prefers, or a **source lint**: the three messages are handled before the
    `UiDecide` call in `WndProc`, and `Engine(` is the return. W20's lints that quote `WndProc` lines must still pass; update only the lines this change moves, and say so.
20. **`docs/PROXY_UI.md`:** the Input paragraph says system keys always pass to the game, including with text focus.

## Scope: files this job touches
- **Smoke and stand-in:** `proxy/tests/smoke_standin.cpp` (new) or `smoke_host.cpp`, `proxy/tools/build.sh` (smoke only), the null games' `registries/engine_sites.jsonl` and
  `registries/config_keys.jsonl` and their regenerated `generated/tables.h` and `nullgame.ini`.
- **Generator:** `proxy/tools/gen_tables.py`, `tests/test_gen_tables.py`, `registries/tools.jsonl` (the header row only).
- **DLL:** `proxy/src/adapter.h`, `devcore.h`, `dev.cpp`, `ui_core.h`, `ui_host.cpp`; the null games' `adapter.cpp`.
- **Tests:** `proxy/tests/test_dev.cpp` (the `LuaPathAllowed`, `RotatePlan`, `TrimIds` and ACL-line tests, plus lints), `test_ui_core.cpp`, `test_guard.cpp`, `test_config.cpp` only if
  a key is added.
- **Docs:** `docs/CONSUMING.md`, `docs/UPGRADING.md`, `docs/PROXY_CTL.md`, `docs/PROXY_SITES.md`, `docs/PROXY_UI.md`, `docs/DECISIONS.md`, `docs/BACKLOG.md` (B80 if built; remove a row
  for every row added).
- **Not touched:** `VERSION` (C27: the Semver line above is the version), `patch_engine.h`, `patch_driver.cpp`, `headless.cpp`, `files.cpp`, `backend.cpp`. No game names in core files.

## Steps
1. Read "What exists" and the three reports. Check this session can build and run the host tests and the smoke (`proxy/tools/build.sh --docker all`, then `--docker smoke`). If not,
   push early and read CI's `proxy` job; budget the extra calls.
2. **Red first, at run time where possible.**
   - `tests/test_gen_tables.py`: the `--exe` cases, red against today's generator (the flag does not exist; the run fails with an argparse error: commit with that output).
   - `test_ui_core.cpp`: a lint "system keys are handed to the engine before `UiDecide`" that fails against today's `WndProc`.
   - The C++ unit tests for `LuaPathAllowed`, `RotatePlan` and `TrimIds` name absent functions, so they are red at compile time, as W33's were; say that in the commit message.
3. **Build B** (`--exe`), then run it on the synthetic PE. Green. Then **F** (system keys), **E** (lua limits, ACL, rotation), **C** (static_assert, designated initialisers).
4. **Build A.** Add the null rows and the new null key, regenerate both null games, build the stand-in, make `gen_tables.py --exe` MATCH it, then write launch 11. Do the decisions
   with the fewest moving parts first: the patch row and the `peek`, then the readback, then the hook row (if the core has a hook to install).
5. Update every smoke check the new rows move (launch 2's count line, launch 8's peek site: `SITE` is "the first engine site of the game", which is now `null.dummy_hook`
   by RVA order; the stand-in's rows must not become the first site by accident: keep their RVAs above 0x1100, or pin the old site by name in the script).
6. Docs, decision, backlog (C, D, B80). Then `python3 wsc.py gates` (full), `python3 wsc.py policy --branch job/W34 --base origin/main`, and CI's `proxy` job green on the pushed
   branch.

## Tests and acceptance: what each layer can prove
- **Host tests (CI, every push):** `LuaPathAllowed` (a table: relative, absolute under each root, `..`, a drive other than the game's, UNC, ADS, case, slash styles, an empty root),
  `RotatePlan`, `TrimIds` (exactly at, one over, empty, one id longer than the window), `UiIsSystemKey`, the `WndProc` lint, the `gen_tables.py --exe` cases, the existing tests on the
  regenerated null tables.
- **Wine smoke (CI):** launch 11: the patch write, the readback line, the peek of patched bytes, `ping`, the page protection, the `ctl: folder` ACL line; `gen_tables.py --exe` on the
  stand-in. The existing 1-10 still pass. It cannot show: Windows' real ACL semantics, an Alt+F4 with an RmlUi field focused, a hook installed into the game's own code.
- **Only the consumer's PC run:** the ACL on NTFS, the system-key route in a real window (type in a text field, press Alt+F4: the game closes), and that the harness's `lua` chunks
  still run under the new path rule. Napoleon's pin-bump job records these with the run id (rule 79: 20 passes on the new build id; this job changes DLL inputs and the generator).
- No new DLL import: the list stays advapi32, dbghelp, kernel32, msvcrt, user32 (plus whatever W24 and W33 added). Every written byte of a **real** table stays identical; the test
  that compares `ApplyPlanToBuffer`'s output with the written bytes covers the stand-in's patch too.

## Semver
`minor` (the row says the same): a new generator flag, new behaviour in the shipped DLL (the `lua` limit and the folder ACL can refuse what worked, system keys now pass), a new
smoke. The release workflow computes the tag; the job does not edit `VERSION`. If a consumer's harness breaks on the `lua` path rule, a later row loosens it; do not ship a
loophole to avoid that.

## What consumers must do after the tag (napoleon-remastered, the pin-bump job after J78)
- **Build id:** `gen_tables.py`, `proxy/src` and the generated tables change, so the build id changes; rule 79's 20 passes.
- **`GameAdapter`:** the napoleon `adapter.cpp` keeps compiling only if its size assert passes; J64 switches it to designated initialisers. Until then it keeps its positional list and
  the `static_assert` it gets from the core must still hold (it does: no field is added in this job).
- **Harness:** every `ctl lua <file>` path must be under `luaDir` or the ctl folder. List the harness's chunks and move any outside; record the run id.
- **`gen_tables.py --exe`:** add it to the napoleon exe-update checklist: `python3 core/proxy/tools/gen_tables.py --exe <staged copy>` after `exe_info.py`, before a PC run.
- **Checks recorded with the run id:** (1) no `could not restrict` line on the PC; (2) Alt+F4 with a focused text field closes the game; (3) the ctl folder's ACL shows one ACE.

## Kill criteria
- The patch write in the stand-in would need any call but VirtualProtect, VirtualQuery and FlushInstructionCache, or would write a byte `ApplyPlanToBuffer` does not: stop and report.
- The owner-only ACL needs a DLL beyond advapi32 and kernel32, or fails on a plain NTFS folder in a way a test can reproduce: stop and report; do not weaken to "everyone".
- The core has no hook it installs without a game callback: drop the hook row and report it (not a failure, decision 2).
- After about 40 calls wine does not show the write, the readback or the peek of patched bytes (decision 4): stop the stand-in work, keep B-F, report the log.
- A system-key change would alter how a plain key or a `WM_CHAR` reaches a text field (the `test_ui_core` exhaustive tests change): stop and report.
- The `GameAdapter` assert cannot be written for both the 32-bit DLL and the 64-bit host build: use the field-count form of decision 10, and if that has no clean form, stop and report.
- Core CI red after three fix attempts for a cause in this change: stop and report. A decision-number collision follows `wsc policy`; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Where `lua` may read.** `luaDir` plus the ctl folder (recommended), or `luaDir` only. Recommended: both. The harness writes chunks into the ctl folder; `luaDir` only would force a
   second channel.
2. **Whether `ctl_dir` outside the mod folder is allowed.** Recommended: allowed, and the ACL applies wherever it is, because a dev who points it at a shared folder gets the owner-only
   rule too. The report says if the ACL changed an existing folder the player owns.
3. **Rotation windows.** 200 `.cmd.taken` files and 4096 ids (recommended). They are constants, not keys.
4. **Designated initialisers.** Core's null adapters switch now (decision 11); napoleon's switch is its J64. Recommended: yes, the core's own adapters should show the rule.
5. **The hook row.** Kept only if the core installs a hook without a game callback (decision 2). If none exists, a follow-up row adds a core-owned test hook; it is not this job.

## Finish
Write the report in `jobs/W34/report.md`. Cover:
- what was built, per decision (A-F);
- the tests, red (step 2's output) then green, and where they ran;
- the smoke: launch 11's log lines for the write, the readback, the peek and the page protection; whether the hook row was kept, and why not if it was dropped;
- the decision number taken, deviations, open questions, and what napoleon must do.

Then run `wsc reg set jobs W34 status=review report=jobs/W34/report.md` (`python3 wsc.py`). Push `job/W34`, open the draft pull request, and stop: an independent reviewer merges (C18).
