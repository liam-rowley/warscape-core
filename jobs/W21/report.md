# W21 report: The core's CI: pipeline economies and a settings check

W21 moves the core's own CI onto the pipeline: push-only triggers, a `changes` job, and pass markers for `proxy` and `harness-windows` (B45). It adds a retry and a pin-keyed cache around the proxy's source fetchers without editing any DLL input (B45b), and a read-only `wsc ci check-settings` that says which repository settings the pipeline lacks (B47). VERSION 0.22.0; branch `job/W21`.

## What exists
- **`proxy/tools/netfetch.py`** (new tool; header, `reg add tools` row `proxy.tools.netfetch`, `not-a-verb`):
  - `retry(fn, what, tries=4, delays=(5, 15, 45), sleep, jitter)`:
    - Transient, so retried: `OSError` (which covers `URLError`, `TimeoutError`, `ConnectionError` and `ssl.SSLError`), `http.client.HTTPException`, `subprocess.CalledProcessError`, and `HTTPError` 408, 429 and 5xx.
    - Never retried: any other `HTTPError`, non-transient exceptions, and `SystemExit` (every sha256 mismatch and every failed patch in the fetchers).
    - Each retry prints one line, `netfetch: <what>: <error>; retry 2 of 4 in 14 s`.
  - `prefetch`: runs `fetch_lua.fetch(<game root>/build/lua)` and `fetch_ui.main(['--out', <game root>/build/ui/src])`, each inside `retry`.
    - Before each `fetch_ui` try it removes a RmlUi or FreeType checkout whose HEAD cannot be read or whose working tree differs from HEAD (`clean_checkouts`).
    - Why: `fetch_ui.py` is not idempotent after a `git fetch` that failed right after `git init`. Its own `rev-parse HEAD` check fails on every later try, and a checkout restored only in part would be trusted, because `fetch_ui.py` checks only HEAD.
  - `ci-cache`: prints `key=<sha256 of fetch_lua.PIN, the UI pin file bytes, fetch_dxvk.PIN>` and a `paths<<NETFETCH_EOF` block.
    - The paths are the raw downloads only: `build/downloads`, `build/ui/src/downloads`, `build/ui/src/rmlui` and `build/ui/src/freetype` under the game root, relative to the working directory.
    - It never caches the patched trees.
- **`proxy/tools/fetch_dxvk.py`:** its two `get()` calls go through `netfetch.retry`; nothing else changed.
- **`{{wsc fetch_cache}}`** in `warscape/ci_render.py` (and its docstring), three steps:
  1. `id: fetch_key`, which runs `<core prefix>proxy/tools/netfetch.py ci-cache >> "$GITHUB_OUTPUT"`.
  2. `actions/cache@v5` with `continue-on-error: true`, `path: ${{ steps.fetch_key.outputs.paths }}` and `key: fetch-<[ci] salt>-${{ steps.fetch_key.outputs.key }}`.
  3. `netfetch.py prefetch`.
- **`ci/gates.yml.in`** (and the rendered `.github/workflows/gates.yml`):
  - `on: push` only; `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}`.
  - `{{wsc changes}}` comes first. `gates` (the Linux and Windows matrix) stays unconditional.
  - `proxy` and `harness-windows` have `needs: changes`, `{{wsc if proxy}}` / `{{wsc if harness}}`, and `{{wsc pass_marker proxy}}` / `{{wsc pass_marker harness shell=bash}}` as their last steps.
  - `proxy` runs `{{wsc fetch_cache}}` before `build.sh all`.
  - `{{wsc notify gates needs=changes,gates,proxy,harness-windows}}`.
  - The header explains, in short form, why it is push-only, why a skip counts as passed, and the fail-safe `!cancelled()`.
  - `policy.yml.in` is unchanged.
- **`wsc.toml` `[ci]`:**
  - `required_checks = ["gates (ubuntu-latest)", "gates (windows-latest)", "policy", "proxy", "harness-windows"]`.
  - `[ci.inputs]`: `proxy = '^\.github/workflows/|^ci/|^proxy/|^wsc\.toml$'` and `harness = '^\.github/workflows/|^ci/|^harness/|^proxy/tools/|^proxy/tests/null_game/|^tests/test_moved_tools\.py$|^warscape/|^wsc\.toml$'`, as briefed.
  - Checked against what each job runs: `harness/ctl.py`, `harness/acceptance.py` and the harness tests reference the library, so `warscape/` stays in. The proxy job reads nothing outside `proxy/` apart from `wsc.toml`.
  - No `[ci.artifacts]`.
