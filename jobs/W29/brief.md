# W29: Release tags by workflow: semver on rows, release branch, annotated tags on a green main

Model: Opus, reason: enforcement and release infrastructure. This job adds a branch kind to `policy` (the check that decides what reaches `main`
unreviewed), a workflow that holds a write token and pushes tags, and a gate change; a mistake is a bypass or a wrong tag nobody can move back (C27:
tags are never moved). Budget about 170 tool calls: about 40 for the pure library and its tests, 40 for policy, schema, brief rule and `core_pin`,
50 for the workflow, the consumer compile and the `core bump` verb, 40 for docs, gates and CI round trips. At the cap, stop, commit, and report what is left.

## Goal
C27 (Liam, 2026-11-04) replaces "tags are cut by Liam only" with release tags made by a workflow. Today every job branch edits `VERSION`, parallel jobs
renumber on merge (W10, W20 and W22 did on 2026-11-04; v0.11.0 and v0.12.0 never existed), all 30 tags are lightweight, `V0.1.0` was upper case (deleted
2026-11-04) and v0.16.0 sat on a red `proxy`. The audit (napoleon-remastered `docs/audits/AUDIT_2026-11-03.md`, "Automation opportunities" 1 and 2, C2, the
`core_pin` rule row) asks for a tag that is a pure function of a green `main`. After this job:
1. **Rows carry the version level.** `registries/jobs` rows get `semver` (`patch|minor|major|none`). Job branches stop editing `VERSION`.
2. **A `release` workflow** tags a green `main`: it computes the next version from the rows that became `done` since the last tag, opens `release/vX.Y.Z`
   (a new policy branch kind that may change `VERSION` only), auto-merges it and puts an **annotated** tag on the merge commit. It never moves a tag.
