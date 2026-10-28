"""`wsc` command-line dispatcher. Verbs are modules with NAME, HELP, add_arguments(parser) and run(args, ctx):
the core's own in `warscape/verbs/`, plus any a repo lists in `wsc.toml` [cli] verb_dirs (game-specific verbs, same contract)."""
import argparse
import importlib
import importlib.util
import sys
from pathlib import Path

from . import core_version
from .registry import RegistryError
from .repo import ConfigError, Ctx

CORE_VERBS = ('reg', 'find', 'gates')


def _load_verbs(ctx):
    mods = [importlib.import_module(f'warscape.verbs.{n}') for n in CORE_VERBS]
    for d in (ctx.config['cli']['verb_dirs'] if ctx else []):
        for f in sorted((ctx.root / d).glob('*.py')):
            if f.name.startswith('_'):
                continue
            spec = importlib.util.spec_from_file_location(f'wsc_verb_{f.stem}', f)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            if not all(hasattr(m, a) for a in ('NAME', 'HELP', 'add_arguments', 'run')):
                raise ConfigError(f'{f}: a verb module needs NAME, HELP, add_arguments and run')
            if m.NAME in {x.NAME for x in mods}:
                raise ConfigError(f'{f}: verb {m.NAME!r} already exists')
            mods.append(m)
    return mods


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument('--root')
    known, _ = pre.parse_known_args(argv)
    ctx, err = None, None
    try:
        ctx = Ctx.load(known.root)
    except ConfigError as e:
        err = e
    try:
        verbs = _load_verbs(ctx)
    except ConfigError as e:
        print(f'wsc: {e}', file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog='wsc', description='warscape-core CLI: registries, lookup and gates for the Total War remasters.')
    ap.add_argument('--root', help='repo root (default: nearest folder upwards with a wsc.toml)')
    ap.add_argument('--version', action='version', version=f'warscape-core {core_version()}')
    sub = ap.add_subparsers(dest='verb', required=True, metavar='{' + ','.join(v.NAME for v in verbs) + '}')
    table = {}
    for v in verbs:
        p = sub.add_parser(v.NAME, help=v.HELP, description=(v.__doc__ or '').strip() or v.HELP,
                           formatter_class=argparse.RawDescriptionHelpFormatter)
        v.add_arguments(p)
        table[v.NAME] = v
    args = ap.parse_args(argv)
    if ctx is None:
        print(f'wsc: {err}', file=sys.stderr)
        return 2
    try:
        return table[args.verb].run(args, ctx) or 0
    except (RegistryError, ConfigError, ValueError) as e:
        print(f'wsc {args.verb}: {e}', file=sys.stderr)
        return 2
    except BrokenPipeError:   # `wsc find x | head` must not traceback
        return 0
