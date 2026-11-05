# Usage accounting in reports (core W31)

Off by default. A game switches it on with two `[jobs]` keys; nothing changes for a repo that sets neither. Code: `warscape/jobq.py`, section "usage accounting".

```toml
[jobs]
usage_from = 60                    # job numbers from this one on need the line (0 = off); older reports are exempt and never edited
usage_cmd = "python3 tools/usage_reader.py --job {id} --json"   # one command line; {id} is the job id
```

## The line
One line in `jobs/<id>/report.md`, after the first paragraph under the title, outside any code fence:

`Usage: <n> tool calls; models: <m1>, <m2>; <free text: sessions, cost estimate, source, date>`

`n` counts the job's **build and fix sessions**, not its reviews and not its brief. The command decides which sessions those are. Models are lower-case family names,
compared with the row's `model` by their first word, ignoring case.

## `wsc jobs check`, from `usage_from` on
For a row in `review`, `fix` or `done` with a report, each of these is an error:
- no line, two lines, or a line that does not parse;
- `n` above 1.25 x the effective budget: the `to` of the newest `budget_lifts` entry, else the brief's `Budget about <n> tool calls`;
- a model other than the row's: correct the line, or the row if the row was wrong;
- a `budget_lifts` entry whose `to` is not above its `from`, whose `from` is not the previous `to` (the brief's budget for the first), or with no `why`.

The reviewer clears an over-budget error with a lift or a corrected line. There is no warning level.

## `wsc jobs usage <id> [--write] [--from-json FILE]`
Prints the line from the game's command, or from `FILE` (the same JSON by hand; a repo with no command uses this route). `--write` replaces the `Usage:` line in the report, or
inserts one, and changes no other byte; it refuses a missing report or a report with two lines. Run it again after a fix round: the fix session counts too.

The command runs with the repo root as cwd, no shell, a 60 s limit. It prints one JSON object on stdout and exits 0:

```json
{"calls": 142, "models": ["opus"], "sessions": 2, "note": "about $3, usage_reader, 2026-11-04"}
```

`models` are family names from `[jobs] models`: a reader that keys by model id maps `claude-opus-5-5` to `opus`, or the command is refused.

Anything else (a non-zero exit, bad JSON, a missing key, a timeout, an empty `usage_cmd`) is exit 1 with the reason, and nothing is written. The core reads no transcript and no
`~/.claude` path: this command is the only seam. It must leave out sessions a row's model does not cover, such as a side request on a smaller model, or the model rule fires.

## `budget_lifts`
An optional row field, oldest entry first. The session that raises a budget adds the entry; the brief is never edited (the brief is the contract as written, the row is the history).

```
wsc reg set jobs J60 'budget_lifts:=[{"date": "2026-11-04", "from": 150, "to": 200, "why": "the scope grew: two more gates"}]'
```

`reg set` replaces the field, so a second lift passes the whole array.

## The `jobs view` cards
A card shows `usage 142 / 150 calls · opus` from the report's line and the effective budget, in red above 1.25 x. A report with no readable line shows nothing. The chip needs no game code.

A `view`-stage gate module adds its own card lines with `Result(..., cards={job id: value})`: a string is escaped text, `{'html': '...'}` is drawn as is (the rule of `Result.html`). An
unknown id or a malformed value is skipped and never fails the page.
