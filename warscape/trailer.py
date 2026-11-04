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

COMMIT = re.compile(r'''(?<![\w./-])git(?:\.exe)?(?:\s+-[cC]\s+(?:"[^"]*"|'[^']*'|\S+))*\s+commit(?![\w-])''')


def commit_lacks_trailer(cmd, session_id, trailer='Claude-Session'):
    """True when `cmd` runs `git commit` without `--trailer "<trailer>: <session_id>"`. False when it is no commit, when the hook was given no
    session id, or when the repo switched the rule off (empty trailer name)."""
    sid = str(session_id or '').strip()
    if not trailer or not sid or not COMMIT.search(cmd):
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
