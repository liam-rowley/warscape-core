import json
import unittest

from _util import CORE
from warscape.schema import check_schema, validate


class CheckSchema(unittest.TestCase):
    def test_shipped_schemas_are_within_the_subset(self):
        files = sorted((CORE / 'schemas').glob('*.schema.json'))
        self.assertEqual(len(files), 8)
        for f in files:
            self.assertEqual(check_schema(json.loads(f.read_text(encoding='utf-8'))), [], f.name)

    def test_unknown_keyword_is_refused_not_ignored(self):
        errs = check_schema({'type': 'object', 'properties': {'a': {'type': 'string', 'contentEncoding': 'base64'}}})
        self.assertEqual(len(errs), 1)
        self.assertIn('contentEncoding', errs[0])
        self.assertIn('not supported', errs[0])

    def test_extension_keywords_are_allowed(self):
        self.assertEqual(check_schema({'type': 'object', 'x-view': {'columns': ['id']}, 'x-unique': [['a']]}), [])

    def test_bad_ref_regex_format_and_type(self):
        self.assertTrue(check_schema({'$ref': '#/$defs/nope'}))
        self.assertTrue(check_schema({'$ref': 'other.json#/x'}))
        self.assertTrue(check_schema({'pattern': '('}))
        self.assertTrue(check_schema({'format': 'email'}))
        self.assertTrue(check_schema({'type': 'str'}))
        self.assertTrue(check_schema({'required': 'id'}))
        self.assertTrue(check_schema({'anyOf': []}))


class Validate(unittest.TestCase):
    S = {'type': 'object', 'required': ['id'], 'additionalProperties': False,
         '$defs': {'id': {'type': 'string', 'pattern': '^[a-z]+$'}},
         'properties': {'id': {'$ref': '#/$defs/id'}, 'n': {'type': 'integer', 'minimum': 0, 'maximum': 9},
                        'd': {'type': 'string', 'format': 'date'}, 'k': {'enum': ['a', 'b']},
                        'l': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True, 'minItems': 1},
                        'x': {'type': ['string', 'null']}}}

    def ok(self, inst, s=None):
        self.assertEqual(validate(inst, s or self.S), [], inst)

    def bad(self, inst, s=None, needle=''):
        errs = validate(inst, s or self.S)
        self.assertTrue(errs, inst)
        if needle:
            self.assertTrue(any(needle in e for e in errs), errs)

    def test_basics(self):
        self.ok({'id': 'abc', 'n': 3, 'd': '2026-10-28', 'k': 'a', 'l': ['p', 'q'], 'x': None})
        self.bad({}, needle="missing required field 'id'")
        self.bad({'id': 'ABC'}, needle='does not match')
        self.bad({'id': 'a', 'extra': 1}, needle="unknown field 'extra'")
        self.bad({'id': 'a', 'n': 10}, needle='above')
        self.bad({'id': 'a', 'n': True}, needle='expected integer')   # a bool is not an integer
        self.bad({'id': 'a', 'n': 1.5})
        self.bad({'id': 'a', 'k': 'c'}, needle='not one of')
        self.bad({'id': 'a', 'l': []}, needle='fewer than')
        self.bad({'id': 'a', 'l': ['p', 'p']}, needle='not unique')
        self.bad({'id': 'a', 'l': [1]}, needle='/l/0')

    def test_date_format_is_a_real_date(self):
        self.ok({'id': 'a', 'd': '2028-02-29'})
        self.bad({'id': 'a', 'd': '2026-02-30'})
        self.bad({'id': 'a', 'd': '2026-10-28T10:00'})

    def test_combinators(self):
        s = {'oneOf': [{'type': 'string'}, {'type': 'integer'}]}
        self.ok('x', s); self.ok(3, s); self.bad(3.5, s, 'oneOf')
        s = {'anyOf': [{'minimum': 5}, {'maximum': 1}]}
        self.ok(7, s); self.ok(0, s); self.bad(3, s, 'anyOf')
        self.bad('Alt+F4', {'not': {'enum': ['Alt+F4']}}, '"not"')
        s = {'if': {'properties': {'k': {'const': 'v'}}}, 'then': {'required': ['a']}, 'else': {'required': ['b']}}
        self.ok({'k': 'v', 'a': 1}, s); self.bad({'k': 'v', 'b': 1}, s); self.ok({'k': 'w', 'b': 1}, s); self.bad({'k': 'w'}, s)

    def test_property_names_and_map_values(self):
        s = {'type': 'object', 'propertyNames': {'pattern': '^[a-z]+$'}, 'additionalProperties': {'type': 'number'}}
        self.ok({'abc': 1}, s)
        self.bad({'ABC': 1}, s, 'key')
        self.bad({'abc': 'x'}, s)


if __name__ == '__main__':
    unittest.main()
