# W12 report: Guards: commit-msg trailer hook, run-README references, stale moved paths, committed views beside a jobs registry

Written by the orchestrator from the builder subagent's hand-back (the harness refuses a subagent's write of a report file). The text is
the builder's own, apart from this note and two marked orchestrator notes. Branch `job/W12`, VERSION 0.24.0, decision C23 (proposed).

## What was built
Every guard below was shown failing before it was made to pass.

1. **B49: committed views beside a jobs registry.**
   - `warscape/jobq.py` gains `views_problems(config)`, called first in `jobq.check`. It fails when `jobs` is declared and
     `[views] commit` is true. The message reads "views are committed beside a jobs registry: set `[views] commit = false` in wsc.toml
     (C19), git rm the committed `<registries_dir>/*.md` views and git-ignore the views dir (`_scratch/registries`)".
   - `wsc jobs check` and the `jobs` gate both go through `jobq.check`, so there is one implementation.
   - `warscape/policy.py`: `settings()` now carries the registry view paths, and the brief-branch refusal appends "(a committed registry
     view: C19, set `[views] commit = false`)" to such a path. The rule itself is unchanged.
   - Tests that failed on the old code: the fixture game with `commit = true` (`tests/test_fixture_game.py` `Verbs`, through both
     `jobs check` and `gates --only jobs`), and `tests/test_policy.py` `CoreOwnConfig`, which expects the hint on `registries/jobs.md`
     and on no other file.
   - `tests/test_extends.py` `ExtendJobs` declared `core:jobs` with the default `commit = true` and failed under the new rule, so its
     toml now sets `[views] commit = false`.
2. **B10: `.githooks/commit-msg`.**
   - `warscape/trailer.py` has `message_problem(text, trailer)` and `message_trailers`.
     - Trailers are read with `git interpret-trailers --parse`, after stripping `#` comment lines and everything from the scissors
       line on.
     - The key is matched case-insensitively, and an empty value is refused.
     - The message names the fix: a `Claude-Session: <id>` trailer in the last paragraph, `git commit --trailer "Claude-Session: <id>"`,
       or `--no-verify` for a human commit.
   - `wsc policy --commit-msg <file>`: `--branch` is no longer required. The check exits 0 silently when `[policy] commit_msg_hook` is
     false or `session_trailer` is empty.
   - `[policy] commit_msg_hook = false` is in `DEFAULTS` and type-checked; the core's `wsc.toml` sets it to true.
   - The hook finds `wsc.py` and Python 3.12 the same way `pre-push` does, and skips merges via `MERGE_HEAD`. It is mode 100755 with LF
     endings and has a tools row (`githooks.commit-msg`); the `wsc.policy` row is refreshed.
   - Tests in `tests/test_trailer.py`:
     - Pure cases: last paragraph ok; J44's shape refused; a missing or empty value refused; editor comment lines; an empty trailer
       name.
     - An agreement test (the kill-criterion check): 11 messages committed with `--cleanup=verbatim`. The hook's verdict is compared
       with `%(trailers:key=Claude-Session,valueonly)`, and the two never disagree.
     - End-to-end `Hook` tests in a temp repo with `core.hooksPath` pointing at this `.githooks`:
       - `git commit -m x` fails and nothing is committed;
       - `--trailer "Claude-Session: t"` passes;
       - a `--no-ff` merge with git's own message passes;
       - no opt-in passes, and an empty trailer name passes;
       - `--no-verify` bypasses the hook.
     - These ran under Git for Windows `sh`, and are skipped only when no `sh` exists.
   - In use: once the hook existed in this worktree, a commit without the trailer ("W12 B10: no trailer") was refused with the hook's
     message (rc=1).
