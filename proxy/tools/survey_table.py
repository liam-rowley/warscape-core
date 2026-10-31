#!/usr/bin/env python3
"""Summarise a file-open survey (<mod_dir>/logs/files.log, dev.log_files=1): distinct paths by folder, API and result.

purpose: find what the engine opens, probes and lists (start-up movies, scripts, preferences, packs) from the survey log, not by assumption
usage: survey_table.py FILES.LOG [--grep TEXT ...] [--failed] [--depth N] [--paths]   (--paths: every matching path, else counts per folder)
when: after a dev.log_files launch (J3 survey; any later "which file does the engine read" question); quote its output in the run report
not-a-verb: reads PC run output, writes a report table
"""
import argparse
import collections
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('log')
    ap.add_argument('--grep', action='append', default=[])
    ap.add_argument('--failed', action='store_true')
    ap.add_argument('--depth', type=int, default=3)
    ap.add_argument('--paths', action='store_true')
    a = ap.parse_args(argv)
    rows = []
    for line in open(a.log, encoding='utf-8', errors='replace'):
        f = line.rstrip('\r\n').split('\t')
        if len(f) < 8 or f[0] == 'utc':
            continue
        utc, api, redir, acc, disp, res, err, path = f[:8]
        if a.grep and not any(g.lower() in path.lower() for g in a.grep):
            continue
        if a.failed and res != 'FAILED':
            continue
        rows.append((utc, api, redir, res, err, path))
    if a.paths:
        for r in rows:
            print('\t'.join(r))
        return 0
    c = collections.Counter()
    for _, api, _, res, _, path in rows:
        p = path.replace('/', '\\').split('\\')
        c[('\\'.join(p[:a.depth]), api.split('.')[0], res)] += 1
    print('| folder | api | result | paths |')
    print('|---|---|---|---|')
    for (folder, api, res), n in sorted(c.items()):
        print(f'| {folder} | {api} | {res} | {n} |')
    return 0


if __name__ == '__main__':
    sys.exit(main())
