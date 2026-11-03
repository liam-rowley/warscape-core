"""Host tests for `x-extends` (warscape.registry.load_schema): a game schema that adds fields to a core schema, merged at load."""
import json
import unittest

from _util import TempRepo
from warscape.registry import RegistryError, load_all, load_schema
from warscape.repo import Ctx

TOML = '''
registries_dir = "registries"
[registries]
tools = "core:tools"
hotkeys = "schemas/hotkeys.schema.json"
engine_facts = "schemas/facts.schema.json"
[tests]
dirs = []
'''

HOTKEYS = {'x-extends': 'core:hotkeys', 'description': 'Hotkeys, with the component that owns a mod key.',
           'properties': {'owner': {'type': 'string', 'minLength': 1}}}
FACTS = {'x-extends': 'core:engine_facts', 'required': ['area'],
         'properties': {'area': {'enum': ['gfx', 'ui']}, 'probe': {'$ref': '#/$defs/probe'}},
         '$defs': {'probe': {'type': 'string', 'pattern': '^[a-z_]+$'}},
         'x-unique': [['claim']]}


class Extends(unittest.TestCase):
    def setUp(self):
        self.repo = TempRepo({'schemas/hotkeys.schema.json': json.dumps(HOTKEYS), 'schemas/facts.schema.json': json.dumps(FACTS)}, toml=TOML)
        rc, out = self.repo.wsc('reg', 'render')
        self.assertEqual(rc, 0, out)

    def tearDown(self):
        self.repo.close()

    def regs(self):
        return load_all(Ctx.load(self.repo.root))

    def errors(self, name):
        regs = self.regs()
        return regs[name].check(regs)

    def put(self, name, schema):
        self.repo.write(f'schemas/{name}.schema.json', json.dumps(schema))

    def load_error(self, schema, needle, name='facts'):
        self.put(name, schema)
        with self.assertRaises(RegistryError) as cm:
            load_schema(f'schemas/{name}.schema.json', self.repo.root)
        self.assertIn(needle, str(cm.exception))

    # ------------------------------------------------------------------ merged rows
    def test_extra_field_is_valid_and_written_after_the_core_fields(self):
        reg = self.regs()['hotkeys']
        reg.add({'owner': 'ui.minimap', 'id': 'mod.zoom', 'source': 'mod', 'description': 'd', 'binding': 'Alt+Z', 'action': 'zoom',
                 'context': 'battle'})
        reg.save()
        self.assertEqual(self.repo.wsc('reg', 'render', 'hotkeys')[0], 0)
        row = json.loads(self.repo.read('registries/hotkeys.jsonl'))
        core_props = list(load_schema('core:hotkeys', self.repo.root)['properties'])
        self.assertEqual(list(row), [k for k in core_props if k in row] + ['owner'])
        self.assertEqual(self.errors('hotkeys'), [])

    def test_merged_document(self):
        s = load_schema('schemas/facts.schema.json', self.repo.root)
        core = load_schema('core:engine_facts', self.repo.root)
        self.assertNotIn('x-extends', s)
        self.assertEqual(list(s['properties']), list(core['properties']) + ['area', 'probe'])
        self.assertEqual(s['required'], core['required'] + ['area'])
        self.assertEqual(s['allOf'], core['allOf'])
        self.assertEqual(s['additionalProperties'], False)
        self.assertEqual(set(s['$defs']), set(core['$defs']) | {'probe'})
        self.assertEqual(s['x-unique'], core.get('x-unique', []) + [['claim']])
        self.assertEqual(s['title'], core['title'])
        h = load_schema('schemas/hotkeys.schema.json', self.repo.root)
        self.assertEqual(h['description'], HOTKEYS['description'])
        self.assertEqual(h['x-unique'], load_schema('core:hotkeys', self.repo.root)['x-unique'])

    def test_unknown_field_is_still_refused(self):
        with self.assertRaises(RegistryError):
            self.regs()['hotkeys'].add({'id': 'm', 'description': 'd', 'binding': 'Alt+Z', 'action': 'a', 'context': 'battle',
                                        'source': 'mod', 'colour': 'red'})

    def test_game_required_field_and_core_rules_apply(self):
        reg = self.regs()['engine_facts']
        with self.assertRaises(RegistryError):        # the game's required `area`
            reg.add({'id': 'f1', 'claim': 'c', 'state': 'open'})
        with self.assertRaises(RegistryError):        # the core's allOf: verified needs evidence and date
            reg.add({'id': 'f1', 'claim': 'c', 'state': 'verified', 'area': 'gfx'})
        with self.assertRaises(RegistryError):        # the game's $defs
            reg.add({'id': 'f1', 'claim': 'c', 'state': 'open', 'area': 'gfx', 'probe': 'Not-OK'})
        reg.add({'id': 'f1', 'claim': 'c', 'state': 'open', 'area': 'gfx', 'probe': 'shadow_probe'})
        reg.add({'id': 'f2', 'claim': 'C', 'state': 'open', 'area': 'ui'})
        reg.save(); reg.write_view()
        self.assertIn('clash on (claim)', '\n'.join(self.errors('engine_facts')))   # the game's x-unique

    def test_a_core_hotkeys_extension_keeps_the_clash_rules(self):
        reg = self.regs()['hotkeys']
        for rid, ctx in (('a', 'battle'), ('b', 'global')):
            reg.add({'id': rid, 'description': 'd', 'binding': 'Alt+S', 'action': 'a', 'context': ctx, 'source': 'mod', 'owner': 'x'})
        reg.save(); reg.write_view()
        self.assertEqual(len(self.errors('hotkeys')), 1)

    # ------------------------------------------------------------------ load errors
    def test_forbidden_top_level_key(self):
        for key, val in (('additionalProperties', True), ('type', 'array'), ('x-wildcard', {'claim': '*'}), ('oneOf', [{}])):
            self.load_error(dict(FACTS, **{key: val}), key)

    def test_redefined_core_property(self):
        self.load_error(dict(FACTS, properties={'claim': {'type': 'string', 'maxLength': 9}}), "'claim'")

    def test_defs_clash(self):
        core_def = next(iter(load_schema('core:engine_facts', self.repo.root)['$defs']))
        self.load_error(dict(FACTS, **{'$defs': {core_def: {'type': 'string'}}}), repr(core_def))

    def test_nested_x_extends(self):
        self.load_error(dict(FACTS, properties={'area': {'type': 'string', 'x-extends': 'core:tools'}}), 'x-extends')
        self.load_error({'type': 'object', 'allOf': [{'x-extends': 'core:tools'}]}, 'x-extends')

    def test_target_must_be_a_core_schema(self):
        self.put('other', {'type': 'object'})
        self.load_error(dict(FACTS, **{'x-extends': 'schemas/other.schema.json'}), 'core:')
        self.load_error(dict(FACTS, **{'x-extends': ['core:engine_facts']}), 'core:')

    def test_missing_core_schema(self):
        self.load_error(dict(FACTS, **{'x-extends': 'core:no_such_schema'}), 'no_such_schema')

    def test_registry_load_names_the_registry(self):
        self.put('facts', dict(FACTS, type='array'))
        with self.assertRaises(RegistryError) as cm:
            self.regs()
        self.assertIn('engine_facts', str(cm.exception))

    # ------------------------------------------------------------------ gate
    def test_schemas_gate_checks_the_merged_document(self):
        rc, out = self.repo.wsc('gates', '--only', 'schemas')
        self.assertEqual(rc, 0, out)
        self.put('facts', dict(FACTS, properties={'area': {'type': 'string', 'contentEncoding': 'base64'}}))   # outside the subset
        rc, out = self.repo.wsc('gates', '--only', 'schemas')
        self.assertEqual(rc, 1, out)
        self.assertIn('contentEncoding', out)
        self.put('facts', dict(FACTS, properties={'area': {'$ref': '#/$defs/nowhere'}}))   # a $ref only the merged $defs could resolve
        rc, out = self.repo.wsc('gates', '--only', 'schemas')
        self.assertEqual(rc, 1, out)
        self.put('facts', dict(FACTS, properties={'claim': {'type': 'string'}}))           # a load error is a gate error
        rc, out = self.repo.wsc('gates', '--only', 'schemas')
        self.assertEqual(rc, 1, out)
        self.assertIn("'claim'", out)

    def test_ref_to_a_core_def_resolves_after_the_merge(self):
        self.put('facts', dict(FACTS, properties={'area': {'enum': ['gfx']}, 'seen': {'$ref': '#/$defs/date'}}))   # the core's def
        rc, out = self.repo.wsc('gates', '--only', 'schemas')
        self.assertEqual(rc, 0, out)