- **`warscape/repo.py` `DEFAULTS['ci']['required_checks'] = []`.**
- **`wsc ci check-settings [--repo owner/name] [--branch main]`** (`warscape/verbs/ci.py`; logic in the new `warscape/ci_settings.py`):
  - It sends three GETs through `ci.gh`'s injectable runner: `repos/{r}`, `repos/{r}/rules/branches/{b}` and `repos/{r}/branches/{b}/protection`.
  - A 404 from the protection endpoint means there is no classic protection. A 403 is reported as a note, not treated as fatal.
  - Expected checks come from `[ci] required_checks`. When that is empty they are derived from the rendered workflows' job ids, minus `changes` and `notify`. A matrix job is named ("matrix job gates: list its checks in [ci] required_checks"), not guessed.
  - Problems: an expected check that is not required; a required check that no workflow job produces; `allow_auto_merge` false; approving reviews required (by a ruleset or by classic protection).
  - Notes: a workflow job that is not required; `strict` checks.
  - Exit codes: 0, 1, or 2 when the settings cannot be read (no `gh`, not logged in, no access). It changes nothing.
  - The `wsc.ci` tools row was updated to the new header.
- **Docs:**
  - `docs/CONSUMING.md` "The job pipeline": `required_checks`, `{{wsc fetch_cache}}` (only for jobs that run `build.sh`), and the settings bullet now points at `check-settings` and adds "require no approving review".
  - `docs/BACKLOG.md`: B45 and B47 removed; B62 added (fold `netfetch.retry` into the two fetchers in the next job that changes a DLL input anyway).

## Tests, red then green
- **Red first** (commit `0ac7aec`): `tests/test_netfetch.py` (new) and additions to `tests/test_ci.py`. They failed with errors=10 and failures=2: no `netfetch`, no `fetch_cache` block, no `required_checks`, no `ci_settings`.
- **Green from `a7e1fc5` on.**
- `test_netfetch.py`:
  - The transient and the never-retried classes, including `SystemExit`.
  - The delay schedule with a fake sleep and a seeded jitter (`random.Random(7)`); the last try's error is raised.
  - `prefetch` against `file://` tarballs and a local git repository in a temporary game root. After it, `fetch_lua.fetch` and `fetch_ui.main` run with `urllib.request.urlopen` and git `fetch` patched to raise, and make no network call.
  - A restored cache without the patched trees needs no network either.
  - A half-restored checkout (a file missing) and a half-fetched one (unborn HEAD) are removed and fetched again.
  - A sha mismatch is never retried.
  - `ci-cache` output shape, the paths, and key changes for each of the three pins.
  - `fetch_dxvk` retries its download but not its sha check.
  - The git cases are skipped with a reason when git is missing.
