"""The answer round (W45, C41; docs/PROPOSALS.md owns the row, the states and the round): a finding of `wsc audit` becomes a proposal with options, a recommendation
and an apply recipe per option; the owner answers the open ones in one message; `decide/<date>` applies it. The verb is warscape/verbs/proposals.py.

What `wsc audit` adds to a record is `overlay` here: it reads rows and returns nothing, so warscape/audit.py stays the only reader of git. Who may write an answer is
warscape/policy.py (`proposal_problems`), because a pull request is judged with its base's rules. "Applied" is computed (`applied`), never stored: a stored one goes stale.
"""
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import policy as pp
from .registry import load_from_config, mint_id

NAME = 'proposals'
PREFIX = 'P'
ANSWERED, LIVE = pp.ANSWERED, ('open', 'accepted')
SEVERITY = {'high': 0, 'medium': 1, 'low': 2}
JOB_RECIPE = ('title', 'description', 'phase', 'model', 'needs_pc', 'semver', 'depends_on')
DECISION_RECIPE = ('decision', 'reversible')
AUTO_BY = pp.AUTO_BY
RECORD = re.compile(r'AUDIT_(\d{4}-\d\d-\d\d)(?:_(\d+))?\.json\Z')


def declared(ctx):
    return NAME in ctx.config['registries']


def load(ctx):
    """{name: Registry} of the three registries a round writes."""
    return {n: r for n, r in load_from_config(ctx.config, ctx.root).items() if n in (NAME, 'jobs', 'decisions')}


def today_utc():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def yymmdd(date):
    return date[2:].replace('-', '')


def option_of(row, key):
    return next((o for o in row.get('options') or [] if o.get('key') == key), None)


def chosen(row):
    """The option the row's answer took, or None."""
    return option_of(row, (row.get('answer') or {}).get('option'))


def applied(row, jobs):
    """An accepted row whose change has happened: a decision at once, a job when its row is `done`."""
    o = chosen(row)
    if row.get('status') != 'accepted' or not o:
        return False
    return o.get('kind') == 'decision' or (o.get('kind') == 'job' and (jobs.get(row.get('job')) or {}).get('status') == 'done')


def sign(direction):
    return 1 if direction == 'above' else -1


def worse(value, baseline, direction, margin):
    """Worse than the baseline by more than `margin`, a share of it; on a baseline of 0, any worsening."""
    return sign(direction) * (value - baseline) > margin * abs(baseline)


def better(value, baseline, direction, margin):
    gain = sign(direction) * (baseline - value)
    return gain > 0 and gain >= margin * abs(baseline)


def newest_by_finding(rows):
    out = {}
    for r in sorted((r for r in rows if r.get('finding')), key=lambda r: (r.get('date', ''), r.get('id', ''))):
        out[r['finding']] = r
    return out


def verdict(row, rec, finding, jobs, merged, margin):
    """moved, not_moved, gone, too_soon or unmeasured for an applied row against a record. A metric not measured leaves no finding, and that absence is never a fix."""
    metric = row.get('metric')
    if metric not in rec['metrics']:
        return 'unmeasured'
    when = (row.get('answer') or {}).get('date') if chosen(row).get('kind') == 'decision' else merged.get(row.get('job'))
    if not when or rec['window']['since'] < when:   # the window still holds what came before the change
        return 'too_soon'
    subject = row['finding'].partition(':')[2]
    if subject and subject in (rec['metrics'][metric].get('details') or {}).get('gone', ()):
        return 'gone'
    b = row['baseline']
    if finding is None or better(finding['value'], b['value'], b['direction'], margin):
        return 'moved'
    return 'not_moved'


def overlay(rec, rows, jobs, merged, margin):
    """Add `suppressed` and `remeasured` to the record `rec`, each only when it has entries, so an older record renders as it did. `rows`: proposal rows; `jobs`: {id: job
    row}; `merged`: {job id: the date it merged}."""
    last = newest_by_finding(rows)
    keep, suppressed = [], []
    for f in rec['findings']:
        r = last.get(f['id'])
        if r and r.get('status') in ('declined', 'deferred') and not worse(f['value'], r['baseline']['value'], r['baseline']['direction'], margin):
            suppressed.append({'proposal': r['id'], 'finding': f['id'], 'status': r['status'], 'baseline': r['baseline']['value'], 'value': f['value']})
        else:
            keep.append(f)
    rec['findings'] = keep
    by_id = {f['id']: f for f in keep}
    measured = []
    for r in sorted(rows, key=lambda r: r.get('id', '')):
        if r.get('finding') and applied(r, jobs):
            f = by_id.get(r['finding'])
            measured.append({'proposal': r['id'], 'finding': r['finding'], 'baseline': r['baseline']['value'], 'value': f['value'] if f else None,
                             'verdict': verdict(r, rec, f, jobs, merged, margin)})
    if suppressed:
        rec['suppressed'] = suppressed
    if measured:
        rec['remeasured'] = measured