3. **`core_pin`** checks that a tag exists for `main`'s `VERSION`.
4. **Before tagging**, CI compiles each consumer's adapter against the candidate (`-fsyntax-only`), which would have caught audit C2.
5. **`wsc core bump <tag>`** writes a consumer's bump commit (gitlink and `[core] version` together, B9) and names colliding game verbs.
After W22 (main health: green means something) and W23 (policy judged with the base's rules, `pull_request_target`); both are `done`.

## What exists (read before building; citations checked 2026-11-04 against `origin/main` ea98a96)
- **Rules:** `CLAUDE.md` ("While you work": the tag sentence, which this job replaces), `docs/DECISIONS.md` C18, C24, C27, `docs/CONSUMING.md`
  ("Upgrading and releasing" line 99-103 says "after Liam merges it, the tag vX.Y.Z is cut"; "The job pipeline"), `docs/REVIEW.md`, `docs/BACKLOG.md` B9,
  `jobs/W22/report.md` and `jobs/W23/report.md` (their changes are the ground this stands on).
- **`VERSION`** is 0.30.0 and `v0.30.0` is the latest tag (`git tag --sort=-v:refname`); every tag is lightweight (`git cat-file -t refs/tags/v0.9.0` says `commit`).
- **`warscape/policy.py`:** the branch kinds are the `if/elif` chain at :190-216 (`job/`, `brief/`, `plan/`, `meta/`, else refusal); `check()` is pure; the kind
  list is also in the module docstring and in the refusal text at :213. `warscape/policy_base.py` judges with the base's code (W23): the head is data only.
  A new kind must work in that child (`JUDGE_API` may only gain optional arguments).
- **`warscape/gates.py`:** `core_tag_problems` (:184-190, every tag on HEAD is `v` + VERSION), `gate_core_pin` (:192-218; `ctx.is_core` branch first),
  `Result` statuses `ok|warn|error`. `tests/test_core_pin.py`.
- **`schemas/jobs.schema.json`** (`additionalProperties: false`, so a new field needs the schema), `warscape/jobq.py` `brief_problems` (:116, the Model-line
  rule: model the shape of a new `Semver:` rule on it) and `problems` (:250).
- **CI:** `ci/gates.yml.in`, `ci/policy.yml.in`, `warscape/ci_render.py` (`render_text`, `[ci] workflows`; a template with no placeholders must still render
  and be compared by the `ci_render` gate), `warscape/ci_main.py` (W22: the required-checks rule and the `gh` runner to reuse), `warscape/ci_settings.py`,
  `wsc.toml` `[ci]` (`required_checks`: `policy` is produced only by pull requests, never by a push to `main`).
- **The adapter contract** the compile guards: `proxy/src/adapter.h` (`GameAdapter`, which gained `gesture` and broke napoleon's `proxy/napoleon/adapter.cpp`
  under `-Werror=missing-field-initializers`), `proxy/tools/build.sh` (:166-172, the one compile line and its flags), `proxy/tests/null_game*`.
- **Verbs:** `warscape/cli.py` `CORE_VERBS` (:13) and `_load_verbs` (a game's `[cli] verb_dirs` modules load after them: a game verb with a core name is the
  collision `core bump` must name); napoleon has `tools/verbs/discovery.py`, which is exactly that collision.
- **Not available to a workflow:** events caused by `GITHUB_TOKEN` (a push, a pull request it opens) start no workflow runs, so a release pull request opened with
  it would never get `gates` or `policy` and auto-merge would wait forever. Decision 1 is the answer.

## Decisions already made (follow them; a deviation goes in the report with its reason)
### 1. The release token (Liam's setting; the job makes the code fail clearly without it)
The workflow opens and merges the release pull request with a repository secret `RELEASE_TOKEN` (a fine-grained token or a GitHub App token; contents and
pull requests write on this repo, contents read on each consumer repo named in `[release]`). A step that finds the secret empty fails the run with the
message "RELEASE_TOKEN is not set: see docs/CONSUMING.md, Releases" and does nothing else; it never falls back to `GITHUB_TOKEN`. The job creates no secret.
The tag is pushed with the same token. `wsc ci check-settings` gains a manual line (a secret value cannot be read without admin rights) telling the owner to
create the secret, to keep `allow_auto_merge` on and to add a tag ruleset on `v*` (no update, no deletion); the same text goes in `docs/CONSUMING.md`.

### 2. Rows: `semver`, and who still edits VERSION
- Schema: `semver` optional enum `patch|minor|major|none`. `jobs check`: required from status `queued` on, for job numbers at or above
  `[jobs] semver_from` (new `wsc.toml` key, default `0` = off; this job sets it to one more than the highest `W<n>` row on `origin/main` when it is built, so
  no existing row needs an edit and `job/` branches may change only their own row). Rows below it without `semver` count as `patch`.
- `none` = no release (docs-only, row-only work). `brief_problems` gains a `Semver: <level>` line that must agree with the row (like the Model line) for ids
  at or above `semver_from`; the "## VERSION" section of a brief is replaced by that line.
- Policy: on a `job/` branch with an id at or above `semver_from`, a change to `VERSION` is refused ("the release workflow owns VERSION (C27)"). Older ids
  keep editing it (their briefs say so); this job's own branch bumps `VERSION` by hand to the next minor, as a legacy job.
- **Compute (`warscape/release.py`, pure functions):** `done_since(tag_rows, head_rows)` = rows `done` at HEAD that were not `done` at the last tag (read with
  `git show <tag>:registries/jobs/<id>.json` and `git ls-tree`, never the working tree); level = highest of their `semver` (missing counts as `patch`,
  `none` counts as nothing). Forced floor `minor`: any change under `schemas/` or to the verb set (a file added or removed under `warscape/verbs/`, or a
  `CORE_VERBS` edit) between the tag and HEAD. While the major number is 0, `major` is applied as `minor` and the tag message says so; `1.0.0` is cut only
  by hand (decision 5). Base = the greater of the last tag and `VERSION` on `main`. If only legacy rows (below `semver_from`) are `done` since the tag and
  `VERSION` already exceeds the tag, the release is that `VERSION` as it is, with no release pull request (the first releases after this lands: in-flight jobs
  still bump by hand). Nothing to release = no new version, exit 0.

### 3. The `release` workflow (`ci/release.yml.in`, rendered to `.github/workflows/release.yml`, listed in `[ci] workflows`)
- Triggers: `workflow_run` of `gates` completed on `main` (and `workflow_dispatch` with an optional `version` input, decision 5). `concurrency: {group: release,
  cancel-in-progress: false}`. Job name `release`; it is not in `required_checks`, and it has no `continue-on-error` (a red release run is the signal).
- **Green gate:** a verb action `wsc release check-green --sha <sha>` reads the check runs of the commit through `gh api` (the injected runner of
  `ci_main.py`) and passes only when every `[ci] required_checks` entry except `policy` has concluded `success` or `skipped` (a skipped job counts as passed,
  as in branch protection) and none is missing or in progress. The workflow acts only when the run's sha is still the tip of `origin/main` (a newer push starts
  its own run).
