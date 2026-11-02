"""The job queue as a verb: check the queue, pick up the next job, find the next job to review or to fix, show the queue as a page.

purpose: Check the jobs registry against jobs/ (status invariants, file links, brief shape, review rounds, the repo's hooks), pick the next job to build, review or fix, and show the queue as a readable page; --serve starts a job's session from its button and --auto starts every ready review and fix.
usage: wsc jobs check | jobs next [--id <id>] [--offline] | jobs review [--id <id>] [--all] [--offline] | jobs fix [--id <id>] [--all] [--offline] | jobs view [--all] [--offline] [--out PATH] [--no-open] | jobs view --serve [--port N] [--dry-run] [--no-open] [--auto [--interval SECONDS]]
when: `next` for "pick up the next job" (`--id` for a named job: what a session launched from the view runs); `review` for "review the next job"; `fix` for a job whose review asked for changes; `check` in the tests gate and before pushing a brief or a job row change; `view` to read the queue in a browser, `view --serve` to start a session from a button.
verb: jobs

The rules are code in warscape/jobq.py (moved from napoleon-remastered `tools/verbs/jobs.py` in napoleon J62; the story of each rule is in that
repo's jobs/J52, J54, J55, J56, J57 reports). `next`, `review`, `fix` and `view` read the remote branch names (one `git ls-remote origin`);
`review`, `fix` and `view` then read each job branch whose job is not done on main after one `git fetch` of `job/*` (`--id`: that branch only,
done or not; `--all`: done jobs too); `--offline` uses the local remote-tracking refs instead. `next`, `review` and `view` first print every open
pull request with a failed check (one `gh pr list` call; `--offline` skips it); `review` and `fix` then read the chosen branch's head commit's
check runs (one `gh api` call) above the steps. `view` writes one self-contained HTML page (default `_scratch/jobs.html`) and opens it;
`view --serve` serves it on 127.0.0.1 and the buttons post (id, action) to the server, which checks a per-run token, Origin, Host, content
type, readiness against fresh branches and no live session of the same name (`claude agents --json`, fail closed), then runs
`claude --bg` itself; no permission flag is ever passed. The repo's own rules and texts: `wsc.toml` [jobs] and its hook modules.
"""
import sys
import threading
import webbrowser
from datetime import datetime, timezone

from .. import jobq as J

NAME = 'jobs'
HELP = 'the job queue: check it, pick the next job to build (next), to review (review) or to fix (fix), view it'


def add_arguments(p):
    p.add_argument('action', choices=['check', 'next', 'review', 'fix', 'view'])
    p.add_argument('--offline', action='store_true', help='use local remote-tracking refs instead of asking origin (a single-branch or shallow clone sees only the branches it fetched)')
    p.add_argument('--id', help='next, review, fix: this job only (J<n>): its steps when it is ready, else exit 1 with the reason')
    p.add_argument('--all', action='store_true', help='review, fix, view: also read the job branches of jobs done on main (skipped by default)')
    p.add_argument('--out', default='_scratch/jobs.html', help='view: where to write the page, relative to the repo root (default %(default)s)')
    p.add_argument('--no-open', action='store_true', help='view: write the page (or start the server) but do not open a browser')
    p.add_argument('--serve', action='store_true', help='view: serve the page on 127.0.0.1 so its buttons start background Claude Code sessions (until Ctrl+C)')
    p.add_argument('--port', type=int, default=0, help='view --serve: the port (default 0: the OS picks one)')
    p.add_argument('--dry-run', action='store_true', help='view --serve: make every check, but answer with the command instead of running it (with --auto: log what it would start)')
    p.add_argument('--auto', action='store_true', help='view --serve: also start every ready review and fix by itself, each --interval (never a brief or a build)')
    p.add_argument('--interval', type=int, default=300, help='view --serve --auto: seconds between autopilot ticks (default %(default)s)')


def refuse(why):
    print(f'jobs: {why}', file=sys.stderr)
    return 1


def run(args, ctx):
    J.configure(ctx)
    reg_dir = ctx.config['registries_dir']
    rows = J.main_rows(ctx)
    by = {r['id']: r for r in rows}

    def done_ids(rs):   # the job branches branch_rows skips; --all reads them too
        return set() if getattr(args, 'all', False) else {r['id'] for r in rs if r.get('status') == 'done'}

    def read(p):
        f = ctx.root / p
        return f.read_text(encoding='utf-8') if f.is_file() else None

    if args.action == 'check':
        jd = ctx.root / J.S.jobs_dir
        folders = [d.name for d in jd.iterdir() if d.is_dir()] if jd.is_dir() else []
        errs = J.problems(rows, read, folders, ctx)
        errs += J.call_hooks('queue_problems', ctx, rows, ctx.files())
        extra = ''.join(', ' + s for s in J.call_hooks('summary', ctx, rows, read, joiner='') if s)
        for e in errs:
            print(f'jobs: {e}', file=sys.stderr)
        print(f'jobs check: {len(rows)} rows, {"%d problems" % len(errs) if errs else "ok"}{extra}')
        return 1 if errs else 0

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
                          root=ctx.root, log_path=ctx.root / '_scratch' / 'jobs_auto.log', ctx=ctx)
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

    J.print_red_prs(ctx.root, args.offline)
    branches = J.remote_branches(ctx.root, args.offline)
    if args.action == 'next' and args.id:
        r = by.get(args.id)
        action = {'needs_brief': 'brief', 'queued': 'build'}.get((r or {}).get('status'))
        if r and not action:
            return refuse(f'{args.id} is {r.get("status")}, not queued or needs_brief: nothing to pick up')
        why = J.not_ready(action or 'build', args.id, by, branches)
        if why:
            return refuse(why)
        print(J.build_steps(r) if action == 'build' else J.brief_steps(r, ctx.root, 'needs a brief'))
        return 0

    if args.action == 'next':
        kind, r, waiting = J.pick_next(rows, branches)
        if kind == 'job':
            print(J.build_steps(r))
        elif kind == 'brief':
            print(J.brief_steps(r, ctx.root))
        else:
            print('Nothing is ready. Waiting:\n  ' + '\n  '.join(waiting or ['(the queue is empty)']))
        return 0

    if args.action == 'view':
        out = ctx.root / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        on_branch = J.branch_rows(ctx.root, branches, args.offline, reg_dir, done=done_ids(rows))
        out.write_text(J.render_view(rows, read, branches, stamp, on_branch, root=ctx.root, ctx=ctx), encoding='utf-8')
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
    rounds = on_branch[jid].rounds   # not_ready has already refused a 4th review and a fix with no round
    print(J.branch_checks(ctx.root, f'job/{jid}', on_branch[jid].head, args.offline))
    title = (on_branch[jid].row or by.get(jid) or {}).get('title', '')
    print(J.review_steps(jid, rounds) if action == 'review' else J.fix_steps(jid, rounds, title))
    return 0
