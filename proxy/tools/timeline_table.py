#!/usr/bin/env python3
"""Turn proxy phase timelines (<mod_dir>/logs/timeline.json, dev.timeline=1) into a table: median and spread per phase, n per arm.

purpose: compare load phases across launches and arms (baseline vs intro skip vs autostart): t from process start, in seconds
usage: timeline_table.py ARM=FILE[,FILE...] [ARM=...] [--json OUT] [--md]   (a FILE may be a folder: every timeline*.json in it)
when: after a PC run of N launches per arm (J3 baseline and cuts, later regression checks); the table goes into the run report and the
      medians into engine_facts. A phase that repeats (movie_open, scene_ready) is keyed by its detail: scene_ready:frontend.
not-a-verb: reads PC run output, writes a report table
"""
import argparse
import json
import statistics
import sys
from pathlib import Path


def key(m, seen):
    k = m['phase'] + (':' + m['detail'] if m.get('detail') and m['phase'] in ('movie_open', 'movie_close', 'movie_refused', 'scene_ready', 'first_present_after_ready', 'loading_started') else '')
    n = seen.get(k, 0) + 1
    seen[k] = n
    return k if n == 1 else f'{k}#{n}'


def load(paths):
    runs = []
    for p in paths:
        p = Path(p)
        files = sorted(p.glob('timeline*.json')) if p.is_dir() else [p]
        for f in files:
            d = json.loads(f.read_text(encoding='utf-8'))
            seen, row = {}, {}
            for m in d['phases']:
                if m.get('t_ms', -1) >= 0:
                    row[key(m, seen)] = m['t_ms'] / 1000.0
            runs.append((f.name, d.get('launch_id', ''), row))
    return runs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('arms', nargs='+')
    ap.add_argument('--json')
    a = ap.parse_args(argv)
    arms, order = {}, []
    for spec in a.arms:
        name, _, files = spec.partition('=')
        arms[name] = load(files.split(','))
        for _, _, row in arms[name]:
            for k in row:
                if k not in order:
                    order.append(k)
    order.sort(key=lambda k: statistics.median([r[k] for arm in arms.values() for _, _, r in arm if k in r]))
    out = {}
    head = '| phase | ' + ' | '.join(f'{n} (n={len(r)})' for n, r in arms.items()) + ' |'
    print(head)
    print('|' + '---|' * (len(arms) + 1))
    for k in order:
        cells = []
        for n, runs in arms.items():
            v = [r[k] for _, _, r in runs if k in r]
            if not v:
                cells.append('-')
                continue
            med = statistics.median(v)
            out.setdefault(k, {})[n] = {'median_s': round(med, 3), 'min_s': round(min(v), 3), 'max_s': round(max(v), 3), 'n': len(v)}
            cells.append(f'{med:.2f} ({min(v):.2f}-{max(v):.2f}){"" if len(v) == len(runs) else f" n={len(v)}"}')
        print(f'| {k} | ' + ' | '.join(cells) + ' |')
    if a.json:
        Path(a.json).write_text(json.dumps({'arms': {n: [{'file': f, 'launch_id': l} for f, l, _ in r] for n, r in arms.items()}, 'phases': out}, indent=1) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
