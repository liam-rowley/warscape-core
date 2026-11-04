# Consuming the core: one-time upgrade steps

What a game does once, in the pin-bump commit that crosses a given core version. Moved out of [CONSUMING.md](CONSUMING.md) on 2026-11-04 (core W29 merge) to keep that doc under the 30 KB cap; CONSUMING.md keeps a one-line pointer under the same heading.

## Hooks and gate keys added in 0.24.0 (C23)

- **`.githooks/commit-msg`** refuses a commit whose message has no `Claude-Session:` trailer with a value (read with `git interpret-trailers --parse`, as `policy` reads
  pushed commits: git sees a trailer only in the last paragraph, with `Co-Authored-By:`). Opt in with `[policy] commit_msg_hook = true` (default `false`; it uses
  `[policy] session_trailer`, and an empty name switches it off). Merge commits are skipped; fix a refusal with `git commit --trailer "Claude-Session: <id>"`;
  a human commit bypasses once with `--no-verify`. Same wiring as the pre-push hook (`core.hooksPath core/.githooks`). It runs `wsc policy --commit-msg <file>`.
- **`run_refs` gate** (fast set): every repo path a tracked `**/runs/**/README.md` names (link targets and backticked paths) must exist: from the root, from the README's
  folder, as the tail of a tracked path, inside a submodule, or git-ignored. `[gates] run_refs_since = "YYYY-MM-DD"` skips run folders dated before it (default `""`:
  all checked); set it to the pin-bump date when old READMEs name moved paths.

## Moving to base-judged policy (0.26.0, core W23, C24)
In the pin-bump commit itself, because the render guard and the new facts fail otherwise (napoleon: J78):
1. **`ci/policy.yml.in`:** `on: pull_request_target` with the same types. For the bump's own pull request add a second trigger, `pull_request` with
   the same types and `paths: ['jobs/<bump id>/report.md']` (main's copy has no `pull_request_target` yet, so without it nothing would run `policy`
   on that pull request); remove it in the next change to the template (`ci_render` warns until then). Run `wsc ci render`.
2. **`[ci] policy_extra_steps`** now run in the base checkout, where `HEAD` is the base. Take the head's sha from an `env:` value
   (`${{ github.event.pull_request.head.sha }}`), never from an expression inside `run:`, and make both pins present in `core/` if a module compares them.
3. **The `policy`-stage module** (napoleon `tools/gates/pipeline.py`): run git at `ctx.facts['repo']` with the `head`, `base` and `merge_base` shas
   (`show`, `show_first`, `core_pin_diff`, `collect_acceptance`), never in `ctx.root` and never with `'HEAD'`; a module left as it is fails closed, as a
   crash. `ctx.root/core/...` is now the base's core: a build id must come from the base's `build_id.py` over the head's blobs, never by running the
   head's copy. When a bump changes `build_id.py` itself, the base's algorithm cannot reproduce the head's id: the game needs a rule for that, and the
   default is a refusal.
4. **Behaviour.** CI judges the pull request's head against the base tip, so a branch behind `main` on the decisions file must merge `main`. Globs
   match by path segment: `registries/*` no longer covers `registries/<name>/<row>.json`. Until the bump merges, the game's pull requests are judged
   as before, with the note.
