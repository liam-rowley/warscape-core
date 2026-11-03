# W17 report: Dev channel: stale ctl requests and a read-only peek

The proxy's dev control channel now refuses a request whose `.cmd` was last written before the game process was created (B40): the request is taken, its id is recorded as used, a `.done` with `status: "refused"` and the reason `stale: written <utc>, before this launch started <utc>: a request from an earlier launch (resend it)` is written, one warning is logged, and it is never run. A new read-only ctl verb `peek <site>[+|-<off>] [*[+|-<off>] ...] <len>` reads 1 to 512 bytes from an address derived from an accepted engine site through up to 8 pointer hops, checking every hop and the final range as readable, and never writes (the `peek` half of B25; B25 is reworded to the `watch` half). The grammar, the hop resolution and the result JSON are pure and host-tested on a fake memory; the wine smoke proves both refusals end to end. VERSION 0.18.0.

## What was built
- `proxy/src/devcore.h`:
  - `CtlStale(writeUnixMs, processStartMs)`: true only when the start is known (>= 0) and the write time is strictly before it.
  - `CtlStaleReason`.
  - `ParsePeekArgs` (grammar above; `PeekGrammar()`). Offsets are decimal or `0x` hex, at most 0xffffffff. No raw address: a number in the site's place is refused. Site ids are letters, digits and `._:/#-` (at most 120).
  - `ResolvePeek(siteAddr, args, readU32)`: 32-bit wrapping arithmetic. Each hop reads a pointer, refuses null, then adds its offset. A stop records the 1-based `failedHop`. A range that runs past 4 GB is refused.
  - `PeekResultJson`, with members `site`, `site_addr`, `hops [{at, ptr}]`, `addr`, `len`, `failed_hop` on a stop, `hex`, and for whole dwords `u32` and `f32` (`%.9g`; `"nan"`, `"inf"`, `"-inf"` as strings).
  - `peek` in `ParseCtl` (no trailing timeout; default 10 s through `CtlDefaultTimeout`) and in `CtlVerbs()`.
