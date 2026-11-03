# W11 report: core_pin: testable, worktree-safe, shallow-safe

`core_pin` now reads `VERSION` from the core checkout it checks (`ctx.core_root`), not the running core (B7). On a shallow submodule it no longer fails on "tags exist, none on HEAD": a pinned tag that is in the checkout is always checked against HEAD, and one missing from a shallow checkout leaves `VERSION` as the only comparison (B12, decision C21, which amends C10). B11 (a linked worktree's pre-push `GIT_DIR` leaking into the gate) was already fixed by C12; it now has a regression test that runs under a pre-push environment recorded from a real hook. New host tests in `tests/test_core_pin.py` build throwaway git repositories (a fake core, a game pinning it, a real `core/` submodule, a linked worktree, a depth-1 submodule), and each case was seen red before its fix. VERSION 0.17.1.

## What exists
- `warscape/__init__.py`: `core_version(root=None)`. `wsc --version` still reads the running core; the gate passes `ctx.core_root` (B7).
- `warscape/gates.py`:
  - `pin_check(pin_commit, shallow, any_tags)` names the rule and returns `tag`, `shallow`, `missing` or `none`.
  - `pin_problems(want, version, pin_commit, head, shallow, any_tags, head_tags=(), core_dir='core')` takes plain values:
    - pinned tag present: its commit must be HEAD, else the old "the core checkout is at an untagged commit / tag(s) ..., not the pinned tag" error;
    - missing from a shallow checkout: `VERSION` only;
    - missing from a full checkout that has other tags: an error naming `` `git -C <core> fetch --tags` ``;
    - no tags at all: `VERSION` only, as before.
  - `gate_core_pin` gathers those values with `_git` (so every call uses `env=git_env()`):
    - `tag --list`;
    - `rev-parse -q --verify refs/tags/<pin>^{commit}`, looked up only when the pin is exactly one of the listed tag names, so tag case still matters;
    - `rev-parse HEAD` and `rev-parse --is-shallow-repository`.
  - The summary says which check ran: `tag v…`, `pinned tag v… not in this shallow checkout: VERSION only`, or `VERSION only: no tags in this checkout`.
  - The `ctx.is_core` branch is unchanged.
- `tests/test_core_pin.py` (new, 12 tests):
  - `DirtyCore` (B7): clean and tagged is ok; a modified tracked file is an error naming it; an untracked file is an error naming it; HEAD one commit past the tag is "untagged commit"; `VERSION` 0.1.1 under tag v0.1.0 is "checkout is 0.1.1".
  - `LinkedWorktree` (B11): a superproject with the fake core as a submodule at `core/`, a `git worktree add`, and `git submodule update --init` in the worktree. A real `pre-push` hook (via `core.hooksPath`) records its environment on a push from the worktree. The gate then runs with cwd set to the worktree and that environment applied:
    - a clean core is ok;
    - a modified `core/a.txt` in the worktree is an error;
    - a modified `g.txt` in the worktree and in the main checkout is ok;
    - `GIT_DIR` is in the recorded environment, and with `git_env` patched to pass it through, a clean core reads as broken (so the test can see a leak).
  - `ShallowSubmodule` (B12): a core with v0.1.0 and v0.2.0, a game pinning v0.1.0, cloned and `submodule update --init --depth 1` over `file://` (git ignores `--depth` for a plain path):
    - the checkout is shallow, holds only tag v0.2.0, and `VERSION` is 0.1.0; pin v0.1.0 is ok as "VERSION only", and pin v0.2.0 is still an error;
    - with the tag fetched (`fetch --depth 1 origin tag v0.1.0`, what napoleon CI does), it is ok as "tag v0.1.0", and a commit on top is "untagged commit";
    - unshallowed with v0.1.0 deleted, it is an error naming `git -C core fetch --tags`.
  - Every git call passes `-c protocol.file.allow=always` and its own identity, gpgsign and autocrlf settings.
  - Fixtures are built once per class (Windows git is slow), and the file runs in about 30 s locally. The worktree tests restore what they edit; the shallow tests clone the game fresh.
- `tests/test_checks.py`: the `pin_problems` unit cases moved to the new signature, and `test_shallow_rule` covers `pin_check` and each branch with plain values.
- `tests/test_cli.py` `test_core_pin`: no longer accepts either outcome. It checks only malformed pins (`v9.9.9`, `V9.9.9`) against the real core; the matching-pin cases live in `test_core_pin.py`.
- Docs:
  - `docs/DECISIONS.md` gets C21: proposed (Claude, core W11), amends C10's shallow clause.
  - `README.md` "Gates" and `docs/CONSUMING.md` (the `core_pin` sentence under the submodule recommendation) say what is compared when.
  - B7, B11 and B12 are removed from `docs/BACKLOG.md`.

## Tests, red then green
- **Red, commit `66c9299`:** the tests were committed before any fix. Against the old gate, 8 of 14 failed (the file had 14 tests then).
  - Every case that expected ok or a specific `VERSION` message failed with "wsc.toml pins core v0.1.0 but the core checkout is 0.15.0", because the old gate read the running core's VERSION (B7). These were `DirtyCore.test_clean_and_tagged`, `DirtyCore.test_version_not_matching_the_pin`, `LinkedWorktree.test_clean_core_is_ok`, `LinkedWorktree.test_modified_superproject_is_not_the_core` and all four ok/`VERSION` cases in `ShallowSubmodule`.
  - The shallow case also failed with napoleon's message: "the core checkout is at an untagged commit, not the pinned tag v0.1.0".
- **After the B7 fix, commit `b251ab7`:** every `DirtyCore` and `LinkedWorktree` test passed.
  - B11 was green on the first run in which it could be seen. Its leak test also passed from the first run: the recorded environment really does select the superproject when let through, and C12's `git_env` drops it. So B11 was fixed by C12 (napoleon J5, 2026-10-29), and no code change was needed for it.
  - Two `ShallowSubmodule` tests still failed: `test_missing_pinned_tag_is_version_only` ("the core checkout is at an untagged commit, not the pinned tag v0.1.0", napoleon J41's failure reproduced) and `test_full_clone_missing_the_pinned_tag_names_the_fix` (no fetch hint).
- **After the B12 fix, commit `2818fe4`:** all green. Commit `a2d3f22` then folded the three read-only shallow checks into one test (14 to 12 tests, same assertions) and built the fixtures once per class.
- **Full gates locally:** 13 ok and 1 warn; 349 host tests passed with 5 old skips (capstone, POSIX sh); 92.9 s.
- **CI run 41716611567** (`5b0c5b4`): all green on the first try, namely gates on ubuntu-latest and windows-latest, harness-windows and proxy. All new tests ran on both platforms; no new skips.

## The recorded hook environment
This was recorded on 2026-11-03 by the `LinkedWorktree` fixture: a real `pre-push` hook running `env`, on a push from a linked worktree of the throwaway superproject. It used git 2.55.0.windows.5 on Windows 11.
- `GIT_DIR=<superproject>/.git/worktrees/game-wt`: absolute, with forward slashes.
- `GIT_PREFIX=`: empty.
- `GIT_EXEC_PATH=C:/Program Files/Git/mingw64/libexec/git-core`.
- `GIT_CONFIG_PARAMETERS`: the test's own `-c` values plus `core.hooksPath`.
- `GIT_INDEX_FILE` and `GIT_WORK_TREE` were **not** set.
- `GIT_EDITOR=true` and `GIT_LFS_PATH` came from the calling environment, not from git.

On ubuntu-latest the same test asserts that `GIT_DIR` is present and passes, so Linux git exports it too. The values there were not printed.

## Version
0.17.1. Main holds 0.15.0, and the open job branches hold W7 0.16.0 and W14 0.17.0, so 0.17.1 is the next free number after the highest. Decision C21 is the next free number after C20, which main and every open branch hold. W8 pushed meanwhile at 0.15.0 / C20 and will need a number after these.

## The consumer's part (not here)
Nothing is required at the pin bump. After it, napoleon may drop its CI step that fetches the pinned tag (`ci/gates.yml.in` lines 63 to 66) and run `wsc ci render`. The pin then checks as "VERSION only" on CI's shallow submodule, as it did before 0.3.0; a pin bump that leaves the step in keeps checking the tag against HEAD, which is also green. Napoleon's `policy.yml` fetch of the pin commit is for its rule 79, not for `core_pin`, and stays. The next napoleon pin-bump job can pick this up.

## Deviations from the brief, and why
- **Model:** built on Opus by Liam's choice for this session; the brief's "Sonnet" line was left as is.
- **VERSION 0.17.1, not the next patch on 0.15.0:** W7 (0.16.0) and W14 (0.17.0) are open; per the brief's version-collision rule I took the next free number.
- **`pin_problems` has two more arguments than the brief lists:** `head_tags`, so the "at tag(s) …" message is kept, and `core_dir`, so the fix names the real submodule folder. There is also a small `pin_check` helper, so the gate's summary and the problems use one rule.
- **The pinned tag's commit is looked up only when the pin is exactly a name in `git tag --list`,** not with a bare `rev-parse refs/tags/<pin>`. On a case-insensitive filesystem a loose ref `V0.1.0` would probably resolve for `v0.1.0`, which would drop C10's "tags are case-sensitive". I reasoned this; I did not test it.
- **`core_version` gained an optional `root`** (`warscape/__init__.py`) instead of a second VERSION reader in the gate.
- **Shared fixtures:** the worktree and shallow fixtures are built once per class, to keep the Windows test time down (the file went from about 60 s to about 30 s).
- **Report and row:** this report was written by the orchestrating session from the builder's text (the builder could not write `jobs/W11/report.md`), and the row was set to `review` with it.

## Open questions
1. **Merge order and collisions:** W7 (0.16.0), W14 (0.17.0), W11 (0.17.1) and W8 (unnumbered) all bump `VERSION`. If W14 adds a decision row, it must take C22 or later. Whoever merges second re-checks both numbers after merging `main`.
2. **The accepted weakening:** in a shallow checkout without the pinned tag, HEAD's commit is not checked, so a wrong commit with a matching `VERSION` passes. The brief accepted this (its open question 1), and the gitlink, not the gate, decides what CI checks out.
3. **For later (old behaviour, out of scope):** if `core/` is not its own git checkout (a folder vendored inside the game repo), `git -C core tag --list` reads the game's tags. Worth a backlog line if anyone vendors the core.
