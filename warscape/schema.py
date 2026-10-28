"""A strict subset of JSON Schema 2020-12, standard library only.

Why a subset and not a dependency: CI runs with no installs. The subset covers what registry rows need, and it is closed:
`check_schema` rejects any keyword it does not implement, so a schema can never rely on a rule that is silently ignored.
Schemas written against it are plain JSON Schema, so swapping in a full validator later (the smallest candidate is
`fastjsonschema`, pure Python, no dependencies) needs no schema change.

Keywords prefixed `x-` are registry extensions read by `warscape.registry` (x-view, x-unique, x-ref, x-source); the validator skips them.
"""
import datetime
import json
import re

ANNOTATIONS = {'$schema', '$id', '$comment', 'title', 'description', 'default', 'examples', 'deprecated', 'readOnly'}
TYPES = {'object', 'array', 'string', 'integer', 'number', 'boolean', 'null'}
SUPPORTED = ANNOTATIONS | {
    'type', 'enum', 'const',
    'properties', 'required', 'additionalProperties', 'propertyNames', 'minProperties', 'maxProperties',
    'items', 'minItems', 'maxItems', 'uniqueItems',
    'pattern', 'minLength', 'maxLength', 'format',
    'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
    '$ref', '$defs', 'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else',
}
SUBSCHEMA = {'additionalProperties', 'propertyNames', 'items', 'not', 'if', 'then', 'else'}
SUBSCHEMA_MAP = {'properties', '$defs'}
SUBSCHEMA_LIST = {'allOf', 'anyOf', 'oneOf'}
DATE = re.compile(r'\d{4}-\d{2}-\d{2}\Z')


def _date(v):
    if not DATE.match(v):
        return False
    try:
        datetime.date.fromisoformat(v)
        return True
    except ValueError:
        return False


FORMATS = {'date': _date}


def check_schema(schema, where='#', root=None):
    """Errors in a schema document: unknown keywords, malformed keyword values, unresolvable $ref, bad regex or format."""
    root = schema if root is None else root
    errs = []
    if isinstance(schema, bool):
        return errs
    if not isinstance(schema, dict):
        return [f'{where}: a schema must be an object or a boolean']
    for k, v in schema.items():
        at = f'{where}/{k}'
        if k.startswith('x-'):
            continue
        if k not in SUPPORTED:
            errs.append(f'{at}: keyword not supported by the stdlib validator (supported: {", ".join(sorted(SUPPORTED - ANNOTATIONS))})')
            continue
        if k in SUBSCHEMA:
            errs += check_schema(v, at, root)
        elif k in SUBSCHEMA_MAP:
            if not isinstance(v, dict):
                errs.append(f'{at}: must be an object')
            else:
                for n, s in v.items():
                    errs += check_schema(s, f'{at}/{n}', root)
        elif k in SUBSCHEMA_LIST:
            if not isinstance(v, list) or not v:
                errs.append(f'{at}: must be a non-empty array')
            else:
                for i, s in enumerate(v):
                    errs += check_schema(s, f'{at}/{i}', root)
        elif k == 'type':
            ts = v if isinstance(v, list) else [v]
            if not ts or any(t not in TYPES for t in ts):
                errs.append(f'{at}: unknown type {v!r}')
        elif k == 'required':
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errs.append(f'{at}: must be an array of strings')
        elif k == 'enum':
            if not isinstance(v, list) or not v:
                errs.append(f'{at}: must be a non-empty array')
        elif k == 'pattern':
            try:
                re.compile(v)
            except (re.error, TypeError) as e:
                errs.append(f'{at}: bad regex: {e}')
        elif k == 'format':
            if v not in FORMATS:
                errs.append(f'{at}: format {v!r} not supported (supported: {", ".join(FORMATS)})')
        elif k == '$ref':
            if _resolve(root, v) is None:
                errs.append(f'{at}: cannot resolve {v!r} (only local "#/$defs/<name>" refs are supported)')
        elif k in ('minLength', 'maxLength', 'minItems', 'maxItems', 'minProperties', 'maxProperties'):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                errs.append(f'{at}: must be a non-negative integer')
        elif k in ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'):
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errs.append(f'{at}: must be a number')
        elif k == 'uniqueItems':
            if not isinstance(v, bool):
                errs.append(f'{at}: must be a boolean')
    return errs


def _resolve(root, ref):
    if not isinstance(ref, str) or not ref.startswith('#/$defs/'):
        return None
    return (root.get('$defs') or {}).get(ref[len('#/$defs/'):])


def _type_ok(v, t):
    if t == 'object': return isinstance(v, dict)
    if t == 'array': return isinstance(v, list)
    if t == 'string': return isinstance(v, str)
    if t == 'boolean': return isinstance(v, bool)
    if t == 'null': return v is None
    if t == 'integer': return isinstance(v, int) and not isinstance(v, bool)
    if t == 'number': return isinstance(v, (int, float)) and not isinstance(v, bool)
    return False