- `test_ci.py`:
  - **Golden render hashes** for the fixture game's `gates.yml` and `policy.yml` and for an all-blocks template in game and core configurations, taken on main before any change. They pass unchanged, so the existing blocks render byte for byte as before.
  - Separately, `ci_render.problems()` for napoleon-remastered's own templates and config returns `[]` with this branch's code (checked by hand, not in CI: napoleon is not in the core's checkout).
  - The `fetch_cache` block's three steps, the core prefix, the salt in the key, and `continue-on-error` on the cache step only.
  - The core's input sets: `docs/` and `jobs/` run neither job; `proxy/src/x.cpp` runs proxy; `harness/watcher.ps1` runs harness; a workflow change runs both.
  - `required_checks` and the default `[]`.
  - `check-settings` on recorded JSON:
    - the core's answers of 2026-11-03 (exit 1, 4 problems);
    - the core after the fix (exit 0);
    - napoleon's answers with explicit checks (exit 0, a note for `viewer`) and derived (a problem for `viewer`);
    - a matrix job when derived;
    - a renamed required check, approving reviews and `strict`;
    - a 403 on classic protection with a ruleset answer;
    - classic checks counted;
    - no `gh`, logged out, and no access (exit 2);
    - only `api` and `repo view` calls, with no `-X`.
- Two host tests went red on the first push (CI run 41721419282, my code) and were fixed in `6b346e9`:
  - `NoGameNames`: a game name in netfetch's docstring.
  - `StdlibOnly`: `test_netfetch.py` imported the proxy tools by name; they now load through `importlib.import_module`.
- `python3 wsc.py gates` (full): 13 ok, 1 warn (5 capstone and toolchain skips that were already there), 0 failed.

## CI evidence (push only; no pull_request run exists)
- **(a) both slow jobs ran and saved markers:** run 41721986205, commit 6b346e9.
  - `changes`, `gates` x 2, `proxy` and `harness-windows` were green.
  - Fetch cache: "Cache not found for input keys: fetch-1-8211d7ce...". `netfetch prefetch` then fetched Lua, RmlUi, FreeType and stb, and the cache was saved under that key.
  - Markers saved: `ci-pass-1-proxy-ebc018f2...` and `ci-pass-1-harness-e7f5aab2...`.
- **(b) both skipped, docs-only push:** run 41723537398, commit 9f45469.
  - `proxy` and `harness-windows` were skipped. The step summary says: "`proxy` skipped: its input tree ebc018f2... already passed in run 41721986205 (attempt 1, commit 6b346e9...)", and the same line for `harness`.
- **(c) fetch cache hit:** run 41721986205 attempt 2, the proxy job re-run (job 126223131395).
  - "Cache hit for: fetch-1-8211d7ce...", and `fetch_ui: rmlui 6.3 at ba95ffe8bfb6 already`, `freetype ... already`.
  - Lua and stb came from the cached `downloads/` copies, which are sha-checked; `fetch_ui`'s message still says "fetched" for those.
  - The marker save on that attempt only warned ("Unable to reserve cache ... another job may be creating this cache": the key already existed). The job stayed green.
- **Final commit 6b4a733:** run 41724750581 is green (`changes`, `gates` x 2; `proxy` and `harness-windows` skipped).
- The first push run 41721419282 was cancelled by the next push. Its red `gates` and `harness-windows` were the two host tests above.

## `check-settings` outputs, 2026-11-03
Core (`python3 wsc.py ci check-settings`, exit 1):

    check-settings: liam-rowley/warscape-core main: required checks gates (ubuntu-latest), gates (windows-latest); allow_auto_merge false; no classic branch protection
    check-settings: workflow checks gates (matrix), proxy, harness-windows, policy ([ci] workflows); expected gates (ubuntu-latest), gates (windows-latest), policy, proxy, harness-windows
    problem: `policy` is expected but not a required check on main: a red `policy` would not block a merge
    problem: `proxy` is expected but not a required check on main: a red `proxy` would not block a merge
    problem: `harness-windows` is expected but not a required check on main: a red `harness-windows` would not block a merge
    problem: allow_auto_merge is false: `gh pr merge --auto` has nothing to wait for (Settings, General, "Allow auto-merge")
    check-settings: 4 problem(s), 0 note(s); this changes nothing: the fix is the owner's, in the repository settings

Napoleon, with its config as it stands (`required_checks` unset, so derived; run through the library with this branch's code, exit 1):

    check-settings: liam-rowley/napoleon-remastered main: required checks gates, policy, proxy, harness-windows; allow_auto_merge true; no classic branch protection
    check-settings: workflow checks gates, proxy, viewer, harness-windows, policy ([ci] workflows); expected derived from the workflows
    problem: `viewer` is expected but not a required check on main: a red `viewer` would not block a merge
    check-settings: 1 problem(s), 0 note(s); this changes nothing: the fix is the owner's, in the repository settings

Napoleon with the optional `required_checks = ["gates", "policy", "proxy", "harness-windows"]` (exit 0):

    check-settings: liam-rowley/napoleon-remastered main: required checks gates, policy, proxy, harness-windows; allow_auto_merge true; no classic branch protection
    check-settings: workflow checks gates, proxy, viewer, harness-windows, policy ([ci] workflows); expected gates, policy, proxy, harness-windows
    note: workflow job `viewer` is not a required check
    check-settings: 0 problem(s), 1 note(s); this changes nothing: the fix is the owner's, in the repository settings

Napoleon's ruleset has a `pull_request` rule with `required_approving_review_count: 0`, which is not a problem.

## build_id.py --inputs against main
- None of the DLL inputs changed: `fetch_lua.py`, `fetch_ui.py`, `build.sh`, `build_id.py`, `proxy/src` and the null game's adapter and pins have the same git object ids on the branch as on main.
- The brief's command (`WSP_GAME_ROOT=proxy/tests/null_game python3 proxy/tools/build_id.py --inputs`) exits 2 on main and on the branch alike ("proxy/null (adapter) is not tracked at HEAD": the null game is not a git root, B16).
- So I ran `build_id.py --root . --inputs` in a throwaway superproject: the null game at its root, the core as `core` checked out at each ref. Both refs print the same seven lines, and the same id, `5fd69e4d7f93`:

      core      core/proxy/src                 e45268457bb2b6ce5b42e7ee8e8f9eaa1f778552
      adapter   proxy/null                     b2d27e9200482416b5867ff8281ee46cc1ab806d
      build_sh  core/proxy/tools/build.sh      01e9495a63b9ddeba6d02b2144a6be08aec2e204
      fetch_lua core/proxy/tools/fetch_lua.py  5ed63198f58c812ed49d2c110a188009f7e2e1b7
      build_id  core/proxy/tools/build_id.py   8afedf3ca9b7e283bf9f23e88cc50695a2bdc52f
      fetch_ui  core/proxy/tools/fetch_ui.py   9637e43803e20f2a0b4391a45c561b0313884790
      ui_pins   viewer/pins.json               b4d70b36d81b263603b2f050b801d42cea16393e

## Version
0.22.0, a minor bump. `origin/main` was 0.17.0, `job/W13` 0.20.0, and `job/W19` took 0.21.0 a minute before this branch did, so this branch moved to 0.22.0 in its own commit.

## Deviations from the brief, and why
- **The `build_id.py --inputs` acceptance ran in a throwaway superproject** (above): the brief's exact command fails on main too (B16).
- **The cache hit (c) comes from a re-run of the proxy job of run (a), not from a later push that changes `proxy/`.** A real `proxy/` change would have meant an artificial edit, plus another 25-minute `harness-windows` run, because `proxy/tools/` is also a harness input. The re-run is the same route: the cache is restored on the same branch, and prefetch runs against it.
- **`prefetch` also removes an incomplete RmlUi or FreeType checkout before each `fetch_ui` try.** The brief assumed the fetchers are idempotent. `fetch_ui.py` is not idempotent after a `git fetch` that fails right after `git init`, and it trusts any `.git` whose HEAD is the pin. Without this step a retry could never succeed, and a half-restored cache could reach the build. The fix lives in the wrapper, with no DLL input touched, and the sha256 checks remain the judge of every downloaded byte.
- **The pull request was opened by the orchestrator after the build**, so "the pull request shows the same checks from the push run" is checked there. No `pull_request`-triggered `gates` run exists for this branch, because the trigger is gone.
- **Built on Opus** by Liam's choice for this session (the brief names Sonnet).
- **Report and row:** the build ran as a subagent, which cannot write report files, so the orchestrator wrote this report from the builder's text and set the row to review (same Claude-Session as the build).

## Open questions
1. Retry inside `fetch_lua.py` and `fetch_ui.py`: not done here (decision 4). B62 folds it in the next job that changes a DLL input. Until then the PC route (`build.sh --docker`, `pc_deploy kit`) fetches without a retry; `fetch_dxvk` has one.
2. Caching the compiled UI objects: not done, as recommended.
3. `check-settings` in CI: not done, as recommended (`GITHUB_TOKEN` cannot read classic protection). Run it by hand or from the orchestrator's start-up checks.
4. A game that sets `required_checks` and has a matrix job must list the `<id> (<value>)` names itself; the derivation only names the job.

## What consumers must do after the tag (napoleon-remastered)
- **No acceptance run for this tag alone:** no DLL input changed, so the build id is the same. A pin bump that also crosses W19 or W20 needs its 20 passes for those jobs.
- Add `{{wsc fetch_cache}}` in `ci/gates.yml.in`'s `proxy` job, after the checkout and before `core/proxy/tools/build.sh all`.
  - **Not in `viewer`:** `viewer/core/build.sh` fetches through napoleon's own `viewer/core/fetch_sources.py` into `build/viewer/src`, inside the emsdk container, not through `build/ui/src` (checked 2026-11-03).
  - Then `python3 core/wsc.py ci render`, and commit the template, the rendered workflow, the `core` gitlink and `wsc.toml` `[core] version` together (B9).
- Optional: `[ci] required_checks = ["gates", "policy", "proxy", "harness-windows"]`; `check-settings` then exits 0 with a note for `viewer`.
- **For Liam (core settings):** require `policy`, `proxy` and `harness-windows` in the core's ruleset (a skipped slow job counts as passed), and switch on "Allow auto-merge". `python3 wsc.py ci check-settings` should then exit 0. This job changed no setting.
