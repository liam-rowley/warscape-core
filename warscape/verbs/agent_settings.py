"""
Purpose: Add or remove one allowed command rule in a Claude Code settings file (.claude/settings.json) without a one-off ask, only when the repo's `[agent_settings] safe` patterns allow it: the guard holds Liam's judgement, the verb never edits a hook or a deny entry.
Usage: wsc agent-settings allow "<rule>" ["<rule>" ...] [--file .claude/settings.json]  |  wsc agent-settings remove "<rule>" [...] [--file ...]   (exit 0 done or already so, 1 the write failed (the file is unchanged), 2 refused: the failed check, and Liam decides)
When: a session keeps asking for the same read-only command (git status, a read-only wsc verb, gh pr view); configure the safe list in wsc.toml [agent_settings] first.
Verb: agent-settings
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

NAME = 'agent-settings'
HELP = "allowed command rules in .claude/settings.json, only within wsc.toml [agent_settings] safe patterns"

RULE = re.compile(r'^([A-Za-z][A-Za-z0-9_]*)\((.+)\)$')
META = re.compile(r'[;&|<>`$\\\n\r]|\$\(')
_replace = os.replace   # tests replace it to prove a failing write leaves the file


class Refused(Exception):
    pass


def add_arguments(p):
    sub = p.add_subparsers(dest='settings_cmd', required=True)
    for name, h in (('allow', 'add rules to permissions.allow (each a safe pattern or narrower)'), ('remove', 'take rules out of permissions.allow')):
        s = sub.add_parser(name, help=h)
        s.add_argument('rules', nargs='+', metavar='rule')
        s.add_argument('--file', help='the settings file (default <repo>/.claude/settings.json); must be in a .claude folder')


def parse(rule):
    """(tool, prefix, is_prefix) of a command rule `Tool(cmd)` or `Tool(cmd:*)`; None when it is not one this verb handles."""
    m = RULE.match(rule.strip())
    if not m:
        return None
    tool, spec = m.group(1), m.group(2)
    if spec.endswith(':*'):
        return tool, spec[:-2], True
    return tool, spec, False


def covers(outer, inner):
    """True when every command the rule `inner` matches is matched by `outer` (both parsed)."""
    ot, op, opre = outer
    it, ip, ipre = inner
    if ot != it:
        return False
    if not opre:
        return not ipre and ip == op
    return ip.startswith(op)


def overlaps(a, b):
    return covers(a, b) or covers(b, a)


def check_allow(rule, safe, deny):
    """None when `rule` may be added; else the one-line reason (the failed check)."""
    p = parse(rule)
    if p is None:
        raise Refused(f'{rule!r} is not a command rule Tool(command) or Tool(command:*): a bare tool or another form is broader than any safe pattern')
    tool, spec, pre = p
    if not spec.strip() or '*' in spec or META.search(spec):
        raise Refused(f'{rule!r}: wildcards inside the command, shell operators and substitutions are never added (only a trailing :*)')
    safe_p = [(s, parse(s)) for s in safe]
    if not any(sp and covers(sp, p) for _, sp in safe_p):
        raise Refused(f'{rule!r} is not a safe pattern of [agent_settings] or narrower than one (safe: {", ".join(safe) or "none"})')
    for d in deny:
        dp = parse(d)
        if dp and overlaps(dp, p):
            raise Refused(f'{rule!r} is covered by the deny rule {d!r}')
        if dp is None and RULE.sub(r'\1', d) == tool and '(' not in d:
            raise Refused(f'{rule!r}: the deny list denies {tool} outright ({d!r})')


def _target(args, ctx):
    f = Path(args.file) if args.file else Path(ctx.root) / '.claude' / 'settings.json'
    if not f.is_absolute():
        f = Path(ctx.root) / f
    if f.parent.name != '.claude' or f.suffix != '.json':
        raise Refused(f'{f} is not a .json file directly in a .claude folder: this verb writes only there')
    if f.is_symlink() or f.parent.is_symlink():
        raise Refused(f'{f} is a link: refused')
    return f


def _indent(text):
    m = re.search(r'^([ \t]+)\S', text, re.M)
    if not m:
        return 2
    ws = m.group(1)
    return '\t' if ws.startswith('\t') else len(ws)


def _write(f, text, old):
    """Atomic: a temporary file in the same folder, then a replace; the old file kept as <name>.bak (once per run)."""
    fd, tmp = tempfile.mkstemp(prefix=f.name + '.', suffix='.tmp', dir=str(f.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as h:
            h.write(text)
        if old is not None:
            shutil.copyfile(f, str(f) + '.bak')
        _replace(tmp, f)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run(args, ctx):
    safe = list(ctx.config['agent_settings']['safe'])
    try:
        if not safe:
            raise Refused('[agent_settings] is not configured in wsc.toml (no safe patterns): nothing changed')
        f = _target(args, ctx)
        old = f.read_text(encoding='utf-8') if f.exists() else None
        try:
            d = json.loads(old) if old is not None else {}
        except ValueError as e:
            raise Refused(f'{f} is not valid JSON ({e}): fix it by hand') from None
        if not isinstance(d, dict) or not isinstance(d.get('permissions', {}), dict):
            raise Refused(f'{f}: the top level and "permissions" must be objects')
        perms = d.setdefault('permissions', {})
        allow = perms.get('allow', [])
        deny = perms.get('deny', [])
        if not isinstance(allow, list) or not isinstance(deny, list):
            raise Refused(f'{f}: permissions.allow and permissions.deny must be lists')
        changed = []
        for rule in args.rules:
            if args.settings_cmd == 'allow':
                if rule in allow:
                    print(f'agent-settings: {rule} is already in permissions.allow')
                    continue
                check_allow(rule, safe, deny)
                allow.append(rule)
            else:
                if rule not in allow:
                    where = ' (it is a deny entry: deny entries are Liam\'s)' if rule in deny else ''
                    raise Refused(f'{rule!r} is not in permissions.allow{where}')
                allow.remove(rule)
            changed.append(rule)
        if not changed:
            return 0
        perms['allow'] = allow
        ind = _indent(old) if old else 2
        nl = '\r\n' if old and '\r\n' in old else '\n'
        text = json.dumps(d, indent=ind, ensure_ascii=False).replace('\n', nl) + (nl if old is None or old.endswith(('\n',)) else '')
        before = json.loads(old) if old else {}
        after = json.loads(text)
        b2, a2 = dict(before), dict(after)
        bp, ap = dict(b2.pop('permissions', {})), dict(a2.pop('permissions', {}))
        bp.pop('allow', None)
        ap.pop('allow', None)
        if b2 != a2 or bp != ap:   # a guard on this code: nothing but permissions.allow may change
            raise Refused('internal check: a key other than permissions.allow would change: nothing written')
    except Refused as e:
        print(f'agent-settings: refused: {e}. Liam decides anything outside the safe list.', file=sys.stderr)
        return 2
    try:
        _write(f, text, old)
    except OSError as e:
        print(f'agent-settings: the write failed ({e}): {f} is unchanged', file=sys.stderr)
        return 1
    verb = 'added to' if args.settings_cmd == 'allow' else 'removed from'
    print(f'agent-settings: {", ".join(changed)} {verb} permissions.allow in {f}' + (f' (the old file is {f.name}.bak)' if old is not None else ''))
    return 0
