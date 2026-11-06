# Upgrade notes: moving a game's pin past a version

What a game repo changes when its core pin crosses one of these versions. Moved out of [CONSUMING.md](CONSUMING.md) on 2026-11-04 to keep that doc
under the 30 KB cap; the upgrade steps themselves are in CONSUMING.md "Upgrading and releasing".

## The `tests` gate: timings, workers, headroom (W139)

Nothing is required at the bump, and `workers` stays 1: one process per folder and the same result lines. Three things show up without a change: the log now has a `timing:` line and each folder's
slowest modules (the `--durations` flag needs Python 3.12), and a folder over 75% of `timeout_s` warns (`[tests] warn_at`, `0` is off). To opt in, read those timings first, then set
`workers` and `first`: [CONSUMING_OPTIONS.md](CONSUMING_OPTIONS.md) "The `tests` gate". This is no DLL or harness input, so a pin bump to it needs no acceptance run for it.

## `wsc proposals` and `decide/` (W45, C41)

A new core verb, a shipped schema and a branch kind; nothing is required at the bump, and without the registry nothing runs. A game verb named `proposals` in `[cli] verb_dirs` now refuses
to load: rename it. To adopt it: [PROPOSALS.md](PROPOSALS.md) "What a game declares". `doc_caps` no longer reads the job folders, so its findings on job briefs go.

## Session cap (W41)

`[jobs] max_sessions` is off by default; a game on a shared PC sets it (napoleon: 4, its D59). It counts background sessions with a pid in any state, across every repo on the PC, so a
core or game queue with no cap can still fill it. `jobs next` then prints the count, says wait at the cap and claims nothing; `jobs next --id` goes on. `--auto` reads `job.sh status`
each tick and starts no `needs_pc` session during an acceptance run, or while a harness cannot answer. `wsc jobs sessions` is new.

## `wsc audit` (W44, C41)

A new core verb and an `[audit]` table; nothing is required at the bump. A game verb named `audit` in `[cli] verb_dirs` now refuses to load: rename it. The keys a game sets:
[AUDIT_METRICS.md](AUDIT_METRICS.md) "What a game sets".

## Hooks and gate keys added in 0.24.0 (C23)

- **`.githooks/commit-msg`** refuses a commit whose message has no `Claude-Session:` trailer with a value (read with `git interpret-trailers --parse`, as `policy` reads
  pushed commits: git sees a trailer only in the last paragraph, with `Co-Authored-By:`). Opt in with `[policy] commit_msg_hook = true` (default `false`; it uses
  `[policy] session_trailer`, and an empty name switches it off). Merge commits are skipped; fix a refusal with `git commit --trailer "Claude-Session: <id>"`;
  a human commit bypasses once with `--no-verify`. Same wiring as the pre-push hook (`core.hooksPath core/.githooks`). It runs `wsc policy --commit-msg <file>`.
- **`run_refs` gate** (fast set): every repo path a tracked `**/runs/**/README.md` names (link targets and backticked paths) must exist: from the root, from the README's
  folder, as the tail of a tracked path, inside a submodule, or git-ignored. `[gates] run_refs_since = "YYYY-MM-DD"` skips run folders dated before it (default `""`:
  all checked); set it to the pin-bump date when old READMEs name moved paths.

## Moving to base-judged policy (0.26.0, core W23, C24)
In the pin-bump commit itself, because the render guard and the new facts fail otherwise (napoleon: J78):
1. **`ci/policy.yml.in`:** `on: pull_request_target` with the same types. For the bump's own pull request add a second trigger, `pull_request` with
   the same types and `paths: ['jobs/<bump id>/report.md']` (main's copy has no `pull_request_target` yet, so without it nothing would run `policy`
   on that pull request); remove it in the next change to the template (`ci_render` warns until then). Run `wsc ci render`.
