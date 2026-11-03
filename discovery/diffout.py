"""Shared writer for the reference-game-to-target-game diff files (discovery/diff/<area>.json): one fixed schema for every area.

purpose: build, validate and write one area's diff file (sorted, deterministic, no timestamps) so a re-run diffs cleanly
usage: from diffout import row, write; write(path, area, rows, detail)   (library; the area tools in discovery/ call it)
when: every discovery diff pass (J6) writes its JSON through this; the README generator (`wsc discovery render`) reads the same schema
not-a-verb: a library module imported by the area readers, which run on the PC without the repo's core checkout

Schema (version 1): {"schema": 1, "area": str, "rows": [row...], "detail": {...}}. A row is the README's top table:
item, <reference game>, <target game> (the names are games.json "reference" and "target"), verdict (same | adapter | new | gone), adapter (note, may be empty), evidence (where it came from).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

SCHEMA = 1
VERDICTS = ('same', 'adapter', 'new', 'gone')


def row_keys():
    return ('item', paths.REFERENCE, paths.TARGET, 'verdict', 'adapter', 'evidence')


def row(item, reference, target, verdict, adapter='', evidence=''):
    if verdict not in VERDICTS:
        raise ValueError(f'{item}: verdict {verdict!r} is not one of {VERDICTS}')
    return {'item': str(item), paths.REFERENCE: str(reference), paths.TARGET: str(target), 'verdict': verdict,
            'adapter': str(adapter), 'evidence': str(evidence)}


def problems(doc):
    """Schema check for one diff file (also used by the host tests and the render verb)."""
    out = []
    if doc.get('schema') != SCHEMA:
        out.append(f'schema {doc.get("schema")!r}, want {SCHEMA}')
    if not isinstance(doc.get('area'), str) or not doc.get('area'):
        out.append('area missing')
    rows = doc.get('rows')
    if not isinstance(rows, list) or not rows:
        out.append('rows missing or empty')
        rows = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict) or tuple(sorted(r)) != tuple(sorted(row_keys())):
            out.append(f'row {i}: keys {sorted(r) if isinstance(r, dict) else type(r).__name__}, want {sorted(row_keys())}')
        elif r['verdict'] not in VERDICTS:
            out.append(f'row {i} ({r["item"]}): verdict {r["verdict"]!r}')
    items = [r.get('item') for r in rows if isinstance(r, dict)]
    if items != sorted(items) or len(set(items)) != len(items):
        out.append('rows are not sorted by item or repeat an item')
    if not isinstance(doc.get('detail'), dict):
        out.append('detail missing')
    return out


def dumps(area, rows, detail):
    doc = {'schema': SCHEMA, 'area': area, 'rows': sorted(rows, key=lambda r: r['item']), 'detail': detail}
    bad = problems(doc)
    if bad:
        raise ValueError(f'{area}: ' + '; '.join(bad))
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=True) + '\n'


def write(path, area, rows, detail):
    text = dumps(area, rows, detail)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return path