- **Prepare:** `wsc release plan --json` prints `{action: none|release|tag, version, level, rows, reasons}`. `release`: create `release/vX.Y.Z` from the tip
  (commit `VERSION` only, message names the rows, trailer `Release-By: workflow`), push, `gh pr create`, `gh pr merge --auto --squash`.
  The `policy` and `gates` runs on that pull request are the proof it is safe; the new `release/` kind is decision 4.
- **Tag:** the next run (the release merge commit's own green `gates`) sees `VERSION` greater than the last tag and no pending rows: action `tag`. It re-derives the
  version itself and refuses (red run, no tag) when `VERSION` on `main` is not what the rows and the floor give (so an agent's own `release/` branch cannot
  choose a version). `git tag -a vX.Y.Z -m <message: version, level, the done rows with titles, consumer check result>` on that merge commit, then
  `git push origin refs/tags/vX.Y.Z`. **Never moves a tag:** if `refs/tags/vX.Y.Z` exists on the remote, it must be an annotated tag object whose commit is this
  one (then the step is a no-op) or the run fails. `--force` never appears in the workflow or the verb (a test greps the rendered workflow and the module for it).
- If the render cannot express a block, keep it in the template; the `ci_render` gate must stay green and the rendered file byte-equal.

### 4. Policy: the `release/` kind, and `core_pin`
- `release/vX.Y.Z` may change only `VERSION`; its content must be `X.Y.Z` (the branch name), exactly one patch, minor or major step above the base's `VERSION`.
  Anything else is refused with the fix. It is judged like any other kind (W23: the base's code; the head only as data). Add the kind to the docstring, the
  refusal text and `tests/test_policy.py` / `tests/test_policy_base.py`.
- `core_pin` (core): on `main` (HEAD reachable from `origin/main`, or `GITHUB_REF` main), `v<VERSION>` should exist and be an annotated tag from the version in
  `[release] annotated_from` (new `wsc.toml` key, set by this job to the first version the workflow tags; older tags stay lightweight and are not rewritten).
  A missing tag is a `warn` ("release workflow pending") until the commit is older than `[release] grace_minutes` (default 120), then `error`; a shallow or
  tag-less checkout stays VERSION-only as C21 says. `core_tag_problems` keeps its lower-case `v` rule. The release workflow runs `wsc gates --only core_pin`
  (or the nearest existing filter; add one if none) after pushing the tag, as its last step.

### 5. Manual lever (Liam's, never an agent's)
`workflow_dispatch` with `version` (to cut `1.0.0`, or to retag after an outage): it validates the string, requires it greater than the last tag, requires a green
`main` (decision 3) and goes through the same release pull request and tag code. No other path chooses a version.

### 6. The consumer compile
- `wsc.toml` `[release] consumers = [{name = "napoleon", repo = "<owner>/napoleon-remastered", adapter = "proxy/napoleon", ref = "main"}]` (a repo-relative adapter
  folder; the job sets the real values with the token's reach in mind; an unreachable consumer is a `skipped` line, never a green claim).
- A new target `proxy/tools/build.sh syntax --adapter DIR` runs the same compile line as `build_dll` with `-fsyntax-only` and the same warning flags
  (`-Wall -Wextra -Wshadow -Werror`, so a missing initialiser in `GameAdapter` fails), no linking, no Lua or UI objects, and exits non-zero on error. The proxy
  CI job runs it for `proxy/tests/null_game`, and `null_game_no_gesture` must fail it (a test of the guard). `wsc release check-consumers --candidate <sha>`
  checks out each consumer (token from decision 1, shallow), runs `build.sh syntax --adapter <checkout>/<adapter>` and prints one line per consumer
  (`ok`, `fails: <first error>`, `skipped: <why>`).
- **Result handling (open question 1):** a failing consumer does not block the tag (the consumer must bump anyway, and a block would deadlock a change that adds
  a required member); it is written into the annotated tag message, the step summary and one `gh issue` per consumer and tag (hidden mark, reuse `ci_main`'s
  open-or-update helper), naming the adapter file and the first error. `[release] consumer_check = "warn"|"block"` selects it; default `warn`.

### 7. `wsc core bump` (a new verb, `warscape/verbs/core.py`, in `CORE_VERBS`)
`python3 core/wsc.py core bump <tag> [--no-commit] [--session ID]` in a consumer: refuse a dirty tree, a tag not of the form `vX.Y.Z`, a tag not found after
`git -C core fetch --tags`, a lightweight tag at or above `[release] annotated_from` (read from the new core), and the core itself. Then check out the tag in the
submodule, write `[core] version` (a text edit that keeps the file's comments), run `ci render` when the repo has `[ci] core`, and make one commit holding the
gitlink, `wsc.toml` and the rendered workflows with the `Claude-Session` trailer (`--session`, `$WSC_SESSION_ID`, `$CLAUDE_CODE_SESSION_ID`, as C26; no id is a
refusal). It prints the verbs that collide: a module in the consumer's `[cli] verb_dirs` whose `NAME` is in the new core's `CORE_VERBS` (read as text from the
checked-out `warscape/cli.py`, like `JUDGE_API`), with the advice "delete it; the core's verb replaces it", and deletes nothing itself. `--no-commit` leaves the
changes staged. Header lines, a `wsc.core` row in `registries/tools.jsonl`, `docs/CONSUMING.md`.

## Scope: files this job touches
`warscape/release.py` (new), `warscape/verbs/release.py` (new: `plan`, `check-green`, `check-consumers`, `tag`), `warscape/verbs/core.py` (new), `warscape/cli.py`
(`CORE_VERBS`), `warscape/policy.py` (kind, docstring, `VERSION` rule), `warscape/policy_base.py` (only if the kind needs an input), `warscape/gates.py`
(`core_pin`), `warscape/jobq.py` (`semver` rules), `warscape/repo.py` (`DEFAULTS`: `[jobs] semver_from`, `[release]`), `warscape/ci_settings.py` (the manual
line), `schemas/jobs.schema.json`, `wsc.toml`, `ci/release.yml.in`, `.github/workflows/release.yml` (rendered), `proxy/tools/build.sh` (`syntax`),
`ci/gates.yml.in` and its render only to run the new `syntax` check in the `proxy` job, `tests/test_release.py` and `tests/test_core_bump.py` (new),
`tests/test_policy.py`, `tests/test_policy_base.py`, `tests/test_core_pin.py`, `tests/test_jobs.py`, `tests/test_ci.py`, `registries/tools.jsonl`,
`docs/CONSUMING.md` (a "Releases" section, "Upgrading and releasing", the settings), `CLAUDE.md` (the tag sentence), `README.md` if it states the tag rule,
`VERSION`. Not `registries/jobs/` other than W29's own row, not `core/` of any game. `build.sh` is a DLL-input question: `build.sh syntax` is tooling and
`build_id.py --inputs` must be identical to `main`'s (compare and say so in the report; if it differs, stop and ask).

## Steps
1. Read "What exists". `python3 wsc.py gates --fast` once for a baseline. Check `python3 wsc.py ci check-settings` runs.
2. **Failing tests first**, committed red:
   - `tests/test_release.py` on pure inputs: the level table (patch, minor, major, none, mixed, missing = patch, legacy rows ignored), the floor from a
     `schemas/` change and from a verb added or removed, major-while-0 applied as minor with the note, base = max(tag, VERSION), the legacy path (VERSION above the
     tag and only legacy rows: action `tag`, no release branch), nothing to release, the re-derivation refusal (VERSION on main not equal to the computed
     one), an existing remote tag on the same commit (annotated: no-op), on another commit or lightweight (fail), the grep for `--force`.
   - runner-injected tests: `check-green` (all green, one red, one missing, one in progress, `policy` ignored, skipped counts as passed, stale sha),
     `check-consumers` with a fake compiler (ok, fails with the first error line, unreachable consumer skipped, `warn` vs `block`).
   - `tests/test_policy.py` and `tests/test_policy_base.py`: a `release/v0.31.0` with only `VERSION` = `0.31.0` passes; two files, a wrong content, a name that
     does not match, two steps at once, a version not greater than the base, a `job/` branch (id at or above `semver_from`) that edits `VERSION`, an older id that
     does, each refused or passed as written.
   - `core_pin` cases (annotated tag present, lightweight below `annotated_from`, missing inside and past the grace window, shallow); the `semver` schema,
     `jobs check` and brief-rule cases; `tests/test_core_bump.py` on temporary repositories (a consumer with a local submodule over `file://`,
     `-c protocol.file.allow=always`): the commit holds gitlink and toml together, trailer present, dirty tree, bad tag, lightweight tag past `annotated_from`,
     colliding verb named, `--no-commit`, no session id.
3. Build `warscape/release.py` and the verb actions (decisions 2, 3, 5), then policy, `core_pin` and `jobs` (2, 4), then `build.sh syntax` and
   `check-consumers` (6), then `core bump` (7). One commit each, tests green at each.
4. The workflow: write `ci/release.yml.in`, add it to `[ci] workflows`, `python3 wsc.py ci render`, commit template and workflow together. Add the `syntax`
   step to the `proxy` job and re-render. Push early: the first push proves the workflow file is valid (the `release` job triggers only after `gates` on `main`).
5. **Proof the builder can make without a push to `main`:** run `python3 wsc.py release plan --json` on this branch and on `origin/main` (paste both: the
   action, the version, the rows), `python3 wsc.py release check-green --sha <a recent main sha> --repo <this repo>` read-only, `build.sh syntax --adapter
   proxy/tests/null_game` (ok) and `null_game_no_gesture` (fails with the missing member named), and `wsc core bump` against the fixture game in a temporary
   folder. State what could only be unit-tested (the token, the pull request, the tag push, the consumer checkout).
6. Docs (`CONSUMING.md` "Releases": the flow, the secret, the tag ruleset, `semver_from`, the manual `1.0.0` path, the consumer steps below), `CLAUDE.md` (the tag
   sentence: "Tags are made by the release workflow (C27); jobs state a `semver` level and no longer edit `VERSION`"), `VERSION` (decision 2),
   `python3 wsc.py gates` (full), `python3 wsc.py policy --branch job/W29 --base origin/main`.

## Tests and acceptance
- New host tests red first, then green; `python3 wsc.py gates` green; the branch's CI run id, including the `proxy` job's `syntax` step and `ci_render`.
- `release plan` output on `origin/main` says what the first real run would do (expected: `action: none`, or `tag` for a hand-bumped VERSION above `v0.30.0`).
- The negative proofs exist as tests: no code path moves or force-pushes a tag; no path uses `GITHUB_TOKEN` for the release pull request; an empty
  `RELEASE_TOKEN` fails with the named message.
- **For the reviewer, after the merge (the first real run, which the builder cannot make):** the `release` run on the merge's push to `main` must end `none` or
  `tag` with an annotated tag (`git cat-file -t refs/tags/vX.Y.Z` says `tag`) and a green `core_pin`; if `RELEASE_TOKEN` is not set yet, the run fails with the
  named message and nothing else changes (tell Liam).

## What consumers must do after the tag (napoleon-remastered)
- Bump with `python3 core/wsc.py core bump v<new>` (from this tag onward), delete the verbs it names, run `gates`; the pin, `wsc.toml` and the rendered
  workflows are one commit (B9). Napoleon's job briefs and rows gain `semver` only for the core's own rows (a consumer has no `VERSION` to bump for the core).
- `[release] consumers` names napoleon's repository and adapter folder; the token must read it. Napoleon's `core_pin` is unchanged.
- **For Liam (settings, his to change):** the `RELEASE_TOKEN` secret, a tag ruleset on `v*` (no update, no deletion), `allow_auto_merge` on. The job changes none of them.

## Kill criteria
- Any code path can move, delete or force-push a tag, or tag a commit whose required checks are not green: stop and fix before anything else.
- The `release/` kind can change a file other than `VERSION`, or pass a version other than one step above the base: stop (policy is the bypass surface).
- A step needs a DLL input change (`proxy/src`, the `build_id.py` inputs): stop and ask; `build.sh syntax` must not change the build id.
- The workflow cannot be made to work without `GITHUB_TOKEN` events (decision 1) and the only way forward is a fallback to that token: stop, report, ask Liam.
- Core CI red after three fix attempts for a cause in this change, or about 170 calls: stop and report. A `VERSION` collision with another merge: take the next
  free number and merge `main` (never rebase a pushed branch).

## Open questions (with recommendations; the builder follows the recommendation unless Liam says otherwise)
1. **Should a failing consumer compile block the tag?** Recommended: no, `warn` (decision 6): the consumer must bump anyway and a required new member would
   deadlock; the failure is in the tag message and an issue. Set `consumer_check = "block"` to change it.
2. **A GitHub App instead of a personal token?** Recommended: either works with the same secret name; a fine-grained personal token is faster to set up and the
   App is better long term (no person behind the tags). Liam's call; the code does not care.
3. **`major` before 1.0.0.** Recommended: applied as `minor` with a note in the tag message; `1.0.0` is a deliberate manual dispatch (decision 5).
4. **Retag the 30 lightweight tags as annotated?** Recommended: no. A tag is never moved (C27), and `annotated_from` makes the rule start where the workflow does.
5. **Should `none`-level rows (docs-only) still produce a release?** Recommended: no; the version moves only for work that changes what a consumer gets.
6. **File overlap for whoever merges second** (merge `main`, never rebase): W26 to W28 and W35 touch `warscape/jobq.py`, `warscape/gates.py`, `warscape/cli.py`,
   `docs/CONSUMING.md`; re-read `docs/BACKLOG.md` and the open `job/*` branches before the last commit. W15, W16, W25 and W33 bump `VERSION` by hand; their
   merges decide the number this job takes.

## Finish
Report in `jobs/W29/report.md` (what was built per decision, tests red then green and where they ran, the branch run id with `ci_render` and the `syntax` step,
the `release plan` outputs, the `build_id.py --inputs` comparison, the version taken, deviations, open questions, what napoleon and Liam must do, what the
reviewer checks on the first `main` push), then `wsc reg set jobs W29 status=review report=jobs/W29/report.md` (`python3 wsc.py`).
Push `job/W29`, open the draft pull request, and stop: an independent reviewer merges (C18); the workflow tags (C27).
