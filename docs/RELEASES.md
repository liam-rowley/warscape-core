# Releases: tags by workflow (0.35.0, core W29, C27)

The core's release tags are a function of a green `main`. Nobody tags by hand: not Liam, not an agent, not the orchestrator. The workflow is
`ci/release.yml.in` (rendered to `.github/workflows/release.yml`), the code is `warscape/release.py` and `wsc release` (warscape/verbs/release.py).

## The flow
1. A job row states its level: `semver` = `patch`, `minor`, `major` or `none` (no release: docs-only or row-only work). From `[jobs] semver_from`
   (40 in the core) `jobs check` wants it from status `queued` on, the brief carries a matching `Semver: <level>` line in place of a "## VERSION"
   section, and `policy` refuses a `job/` branch that edits `VERSION`. Older rows count as `patch`, and their jobs still bump `VERSION` by hand.
2. `gates` passes on `main`, and `release` starts (`workflow_run`, one at a time: `concurrency: release`). `wsc release check-green` passes only when
   every `[ci] required_checks` entry but `policy` concluded `success` or `skipped` on that commit and the commit is still `main`'s tip.
3. `wsc release plan`: the level is the highest `semver` of the rows that became `done` since the last tag; at least `minor` when `schemas/` changed or a
   verb was added or removed (or `CORE_VERBS` changed); `major` counts as `minor` while the major number is 0. Then:
   - `release`: `release/vX.Y.Z` is cut from the commit with `VERSION` only (trailer `Release-By: workflow`), its pull request opened and set to
     auto-merge (squash). `policy` judges the kind (`release/vX.Y.Z` may change only `VERSION`, to exactly one step above the base's).
   - `tag` (the release merge commit's own green run, or a hand bump by a legacy job): the version is re-derived from the rows, never taken from the
     branch; the consumers' adapters are compiled (`wsc release check-consumers`, `proxy/tools/adapter_syntax.py -fsyntax-only`); the annotated tag
     `vX.Y.Z` goes on the commit and is pushed; `wsc gates --only core_pin` closes the run.
   - `none`: nothing to release. `error`: `VERSION` on `main` is not what the rows give; the run is red and nothing is tagged.
4. A tag is never moved or deleted. An existing remote tag must be the annotated tag on this very commit (a no-op) or the run fails.

`core_pin` in the core: on `main` with tags in the checkout, `v<VERSION>` must exist (a warning for `[release] grace_minutes` after the commit that set
`VERSION`, then an error) and, from `[release] annotated_from`, be annotated. Older tags stay lightweight; none is rewritten.

## Consumers (`[release] consumers`)
Each entry (`name`, `repo`, `adapter`, `ref`) is cloned shallow and its adapter compiled against the candidate. `consumer_check = "warn"` (default): a
failure is written into the tag message, the step summary and one issue per consumer and tag, and the tag is still made (the consumer must bump anyway,
and a block would deadlock a change that adds a required `GameAdapter` member). `"block"`: no tag while a consumer fails. An unreachable consumer is
`skipped`, never `ok`. The consumer then bumps with `python3 core/wsc.py core bump vX.Y.Z` (docs/CONSUMING.md, "Upgrading and releasing").

## The token (the owner's settings; decided by Liam 2026-11-04: a GitHub App)
Events caused by `GITHUB_TOKEN` start no workflow runs, so the release pull request would never get `gates` or `policy`. The workflow therefore uses a
GitHub App token (secrets `RELEASE_APP_CLIENT_ID` and `RELEASE_APP_KEY`, through `actions/create-github-app-token` pinned by sha), or a token in the
secret `RELEASE_TOKEN`. With neither, the first step fails with "RELEASE_TOKEN is not set: see docs/CONSUMING.md, Releases" and nothing else runs.

1. **Create the app** (github.com, Settings, Developer settings, GitHub Apps, New GitHub App): name `warscape-release`, homepage the repo URL,
   Webhook off, "Only on this account". Repository permissions: Contents read and write, Pull requests read and write, Issues read and write, Checks
   read-only (Metadata read-only is automatic). Nothing else: no Workflows, Administration or Actions permission.
2. **Generate a private key** (the app's page, Private keys) and note its **Client ID**.
3. **Install it** on `liam-rowley/warscape-core` only ("Only select repositories"). The consumer `liam-rowley/napoleon-remastered` is public, so
   the shallow clone needs no access; a private consumer would need the app installed there with Contents read-only.
4. **Secrets** (warscape-core, Settings, Secrets and variables, Actions): `RELEASE_APP_CLIENT_ID` = the Client ID, `RELEASE_APP_KEY` = the whole
   `.pem` file.
5. **Tag ruleset** (Settings, Rules, Rulesets, New tag ruleset): name `release tags`, enforcement Active, target `Include by pattern` `refs/tags/v*`,
   rules "Restrict updates" and "Restrict deletions" (and "Restrict creations" with the app in the bypass list, so only the workflow can make a tag).
6. **Keep** Settings, General, "Allow auto-merge" on. `python3 wsc.py ci check-settings` prints these as its `manual:` line.

## The manual lever (the owner's only)
Actions, `release`, Run workflow, `version` = `X.Y.Z` (to cut `1.0.0`, or to retag after an outage). It must be greater than the last tag and one step
above `VERSION`, and `main` must be green. The run opens the release pull request; once it merges, the automatic run on the merge is red (the version
is not what the rows give) and the owner runs the workflow again with the same version, which tags it.
