"""The fixture game's one `gates`-stage module: no file under docs/ says TODO (warscape/gatemods.py)."""
from warscape.gates import Result

NAME = 'no_todo'


def run(ctx):
    bad = [p for p in ctx.files() if p.startswith('docs/') and 'TODO' in (ctx.root / p).read_text(encoding='utf-8', errors='replace')]
    return Result(NAME, 'error' if bad else 'ok', f'{len(bad)} docs say TODO' if bad else 'no doc says TODO', bad)
