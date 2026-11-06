"""The pipeline measured (W44, C41): one function per metric, each `(value, details, findings)`, and `record()`, which assembles them.

Everything is read from git at one commit (`main`: origin/main, or `head=`), the jobs registry at that commit and, online, `gh`; never the
working tree, so a dirty checkout or a job branch measures the same main. No model computes a number; a finding is a fact with its evidence.
The metric definitions and rules have one owner, `docs/AUDIT_METRICS.md`; the thresholds are `[audit]` in `warscape/repo.py` DEFAULTS.

A finding id is `<rule>:<subject>` (or `<rule>`), stable across runs: W45 suppresses and re-measures by it. `direction` says which way is worse
(`above`: more is worse; `below`: less is worse). A metric raises `Skip` to land in `skipped` (on purpose: offline, nothing to read), and any
other failure lands in `failed`, which is what makes the verb exit 1. Git and gh go through `run` (subprocess.run's shape) and the clock through
`now`, except the two reads that are the queue's own and take no runner: `policy.rows_at` and `jobq.remote_heads`.
"""
import json
import math
import re
import statistics
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import checks, ci
from . import jobq as J
from . import policy as P
from . import proposals as PR
from .repo import git_env, matches

VERSION = 1
LATER = re.compile(r'\*\*\s*later\b', re.I)
VTAG = re.compile(r'v(\d+)\.(\d+)\.(\d+)\Z')
PIN = re.compile(r'v?(\d+)\.(\d+)\.(\d+)')   # napoleon's [core] version carries the v
DAY = 86400


class Skip(Exception):
    """This metric was not measured, on purpose; the message is the reason."""


class Unreadable(ValueError):
    """The repository cannot be read: the verb exits 2."""


@dataclass
class Merge:
    sha: str
    when: int
    subject: str
    files: list
    kind: str
    job: str = ''


@dataclass
class Audit:
    """What the metrics share: the config, one read of main, the window, and the branches."""
    ctx: object
    run: object
    now: datetime
    offline: bool
    main: str = ''
    since: int = 0
    until: int = 0
    merges: list = field(default_factory=list)   # every first-parent commit of main, newest first
    window: list = field(default_factory=list)   # the ones in the window
    heads: dict = None                           # {branch: sha} of job/* and brief/*, or None when they could not be read
    heads_error: str = ''
    _rows: dict = None
    _tree: dict = None
    _sizes: dict = None

    @property
    def cfg(self):
        return self.ctx.config['audit']

    def git(self, *args):
        """stdout of a git command in the repo; raises Unreadable with its stderr."""
        p = self.run(['git', '-C', str(self.ctx.root), '-c', 'core.quotepath=off', *args], capture_output=True, text=True, encoding='utf-8',
                     errors='replace', timeout=300, env=git_env())
        if p.returncode != 0:
            raise Unreadable(f'git {args[0]} failed: {(p.stderr or p.stdout).strip()[:200]}')
        return p.stdout

    @property
    def rows(self):
        """{id: row} of the jobs registry at main."""
        if self._rows is None:
            self._rows = P.rows_at(self.main, P.settings(self.ctx.config), cwd=str(self.ctx.root))
        return self._rows

    @property
    def tree(self):
        """{path: bytes, or None for a gitlink, which has no size} of everything at main (one `ls-tree`)."""
        if self._tree is None:
            self._tree = {}
            for entry in self.git('ls-tree', '-r', '-l', '-z', self.main).split('\0'):
                meta, _, path = entry.partition('\t')
                if path:
                    size = meta.split()[-1]
                    self._tree[path] = None if size == '-' else int(size)
        return self._tree

    @property
    def sizes(self):
        """{path: bytes} of every file at main."""
        if self._sizes is None:
            self._sizes = {p: n for p, n in self.tree.items() if n is not None}
        return self._sizes

    def jobs(self):
        """The job merges in the window, newest first."""
        return [m for m in self.window if m.kind == 'job']

    def job_ids(self):
        """The ids merged in the window, newest merge first, each once (a job can have two merges: W38's row, then its work)."""
        return list(dict.fromkeys(m.job for m in self.jobs()))

    def blobs(self, paths):
        """{path: text or None} at main, in one call."""
        got = J._blobs(self.ctx.root, [f'{self.main}:{p}' for p in paths], self.run)
        return {p: got.get(f'{self.main}:{p}') for p in paths}

    def branch_refs(self):
        """{branch: sha} of the job/ and brief/ branches to read; Skip when this clone has none and cannot fetch them."""
        if self.heads is None:
            raise ValueError(self.heads_error)
        if not self.heads and self.offline:
            raise Skip('this clone has no origin job/ or brief/ branches and --offline fetches none')
        return self.heads


