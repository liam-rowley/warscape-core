"""The job queue as a verb: check the queue, pick up the next job, find the next job to review or to fix, show the queue as a page.

purpose: Check the jobs registry against jobs/ (status invariants, file links, brief shape, review rounds, the repo's `jobs`-stage gate modules), pick the next job to build, review or fix, and show the queue as a readable page; --serve starts a job's session from its button and --auto starts every ready review and fix.
usage: wsc jobs check | jobs next [--id <id>] [--peek] [--offline] | jobs review [--id <id>] [--all] [--offline] | jobs fix [--id <id>] [--all] [--offline] | jobs view [--all] [--offline] [--out PATH] [--no-open] | jobs view --serve [--port N] [--dry-run] [--no-open] [--auto [--interval SECONDS]] | jobs worktrees [--prune] | jobs usage <id> [--write] [--from-json FILE]
when: `next` for "pick up the next job" (`--id` for a named job: what a session launched from the view runs); `review` for "review the next job"; `fix` for a job whose review asked for changes; `check` in the tests gate and before pushing a brief or a job row change; `view` to read the queue in a browser, `view --serve` to start a session from a button; `worktrees` for stale worktree registrations and a `.git` above the repo; `usage` to fill a report's `Usage:` line before status=review.
verb: jobs

The rules are code in warscape/jobq.py (moved from napoleon-remastered `tools/verbs/jobs.py` in napoleon J62; the story of each rule is in that
repo's jobs/J52, J54, J55, J56, J57 reports). `next`, `review`, `fix` and `view` read the remote branch names (one `git ls-remote origin`);
`review`, `fix` and `view` then read each job branch whose job is not done on main after one `git fetch` of `job/*` (`--id`: that branch only,
done or not; `--all`: done jobs too); `--offline` uses the local remote-tracking refs instead. `next`, `review`, `fix` and the static `view` first print main's CI state
(W22: the latest completed push run of each workflow in `[ci] workflows` on main and its required jobs, two `gh api` calls per workflow; a red job is
the first thing printed, an unreadable state is one "unknown" line, green prints nothing; the page head carries the same line, `view --serve`
memoises it for 60 s; nothing is refused) and then every open
pull request with a failed check (one `gh pr list` call; `--offline` skips both); `review` and `fix` then read the chosen branch's head commit's
check runs (one `gh api` call) above the steps. `view` writes one self-contained HTML page (default `_scratch/jobs.html`) and opens it;
`view --serve` serves it on 127.0.0.1 and the buttons post (id, action) to the server, which checks a per-run token, Origin, Host, content
type, readiness against fresh branches and no live session of the same name (`claude agents --json`, fail closed), then runs
`claude --bg` itself; no permission flag is ever passed. `review` (and the server, for a review) first claims the round: the remote ref
refs/claims/<id>/round-<n> (warscape/claims.py, core W27); a round claimed by another session within `[jobs] claim_hours` is refused naming
it, and an unreadable origin refuses (`--offline` claims nothing). `next`, `review` and `view` print the live claims; `next` and `review`
release the claims of finished rounds.
W26: `next` claims before it prints: a create-only `git push` of origin/main to `job/<id>` (`brief/<id>` for a brief); a claim another session
won moves on to the next ready job (at most 5 tries); `--peek` and `--offline` claim and release nothing. It orders by (phase, number) and, with `[jobs] pc_state`
or `WSC_PC_STATE`, skips a needs_pc build where that folder is absent. `--auto` starts a review only on a green head, a fix once CI has finished,
one needs_pc row at a time, and prunes dead worktree registrations each tick. `worktrees` prints the stale-worktree warnings (warscape/worktrees.py).
W31: `usage` prints a report's `Usage:` line from the game's `[jobs] usage_cmd` (no shell, 60 s, repo root as cwd; the core reads no transcript) or from
`--from-json FILE`, the same JSON by hand; `--write` puts it in `jobs/<id>/report.md`, changing nothing else there.
The repo's own rules and texts: `wsc.toml` [jobs] and its game gate modules (`[gates] dirs`, stages `jobs` and `view`).
"""
import sys
import threading
import webbrowser
from datetime import datetime, timezone

from .. import jobq as J
from .. import worktrees as W

NAME = 'jobs'
HELP = 'the job queue: check it, claim the next job to build (next), to review (review) or to fix (fix), view it, its stale worktrees (worktrees), a report\'s usage line (usage)'


