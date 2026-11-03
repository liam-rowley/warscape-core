# W17: Dev channel: stale ctl requests and a read-only peek

Model: Sonnet, reason: none needed (Sonnet is the default). Two small changes to the proxy's dev control channel with pure, host-tested cores; no reverse
engineering, no engine write, no PC. Budget about 90 tool calls (the C++ host tests may only run in CI if the session has no MinGW g++: allow for CI round trips).
At the cap, stop, commit, and report what is left.

## Goal
Two items from napoleon-remastered sittings (`docs/BACKLOG.md` B40 and B25; B40 removed and B25 reworded when this merges):
- **B40, stale requests.** The proxy runs every `<dev.ctl_dir>\<id>.cmd` it finds. `harness/job.sh ctl` withdraws its own request when it times out, but a driver
  that is killed while it waits leaves its `.cmd` behind, and the next launch runs it (napoleon J9, `jobs/J9/report.md` "Harness trouble": "a stale ctl request ran
  in the next launch"). The proxy refuses a request written before its own process started.
- **B25, a read-only peek.** A console command that runs but changes nothing cannot be told apart today (a lookup that returns null, or a later check that fails),
  and each answer costs a new detour (napoleon J40, fact `napoleon.console.transport_to_region_no_move`). A ctl verb `peek` reads memory at an address derived from
  an accepted engine site, through pointer hops, and never writes.

## What exists (read before building)
- The channel: `proxy/src/dev.cpp` `CtlThread` (lists `*.cmd` with their `ftLastWriteTime`, sorted, then `HandleRequest` each: rename to `.cmd.taken`, refuse a bad
  or used id, `ParseCtl`, `Execute`, write `.done` atomically) and `proxy/src/devcore.h` (the pure grammar: `CtlRequest`, `CtlVerbs()`, `CtlDefaultTimeout`,
  `ParseCtl`; host tests in `proxy/tests/test_dev.cpp`). The driver side: `harness/job.sh ctl` (exit 0 ok, 1 failed, 2 refused, 3 timeout, 124 no answer).
- Process start: `dev.cpp` sets `s_tl.processStartMs` from `GetProcessTimes` at init (Unix ms; `FileTimeToUnixMs` in `hooks.cpp`, declared in `runtime.h`).
- Sites: `patch_driver.cpp` `SiteAddress(id)` returns `base + rva + len(anchor)` of an `engine_sites` row only when the exe-identity guard and the patch engine
  accepted every site (`rt.sitesAccepted`), else 0. Camera, console and orders read their operands through it (`Operand(site, off)`).
- A Lua probe already exists: `wsp.peek(addr, n)` (`luabridge.cpp`, `orders.cpp` `OrdersPeek`), behind `dev.orders`, on a raw address. This job does not change it.
- Readability checks (`VirtualQuery`: committed, not `PAGE_NOACCESS`/`PAGE_GUARD`) are copied in `patch_driver.cpp`, `guard_driver.cpp`, `camera.cpp`, `console.cpp`
  and `orders.cpp`.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### B40
1. A pure function in `devcore.h`, `CtlStale(int64_t writeUnixMs, int64_t processStartMs) -> bool`: true when `processStartMs >= 0` and the request's last write
   time is strictly before the process creation time. No slack: process creation precedes the DLL's load, so a request written after `CreateProcess` is always
   accepted, and no core driver writes a request before its launch returns (`harness/ctl.py` `launch` sends `waitfor frontend` only after the watcher's `launch` job).
2. `CtlThread` passes each file's write time to `HandleRequest`. A stale request is taken (renamed to `.cmd.taken`, as now), its id is recorded as used, and a `.done`
   is written with `status: "refused"` and the reason `stale: written <utc>, before this launch started <utc>: a request from an earlier launch (resend it)`, plus one
   `LOGW` line. It is never executed. A `.done` is written so a driver that is somehow still waiting gets an answer (job.sh exit 2) instead of a timeout.
3. When `processStartMs` is unknown (`GetProcessTimes` failed), requests are accepted and one warning is logged at the thread start (fail open here: the channel is a
   dev tool, and refusing everything would look like a dead proxy).

### B25
4. **`peek` only; the `watch` site kind is not built here.** `watch` (log a function's return value) needs a generic return detour on any engine function (prologue
   copy, a per-thread return stack, an executable thunk): a code write in the game with a crash risk, Opus work. B25 is reworded to the `watch` half and stays a
   backlog note (see Open questions 1).
5. **Grammar** (pure, `devcore.h` `ParsePeekArgs`, cases in `test_dev.cpp`): `peek <site>[+|-<off>] [*[+|-<off>] ...] <len>`.
   `<site>` is an `engine_sites` id (the generated table's ids; letters, digits, `._:/#-`), `<off>` decimal or `0x` hex, at most 8 `*` hops (each reads a 4-byte
   pointer at the current address, refuses a null pointer, then adds its offset), `<len>` 1 to 512 bytes (the Lua probe's limit). No raw absolute address is
   accepted: every read starts at an accepted site. Default timeout 10 s (`CtlDefaultTimeout`), no trailing timeout argument. Add `peek ...` to `CtlVerbs()`.
6. **Guard:** `dev.ctl` on (the channel itself; default off in release) and `SiteAddress(site) != 0`, i.e. the exe-identity guard passed and the patch engine
   accepted the sites. Refusals name the reason (`unknown site`, `sites not accepted by the patch engine: <rt.sitesWhy>`). No new config key: see Open questions 2.
7. **Read:** every hop and the final range checked readable before it is read (one shared helper; reuse the `patch_driver.cpp` `Readable` by declaring it in
   `runtime.h`, do not add a sixth copy; consolidating the other four copies is not in scope). Reads happen on the ctl thread; a racing write by the game can make a
   value torn, which is fine for a probe and said in the verb's doc line.
8. **Result** (`.done`, rules 77 and 78 of the consumer: the result is the readback): `{"site", "site_addr", "hops": [{"at", "ptr"}, ...], "addr", "len", "hex",
   "u32": [...], "f32": [...]}` (the two views only for whole dwords; floats with `%.9g`, non-finite as strings). The resolution is pure and host-tested with a fake
   memory (`ResolvePeek(siteAddr, args, readU32) -> {addrs, error}`), so the hop arithmetic, the null-pointer stop and the unreadable stop are tested without Windows.

## Scope: files this job touches
`proxy/src/devcore.h` (`CtlStale`, `ParsePeekArgs`, `ResolvePeek`, the grammar and verb list), `proxy/src/dev.cpp` (stale check in `HandleRequest`/`CtlThread`;
`peek` in `Execute`), `proxy/src/runtime.h` and `proxy/src/patch_driver.cpp` (expose `Readable`; no behaviour change), `proxy/tests/test_dev.cpp` (stale cases,
peek grammar and resolution), optionally `proxy/tools/build.sh` and `proxy/tests/smoke_host.cpp` (see step 4), `harness/job.sh` (only its comment that cites
`proxy/README.md`: point it at the core doc you write), `docs/CONSUMING.md` ("The proxy, the harness and the save tools": two lines on the stale rule and `peek`),
`docs/BACKLOG.md` (remove B40; reword B25 to `watch` only), `VERSION`. No game names in core files (`tests/test_moved_tools.py` `NoGameNames`).

## Steps
1. Read the files in "What exists". Check whether this session can build the host tests (`proxy/tools/build.sh tests` needs `g++-mingw-w64-i686` or Docker; the
   null-game Docker build is B16, W16). If not, the tests run in CI's `proxy` job: push early and read its log.
2. **Failing tests first**, committed red, in `proxy/tests/test_dev.cpp`: `CtlStale` (before, equal, after, unknown start); `ParsePeekArgs` (a site alone with a
   length, `+0x10`, `-8`, decimal, 1 to 8 hops, 9 hops refused, length 0 and 513 refused, a raw `0x401000` refused as a site, junk refused, `peek` with no argument);
   `ResolvePeek` with a fake memory (two hops, a null pointer stops with its hop index, an unreadable hop stops, negative offsets wrap correctly in 32 bits).
3. Build B40 (decisions 1 to 3), then B25 (decisions 4 to 8).
4. **Smoke (optional, kill-limited):** if the wine smoke can run the ctl thread long enough, add one launch to `build.sh smoke` with `dev.ctl=1` and a `.cmd`
   whose write time is set before the launch (`touch -d`), and check the log's `stale` line and the `.done`'s `refused`. The null game's one site is refused by
   design (no real exe), so a `peek` there can only show the `sites not accepted` refusal; add it if the same launch allows. Drop this step after about 15 calls
   if the stand-in exe exits before the ctl thread runs, and say so in the report.
5. Docs, backlog, `VERSION`; then `python3 wsc.py gates` (full), CI's `proxy` job green, and `python3 wsc.py policy --branch job/W17 --base origin/main`.

## Tests and acceptance
- The `test_dev.cpp` cases above red first, then green, with every existing proxy host test; null-game `build.sh all`, `repro` and `smoke` green in CI.
- `CtlVerbs()` lists `peek`; a `peek` with `dev.ctl` on and refused sites answers `refused` with the patch engine's reason (smoke, or reasoned from the code path in
  the report if step 4 was dropped).
- The positive path of `peek` on a real exe is the consumer's to prove (below); the core proves it on the fake memory.

## VERSION
A minor bump (a new ctl verb and a changed channel behaviour; the DLL inputs change). Take the next free minor at merge time: `origin/main` says 0.15.0 when this
brief was written and other W rows (W7 to W21) may claim minors first. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit; the
second to merge takes the next free number and merges `main` (never rebase). Say in the report which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered)
- The DLL inputs change, so the pin bump that crosses this tag needs 20 consecutive acceptance passes on the new build id (napoleon rule 79), like any proxy change.
- `proxy/README.md` "Dev control channel": add the stale rule and the `peek` grammar (or point at the core doc).
- A driver that writes a request before its game process exists now gets `refused: stale`; none of napoleon's drivers do (they go through `ctl.py`/`job.sh`
  after `launch`), but a hand-run `job.sh ctl` issued before `job.sh launch` returns will be refused: resend it.