class ExtendJobs(unittest.TestCase):
    """Open question 4 of W14: a core schema that drives code (`core:jobs`) can be extended; the extra field is inert to the queue."""

    def test_jobs_extension_passes_jobs_check(self):
        toml = TOML.replace('hotkeys = "schemas/hotkeys.schema.json"\nengine_facts = "schemas/facts.schema.json"',
                            'jobs = "schemas/jobs.schema.json"') + '[jobs]\nid_prefix = "J"\n[storage]\ndir = ["jobs"]\n'
        ext = {'x-extends': 'core:jobs', 'properties': {'sprint': {'type': 'integer', 'minimum': 1}}}
        repo = TempRepo({'schemas/jobs.schema.json': json.dumps(ext)}, toml=toml)
        try:
            self.assertEqual(repo.wsc('reg', 'render')[0], 0)
            reg = load_all(Ctx.load(repo.root))['jobs']
            reg.add({'id': 'J1', 'description': 'd', 'title': 't', 'phase': 1, 'status': 'needs_brief', 'model': 'opus',
                     'needs_pc': False, 'depends_on': [], 'sprint': 3})
            reg.save()
            self.assertEqual(repo.wsc('reg', 'render')[0], 0)
            self.assertIn('"sprint": 3', repo.read('registries/jobs/J1.json'))
            rc, out = repo.wsc('jobs', 'check')
            self.assertEqual(rc, 0, out)
        finally:
            repo.close()


if __name__ == '__main__':
    unittest.main()
