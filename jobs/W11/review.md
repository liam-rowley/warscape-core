## Round 1 (2026-11-03, branch job/W11 at 5039021)

**Verdict: merge.**

Reviewed by a fresh session that did not build the branch. Machines: `wsc gates` 13 ok, 1 warn (tests: 349 passed, the 5 known skips); `tests/test_core_pin.py` 12 passed in 43 s locally; the CI run on 3d777f9 was still in progress when I started (the PR checks are the merge gate).

I merged `main` (0.16.0, W7) into the branch: `VERSION` conflicted and I kept 0.17.1; nothing else conflicted. C21 is still the next free decision number and W17 (0.18.0) is not merged, so 0.17.1 stays free.

### Claims against evidence
- B7: `gate_core_pin` reads `VERSION` through `core_version(ctx.core_root)`; `wsc --version` still reads the running core. Confirmed in the diff; the fixture tests use a fake core.
- B11: the report says C12's `git_env` already fixed it. `LinkedWorktree` builds a real submodule in a real linked worktree, records a real pre-push hook environment (`GIT_DIR` set; `GIT_INDEX_FILE` and `GIT_WORK_TREE` not), and has a leak test that passes the variable through. Passes here.
- B12: `pin_check` and `pin_problems` implement the brief's four rules exactly, as plain values; `ShallowSubmodule` reproduces the depth-1 failure and covers tag fetched, tag missing and not shallow. Passes here.
- Docs: C21 appended after C20 and names C10; README, CONSUMING and BACKLOG edited as the brief says; `core_pin` inside the core is unchanged ("this is the core (0.17.1)").
- The red-first claim (commits 66c9299, b251ab7, 2818fe4) is in the history and consistent with the report.

### Risk-first reading
I read `gate_core_pin` and `pin_problems` in full, because a wrong answer here either blocks every game's CI or lets a patched core through. The pinned-tag lookup only runs when the pin is exactly a name in `git tag --list`, which keeps C10's case-sensitivity. A missing `HEAD` gives `head=None` and a tag commit that is not None, so it reports an error rather than passing. The dirty-core check is independent of the tag logic. No git call lacks `env=git_env()`.

### Findings
- **blocker:** none.
- **should-fix:** none.
- **later:** (1) the report's own note: a vendored `core/` that is not its own git checkout reads the game's tags (old behaviour, out of scope). (2) The shallow weakening is accepted by the brief: a wrong commit with a matching `VERSION` passes on a shallow checkout without the pinned tag. (3) The case-insensitive-filesystem reasoning behind the exact-name lookup was not tested; harmless.