def finding(rule, metric, subject, severity, value, threshold, direction, evidence):
    return {'id': f'{rule}:{subject}' if subject else rule, 'metric': metric, 'subject': subject, 'severity': severity, 'value': value,
            'threshold': threshold, 'direction': direction, 'evidence': evidence}


def share(n, of):
    return round(n / of, 4) if of else None


def p90(values):
    """The nearest-rank 90th percentile."""
    v = sorted(values)
    return v[max(0, math.ceil(0.9 * len(v)) - 1)]


def hours(seconds):
    return round(seconds / 3600, 2)


# ------------------------------------------------------------------ reading main
def subject_kind(subject, prefix):
    """(kind, job id or '') of a first-parent subject: `<prefix><n>:` or `<prefix><n> ` is a job, but `<prefix><n> brief` is that job's brief (napoleon's
    early form); `brief`, `plan`, `meta`, `decide`, `release` start theirs."""
    m = re.match(rf'({re.escape(prefix)}\d+)[: ]', subject)
    if m:
        return ('brief', '') if re.match(r' brief\b', subject[m.end(1):]) else ('job', m.group(1))
    for kind in ('brief', 'plan', 'meta', 'decide', 'release'):
        if re.match(rf'{kind}\b', subject):
            return kind, ''
    return 'other', ''


def read_merges(a):
    """Every first-parent commit of main, newest first, each with the files it changed from its first parent. No rename detection: a move
    touches both names, as `git log -- <file>` counts them."""
    out = a.git('log', '--first-parent', '--diff-merges=first-parent', '--no-renames', '--name-only', '--format=%x01%H%x02%ct%x02%s', a.main)
    merges = []
    prefix = a.ctx.config['jobs']['id_prefix']
    for chunk in out.split('\x01')[1:]:
        head, _, names = chunk.partition('\n')
        sha, when, subject = head.split('\x02', 2)
        kind, job = subject_kind(subject, prefix)
        merges.append(Merge(sha, int(when), subject, [n for n in names.splitlines() if n], kind, job))
    return merges


def resolve_main(a, head):
    """The commit audited: `head`, or origin/main, else main, else HEAD. Raises Unreadable when none resolves."""
    for rev in ([head] if head else ['refs/remotes/origin/main', 'refs/heads/main', 'HEAD']):
        try:
            return a.git('rev-parse', '--verify', '--quiet', f'{rev}^{{commit}}').strip()
        except Unreadable:
            continue
    raise Unreadable(f'no commit to audit in {a.ctx.root}: {head or "origin/main, main and HEAD"} did not resolve')


