# W21: The core's CI: pipeline economies and a settings check

Model: Sonnet, reason: none needed (Sonnet is the default). Workflow templates, one renderer block, a small fetch helper and one read-only verb, all
standard-library Python with host tests; no DLL input changes, no PC. Budget about 100 tool calls (CI round trips included: the workflow change can only be
proved by pushes). At the cap, stop, commit, and report what is left.

## Goal
Backlog B45 and B47 (both from napoleon J62), plus a third item the orchestrator found on 2026-11-03 (call it **B45b, fetch flakes**):
- **B45, CI economies.** The core's `ci/gates.yml.in` still runs on `push` and `pull_request` (two whole runs per push to a branch with a pull request) and
  runs the slow `proxy` (about 15-25 min) and `harness-windows` jobs on every run, docs-only branches included. Napoleon has had push-only triggers (J42),
  the `changes` job and pass markers (J54, J57) since 0.9.0, all rendered by the core's own `warscape/ci_render.py`; the core never adopted them.
- **B45b, fetch flakes.** The `proxy` job's `build.sh all` fails often on network errors in the fetchers: on 2026-11-03 runs 41708778053, 41709913755,
  41709922127, 41709945251, 41711877058 and 41710414965 failed in `proxy/tools/build.sh all` (rerun to green). Read from the logs: every failure readable
  there is `www.lua.org` (`fetch_lua.py` line 62, and `fetch_ui.py` `download()` for its Lua copy): `ConnectionResetError` during the TLS handshake and
  `TimeoutError` on connect. The fetchers use `urllib` with no retry, and CI starts from an empty `build/` every time. (`fetch_dxvk.py`, github.com, is not
  run by CI at all: `pc_deploy.py kit` calls it on the PC route; it gets the same retry here.)
- **B47, a settings check.** The settings a pipeline needs are the owner's and nothing tells anyone when they drift. Read 2026-11-03 with `gh api`: the core
  has **no classic branch protection** and one **ruleset** on `main` requiring only `gates (ubuntu-latest)` and `gates (windows-latest)` (not `policy`,
  `proxy`, `harness-windows`), and `allow_auto_merge` is **false**; napoleon's ruleset requires `gates`, `policy`, `proxy`, `harness-windows`, auto-merge on.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### B45: the core's workflow becomes the pipeline's (reuse the existing blocks, write no new YAML logic by hand)
1. `ci/gates.yml.in`: `on: push` only (keep `workflow_dispatch` out unless needed); `concurrency` cancels in progress except on `main`
   (`${{ github.ref != 'refs/heads/main' }}`), as napoleon's; `{{wsc changes}}` first; `proxy` and `harness-windows` get `needs: changes`, `{{wsc if proxy}}`
   / `{{wsc if harness}}` and `{{wsc pass_marker proxy}}` / `{{wsc pass_marker harness shell=bash}}` as their last steps; `gates` (the Linux and Windows
   matrix) stays unconditional; `{{wsc notify gates needs=changes,gates,proxy,harness-windows}}`. `policy.yml.in` is unchanged (it already owns
   `pull_request`). Copy the header comments that explain push-only, skips counting as passed, and the fail-safe `!cancelled()` from napoleon's template in
   short form. Then `python3 wsc.py ci render` and commit template and workflow together.
2. `wsc.toml` `[ci] inputs` for the core (start from these, and check each against what the job really runs; when unsure, include the path):
   - `proxy = '^\.github/workflows/|^ci/|^proxy/|^wsc\.toml$'`
   - `harness = '^\.github/workflows/|^ci/|^harness/|^proxy/tools/|^proxy/tests/null_game/|^tests/test_moved_tools\.py$|^warscape/|^wsc\.toml$'`
   Add a `tests/test_ci.py` case that classifies sample paths for the core's own config (a `docs/` or `jobs/` change runs neither; `proxy/src/x.cpp` runs
   proxy; `harness/watcher.ps1` runs harness; a workflow change runs both). No `[ci.artifacts]` (the core keeps no build artifact).
3. Existing render blocks must not change byte for byte: napoleon renders the same blocks and its `ci_render` gate would fail after the pin bump. A new
   test renders `tests/fixture_game`'s templates and compares with the committed expectation (or the existing render test covers it: say which).

### B45b: retry and cache, without touching a DLL input
4. **The constraint:** `proxy/tools/build_id.py` `INPUTS` hashes `fetch_lua.py`, `fetch_ui.py` and `build.sh` into the DLL build id, so editing any of
   them gives every consumer a new build id and, in napoleon, 20 acceptance passes at the pin bump (rule 79) for a DLL with the same bytes. So this job does
   **not edit** `fetch_lua.py`, `fetch_ui.py`, `build.sh` or `build_id.py`. Acceptance: `python3 proxy/tools/build_id.py --inputs` (with
   `WSP_GAME_ROOT=proxy/tests/null_game`) prints the same object ids on the branch as on `main`.
