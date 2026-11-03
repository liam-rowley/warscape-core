## Round 1 (2026-11-03, branch job/W17 at bb800bf)
**Verdict: merge.**

Reviewed cold against the brief. `wsc gates` ran 13 ok and 1 warn (skipped host tests that need POSIX sh and capstone), 0 failed. The `proxy` CI job was green on f04299a:
`test_dev: 296 passed`, `build.sh repro` identical, `build.sh smoke` passed with 8 launches (run 41718572763). The run on the report commit was still going when I read it.

Read in depth, because they run inside the game process: `proxy/src/dev.cpp` `Peek()` and the stale branch of `HandleRequest`, `devcore.h` `ParsePeekArgs`/`ResolvePeek`, and the `MemReadable` move in `patch_driver.cpp`.
- **Stale (B40):** `CtlStale` is the strict comparison the brief asks for and fails open on an unknown start. The id is recorded as used before the check, and the `.done` is written. The request never reaches `Execute`.
- **Peek (B25):** it starts only from `SiteAddress`. No raw address is accepted, and no write path exists. Every hop and the final range go through `MemReadable` first. The 32-bit wrap and the null-hop stop are covered by the host tests on a fake memory.
- **Smoke launch 8:** it proves both refusals end to end, and the stale `exit` never ran.
- **Deviations** (all named in the report with reasons): `MemReadable` instead of `Readable` because of the `guard_driver.cpp` name clash; a trailing `-<n>` in a site id is ambiguous, with `+0` as the escape, tested and documented; `smoke_host.cpp` got a `wait` mode; the new `docs/PROXY_CTL.md`.

Merge conflict: `VERSION` conflicted with main (W14 took 0.17.0 after this branch was cut). I merged `origin/main` into the branch (no rebase) and kept 0.18.0, the next free minor. `BACKLOG.md` and `CONSUMING.md` merged automatically, and the fast gates pass on the merge.

### Blocker
None.

### Should-fix
None.

### Later
- The stale rule compares the file's write time with the process creation time on the PC's clock. A `.cmd` written over a network share would carry the file server's clock (the report's open question 2). No core driver does that. Revisit only if one starts to.
- `MemReadable` is the copy `patch_driver.cpp` already had, now exported. The other four (`guard_driver.cpp`, `camera.cpp`, `console.cpp`, `orders.cpp`) could move onto it: a future cleanup, outside this job.
