#!/usr/bin/env python3
"""esf_map.py: generic, offset-based walker for semantic maps of an ESF save (no tree objects, so a 30 MB save stays cheap).

purpose: library for a game's save map: navigate records by name, read values by child position @N, find record paths, and grep every value that equals an id
usage: from esf_map import Save; s = Save(path); s.sub(span, 'NAME'); s.vals(span)[N]; s.items(span, 'ARRAY'); s.path('WORLD', 'FACTION_ARRAY')  |  python3 -I saves/core/esf_map.py SAVE id ID
when: writing a game's semantic map (a game repo's save_map.py) or chasing an id through a save (both ends of every link); field meanings live in saves/SAVE_FORMAT.md
not-a-verb: a game-agnostic library and id grep run on the PC against saves outside the repo (warscape-core candidate, D10)

Ported from the generic half of empire-remastered rml_mod/tools/db/esf_map.py (J14); that game's record paths stayed behind.
A span is (start, end) of a record's children; @N counts every child (records too), as esf_diff and esf_dump print it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esf_dump import Esf, find, root_span  # noqa: E402

FIX = 1 << 20  # positions are 12.20 fixed point map units (LOCOMOTABLE, residences, in both PFH0 titles seen)


class Save:
    def __init__(self, path):
        self.e = Esf(path)
        self.rn, self.o, self.end = root_span(self.e)

    def root(self):
        return (self.o, self.end)

    def kids(self, span):
        return list(self.e.children(span[0], span[1]))

    def sub(self, span, name, nth=0):
        """span of the nth child record (or (items, ver) of a record array) named name, or None"""
        for k, n, p in self.e.children(span[0], span[1]):
            if n == name:
                if nth == 0:
                    return p[:2] if k == 'rec' else p
                nth -= 1
        return None

    def chain(self, span, *names):
        for n in names:
            span = self.sub(span, n)
            if span is None:
                raise KeyError('/'.join(names))
        return span

    def items(self, span, name):
        """[(start, end)] of the items of the record array name below span ([] when absent)"""
        p = self.sub(span, name)
        return p[0] if p else []

    def item_rec(self, item):
        """the (name, span) of the single record an array item wraps (FACTION_ARRAY[i] -> FACTION)"""
        for k, n, p in self.e.children(item[0], item[1]):
            if k == 'rec':
                return n, p[:2]
        return None, item

    def vals(self, span):
        """child position @N -> value, for the value children of span"""
        return {i: p for i, (k, n, p) in enumerate(self.e.children(span[0], span[1])) if k == 'val'}

    def path(self, *names):
        """every hit of a record path suffix: [(kind, name path, payload)]"""
        h = []
        find(self.e, self.o, self.end, [self.rn], list(names), h)
        return h


def grep_id(s, want, span=None, path='', out=None, skip=('CAI_INTERFACE', 'CAMPAIGN_PATHFINDER', 'QUAD_TREE_BIT_ARRAY')):
    """every value path@N equal to want (or a list holding it), outside the skipped records: the links an id takes part in"""
    out = [] if out is None else out
    span = span or s.root()
    for i, (k, n, p) in enumerate(s.e.children(span[0], span[1])):
        if k == 'val':
            if p == want or (isinstance(p, list) and want in p):
                out.append('%s@%d' % (path, i))
        elif n in skip:
            continue
        elif k == 'rec':
            grep_id(s, want, p[:2], '%s/%s' % (path, n), out, skip)
        else:
            for j, it in enumerate(p[0]):
                grep_id(s, want, it, '%s/%s[%d]' % (path, n, j), out, skip)
    return out


def main():
    if len(sys.argv) != 4 or sys.argv[2] != 'id':
        sys.exit('usage: esf_map.py SAVE id ID')
    s = Save(sys.argv[1])
    for line in grep_id(s, int(sys.argv[3], 0)):
        print(line)


if __name__ == '__main__':
    main()
