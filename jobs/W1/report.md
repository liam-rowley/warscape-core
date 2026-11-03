# W1 report: Triage the core backlog into queue rows

The triage is `jobs/W1/triage.md`. It has one line per open backlog item in backlog order, read on main at e047ba0 (VERSION 0.13.0). A second table
holds the rows on open PRs, to re-check after they merge:
- #28 (`job/W4`): B54 to B56;
- #30 (`plan/backlog-numeric-keys-nile-flake`): B59 and B60.

No code, no registry rows, no BACKLOG edit.

## Counts
- **Items triaged:** 55. Of these, 50 are on main (B1 to B58, with gaps) and 5 are on open PRs. A script check confirmed that every backlog id on
  main appears exactly once.
- **Rows proposed:** 15 (P1 to P15), covering 41 items. This is exactly the brief's cap; grouping got there, not stopping early.
- **Merged:** 1. B31 goes into B26: the same `build_info` kit-id fallback, found twice.
- **Backlog notes:** 13.
  - On main: B4, B9, B14, B36, B37, B38, B42, B44, B50 and B57.
  - On open PRs: B54, B55 and B56.

## Dependency order
P1 comes first because napoleon J27 is blocked on B59 and P1 depends on nothing. P2 (host tests) comes before the harness rows that change those tools.
- **P1** (B41, B59): engine-site `value_offset`, and numeric patch values from config keys.
- **P2** (B17, B18): the moved tools' host tests in the core, and a Git Bash finder in the core.
- **P3** (B26 + B31, B51, B60): the build id read after launch, staged saves, and the hist_nile relaunch retry. Needs a PC. Depends on P2.
- **P4** (B20, B21, B27, B30, B39): race fixes in the watcher and `pc_deploy`. Depends on P2 and W5, which both change `watcher.ps1`.
- **P5** (B7, B11, B12): `core_pin` made testable, safe in a worktree and safe in a shallow clone.
- **P6** (B10, B13, B24, B49): guards. A commit-msg trailer hook, run-README references, stale moved paths, and committed views beside a jobs registry.
- **P7** (B1, B46): game-specific gates, then the five hook names as gate modules. Opus.
- **P8** (B2, B3): core schemas with `x-extends`, and hotkeys that ignore which modifier is held.
- **P9** (B6, B28, B43): `reg remove`, stamping `last_used`, and exe words in `find`. Depends on W4, which brings `exe_strings.py`.
- **P10** (B15, B16, B52): the null game builds and tests on its own. Depends on W2.
- **P11** (B25, B40): stale ctl requests dropped, and a read-only peek.
- **P12** (B19, B22, B23): the headless display guard. Needs a PC.
- **P13** (B32, B33, B34): the capture timeout, capture on the render thread only, and state blocks. Opus.
- **P14** (B53, B58): hardening of the UI host and the gesture driver. Depends on W2 and W6.
- **P15** (B45, B47): savings in the core's CI, and a `ci check-settings` verb.

Every row is phase 1 and `needs_brief` when it is added. Only P3 and P12 need a PC.

## Judgement calls to check
- **B50 is a note, not a row.** `card_extra` would be a sixth hook name, and C18 and `CONSUMING.md` cap the hook module at five. Someone has to
  decide what carries it: B46's gate modules, an amendment to C18, or `view_panel`. This applies the brief's kill criterion "a row needs a design
  decision the line lacks".
- **B42 and B36 are notes for the same reason.** B42 needs the rules for loose-file ownership, uninstall and Steam Verify. B36 needs the backend
  interface, and it has no DX11 consumer.
- **B37, B38, B54, B56 and B14 wait on a second game:** Shogun 2 or Empire on the core, a second UI atlas or a second reference repo. Liam agreed B37
  and B38 in a planning chat, so he may want them queued anyway.
- **B55 is a note:** it is a regeneration commit in napoleon's repo, with nothing to build in the core.
- **B9 is a note** because its own line says it is low value. **B44 is a note** because nothing consumes it yet.
- **Grouping was pushed to fit 15 rows.** P4 (5 items) and P6 (4 items) are the widest.
  - P6 mixes a git hook, two lints and a `jobs check` rule under one theme: a learning becomes a guard.
  - P4 could split into a watcher row and a `pc_deploy` row if a brief writer finds it too big.
- **B59 and B60 sit in rows that start from items on main.**
  - B59 is in P1 with B41: they touch the same files, and B59's line says they can be combined.
  - B60 is in P3 with B26 and B51: the same `ctl.py` scene path. That is why P3 needs a PC.
  - If PR #30 changes in review, re-check both.
- **P3 and P4 depend on P2 (host tests first).** That puts the B60 flake fix behind a test port. Drop the edge if the flake costs more than the order
  is worth.
- **P4 depends on W5 only to avoid a conflict in `watcher.ps1`.** It is not a functional dependency.
- **`needs_pc` is false for P4 and P13.** That assumes the `harness-windows` host tests and a stand-in device can cover them; the consumer proves them
  in game.
- **Only two rows use Opus.** P7 adds a new extension point and migrates a live hook. P13 changes threading and adds new vtable hooks in the D3D9
  detours.

## Deviations
- The brief predates B50 to B58 on main and the rows on open PRs. All of them are triaged; the open-PR rows are in a separate table, "Rows on open PRs
  (re-check after they merge)".
- The brief names Sonnet. The triage was done by an Opus subagent of the orchestrator's chat, because Liam asked on 2026-11-03 for Opus at high effort
  across the board.
- The orchestrator wrote this report from the subagent's hand-back, because the harness refuses a subagent's write of `report.md`. The orchestrator
  also set row W1 and pushed. The subagent committed only `triage.md`, locally (68b4aa0). The Claude-Session is the same.

## Open questions
- B50: a sixth hook name, or wait for B46?
- B37 and B38 (the Shogun 2 formats): queue them now on the planning chat's word, or wait for a Shogun 2 consumer?
- B57: may the host hook in with `ui.enabled=0`? This is Liam's call, or the consumer's. It decides whether a later row relaxes W2's lint.
- Should phase carry priority? Every row is phase 1 because the queue has no later phase defined.