def set_window(a, since):
    """Fill since, until and window. `since`: a YYYY-MM-DD (from that midnight, UTC), a commit (the first-parent commits after it) or None (the
    last `[audit] window_days` days)."""
    a.until = int(a.now.timestamp())
    if since is None:
        a.since = int((a.now - timedelta(days=a.cfg['window_days'])).timestamp())
    elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', since):
        a.since = int(datetime.strptime(since, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())   # a bad date is a ValueError: exit 2
    else:
        try:
            sha = a.git('rev-parse', '--verify', '--quiet', f'{since}^{{commit}}').strip()
        except Unreadable:
            raise ValueError(f'--since {since}: neither a YYYY-MM-DD nor a commit here') from None
        at = next((i for i, m in enumerate(a.merges) if m.sha == sha), None)
        a.since = int(a.git('show', '-s', '--format=%ct', sha).strip())
        if at is not None:
            a.window = a.merges[:at]
            return
    a.window = [m for m in a.merges if a.since <= m.when <= a.until]


def read_branches(a):
    """Fill heads, and online fetch those branches and main first (open question 2 of the brief: one fetch, never with --offline)."""
    try:
        heads = J.remote_heads(a.ctx.root, a.offline)
    except ValueError as e:
        a.heads_error = str(e)
        return
    a.heads = {b: s for b, s in heads.items() if b.startswith(('job/', 'brief/'))}
    if not a.offline and a.heads:
        p = a.run(['git', '-C', str(a.ctx.root), 'fetch', '-q', 'origin', '+refs/heads/job/*:refs/remotes/origin/job/*', '+refs/heads/brief/*:refs/remotes/origin/brief/*'],
                  capture_output=True, text=True, timeout=300, env=git_env())
        if p.returncode != 0:
            a.heads, a.heads_error = None, f'git fetch of the job and brief branches failed: {(p.stderr or "").strip()[:200]}'


# ------------------------------------------------------------------ the metrics
def hot_files(a):
    c = a.cfg
    jobs_dir, reg = a.ctx.config['jobs']['dir'], a.ctx.config['registries_dir']
    skip = [f'{jobs_dir}/**', f'{reg}/jobs/**', *c['hot_exempt']]
    jobs = a.jobs()
    counts = {}
    for m in jobs:
        for p in m.files:
            if not matches(p, skip):
                counts[p] = counts.get(p, 0) + 1
    out, gone = [], []
    for p, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        s = share(n, len(jobs))
        if s >= c['hot_file_share'] and n >= c['hot_file_min']:
            if p not in a.tree:                                 # already moved or deleted: a proposal about it would fix nothing
                gone.append(p)
                continue
            out.append(finding('hot_file', 'hot_files', p, 'high' if s >= c['hot_file_high'] else 'medium', s, c['hot_file_share'], 'above',
                               f'{p} was touched by {n} of {len(jobs)} job merges in the window ({s:.0%}).'))
    top = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20])
    return top, {'job_merges': len(jobs), 'files': len(counts), 'gone': gone}, out


def conflict_files(a):
    heads = a.branch_refs()
    refs = sorted(f'refs/remotes/origin/{b}' for b in heads)
    known = set(a.git('for-each-ref', '--format=%(refname)', 'refs/remotes/origin/').split())
    refs = [r for r in refs if r in known]
    merges = 0
    counts = {}
    if refs:
        log = a.git('log', '--merges', '--min-parents=2', '--max-parents=2', '--format=%H %ct %P', *refs, '--not', a.main)
        for line in log.splitlines():
            sha, when, p1, p2 = line.split()
            if not a.since <= int(when) <= a.until:
                continue
            merges += 1
            one = set(a.git('diff', '--name-only', '--no-renames', p1, sha).splitlines())
            two = set(a.git('diff', '--name-only', '--no-renames', p2, sha).splitlines())
            for p in one & two:
                counts[p] = counts.get(p, 0) + 1
    n = a.cfg['both_sides_min']
    hit = [(p, v) for p, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if v >= n]
    out = [finding('conflict_file', 'conflict_files', p, 'medium', v, n, 'above', f'{p} changed on both sides of {v} of the {merges} branch merges read.')
           for p, v in hit if p in a.tree]
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))), {'merges': merges, 'branches': len(refs), 'gone': [p for p, _ in hit if p not in a.tree]}, out


def job_lifetime(a):
    c = a.cfg
    heads = a.branch_refs()
    on_main = set(a.git('rev-list', a.main).split())
    last = {}
    for m in a.jobs():
        last.setdefault(m.job, m)                               # newest first: a job merged twice is measured to its last merge
    jobs, no_branch = {}, []
    for jid, m in last.items():
        if f'job/{jid}' not in heads:
            no_branch.append(jid)
            continue
        log = a.git('log', '--format=%ct %P', f'refs/remotes/origin/job/{jid}', '--not', a.main)
        commits = [l.split() for l in log.splitlines() if l.strip()]
        commits = [x for x in commits if int(x[0]) <= m.when]   # a commit after the merge is not the job's life
        if not commits:
            no_branch.append(jid)
            continue
        jobs[jid] = {'hours': hours(m.when - min(int(x[0]) for x in commits)), 'merges_from_main': sum(1 for x in commits if len(x) == 3 and x[2] in on_main),
                     'files': len(m.files)}
    out = []
    for jid, v in sorted(jobs.items(), key=lambda kv: J.num(kv[0])):
        if v['hours'] > c['max_job_hours']:
            out.append(finding('long_job', 'job_lifetime', jid, 'medium', v['hours'], c['max_job_hours'], 'above', f'{jid} took {v["hours"]} hours from its first commit to its merge.'))
        if v['files'] > c['max_job_files']:
            out.append(finding('wide_job', 'job_lifetime', jid, 'medium', v['files'], c['max_job_files'], 'above', f'{jid} merged {v["files"]} files in one squash commit.'))
    exposed = sum(1 for v in jobs.values() if v['merges_from_main'])
    s = share(exposed, len(jobs))
    if s is not None and s >= c['branch_exposure_share']:
        out.append(finding('branch_exposure', 'job_lifetime', '', 'medium', s, c['branch_exposure_share'], 'above', f'{exposed} of {len(jobs)} jobs merged main into their branch before merging ({s:.0%}).'))
    hs = [v['hours'] for v in jobs.values()]
    return jobs, {'jobs': len(jobs), 'no_branch': sorted(no_branch, key=J.num), 'median_hours': statistics.median(hs) if hs else None, 'p90_hours': p90(hs) if hs else None,
                  'exposed_share': s}, out