def recipe_problems(rid, o):
    k, recipe = o.get('kind'), o.get('recipe') or {}
    need = {'job': JOB_RECIPE, 'decision': DECISION_RECIPE}.get(k, ())
    if need and not recipe:
        return [f'{rid}: option {o.get("key")!r} ({k}) has no recipe']
    out = [f'{rid}: option {o.get("key")!r}: the recipe has no {n}' for n in need if n not in recipe]
    if k == 'decision' and recipe.get('reversible', 'yes') not in ('yes', 'no'):
        out.append(f'{rid}: option {o.get("key")!r}: reversible is not yes or no')
    return out


def check(ctx):
    """`wsc proposals check`, in the `jobs` gate: what a row of any status must hold. A skeleton fails until it is filled, on purpose."""
    if not declared(ctx):
        return []
    regs = load(ctx)
    rows = regs[NAME].rows
    errs, live = [], {}
    for r in rows:
        rid, opts = r['id'], r.get('options') or []
        keys = [o.get('key') for o in opts]
        if r['status'] == 'open':
            if not opts:
                errs.append(f'{rid}: an open proposal needs options (fill the skeleton)')
            if r.get('recommended') not in keys:
                errs.append(f'{rid}: recommended {r.get("recommended")!r} is not one of its options')
        if len(set(keys)) != len(keys):
            errs.append(f'{rid}: two options share a key')
        for o in opts:
            errs += recipe_problems(rid, o)
        if r.get('finding') and r['status'] in LIVE:
            live.setdefault(r['finding'], []).append(rid)
        a = r.get('answer')
        if a:
            if not (ctx.root / a['record']).is_file():
                errs.append(f'{rid}: answer.record {a["record"]} does not exist')
            if not option_of(r, a['option']):
                errs.append(f'{rid}: answer.option {a["option"]!r} is not one of its options')
        if r.get('decision') and r['decision'] not in regs['decisions'].by_id():
            errs.append(f'{rid}: decision {r["decision"]} is not a row')
        if r.get('job') and r['job'] not in regs['jobs'].by_id():
            errs.append(f'{rid}: job {r["job"]} is not a row')
    errs += [f'{f}: two live proposals, {", ".join(ids)}' for f, ids in sorted(live.items()) if len(ids) > 1]
    return errs


def newest_record(folder):
    """The newest `AUDIT_<date>[_n].json` in `folder`, or None."""
    got = [(m.group(1), int(m.group(2) or 1), f) for f in Path(folder).glob('AUDIT_*.json') if (m := RECORD.match(f.name))]
    return max(got, key=lambda t: t[:2])[2] if got else None


def read_record(ctx, path=None):
    """(the record, its repo-relative path). `path` or the newest committed one."""
    f = Path(path) if path else newest_record(ctx.root / ctx.config['audit']['dir'])
    if not f or not f.is_file():
        raise ValueError(f'no record in {ctx.config["audit"]["dir"]}: run wsc audit --record first, or pass --record PATH')
    f = f if f.is_absolute() else ctx.root / f
    try:
        rel = f.resolve().relative_to(ctx.root.resolve()).as_posix()
    except ValueError:
        rel = f.as_posix()
    return json.loads(f.read_text(encoding='utf-8')), rel


def skeleton(reg, f, record, today, follows=None, question=None):
    rid = mint_id(PREFIX, set(reg.by_id()), today=yymmdd(today))
    row = {'id': rid, 'date': today, 'kind': 'finding', 'finding': f['id'], 'metric': f['metric'], 'class': f['id'].partition(':')[0],
           'question': question or f'What should change? {f["evidence"]}',
           'baseline': {'record': record, 'value': f['value'], 'threshold': f['threshold'], 'direction': f['direction'], 'severity': f['severity'], 'evidence': f['evidence']},
           'options': [], 'status': 'open'}
    if follows:
        row['reraises'] = follows
    reg.add(row)
    return rid


def draft(ctx, record=None, today=None):
    """A skeleton per finding of the record with no live row; returns the new ids. A finding still in the record past a decline follows the row it comes back from."""
    today = today or today_utc()
    rec, rel = read_record(ctx, record)
    regs = load(ctx)
    reg = regs[NAME]
    last = newest_by_finding(reg.rows)
    made = []
    for f in rec['findings']:
        r = last.get(f['id'])
        if r and r['status'] in LIVE:
            continue
        made.append(skeleton(reg, f, rel, today, follows=r['id'] if r else None))
    if made:
        reg.save()
    return made


