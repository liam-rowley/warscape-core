#!/usr/bin/env python3
# purpose: Entry point of the warscape-core CLI: puts the core on sys.path and runs the `wsc` verbs (reg, find, gates, plus a repo's own verbs).
# usage: python3 wsc.py <verb> ...   (from a game repo with the core at core/: python3 core/wsc.py <verb> ...; `--help` lists the verbs)
# when: every registry change, lookup or gate run; it is the only way into the core.
# not-a-verb: it is the launcher every verb runs through.
import os
import sys

if sys.version_info < (3, 12):
    sys.exit(f'wsc needs Python 3.12 or newer (this is {sys.version.split()[0]})')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from warscape.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