def work_mix(a):
    c = a.cfg
    ids = list(dict.fromkeys(m.job for m in a.merges if m.kind == 'job'))[:c['window_jobs']]
    phases = {}
    for jid in ids:
        ph = str(a.rows.get(jid, {}).get('phase'))
        phases[ph] = phases.get(ph, 0) + 1
    heavy = {str(p) for p in c['overhead_phases']}
    n = sum(v for k, v in phases.items() if k in heavy)
    s = share(n, len(ids)) if heavy else None
    out = []
    if s is not None and s > c['max_overhead_share']:
        out.append(finding('overhead_share', 'work_mix', '', 'medium', s, c['max_overhead_share'], 'above', f'{n} of the last {len(ids)} merged jobs are in the overhead phases ({s:.0%}).'))
    return s, {'jobs': len(ids), 'phases': dict(sorted(phases.items()))}, out


def gated_by(rows):
    """{id: [not-done rows that wait on it, directly or not]} for each not-done row."""
    live = {j: r for j, r in rows.items() if r.get('status') != 'done'}
    waits = {}
    for j, r in live.items():
        for d in r.get('depends_on', []):
            if d in live:
                waits.setdefault(d, set()).add(j)
    out = {}
    for j in live:
        seen, todo = set(), list(waits.get(j, ()))
        while todo:
            x = todo.pop()
            if x not in seen and x != j:
                seen.add(x)
                todo += waits.get(x, ())
        out[j] = sorted(seen, key=J.num)
    return out


def parked(a, lanes):
    """{id: hours} of the `progress` rows whose branch head is over `max_job_hours` old: claimed and left, so nobody is building them."""
    branch = {j: f'{"job" if a.rows[j].get("status") == "queued" else "brief"}/{j}' for j, v in lanes.items() if v == 'progress'}
    if not branch:
        return {}
    shas = sorted({a.heads[b] for b in branch.values()})
    when = dict(line.split() for line in a.git('show', '-s', '--format=%H %ct', *shas).splitlines())
    age = {j: hours(a.now.timestamp() - int(when[a.heads[b]])) for j, b in branch.items()}
    return {j: h for j, h in sorted(age.items(), key=lambda kv: J.num(kv[0])) if h > a.cfg['max_job_hours']}


