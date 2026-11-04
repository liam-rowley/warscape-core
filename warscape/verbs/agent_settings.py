"""
Purpose: Add or remove one allowed command rule in a Claude Code settings file (.claude/settings.json) without a one-off ask, only when the repo's `[agent_settings] safe` patterns allow it: the guard holds Liam's judgement, the verb never edits a hook or a deny entry.
Usage: wsc agent-settings allow "<rule>" ["<rule>" ...] [--file .claude/settings.json]  |  wsc agent-settings remove "<rule>" [...] [--file ...]   (exit 0 done or already so, 1 the write failed (the file is unchanged), 2 refused: the failed check, and Liam decides)
When: a session keeps asking for the same read-only command (git status, a read-only wsc verb, gh pr view); configure the safe list in wsc.toml [agent_settings] first.
Verb: agent-settings

A narrower rule is a safe pattern extended by whole words (`Bash(git diff --stat:*)` under `Bash(git diff:*)`, never `Bash(git diffx:*)`)
with no write- or run-capable flag among the added words (WRITE_FLAGS: `--output`, `--ext-diff`, `-c` ...); `[agent_settings]
exact_only = true` allows only the patterns themselves. A deny with a `*` inside is read broadly (glob_overlaps). The file is
`<repo>/.claude/<name>.json` once every link is resolved: `.claude` a symlink or junction, `--file` naming another `.claude` folder, the
file or its `.bak` a link, or a hard-linked file, refuses. Each writing run replaces `<name>.json.bak` (through a temporary file, never
through a link) with the file as it was before that run, so two runs keep only the second original.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

NAME = 'agent-settings'
HELP = "allowed command rules in .claude/settings.json, only within wsc.toml [agent_settings] safe patterns"

RULE = re.compile(r'^([A-Za-z][A-Za-z0-9_]*)\((.+)\)$')
META = re.compile(r'[;&|<>`$\\\n\r]|\$\(')
_replace = os.replace   # tests replace it to prove a failing write leaves the file
# Flags that make a read command write a file or run a program: git diff/log/show --output writes any file, --ext-diff and --textconv
# run a configured program, -c/--config set any config (an alias or core.pager included), grep -O opens a pager, --exec/-x run a
# command, --upload-pack and kin name a program, -o is an output file for many tools. Refused among the words a rule adds to its safe
# pattern: a long flag also as `--flag=value`, a short one also with its value attached (`-cfoo=bar`). A flag inside the safe pattern
# itself is Liam's choice.
WRITE_FLAGS = ('--output', '--output-directory', '--ext-diff', '--textconv', '--config', '--config-env', '--exec', '--exec-path',
               '--upload-pack', '--receive-pack', '--extcmd', '--tool', '--template', '--open-files-in-pager', '--git-dir', '--work-tree',
               '-c', '-O', '-o', '-x')


class Refused(Exception):
    pass


def add_arguments(p):
    sub = p.add_subparsers(dest='settings_cmd', required=True)
    for name, h in (('allow', 'add rules to permissions.allow (each a safe pattern, or one extended by whole words without a write flag)'),
                    ('remove', 'take rules out of permissions.allow')):
        s = sub.add_parser(name, help=h)
        s.add_argument('rules', nargs='+', metavar='rule')
        s.add_argument('--file', help="the settings file (default <repo>/.claude/settings.json); must resolve to a .json directly in this "
                                      "repo's own .claude folder with no link on the way. Each writing run replaces <file>.bak with the "
                                      'file as it was before the run: two runs keep only the second original')


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
    """True when every command the rule `inner` matches is matched by `outer` (both parsed). A prefix covers only whole-word
    extensions: `git diff` covers `git diff --stat`, never `git diffx` (another command)."""
    ot, op, opre = outer
    it, ip, ipre = inner
    if ot != it:
        return False
    if not opre:
        return not ipre and ip == op
    return ip == op or (ip.startswith(op) and (op[-1:].isspace() or ip[len(op)].isspace()))


def overlaps(a, b):
    return covers(a, b) or covers(b, a)


def write_flag(words):
    """The first of `words` that is a WRITE_FLAGS flag (also `--flag=value` and `-cvalue`), else None."""
    for w in words:
        for f in WRITE_FLAGS:
            if w == f or (f.startswith('--') and w.startswith(f + '=')) or (not f.startswith('--') and not w.startswith('--') and w.startswith(f)):
                return w
    return None


def glob_overlaps(deny, rule):
    """A deny whose command has a `*` inside (`Bash(git * --force)`) is not compared literally: it overlaps any rule of its tool whose
    command starts with the deny's text before the first `*`, or (a prefix rule) whose command that text starts with."""
    dt, dp, _ = deny
    rt, rp, rpre = rule
    if dt != rt or '*' not in dp:
        return False
    lead = dp.split('*', 1)[0]
    return rp.startswith(lead) or (rpre and lead.startswith(rp))


