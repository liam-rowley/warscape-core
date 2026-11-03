# W12: Guards: commit-msg trailer hook, run-README references, stale moved paths, committed views beside a jobs registry

Model: Sonnet, reason: none needed (Sonnet is the default). Four small guards in `warscape/`, `.githooks/` and the host tests; no DLL, no PC.
Budget about 100 tool calls (about 25 per guard); at the cap, stop, commit the guards that are green, and list in the report what is left.

## What
Backlog B10, B13, B24 and B49 (`docs/BACKLOG.md`). Each turns a rule that today lives in prose, or is found late, into a check that fails at once and
names the fix ("a learning becomes code first", `CLAUDE.md`). Build them in this order and commit after each; each is independent.

1. **B49: committed views beside a jobs registry.** C19: a repo with a `jobs` registry and `[views] commit = true` (the default in
   `warscape/repo.py` `DEFAULTS`) can never pass a brief branch: `policy` refuses the committed `registries/jobs.md` that `reg set` rewrites, and the
   `registries` gate refuses the branch without it. Today a repo finds out at its first brief.
   - `wsc jobs check` and the `jobs` gate (`warscape/gates.py` `gate_jobs`, `warscape/jobq.py`; make both paths report it, one implementation)
     fail when `jobs` is declared in `[registries]` and `[views] commit` is true, with: "views are committed beside a jobs registry: set `[views]
     commit = false` in wsc.toml (C19), git rm the committed `<registries_dir>/*.md` views and git-ignore the views dir".
   - `warscape/policy.py`, brief-branch refusal: when a refused path is a registry view (`<registries_dir>/<name>.md` for a declared registry), add
     "(a committed registry view: C19, set `[views] commit = false`)" to the message. Only the hint; the rule is unchanged.
   - Tests: `tests/test_jobs.py` (or `tests/test_fixture_game.py`, `BriefBranch`): the fixture game with `commit = true` fails `jobs check` naming C19;
     `tests/test_policy.py`: a brief branch that also changes `registries/jobs.md` gets the hint. Check every test repo that declares `core:jobs`
     still passes (today only `tests/fixture_game/wsc.toml`, which already sets `commit = false`).
2. **B10: `.githooks/commit-msg` refuses a commit without the session trailer.** Napoleon enforces `Claude-Session:` with a Claude Code hook that runs
   only when the session started in the repo folder, and with `policy` after the push; napoleon J44 put the line one paragraph above
   `Co-Authored-By:`, where git reads no trailer at all (`warscape/trailer.py` docstring). A git hook holds in every session and says so at commit time.
   - The rule as a function in `warscape/trailer.py` (beside `commit_lacks_trailer`): given the message text and the trailer name, the problem or
     None. Parse trailers with `git interpret-trailers --parse` (the same reading as the `%(trailers:key=...)` that `policy` uses), so the hook and the
     policy can never disagree; the value must be non-empty. The message names the fix: put `Claude-Session: <session id>` in the last paragraph,
     with `Co-Authored-By:`, or use `git commit --trailer "Claude-Session: <id>"`; a human commit bypasses once with `git commit --no-verify`.
   - Run it through the `policy` verb (`wsc policy --commit-msg <file>`; the verb already owns `[policy] session_trailer`), not a new verb.
   - The hook script `.githooks/commit-msg`: find `wsc.py` and Python 3.12 exactly as `.githooks/pre-push` does (repo root or `core/`), exit 0 when
     the repo has not opted in, and skip merge commits (`git rev-parse -q --verify MERGE_HEAD`: a "merge main" commit carries git's own message).
     A tool header (purpose, usage, when, not-a-verb) and a row: `python3 wsc.py reg add tools .githooks/commit-msg`. LF endings
     (`.gitattributes` already has `.githooks/* text eol=lf`).
   - Opt-in: a new `[policy]` key in `DEFAULTS` (see open question 1), off by default; the core's own `wsc.toml` turns it on. An empty
     `session_trailer` also switches the hook off.
   - Tests (`tests/test_trailer.py` and a hook case): pure cases of the function (trailer in the last paragraph ok; J44's shape, the line one
     paragraph above `Co-Authored-By:`, refused; empty value refused; trailing `#` comment lines as an editor leaves them; no opt-in passes), and one
     end-to-end case: a temp repo with `core.hooksPath` pointing at this `.githooks` and the opt-in set, where `git commit -m "x"` fails, `git commit
     -m "x" --trailer "Claude-Session: t"` passes, and a merge commit passes. Skip the end-to-end case with a reason where no `sh` can run the hook.
3. **B24: a lint for paths of the old layout in the moved trees.** `harness/job.sh` line 5 names `harness/core/watcher.ps1`; the J12 lint
   (`tests/test_moved_tools.py` `NoGameNames`) checks game names, not paths that no longer exist. Add a class beside it, over the same trees
   (`proxy/`, `harness/`, `saves/`, `discovery/`), that fails on `(proxy|harness|saves|discovery)/core/` (the trees that moved into the core and are
   gone from it; `viewer/core/` is still a consumer's folder and is not matched), with an allow list keyed by path and the matched text, each entry
   with its reason, and no blanket exemption. At `origin/main` `8640a3e` the matches are (re-run `git grep -nE
   '(proxy|harness|saves|discovery)/core/'` before you start):
   - **Fix** (comments, docstrings and `usage:` lines that point readers at a path that is gone): `harness/job.sh:5`, `harness/ctl.py:7` and `:20`,
     `harness/acceptance.py:7`, `harness/shot.sh:3`, `saves/esf_diff.py:5`, `saves/esf_dump.py:5`, `saves/esf_edit.py:5`, `saves/esf_map.py:5`,
     `proxy/tools/gen_tables.py:144` (the docstring only). A changed header line changes the tool's row: run `python3 wsc.py reg add tools <path>`
     for each and commit the rows with the files (the `tools` gate fails on drift).
   - **Allow, with the reason in the entry:** every `discovery/core/` string that is written into a committed result (the generator and
     provenance strings in `discovery/*.py`: changing them moves a game's committed bytes; B55 re-stamps them in a regeneration commit on the game);
     `proxy/tools/gen_tables.py:153` (written into the generated `console_table.h`, a DLL input of every game: changing it changes their build ids);
     `proxy/src/camera.h:4` (a DLL input: fix with the next DLL change); `proxy/tools/pc_deploy.py:80` (code that still supports the old layout on
     purpose); `harness/watcher.ps1:1` and `:3` (the watcher kit: fix with the next watcher change, W10, so its version and the consumer's rule-79
     streak move once); the null game's `nullgame.ini:25` and `config_keys.jsonl` row `dev.file_rules` (`proxy/core/filerules.h`: fix the row and
     regenerate with `gen_tables.py` if it is one command, else allow).
   - `discovery/README.md` documents the old-to-new paths on purpose: allow it by path with that reason.
   - Show the lint red on `main` first (it must fail on `harness/job.sh:5`), then green.
4. **B13: a gate that every repo path a run README names exists.** A run README cited a log that was never committed (napoleon J2 review S1). The
   core has no `runs/` folders, so the gate is for games; build it in `warscape/checks.py` (the rule) and `warscape/gates.py` (the gate, named
   `run_refs`, in the fast set: it reads files only).
   - Which files: tracked `**/runs/**/README.md`.
   - Which references: Markdown link targets and backticked tokens that look like a relative path (contain `/`, end in a file extension or `/`); not
     URLs, absolute or drive paths, `%VAR%`/`$VAR`/`~` paths, backslash paths, and nothing with `* ? < > { } |` or a `..` range (`raw/chain1..3/`).
     Strip a trailing `:<line>` and punctuation.
   - Found when any of these holds: the path from the repo root; from the README's folder; any tracked file or folder whose path ends with `/<token>`
     (a run README often writes `probes/x.lua` for a file under the adapter); a file inside a submodule (`git ls-files --recurse-submodules`, so a
     game's `core/harness/ctl.py` counts); or `git check-ignore` says the path is ignored (build output named on purpose; `check-ignore` refuses a path
     inside a submodule, so resolve those on disk first).
   - Grandfathering: run READMEs are dated records and their old paths are not wrong, only old. A new `[gates]` key (see open question 2) names a
     date; run folders whose name starts with an earlier date (`YYYYMMDD_` or `YYYY-MM-DD_`) are skipped and counted in the summary.
   - Sizing, measured on napoleon `main` `562dde6` with a prototype of these rules: 39 run READMEs, 142 path-shaped tokens, about 13 not found after the
     rules above, all in folders dated 2026-10-28 to 2026-11-02 (moved paths such as `harness/core/job.sh`, `registries/engine_facts.jsonl` from
     before per-row storage, and `snapshots/j46_pre.json` and `j46_post.json` in `harness/runs/20261102_j46pc`, which may be the kind of miss this gate exists for).
   - Tests in `tests/test_checks.py` (rule) and `tests/test_cli.py` (gate): a temp repo with a run README naming a committed file (ok), a missing log
     (error naming README and line), a path relative to the README, a suffix match, an ignored build path, a URL and a glob (not checked), and a
     folder dated before the grandfather date (skipped).
5. **Docs and release.** `README.md` "Gates" lists `run_refs`; `docs/CONSUMING.md`: the commit-msg hook and its opt-in key, the `run_refs` gate and
   its date key, and the sentence "Nothing refuses the combination yet (B49)" in "The job pipeline" becomes what refuses it now. A decision row in
   `docs/DECISIONS.md` (append only; the next free `C<n>`, "proposed (Claude, core W12)") for the commit-msg hook, as C6 is for the pre-push hook:
   what it refuses, the opt-in, merges exempt, `--no-verify` for a human commit. Remove B10, B13, B24 and B49 from `docs/BACKLOG.md`. `VERSION`: the
   next free minor (a new gate, a new hook and new `wsc.toml` keys; `main` holds 0.15.0 when this was written).

Files this job touches: `warscape/jobq.py`, `warscape/gates.py`, `warscape/checks.py`, `warscape/policy.py`, `warscape/verbs/policy.py`,
`warscape/trailer.py`, `warscape/repo.py` (`DEFAULTS`), `.githooks/commit-msg` (new), `registries/tools.jsonl`, `wsc.toml`, the header lines listed in
item 3 (`harness/job.sh`, `harness/ctl.py`, `harness/acceptance.py`, `harness/shot.sh`, `saves/esf_*.py`, `proxy/tools/gen_tables.py`, maybe the
null game's `config_keys.jsonl` and `nullgame.ini`), `tests/test_moved_tools.py`, `tests/test_jobs.py`, `tests/test_policy.py`, `tests/test_trailer.py`,
`tests/test_checks.py`, `tests/test_cli.py`, `README.md`, `docs/CONSUMING.md`, `docs/DECISIONS.md`, `docs/BACKLOG.md`, `VERSION`. Not touched:
`proxy/src/**` and `proxy/tools/build.sh` (DLL inputs), `harness/watcher.ps1` (W10). Branch `job/W12`.

## Acceptance
- `python3 wsc.py gates` green locally and in CI on `ubuntu-latest` and `windows-latest`; each guard shown failing on a fixture before it passes
  (one line each in the report).
- This job's own commits are made with the new hook wired in the worktree (`git config core.hooksPath .githooks`) once item 2 is in: say so in the
  report, and that a commit without the trailer was refused.
- Run the `run_refs` rule once against a local napoleon-remastered clone (read only: a scratch script or `--root`, nothing written there) and put the
  list of misses in the report, so the pin-bump job knows what it will meet.

## The consumer's part (not here)
At the game's pin bump: (a) the `run_refs` gate may fail on old run READMEs: fix a README whose run is still open, otherwise set the grandfather date
key to the bump date in the same commit; (b) opt into the commit-msg hook with the new `[policy]` key (napoleon's `.claude/settings.json` hook can
stay as a second line); (c) nothing for B49 (napoleon already has `[views] commit = false`). Napoleon pins v0.9.0 today, so this lands with whichever
bump picks up this tag. Say this in the report.

## Open questions (recommendation for each)
1. **The commit-msg opt-in key.** Recommended: `[policy] commit_msg_hook = false` in `DEFAULTS`, `true` in the core's `wsc.toml`, beside
   `session_trailer`, which names the trailer it checks. A hook that enforces with no opt-in would refuse Liam's own hand commits in any repo that
   wires `core/.githooks`. Alternative: enforce only when Claude Code's environment marker is set (agents only); rejected as the default because it
   ties a git hook to one client's variable, but mention it in the report if the opt-in proves awkward.
2. **Run-README grandfathering.** Recommended: `[gates] run_refs_since = ""` (empty: every run README is checked) and a game sets the date at its pin
   bump; the core has no runs, so nothing changes here. Alternative: check only READMEs changed against the merge base, which needs `origin/main`
   and makes a deterministic gate depend on the branch; rejected.
3. **B24 as a host test, not a gate.** Recommended: a test class beside `NoGameNames`, because the moved trees are the core's own and no game needs
   the rule; the old-layout names are a fixed list.
4. **File overlap with W8 and W11** (likely built one after another; base on the latest `main`, merge `main` in, never rebase):
   - W8 edits `harness/ctl.py` (`bash()` and its docstring) and `tests/test_moved_tools.py` (its `git_bash()` helper and the `NoGameNames` file
     list); this job edits `ctl.py` header lines 7 and 20 (so its tools row too) and adds a class to `test_moved_tools.py`. Separate hunks; whoever
     merges second resolves them by hand.
   - W11 edits `warscape/gates.py` (`gate_core_pin`, `pin_problems`), appends a decision row, and edits `README.md` "Gates" and `docs/CONSUMING.md`;
     this job adds `run_refs` to `gates.py` `GATES`, keys to `repo.py` `DEFAULTS` and another decision row. Take the next free `C<n>` when you commit
     and re-check after merging `main`.
   - W10 (not briefed yet) changes `harness/job.sh` (the lock) and `harness/watcher.ps1`; this job changes only `job.sh` line 5 and leaves the
     watcher's two lines to W10 (allow entries that name W10).
   - All three edit `VERSION` and `docs/BACKLOG.md`.

## Kill criteria
- `git interpret-trailers --parse` and the policy's `%(trailers)` reading disagree on any test message: stop item 2 and report the message; never
  ship a hook that accepts what the policy refuses or the reverse.
- The commit-msg hook cannot run under Git for Windows' `sh` with the same Python finder as `pre-push` after about 10 calls: stop item 2, report.
- The `run_refs` rule finds more than about 20 misses in napoleon's READMEs dated on or after 2026-11-03 (after grandfathering), or flags tokens that
  are not paths: tighten the token rule once; if it still misfires, ship the rule as a `warn` and report.
- A B24 fix would touch a DLL input, a generated file or a committed result: allow it instead, with the reason.
- CI red after three fix attempts for a cause in this change: stop and report.
- Version collision: W8 and W11 also bump `VERSION`. Re-read `origin/main` `VERSION` and the open `job/*` branches before the last commit; the
  second to merge takes the next free number and merges `main`. Say in the report which number you took.

## Finish
Report in `jobs/W12/report.md` (each guard: the fixture that failed, the fix, the tests; the napoleon `run_refs` misses; deviations; open
questions), then `wsc reg set jobs W12 status=review report=jobs/W12/report.md` (`python3 wsc.py`). Liam tags the core after the merge; stop after the PR.
