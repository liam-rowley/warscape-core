"""The fixture game's hook module: one example of each hook name (warscape/hooks.py)."""


def brief_problems(ctx, jid, row, text):
    return [] if 'Fixture rule' in text else ['fixture rule: the brief does not say "Fixture rule"']


def queue_problems(ctx, rows, files):
    return [f'fixture queue rule: row {r["id"]} is blocked without a hook-approved reason' for r in rows if r.get('status') == 'blocked']


def policy_problems(ctx, facts):
    if facts['kind'] != 'job':
        return []
    return [f'fixture policy rule: {p} is in a forbidden folder' for p in facts['changed'] if p.startswith('forbidden/')]


def view_panel(ctx):
    return '<p class="muted">fixture panel</p>'


def summary(ctx, rows, read):
    n = sum(1 for r in rows if read('jobs/' + r['id'] + '/brief.md') is not None)
    return f'{n} fixture briefs'