2. **`[ci] policy_extra_steps`** now run in the base checkout, where `HEAD` is the base. Take the head's sha from an `env:` value
   (`${{ github.event.pull_request.head.sha }}`), never from an expression inside `run:`, and make both pins present in `core/` if a module compares them.
3. **The `policy`-stage module** (napoleon `tools/gates/pipeline.py`): run git at `ctx.facts['repo']` with the `head`, `base` and `merge_base` shas
   (`show`, `show_first`, `core_pin_diff`, `collect_acceptance`), never in `ctx.root` and never with `'HEAD'`; a module left as it is fails closed, as a
   crash. `ctx.root/core/...` is now the base's core: a build id must come from the base's `build_id.py` over the head's blobs, never by running the
   head's copy. When a bump changes `build_id.py` itself, the base's algorithm cannot reproduce the head's id: the game needs a rule for that, and the
   default is a refusal.
4. **Behaviour.** CI judges the pull request's head against the base tip, so a branch behind `main` on the decisions file must merge `main`. Globs
   match by path segment: `registries/*` no longer covers `registries/<name>/<row>.json`. Until the bump merges, the game's pull requests are judged
   as before, with the note.
5. **`[policy] bases` (W36) fails open on an older base.** CI's parent is the base's code, so a branch whose core predates W36 does not know the rule: a pull
   request into it is not refused. Its merge still reaches `main` only through a pull request judged by main's rules.

## Workflow inputs, bases and the commit match (core W36)
Nothing is forced; the defaults apply when the keys are absent.
- **`[policy] bases`** (default `["main"]`): a game whose default branch is not `main` lists it, or sets `[]`, in the pin-bump commit, or its pull requests are refused.
- **`[policy] workflow_paths`** (default `.github/workflows/**`, `ci/**`): a warning, never a refusal, so a brief that touches CI should name each file, the
  rendered workflow as well as its template. Set `[]` to switch it off.
- **`commit_lacks_trailer`** takes the command as typed: global options, `-c alias.X=` and a shell's command string are seen, and an argument (`echo git commit`) is
  no commit. A hook that normalises first keeps working; `warscape.trailer.COMMIT` is gone (nothing in the core or napoleon read it).

## The build id names one DLL (0.27.0, W24, C25; [PROXY_BUILD.md](PROXY_BUILD.md))
- **Rule 79:** a new build id (`core`, `build_sh`, `build_id`, `fetch_lua`, `fetch_ui` changed, `toolchain` new) and new DLL bytes: 20 passes.
- **CI:** install `$(python3 core/proxy/tools/toolchain.py apt)` with `--no-install-recommends` instead of `g++-mingw-w64-i686` (else `build.sh`
  refuses once the archive moves), then `wsc ci render` (`{{wsc fetch_cache}}` is two steps). `build_id.py` test fixtures copy `toolchain.py`.
- **PC:** nothing; `--docker` installs the pins. Off the pin, `WSP_TOOLCHAIN=any` gives a `-dirty` DLL; an untracked source refuses the build.
- `proxy.log`'s second line is `self_hash: ...`; `ctl.py` `build_info()` returns `dll_sha256`.

## DLL changes in 0.34.0 (W33, C29)
- **New key `proxy.file_rules`** (release file rules; `filerules.h` grammar; applied after the dev rules; no dev feature, no thread). Add the
  row to `registries/config_keys` (text: `proxy/tests/null_game/registries/config_keys.jsonl`), then `gen_tables.py`; without it the host
  tests fail and name the key. A release component that ships a rule file sets it through its `ini_set`; `release_value` stays "".
- **Migration:** a release that set `dev.file_rules` for shipped data rules moves them to `proxy.file_rules`; the player ini then sets no
  dev key. A dev launch's `dev.file_rules` stays and wins on the same path.
- **New log lines:** `patch_engine: protections restored on <n> page(s): ...` (and `... left changed` per bad page), `thread: <name> started
  (tid N)`, the `dev:` line's `threads at the first Direct3DCreate9: state=<0|1> ctl=<0|1>`, `redirect: <n> rules from <path> (proxy.file_rules)`.
