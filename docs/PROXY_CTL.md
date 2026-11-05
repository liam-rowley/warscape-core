# The proxy's dev control channel: core rules

Owner of: the rules the core's control channel enforces for every game (`proxy/src/dev.cpp` `CtlThread`, `HandleRequest`, `Execute`; the pure
grammar in `proxy/src/devcore.h`, host-tested in `proxy/tests/test_dev.cpp`; the wine smoke's launch 8 in `proxy/tools/build.sh`). The
channel's file protocol and per-verb guide stay in the game's `proxy/README.md` "Dev control channel" until they move here; the driver side is
`harness/job.sh ctl` (exit 0 ok, 1 failed, 2 refused, 3 timeout, 124 no answer).

From 0.29.0 (W10) `job.sh ctl <owner> ...` needs the game lock: the owner or the session of the lock must be `<owner>` (`job.sh holds <owner>`; take it with `job.sh lock`), and its default wait is 100 s, not 170.

## The protocol in one paragraph
With `dev.ctl=1` the proxy watches `<dev.ctl_dir>`: a request is `<id>.cmd` (one line, a verb and its arguments), taken by renaming it to
`<id>.cmd.taken`, answered by `<id>.done` (JSON, written atomically, last). Requests run one at a time, oldest write time first. An id is
1 to 64 of `A-Za-z0-9._-`, not starting with `.` or `_`, and never reused within a launch or while its `.done` exists (`_ids.txt` keeps them across launches, see "The folder"). `CtlVerbs()` lists the verbs.
The ctl thread starts at the game's first `Direct3DCreate9`, never in DllMain (W33, C29; `thread: dev.ctl started` in `proxy.log`). A
request written between process start and then waits for it and is not stale: it was written after the process was created.

## Stale requests (0.18.0, W17)
A request whose file was last written **before this process was created** is from an earlier launch (a driver killed while it waited
leaves its `.cmd` behind). It is taken, its id is recorded as used, and it is answered `refused` with the reason
`stale: written <utc>, before this launch started <utc>: a request from an earlier launch (resend it)`, plus one warning line in
`proxy.log`. It is never run. There is no slack: process creation precedes the DLL's load, and no core driver writes a request before its
launch returns, so a hand-run `job.sh ctl` issued before `job.sh launch` returns is refused: resend it. When the process start time is
unknown (`GetProcessTimes` failed) every request is accepted and the ctl thread logs one warning at its start.

## `lua`: which files it reads (W34, C8)
A chunk runs with the game's rights, so `lua <file>` reads only under the game's Lua folder (`DevAdapter::luaDir`) and the ctl folder (`LuaPathAllowed`,
`proxy/src/devcore.h`, host-tested). A relative path, and a relative `dev.ctl_dir`, resolve against the game folder; `/` and `\`, a `\\?\` prefix and ASCII case do not
matter. Refused, never resolved: a `..` segment, a segment ending in a dot or a space, `:` after the drive (an alternate stream, `C:x`), a rooted path with no drive,
UNC and device paths, a reserved device name, a NUL. The answer is `refused`, the reason `lua: <path> is outside the lua folder <luaDir> and the ctl folder`, and the
bridge never sees the path. Links are not followed: a junction under a root is the folder owner's to make. A driver's scratch chunk goes in the ctl folder.

## The folder (W34, C8)
- **Owner-only.** The ctl thread gives `<dev.ctl_dir>` a protected DACL with one ACE, full control for the user the game runs as (`D:PAI(A;OICI;FA;;;<user SID>)`, wherever the folder
  is, new or existing), and logs `ctl: folder <dir> is owner-only`, or `ctl: could not restrict <dir> (error N): continuing`: a failure never stops the channel (FAT may refuse). The ACE
  names the user, not OWNER RIGHTS (`OW`): wine maps `OW` to mode 000 and reports success. Files made
  from then on inherit it; a file already there keeps its old ACL (`SetFileSecurityW` does not walk the folder). A driver that runs as another user than the game
  cannot use the folder: it must run as the game's user.
- **Rotation.** At ctl start and every 500 handled requests the disk keeps the newest 200 `*.cmd.taken` files and, once `_ids.txt` holds more than 8192 ids, its last
  4096 (`devcore.h` constants, no key). `.done` files are never deleted: a driver may be reading one. Every id stays refused for the whole launch (the set in memory), and
  an id whose `.done` exists stays refused for good. An id older than the kept window with no `.done` can come back in a later launch, which is safe: a request from an earlier launch is refused as stale.

## `peek`: a read-only probe (0.18.0, W17)
    peek <site>[+|-<off>] [*[+|-<off>] ...] <len>

- `<site>` is an `engine_sites` id of the game; its base address is the patch engine's checked one (`SiteAddress`: rva + the anchor's
  length, the same address hooks and patches use). No raw address is accepted: a number in the site's place is refused.
- `<off>` is decimal or `0x` hex. A `-` may be part of an id, so the site's offset is the number after the last `+` or `-`; write `+0`
  to keep an id that ends in `-<n>` (`slot-2+0`).
- Each `*` reads the 4-byte pointer at the current address, refuses a null one, then adds its offset; at most 8 hops. `<len>` is 1 to 512
  bytes. All arithmetic is 32-bit and wraps; a range that runs past 4 GB is refused. The default timeout is 10 s (no trailing timeout).
- **Guard:** `dev.ctl` (dev only, off in release) and the site accepted, i.e. the exe-identity guard passed and the patch engine accepted
  every site. Refusals: `unknown site '<id>' (not in this game's engine_sites)`, `sites not accepted by the patch engine: <why>`. No other
  key.
- **Read:** every hop and the final range are checked readable (`MemReadable`: committed, not no-access or guard) before they are read,
  on the ctl thread while the game runs. It never writes. A value the game writes at the same moment may come back torn; a page freed
  between the check and the copy would fault, as with any in-process probe.
- **Result** (`.done` members): `site`, `site_addr`, `hops` (`[{"at", "ptr"}, ...]`), `addr`, `len`, `hex` (`"aa bb ..."`), and for the
  whole dwords `u32` (numbers) and `f32` (`%.9g`; `"nan"`, `"inf"`, `"-inf"` as strings). A resolution that stops (`failed`: a null
  pointer, an unreadable hop or range) carries the hops read so far, `failed_hop` (1-based) and no bytes.
- `peek` answers "did the lookup fill the object it should" without a detour. Logging a function's return value that is never stored
  (a `watch` site kind) is not built: B25.
