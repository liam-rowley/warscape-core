#!/usr/bin/env python3
"""Contact sheets of the UI art: one sheet set per role, labelled tiles on a checker, at most 192 tiles a sheet (needs Pillow).

purpose: draw every image row of registries/assets.jsonl onto per-role contact sheets under /extract/<target>/sheets/ and write discovery/assets/sheets.json (sheet name to tile ids; position from the tile's index)
usage: python3 discovery/sheets.py [--games <adapter>/games.json] [--role ROLE ...]   (or `wsc discovery sheets`); Pillow: python3 -m pip install --user -r discovery/requirements.txt
when: J7 after the asset pass; J10 (atlas) to eyeball a role; re-run after the registry changes. Ported in spirit from empire-remastered assets/tools/make_sheets.py
not-a-verb: decodes game textures read in place on the PC with Pillow (not in CI); `wsc discovery sheets` runs it

The sheets are game content: they stay under the git-ignored /extract/. Only sheets.json is committed.
"""
import argparse
import collections
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402
REPO = paths.REPO
import assets  # noqa: E402
from packfs import PackFS  # noqa: E402

OUT = os.path.join(REPO, 'extract', assets.GAME, 'sheets')
INDEX = os.path.join(REPO, 'discovery', 'assets', 'sheets.json')
COLS, ROWS = 12, 16
THUMB, LABEL = 128, 30
TW, TH = THUMB + 8, THUMB + LABEL + 4
IMAGE_FORMATS = ('tga', 'dds', 'png', 'jpg', 'jpeg', 'cur', 'ani')  # .ani has no Pillow reader: a red failed tile


def image_rows(reg, roles=None):
    by = collections.defaultdict(list)
    for r in reg:
        if r['format'].split(' ', 1)[0] in IMAGE_FORMATS and (not roles or r['role'] in roles):
            by[r['role']].append(r)
    return {k: sorted(v, key=lambda r: r['id']) for k, v in sorted(by.items())}


def plan(by_role):
    """{sheet name: {role, tiles: [ids]}}: <role>_<nn>, COLS * ROWS tiles each, ids in order."""
    out = {}
    per = COLS * ROWS
    for role, rows in by_role.items():
        for i in range(0, len(rows), per):
            out[f'{role}_{i // per + 1:02d}'] = {'role': role, 'tiles': [r['id'] for r in rows[i:i + per]]}
    return out


def checker(Image, w, h, sq=8):
    im = Image.new('RGBA', (w, h), (200, 200, 200, 255))
    px = Image.new('RGBA', (sq, sq), (150, 150, 150, 255))
    for y in range(0, h, sq):
        for x in range((y // sq % 2) * sq, w, sq * 2):
            im.paste(px, (x, y))
    return im


def label(id_, n=22):
    tail = id_.rsplit('/', 1)[-1]
    return [tail[i:i + n] for i in range(0, min(len(tail), 2 * n), n)]


def draw(fs, rows, path):
    from PIL import Image, ImageDraw, ImageFont
    n = len(rows)
    sheet = Image.new('RGBA', (COLS * TW, ((n + COLS - 1) // COLS) * TH), (40, 40, 40, 255))
    font = ImageFont.load_default(11)
    d = ImageDraw.Draw(sheet)
    bg = checker(Image, THUMB, THUMB)
    failed = []
    for i, r in enumerate(rows):
        x, y = i % COLS * TW + 4, i // COLS * TH + 4
        tile = bg.copy()
        try:
            im = Image.open(io.BytesIO(fs.read(r['path'])))
            im.load()
            im = im.convert('RGBA')
            im.thumbnail((THUMB, THUMB))
            tile.alpha_composite(im, ((THUMB - im.width) // 2, (THUMB - im.height) // 2))
        except Exception:  # noqa: BLE001  Pillow raises many types for formats it cannot read
            tile = Image.new('RGBA', (THUMB, THUMB), (160, 30, 30, 255))
            failed.append(r['id'])
        sheet.paste(tile, (x, y))
        for j, line in enumerate(label(r['id'])):
            d.text((x, y + THUMB + 2 + j * 13), line, fill=(235, 235, 235, 255), font=font)
    sheet.save(path)
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--games', default=paths.adapter_file('games.json'))
    ap.add_argument('--role', action='append')
    a = ap.parse_args(argv)
    fs = PackFS.from_games(json.load(open(a.games, encoding='utf-8')), assets.GAME)
    reg = assets.read_registry()
    by_role = image_rows(reg, a.role)
    sheets = plan(by_role)
    rows_by_id = {r['id']: r for r in reg}
    os.makedirs(OUT, exist_ok=True)
    failed = []
    for name, s in sheets.items():
        failed += draw(fs, [rows_by_id[i] for i in s['tiles']], os.path.join(OUT, name + '.png'))
    if not a.role:
        doc = {'schema': 1, 'note': f'Contact sheets under /extract/{assets.GAME}/sheets/<name>.png (regenerate with `wsc discovery sheets`). '
                                    f'Tile i sits at x = (i % cols) * tile_w, y = (i // cols) * tile_h; the label is the tail of its registry id.',
               'cols': COLS, 'tile_w': TW, 'tile_h': TH, 'failed': sorted(failed), 'sheets': sheets}
        with open(INDEX, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(doc, f, indent=0, sort_keys=True)
            f.write('\n')
    print(f'{len(sheets)} sheets, {sum(len(s["tiles"]) for s in sheets.values())} tiles, {len(failed)} failed to decode: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
