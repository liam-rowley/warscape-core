# W45: Proposals registry, the answer round and the decide/ branch kind

Phase 1 (the pipeline). C41: "The pipeline audits itself; Liam answers, the queue applies." W44 built the measuring half: `wsc audit` writes
findings with stable ids. This job builds the half between a finding and a change: a proposal with options and a recommendation, one
question table, one message from Liam, and a `decide/` branch that applies his answers and that only he merges. The point of the branch kind
is that the approval stays his although `plan/` now merges itself (C40), so the rule that matters most here is the one that stops any other
branch writing an answer.

Model: Opus, reason: a policy rule that guards the owner's approval, and the state machine every later proposal, W47's audit session and W32 rest on (builds run on Opus).
Budget about 150 tool calls: about 15 reading, 30 for fixtures and red tests, 65 to build the registry, the verbs and the policy kind, 15 for the audit changes and the dry run, 25 for docs, gates and the report. Comparables: W44 (130, build 120), W43 (125, Usage 115), W31 (150, Usage 136).
Semver: minor
No DLL or harness input changes: a schema, a library module, a verb, `warscape/policy.py`, `warscape/audit.py`, `jobs view`, `wsc.toml`, tests and docs. A game's pin bump to this tag carries no acceptance run for it (napoleon rule 79, J58). No workflow file changes.
Subagents: none.

