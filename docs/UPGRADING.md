# Upgrade notes: moving a game's pin past a version

What a game repo changes when its core pin crosses one of these versions. Moved out of [CONSUMING.md](CONSUMING.md) on 2026-11-04 to keep that doc
under the 30 KB cap; the upgrade steps themselves are in CONSUMING.md "Upgrading and releasing".

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
