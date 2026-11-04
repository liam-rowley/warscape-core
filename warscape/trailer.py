"""The session-trailer rule for a Claude Code PreToolUse hook: a `git commit` must name the session that makes it.

Moved from napoleon-remastered `tools/claude_hook.py` (napoleon D21, J20, J62). The pull-request policy (`wsc policy`) tells a job's builder from
its reviewer by the trailer (`[policy] session_trailer`), so a commit without it is refused before it is made. Only the `--trailer` flag counts:
a `Claude-Session:` line in a `-m` body is a trailer only in the message's last paragraph, and napoleon J44's 19 commits put it one paragraph
above `Co-Authored-By:`, so git (and the policy) read no session at all.

A game's hook entry point (its own game-folder rules, the JSON protocol on stdin and stdout) stays in the game repo and calls `commit_lacks_trailer`.

`message_problem` is the same rule for a git `commit-msg` hook (`.githooks/commit-msg`, run through `wsc policy --commit-msg <file>`): it reads the
message the way `policy` reads a pushed commit (`git interpret-trailers --parse` and `%(trailers:key=...)` are one parser), so the hook and the
policy cannot disagree, and it holds in every session, not only one started in the repo folder.
"""
import re
import subprocess

from .repo import git_env

# `git` where a command starts: the line's start, after a separator, after a shell's command-string flag (with or without its opening quote), behind
# `VAR=value` words and the wrappers that run their arguments. An argument is no command, so `echo git commit` and `grep "git commit" docs` are no commits.
GIT = re.compile(r'''(?:^|[;&|({\n`]|\$\(|(?:\s-\w*c|\s-Command|\s/c|\beval)\s+["']?)\s*'''
                 r'''(?:(?:\w+=(?:"[^"]*"|'[^']*'|\S*)|sudo|env|command|exec|time|nohup|if|then|else|elif|do|while|until|!)\s+)*'''
                 r'''(?:[^\s;&|"'`]*\\)?git(?:\.exe)?(?=[ \t])''')
# One shell word: quoted and bare pieces, `$(...)` and backticks whole. A separator, a newline or an unmatched quote ends it.
WORD = re.compile(r'''[ \t]+((?:"[^"]*"|'[^']*'|\$\([^()]*\)|`[^`]*`|[^\s"'`;&|()<>])+)''')
FLAGS = {'-p', '-P', '--paginate', '--no-pager', '--no-replace-objects', '--bare', '--literal-pathspecs', '--glob-pathspecs', '--noglob-pathspecs',
         '--icase-pathspecs', '--no-optional-locks', '--exec-path'}
TAKES_NEXT = {'-c', '-C', '--git-dir', '--work-tree', '--namespace', '--config-env'}   # the option's value is the next word
TAKES_EQUALS = ('--git-dir=', '--work-tree=', '--namespace=', '--exec-path=', '--super-prefix=', '--config-env=')


def _unquote(word):
    return re.sub(r'''"([^"]*)"|'([^']*)\'''', lambda m: m.group(1) or m.group(2) or '', word)


def _runs_commit(text, at, aliases):
    """True when the git arguments in `text` from `at` on name `commit`: past the global options, the subcommand is `commit` or an alias of it.
    `aliases`: {lower-case name: value}, what `-c alias.<name>=<value>` set so far (an alias used is removed, so a loop ends)."""
    while m := WORD.match(text, at):
        word, at = _unquote(m.group(1)), m.end()
        if word in FLAGS or word.startswith(TAKES_EQUALS):
            continue
        if word not in TAKES_NEXT:
            if word == 'commit':
                return True
            value = aliases.pop(word.lower(), None)
            if value is None:
                return False
            return _has_commit(value[1:], aliases) if value.startswith('!') else _runs_commit(f' {value}', 0, aliases)
        m = WORD.match(text, at)
        if not m:
            return False
        at = m.end()
        key, eq, value = _unquote(m.group(1)).partition('=')
        if word == '-c' and eq and key.lower().startswith('alias.'):
            aliases[key[6:].lower()] = value
    return False


def _has_commit(cmd, aliases=None):
    """True when the shell line `cmd` runs git's `commit`. A later `git` starts with the aliases of its own `-c` options only, as git does."""
    return any(_runs_commit(cmd, m.end(), dict(aliases or {})) for m in GIT.finditer(cmd))


def commit_lacks_trailer(cmd, session_id, trailer='Claude-Session'):
    """True when `cmd` runs `git commit` without `--trailer "<trailer>: <session_id>"`. False when it is no commit, when the hook was given no
    session id, or when the repo switched the rule off (empty trailer name). A hook passes the command as typed (W36): git's global options may
    stand before the subcommand, and an alias defined in the command (`git -c alias.ci="commit -q" ci`) is followed, through other aliases and
    `!` shell aliases. An alias from the user's gitconfig cannot be known from the command string and stays unseen (fails open: the commit-msg hook
    and `policy` still read the commit), as does a path-qualified `/usr/bin/git`."""
    sid = str(session_id or '').strip()
    if not trailer or not sid or not _has_commit(cmd):
        return False
    return not re.search(r'--trailer[\s=]+["\']?' + re.escape(trailer) + r':\s*' + re.escape(sid) + r'(?![\w-])', cmd)


SCISSORS = '# ------------------------ >8 ------------------------'


def _strip_comments(text):
    """The message as git keeps it: nothing from the scissors line on, and no `#` comment lines (an editor leaves them in the file the hook reads)."""
    out = []
    for line in text.splitlines():
        if line.startswith(SCISSORS):
            break
        if not line.startswith('#'):
            out.append(line)
    return chr(10).join(out) + chr(10)


def message_trailers(text):
    """`[(key, value)]` of the trailer block of a commit message, read by `git interpret-trailers --parse`."""
    p = subprocess.run(['git', 'interpret-trailers', '--parse'], input=_strip_comments(text).encode('utf-8'), capture_output=True, env=git_env())
    if p.returncode != 0:
        raise RuntimeError('git interpret-trailers failed: ' + p.stderr.decode('utf-8', 'replace').strip())
    out = []
    for line in p.stdout.decode('utf-8', 'replace').splitlines():
        k, _, v = line.partition(':')
        out.append((k.strip(), v.strip()))
    return out


def message_problem(text, trailer='Claude-Session'):
    """What is wrong with the commit message `text`, or None: it has no `<trailer>:` trailer with a non-empty value. None when `trailer` is empty
    (the repo switched the rule off). A trailer is a line of the message's last paragraph (git's rule), so a `Claude-Session:` line one paragraph
    above `Co-Authored-By:` (napoleon J44) is no trailer and is refused."""
    if not trailer:
        return None
    vals = [v for k, v in message_trailers(text) if k.lower() == trailer.lower()]
    if any(vals):
        return None
    why = 'its value is empty' if vals else 'git reads a trailer only in the last paragraph, with the other trailers such as Co-Authored-By'
    return (f'the commit message has no `{trailer}:` trailer ({why}). Put `{trailer}: <session id>` in the last paragraph, '
            f'with `Co-Authored-By:`, or use `git commit --trailer "{trailer}: <session id>"`. A human commit bypasses once with `git commit --no-verify`.')
