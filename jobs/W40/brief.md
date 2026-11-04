# W40: Rule A (reviewer code under a merge verdict) becomes an error

Model: Opus, reason: a change to `policy.py`, the one gate that decides what reaches `main`; the error half is a bypass if its file set or its round attribution is wrong (D52: builds on Opus). Budget about 70 tool calls: about 15 reading and the scan, 15 for the red tests, 15 for the key and the rule, 10 for docs, 15 for gates, CI and the report. At the cap, stop, commit, and report what is left.
Semver: patch

## Goal
W27 shipped rule A (a review round whose own commits change a file outside `jobs/<id>/` and the job's row must end `merge after fixes`, never `merge`) as a **warning**, because a scan of the merged job branches found it would have refused 32 (5 core, 27 napoleon), past W27's kill criterion of 3 beyond the audit's (`jobs/W27/report.md`, deviation 1 and open question 1; `jobs/W27/review.md` finding 3). Liam decided on 2026-11-04 (the W40 row) that it becomes an error later, by a small job, once reviewers have used `merge after fixes` for a while: outright, or behind a `[policy]` key a game can switch on. This job re-runs the scan over what merged since W27, picks one, and builds it. Audit source: napoleon-remastered `docs/audits/AUDIT_2026-11-03.md` (R5; read-only with `git -C /c/Users/liamr/repos/napoleon-remastered show origin/main:docs/audits/AUDIT_2026-11-03.md`).

## What exists (read before building; checked 2026-11-04 against `origin/main` f1dbb13)
- **The rule:** `warscape/policy.py` `round_problems` (about :346-390; the `# rule A` loop at the end) returns `(errs, warns)` and appends rule A to `warns`; its docstring and the module docstring (rule list, A) say it warns. The file set is `ok(p)`: `<jobs dir>/<id>/` and `<reg_jobs>/<id>.json` (C28 made every other change count as code).
- **Config:** `warscape/repo.py` `DEFAULTS['policy']` (:78-91) and its type checks (:186-200; `decisions_cite_job` is the model for a new key, a string enum like `release.consumer_check` at :190 is the shape wanted). The `cfg` dict `policy.py` reads is built at :70-80 from the base's `wsc.toml` (W23: the base's rules judge, the head is data), so a new key needs no `JUDGE_API` change. `JUDGE_API` stays as it is.
- **Tests:** `tests/test_policy.py` `W27ReviewerCode` (:222, helpers `w27(steps)`, `rv`, `BUILD`, `FIX1`; the first test comments that it is a warning), `tests/test_policy_base.py` CoreMode `test_w27_*` (A warns, exit 0).
- **Docs:** `docs/REVIEW.md` ("Output", the verdict rules, lines 43-46), `docs/CONSUMING.md` (`[policy]` block from line 150: `decisions_cite_job`, `thin_merge_*`), `wsc.toml` `[policy]`, `README.md` only if it states rule A.
- **The scan:** W27's script was not committed (review finding 4: it "should be a committed, host-tested tool so the warn/error split can be re-measured"). W27's method: every merged `job/*` pull request judged at its head against its merge commit's first parent, with the current rules, gate modules off, `decisions_cite_job` on. Merged jobs since W27 (`git log --first-parent origin/main` after 95f0269): at least W28, W29, W26, W15; list the rest with `gh pr list --state merged --search "head:job/"`.

## Decisions already made (follow them; a deviation goes in the report with its reason)
1. **Build, unless the scan contradicts it: a `[policy]` key `reviewer_code = "warn" | "error"`, default `"warn"`; the core's own `wsc.toml` sets `"error"`.** Why: a game with a history of `merge` rounds that touched docs (napoleon: 27 branches) switches on at its own pin bump; the core's reviewers know the rule (`docs/REVIEW.md`). "Outright" is chosen only if the scan shows 0 refusals since W27 in both repos and the report says why a default of `error` is safe for a game that has not read the new wording. Either way the file set is C28's, unchanged.
2. **The error text keeps rule A's wording** (commit shas, paths, "write the verdict `merge after fixes`; a fresh round reviews your change"), so a reviewer who met the warning recognises it.
3. **In-flight branches:** policy is judged with the base's rules (C24), so a branch already carrying a `merge` round over reviewer code starts to fail when the base changes. State in the report what that costs (expected: a new round with the verdict changed, a two-line review change) and which open `job/*` branches it touches today (`git branch -r`).
4. **The scan becomes a committed tool**, not a scratch script (W27 review finding 4): `wsc policy --scan [--repo DIR] [--since REV] [--rule A]` is the shape wanted, a mode of the existing verb (no new verb file, so no verb-set `minor` floor). It prints one line per merged `job/` branch that a rule refuses or warns about, and the count per rule. The pure parts (which branches to judge, the count) get host tests on temporary repositories; the `gh` call is injected. If this does not fit the budget, say so in the report and paste W27's method as a documented one-off instead.