def queue(a):
    c = a.cfg
    rows = a.rows
    if a.heads is None:
        raise ValueError(a.heads_error)
    branches = set(a.heads)
    done = {j for j, r in rows.items() if r.get('status') == 'done'}
    on_branch = J.branch_rows(a.ctx.root, branches, True, a.ctx.config['registries_dir'], done=done, run=a.run)
    # needs_pc is cleared for the lane: lane() asks whether THIS machine has the PC, and a finding must not depend on where the audit ran
    lanes = {r['id']: J.lane({**r, 'needs_pc': False}, rows, branches, on_branch)[0] for r in rows.values()}
    value = {k: sum(1 for v in lanes.values() if v == k) for k, _, _ in J.LANES}
    ready = [j for j, v in lanes.items() if v == 'ready']
    idle = parked(a, lanes)
    busy = value['progress'] - len(idle) + value['review'] + value['fix']
    pc = [j for j in ready if rows[j].get('needs_pc')]
    out = []
    if ready and not busy:
        left = f' ({", ".join(idle)} parked: no commit on the branch for over {c["max_job_hours"]} hours)' if idle else ''
        out.append(finding('idle_queue', 'queue', '', 'high', len(ready), 1, 'above', f'{len(ready)} rows are ready and nothing is in progress{left}, in review or in fix.'))
    s = share(len(pc), len(ready))
    if len(ready) >= c['pc_serial_min'] and s >= c['pc_serial_share']:
        out.append(finding('pc_serial', 'queue', '', 'medium', s, c['pc_serial_share'], 'above', f'{len(pc)} of {len(ready)} ready rows need the PC, which runs one at a time ({s:.0%}).'))
    gated = gated_by(rows)
    for j, g in sorted(gated.items(), key=lambda kv: (-len(kv[1]), J.num(kv[0]))):
        if len(g) >= c['chokepoint_fanout']:
            st = rows[j].get('status')
            out.append(finding('chokepoint', 'queue', j, 'high' if st == 'needs_brief' else 'medium', len(g), c['chokepoint_fanout'], 'above',
                               f'{j} ({st}) gates {len(g)} rows that are not done: {", ".join(g)}.'))
    return value, {'ready': sorted(ready, key=J.num), 'ready_needs_pc': len(pc), 'parked': idle, 'gating': {j: len(g) for j, g in gated.items() if g}}, out


def round_one_merge(text):
    """True when review.md has one round and it merged."""
    rounds = J.review_rounds(text)[1]
    v = P.verdict(rounds[0][1]) if len(rounds) == 1 else None
    return bool(v) and v.startswith('merge') and 'after fixes' not in v


def review_loop(a):
    c = a.cfg
    ids = [j for j in a.job_ids() if a.rows.get(j, {}).get('status') == 'done']
    jd = a.ctx.config['jobs']['dir']
    texts = a.blobs([f'{jd}/{j}/review.md' for j in ids])
    rounds, first, later = {}, 0, 0
    for j in ids:
        text = texts[f'{jd}/{j}/review.md']
        n = J.round_count(text)
        later += sum(1 for l in (text or '').splitlines() if LATER.search(l))
        if n:
            rounds[j] = n
            first += round_one_merge(text)
    s = share(first, len(rounds))
    out = []
    if s is not None and s < c['min_round1_merge']:
        out.append(finding('review_churn', 'review_loop', '', 'medium', s, c['min_round1_merge'], 'below', f'{first} of {len(rounds)} done jobs merged in round 1 ({s:.0%}).'))
    return s, {'rounds': dict(sorted(rounds.items(), key=lambda kv: J.num(kv[0]))), 'no_review': sorted(set(ids) - set(rounds), key=J.num), 'later': later}, out


def brief_cost(a):
    c = a.cfg
    jd = a.ctx.config['jobs']['dir']
    ids = a.job_ids()
    briefs = [a.sizes[f'{jd}/{j}/brief.md'] for j in ids if f'{jd}/{j}/brief.md' in a.sizes]
    reports = [a.sizes[f'{jd}/{j}/report.md'] for j in ids if f'{jd}/{j}/report.md' in a.sizes]
    mb = statistics.median(briefs) if briefs else None
    mr = statistics.median(reports) if reports else None
    ratio = round(mb / mr, 4) if mb and mr else None
    out = []
    if ratio is not None and ratio > c['max_brief_ratio']:
        out.append(finding('brief_heavy', 'brief_cost', '', 'medium', ratio, c['max_brief_ratio'], 'above', f'The median brief is {mb} bytes against a median report of {mr} bytes ({ratio}x).'))
    return ratio, {'median_brief': mb, 'median_report': mr, 'brief_merges': sum(1 for m in a.window if m.kind == 'brief'), 'job_merges': len(a.jobs())}, out


def startup_read(a):
    c = a.cfg
    names = ['CLAUDE.md', 'README.md', *c['startup_docs']]
    got = {p: a.sizes[p] for p in names if p in a.sizes}
    kb = round(sum(got.values()) / 1024, 2)
    out = []
    if kb > c['max_startup_kb']:
        out.append(finding('startup_heavy', 'startup_read', '', 'medium', kb, c['max_startup_kb'], 'above', f'A session starts by reading {kb} KB: {", ".join(got)}.'))
    return kb, {'bytes': got, 'missing': [p for p in names if p not in a.sizes]}, out