def add_arguments(p):
    p.add_argument('action', choices=['check', 'next', 'review', 'fix', 'view', 'worktrees', 'usage'])
    p.add_argument('job', nargs='?', help='usage: the job id (every other action takes --id)')
    p.add_argument('--offline', action='store_true', help='use local remote-tracking refs instead of asking origin (a single-branch or shallow clone sees only the branches it fetched)')
    p.add_argument('--id', help='next, review, fix: this job only (J<n>): its steps when it is ready, else exit 1 with the reason')
    p.add_argument('--all', action='store_true', help='review, fix, view: also read the job branches of jobs done on main (skipped by default)')
    p.add_argument('--out', default='_scratch/jobs.html', help='view: where to write the page, relative to the repo root (default %(default)s)')
    p.add_argument('--no-open', action='store_true', help='view: write the page (or start the server) but do not open a browser')
    p.add_argument('--serve', action='store_true', help='view: serve the page on 127.0.0.1 so its buttons start background Claude Code sessions (until Ctrl+C)')
    p.add_argument('--port', type=int, default=0, help='view --serve: the port (default 0: the OS picks one)')
    p.add_argument('--dry-run', action='store_true', help='view --serve: make every check, but answer with the command instead of running it (with --auto: log what it would start)')
    p.add_argument('--auto', action='store_true', help='view --serve: also start every ready review and fix by itself, each --interval (never a brief or a build)')
    p.add_argument('--peek', action='store_true', help='next: print what would be picked and the push that would claim it; claim nothing')
    p.add_argument('--prune', action='store_true', help='worktrees: run git worktree prune (registrations whose folder is gone) and say how many it removed')
    p.add_argument('--interval', type=int, default=300, help='view --serve --auto: seconds between autopilot ticks (default %(default)s)')
    p.add_argument('--write', action='store_true', help='usage: put the line in jobs/<id>/report.md (replaces the one there, or goes after the first paragraph)')
    p.add_argument('--from-json', metavar='FILE', help='usage: the numbers from this file, the JSON [jobs] usage_cmd prints, instead of running the command')
    p.add_argument('--session', help='review: the name the round is claimed for (default $WSC_SESSION_ID, $CLAUDE_CODE_SESSION_ID, then user@host)')


def refuse(why):
    print(f'jobs: {why}', file=sys.stderr)
    return 1


def usage(args, ctx, by):
    """`jobs usage <id>`: print the report line from the game's command or `--from-json`; `--write` puts it in the report. Any failure writes nothing."""
    jid = args.job
    if not jid:
        return refuse('usage needs a job id: wsc jobs usage <id> [--write] [--from-json FILE]')
    if jid not in by:
        return refuse(f'{jid} is not a row of the jobs registry')
    report = ctx.root / J.S.jobs_dir / jid / 'report.md'
    rel = report.relative_to(ctx.root).as_posix()
    if args.write and not report.is_file():
        return refuse(f'{rel} does not exist: --write changes a report, it never starts one')
    try:
        line = J.usage_line(J.read_usage_json(args.from_json) if args.from_json else J.run_usage_cmd(J.S.usage_cmd, jid, ctx.root))
        if args.write:
            report.write_bytes(J.set_usage_line(report.read_bytes().decode('utf-8'), jid, line).encode('utf-8'))   # bytes: a CRLF report stays CRLF
    except ValueError as x:
        return refuse(f'usage {jid}: {x}')
    print(line)
    if args.write:
        print(f'jobs usage: wrote {rel}')
    return 0


