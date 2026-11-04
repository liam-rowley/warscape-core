"""Host tests for warscape/worktrees.py (W26): stale worktree registrations, merged worktrees and a .git above the repository, on real
`git worktree add` repositories in a temp folder with a local bare origin; and `wsc jobs worktrees [--prune]`."""
import contextlib
import io
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from _util import git as _git  # noqa: E402
from warscape import jobq, worktrees as W  # noqa: E402
from warscape.repo import DEFAULTS  # noqa: E402


def git(cwd, *args):
    p = _git(cwd, *args, check=False)
    if p.returncode:
        raise AssertionError(f'git {" ".join(args)} in {cwd} failed ({p.returncode}):\n{p.stdout}{p.stderr}')
    return p.stdout.strip()


def row(jid, status):
    return {'id': jid, 'title': 't', 'status': status, 'phase': 1, 'model': 'sonnet', 'needs_pc': False, 'depends_on': []}


ROWS = [row('J1', 'done'), row('J2', 'queued'), row('J5', 'queued'), row('J6', 'queued'), row('J7', 'queued'), row('J9', 'queued')]


def same(a, b):
    return Path(a).resolve() == Path(b).resolve()


class Worktrees(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name).resolve()
        self.origin = self.d / 'origin.git'
        git(self.d, 'init', '-q', '--bare', str(self.origin))
        self.repo = self.d / 'p1' / 'p2' / 'repo'
        self.repo.parent.mkdir(parents=True)
        git(self.d, 'clone', '-q', str(self.origin), str(self.repo))
        git(self.repo, 'commit', '-q', '--allow-empty', '-m', 'm1')
        git(self.repo, 'push', '-q', 'origin', 'main')
        # job/J5: its folder is deleted (gone); job/J1: the row is done (merged); job/J9: work of its own, pushed (live)
        self.wt = {j: self.d / 'wt' / j for j in ('J5', 'J1', 'J9')}
        for j, p in self.wt.items():
            git(self.repo, 'worktree', 'add', '-q', '-b', f'job/{j}', str(p), 'origin/main')
        git(self.wt['J9'], 'commit', '-q', '--allow-empty', '-m', 'work')
        git(self.wt['J9'], 'push', '-q', 'origin', 'job/J9')
        git(self.wt['J1'], 'commit', '-q', '--allow-empty', '-m', 'done work')
        git(self.wt['J1'], 'push', '-q', 'origin', 'job/J1')
        shutil.rmtree(self.wt['J5'])

    def branches(self):
        return jobq.remote_branches(self.repo, False)

    def test_registered_reads_porcelain(self):
        reg = W.registered(self.repo)
        self.assertTrue(same(reg[0][0], self.repo))
        self.assertEqual(reg[0][1], 'main')
        by = {Path(p).name: (b, why) for p, b, why in reg[1:]}
        self.assertEqual(by['J9'], ('job/J9', None))
        self.assertEqual(by['J5'][0], 'job/J5')
        self.assertTrue(by['J5'][1])   # git marks it prunable

    def test_gone_merged_and_never_the_main_worktree(self):
        gone, merged = W.stale(self.repo, ROWS, self.branches())
        self.assertEqual([Path(p).name for p in gone], ['J5'])
        self.assertEqual([Path(p).name for p in merged], ['J1'])
        self.assertFalse(any(same(p, self.repo) for p in gone + merged))

    def test_merged_rules_brief_ancestor_and_gone_upstream(self):
        brief = self.d / 'wt' / 'b6'
        git(self.repo, 'worktree', 'add', '-q', '-b', 'brief/J6', str(brief), 'origin/main')
        git(brief, 'commit', '-q', '--allow-empty', '-m', 'brief')
        git(brief, 'push', '-q', '-u', 'origin', 'brief/J6')
        rows = [r if r['id'] != 'J6' else row('J6', 'needs_brief') for r in ROWS]
        self.assertNotIn('b6', [Path(p).name for p in W.stale(self.repo, rows, self.branches())[1]])
        self.assertIn('b6', [Path(p).name for p in W.stale(self.repo, ROWS, self.branches())[1]])   # past needs_brief: merged
        anc = self.d / 'wt' / 'anc'
        git(self.repo, 'worktree', 'add', '-q', '-b', 'topic', str(anc), 'origin/main')   # an ancestor of origin/main
        self.assertIn('anc', [Path(p).name for p in W.stale(self.repo, rows, self.branches())[1]])
        git(self.repo, 'push', '-q', 'origin', '--delete', 'brief/J6')   # its remote branch gone after a fetch --prune
        git(self.repo, 'fetch', '-q', '--prune', 'origin')
        self.assertIn('b6', [Path(p).name for p in W.stale(self.repo, rows, self.branches())[1]])

    def test_prune_removes_only_the_missing_folders(self):
        self.assertEqual(W.prune(self.repo), (1, None))
        names = [Path(p).name for p, _, _ in W.registered(self.repo)[1:]]
        self.assertEqual(sorted(names), ['J1', 'J9'])   # merged J1 is reported, never removed
        self.assertTrue(self.wt['J1'].is_dir())
        self.assertEqual(W.prune(self.repo), (0, None))

    def test_prune_failure_is_a_reason_not_an_exception(self):
        removed, err = W.prune(self.d / 'no' / 'such')
        self.assertEqual(removed, 0)
        self.assertTrue(err)

    def test_stray_git_above_the_main_root(self):
        self.assertIsNone(W.stray_git(self.repo, ceiling=self.d))
        linked = self.repo / '.claude' / 'worktrees' / 'x'
        git(self.repo, 'worktree', 'add', '-q', '-b', 'x', str(linked), 'origin/main')
        self.assertIsNone(W.stray_git(linked, ceiling=self.d))   # a linked worktree's own repository is not "above"
        (self.d / 'p1' / '.git').mkdir()                          # a .git folder two levels above the main root
        self.assertTrue(same(W.stray_git(self.repo, ceiling=self.d), self.d / 'p1'))
        self.assertTrue(same(W.stray_git(linked, ceiling=self.d), self.d / 'p1'))
        (self.d / 'p1' / 'p2' / '.git').write_text('gitdir: elsewhere\n', encoding='utf-8')   # a .git file counts too
        self.assertTrue(same(W.stray_git(self.repo, ceiling=self.d), self.d / 'p1' / 'p2'))

    def test_report_lines(self):
        (self.d / 'p1' / '.git').mkdir()
        lines = W.report(self.repo, ROWS, self.branches(), ceiling=self.d)
        stray = (self.d / 'p1' / '.git').as_posix()
        self.assertEqual(lines, [
            '1 registered worktrees have no folder: git worktree prune removes them',
            f"1 worktrees' branches are merged: {self.wt['J1'].as_posix()}, remove them with git worktree remove <path>",
            f'a .git sits above this repository at {stray}: git commands run from {self.repo.as_posix()} may act on that repository; '
            'delete it or move the clones'])
        W.prune(self.repo)
        git(self.repo, 'worktree', 'remove', str(self.wt['J1']))
        (self.d / 'p1' / '.git').rmdir()
        self.assertEqual(W.report(self.repo, ROWS, self.branches(), ceiling=self.d), [])

    def test_report_names_at_most_five_merged_paths(self):
        for n in range(6):
            p = self.d / 'wt' / f'm{n}'
            git(self.repo, 'worktree', 'add', '-q', '-b', f'm{n}', str(p), 'origin/main')
        line = [l for l in W.report(self.repo, ROWS, self.branches(), ceiling=self.d) if 'merged' in l][0]
        self.assertTrue(line.startswith("7 worktrees' branches are merged: "), line)
        self.assertIn('(and 2 more)', line)

    def verb(self, *flags):
        from warscape.verbs import jobs as jverb
        ctx = types.SimpleNamespace(root=self.repo, config={'registries_dir': 'registries', 'jobs': DEFAULTS['jobs'], 'ci': DEFAULTS['ci']})
        saved = jobq.main_rows
        jobq.main_rows = lambda ctx: ROWS
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = jverb.run(types.SimpleNamespace(action='worktrees', id=None, offline=False, auto=False, serve=False, all=False,
                                                     peek=False, prune='--prune' in flags), ctx)
        finally:
            jobq.main_rows = saved
            jobq.configure_from(DEFAULTS['jobs'])
        return rc, out.getvalue()

    def test_the_verb_prints_the_report_and_prune_removes_only_missing_folders(self):
        rc, out = self.verb()
        self.assertEqual(rc, 0)
        self.assertIn('1 registered worktrees have no folder', out)
        self.assertIn("1 worktrees' branches are merged", out)
        rc, out = self.verb('--prune')
        self.assertEqual(rc, 0)
        self.assertIn('pruned 1 worktree registration', out)
        self.assertEqual(sorted(Path(p).name for p, _, _ in W.registered(self.repo)[1:]), ['J1', 'J9'])


if __name__ == '__main__':
    unittest.main()