- **Behaviour:** the dev threads start at the first `Direct3DCreate9`, not in DllMain, and only for `state_json`/`timeline` (state) and
  `ctl`/`autostart` (ctl). A new DLL input: the build id changes.

## pc_deploy takes the lock; exe_check is a start-time setting (0.33.0, core W25, C28)
- `pc_deploy install|uninstall|set|sync-lua` take the game lock through `job.sh` (`--owner`, `--session`, `--job-sh`; defaults as above) or use the caller's; held by another: exit 2.
  `--assume-closed` skips only the running check, which `set` now makes too. The ini and `install.json` are replaced atomically; `owned` is the union of installed kits.
- Nothing installed but the mod's config file or folder present: `status` fails, `install` refuses (`--move-stray` moves it to `<state>/_to_delete`).
- Watcher **1.5.0**: neither a `watcher.ini` reload nor a `restart`/`update` job weakens `exe_check`; for `warn`, Liam stops the watcher and starts it by hand.
- `esf_edit.set_value` takes the `@N` child position (as `esf_dump` prints), not the Val-only index.

## `gen_tables.py --exe`: the offline site check (W34, C7)
`python3 core/proxy/tools/gen_tables.py --exe <staged exe copy>` checks every `engine_sites` row against a copy of the exe with no game running: the file's sha1, `TimeDateStamp` and
`SizeOfImage` against the identity (`IDENTITY MISMATCH ...`), then one line per site, `MATCH <id> 0x<rva>` or `MISMATCH <id> 0x<rva>: <anchor|stock> byte <i> is <got>, the row says <want>`
(`MISMATCH <id>: rva not in the file` outside every section's file bytes). A hook outside an executable section mismatches, as the DLL refuses it. The file is unrelocated, so the bytes compare as
they stand, an absolute address in an anchor too. It does not know relocations: a patch value the DLL refuses as `RELOCATED VALUE` still reads `MATCH` here. It runs the row validation first and writes nothing;
exit 0 all match, 1 a mismatch, 2 an unreadable file. `--allow-pin-mismatch` is for a file that carries the sites but is not the pinned build (the smoke's stand-in): one note for the identity, the bytes still decide.

## Gate changes in 0.36.0 (W28, C31): the steps at the pin bump
- **`[gates] skip`** takes `"<gate>:<decision id>"` only; a bare name is a config error. Add a decisions row first, then skip under its id. Each skip prints a warning line.
- **`verified_dates`** no longer takes `3-10`, "session", `.md)` or `v2` as a date: fix each flagged line with its true date or run id (`git log`, the report).
- **`json`** refuses a key twice in one object, in every `.json`/`.jsonl` and in every registry row: fix the data, never relax the check.
- **`doc_paths`** (an error) fails on backticked paths in living docs that are not in the repo: point a renamed one at its new path, drop a gone one,
  mark a historical one `(was <path>)`, and list tokens that are not this repo's paths (branch prefixes such as `plan/`, another repo's folders as a
  prefix glob such as `rml_mod/**`) in `[docs] path_ignore`; the core's own `wsc.toml` is the example. Job folders at any depth, the decisions file and
  `../` paths are not checked. napoleon-remastered had 56 misses on 2026-11-04 (W28 report): clear them in its pin-bump branch, or skip the gate there
  under a decision id (`"doc_paths:<id>"`) while it does.
- **`gen_tables.py`** reads `engine_sites` and `config_keys` through the registry loader, so the game's whole `wsc.toml` must load with this core.

## Crash symbolisation and guarded verbs (0.38.0, core W35, C35)
Pin bump: a new build id (`build.sh` changed: 20 passes); delete game verbs named `crash` or `agent-settings`; put `{{wsc proxy_map step=dll}}`
after the proxy build step (give it `id: dll`) and `wsc ci render`; attach `d3d9.map` and `d3d9.map.json` to each release; set `[agent_settings] safe` (`exact_only = true`: only those rules).
What the verbs do: [PROXY_BUILD.md](PROXY_BUILD.md) "Symbolising a crash", [PROXY_HARNESS.md](PROXY_HARNESS.md) "Guarded verbs".

## DLL changes in 0.40.0 (W39)
- **New key `proxy.dxvk_wndproc_fix`** (bool, JSON `true` in the row, so `default` and `release_value` render as 1; owner `proxy`). Add the row to
  `registries/config_keys`, then `gen_tables.py`; without it the host tests fail and name the key. Every game that builds the proxy needs the row: the
  test reads the core's key list, not the game's backend.
- **Behaviour:** with DXVK loaded, its own `GetWindowLong`/`SetWindowLong` (W and A) import slots go through a guard, so a window proc stacked above
  DXVK's is dropped at a fullscreen re-entry and cannot close a cycle with it (a stack overflow at an in-game resolution change). The key at 0 patches
  nothing and warns. Nothing changes under the system d3d9. A new DLL input: the build id changes, so the acceptance passes run again.
- **New log lines:** `backend: wndproc guard on DXVK's imports: <n> slots`, then a warning `backend: wndproc guard patched <n> of 4 slots: ...` if a DXVK build imports fewer, `wndproc guard: DXVK hooked|restored window ...`
  per set, `wndproc guard: window ... above DXVK's proc ...` naming the dropped module, `backend: proxy.dxvk_wndproc_fix=0: ...` with the key off.
- **New tool:** `proxy/tools/dump_read.py` reads a dump with cdb (stack against its limit, the repeating frame cycle, graphics modules). A game
  retires its own copy's `tools` row at the bump.
- **Proof on a PC:** host tests model the switches; only the game shows the fix works. After the bump, change the resolution in the game with the key on
  and read the log lines above. The wine smoke has no DXVK window, so it cannot.

## Decisions as row files and `later` rows (core W43)

Nothing is forced: a repo keeps its Markdown decisions file, and a pin bump past W43 changes nothing until it opts in (CONSUMING_OPTIONS.md, "Decisions as one file per row"). The `later` status and the `backlog_id` and `area` fields are in the core's jobs schema from this release on.

## DLL changes: the headless guard (core W18)
- **No key, no adapter change.** `proxy/src` changes (a new DLL input: the build id changes), so rule 79 applies: one 20-pass acceptance run on the new build id
  (`python3 core/harness/acceptance.py run`) covers every tag the bump crosses.
- **Behaviour:** a window a DLL shows after start-up is hidden at show time, not within the 250 ms sweep; the guard's own move is recognised at a scaled target DPI (measured with a probe window, not yet with a game there);
  `headless_status.json` is rewritten after each verified relocation and gains `relocations` (see [PROXY_HARNESS.md](PROXY_HARNESS.md), "The headless guard").
- **Game docs:** the game's own "Headless" doc (napoleon-remastered `proxy/README.md`) names the show hook beside the sweep, the logical own-move rect and its near-miss line,
  and the status rewrite with `relocations`. A game pinned below this tag also follows each earlier version's notes in this file.

## Acceptance evidence and scene launches (W9, minor)

Nothing breaks at the bump; a game with no `ctl.saves` block, no flakes and a current watcher behaves as before, except that `acceptance.py run` now refuses a reused `--run` id and a watcher whose installed bytes differ from the pin's,
and writes schema 2. Details and the consumer's rule 79 changes: [PROXY_HARNESS.md](PROXY_HARNESS.md) "Acceptance evidence". Set `acceptance.max_flakes` in the harness adapter (suggested 1) and, for rows with `save_file`, `ctl.saves`.
Because `harness/` changes at this pin, the first bump past it needs a 20-pass run on a PC whose installed watcher is the kit at that pin (the preflight checks it).
