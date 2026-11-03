"""The fixture game's pipeline rules: one gate module with the `jobs`, `policy` and `view` stages (warscape/gatemods.py), the shape a game
moving off the five hook names takes (core W13). Each rule and message is the one its hook had."""
from warscape.gates import Result

NAME = 'fixture_rules'
STAGES = ('jobs', 'policy', 'view')


def _jobs(ctx):
    errs = [f'{jid}: brief: fixture rule: the brief does not say "Fixture rule"' for jid, row, text in ctx.briefs() if 'Fixture rule' not in text]
    errs += [f'fixture queue rule: row {r["id"]} is blocked without a hook-approved reason' for r in ctx.rows if r.get('status') == 'blocked']
    n = sum(1 for r in ctx.rows if ctx.read('jobs/' + r['id'] + '/brief.md') is not None)
    return Result(NAME, 'error' if errs else 'ok', f'{n} fixture briefs', errs)


def _policy(ctx):
    f = ctx.facts
    errs = [] if f['kind'] != 'job' else [f'fixture policy rule: {p} is in a forbidden folder' for p in f['changed'] if p.startswith('forbidden/')]
    return Result(NAME, 'error' if errs else 'ok', f'{len(errs)} fixture policy problems', errs)


def _view(ctx):
    return Result(NAME, 'ok', 'fixture panel', html='<p class="muted">fixture panel</p>')


def run(ctx):
    return {'jobs': _jobs, 'policy': _policy, 'view': _view}[ctx.stage](ctx)
