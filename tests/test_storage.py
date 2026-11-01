"""Registry storage and views (napoleon J55): one file per row (`[storage] dir`), uncommitted views (`[views] commit = false`),
`wsc reg migrate`, and that a repo setting neither keeps the JSONL + committed-view layout."""
import json
import subprocess
import unittest

from _util import MINIMAL_TOML, TOOL_PY, TempRepo
from warscape.checks import windows_path_errors
from warscape.registry import RegistryError, file_to_id, id_to_file, load_all
from warscape.repo import ConfigError, Ctx, load_config
from warscape.verbs.reg import set_storage_dir

DIR_TOML = MINIMAL_TOML + '\n[storage]\ndir = ["engine_facts", "tools"]\n'
NOVIEW_TOML = MINIMAL_TOML + '\n[views]\ncommit = false\n'
FACT = ['id=napoleon.lua.stall', 'claim=string.find stalls the pump', 'state=open']


def regs(repo):
    return load_all(Ctx.load(repo.root))


def errors(repo, name):
    r = regs(repo)
    return r[name].check(r)


class FileNames(unittest.TestCase):
    IDS = ['J55', 'discovery.core.api_inventory', 'a b', 'a/b\\c', 'x:y?z*', '100%', 'con', 'NUL.json', 'com1.x', 'lpt9', 'trail.',
           'trail ', 'ünïcode', 'a"b<c>|d', '.hidden', 'Con', 'conx']

    def test_the_rule_is_reversible_and_windows_safe(self):
        names = [id_to_file(i) for i in self.IDS]
        self.assertEqual([file_to_id(n) for n in names], self.IDS)
        self.assertEqual(windows_path_errors([f'registries/x/{n}' for n in names if n != id_to_file('Con')]), [])
        self.assertEqual(id_to_file('J55'), 'J55.json')
        self.assertEqual(id_to_file('discovery.core.api_inventory'), 'discovery.core.api_inventory.json')
        self.assertEqual(id_to_file('con'), '%63on.json')
        self.assertEqual(id_to_file('conx'), 'conx.json')
        for bad in ('', None, 5):
            with self.assertRaises(RegistryError):
                id_to_file(bad)


class Defaults(unittest.TestCase):
    def test_nothing_set_keeps_jsonl_and_committed_views(self):
        repo = TempRepo()
        try:
            cfg = load_config(repo.root)
            self.assertEqual((cfg['storage'], cfg['views']), ({'dir': []}, {'commit': True, 'dir': '_scratch/registries'}))
            self.assertEqual(repo.wsc('reg', 'render')[0], 0)
            self.assertEqual(repo.wsc('reg', 'add', 'engine_facts', *FACT)[0], 0)
            self.assertTrue((repo.root / 'registries/engine_facts.jsonl').is_file())
            self.assertIn('napoleon.lua.stall', repo.read('registries/engine_facts.md'))
            self.assertFalse((repo.root / '_scratch').exists())
            repo.write('registries/engine_facts.md', 'stale\n')
            self.assertTrue(any('stale or missing' in e for e in errors(repo, 'engine_facts')))
        finally:
            repo.close()

    def test_bad_settings_are_refused(self):
        for extra in ('[storage]\ndir = ["nope"]\n', '[views]\ncommit = "no"\n', '[storage]\nfiles = 1\n'):
            repo = TempRepo(toml=MINIMAL_TOML + '\n' + extra)
            try:
                with self.assertRaises(ConfigError):
                    load_config(repo.root)
            finally:
                repo.close()


