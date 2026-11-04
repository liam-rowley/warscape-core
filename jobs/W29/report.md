# W29 report: Release tags by workflow: semver on rows, release branch, annotated tags on a green main

W29 makes the core's release tags a function of a green `main` (C27): job rows carry `semver`, a `release` workflow computes the version from the rows done since the last tag, opens and auto-merges `release/vX.Y.Z` (a new policy kind that may change only `VERSION`) and puts an annotated tag on the merge commit; it never moves a tag and never uses `GITHUB_TOKEN`. `core_pin` checks the tag on `main`, each consumer adapter is compiled with `-fsyntax-only` before the tag, and `wsc core bump <tag>` writes a consumer's bump as one commit. VERSION 0.34.0 (a legacy job, bumped by hand).

## What was built, per decision
1. **Token** (decided by Liam 2026-11-04: a GitHub App). `ci/release.yml.in` mints a token with `actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510`
   (v3.3.0, released 2026-10-12) from the secrets `RELEASE_APP_CLIENT_ID` and `RELEASE_APP_KEY`, else takes the secret `RELEASE_TOKEN`; the code is
   token-agnostic. The step after the mint fails with "RELEASE_TOKEN is not set: see docs/CONSUMING.md, Releases" before the checkout (which would
   otherwise fall back to the workflow's own token). `wsc release check-token`, `open` and `tag` refuse without `$RELEASE_TOKEN` (`release.need_token`).
   `wsc ci check-settings` prints a `manual:` line (secrets, auto-merge, the `v*` ruleset) when `release.yml` is in `[ci] workflows`.
2. **Rows.** `schemas/jobs.schema.json` `semver` (`patch|minor|major|none`); `[jobs] semver_from` (default 0 = off; the core sets **40**, one above W39,
   the highest row on `origin/main` at the final merge). `jobs check` wants it from `queued` on at or above that id; `brief_problems` wants a `Semver:`
   line agreeing with the row and no `## VERSION` section. `policy` refuses a `job/` branch at or above it that changes `VERSION`. `warscape/release.py`:
   pure `plan`, `bump`, `done_since`, `floor_reasons`, `remote_tag_state`, `green_problems`, `tag_message`; git and gh behind an injected `run`.
3. **Workflow** `release` (`workflow_run` of `gates` on `main`, `workflow_dispatch` with `version`; `concurrency: release`, no cancel; not a required
   check; no `continue-on-error`): `check-green` (every required check but `policy` success or skipped, the latest run per name, and the sha still
   main's tip), `plan`, then `open` (release branch, `Release-By: workflow` trailer, `gh pr create`, `gh pr merge --auto --squash`) or
   `check-consumers` + `tag` (re-derives the version; `git tag -a`, `git push origin refs/tags/vX.Y.Z`; an existing remote tag is a no-op only when it
   is the annotated tag on this commit, anything else fails) + `wsc gates --only core_pin`.
4. **Policy and core_pin.** `release/vX.Y.Z`: only `VERSION`, content `X.Y.Z`, one patch, minor or major step above the base's VERSION; in the
   docstring and the refusal text; judged by the base's code (W23: no new judge input, `JUDGE_API` unchanged). `core_pin` in the core, on main
   (`GITHUB_REF` main, or HEAD an ancestor of `origin/main`) with tags in the checkout: `v<VERSION>` missing is a `warn` for `[release] grace_minutes`
   (120) after the commit that set VERSION, then an `error`; lightweight at or above `[release] annotated_from` (0.34.0) is an `error`.
5. **Manual lever:** `--version` on `plan`, `open` and `tag`, only through the dispatch input: greater than the last tag, one step above VERSION.
6. **Consumer compile:** `proxy/tools/adapter_syntax.py` (deviation 1) reads the DLL compile line's flags from build.sh's text at run time. CI's
   `proxy` job runs it on `null_game` and `null_game_no_gesture` (both compile) and on a copy of `null_game` with the gesture initialiser removed, which
   must fail naming `gesture`. `[release] consumers` names napoleon (`liam-rowley/napoleon-remastered`, `proxy/napoleon`, public).
   `wsc release check-consumers` prints `ok`, `fails: <first error>` or `skipped: <why>`, writes the JSON the tag message reads, opens one issue per
   failing consumer and tag (hidden mark) and, with `consumer_check = "block"`, exits 1.
7. **`wsc core bump <tag>`** (`warscape/verbs/core.py`; `release` and `core` added to `CORE_VERBS`; tool rows `wsc.core`, `wsc.release`,
   `proxy.tools.adapter_syntax`).

## Evidence
- Tests: `tests/test_release.py` (among them the `--force` and `GITHUB_TOKEN` grep of the module, the verb and the workflow),
  `tests/test_core_bump.py` (3, real repositories over file://), `tests/test_policy_base.py` (a base-judged `release/` branch, and a head that widens
  its own kind), `tests/test_ci.py` (the manual line). Committed first in f454a13 without the code; the pre-push hook refused to push that red tree,
  so it went up with the code in 1b5c14e. Local (Windows, 2026-11-04): the affected modules, 289 tests, green; `gates --fast` green. A full local
  `gates` exceeds the 600 s tests timeout on this PC, so CI is the full run.
- `release plan --json` on this branch: `tag 0.34.0`, level minor (floor: schemas, two verb modules, CORE_VERBS), row W38, "bumped by hand: tagged as
  it is". On `origin/main` (79ebbb4): `tag 0.30.1`, row W38 patch (W38's hand bump, untagged on 2026-11-04).
- `release check-green --sha 79ebbb40 --repo liam-rowley/warscape-core` (read-only): `gates (windows-latest)`, `proxy` and `harness-windows`
  in_progress, "not green: no release", exit 1.
- `build_id.py --inputs` does not run in this Windows worktree (it reports the null adapter untracked); instead `git diff origin/main --stat --` every
  INPUTS path (proxy/src, build.sh, fetch_lua.py, build_id.py, fetch_ui.py, toolchain.py, both null games) is empty: the build id is unchanged.
- Only unit-tested: the App token, the pull request and auto-merge, the tag push, the consumer checkout (injected runners).

## CI
- Run 41888137895 (446919f, 2026-11-04): `proxy` green, with the new step: `null_game` and `null_game_no_gesture` "ok", the copy without
  the gesture initialiser "fails: adapter.cpp:29:127: error: missing initializer for member 'wsp::GameAdapter::gesture'
  [-Werror=missing-field-initializers]"; `harness-windows` green; both `gates` red on one test (`test_checks.StdlibOnly`: the test imported
  `adapter_syntax` by name), fixed in 82dc133.
- Run 41889815638 (82dc133, 2026-11-04): `gates (ubuntu-latest)` and `gates (windows-latest)` green (full set, `ci_render` among them, 3 workflows);
  `proxy` and `harness-windows` skipped by their pass markers (the same input trees passed in 41888137895).

## Deviations
1. **`proxy/tools/adapter_syntax.py`, not `build.sh syntax`.** build.sh is a DLL input (`build_id.py` INPUTS role `build_sh`): any edit changes every
   build id, which the brief's kill criterion forbids. The new tool takes its flags from build.sh's `build_dll` line at run time (a test checks they
   are the DLL's), so the two compile lines cannot drift.
2. **`null_game_no_gesture` compiles** (W37 gave it `gesture = nullptr` explicitly), so the guard's negative case is a CI-made copy of `null_game` with
   the `&kGesture` initialiser removed; the step fails if that copy compiles or its error does not name `gesture`.
3. **App secrets** `RELEASE_APP_CLIENT_ID` and `RELEASE_APP_KEY` beside `RELEASE_TOKEN`, after Liam's App decision; the token is `RELEASE_TOKEN` inside.
4. **`docs/RELEASES.md`** (new) holds the flow and the setup: `docs/CONSUMING.md` was at 28.7 of its 30 KB, so its "Upgrading and releasing" section
   carries a short Releases bullet that links there.
5. **Tests in `tests/test_release.py`** for the policy kind, the semver rules and the `core_pin` rule (pure), rather than spread over `test_policy.py`,
   `test_jobs.py` and `test_core_pin.py`; the base-judged case is in `test_policy_base.py`.
6. **`semver_from` 40 and VERSION 0.34.0**: W39 reached `main` while this was built, and W15, W16 and W25 hold 0.31.0 to 0.33.0 on their branches.
7. A schema-only change with no done rows releases a `minor` (the floor applies with no rows: a consumer gets a changed schema).
8. The manual 1.0.0 takes two dispatches: the first opens the release pull request, the automatic run on its merge is red (VERSION above what the
   rows give: the re-derivation guard), and a second dispatch with the same version tags it.

## Open questions
1. **For Liam, the GitHub App** (decided by Liam 2026-11-04: GitHub App; steps also in `docs/RELEASES.md`, "The token"): create a private app on your
   account (Webhook off, "Only on this account"); repository permissions Contents read and write, Pull requests read and write, Issues read and write,
   Checks read-only (Metadata read-only is automatic), nothing else; generate a private key; install it on `liam-rowley/warscape-core` only (napoleon
   is public, so the consumer clone needs no access); add the Actions secrets `RELEASE_APP_CLIENT_ID` (the app's Client ID) and `RELEASE_APP_KEY`
   (the whole .pem file).
2. **For Liam, the tag ruleset:** Settings, Rules, Rulesets, New tag ruleset, enforcement Active, include `refs/tags/v*`, "Restrict updates" and
   "Restrict deletions", plus "Restrict creations" with the app as the only bypass actor; keep Settings, General, "Allow auto-merge" on.
3. Followed the recommendations: a failing consumer warns (1); `major` before 1.0.0 is `minor` (3); the 30 lightweight tags stay (4); `none` rows
   release nothing (5).
4. Until this merges and the App exists, the orchestrator tags by hand as C27 says (v0.30.1 is untagged today). From 0.34.0 nobody does: a hand-made
   lightweight `v0.34.0` would turn `core_pin` red.

## What napoleon and the reviewer do
- Napoleon: the bump to v0.34.0 is by hand (its pinned core has no `core bump`); after that `python3 core/wsc.py core bump vX.Y.Z`, delete the verbs it
  names (`tools/verbs/discovery.py` collides with the core's `discovery`), run `gates`.
- Reviewer, after the merge: the `release` run on the merge must end `tag` for v0.34.0 with an annotated tag (`git cat-file -t refs/tags/v0.34.0`
  says `tag`) and a green `core_pin`; without the App secrets it fails at the token step with the named message and changes nothing (tell Liam).
