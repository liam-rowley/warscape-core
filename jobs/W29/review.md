# W29 review

## Round 1 (2026-11-04, branch job/W29 at 86b4fd6)
**Verdict: merge.**

Read closely (the code that can move or mint a tag, spend a token or widen what reaches `main` unreviewed): `ci/release.yml.in`, `warscape/release.py`,
`warscape/verbs/release.py`, the `release/` kind and the `VERSION` rule in `warscape/policy.py`, `core_pin` in `warscape/gates.py`, `adapter_syntax.py`.
`main` had not moved (merge base = origin/main 6e743da, VERSION 0.33.0, so 0.34.0 and `semver_from` 40 are the next free numbers; W39 is the highest row).

Checked against the brief:
- No tag path moves or forces: `push_tag` pushes only when the remote ref is absent, a same-commit annotated tag is a no-op, anything else raises; no `-f`/`--force`
  in the module, verb or workflow (tests grep them). Tags go only on a commit `check-green` saw green and that is main's tip.
- No `GITHUB_TOKEN` for the release: the App token (or `RELEASE_TOKEN`) is minted first, an empty one fails before the checkout (which would otherwise
  fall back to the workflow token), `open` and `tag` call `need_token`. `workflow_run` is push-only (`gates` has no `pull_request`), so a fork cannot reach the
  secrets with its own `wsc.py`.
- `release/` kind: only `VERSION`, content = branch name, exactly one patch/minor/major step above the base; judged with the base's code (W23), `JUDGE_API` unchanged.
- The consumer compile is warn-only as decided, and `build.sh` is untouched (deviation 1: `adapter_syntax.py`; `proxy/src` and every build-id input unchanged).
- Rows, schema, brief rule, `jobs check`, `core_pin` (grace window, annotated from 0.34.0), `core bump`, docs and the manual settings line are present.
- Local: affected modules (test_release, test_policy_base, test_core_bump, test_core_pin, test_jobs, test_policy, test_ci) 223 tests green on Windows.

Findings:
- **should-fix (fixed in 86b4fd6):** `warscape/release.py` `plan`, the `V > T and not new` branch tagged "as it is" even when no row at all became done since
  the tag. A hand-made `release/v0.35.0` (VERSION only, one step up: policy passes it) would then have been tagged, so an agent could choose a version, which
  the brief's re-derivation rule forbids. Now an `error` ("no job row became done since"); the legacy hand-bump path (done legacy rows exist) is unchanged.
  Test `test_version_above_the_tag_with_no_rows_is_refused`.
- **later:** `open_release` assumes a remote `release/vX.Y.Z` with a MERGED pull request never recurs (the second `gh pr create` would fail "no commits"); the plan makes this
  unlikely, and the failure is a red run, not a wrong tag. Delete-branch-on-merge on the repo would remove it.
- **later:** the manual 1.0.0 needs two dispatches (report, deviation 8); fine, it is Liam's lever.

First real run (for whoever looks after the merge): the `release` run on the merge push must end `tag` for v0.34.0 (annotated, `git cat-file -t refs/tags/v0.34.0` says
`tag`) with a green `core_pin`, or fail at the token step with "RELEASE_TOKEN is not set" if the App secrets are not there yet (tell Liam). Never tag by hand.