5. **`proxy/tools/netfetch.py`** (new tool, header and `reg add tools`; `not-a-verb`: it needs network and writes build output, like the fetchers):
   - `retry(fn, what, tries=4, delays=(5, 15, 45), sleep=time.sleep)`: calls `fn`; on a transient error waits `delay x uniform(0.8, 1.2)` and tries again,
     printing one line per retry (`netfetch: <what>: <error>; retry 2 of 4 in 14 s`). Transient: `OSError` (it covers `URLError`, `TimeoutError`,
     `ConnectionError`, `ssl.SSLError`), `http.client.HTTPException`, `subprocess.CalledProcessError` from git, and `HTTPError` only for 408, 429 and 5xx. Never
     retried: other `HTTPError`s and `SystemExit` (every sha256 mismatch and every failed patch in the fetchers raises `SystemExit`: a wrong byte is never a
     flake). The sha256 checks stay exactly where they are.
   - `prefetch`: runs `fetch_lua.fetch(<game root>/build/lua)` and `fetch_ui.main(['--out', <game root>/build/ui/src])` (the outputs `build.sh` uses), each
     inside `retry`. The fetchers are idempotent (they skip what is present and sha-checked), so retrying a whole call equals retrying its failed request;
     `build.sh` then finds everything in place and makes no network call.
   - `ci-cache`: prints, for `$GITHUB_OUTPUT`, `key=<sha256 of fetch_lua.PIN, the UI pin file bytes and fetch_dxvk.PIN>` and a multi-line `paths` (the
     `name<<EOF` form) of the **raw** downloads only, relative to the working directory: `<game root>/build/downloads`, `<game root>/build/ui/src/downloads`,
     `<game root>/build/ui/src/rmlui`, `<game root>/build/ui/src/freetype`. Never the patched outputs (`build/lua/src`, `build/ui/src/lua`): their stamps hold
     only the tarball's sha256, not the patch list, so a cached patched tree could survive a patch change.
   - `fetch_dxvk.py` (not a DLL input) calls `netfetch.retry` around its two `get()` calls; nothing else in it changes.
6. **A render block** `{{wsc fetch_cache}}` in `warscape/ci_render.py` (and its docstring): three steps for a job that builds the proxy, placed before the
   build: `id: fetch_key` running `<wsc's core prefix>proxy/tools/netfetch.py ci-cache >> "$GITHUB_OUTPUT"`; `actions/cache@v5` with
   `path: ${{ steps.fetch_key.outputs.paths }}` and `key: fetch-<[ci] salt>-${{ steps.fetch_key.outputs.key }}`, `continue-on-error: true` (a cache fault never
   fails the job); then `netfetch.py prefetch`. The core's `proxy` job uses it. The cache key changes only when a pin changes (or the salt), so a warm cache
   makes the proxy job's fetch offline except for a pin bump.

### B47: `wsc ci check-settings`
7. A new action of the `ci` verb (`warscape/verbs/ci.py`; logic in `warscape/ci.py` or a new `warscape/ci_settings.py`), read-only, through `gh` with the
   existing injectable runner (`ci.gh(args, run=...)`): `wsc ci check-settings [--repo owner/name] [--branch main]` (repo default: `gh repo view --json
   nameWithOwner`). It reads `GET repos/{r}` (`allow_auto_merge`), `GET repos/{r}/rules/branches/{b}` (rulesets: `required_status_checks`,
   `pull_request` rules) and `GET repos/{r}/branches/{b}/protection` (classic; a 404 "Branch not protected" means none, a 403 means it cannot be read without
   admin and is said, not fatal when rulesets answered).
8. **Expected checks** come from a new `[ci] required_checks` list (`warscape/repo.py` `DEFAULTS`, default `[]`). Empty: derived from the rendered workflows
   named in `[ci] workflows` (the job ids under `jobs:`, minus `changes` and `notify`); a job with a `matrix` is named `<id> (<value>)` by GitHub, which the
   derivation cannot know without a YAML parser, so it says "matrix job <id>: list its checks in [ci] required_checks" instead of guessing.