- To use `peek` on `transport_to_region` (J40's open fact), the consumer needs an `engine_sites` row whose accepted address reaches the data to read (a site whose
  operand is the global, then `*` hops); that row, its check and the probe are napoleon's work, not this job's.

## Kill criteria
- The stale check would refuse a request a core driver sends in a normal launch (any `harness/` or `proxy/tools/` path that writes a `.cmd` before the launch job
  returns): stop and report the path; do not add slack to hide it.
- `peek` cannot reach a site address without changing `SiteAddress`'s acceptance rule (all sites accepted) or reading through a raw address: stop and report.
- Anything that would write game memory or install a hook: out of scope, stop.
- Core CI red (the `proxy` job included) after three fix attempts for a cause in this change: stop and report.
- Version collision handled as in VERSION above; never rebase a pushed branch.

## Open questions (with recommendations; the brief follows the recommendation unless Liam says otherwise)
1. **`peek` now, `watch` later?** Recommended: yes (decision 4). `peek` with pointer hops answers "did the lookup fill the object it should" without a detour and with
   no write; `watch` is the only way to see a return value that is never stored, but it is a generic code hook. If J40's question still needs it after a `peek`
   probe, B25 (reworded) becomes an Opus row of its own.
2. **A dedicated `dev.peek` key?** The Lua probe sits behind `dev.orders`. Recommended: no new key: `dev.ctl` is already a dev-only key (off in release) and the
   site guard is the identity check B25 asks for; a new key would need a `config_keys` row in every game and the null game for no extra safety.
