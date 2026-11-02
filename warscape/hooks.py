"""Hook modules: the one place a game repo adds rules to the job pipeline without patching the core (napoleon J62).

A repo lists Python files in `wsc.toml` `[jobs] hooks`; each is loaded by path and may define any of these names (all optional):

    brief_problems(ctx, jid, row, text) -> [str]    extra rules for one brief (not run for ids in the legacy file's `brief_hooks`)
    queue_problems(ctx, rows, files) -> [str]       extra rules for the whole queue (`rows`: the jobs rows; `files`: ctx.files())
    policy_problems(ctx, facts) -> [str]            extra pull-request rules (`wsc policy`; the facts: warscape/policy.py `collect_facts`)
    view_panel(ctx) -> str                          an HTML paragraph for the top of the status page ('' for none)
    summary(ctx, rows, read) -> str                 text appended to the last line of `wsc jobs check` (`read(path)` -> text or None)

Five names, no more: a general game-gates mechanism is backlog B1, and these hooks are its first consumer. A hook module is library code:
it needs no tool header, runs inside the `wsc` process and may import from the repo it lives in.
"""
import importlib.util
import sys
from pathlib import Path

NAMES = ('brief_problems', 'queue_problems', 'policy_problems', 'view_panel', 'summary')


def load(root, paths):
    """The modules for the repo-relative `paths`, in order. A missing file, or a module that defines a name that looks like a hook but is
    not one of NAMES, is an error (a typo would otherwise switch a rule off silently)."""
    mods = []
    for p in paths:
        f = Path(root) / p
        if not f.is_file():
            raise ValueError(f'wsc.toml [jobs] hooks: {p} does not exist')
        spec = importlib.util.spec_from_file_location(f'wsc_hook_{f.stem}', f)
        m = importlib.util.module_from_spec(spec)
        keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # no __pycache__ in the repo being checked (`git add -A` would commit it)
        try:
            spec.loader.exec_module(m)
        finally:
            sys.dont_write_bytecode = keep
        if not any(hasattr(m, n) for n in NAMES):
            raise ValueError(f'{p} is listed in [jobs] hooks but defines none of: {", ".join(NAMES)}')
        mods.append(m)
    return mods