def doc_caps(a):
    c, dc = a.cfg, a.ctx.config['docs']
    at = c['doc_cap_share'] * dc['max_kb'] * 1024
    finished = [f"{a.ctx.config['jobs']['dir']}/**"]   # a brief of a finished job will not change: the doc_size gate still reads it, the finding has no one to act on it
    docs = [p for p in checks.living_docs(sorted(a.sizes), dc) if not matches(p, finished)]
    near = {p: a.sizes[p] for p in docs if a.sizes[p] >= int(at)}
    out = [finding('doc_cap', 'doc_caps', p, 'medium', round(n / 1024, 2), round(at / 1024, 2), 'above', f'{p} is {n / 1024:.1f} KB of the {dc["max_kb"]} KB cap.')
           for p, n in sorted(near.items())]
    return len(near), {'docs': len(docs), 'near': near}, out


def core_tags(a, sub):
    """The tag names of the core at `sub`: origin's when online, without a write, because a finding must not depend on how fresh this clone's store
    is; the local store's with --offline. Online, an origin that cannot be read fails the metric rather than falling back to a stale answer."""
    if a.offline:
        p = a.run(['git', '-C', str(sub), 'tag', '--list', 'v*'], capture_output=True, text=True, timeout=60, env=git_env())
        return (p.stdout or '').split() if p.returncode == 0 else []
    p = a.run(['git', '-C', str(sub), 'ls-remote', '--tags', 'origin', 'v*'], capture_output=True, text=True, timeout=60, env=git_env())
    if p.returncode != 0:
        raise ValueError(f'git ls-remote --tags in {sub.name}/ failed: {(p.stderr or "").strip()[:200]}; --offline reads the local store')
    return [line.rsplit('refs/tags/', 1)[-1] for line in p.stdout.splitlines()]   # an annotated tag's `^{}` line fails VTAG


def pin_lag(a):
    folder = a.ctx.config['ci']['core']
    if not folder:
        raise Skip('[ci] core is empty: this repo pins no core')
    pinned = PIN.fullmatch(a.ctx.config['core']['version'] or '')
    if not pinned:
        raise Skip('[core] version is not X.Y.Z or vX.Y.Z')
    sub = a.ctx.root / folder
    if not (sub / '.git').exists():
        raise Skip(f'{folder}/ is not checked out here: its tags cannot be read')
    tags = [tuple(map(int, m.groups())) for t in core_tags(a, sub) if (m := VTAG.fullmatch(t))]
    where = f'in the local {folder}/ store (--offline: origin may be newer)' if a.offline else f'at the origin of {folder}/'
    if not tags:
        raise Skip(f'no vX.Y.Z tag {where}')
    new, old = max(tags), tuple(map(int, pinned.groups()))
    n = a.cfg['max_pin_lag']
    # a newer major is behind by at least the limit, whatever its minor says
    lag = max(0, new[1] - old[1]) if new[0] == old[0] else n if new[0] > old[0] else 0
    newest = '.'.join(map(str, new))
    out = []
    if lag >= n:
        out.append(finding('pin_lag', 'pin_lag', '', 'medium', lag, n, 'above', f'The pin is {a.ctx.config["core"]["version"]} and the newest tag {where} is {newest}: {lag} minor versions behind.'))
    return lag, {'pinned': a.ctx.config['core']['version'], 'newest': newest, 'tags_from': 'local store' if a.offline else 'origin'}, out