9. **Findings**, one line each, then a summary: `problem` for an expected check that is not required (a red check would not block a merge), a required
   check no workflow produces (it never reports, so every merge waits forever: a renamed job), `allow_auto_merge` false (`gh pr merge --auto` has nothing to
   wait for), and a rule requiring approving reviews (one account cannot approve its own pull request, so the pipeline's merges stall); `note` for a workflow
   job that is not required (e.g. napoleon's `viewer`) and for `strict` up-to-date checks. Exit 0 no problem, 1 problems, 2 cannot read (no `gh`, not
   logged in, no access). It changes nothing: the fix is the owner's, in the repository settings.
10. The core's own `wsc.toml`: `[ci] required_checks = ["gates (ubuntu-latest)", "gates (windows-latest)", "policy", "proxy", "harness-windows"]`.

## Scope: files this job touches
`ci/gates.yml.in`, `.github/workflows/gates.yml` (rendered), `wsc.toml` (`[ci] inputs`, `required_checks`), `warscape/ci_render.py` (the `fetch_cache` block),
`warscape/ci.py` or `warscape/ci_settings.py` (new), `warscape/verbs/ci.py` (the action, its header lines), `warscape/repo.py` (`DEFAULTS` `ci.required_checks`),
`proxy/tools/netfetch.py` (new), `proxy/tools/fetch_dxvk.py`, `registries/tools.jsonl` (netfetch's row; the `wsc.ci` row after its header changes),
`tests/test_ci.py`, `tests/test_netfetch.py` (new), `docs/CONSUMING.md` ("The job pipeline": the new key, the new block, the verb; the "Settings only the
owner can make" bullet points at the verb), `docs/BACKLOG.md` (remove B45 and B47), `VERSION`. **Not** `fetch_lua.py`, `fetch_ui.py`, `build.sh`,
`build_id.py` (decision 4).

## Steps
1. Read `warscape/ci_render.py`, `warscape/ci.py`, `warscape/verbs/ci.py`, `tests/test_ci.py`, both core templates and napoleon-remastered's
   `ci/gates.yml.in` and `wsc.toml` `[ci]` (read-only, for the shape), and the three fetchers.
2. **Failing tests first**, committed red: `test_netfetch.py` (the transient and the never-retried classes; the delay schedule with a fake sleep and a
   seeded jitter; `prefetch` against `file://` tarballs and a local git repo in a temp game root, after which running `fetch_lua.fetch` and `fetch_ui.main`
   with `urllib.request.urlopen` and git patched to raise makes no network call; `ci-cache` output shape; skip the git case with a reason when git is missing);
   `test_ci.py` (the core's input sets; the `fetch_cache` block's steps and `continue-on-error`; check-settings on recorded JSON for the core's 2026-11-03
   answers above, for napoleon's, a 403 on classic protection with a ruleset answer, a renamed required check, approving reviews, and no `gh`).
3. Build B45b (decisions 4-6), then B45 (1-3), then B47 (7-10); `python3 wsc.py ci render`; commit each.
4. Push early: the first push of the new workflow is the proof. Read the run: `changes` runs, `proxy` and `harness-windows` run (the workflow changed), each
   writes its pass marker; then push a docs-only commit and show both slow jobs **skipped** with the step-summary line naming the run that passed the tree;
   and the proxy job's log shows `netfetch` prefetch and, on the second proxy run (a later push that changes `proxy/`), a cache hit with no download.
5. Run `python3 wsc.py ci check-settings` against the core and napoleon (read-only) and paste both outputs in the report.
6. Docs, backlog, `VERSION`; `python3 wsc.py gates` (full) and `python3 wsc.py policy --branch job/W21 --base origin/main`.

## Tests and acceptance
- New host tests red first, then green; `python3 wsc.py gates` green (its `ci_render` gate proves the committed workflow equals its render).
- CI on the branch: the run ids for (a) a push that ran both slow jobs and saved markers, (b) a push that skipped both, (c) a proxy run with a fetch cache
  hit, in the report. A pull request shows the same checks from the push run, and no `pull_request`-triggered `gates` run starts.
- `build_id.py --inputs` unchanged against `main` (decision 4).
- `check-settings` exits 1 on the core today (missing `policy`, `proxy`, `harness-windows`; auto-merge off) and 0 or only notes on napoleon.

## VERSION
A minor bump (a new verb action, a new `[ci]` key, a new render block and tool). Take the next free minor at merge time: `origin/main` says 0.15.0 when
this brief was written, W7 expects 0.16.0, and W17, W19 and W20 also bump. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last
commit; the second to merge takes the next free number and merges `main` (never rebase). Say which number you took. Tags are Liam's.

## What consumers must do after the tag (napoleon-remastered)
- **No acceptance run for this tag alone:** no DLL input changes (decision 4), so the build id is the same. (A pin bump that also crosses W19 or W20 needs its
  20 passes for those.)
- The retry and the cache reach napoleon's CI only through its own template: in `ci/gates.yml.in` add `{{wsc fetch_cache}}` in the `proxy` job after the
  checkout and before `core/proxy/tools/build.sh all` (and in the `viewer` job before its build if `viewer/core/build.sh` reads the same `build/ui/src`
  folders: check, do not assume), then `python3 core/wsc.py ci render`, and commit the template, the rendered workflow, the `core` gitlink and `wsc.toml`
  `[core] version` together (B9). Nothing else in its rendered workflow changes.
- Optional: `[ci] required_checks = ["gates", "policy", "proxy", "harness-windows"]` and `python3 core/wsc.py ci check-settings` (expected: only a note that
  `viewer` is not required).
- **For Liam (core settings, his to change):** after this merges, the core's ruleset can require `policy`, `proxy` and `harness-windows` (a skipped slow job
  counts as passed, so docs-only pull requests no longer wait for them) and "Allow auto-merge" can be switched on; `wsc ci check-settings` says what is
  missing. The job changes no setting.

## Kill criteria
- A decision needs an edit to `fetch_lua.py`, `fetch_ui.py`, `build.sh` or `build_id.py`: stop and report; do not change a DLL input in this job.
- An existing render block's output changes for napoleon's or the fixture game's templates: stop and fix before anything else.
- The skip route cannot be shown on the branch after three pushes (a slow job still runs on a docs-only push, or never runs when its inputs change):
  stop and report the run ids.
- The cache step can fail the job (not `continue-on-error`, or a restore that leaves a half tree the fetchers accept): stop; the fetchers' sha checks
  must stay the only judge of a byte.
- Core CI red after three fix attempts for a cause in this change: stop and report. Version collision as in VERSION; never rebase a pushed branch.

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Retry inside `fetch_lua.py` and `fetch_ui.py` themselves?** The orchestrator asked for retry in the fetchers. Recommended: not in this job (decision
   4): it changes the DLL build id of every consumer for identical DLL bytes, which costs napoleon a 20-pass sitting. `netfetch.py prefetch` gives CI the
   same retry, and the PC route (`build.sh --docker`, `pc_deploy kit`) keeps `build/downloads` between builds. Fold `netfetch.retry` into the two fetchers in
   the next job that changes a DLL input anyway (a backlog line, added by this job, naming it).
2. **Cache the compiled UI objects (`build/ui/obj`, keyed by their stamp) too?** Recommended: not now. It would save the largest part of the proxy job, but a
   stale object is a wrong DLL that `repro` (which rebuilds from copies) might not catch the same way; pass markers already skip the job on an unchanged tree.
   A later row with its own proof.
3. **Run `check-settings` in CI?** Recommended: no. `GITHUB_TOKEN` cannot read classic protection, and a settings drift is the owner's to fix, not a reason to
   fail a contributor's push. Run it by hand, from the orchestrator's start-up checks, or later in `wsc jobs view`.
4. **`required_checks` explicit or derived?** Recommended: explicit in the core (decision 10, matrix names), derived as a fallback (decision 8).
5. **File overlap with the other core rows**, for whoever merges second (merge `main`, never rebase):
   - **W20** (UI host and gesture hardening) may add `xvfb` and Mesa packages to the `proxy` job for its smoke walk (`ci/gates.yml.in`, the rendered
     workflow): re-apply that step to the new template and re-render.
   - **W16** (the null game on its own) touches `proxy/tools/build.sh` and `build_id.py` (B16): no file overlap with this job, which edits neither.
   - **W12** (guards: commit-msg hook, run-README references) and **W13** (game gates, hook names) touch `warscape/`; **W12** may touch `.githooks/`; none
     touch `ci_render.py` or `ci.py` as briefed, but re-read them before merging.
   - **W7**, **W17**, **W19** touch `proxy/src`: a later push of theirs after this merges is what first exercises the pass markers on real proxy changes.
   - All rows: `docs/BACKLOG.md`, `docs/CONSUMING.md`, `VERSION`.

## Finish
Report in `jobs/W21/report.md` (what was built, the tests red then green, the CI run ids for the run, skip and cache-hit cases, both `check-settings`
outputs, the `build_id.py --inputs` comparison, the version taken, deviations, open questions, what napoleon and Liam must do), then
`wsc reg set jobs W21 status=review report=jobs/W21/report.md` (`python3 wsc.py`). Push `job/W21`, open the draft pull request, and stop: an independent
reviewer merges (C18); Liam tags.