3. **B24: old-layout path lint.**
   - `NoOldLayoutPaths` in `tests/test_moved_tools.py` scans the tracked files of `proxy/`, `harness/`, `saves/` and `discovery/` for
     `(proxy|harness|saves|discovery)/core/`. `viewer/core/` is not matched.
   - `ALLOW` is keyed by (path, matched text) and holds (expected count, reason). A new match in an allowed file fails, and so does a
     stale entry once its strings are re-stamped.
   - Red first: on the pre-change files it failed at `harness/job.sh:5` and the other lines below.
   - Fixed:
     - the headers of `harness/job.sh:5`, `harness/ctl.py:7` and `:20`, `harness/acceptance.py:7`, `harness/shot.sh:3` and
       `saves/esf_{diff,dump,edit,map}.py:5`;
     - the `gen_tables.py` docstring (now line 288);
     - the null game's `config_keys.jsonl` row `dev.file_rules` and `nullgame.ini:25`. This was regenerated with
       `WSP_GAME_ROOT=proxy/tests/null_game python3 proxy/tools/gen_tables.py --adapter proxy/null`; `--check` is ok and only the ini
       line changed;
     - `discovery/shader_catalog.py:721`, an error message that no result contains.
   - The tools rows of the eight changed headers were re-added in the same commit.
   - Allowed, with reasons in the entries:
     - discovery generator and provenance strings (18 matches in 9 files, plus `discovery/README.md`; B55);
     - `gen_tables.py:297` (the string is written into `console_table.h`);
     - `proxy/src/camera.h:4`;
     - `proxy/tools/pc_deploy.py:80`;
     - `harness/watcher.ps1` (2 matches; the entry names W10).
4. **B13: the `run_refs` gate.**
   - `warscape/checks.py` has `run_readmes`, `run_folder_date`, `run_ref_tokens`, `run_ref_index`, `run_ref_found` and
     `run_ref_problems`. `warscape/gates.py` has `gate_run_refs`, registered in `GATES` and in the fast set.
   - A reference is found when any of these holds:
     - it exists from the root, or from the README's folder;
     - it is the tail of a tracked path;
     - it is in a submodule (`git ls-files --recurse-submodules`; paths inside a submodule are checked on disk);
     - `git check-ignore` says it is ignored.
   - An untracked file on disk counts as a miss, which is napoleon J2's case.
   - `[gates] run_refs_since` (default "") skips older run folders and counts them in the summary; a value that is not YYYY-MM-DD is a
     config error.
   - `tests/test_checks.py` `RunRefs` covers:
     - token shapes: URL, glob, drive letter, fenced block, a `..` range, a `:line` suffix;
     - root, README-relative and suffix matches;
     - the ignored case, grandfathering and line numbers.
   - `tests/test_cli.py` `RunRefsGate` runs the gate in a temp repo:
     - a committed file, a relative path, a suffix match, an ignored build path, a URL and a glob pass;
     - a missing log fails, naming the README and the line;
     - an untracked log that is present on disk fails;
     - an older run folder is skipped and counted;
     - a bad date key is a config error.
5. **Docs and release.**
   - `README.md` "Gates" lists `run_refs`.
   - `docs/CONSUMING.md` gains "Hooks and gate keys added in 0.24.0 (C23)", and the B49 sentence now names what refuses the
     combination.
   - `docs/DECISIONS.md` gains C23 (proposed).
   - `docs/BACKLOG.md` loses B10, B13, B24 and B49.
   - `VERSION` is 0.24.0.

## Gates
`python3 wsc.py gates` (full, on this PC): 14 ok, 1 warn, 0 failed.
- `run_refs`: no run READMEs.
- `tests`: 594 host tests passed and 5 skipped. The skips are existing ones: the pre-push hook test needs POSIX sh and symlinks, and
  four tests need capstone.

CI (ubuntu and windows) runs on the push of this branch. Orchestrator note: the run id is recorded in the pull request.