def _key(v):
    return json.dumps(v, sort_keys=True)


def validate(inst, schema, where='', root=None):
    """Error strings ('<json pointer>: message') for `inst` against `schema`; empty list means valid."""
    root = schema if root is None else root
    if schema is True:
        return []
    if schema is False:
        return [f'{where or "/"}: not allowed']
    at = where or '/'
    errs = []
    if '$ref' in schema:
        errs += validate(inst, _resolve(root, schema['$ref']), where, root)
    if 'type' in schema:
        ts = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not any(_type_ok(inst, t) for t in ts):
            return errs + [f'{at}: expected {" or ".join(ts)}, got {type(inst).__name__}']
    if 'enum' in schema and _key(inst) not in {_key(e) for e in schema['enum']}:
        errs.append(f'{at}: {inst!r} is not one of {schema["enum"]}')
    if 'const' in schema and _key(inst) != _key(schema['const']):
        errs.append(f'{at}: must be {schema["const"]!r}')
    if isinstance(inst, str):
        if 'minLength' in schema and len(inst) < schema['minLength']:
            errs.append(f'{at}: shorter than {schema["minLength"]}')
        if 'maxLength' in schema and len(inst) > schema['maxLength']:
            errs.append(f'{at}: longer than {schema["maxLength"]}')
        if 'pattern' in schema and not re.search(schema['pattern'], inst):
            errs.append(f'{at}: {inst!r} does not match {schema["pattern"]!r}')
        if 'format' in schema and not FORMATS[schema['format']](inst):
            errs.append(f'{at}: {inst!r} is not a valid {schema["format"]}')
    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if 'minimum' in schema and inst < schema['minimum']: errs.append(f'{at}: below {schema["minimum"]}')
        if 'maximum' in schema and inst > schema['maximum']: errs.append(f'{at}: above {schema["maximum"]}')
        if 'exclusiveMinimum' in schema and inst <= schema['exclusiveMinimum']: errs.append(f'{at}: must be > {schema["exclusiveMinimum"]}')
        if 'exclusiveMaximum' in schema and inst >= schema['exclusiveMaximum']: errs.append(f'{at}: must be < {schema["exclusiveMaximum"]}')
    if isinstance(inst, dict):
        props = schema.get('properties', {})
        for r in schema.get('required', []):
            if r not in inst:
                errs.append(f'{at}: missing required field {r!r}')
        for k, v in inst.items():
            if k in props:
                errs += validate(v, props[k], f'{where}/{k}', root)
            elif 'additionalProperties' in schema:
                ap = schema['additionalProperties']
                if ap is False:
                    errs.append(f'{at}: unknown field {k!r}')
                else:
                    errs += validate(v, ap, f'{where}/{k}', root)
            if 'propertyNames' in schema:
                errs += [e.replace(f'{where}/{k}', f'{at} key') for e in validate(k, schema['propertyNames'], f'{where}/{k}', root)]
        if 'minProperties' in schema and len(inst) < schema['minProperties']: errs.append(f'{at}: fewer than {schema["minProperties"]} fields')
        if 'maxProperties' in schema and len(inst) > schema['maxProperties']: errs.append(f'{at}: more than {schema["maxProperties"]} fields')
    if isinstance(inst, list):
        if 'items' in schema:
            for i, v in enumerate(inst):
                errs += validate(v, schema['items'], f'{where}/{i}', root)
        if 'minItems' in schema and len(inst) < schema['minItems']: errs.append(f'{at}: fewer than {schema["minItems"]} items')
        if 'maxItems' in schema and len(inst) > schema['maxItems']: errs.append(f'{at}: more than {schema["maxItems"]} items')
        if schema.get('uniqueItems') and len({_key(v) for v in inst}) != len(inst): errs.append(f'{at}: items are not unique')
    for s in schema.get('allOf', []):
        errs += validate(inst, s, where, root)
    if 'anyOf' in schema and not any(not validate(inst, s, where, root) for s in schema['anyOf']):
        errs.append(f'{at}: matches none of anyOf')
    if 'oneOf' in schema:
        n = sum(1 for s in schema['oneOf'] if not validate(inst, s, where, root))
        if n != 1:
            errs.append(f'{at}: matches {n} of oneOf (exactly one required)')
    if 'not' in schema and not validate(inst, schema['not'], where, root):
        errs.append(f'{at}: matches a "not" schema')
    if 'if' in schema:
        branch = 'then' if not validate(inst, schema['if'], where, root) else 'else'
        if branch in schema:
            errs += validate(inst, schema[branch], where, root)
    return errs