def throughput(a):
    c = a.cfg
    length = a.until - a.since
    prior = [m for m in a.merges if a.since - length <= m.when < a.since]
    now = [m for m in a.window]
    count = lambda ms, k: sum(1 for m in ms if m.kind == k)
    days = max(length / DAY, 1 / 24)
    cur, old = (count(now, 'job') + count(now, 'brief')) / days, (count(prior, 'job') + count(prior, 'brief')) / days
    ratio = round(cur / old, 4) if old else None
    out = []
    if ratio is not None and ratio < c['slowdown_ratio']:
        out.append(finding('slowdown', 'throughput', '', 'medium', ratio, c['slowdown_ratio'], 'below', f'{cur:.2f} job and brief merges a day against {old:.2f} in the window before.'))
    kinds = dict.fromkeys(('job', 'brief', 'plan', 'meta', 'decide', 'release', 'other'), 0)
    for m in now:
        kinds[m.kind] += 1
    return ratio, {'days': round(days, 2), 'jobs': count(now, 'job'), 'briefs': count(now, 'brief'), 'prior_jobs': count(prior, 'job'), 'prior_briefs': count(prior, 'brief'),
                   'per_day': round(cur, 2), 'prior_per_day': round(old, 2), 'kinds': kinds}, out


def job_minutes(j):
    """A finished job's minutes, or None for one that did not run (a skipped job reports a near-zero time that would drag the median down)."""
    if j.get('conclusion') in (None, 'skipped', 'cancelled') or not j.get('started_at') or not j.get('completed_at'):
        return None
    t = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    return (t(j['completed_at']) - t(j['started_at'])).total_seconds() / 60


def ci_durations(a):
    if a.offline:
        raise Skip('--offline')
    c, cc = a.cfg, a.ctx.config['ci']
    seen = {}
    try:
        for wf in cc['workflows']:
            q = f'repos/{{owner}}/{{repo}}/actions/workflows/{wf}/runs?branch=main&status=completed&per_page={c["ci_runs"]}'
            for r in J._gh_json(a.run, a.ctx.root, q)['workflow_runs']:
                jobs = J._gh_json(a.run, a.ctx.root, f'repos/{{owner}}/{{repo}}/actions/runs/{r["id"]}/jobs?per_page=100')['jobs']
                for j in ci.required_jobs(cc, jobs):
                    if (m := job_minutes(j)) is not None:
                        seen.setdefault(j['name'], []).append(m)
    except (RuntimeError, KeyError, TypeError, AttributeError) as x:
        raise Skip(f'gh cannot be read: {x}') from None
    value = {k: round(statistics.median(v), 2) for k, v in sorted(seen.items())}
    out = []
    for name, m in value.items():
        limit = c['ci_check_minutes'].get(name, c['ci_check_default'])
        if m > limit:
            out.append(finding('slow_check', 'ci_durations', name, 'medium', m, limit, 'above', f'{name} took a median {m} minutes over its last {len(seen[name])} runs on main.'))
    return value, {'runs': {k: len(v) for k, v in sorted(seen.items())}}, out


FUNCS = {f.__name__: f for f in (hot_files, conflict_files, job_lifetime, work_mix, queue, review_loop, brief_cost, startup_read, doc_caps, pin_lag, throughput, ci_durations)}
METRICS = tuple(FUNCS)
SEVERITY = {'high': 0, 'medium': 1, 'low': 2}


def repo_name(a):
    """The origin URL's last name, so a worktree or a differently named clone records the same repo; the folder name without an origin."""
    try:
        url = a.git('remote', 'get-url', 'origin').strip().rstrip('/')
    except Unreadable:
        return a.ctx.root.name
    return re.sub(r'\.git\Z', '', re.split(r'[/:\\]', url)[-1])


