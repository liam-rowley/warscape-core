"""`wsc reg remove <reg> <id>...` (W15, backlog B28): removes rows, refusing while anything points at them; nothing written on a refusal."""
import json
import unittest

from _util import TOOL_PY, TempRepo
from warscape.registry import Registry, RegistryError, load_all
from warscape.repo import Ctx

THINGS = {
    'type': 'object', 'required': ['id'], 'additionalProperties': False,
    'properties': {'id': {'type': 'string'}, 'parent': {'type': 'string', 'x-ref': 'things'},
                   'links': {'type': 'array', 'items': {'type': 'string', 'x-ref': 'things'}},
                   'note': {'type': 'string'}},
}
NOTES = {
    'type': 'object', 'required': ['id'], 'additionalProperties': False,
    'properties': {'id': {'type': 'string'}, 'thing': {'type': 'string', 'x-ref': 'things'}},
}

TOML = '''
registries_dir = "registries"
[registries]
tools = "core:tools"
things = "schemas/things.schema.json"
notes = "schemas/notes.schema.json"
jobs = "core:jobs"
[storage]
dir = ["things", "jobs"]
[views]
commit = false
[tests]
dirs = []
'''


def job_row(jid, depends=()):
    return {'id': jid, 'description': 'd', 'title': 't', 'phase': 1, 'status': 'needs_brief', 'model': 'sonnet', 'needs_pc': False,
            'depends_on': list(depends)}


class RegRemove(unittest.TestCase):
    def setUp(self):
        files = {'schemas/things.schema.json': json.dumps(THINGS), 'schemas/notes.schema.json': json.dumps(NOTES),
                 'a.py': TOOL_PY.format(name='a.py'), 'b.py': TOOL_PY.format(name='b.py')}
        self.repo = TempRepo(files, toml=TOML)
        self.addCleanup(self.repo.close)
        r = self.repo.wsc
        self.assertEqual(r('reg', 'render')[0], 0)
        for row in ({'id': 'alone'}, {'id': 'top'}, {'id': 'kid', 'parent': 'top'}, {'id': 'linked'}, {'id': 'linker', 'links': ['x1', 'linked']},
                    {'id': 'x1'}, {'id': 'p1', 'parent': 'p2'}, {'id': 'p2', 'parent': 'p1'}):
            self.assertEqual(r('reg', 'add', 'things', '--json', json.dumps(row))[0], 0)
        self.assertEqual(r('reg', 'add', 'notes', 'id=n1', 'thing=alone')[0], 0)
        self.assertEqual(r('reg', 'add', 'notes', 'id=n2')[0], 0)
        self.assertEqual(r('reg', 'add', 'tools', 'a.py', 'b.py')[0], 0)
        for row in (job_row('W1'), job_row('W2', ['W1']), job_row('W3')):
            self.assertEqual(r('reg', 'add', 'jobs', '--json', json.dumps(row))[0], 0)
        self.repo.write('jobs/W3/brief.md', '# W3\n')

    def snapshot(self):
        out = {}
        for p in sorted((self.repo.root / 'registries').rglob('*')):
            if p.is_file():
                out[p.relative_to(self.repo.root).as_posix()] = p.read_bytes()
        return out

    def refused(self, *args):
        before = self.snapshot()
        rc, out = self.repo.wsc('reg', 'remove', *args)
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.snapshot(), before, 'a refusal writes nothing')
        return out

    def rows(self, name):
        return {r['id'] for r in load_all(Ctx.load(self.repo.root))[name].rows}

    def test_registry_remove_in_memory(self):
        reg = load_all(Ctx.load(self.repo.root))['things']
        gone = reg.remove(['alone', 'x1'])
        self.assertEqual([r['id'] for r in gone], ['alone', 'x1'])
        self.assertNotIn('alone', reg.by_id())
        with self.assertRaisesRegex(RegistryError, "things: no row with id 'nope'"):
            reg.remove(['nope'])
        self.assertIsInstance(reg, Registry)

    def test_removed_in_dir_storage(self):
        self.repo.write('registries/notes.jsonl', self.repo.read('registries/notes.jsonl'))   # untouched jsonl
        rc, out = self.repo.wsc('reg', 'remove', 'things', 'x1', 'linker')
        self.assertEqual(rc, 0, out)
        self.assertIn('removed things:x1, linker', out)
        self.assertFalse((self.repo.root / 'registries/things/x1.json').exists())
        self.assertFalse((self.repo.root / 'registries/things/linker.json').exists())
        self.assertNotIn('linker', self.repo.read('_scratch/registries/things.md'))
        self.assertEqual(self.repo.wsc('reg', 'check')[0], 0)

    def test_removed_in_jsonl_storage(self):
        rc, out = self.repo.wsc('reg', 'remove', 'notes', 'n2')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.rows('notes'), {'n1'})
        self.assertNotIn('n2', self.repo.read('registries/notes.jsonl'))
        self.assertNotIn('n2', self.repo.read('_scratch/registries/notes.md'))

    def test_refused_for_a_scalar_x_ref(self):
        out = self.refused('things', 'top')
        self.assertIn('registries/things/kid.json: kid: parent', out)
        out = self.refused('things', 'alone')
        self.assertIn('registries/notes.jsonl: n1: thing', out)

    def test_refused_for_an_array_item_x_ref(self):
        out = self.refused('things', 'linked')
        self.assertIn('registries/things/linker.json: linker: links', out)
        out = self.refused('jobs', 'W1')
        self.assertIn('W2: depends_on', out)

    def test_rows_pointing_at_each_other_go_together(self):
        self.refused('things', 'p1')
        rc, out = self.repo.wsc('reg', 'remove', 'things', 'p1', 'p2')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.rows('things') & {'p1', 'p2'}, set())

    def test_refused_for_a_superseded_status(self):
        (self.repo.root / 'b.py').unlink()
        self.assertEqual(self.repo.wsc('reg', 'set', 'tools', 'b', 'status=superseded:a')[0], 0)
        (self.repo.root / 'a.py').unlink()
        out = self.refused('tools', 'a')
        self.assertIn('registries/tools.jsonl: b: status superseded:a', out)
        rc, out = self.repo.wsc('reg', 'remove', 'tools', 'a', 'b')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.rows('tools'), set())

    def test_refused_for_a_tool_whose_file_exists(self):
        out = self.refused('tools', 'a')
        self.assertIn('a.py', out)
        self.assertIn('delete the file first, or supersede the row', out)
        (self.repo.root / 'a.py').unlink()
        rc, out = self.repo.wsc('reg', 'remove', 'tools', 'a')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.rows('tools'), {'b'})

    def test_refused_for_a_job_whose_folder_exists(self):
        out = self.refused('jobs', 'W3')
        self.assertIn('jobs/W3/', out)
        rc, out = self.repo.wsc('reg', 'remove', 'jobs', 'W2', 'W1')
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.rows('jobs'), {'W3'})

    def test_refused_for_an_unknown_id(self):
        out = self.refused('things', 'alone', 'nope')
        self.assertIn("things: no row with id 'nope'", out)
        rc, out = self.repo.wsc('reg', 'remove', 'nothere', 'x')
        self.assertNotEqual(rc, 0, out)
        self.assertIn('unknown registry nothere', out)


if __name__ == '__main__':
    unittest.main()
