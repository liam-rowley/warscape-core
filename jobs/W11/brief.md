# W11: core_pin: testable, worktree-safe, shallow-safe

Model: Sonnet, reason: none needed (Sonnet is the default). One gate in `warscape/gates.py` and host tests that build throwaway git repositories;
no DLL, no PC. Budget about 60 tool calls; at the cap, stop, commit what is green, and list in the report what is left.

## What
Backlog B7, B11 and B12 (`docs/BACKLOG.md`), all about the `core_pin` gate (`warscape/gates.py` `gate_core_pin`, `pin_problems`; decision C10). In a
game repo it checks that the `core/` submodule is the pinned `vX.Y.Z` tag, its `VERSION` matches, and it has no local changes ("a game repo never
patches the core in place", C1).

1. **B7: testable on a throwaway core.** `gate_core_pin` reads the pin's version through `core_version()` (`warscape/__init__.py`), which reads the
   **running** core's `VERSION` (`CORE_ROOT`), not `ctx.core_root`, so a test cannot point the gate at another checkout; and the only end-to-end test
   (`tests/test_cli.py` `test_core_pin`) runs against the real core, so "dirty core fails" is never seen failing (it accepts either outcome). Read
   `VERSION` from `ctx.core_root` in the gate (keep `core_version()` for `wsc --version`). Then a failing-fixture test: a temp git repo as the core
   (a `VERSION`, a commit, a `vX.Y.Z` tag), a temp game repo pinning it, `Ctx(root=game, config=..., core_root=fake core)`, and the cases
   clean and tagged (ok), a modified tracked file (error, names the file), an untracked file (error), HEAD one commit past the tag (error,
   "untagged commit"), `VERSION` not matching the pin (error). Show it red against the old code first (commit the test before the fix, or say in the
   report how you saw it fail).
2. **B11: from a linked worktree.** Napoleon J3 (review 8, 2026-10-29) saw the pre-push hook's `GIT_DIR` make `core_pin` read the superproject's
   status from a linked worktree. C12 (`warscape/repo.py` `git_env`, napoleon J5, the same day) already drops the repository-selecting `GIT_*`
   variables from every core git call, and B11 was filed two days later from the older review, so it may already be fixed. Prove it either way with a
   real case, not a reading: a temp superproject with the fake core added as a submodule at `core/` (`git -c protocol.file.allow=always submodule
   add`), `git worktree add` of the superproject, `git submodule update --init` inside the worktree, then run the gate for the worktree with the
   environment a pre-push hook in that worktree gets (`GIT_DIR` set to the worktree's git dir; also `GIT_INDEX_FILE` and `GIT_WORK_TREE` if your
   git exports them: print them from a real `pre-push` hook once and record what you saw). Expected: clean core is ok, a modified file in the
   worktree's `core/` is an error, a modified file in the superproject is not. If it passes on the first run, B11 was fixed by C12: keep the test as
   its regression guard and say so in the report. If it fails, find the leak (any `subprocess` git call in the gate path without `env=git_env()`) and
   fix it there.
3. **B12: on a shallow submodule.** A depth-1 submodule fetch brings the core tip's tag but not the pinned one once the core has a newer tag, so
   `pin_problems` sees "tags exist, none on HEAD" and fails (napoleon J41 review, reviewer fix and later item 5; napoleon CI works around it with a
   step that fetches the pinned tag, `ci/gates.yml.in` lines 63 to 66). New rule, decided here (see open question 1):
   - the pinned tag exists in the checkout (`git rev-parse -q --verify refs/tags/<pin>^{commit}`): its commit must be HEAD, else an error as today;
   - it does not exist and the checkout is shallow (`git rev-parse --is-shallow-repository` says `true`): compare `VERSION` only, with the summary
     saying so ("pinned tag v… not in this shallow checkout: VERSION only");
   - it does not exist and the checkout is not shallow but has other tags: an error naming the fix (`git -C core fetch --tags`);
   - no tags at all: `VERSION` only, as today.
   Make `pin_problems` take what it needs as plain values (the pinned tag's commit or None, HEAD's commit, shallow or not) so the unit cases in
   `tests/test_checks.py` stay pure, and add an end-to-end case: a core with tags v0.1.0 and v0.2.0, a game pinning v0.1.0, the submodule cloned with
   `--depth 1` the way CI does it (reproduce napoleon's failure first: "untagged commit"), then green with the new rule; and the same game with the
   tag fetched still checks tag against HEAD.
4. **Docs and release.** A new decision row in `docs/DECISIONS.md` (append only; the next free `C<n>`, "proposed (Claude, core W11)") that
   amends C10's shallow clause with the rule above and names C10. `README.md` "Gates" (the `core_pin` sentence) and `docs/CONSUMING.md` (the
   `core_pin` sentence under the submodule recommendation) say what is compared when. Remove B7, B11 and B12 from `docs/BACKLOG.md`. `VERSION`: the next
   free patch (a fix to an existing gate; `main` holds 0.15.0 when this was written).

Files this job touches: `warscape/gates.py` (`gate_core_pin`, `pin_problems`), possibly `warscape/__init__.py` (only if a helper there changes),
`tests/test_checks.py`, a new `tests/test_core_pin.py` for the repository-building cases (or inside `tests/test_cli.py`; one place, your choice),
`tests/test_cli.py` (`test_core_pin` stops accepting either outcome once the fixture test covers it), `docs/DECISIONS.md`, `README.md`,
`docs/CONSUMING.md`, `docs/BACKLOG.md`, `VERSION`. Branch `job/W11`.

## Acceptance
- `python3 wsc.py gates` green locally and in CI on `ubuntu-latest` and `windows-latest` (the submodule and worktree cases run on both; `git` on the
  Windows runner allows the local-file protocol only with `-c protocol.file.allow=always`, which the test passes itself).
- The report shows each new case red before its fix (or, for B11, says it was green on the first run and why), and the recorded hook environment.
- `core_pin` inside the core itself (`ctx.is_core`) is unchanged: the core's own gates still say "this is the core (…)".

## The consumer's part (not here)
Nothing is required at the pin bump. After it, a game may drop its CI step that fetches the pinned tag (napoleon `ci/gates.yml.in` lines 63 to 66,
then `wsc ci render`); the pinned tag check then runs as "VERSION only" on CI's shallow submodule, as it did before 0.3.0. Napoleon's `policy.yml`
fetch of the pin commit is for its rule 79, not for `core_pin`, and stays. Say this in the report so the next napoleon pin-bump job can pick it up.

## Open questions (recommendation for each)
1. **The shallow rule** (item 3). Recommended as written: a tag that is present is always checked against HEAD; a missing tag weakens the check to
   `VERSION` only in a shallow checkout and nowhere else. The alternative, fetching the tag from inside the gate, breaks "gates need no network"
   (`warscape/gates.py` docstring). The weaker check on CI is the same one C10 already accepts for a checkout with no tags.
2. **If B11 is already fixed** (likely, see item 2): keep the real-worktree test anyway and remove B11 from the backlog; no code change for it.
3. **File overlap with W8 and W12** (likely built one after another; base on the latest `main`, merge `main` in, never rebase): W12 adds a new gate
   to `warscape/gates.py` (a new function and an entry in `GATES`), new keys in `warscape/repo.py` `DEFAULTS`, possibly a decision row, and edits
   `README.md` "Gates" and `docs/CONSUMING.md`; this job edits `gate_core_pin`/`pin_problems` and the `core_pin` sentences. Separate hunks; the
   decision numbers must not collide (take the next free `C<n>` when you commit, re-check after merging `main`). All three edit `VERSION` and
   `docs/BACKLOG.md`. W8 touches none of this job's code files.

## Kill criteria
- The linked-worktree case cannot be built on one of the CI platforms after about 10 calls (submodule in a worktree, file protocol): keep it on the
  platform where it runs, skip it on the other with the reason (a `warn` in the `tests` gate), and report.
- The shallow rule needs network access or a change to how a game's CI checks out the submodule: stop, record what you found, do not change a
  game's CI from here.
- The fix would change what `core_pin` says inside the core itself, or the C10 rules for a full clone: stop and report.
- CI red after three fix attempts for a cause in this change: stop and report.
- Version collision: W8 and W12 also bump `VERSION`. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit; the
  second to merge takes the next free number and merges `main`. Say in the report which number you took.

## Finish
Report in `jobs/W11/report.md` (each item: how it failed, the fix or why none was needed, the tests red then green, the recorded hook environment,
deviations, open questions), then `wsc reg set jobs W11 status=review report=jobs/W11/report.md` (`python3 wsc.py`). Liam tags the core after the
merge; stop after the PR.
