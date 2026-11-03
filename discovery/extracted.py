"""Effective files of a game's extract folder: one copy per entry path, the latest pack in the game's pack order winning.

purpose: list the extracted pack entries of one game (extract/<game>/<pack stem>/<path>) with patch-pack precedence applied
usage: from extracted import effective, load_games; effective(games, paths.TARGET, exts={'', '.luac'}) -> {path: file}   (library)
when: every discovery pass that reads extracted layouts, fonts, scripts or shaders (J6); the extract itself is core/proxy/tools/pack_list.py --extract
not-a-verb: a library module imported by the discovery readers
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

REPO = paths.REPO


def load_games(path=None):
    return json.load(open(path or paths.adapter_file('games.json'), encoding='utf-8'))


def effective(games, game, exts=None, under=''):
    """{entry path (lower case, backslashes): extracted file}; exts filters on the extension ('' = none)."""
    root = os.path.join(REPO, games['extract'], game)
    order = games[game]['pack_order']
    out = {}
    for stem in sorted(os.listdir(root) if os.path.isdir(root) else [], key=lambda s: order.index(s) if s in order else -1):
        base = os.path.join(root, stem)
        for d, _, files in os.walk(base):
            for f in files:
                rel = os.path.relpath(os.path.join(d, f), base).replace('/', '\\').lower()
                if under and not rel.startswith(under):
                    continue
                if exts is not None and os.path.splitext(f)[1].lower() not in exts:
                    continue
                out[rel] = os.path.join(d, f)
    return dict(sorted(out.items()))