def record(ctx, since=None, only=None, offline=False, now=None, run=subprocess.run, head=None):
    """The audit record (`docs/AUDIT_METRICS.md`) of `ctx`'s repository. `head`: measure this commit instead of origin/main (the calibration against an
    older number; pass a matching `now`). Raises Unreadable (a ValueError) when the repository cannot be read, ValueError on bad input."""
    bad = sorted(set(only or ()) - set(METRICS))
    if bad:
        raise ValueError(f'no metric {", ".join(bad)} (the metrics: {", ".join(METRICS)})')
    J.configure(ctx)
    a = Audit(ctx, run, now or datetime.now(timezone.utc), offline)
    try:
        a.git('rev-parse', '--git-dir')
    except (Unreadable, OSError) as e:
        raise Unreadable(f'{ctx.root} cannot be read as a git repository: {e}') from None
    read_branches(a)
    if not offline and not head:
        J.fetch_main(ctx.root, run)                           # failing leaves the last origin/main: the record names the sha it measured
    a.main = resolve_main(a, head)
    a.merges = read_merges(a)
    set_window(a, since)
    metrics, findings, skipped, failed = {}, [], [], []
    for name in METRICS:
        if only and name not in only:
            skipped.append({'metric': name, 'reason': 'not in --only'})
            continue
        try:
            value, details, got = FUNCS[name](a)
        except Skip as s:
            skipped.append({'metric': name, 'reason': str(s)})
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as e:
            failed.append({'metric': name, 'reason': f'{type(e).__name__}: {e}'})
        else:
            metrics[name] = {'value': value, 'details': details}
            findings += got
    findings.sort(key=lambda f: (SEVERITY[f['severity']], f['id']))
    day = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d')
    rec = {'version': VERSION, 'repo': repo_name(a), 'date': day(a.until), 'main': a.main,
           'window': {'since': day(a.since), 'until': day(a.until), 'job_merges': len(a.jobs())},
           'metrics': metrics, 'findings': findings, 'skipped': skipped, 'failed': failed}
    if PR.NAME in ctx.config['registries']:
        # the rows at the measured sha, not the working tree: a finding must not depend on where the audit ran
        cfg = P.settings(ctx.config)
        rows = P.dir_rows_at(a.main, cfg['proposals_dir'], cwd=ctx.root) or {}
        PR.overlay(rec, list(rows.values()), P.rows_at(a.main, cfg, cwd=ctx.root), {m.job: day(m.when) for m in reversed(a.merges) if m.kind == 'job'}, a.cfg['reraise_margin'])
    return rec


# ------------------------------------------------------------------ output
def finding_line(f):
    return f'{f["severity"]:<6} {f["id"]}: {f["evidence"]}'


def cell(v):
    return str(v).replace('|', '\\|').replace('\n', ' ')


def remeasured_line(m):
    return f'- `{cell(m["finding"])}`: {m["proposal"]} {m["verdict"]}, {cell(m["baseline"])} then, {cell(m["value"])} now'


def render_md(rec):
    """The record as Markdown: a pure function of the JSON, so it is generated and never edited."""
    w = rec['window']
    out = [f'# Audit {rec["date"]}: {rec["repo"]}', '',
           f'Generated by `wsc audit` from the JSON beside this file; never edit it. Main `{rec["main"]}`, window {w["since"]} to {w["until"]}, {w["job_merges"]} job merges.', '',
           f'## Findings ({len(rec["findings"])})', '']
    if rec['findings']:
        out += ['| Id | Severity | Value | Threshold | Evidence |', '| --- | --- | --- | --- | --- |']
        out += [f'| `{cell(f["id"])}` | {f["severity"]} | {cell(f["value"])} | {cell(f["threshold"])} ({f["direction"]}) | {cell(f["evidence"])} |' for f in rec['findings']]
    else:
        out.append('None.')
    out += ['', '## Metrics', '', '| Metric | Value | Details |', '| --- | --- | --- |']
    out += [f'| {k} | {cell(json.dumps(m["value"], sort_keys=True))} | {cell(json.dumps(m["details"], sort_keys=True))} |' for k, m in rec['metrics'].items()]
    for title, key in (('Not measured', 'skipped'), ('Failed', 'failed')):
        if rec[key]:
            out += ['', f'## {title}', ''] + [f'- {s["metric"]}: {s["reason"]}' for s in rec[key]]
    if rec.get('suppressed'):
        out += ['', '## Suppressed', ''] + [f'- `{cell(s["finding"])}`: {s["proposal"]} {s["status"]}, {cell(s["baseline"])} then, {cell(s["value"])} now' for s in rec['suppressed']]
    if rec.get('remeasured'):
        out += ['', '## Re-measured', ''] + [remeasured_line(m) for m in rec['remeasured']]
    return '\n'.join(out) + '\n'


def write_pair(rec, json_path):
    """Write the record at `json_path` and its Markdown beside it."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(rec, indent=1, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    json_path.with_suffix('.md').write_text(render_md(rec), encoding='utf-8', newline='\n')
    return json_path


def record_path(folder, date):
    """`<folder>/AUDIT_<date>.json`, or `_2`, `_3`, ... when that day already has a record."""
    n, path = 1, folder / f'AUDIT_{date}.json'
    while path.exists():
        n += 1
        path = folder / f'AUDIT_{date}_{n}.json'
    return path