3. **Hex or decimal offsets only?** Recommended: both (`0x` prefix), since site offsets in reports are written in hex.
4. **File overlap with the other core rows (W7 to W21)**, for whoever merges second (merge `main`, never rebase):
   - **W7** (engine-site patch values: `value_offset`, numeric values from config keys): `proxy/src/patch_driver.cpp` and `patch_engine.h` (site table and plan).
     This job only exposes `Readable` there; if W7 moves `SiteAddress` to the value offset, `peek`'s base address moves with it, and the docs must say which.
   - **W19** (capture: timeout path, render thread only, state blocks): `proxy/src/dev.cpp` (`Execute`'s capture branch) and possibly `devcore.h`.
   - **W20** (UI host and gesture hardening, incl. `ctl gesture press`): `proxy/src/devcore.h`/`dev.cpp` only if it touches the gesture verb's parse; otherwise
     `gesture.cpp`, `ui_host.cpp`.
   - **W16** (the null game builds and tests on its own): `proxy/tools/build.sh` and the null game's files, if step 4 adds a smoke launch.
   - **W12** (stale moved paths lint, B24): `harness/job.sh` comments; **W10** (watcher and job.sh races): `harness/job.sh` (the `lock` code, not `ctl`).
   - All rows: `docs/BACKLOG.md`, `docs/CONSUMING.md` and `VERSION`.

## Finish
Report in `jobs/W17/report.md` (what was built, the tests red then green, where they ran, whether the smoke step ran, the version taken, deviations, open
questions, what napoleon must do), then `wsc reg set jobs W17 status=review report=jobs/W17/report.md` (`python3 wsc.py`). Push `job/W17`, open the draft pull
request, and stop: an independent reviewer merges (C18); Liam tags.
