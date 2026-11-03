# W4: discovery/core in the core (napoleon J64's core half)

Model: Sonnet, reason: none needed (Sonnet is the default). A pure move of Python, Markdown and JSON with no DLL work and no game launch; the
consumer's J64 brief is Sonnet, medium. Budget about 200 tool calls for the core part (napoleon-remastered J64 has about 320 in all; the
remainder, the baseline, the parameterising and the pin switch, runs there and not here).

## What
The game-agnostic half of napoleon-remastered J64 (its brief, `jobs/J64/brief.md` on that repo's `main`, is the full specification: read "Target facts",
"Decisions already made" and "Deliverables" 2 and 3 first). `discovery/core/` moves into this repo as `discovery/` and comes back as the next minor.
- The modules, flat, in `discovery/` (31 of them, about 7,250 lines), with their tools-registry ids kept (`wsc reg add tools <new path> --id <old id>`:
  `discovery.core.*`, `wsc.discovery`, `proxy.tools.exe_info`). Host tests in `discovery/tests/`; add the folder to `wsc.toml` `[tests] dirs`;
  the capstone tests keep their skip; a short `discovery/README.md`.
- The verb `discovery` as a core verb (`warscape/verbs/discovery.py`), driven by a new `[discovery] adapter` table (`warscape/repo.py` `DEFAULTS`, with a
  test that an unknown key is still refused and the new one accepted) and `layout.py` `discovery_adapter()`. No module finds the game by its own
  location; `--games` and `--out` still override.
- `exe_info.py` to `proxy/tools/exe_info.py` (`exe.py` depends on its PE helpers); its two game defaults (`--identity`, `--def`) come from `layout.py`.
- The game-name lint (`tests/test_moved_tools.py` `NoGameNames`) extended over `discovery/`. Game names become adapter parameters: `games.json` carries
  `target` and `reference`; Napoleon's rules (`STATIC_ONLY` reasons, art rules, the probe-safe naming rule, the `console_cmds` profile) become adapter
  JSON the tool reads. A module that cannot be made name-free gets a named, reasoned allowlist entry in the test plus a backlog row, never a blanket exemption.
- Optional extras (Pillow for `sheets`; capstone and pefile in the RE environment): checked before first use with a message naming the fix, no gate or
  host test imports them without a skip. Pins move with the code (`discovery/requirements.txt`, `re_env.py`). Propose a `C<n>` line in
  `docs/DECISIONS.md` (Liam's merge accepts it) and add a `docs/CONSUMING.md` section "Discovery (optional extras)" (adapter files a game provides,
  the extras, the re-run steps). Core CI covers `discovery/tests/` on Linux and Windows. Backlog rows for anything left.
- `VERSION`: the next free minor when this is built (see the kill criteria).

## The consumer's part (not here)
The byte-for-byte proof (every committed discovery output unchanged), the baseline `before.sha256`, the game-side adapter files, the pin bump, the
deletion of `discovery/core/` and the repointed importers all run under napoleon-remastered J64 on `job/J64`, after Liam tags this. The core's own
tests must be green on null-game fixtures; no result is regenerated here. The branch is `job/W4` (the core's policy refuses a free-named branch).

## Kill criteria
- A module cannot be made game-agnostic without changing a result (an output byte differs on a fixture taken from the consumer's committed outputs
  after two attempts): stop on that module, use the named allowlist entry, report it; do not widen the lint exemption.
- Making one module name-free costs more than about 40 calls: same allowlist fallback.
- The core needs a design change beyond a `[discovery]` table and `layout.py` function (for example B1, game gates): stop before the tag and report
  the proposal.
- Core CI is red after three fix attempts for a cause in the move: stop and report.
- Version collision: W2 claims 0.10.0, W3 takes the next patch (0.9.1 or 0.10.1), W5 also wants a minor. Re-read `origin/main` `VERSION` and the open
  `job/*` branches before the last commit; the second to merge takes the next free number and merges `main`. Say in the report which number you took.

## Finish
Report in `jobs/W4/report.md` (what moved, as a table of old path and core path; the `C<n>` number; the lint and any allowlist entry; deviations;
open questions), then `wsc reg set jobs W4 status=review report=jobs/W4/report.md` (`python3 wsc.py`). Liam merges and tags the core; stop after the PR.