def cell(v):
    return ' '.join(str(v).split()).replace('|', '\\|')


def ask(ctx, limit):
    """The question table, severity first."""
    rows = [r for r in load(ctx)[NAME].rows if r['status'] == 'open']
    if not rows:
        return 'Nothing is waiting: no open proposals.'
    rows.sort(key=lambda r: (SEVERITY.get((r.get('baseline') or {}).get('severity'), 9), r['id']))
    out = ['| Id | Question | Options | Recommended | Tag |', '| --- | --- | --- | --- | --- |']
    for r in rows[:limit]:
        opts = '; '.join(f'`{o["key"]}` {o["summary"]}' for o in r.get('options') or [])
        out.append(f'| {r["id"]} | {cell(r["question"])} | {cell(opts)} | `{r.get("recommended", "")}` | {r.get("tag", "")} |')
    if len(rows) > limit:
        out += ['', f'{len(rows) - limit} more open, left out by --max.']
    return '\n'.join(out)


def next_job_id(prefix, rows, taken):
    nums = [int(i[len(prefix):]) for i in [*rows, *taken] if re.fullmatch(rf'{re.escape(prefix)}\d+', str(i))]
    return max(nums, default=0) + 1


def apply_rows(regs, picks, by, record, today, who, prefix, dprefix, taken):
    """Write each (row, option) in `picks`: the status and the answer, one decision row for the round and a job row per job option. `decision` and `job` go on the rows."""
    reg, jobs, decisions = regs[NAME], regs['jobs'], regs['decisions']
    accepted = [(r, o) for r, o in picks if o['kind'] in ('decision', 'job')]
    did = None
    if accepted:
        did = mint_id(dprefix, set(decisions.by_id()), today=yymmdd(today))
        said = ' '.join(f'{r["id"]}: {(o.get("recipe") or {}).get("decision") or o["summary"]}' for r, o in accepted)
        final = 'no' if any((o.get('recipe') or {}).get('reversible') == 'no' for _, o in accepted) else 'yes'
        decisions.add({'id': did, 'date': today, 'who': who, 'decision': f'**Accepted in the answers of {today} ({record}).** {said}', 'reversible': final})
    n = next_job_id(prefix, jobs.by_id(), taken)
    for r, o in picks:
        change = {'status': {'decision': 'accepted', 'job': 'accepted', 'defer': 'deferred', 'none': 'declined'}[o['kind']],
                  'answer': {'by': by, 'date': today, 'record': record, 'option': o['key']}}
        if o['kind'] in ('decision', 'job'):
            change['decision'] = did
        if o['kind'] == 'job':
            jid, n = f'{prefix}{n}', n + 1
            recipe = o['recipe']
            jobs.add({'id': jid, 'description': f'{recipe["description"]} Proposal {r["id"]}, {did}.', 'title': recipe['title'], 'phase': recipe['phase'], 'status': 'needs_brief',
                      'model': recipe['model'], 'needs_pc': recipe['needs_pc'], 'semver': recipe['semver'], 'depends_on': list(recipe['depends_on'])})
            change['job'] = jid
        reg.set(r['id'], change)
    for x in (decisions, jobs, reg):
        x.save()


def answer(ctx, answers, quote, branch, today=None, taken=()):
    """The owner's answers (`{id: option key or "recommended"}`), quoted verbatim in the ANSWERS record, written on a `decide/` checkout. Everything is checked before anything
    is written. Returns the ANSWERS path."""
    today = today or today_utc()
    record = pp.answers_path(ctx.config['audit']['dir'], branch)
    if not record:
        raise ValueError(f'{branch} is not decide/<YYYY-MM-DD>[-<n>]: answers land only on a decide/ branch (C41)')
    if (ctx.root / record).exists():
        raise ValueError(f'{record} already holds a round of answers and is never rewritten: answer on {pp.next_decide(branch)}')
    owner = ctx.config['jobs']['text'].get('owner')
    if not owner:
        raise ValueError('[jobs.text] owner is not set: an answer must name who gave it')
    regs = load(ctx)
    rows = regs[NAME].by_id()
    picks = []
    for rid, key in answers.items():
        r = rows.get(rid)
        if r is None:
            raise ValueError(f'no proposal {rid}')
        if r['status'] != 'open':
            raise ValueError(f'{rid} is {r["status"]}, not open')
        o = option_of(r, r.get('recommended') if key == 'recommended' else key)
        if o is None:
            raise ValueError(f'{rid} has no option {key!r}')
        picks.append((r, o))
    apply_rows(regs, picks, owner, record, today, owner, ctx.config['jobs']['id_prefix'], ctx.config['policy']['decision_prefix'], taken)
    f = ctx.root / record
    f.parent.mkdir(parents=True, exist_ok=True)
    said = '\n'.join(f'> {line}'.rstrip() for line in quote.strip('\n').splitlines())
    table = '\n'.join(f'| {r["id"]} | {cell(r["question"])} | `{o["key"]}` | {cell(o["summary"])} |' for r, o in picks)
    f.write_text(f'# Answers of {today}\n\n{owner}, verbatim:\n\n{said}\n\n| Id | Question | Answer | Meaning |\n| --- | --- | --- | --- |\n{table}\n', encoding='utf-8', newline='\n')
    return record


