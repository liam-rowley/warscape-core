# Proposals: from a finding to an applied change

The one owner of the row, its states and the answer round (W45, C41). Code: `warscape/proposals.py`; who may write what: `warscape/policy.py`; the verb's flags: `warscape/verbs/proposals.py`;
the fields: `schemas/proposals.schema.json`. What is measured is [AUDIT_METRICS.md](AUDIT_METRICS.md).

## The round
1. `wsc audit --record` writes the findings. `wsc proposals close` applies what that record re-measured, then `wsc proposals draft` writes a skeleton per finding with no live row. A person or a session fills each: a question, options, a `recommended`, a `tag` if it must always be asked. `wsc proposals check` refuses a skeleton, so an unfilled row cannot merge.
2. `wsc proposals answer --auto` accepts the rows of `[audit] auto_apply` at their recommendation. This all goes on a `plan/` branch, which merges itself.
3. `wsc proposals ask` prints the table; `jobs view` shows the same rows under "Waiting on" the owner. The owner answers in one message.
4. On `decide/<date>`: put the message in a file, the answers in `{"<id>": "<option key>"}` (`"recommended"` is allowed; rows not named stay open), and run `wsc proposals answer --answers FILE --quote FILE`. It writes the rows, one decision row for the round, a `needs_brief` job row per job option and `<[audit] dir>/ANSWERS_<date>.md`. It commits nothing. **Only the owner merges a `decide/` branch**: never queue auto-merge on one.
5. Job rows go through the queue. The next audit re-measures each applied row, and step 1's `close` closes it or re-raises it.

## The states
| Status | How it gets there | What it does |
| --- | --- | --- |
| `open` | `draft` | is asked |
| `accepted` | a `decision` or `job` option | "applied" once the decision exists or the job row is `done`, computed, never stored |
| `declined` | a `none` option | suppresses its finding inside the margin |
| `deferred` | a `defer` option | the same |
| `closed` | `close`, with an `outcome` | stays closed |

A `closed` row has `outcome` `moved`, `not_moved` or `gone`. `not_moved` also drafts a new row with `reraises`, the delta in its question. A finding that comes back past a decline gets a new row with `reraises` from `draft`.

## Why the id is minted
`P<yymmdd>-<4 hex>`, as decisions are (W43): a finding id holds `:` and `/`, which no file name may, and two branches need not agree on a number. `finding` is a field; `class` is the finding's rule, the word `[audit] auto_apply` lists.

## Who may write what
Judged with the base's rules, on every branch kind (`warscape/policy.py` docstring): only `decide/` writes an answer. `plan/` may add and fill open rows, close an answered row, close an open row as `gone`, and accept a row the base's `auto_apply` lists, untagged, at its recommendation. On an existing row it may add a `tag`, but not change or remove one, nor change `class`: those two decide what is auto-accepted. No other kind touches a row. An answered row keeps its content, and no row is deleted. An `ANSWERS_` file changes only on `decide/`, because it quotes the owner.

## Re-measuring and suppression
Both are read from the rows at the measured sha, and are in the record as `suppressed` and `remeasured` ([AUDIT_METRICS.md](AUDIT_METRICS.md), "The record"). Worse is `sign * (value - baseline) > reraise_margin * abs(baseline)`; on a baseline of 0, any worsening. A `remeasured` verdict is `unmeasured` (the metric is not in the record: never read as fixed), `too_soon` (the window starts before the change, so it still holds the old state), `gone` (the subject left main), `moved` (no finding, or better by the margin) or `not_moved`.

## Traps
- Until W117 lands, a drafted `idle_queue` on a quiet main may be false: a fresh claim reads as parked. Look at the queue before filling it.
- A `decide/` branch is judged by its name: a second round on one day is `decide/<date>-2`, and its record is `ANSWERS_<date>_2.md`.
- Nothing can tell the owner's merge from an agent's: the agents push with the same account. The rule is that no tool and no session queues the merge, as with `meta/`.

## What a game declares
`proposals = "core:proposals"` in `[registries]`, `"proposals"` in `[storage] dir`, `registries/proposals/*` in `[policy] plan` and in any list of paperwork paths, a `[jobs.text] owner`, and `[policy] decisions = "registry:<name>"`. Without the registry none of this runs, and `decide/` is refused.