## Start
1. `git pull`; `python3 wsc.py jobs next --id W45` and follow its mechanics. If this session's model is not Opus, stop and say so.
2. `python3 wsc.py gates --fast` for a baseline; `python3 wsc.py find proposal` and `python3 wsc.py find decide` (reuse before you write).
3. Read C40 and C41 (`registries/decisions/`), the rows of W47 and W32 (they consume this job's verbs and schema), `jobs/W44/report.md` from
   "Deviations" on, and `docs/AUDIT_METRICS.md`.

## Target facts (check each again before relying on it)
- Reuse: `warscape/registry.py` `mint_id` and one-file-per-row storage (`[storage] dir`), and the `--mint` path in `warscape/verbs/reg.py`, which today refuses every
  registry but the decisions one; `warscape/audit.py` `record`, `finding`, `record_path`, `render_md`, `subject_kind`, `doc_caps`; `warscape/jobq.py` `LANES`, `lane`, `rows_at`
  callers, `remote_heads`; `warscape/policy.py` `settings`, `run_check` and its per-kind branches; `warscape/policy_base.py` (the judge).
- **A finding id cannot be a file name:** ids like `hot_file:docs/CONSUMING.md` hold `:` and `/` (`windows_paths` gate). The row's id is minted; `finding` is a field.
- **W44 has no re-measuring.** The row says `close` "applies W44's re-measure findings", but `record()` writes no such thing: this job adds it (decision 6).
- **`skipped` and `failed` matter:** a metric not measured leaves no finding, and its absence must never read as fixed. `--only` lists the unselected metrics in `skipped` for this reason (W44 deviation 3).
- `details.gone` in `hot_files` and `conflict_files` lists paths no longer at main that would have fired.
- A finding's `value` is a number, and `direction` is `above` or `below` (read every `finding(` call to confirm).
- `job/<id>` may change any file but only its own jobs row (`warscape/policy.py` docstring), so proposal rows are open to it until decision 5. `plan/` and `meta/` are limited by globs; `registries/*` in `meta` does not reach `registries/proposals/<file>`.
- A pull request is judged with its base's rules (C24): `settings()` is what reaches the child. New settings go through it as optional values; a new argument to the child means `JUDGE_API` reasoning (`warscape/policy.py` docstring).
- `audit_problem` in `warscape/repo.py` type-checks every `[audit]` key from its default.
- `CORE_VERBS` in `warscape/cli.py` has an order a test reads (`test_core_verbs_read_as_text` failed W44's CI). Adding a module under `warscape/verbs/` floors the release at minor.
- `docs/CONSUMING.md` sits at the `doc_size` cap: anything added is paid for with a cut.
- The Windows `tests` gate has a time limit (`[tests] timeout_s`), and W44 pushed past the old one. Use W44's cheap fixtures (`tests/test_audit.py`: no template on `git init`, refs mirrored, not pushed) and report what your tests add to the run.
- This session's guard may refuse compound shell commands: one git or python call per command (W42's budget lift).

## Decisions already made for this job
1. **The row** (`schemas/proposals.schema.json`, `core:proposals`, in `[storage] dir`, one file per row). Id `P<yymmdd>-<4 hex>` from `mint_id`, so two branches need not agree on a number; `--mint` is
   widened to this registry. Fields: `id`, `date`, `kind` (`finding` or `question`; this job drafts only `finding`, `question` is W32's and needs no `finding` or `baseline`), `finding`, `metric`,
   `class` (draft sets the finding's rule, so `[audit] auto_apply` names rules), `question` (one sentence), `baseline` (`{record, value, threshold, direction, severity, evidence}`), `options`
   (list of `{key, kind, summary, recipe}`; `kind` is `decision`, `job`, `defer` or `none`; `decision` needs `{decision, reversible}` in `recipe`, `job` needs `{title, description, phase, model, needs_pc, semver, depends_on}`,
   the other two none), `recommended` (an option key), `tag` (optional: `taste`, `risk`, `legal`), `status` (`open`, `accepted`, `declined`, `deferred`, `closed`), `answer`
   (`{by, date, record, option}`), `decision` and `job` (the ids an answer made), `outcome` (`moved`, `not_moved`, `gone`), `reraises` (the proposal id this one follows).
   "Applied" is computed, never stored: `accepted` and either a `decision` option or its `job` row is `done`. A stored status would go stale.
2. **The verb:** `wsc proposals draft|check|ask|answer|close`, in `warscape/proposals.py` and `warscape/verbs/proposals.py`.
   - `draft [--record PATH]`: a skeleton per finding of the newest committed record in `[audit] dir` that has no live proposal (live: `open`, `accepted`, or suppressed by decision 6), with its baseline. Options stay empty for a session to fill.
   - `check`: in the `jobs` gate, called from `gate_jobs`. Refuses an `open` row without options or a `recommended` that is one of them, a bad recipe, two live rows on one finding, an answered row whose `answer.record`, `decision` or `job` does not exist. A skeleton therefore fails the gate until filled, on purpose.
   - `ask [--max N]`: the Markdown question table, open rows only, severity then id, `--max` from `[audit] max_questions` (8): id, question, options, recommended, tag. It says how many were left out.
   - `answer --answers FILE --quote FILE [--date D]`: `--answers` is JSON, `{"<id>": "<option key>"}`, with `"recommended"` as a value; `--quote` is Liam's message, verbatim. Refuses unless the checkout is on `decide/<date>`. Writes statuses and `answer`, one minted decision row (`who` = `[jobs.text] owner`) naming every accepted proposal when any was accepted with a `decision` or `job` option, a `needs_brief` job row per `job` option (next id as the rows on main and the open `plan/` and `brief/` branches allow), and `<[audit] dir>/ANSWERS_<date>.md` quoting the message and listing each answer. An option of kind `defer` sets `deferred`, `none` sets `declined`. Rows not named stay `open`. It commits nothing, and prints the push and the pull request **without** `gh pr merge --auto`.
   - `answer --auto`: on a `plan/` branch, accepts each `open` row whose class is in `[audit] auto_apply` and which has no `tag`, at its recommendation, `answer.by` = `auto_apply`, `answer.record` = the baseline's record. W47's session calls it after filling.
   - `close [--record PATH]`: applies the record's `remeasured` list (decision 6): `moved` and `gone` close the row; `not_moved` closes it and drafts a new row with `reraises`, the delta in its question; `too_soon` and `unmeasured` leave it. An `open` row whose finding is gone from a measured metric closes as `gone`.
3. **Config:** `[audit] auto_apply` (`[]`), `reraise_margin` (0.25), `max_questions` (8), each commented in `DEFAULTS` and read by `audit_problem`. The core's `wsc.toml` declares the registry, adds it to `[storage] dir`, adds `registries/proposals/*` to `[policy] plan` and to `plan_summary`; `DEFAULTS['policy']['plan']` gains it too. `auto_apply` stays empty (C41: a `wsc.toml` change, so a `meta/` branch).
4. **The branch kind:** `decide/<YYYY-MM-DD>`, or `decide/<YYYY-MM-DD>-<n>` for a second round that day. It may change only: proposal rows, added decision rows, added job rows with status `needs_brief`, and one added `<[audit] dir>/ANSWERS_<date>.md`. Each proposal it moves to an answered status has `answer.by` equal to `[jobs.text] owner`, `answer.record` equal to that file, its id in that file and, for a `decision` or `job` option, its decision row (whose text contains the id) or job row added on the branch. A repo with no proposals registry refuses the kind, naming the fix. `audit.py` `subject_kind` and `throughput` learn `decide`. Only Liam merges: nothing in the core calls auto-merge on it, as with `meta/`; `docs/REVIEW.md` says so.
5. **The guard, every branch kind.** Beside the kind's own check, as the decisions rule is:
   - an answered status (`accepted`, `declined`, `deferred`), or any change to `answer`, on a row that had none at the base is refused outside `decide/`; the one exception is a `plan/` row that qualifies for `--auto` by the **base's** `auto_apply` (no tag, the recommended option, `answer.by` = `auto_apply`);
   - a proposal row added already answered counts as the same change;
   - once answered, only `status`, `outcome`, `decision`, `job` may change, and a row is never deleted;
   - `plan/` may add `open` rows, fill `open` rows, and close rows; a `job/` branch may change no proposal row;
   - an `ANSWERS_` file may be added or changed only on `decide/` (`docs/**` would otherwise let a `plan/` branch write a quotation of Liam).
6. **`wsc audit` reads the proposals** from the rows at the sha it measures (`rows_at`, not the working tree: a finding must not depend on where the audit ran), adding two keys to the record, present only when not empty, so old records render unchanged and `VERSION` stays 1:
   - `suppressed`: a finding whose row is `declined` or `deferred` leaves `findings` and is listed here with its row id, unless it is worse than the baseline by more than the margin. Worse: `sign * (value - baseline) > reraise_margin * abs(baseline)`, sign from `direction`; on a baseline of 0, any worsening. It then stays in `findings`, and `draft` writes a row with `reraises`.
   - `remeasured`: one entry per applied row not yet closed: `{proposal, finding, baseline, value, verdict}`. `unmeasured` when the metric is in `skipped` or `failed`; `too_soon` when the window starts before the row was applied (the job's merge, or the answer's date for a decision), or the old state would be read as no change; `gone` when the subject is in `details.gone`; `moved` when the finding is absent, or better than the baseline by at least the margin; else `not_moved`.
   `render_md` shows both. The verb prints a line for each moved and not moved row.
7. **`doc_caps` skips the job folders** (W44 report question 2, as recommended): `<[jobs] dir>/**` is left out of the metric, and only the metric: the `doc_size` gate does not change. This lands before any finding becomes a proposal.
8. **Waiting on Liam** is a section at the top of `jobs view`, not a job lane (a proposal is not a job row, and `lane()` stays as it is): the open proposals in `ask`'s order, or nothing when there are none. The heading uses `[jobs.text] owner`.

## Deliverables
1. The schema and the registry (decisions 1 and 3), declared in the core; it stays empty here, and CI exercises it end to end like the other shipped schemas.
2. `warscape/proposals.py`, `warscape/verbs/proposals.py` with its header and tools row (`python3 wsc.py reg add tools warscape/verbs/proposals.py`), `proposals` in `CORE_VERBS`, `check` in `gate_jobs`.
3. The `decide/` kind and the guard (decisions 4 and 5) in `warscape/policy.py`, the docstring updated (it is the reference for the kinds).
4. `warscape/audit.py`: decisions 6 and 7, and `docs/AUDIT_METRICS.md` to match.
5. `jobs view`: decision 8.
6. Host tests, red first, in `tests/test_proposals.py` and beside the existing policy and audit tests. Each state change, each verdict of decision 6, and for the guard **one test per forgery**, each refused: a `plan/` branch accepting a row; a `plan/` branch adding a row already accepted; a `plan/` branch auto-accepting a tagged row, an off-recommendation option, or a class only its own head's `wsc.toml` lists; a `job/` branch changing a row; a `plan/` branch adding an `ANSWERS_` file; a `decide/` branch with `answer.by` not the owner, with a job row not `needs_brief`, changing an existing job row, touching code, or naming a decision row that lacks the id. Then the same changes allowed where they should be.
7. **A dry run, in a throwaway clone, pasted in the report:** the core's newest committed record, `draft`, fill two rows by hand (one `job`, one `none`), `proposals check`, `ask`, `answer` on `decide/<date>`, `wsc policy --branch decide/<date>` saying ok, the same diff on a `plan/` branch refused; then a later synthetic record through `audit` and `close`. No proposal row is committed on this branch: W47's session raises the first real ones.
8. Docs: `docs/PROPOSALS.md`, the one owner of the row, the states and the answer round, short; a link from `docs/CONSUMING.md` paid for with a cut; `docs/REVIEW.md` one clause that `decide/` waits for the owner, as `meta/` does; `docs/UPGRADING.md`, what a game declares (the registry, `[storage] dir`, `[policy] plan`).

## Out of scope
- The audit session, its cadence, `docs/AUDIT.md` and the first real proposals (W47); brief questions as proposals and `jobs check` listing due ones (W32); autopilot starting briefs and builds (W46).
- `both_sides_min` (W44 report question 3): a judgement after one more record, so it stays 3 here, and so does every other `[audit]` default.
- W117 (the false `parked` and the case-sensitive subjects): a `later` row, and a `job/` branch cannot change another row, so it cannot be closed from here. Until it lands, a drafted `idle_queue` on a quiet main needs a human eye; say so in `docs/PROPOSALS.md`.
- Fixing anything a finding names. Napoleon's `wsc.toml` and its pin (its adoption job).

## Open questions
1. Is 0.25 right for `reraise_margin`, as a share of the baseline? recommended: yes, judged after the first closed proposals; default after: 2026-11-20.
2. "Only Liam merges" a `decide/` branch rests on nothing calling auto-merge, as with `meta/`: the agents push with his account, so no check can tell him from them. Should CI refuse a `decide/` pull request that has auto-merge on? recommended: no, the same standing as `meta/`, since an agent could as well merge by hand; tag: risk.

## Kill criteria
- A forgery test of deliverable 6 cannot be made to fail closed through `settings()` without a required new argument to the judge child: stop and report, a `JUDGE_API` break is Liam's call.
- `audit.py` needs a change to a metric's numbers beyond decision 7: `python3 wsc.py audit --offline` at the branch's merge base and at the head differ on any finding but `doc_cap:jobs/...`: stop and report the difference.
- `tests/test_audit.py` or the new tests take the Windows `tests` gate past `[tests] timeout_s` on CI: stop adding tests, slim the fixtures, and report the run; do not raise the limit (a `wsc.toml` change the reviewer must judge).
- The dry run's `policy` line does not say ok on `decide/<date>`, or is not refused on `plan/`, after 10 calls: stop and report both outputs.
- Over about 150 tool calls: stop, commit, report what is left.

## Finish
Report in `jobs/W45/report.md` with `## What was built`, `## Evidence` (tests red then green, the branch's CI run id, the dry run, what the tests add to the Windows run), `## Deviations from the brief and why`, `## Open questions`, and what W47's brief must call (`draft`, `answer --auto`, `close`, in that order) and what a game declares. Run the full `python3 wsc.py gates` before pushing anything that removes or depends on a tracked file. Write the usage line: `python3 wsc.py jobs usage W45 --write --from-json <file>`. Then:
`wsc reg set jobs W45 status=review report=jobs/W45/report.md` (`python3 wsc.py`)
Push `job/W45`, open the draft pull request, and stop: an independent reviewer merges (C18); the release workflow tags (C27).
