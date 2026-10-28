import unittest

from _util import TOOL_PY, TempRepo
from warscape import tools
from warscape.registry import load_all
from warscape.repo import Ctx


class Headers(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo()

    def tearDown(self):
        self.repo.close()

    def test_comment_docstring_and_batch_forms(self):
        p = self.repo.write('a.py', TOOL_PY.format(name='a.py'))
        self.assertEqual(tools.read_header(p), {'purpose': 'Do a thing for the tests.', 'usage': 'python3 a.py', 'when': 'in tests only.', 'not_a_verb': 'a test fixture.'})
        p = self.repo.write('b.py', '"""\nPurpose: B things.\nUsage (cloud): python3 b.py\nWhen to use: rarely.\nVerb: bee\n"""\nx = 1\n')
        self.assertEqual(tools.read_header(p), {'purpose': 'B things.', 'usage': 'python3 b.py', 'when': 'rarely.', 'verb': 'bee'})
        p = self.repo.write('c.cmd', '@echo off\nrem purpose: C things\nrem usage: c.cmd\nrem when: on Windows\nrem not a verb: runs in cmd.exe\n')
        self.assertEqual(tools.read_header(p)['not_a_verb'], 'runs in cmd.exe')
        p = self.repo.write('d.lua', '-- purpose: D\n-- purpose: second wins nothing\n')
        self.assertEqual(tools.read_header(p)['purpose'], 'D')

    def test_header_must_be_in_the_first_40_lines(self):
        p = self.repo.write('late.py', '\n' * 45 + '# purpose: too late\n')
        self.assertEqual(tools.read_header(p), {})

    def test_header_problems(self):
        self.assertTrue(any('neither' in e for e in tools.header_problems({'purpose': 'p', 'usage': 'u', 'when': 'w'})))
        self.assertTrue(any('both' in e for e in tools.header_problems({'purpose': 'p', 'usage': 'u', 'when': 'w', 'verb': 'v', 'not_a_verb': 'r'})))
        self.assertEqual(tools.header_problems({'purpose': 'p', 'usage': 'u', 'when': 'w', 'verb': 'v'}), [])
        self.assertEqual(len(tools.header_problems({})), 4)

    def test_slug(self):
        self.assertEqual(tools.slug('adapter/tools/pc_sync.py'), 'adapter.tools.pc_sync')
        self.assertEqual(tools.slug('.githooks/pre-push'), 'githooks.pre-push')
        self.assertEqual(tools.slug('Scripts/Run Me.cmd'), 'scripts.run-me')


class Coverage(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo({'adapter/sync.py': TOOL_PY.format(name='adapter/sync.py'), 'notes.txt': 'not a tool'})
        self.repo.wsc('reg', 'render')

    def tearDown(self):
        self.repo.close()

    def check(self):
        ctx = Ctx.load(self.repo.root)
        return tools.check(ctx, load_all(ctx)['tools'])

    def test_missing_row_then_add_then_drift(self):
        errs, _ = self.check()
        self.assertEqual(len(errs), 1)
        self.assertIn('without a registry row', errs[0])
        rc, out = self.repo.wsc('reg', 'add', 'tools', str(self.repo.root / 'adapter/sync.py'))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.check(), ([], []))
        self.repo.write('adapter/sync.py', TOOL_PY.format(name='adapter/sync.py').replace('Do a thing', 'Do another thing'))
        errs, _ = self.check()
        self.assertIn('differs from the file header in purpose', errs[0])

    def test_header_fields_cannot_be_set_by_hand(self):
        self.repo.wsc('reg', 'add', 'tools', '--missing')
        rc, out = self.repo.wsc('reg', 'set', 'tools', 'adapter.sync', 'purpose=hand edit')
        self.assertEqual(rc, 2)
        self.assertIn('come from the file header', out)

    def test_add_refuses_a_file_without_a_header(self):
        self.repo.write('bare.py', 'print(1)\n')
        rc, out = self.repo.wsc('reg', 'add', 'tools', str(self.repo.root / 'bare.py'))
        self.assertEqual(rc, 2)
        self.assertIn('no `purpose:` line', out)

    def test_removed_file_superseded_chain_and_retirement(self):
        self.repo.write('adapter/sync2.py', TOOL_PY.format(name='adapter/sync2.py'))
        self.assertEqual(self.repo.wsc('reg', 'add', 'tools', '--missing')[0], 0)
        (self.repo.root / 'adapter/sync.py').unlink()
        errs, _ = self.check()
        self.assertTrue(any('live row whose file' in e for e in errs), errs)
        self.assertEqual(self.repo.wsc('reg', 'set', 'tools', 'adapter.sync', 'status=superseded:adapter.sync2')[0], 0)
        self.assertEqual(self.check(), ([], []))
        rc, out = self.repo.wsc('reg', 'set', 'tools', 'adapter.sync2', 'status=superseded:nothing')
        errs, _ = self.check()
        self.assertTrue(any("superseded by 'nothing'" in e for e in errs), errs)
        self.repo.wsc('reg', 'set', 'tools', 'adapter.sync2', 'status=live', 'last_used=2020-01-01')
        self.assertEqual(self.check(), ([], []))            # retirement warnings are off by default
        self.repo.write('wsc.toml', self.repo.read('wsc.toml') + '\n[tools]\nretire_after_days = 90\n')
        errs, warns = self.check()
        self.assertEqual(errs, [])
        self.assertIn('retire', warns[0])

    def test_a_moved_tool_keeps_its_id(self):
        self.repo.wsc('reg', 'add', 'tools', '--missing')
        (self.repo.root / 'adapter/sync.py').rename(self.repo.root / 'adapter/pc_sync.py')
        rc, out = self.repo.wsc('reg', 'add', 'tools', str(self.repo.root / 'adapter/pc_sync.py'), '--id', 'adapter.sync')
        self.assertEqual(rc, 0, out)
        ctx = Ctx.load(self.repo.root)
        self.assertEqual([(r['id'], r['path']) for r in load_all(ctx)['tools'].rows], [('adapter.sync', 'adapter/pc_sync.py')])
        self.assertEqual(self.check(), ([], []))

    def test_library_and_exempt_globs(self):
        self.repo.write('wsc.toml', self.repo.read('wsc.toml') + '\n[tools]\nlibrary = ["lib/**"]\nexempt = ["runs/**"]\n')
        self.repo.write('lib/deep/helper.py', 'x = 1\n')
        self.repo.write('runs/20261028_a/probe.py', 'x = 1\n')
        self.repo.wsc('reg', 'add', 'tools', '--missing')
        self.assertEqual(self.check(), ([], []))


if __name__ == '__main__':
    unittest.main()