def run(args, ctx):
    if getattr(args, 'job', None) and args.action != 'usage':   # `jobs next W31` must not pick some other job
        return refuse(f'{args.action} takes its job as --id {args.job}')
    J.configure(ctx)
    reg_dir = ctx.config['registries_dir']
    rows = J.main_rows(ctx)
    by = {r['id']: r for r in rows}

    def done_ids(rs):   # the job branches branch_rows skips; --all reads them too
        return set() if getattr(args, 'all', False) else {r['id'] for r in rs if r.get('status') == 'done'}

    hours = ctx.config['jobs'].get('claim_hours', 4)

    def read(p):
        f = ctx.root / p
        return f.read_text(encoding='utf-8') if f.is_file() else None

    if args.action == 'check':
        jd = ctx.root / J.S.jobs_dir
        folders = [d.name for d in jd.iterdir() if d.is_dir()] if jd.is_dir() else []
        errs, warns, summaries = J.check(ctx, rows, read, folders)
        extra = ''.join(', ' + s for s in summaries)
        for e in errs:
            print(f'jobs: {e}', file=sys.stderr)
        for w in warns:
            print(f'jobs: warning: {w}', file=sys.stderr)
        print(f'jobs check: {len(rows)} rows, {"%d problems" % len(errs) if errs else "ok"}{extra}')
        return 1 if errs else 0

    if args.action == 'usage':
        return usage(args, ctx, by)

    if args.action == 'worktrees':   # W26: what a game's setup verb prints (warscape.worktrees.report); --prune removes dead registrations only
        if getattr(args, 'prune', False):
            removed, err = W.prune(ctx.root)
            if err:
                return refuse(f'git worktree prune failed: {err}')
            print(f'worktrees: pruned {removed} worktree registration{"" if removed == 1 else "s"} whose folder was gone')
            return 0
        try:
            branches = J.remote_branches(ctx.root, args.offline)
        except ValueError as x:
            return refuse(str(x))
        lines = W.report(ctx.root, rows, branches)
        print('\n'.join(f'worktrees: warning: {l}' for l in lines) if lines else 'worktrees: nothing stale')
        return 0

    if args.auto and not (args.action == 'view' and args.serve):
        return refuse('--auto runs inside jobs view --serve')
    if args.auto and args.interval < 30:
        return refuse('--interval must be at least 30 seconds (each tick fetches the job branches)')

    if args.action == 'view' and args.serve:
        def snapshot():   # fresh on every request: the working tree's rows and docs, origin's branches, each job branch's row
            now = J.main_rows(ctx)
            branches = J.remote_branches(ctx.root, args.offline)
            return now, read, branches, J.branch_rows(ctx.root, branches, args.offline, reg_dir, done=done_ids(now))
        srv = J.JobServer(snapshot, J.list_agents, lambda argv: J.start_session(argv, ctx.root), port=args.port, dry_run=args.dry_run,
                          root=ctx.root, log_path=ctx.root / '_scratch' / 'jobs_auto.log', ctx=ctx,
                          main_line=lambda: J.main_html(J.main_state(ctx.config['ci'], ctx.root, args.offline)),
                          ci=lambda sha: J.branch_ci(ctx.root, sha, args.offline), prune=lambda: W.prune(ctx.root),
                          claim=None if args.offline else lambda jid, n, head, who: J.take_claim(ctx.root, jid, n, head, who, hours))
        print(f'jobs view: serving {srv.url}{" (dry run: nothing is started)" if args.dry_run else ""}; Ctrl+C stops it', flush=True)
        stop = threading.Event()
        if args.auto:
            threading.Thread(target=srv.run_auto, args=(args.interval, stop), daemon=True).start()
        if not args.no_open:
            webbrowser.open(srv.url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            srv.server_close()
        return 0

    mstate = J.print_main_health(ctx.config['ci'], ctx.root, args.offline)   # W22: a red main first, then the pull requests
    J.print_red_prs(ctx.root, args.offline)
    branches = J.remote_branches(ctx.root, args.offline)
    if args.action == 'next':   # W27: live review claims, releasing those whose job branch is gone (never on --peek); W26: claim, then print
        peek = getattr(args, 'peek', False)
        J.print_claims(ctx.root, args.offline, branches, release=not peek)
        rc, text = J.next_claim(ctx.root, rows, lambda: J.remote_heads(ctx.root, args.offline), jid=args.id, peek=peek, offline=args.offline)
        if rc:
            return refuse(text)
        print(text)
        return 0

    if args.action == 'view':
        out = ctx.root / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        on_branch = J.branch_rows(ctx.root, branches, args.offline, reg_dir, done=done_ids(rows))
        J.print_claims(ctx.root, args.offline, branches)
        out.write_text(J.render_view(rows, read, branches, stamp, on_branch, root=ctx.root, ctx=ctx, main_html=J.main_html(mstate)), encoding='utf-8')
        print(f'jobs view: {len(rows)} jobs -> {out}')
        if not args.no_open:
            webbrowser.open(out.resolve().as_uri())
        return 0

    action = args.action   # review or fix: both read the job branch's own row
    if args.id:
        on_branch = J.branch_rows(ctx.root, branches, args.offline, reg_dir, only=args.id)
        why = J.not_ready(action, args.id, by, branches, on_branch)
        if why:
            return refuse(why)
        jid = args.id
    else:
        on_branch = J.branch_rows(ctx.root, branches, args.offline, reg_dir, done=done_ids(rows))
        jid = J.pick_branch(action, on_branch)
        if not jid:
            print(f'No job branch is waiting for {"review" if action == "review" else "fixes"}: ' + (', '.join(
                f'{j} ({(J.branch_state(b).row or {}).get("status", "no row")})' for j, b in sorted(on_branch.items(), key=lambda x: J.num(x[0])))
                or 'no job branches'))
            return 0
    if action == 'review':   # W27: release the claims of rounds the branches already have, then claim this round (the push is the lock)
        J.print_claims(ctx.root, args.offline, branches, {j: J.branch_state(b).rounds for j, b in on_branch.items()}, release=True)
        if args.offline:
            print('(round not claimed: --offline)')
        else:
            from ..claims import ClaimError, ref, session_name
            who, n = session_name(getattr(args, 'session', None)), on_branch[jid].rounds + 1
            try:
                held, c = J.take_claim(ctx.root, jid, n, on_branch[jid].head, who, hours)
            except ClaimError as e:
                return refuse(f'cannot claim round {n} of {jid}: {e}: the claim cannot be proved, so the review does not start '
                              '(--offline skips the claim, for local tests only)')
            if not held:
                return refuse(f'round {n} of {jid} is claimed by {c.session} ({ref(jid, n)}, stale after {hours} h): review another job '
                              f'(--id) or wait')
            print(f'Claimed round {n} of {jid} ({ref(jid, n)}) for {who}.')
    rounds = on_branch[jid].rounds   # not_ready has already refused a 4th review and a fix with no round
    print(J.branch_checks(ctx.root, f'job/{jid}', on_branch[jid].head, args.offline))
    title = (on_branch[jid].row or by.get(jid) or {}).get('title', '')
    hb = J.branch_state(on_branch[jid]).handback
    print(J.review_steps(jid, rounds, hb) if action == 'review' else J.fix_steps(jid, rounds, title, hb))
    return 0