- `proxy/src/dev.cpp`:
  - `CtlThread` passes each file's `ftLastWriteTime` (as Unix ms) to `HandleRequest`, which refuses a stale request after the id checks and after recording the id. When `GetProcessTimes` failed, the thread logs one warning at its start and accepts every request.
  - `Peek()` checks, in order: the site is in the adapter's table (`unknown site '<id>' (not in this game's engine_sites)`), then `SiteAddress(site) != 0` (`sites not accepted by the patch engine: <rt.sitesWhy>`). Then it resolves through `MemReadable`, checks the final range, copies, and answers.
- `proxy/src/patch_driver.cpp` and `runtime.h`: the existing readability check is now the shared `wsp::MemReadable` (declared in `runtime.h`; a wrap guard was added). Its behaviour is otherwise unchanged; `SiteAddress` is untouched.
- `proxy/tests/smoke_host.cpp`: a `wait <file>` mode (waits up to 60 s for a file, then exits without `FreeLibrary` because the ctl thread is still inside the DLL).
- `proxy/tools/build.sh smoke`: launch 8.
  - Before the launch, an `exit` request is written and dated 2020 with `touch -d`.
  - After the log shows `ctl: watching`, `peek null.dummy_hook * 4` is written.
  - The launch checks the stale log line and both `.done` refusals, and that the stale `exit` never ran.
- Docs:
  - `docs/PROXY_CTL.md` (new): the core's channel rules, the stale refusal and `peek`.
  - `docs/CONSUMING.md`: two lines in "The proxy, the harness and the save tools".
  - `docs/BACKLOG.md`: B40 removed; B25 reworded to the `watch` site kind only.
  - `harness/job.sh`: the ctl comment points at `docs/PROXY_CTL.md`.
  - `VERSION` 0.18.0.

## Tests, red then green
- **Red:** commit `W17: failing host tests ...` adds the `test_dev.cpp` cases:
  - `CtlStale`: before, equal, after, unknown start, and the reason text.
  - `ParsePeekArgs`: site alone, `+0x10`, `-8`, decimal, 1 to 8 hops, 9 refused, lengths 0 and 513 refused, `0x401000` / `0x401000+4` / `4198400` refused as raw addresses, 22 junk forms refused directly and through `ParseCtl`, `peek` with no argument, no trailing timeout, the `-` in an id rule.
  - `ResolvePeek` on a fake memory: two hops; a null pointer stops at hop 2 with its address; an unreadable hop stops at hop 2 and at hop 1; negative offsets wrap (`4 - 8 = 0xfffffffc`, site `0x10 - 0x20 = 0xfffffff0`); a range past 4 GB is refused.
  - `PeekResultJson`: hops, hex, u32 and f32 views, NaN and -inf as strings, pi as `3.14159274`, no views under a dword, a stopped result with `failed_hop` and no bytes.
  - Compiled against the previous `devcore.h` in an ubuntu:24.04 container: 22 compile errors (`'CtlStale' was not declared in this scope`, ...).
- **Green:** `test_dev: 296 passed, 0 failed`, with every proxy host test passing (`build.sh all` in an ubuntu:24.04 container on the null game, 2026-11-03).
- **CI** run 41718572763 on f04299a (2026-11-03): `proxy` green (`test_dev: 296 passed`, `build.sh repro: identical from another path`, `build.sh smoke: passed (8 launches under wine, 2 dumps)`), `gates` on Linux and Windows green, `harness-windows` green.
- **Full gates locally:** 13 ok, 1 warn (skipped host tests: the POSIX hook test and capstone), 0 failed.

## The smoke step (ran)
Launch 8 under wine (the local container, then CI), proxy.log:
- `ctl: old1: refused: stale: written 2020-01-02T03:04:05.000Z, before this launch started 2026-11-03T21:10:52.921Z: a request from an earlier launch (resend it)`
- `ctl: peek1: refused: sites not accepted by the patch engine: site 'null.dummy_hook' (RVA 0x1000): ANCHOR MISMATCH at byte +0`

`old1.done` and `peek1.done` both say `"status": "refused"` with those reasons, and the stale `exit` never ran (the launch lived on to answer the peek). The positive `peek` path on a real exe is the consumer's to prove; the core proves it on the fake memory.

## Kill criteria checked
- **No core driver writes a `.cmd` before its launch returns.** `harness/ctl.py` `launch` sends `waitfor frontend` only after the watcher's `launch` job returns. `harness/acceptance.py` goes through it. The watcher returns only after `Start-Process` of the exe, or after a game process appeared on the steam route. Residual, not a demonstrated path: if a store front ever relaunched the exe after that first process appeared, a request sent in that gap would be refused as stale, never mis-run.
- **`peek` reaches sites through `SiteAddress`.** Its acceptance rule is unchanged and no raw address is accepted.
- **Nothing writes game memory or installs a hook.**

## Version
0.18.0. At the last check, origin/main was at 0.16.0 and the open branches were W14 0.17.0 and W11 0.17.1, so 0.18.0 was the next free minor.

## What napoleon must do after the tag
- The DLL inputs change, so the pin bump that crosses v0.18.0 needs 20 consecutive acceptance passes on the new build id (rule 79).
- In `proxy/README.md` "Dev control channel", add the stale rule and the `peek` grammar, or point at the core's `docs/PROXY_CTL.md`.
- A hand-run `job.sh ctl` issued before `job.sh launch` returns is now refused as stale (exit 2): resend it. `ctl.py` and `acceptance.py` are unaffected.
- To probe `transport_to_region` (J40's open fact), add an `engine_sites` row whose accepted address leads to the data (a site whose operand is the global, then `*` hops), its check, and the probe. Optionally add `peek` to the verb list in the `dev.ctl` key description.

## Deviations from the brief, and why
1. **The shared helper is `MemReadable`, not `Readable`.** `guard_driver.cpp` keeps an anonymous `Readable(const void*, size_t)` with the same signature, so a `wsp::Readable` in `runtime.h` would make its calls ambiguous. Consolidating that copy was out of scope.
2. **A `-` can be part of a site id**, which makes `site-2` ambiguous. Rule: the offset is the number after the last `+` or `-`; `+0` keeps an id that ends in `-<n>` (`slot-2+0`). Tested and documented.
3. **`smoke_host.cpp` gained a `wait <file>` mode** so the stand-in exe stays alive for the ctl thread. The smoke step needed it and the brief allowed the file.
4. **A new contract doc `docs/PROXY_CTL.md`** ("the core doc you write" in the brief). It has no README table row, like PROXY_UI and PROXY_GESTURES.
5. **Peek reads have no exception guard.** Pages are checked with `VirtualQuery`, then copied. A page freed between the two would fault, as with the existing in-process probes; mingw g++ has no `__try`. Said in the doc.
6. **Built on Opus** (Liam's choice); the brief names Sonnet.
7. **Report and row:** the build ran as a subagent, which cannot write report files, so the orchestrator wrote this report from the builder's text and set the row to review (same Claude-Session as the build).

## Open questions
1. B25 `watch` stays a backlog row; build it (Opus) only if a `peek` probe leaves napoleon's `napoleon.console.transport_to_region_no_move` open.
2. The stale check compares the file's last write time with the process creation time, both from the PC's clock. A request written onto the PC over a network share would carry the file server's clock: none of the core drivers do that today.