class DirStorage(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo({'adapter/sync.py': TOOL_PY.format(name='adapter/sync.py')}, toml=DIR_TOML)
        self.assertEqual(self.repo.wsc('reg', 'render')[0], 0)

    def tearDown(self):
        self.repo.close()

    def test_rows_live_one_per_file_in_canonical_form(self):
        self.assertEqual(self.repo.wsc('reg', 'add', 'engine_facts', *FACT)[0], 0)
        self.assertEqual(self.repo.wsc('reg', 'add', 'tools', '--missing')[0], 0)
        f = self.repo.root / 'registries/engine_facts/napoleon.lua.stall.json'
        self.assertEqual(f.read_text(encoding='utf-8'),
                         '{\n  "id": "napoleon.lua.stall",\n  "claim": "string.find stalls the pump",\n  "state": "open"\n}\n')
        self.assertFalse((self.repo.root / 'registries/engine_facts.jsonl').exists())
        self.assertEqual(len(list((self.repo.root / 'registries/tools').glob('*.json'))), 1)
        self.assertIn('`registries/engine_facts/`', self.repo.read('registries/engine_facts.md'))
        rc, out = self.repo.wsc('gates', '--fast')
        self.assertEqual(rc, 0, out)
        rc, out = self.repo.wsc('find', 'stalls', 'pump')
        self.assertEqual(rc, 0, out)
        self.assertIn('napoleon.lua.stall', out)

    def test_set_rewrites_only_its_row(self):
        self.repo.wsc('reg', 'add', 'engine_facts', *FACT)
        self.repo.wsc('reg', 'add', 'engine_facts', 'id=b.other', 'claim=c', 'state=open')
        other = self.repo.root / 'registries/engine_facts/b.other.json'
        before = other.stat().st_mtime_ns
        self.assertEqual(self.repo.wsc('reg', 'set', 'engine_facts', 'napoleon.lua.stall', 'notes=n')[0], 0)
        self.assertEqual(other.stat().st_mtime_ns, before)
        self.assertIn('"notes": "n"', self.repo.read('registries/engine_facts/napoleon.lua.stall.json'))

    def test_empty_registry_needs_no_folder(self):
        self.assertFalse((self.repo.root / 'registries/engine_facts').exists())
        self.assertEqual(errors(self.repo, 'engine_facts'), [])

    def test_name_id_stray_file_canonical_and_second_copy_errors(self):
        self.repo.wsc('reg', 'add', 'engine_facts', *FACT)
        d = 'registries/engine_facts'
        self.repo.write(f'{d}/wrong.json', json.dumps({'id': 'right', 'claim': 'c', 'state': 'open'}, indent=2) + '\n')
        self.repo.write(f'{d}/notes.txt', 'x\n')
        self.repo.write(f'{d}/napoleon.lua.stall.json', '{"id": "napoleon.lua.stall", "claim": "x", "state": "open"}\n')
        self.repo.write('registries/engine_facts.jsonl', '')
        errs = '\n'.join(errors(self.repo, 'engine_facts'))
        self.assertIn("wrong.json: holds id 'right', whose file is right.json", errs)
        self.assertIn('notes.txt: only <id>.json row files', errs)
        self.assertIn('napoleon.lua.stall.json: not in canonical form', errs)
        self.assertIn('registries/engine_facts.jsonl: a second copy', errs)
        (self.repo.root / f'{d}/wrong.json').unlink()
        (self.repo.root / f'{d}/notes.txt').unlink()
        (self.repo.root / 'registries/engine_facts.jsonl').unlink()
        self.assertEqual(self.repo.wsc('reg', 'render', 'engine_facts')[0], 0)
        self.assertEqual(errors(self.repo, 'engine_facts'), [])

    def test_ids_differing_only_in_case_are_refused(self):
        reg = regs(self.repo)['engine_facts']
        reg.validate_row = lambda row: []          # the core schemas take lower-case ids; a repo schema may not
        reg.add({'id': 'Fact.A', 'claim': 'c', 'state': 'open'})
        with self.assertRaisesRegex(RegistryError, 'only in case'):
            reg.add({'id': 'fact.a', 'claim': 'c', 'state': 'open'})

    def test_two_branches_adding_and_changing_different_rows_merge_cleanly(self):
        """No .gitattributes at all: git's own merge, not merge=union, keeps both rows."""
        g = lambda *a: subprocess.run(['git', '-C', str(self.repo.root), '-c', 'user.name=t', '-c', 'user.email=t@t', *a],
                                      capture_output=True, text=True)
        self.repo.write('wsc.toml', DIR_TOML + '\n[views]\ncommit = false\n')
        self.repo.write('.gitignore', '_scratch/\n')
        for n in [p for p in (self.repo.root / 'registries').glob('*.md')]:
            n.unlink()
        for rid in ('base.one', 'base.two'):
            self.assertEqual(self.repo.wsc('reg', 'add', 'engine_facts', f'id={rid}', 'claim=c', 'state=open')[0], 0)
        g('add', '-A'); g('commit', '-qm', 'base'); g('branch', '-M', 'main')
        for br in ('one', 'two'):
            g('checkout', '-q', '-b', br, 'main')
            self.repo.wsc('reg', 'add', 'engine_facts', f'id=j.{br}', 'claim=c', 'state=open')
            self.repo.wsc('reg', 'set', 'engine_facts', f'base.{br}', f'claim=changed by {br}')
            g('add', '-A'); g('commit', '-qm', br)
        g('checkout', '-q', 'one')
        m = g('merge', '--no-edit', 'two')
        self.assertEqual(m.returncode, 0, m.stdout + m.stderr)
        rows = regs(self.repo)['engine_facts'].by_id()
        self.assertEqual(sorted(rows), ['base.one', 'base.two', 'j.one', 'j.two'])
        self.assertEqual([rows[f'base.{b}']['claim'] for b in ('one', 'two')], ['changed by one', 'changed by two'])
        self.assertEqual(errors(self.repo, 'engine_facts'), [])


class Views(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo(toml=NOVIEW_TOML)

    def tearDown(self):
        self.repo.close()

    def test_views_go_to_the_scratch_folder_and_are_not_compared(self):
        self.assertEqual(self.repo.wsc('reg', 'render')[0], 0)
        self.assertFalse((self.repo.root / 'registries/engine_facts.md').exists())
        self.assertTrue((self.repo.root / '_scratch/registries/engine_facts.md').is_file())
        self.assertEqual(self.repo.wsc('reg', 'add', 'engine_facts', *FACT)[0], 0)
        (self.repo.root / '_scratch/registries/engine_facts.md').unlink()
        self.assertEqual(errors(self.repo, 'engine_facts'), [])      # a missing or stale view is fine: it is not committed
        rc, out = self.repo.wsc('find', 'stalls')
        self.assertEqual(rc, 0, out)

    def test_a_committed_view_is_an_error(self):
        self.repo.wsc('reg', 'render')
        self.repo.write('registries/hotkeys.md', '# old\n')
        self.assertTrue(any('views are not committed' in e for e in errors(self.repo, 'hotkeys')))

    def test_render_out(self):
        rc, out = self.repo.wsc('reg', 'render', 'hotkeys', '--out', str(self.repo.root / 'elsewhere'))
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.repo.root / 'elsewhere/hotkeys.md').is_file())