## Napoleon `run_refs` misses (read only)
The rule was run from a scratch script against napoleon-remastered at 5a76c0d; nothing was written there. Result: 42 run READMEs, 151
references, 11 misses, all in runs dated 2026-10-29 to 2026-11-02:
- `harness/runs/20261030_j43pc/README.md:24`: `harness/core/campose.py`
- `harness/runs/20261030_j44pc/README.md:51`: `tests/test_ctl.PcLaunch`. This is a test class, not a path: a false positive.
- `harness/runs/20261101_j8pc/README.md:50`: `harness/core/job.sh`
- `harness/runs/20261102_j46pc/README.md:9` and `:11`: `snapshots/j46_pre.json` and `snapshots/j46_post.json`, possibly a genuine
  miss.
- `proxy/runs/20261029_4kcrash/README.md:17` and `:18`: `core/crash.cpp` and `core/crashpolicy.h`
- `proxy/runs/20261029_j13pc/README.md:5` and `:6`: `harness/core/job.sh` and `harness/core/win_probe.ps1`
- `proxy/runs/20261030_j18pc/README.md:9`: `src/exe_identity.json`
- `upscale/runs/2026-10-31_j50/README.md:4`: `harness/core/ctl.py`

With `run_refs_since = "2026-11-03"`, 39 READMEs are skipped, 13 references are checked, and none is missing. That is well under the
kill criterion's 20.

## What napoleon must do after the tag
At the pin bump that picks up 0.24.0 (orchestrator note: napoleon pins v0.10.0 since J30, and J64 or J78 takes this tag):
- **(a)** The `run_refs` gate may fail on old run READMEs. Fix any README whose run is still open (for example the j46pc
  snapshots); otherwise set `[gates] run_refs_since` to the bump date in the same commit.
- **(b)** Opt into the commit-msg hook with `[policy] commit_msg_hook = true`. Napoleon's Claude Code hook can stay as a second line
  of defence.
- **(c)** Nothing for B49: napoleon already has `[views] commit = false`.

## Deviations from the brief, and why
- **VERSION 0.24.0.** `origin/job/W20` already holds 0.23.0; the orchestrator renumbers at merge.
- **C23.** That is the next free number on main. Re-check it after merging main.
- **More reference shapes than the brief lists:**
  - Markdown link targets with an extension but no `/` (for example `[raw](raw.log)`) are checked, because a sibling link is
    exactly a path that can go missing. Backticked tokens still need a `/`.
  - Fenced code blocks in run READMEs are skipped, since they hold commands and logs.
  - A token with a space, or with a leading `-` or `=`, is treated as a command-line fragment and excluded.
  - A `..` path segment is resolved against the README's folder. A `..` inside a segment (a range such as `chain1..3`) is skipped.
- **Moved line numbers.** The B24 targets drifted from the brief: the `gen_tables.py` docstring is now at 288 and the generated string
  at 297. `shader_catalog.py:721` was fixed rather than allowed, because it is an error message, not a committed result.
- **`ALLOW` carries an expected count**, which is stricter than "keyed by path and matched text".
- **`tests/test_extends.py` was edited**, although the brief's file list leaves it out (see B49 above).
- **Left alone:** `warscape/verbs/discovery.py:70` also writes a `discovery/core/` string into generated READMEs. It sits outside the
  four scanned trees, and B55 covers it.
- **Hook mode:** `.githooks/commit-msg` was first committed as 100644 (44d3f4b) and fixed to 100755 in 1dad1a0. Both commits stay in
  the history.

## Open questions
1. The opt-in key was taken as recommended. If a repo-wide hook still bites hand commits in a game, the rejected alternative stays
   open: enforce only when Claude Code's environment marker is set.
2. Should the `run_refs` token rule skip a token whose "extension" starts with an upper-case letter (the `PcLaunch` case)? Or should
   the pin-bump job fix that README instead?
3. Once B55 lands, should the moved-trees lint scan `warscape/` too?
4. After merging main, re-check the C number, the VERSION and the B24 `ALLOW` counts. W10 edits `watcher.ps1`, and W8, W11 and W20
   touch `VERSION`, `BACKLOG.md`, `DECISIONS.md`, `gates.py`, `test_moved_tools.py` and `ctl.py`.