## Scope: files this job touches
`warscape/policy.py`, `warscape/repo.py`, `warscape/verbs/policy.py`, `wsc.toml`, `tests/test_policy.py`, `tests/test_policy_base.py`, the repo-config test file that holds the other `[policy]` key checks (find it with `grep -l decisions_cite_job tests/*.py`), `docs/REVIEW.md`, `docs/CONSUMING.md` (keep it under the 30 KB `doc_size` cap), `README.md` if it states rule A, `registries/tools.jsonl` only if the `policy` row text changes. Not `VERSION` (C27: this id is above `[jobs] semver_from`; the release workflow owns it), not `registries/jobs/` other than W40's own row, not `proxy/` or `harness/` (no acceptance passes apply).

## Steps
1. `git fetch`; `python3 wsc.py gates --fast` for a baseline. Read "What exists".
2. **Re-run the scan** before any code: W27's way over every merged `job/` branch of this repo and of napoleon-remastered (`git -C /c/Users/liamr/repos/napoleon-remastered fetch`; read-only, that clone is not otherwise touched), then restricted to branches merged after W27 (core: after 95f0269; napoleon: after its pin bump to 0.35.0 or later). Record per repo: branches judged, rule A hits, hits since W27, and for the since-W27 hits who wrote the code (a reviewer's `merge` over docs, a fix session, a builder-attributed commit). The numbers answer: do reviewers now write `merge after fixes` when they touch code? Decision 1 stands if the core has 0 to 3 hits since W27; more than 3 is the first kill criterion.
3. **Failing tests first**, committed red: `W27ReviewerCode` split into warn mode and error mode (the same `steps`; `reviewer_code="error"` gives `e` naming the sha and path and `w == []`; `"warn"` keeps today's lines); key validation (`"error"`, `"warn"` ok; `"maybe"` and a bool refused with a `ConfigError` naming the key); CoreMode in `test_policy_base.py`: with the base's `wsc.toml` at `error` the verdict is REFUSED and exit 1, at `warn` it is ok and exit 0, and a **head** that flips the key to `warn` is still judged with the base's value (C24). Unchanged cases stay green in both modes: a reviewer commit of `review.md` and the row only; code by round 1 reviewed by round 2; the unattributed-commit case.
4. Build: the key (`DEFAULTS`, check), `cfg` in `policy.py`, `round_problems` routing rule A to `errs` or `warns` by the key, the two docstrings, `wsc.toml` `reviewer_code = "error"`, then the scan mode (decision 4). One commit each, tests green at each.
5. Docs: `REVIEW.md` "Output" says that under the core's rules `merge` after reviewer code is refused and names the fix; `CONSUMING.md` documents `reviewer_code` beside `decisions_cite_job`, with the napoleon note (a game turns it on in its pin-bump commit, once its open `merge` rounds are done).
6. `python3 wsc.py gates` (full), then from the branch checkout `python3 wsc.py policy --branch job/W40 --base origin/main` (read the output; never chain after a pipe).

## Tests and acceptance
- New host tests red first, then green; `python3 wsc.py gates` green; the branch's CI run id (`gates` and `policy`) in the report.
- The repro, through the real `wsc policy` verb on a temporary repository: a job branch whose round 1 reviewer commit changes `docs/REVIEW.md` and writes `merge` ends REFUSED with `reviewer_code = "error"` and ok with a warning at `"warn"` (paste both outputs).
- The scan numbers in the report: per repo, branches judged, rule A hits, hits since W27, the date of the scan, and the choice they support (key or outright).
- `python3 wsc.py policy --branch job/W40 --base origin/main` ok apart from the missing report and review of a job still in progress.

## What a game must do after this
Napoleon: nothing is forced. Its pin bump may set `[policy] reviewer_code = "error"` when it wants it; until then rule A stays a warning there. State this in the report under "what napoleon must do".

## Kill criteria
- More than 3 merged core `job/` branches since W27 would be refused by rule A as an error: stop and report the list; reviewers are not yet using `merge after fixes` and the error should wait.
- Any change that lets a head's `wsc.toml` choose the mode for its own pull request (policy is the bypass surface, C24): stop and fix first.
- Rule A's file set changes (C28 fixed it), or a rule other than A changes severity: stop; that is not this job.
- Core CI red after three fix attempts for a cause in this change, or about 70 calls: stop and report.

## Open questions (recommendation; follow it unless Liam says otherwise)
1. **Key or outright?** Recommended: the key, default `warn`, the core at `error` (decision 1).
2. **Should rule D's unmerged-branch cites (the other W27 warning) follow?** Recommended: no, it is separate evidence; list its since-W27 count in the report so a later job can decide.
3. **A `--rule` flag on the scan for B, C, D and F too?** Recommended: yes if it falls out of the same code, else A only.

## Finish
Report in `jobs/W40/report.md` (the scan before any code, the choice it supports, tests red then green and where they ran, the branch run id, both repro outputs, deviations, open questions, what napoleon must do), then `wsc reg set jobs W40 status=review report=jobs/W40/report.md` (`python3 wsc.py`).
Push `job/W40`, open the draft pull request, and stop: an independent reviewer merges (C18); the workflow tags (C27).
