"""The session-trailer rule for a Claude Code PreToolUse hook: a `git commit` must name the session that makes it.

Moved from napoleon-remastered `tools/claude_hook.py` (napoleon D21, J20, J62). The pull-request policy (`wsc policy`) tells a job's builder from
its reviewer by the trailer (`[policy] session_trailer`), so a commit without it is refused before it is made. Only the `--trailer` flag counts:
a `Claude-Session:` line in a `-m` body is a trailer only in the message's last paragraph, and napoleon J44's 19 commits put it one paragraph
above `Co-Authored-By:`, so git (and the policy) read no session at all.

A game's hook entry point (its own game-folder rules, the JSON protocol on stdin and stdout) stays in the game repo and calls `commit_lacks_trailer`.
"""
import re

COMMIT = re.compile(r'''(?<![\w./-])git(?:\.exe)?(?:\s+-[cC]\s+(?:"[^"]*"|'[^']*'|\S+))*\s+commit(?![\w-])''')


def commit_lacks_trailer(cmd, session_id, trailer='Claude-Session'):
    """True when `cmd` runs `git commit` without `--trailer "<trailer>: <session_id>"`. False when it is no commit, when the hook was given no
    session id, or when the repo switched the rule off (empty trailer name)."""
    sid = str(session_id or '').strip()
    if not trailer or not sid or not COMMIT.search(cmd):
        return False
    return not re.search(r'--trailer[\s=]+["\']?' + re.escape(trailer) + r':\s*' + re.escape(sid) + r'(?![\w-])', cmd)
