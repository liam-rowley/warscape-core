# warscape-core: rules for every chat and agent

**The repo is the single source of truth.** If it isn't in the repo, the next chat can't see it and it doesn't exist.
The core is game-agnostic: no game paths, addresses or facts live here; those belong to a game repo's adapter.

## Before you start
1. `git pull`. Read `README.md`, the decisions (`python3 wsc.py reg render decisions`, then `_scratch/registries/decisions.md`) and, for consumers, `docs/CONSUMING.md`.
2. Look it up before you write it: `python3 wsc.py find <words>` searches every registry; the tools view is `_scratch/registries/tools.md`
   (`python3 wsc.py reg render` writes it: views are not committed, C19).
3. Set the hook once per clone: `git config core.hooksPath .githooks` (the `hooks` gate warns until you do).

## Jobs (C18): the core runs the same queue a game does
- The queue is the `jobs` registry (`registries/jobs/W<n>.json`, one file per job) with a folder `jobs/<id>/` per job (`brief.md`, `report.md`,
  `review.md`); a job in progress is a remote branch `job/<id>`. `python3 wsc.py jobs next` names the next job (or the brief to write, on `brief/<id>`);
  `jobs review` and `jobs fix` name the branch to review or fix; `jobs view` shows the queue; `jobs check` runs in the `jobs` gate.
- The branch name decides what a pull request may change (`python3 wsc.py policy --branch <branch>`; the kinds are the docstring of `warscape/policy.py`),
  judged with the base's rules, never the branch's own (C24): `git fetch` first, and a change to the policy proves itself with host tests.
  Work Liam asks for that is not in the queue becomes a `needs_brief` row on a `plan/` branch first. A job is reviewed by a fresh session per round, which
  claims the round first and never edits an earlier one (`docs/REVIEW.md`; `policy` checks the rounds, W27);
  never mark your own job `done`, never review a job you built. Everything a game can configure is in `docs/CONSUMING.md`, "The job pipeline".

## While you work
- Work on a branch; commit and push after every meaningful step. `main` changes only through the job queue (below, C18): a `job/W<n>`
  branch is merged by its independent reviewer on green CI. Tags are made by the release workflow (C27); jobs state a `semver` level and no longer edit `VERSION` (from `[jobs] semver_from`), and `VERSION` says the
  same number (`core_pin` gate). Every commit carries a `Claude-Session: <session id>` trailer (the `policy` check reads it).
- **A learning becomes code first.** When something bites (a timing, a trap, a wrong default), fix it in the tool, its default,
  a schema rule, a guard or a gate so the next agent cannot hit it. Prose is the last resort, in the doc that owns the topic.
- **Reuse before you write.** Extend an existing verb or library module rather than adding a near-duplicate. A new capability is a
  `wsc` verb (`warscape/verbs/<name>.py`: `NAME`, `HELP`, `add_arguments`, `run`) unless there is a reason it cannot be.
- **Every tool has a header and a row.** In its first 40 lines: `purpose:`, `usage:`, `when:`, and `verb: <name>` or
  `not-a-verb: <reason>` (comment lines, or a Python docstring; format in `warscape/tools.py`). Then `python3 wsc.py reg add tools <path>`
  and commit the file and its `registries/tools/` row together. Library modules (`warscape/*.py`) and host
  tests are not tools (`wsc.toml` `[tools]`). Retire a tool with `wsc reg set tools <id> status=superseded:<new id>`; after a move,
  `wsc reg add tools <new path> --id <its id>` keeps its id.
- **A decision is a row file:** `python3 wsc.py reg add decisions --mint who=... decision=... reversible=yes|no` draws an id no other branch can take; a row never changes, and a reversal is a new row with `replaces` (W43). **An agreed change not yet built is a `later` job row**, found with `wsc find`, old `B<n>` numbers included, and picked up batched by area, not one job each.
- **Registries change through `wsc reg`** (or a JSONL edit followed by `wsc reg render`). Views are generated into the git-ignored
  `_scratch/registries/` and never committed (C19, `wsc.toml` `[views] commit = false`; the `registries` gate refuses a committed one): a `brief/` branch may change
  only its brief and its row, so a committed view of the jobs registry could never be current on it.
- **"Verified" carries a date and a run id** (e.g. "verified 2026-10-28, run 20261028_a"); in registries use the structured
  fields (`verified: {date, run}`, `state` + `date` + `evidence`). The `verified_dates` gate fails an undated claim in a living doc.
- **Standard library only, Python 3.12.** A dependency needs a dated decision row first (C3 names the fallback).
- **One owner per topic; keep docs short.** Living docs stay under 30 KB (`doc_size` gate); dated records are exempt. Link, don't copy.
- Windows-safe names only: the `windows_paths` gate (`warscape/checks.py`) is the rule.
- **Run the gates before you push:** `python3 wsc.py gates` (full) or `--fast` (what the hook runs). Bypass the hook only with
  `git push --no-verify` and say why in the commit.
- **Game repos never patch the core in place** (their `core_pin` gate fails on local changes); a change for a game lands here
  first, with host tests, and ships in a tag.

## Usage
The game repo's usage rules apply (napoleon-remastered `docs/DECISIONS.md` D15; its `CLAUDE.md` "Usage" owns the wording).