def check_allow(rule, safe, deny, exact_only=False):
    """Returns when `rule` may be added; else raises Refused with the one-line reason (the failed check)."""
    p = parse(rule)
    if p is None:
        raise Refused(f'{rule!r} is not a command rule Tool(command) or Tool(command:*): a bare tool or another form is broader than any safe pattern')
    tool, spec, pre = p
    if not spec.strip() or '*' in spec or META.search(spec):
        raise Refused(f'{rule!r}: wildcards inside the command, shell operators and substitutions are never added (only a trailing :*)')
    if exact_only:
        if rule.strip() not in [s.strip() for s in safe]:
            raise Refused(f'{rule!r} is not one of the [agent_settings] safe patterns (exact_only = true; safe: {", ".join(safe) or "none"})')
    else:
        outer = [sp for sp in (parse(s) for s in safe) if sp and covers(sp, p)]
        if not outer:
            raise Refused(f'{rule!r} is not a safe pattern of [agent_settings] or one extended by whole words (safe: {", ".join(safe) or "none"})')
        closest = max(outer, key=lambda o: len(o[1]))
        bad = write_flag(spec[len(closest[1]):].split())
        if bad:
            raise Refused(f'{rule!r} adds {bad!r}, a flag that writes a file or runs a program (agent_settings.WRITE_FLAGS)')
    for d in deny:
        dp = parse(d)
        if dp and glob_overlaps(dp, p):
            raise Refused(f'{rule!r} may be matched by the deny rule {d!r} (a wildcard inside a deny is read broadly)')
        if dp and overlaps(dp, p):
            raise Refused(f'{rule!r} is covered by the deny rule {d!r}')
        if dp is None and RULE.sub(r'\1', d) == tool and '(' not in d:
            raise Refused(f'{rule!r}: the deny list denies {tool} outright ({d!r})')


def _real(p):
    return os.path.normcase(os.path.realpath(p))


def _is_link(p):
    return p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())


def _target(args, ctx):
    """The settings file: a .json directly in <root>/.claude after every link is resolved, the folder, the file and its .bak no link."""
    root = Path(ctx.root)
    home = root / '.claude'
    f = Path(args.file) if args.file else home / 'settings.json'
    if not f.is_absolute():
        f = root / f
    if f.parent.name != '.claude' or f.suffix != '.json':
        raise Refused(f'{f} is not a .json file directly in a .claude folder: this verb writes only there')
    real_home = os.path.join(os.path.realpath(root), '.claude')
    if _is_link(home) or _real(home) != os.path.normcase(real_home):
        raise Refused(f'{home} is a link (a symlink or junction) to {os.path.realpath(home)}: this verb writes only into the repo\'s own .claude folder')
    if _real(f.parent) != os.path.normcase(real_home):
        raise Refused(f'{f} is not in this repo\'s own .claude folder ({home}): refused')
    bak = f.with_name(f.name + '.bak')
    for p in (f, bak):
        if _is_link(p):
            raise Refused(f'{p} is a link: refused')
        if p.exists() and not p.is_file():
            raise Refused(f'{p} is not a regular file: refused')
        if p.exists() and os.stat(p).st_nlink > 1:
            raise Refused(f'{p} has {os.stat(p).st_nlink} hard links: a write would reach another name: refused')
        if _real(p) != os.path.normcase(os.path.join(real_home, p.name)):
            raise Refused(f'{p} resolves to {os.path.realpath(p)}, outside the repo\'s own .claude folder: refused')
    return f


def _indent(text):
    m = re.search(r'^([ \t]+)\S', text, re.M)
    if not m:
        return 2
    ws = m.group(1)
    return '\t' if ws.startswith('\t') else len(ws)


def _temp(folder, name, data):
    fd, tmp = tempfile.mkstemp(prefix=name + '.', suffix='.tmp', dir=str(folder))
    with os.fdopen(fd, 'wb') as h:
        h.write(data)
    return tmp


def _write(f, text, old):
    """Atomic: a temporary file in the same folder, then a replace. The old bytes go to <name>.bak the same way (a replace of the name,
    so a link put there since the check is replaced, never written through), once per run."""
    temps = []
    try:
        temps.append(_temp(f.parent, f.name, text.encode('utf-8')))
        if old is not None:
            temps.append(_temp(f.parent, f.name + '.bak', old))
            _replace(temps[-1], str(f) + '.bak')
            temps.pop()
        _replace(temps[0], f)
        temps.pop()
    finally:
        for t in temps:
            try:
                os.unlink(t)
            except OSError:
                pass


def run(args, ctx):
    cfg = ctx.config['agent_settings']
    safe = list(cfg['safe'])
    exact_only = cfg.get('exact_only', False)
    try:
        if not safe:
            raise Refused('[agent_settings] is not configured in wsc.toml (no safe patterns): nothing changed')
        if not isinstance(exact_only, bool):
            raise Refused(f'[agent_settings] exact_only must be true or false, not {exact_only!r}')
        f = _target(args, ctx)
        raw = f.read_bytes() if f.exists() else None
        try:
            old = raw.decode('utf-8') if raw is not None else None
            d = json.loads(old) if old is not None else {}
        except ValueError as e:
            raise Refused(f'{f} is not valid JSON in UTF-8 ({e}): fix it by hand') from None
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
                check_allow(rule, safe, deny, exact_only)
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
        text = json.dumps(d, indent=ind, ensure_ascii=False).replace('\n', nl) + (nl if old is None or old.endswith('\n') else '')
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
        _write(f, text, raw)
    except OSError as e:
        print(f'agent-settings: the write failed ({e}): {f} is unchanged', file=sys.stderr)
        return 1
    verb = 'added to' if args.settings_cmd == 'allow' else 'removed from'
    print(f'agent-settings: {", ".join(changed)} {verb} permissions.allow in {f}' + (f' (the old file is {f.name}.bak)' if raw is not None else ''))
    return 0
