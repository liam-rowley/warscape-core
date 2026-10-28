# warscape-core: rules for every chat and agent

**The repo is the single source of truth.** If it isn't in the repo, the next chat can't see it and it doesn't exist.
The core is game-agnostic: no game paths, addresses or facts live here; those belong to a game repo's adapter.

## Before you start
1. `git pull`. Read `README.md`, `docs/DECISIONS.md` and, for consumers, `docs/CONSUMING.md`.
2. Look it up before you write it: `python3 wsc.py find <words>` searches every registry; the tools view is `registries/tools.md`.
3. Set the hook once per clone: `git config core.hooksPath .githooks`.

## While you work
- Work on a branch; commit and push after every meaningful step. `main` changes only by a merge Liam approves. Tags (`vX.Y.Z`)
  are cut only after that merge, and `VERSION` says the same number.
- **A learning becomes code first.** When something bites (a timing, a trap, a wrong default), fix it in the tool, its default,
  a schema rule, a guard or a gate so the next agent cannot hit it. Prose is the last resort, in the doc that owns the topic.
- **Reuse before you write.** Extend an existing verb or library module rather than adding a near-duplicate. A new capability is a
  `wsc` verb (`warscape/verbs/<name>.py`: `NAME`, `HELP`, `add_arguments`, `run`) unless there is a reason it cannot be.
- **Every tool has a header and a row.** In its first 40 lines: `purpose:`, `usage:`, `when:`, and `verb: <name>` or
  `not-a-verb: <reason>` (comment lines, or a Python docstring; format in `warscape/tools.py`). Then `python3 wsc.py reg add tools <path>`
  and commit the file, `registries/tools.jsonl` and `registries/tools.md` together. Library modules (`warscape/*.py`) and host
  tests are not tools (`wsc.toml` `[tools]`). Retire a tool with `wsc reg set tools <id> status=superseded:<new id>`.
- **Registries change through `wsc reg`** (or a JSONL edit followed by `wsc reg render`). Never edit a generated view.
- **"Verified" carries a date and a run id** (e.g. "verified 2026-10-28, run 20261028_a"); in registries use the structured
  fields (`verified: {date, run}`, `state` + `date` + `evidence`). The `verified_dates` gate fails an undated claim in a living doc.
- **Standard library only, Python 3.12.** A dependency needs a dated decision in `docs/DECISIONS.md` first (C3 names the fallback).
- **One owner per topic; keep docs short.** Living docs stay under 30 KB (`doc_size` gate); dated records are exempt. Link, don't copy.
- Windows-safe names only: no CON/PRN/AUX/NUL/COM1-9/LPT1-9, no `<>:"|?*\`, no trailing dot or space, no names differing only in case.
- **Run the gates before you push:** `python3 wsc.py gates` (full) or `--fast` (what the hook runs). Bypass the hook only with
  `git push --no-verify` and say why in the commit.
- **Game repos never patch the core in place** (their `core_pin` gate fails on local changes); a change for a game lands here
  first, with host tests, and ships in a tag.

## Usage (napoleon-remastered D15)
Sonnet medium by default; Opus only with a reason in the brief (reverse engineering, shaders, DLL, crashes, independent checks);
at most 2 agents at once; every job brief states a call budget and a kill criterion; waiting and polling belong to the harness, not
to an agent making repeated calls.