class Migrate(unittest.TestCase):
    def test_jsonl_to_dir_and_back(self):
        repo = TempRepo()
        try:
            repo.wsc('reg', 'render')
            repo.wsc('reg', 'add', 'engine_facts', *FACT)
            repo.wsc('reg', 'add', 'engine_facts', 'id=con', 'claim=a device name', 'state=open')
            before = repo.read('registries/engine_facts.jsonl')
            rc, out = repo.wsc('reg', 'migrate', 'engine_facts', '--to', 'dir')
            self.assertEqual(rc, 0, out)
            self.assertFalse((repo.root / 'registries/engine_facts.jsonl').exists())
            self.assertTrue((repo.root / 'registries/engine_facts/%63on.json').is_file())
            self.assertEqual(load_config(repo.root)['storage']['dir'], ['engine_facts'])
            self.assertEqual(errors(repo, 'engine_facts'), [])
            self.assertNotEqual(repo.wsc('reg', 'migrate', 'engine_facts', '--to', 'dir')[0], 0)
            self.assertEqual(repo.wsc('reg', 'migrate', 'engine_facts', '--to', 'jsonl')[0], 0)
            self.assertEqual(repo.read('registries/engine_facts.jsonl'), before)
            self.assertFalse((repo.root / 'registries/engine_facts').exists())
            self.assertEqual(load_config(repo.root)['storage']['dir'], [])
        finally:
            repo.close()

    def test_set_storage_dir_edits_the_toml(self):
        self.assertEqual(set_storage_dir('a = 1\n', ['jobs']), 'a = 1\n\n[storage]\ndir = ["jobs"]   # one file per row (wsc reg migrate)\n')
        t = '[storage]\ndir = ["a"]  # c\n\n[views]\ncommit = false\n'
        self.assertEqual(set_storage_dir(t, ['a', 'b']), '[storage]\ndir = ["a", "b"]\n\n[views]\ncommit = false\n')
        self.assertEqual(set_storage_dir('[storage]\n[x]\n', ['a']), '[storage]\ndir = ["a"]\n[x]\n')
        with self.assertRaises(RegistryError):
            set_storage_dir('[storage]\ndir = [\n  "a",\n]\n', ['b'])


if __name__ == '__main__':
    unittest.main()
