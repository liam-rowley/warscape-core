"""The session-trailer rule (warscape/trailer.py), moved from napoleon-remastered tests/test_claude_hook.py (napoleon J62)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from warscape.trailer import commit_lacks_trailer  # noqa: E402

SID = 'bc89f81a-9222-45d4-9010-6ec5f16df11f'


class Trailer(unittest.TestCase):
    def test_a_commit_without_the_flag_lacks_it(self):
        self.assertTrue(commit_lacks_trailer('git commit -m x', SID))
        self.assertTrue(commit_lacks_trailer('git -C /r commit -m x && git push', SID))
        self.assertTrue(commit_lacks_trailer('git -c core.hooksPath=/dev/null commit -q -m x', SID))

    def test_only_the_trailer_flag_counts_not_a_line_in_the_message(self):
        self.assertTrue(commit_lacks_trailer(f'git commit -m "x\n\nClaude-Session: {SID}"', SID))
        self.assertFalse(commit_lacks_trailer(f'git commit -m x --trailer "Claude-Session: {SID}"', SID))
        self.assertFalse(commit_lacks_trailer(f"git commit -m x --trailer 'Claude-Session: {SID}' --trailer 'Co-Authored-By: c'", SID))
        self.assertFalse(commit_lacks_trailer(f'git commit -m x --trailer=Claude-Session:{SID}', SID))

    def test_another_sessions_id_does_not_count(self):
        self.assertTrue(commit_lacks_trailer('git commit -m x --trailer "Claude-Session: other"', SID))
        self.assertTrue(commit_lacks_trailer(f'git commit -m x --trailer "Claude-Session: {SID}-2"', SID))

    def test_not_a_commit_no_session_or_the_rule_off(self):
        self.assertFalse(commit_lacks_trailer('git status', SID))
        self.assertFalse(commit_lacks_trailer('git commit-tree abc', SID))
        self.assertFalse(commit_lacks_trailer('echo git commit', ''))
        self.assertFalse(commit_lacks_trailer('git commit -m x', SID, ''))

    def test_a_game_may_name_its_own_trailer(self):
        self.assertFalse(commit_lacks_trailer(f'git commit -m x --trailer "Agent-Session: {SID}"', SID, 'Agent-Session'))
        self.assertTrue(commit_lacks_trailer(f'git commit -m x --trailer "Claude-Session: {SID}"', SID, 'Agent-Session'))


if __name__ == '__main__':
    unittest.main()