def answer_auto(ctx, branch, today=None, taken=()):
    """Accept each open row of an `[audit] auto_apply` class at its recommendation, on a plan/ branch (C41). A tagged row is always asked. Returns the ids."""
    if not branch.startswith('plan/'):
        raise ValueError(f'{branch} is not a plan/ branch: --auto runs on plan/ (a decide/ branch carries the owner\'s answers)')
    today = today or today_utc()
    regs = load(ctx)
    classes = ctx.config['audit']['auto_apply']
    picks = [(r, o) for r in regs[NAME].rows if r['status'] == 'open' and r['class'] in classes and not r.get('tag') and (o := option_of(r, r.get('recommended')))]
    by_record = {}
    for r, o in picks:
        by_record.setdefault(r['baseline']['record'], []).append((r, o))
    for record, group in by_record.items():
        apply_rows(regs, group, AUTO_BY, record, today, f'{AUTO_BY} ([audit] auto_apply, C41)', ctx.config['jobs']['id_prefix'], ctx.config['policy']['decision_prefix'], taken)
    return [r['id'] for r, _ in picks]


def delta(new, old):
    return f'{new - old:+g}' if isinstance(new, (int, float)) else 'unknown'


def close(ctx, rec, record, today=None):
    """Apply a record's `remeasured` list, and close an open row whose finding left a measured metric. `moved` and `gone` close; `not_moved` closes and drafts the row that
    follows it, the delta in its question; `too_soon` and `unmeasured` leave the row. Returns {'closed': ids, 'drafted': ids}."""
    today = today or today_utc()
    regs = load(ctx)
    reg = regs[NAME]
    rows = reg.by_id()
    closed, drafted = [], []
    for m in rec.get('remeasured') or []:
        r, v = rows.get(m['proposal']), m['verdict']
        if r is None or r['status'] != 'accepted' or v in ('too_soon', 'unmeasured'):
            continue
        reg.set(r['id'], {'status': 'closed', 'outcome': v})
        closed.append(r['id'])
        if v == 'not_moved':
            b = r['baseline']
            f = {'id': r['finding'], 'metric': r['metric'], 'value': m['value'] if m['value'] is not None else b['value'], 'threshold': b['threshold'], 'direction': b['direction'],
                 'severity': b['severity'], 'evidence': b['evidence']}
            q = f'{r["id"]} was applied and {r["finding"]} did not move: {b["value"]} to {f["value"]} ({delta(f["value"], b["value"])}). What now?'
            drafted.append(skeleton(reg, f, record, today, follows=r['id'], question=q))
    now = {f['id'] for f in rec['findings']} | {s['finding'] for s in rec.get('suppressed') or []}
    for r in list(reg.rows):
        if r['status'] == 'open' and r['id'] not in drafted and r.get('finding') and r.get('metric') in rec['metrics'] and r['finding'] not in now:
            reg.set(r['id'], {'status': 'closed', 'outcome': 'gone'})
            closed.append(r['id'])
    if closed or drafted:
        reg.save()
    return {'closed': closed, 'drafted': drafted}


def view_html(ctx):
    """The Waiting on the owner section of `jobs view`: the open proposals in `ask`'s order, or '' when none are."""
    if ctx is None or not declared(ctx):
        return ''
    rows = [r for r in load(ctx)[NAME].rows if r['status'] == 'open']
    if not rows:
        return ''
    rows.sort(key=lambda r: (SEVERITY.get((r.get('baseline') or {}).get('severity'), 9), r['id']))
    e = html.escape
    who = ctx.config['jobs']['text'].get('owner') or 'the owner'
    items = ''.join(f'<li><code>{e(r["id"])}</code> {e(r["question"])}' + (f' <b>{e(r["tag"])}</b>' if r.get('tag') else '') + '</li>' for r in rows)
    return (f'<section class="lane" id="lane-owner"><h2>Waiting on {e(who)} <span class="muted">({len(rows)})</span></h2>'
            f'<p class="muted">open proposals: <code>wsc proposals ask</code> prints the table to answer</p><ul>{items}</ul></section>')
