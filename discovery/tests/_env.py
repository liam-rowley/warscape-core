"""Test environment for the discovery host tests (W4): the module folder and proxy/tools on the path, and the fixture adapter
(null_adapter/games.json: games "tgt" and "ref") as the discovery adapter, so no test depends on any real game repo.

purpose: set sys.path and WSP_DISCOVERY_ADAPTER for the discovery host tests; imported first by each test file
usage: import _env  (then import the modules under test; _env.CORE is the core's root)
when: every file in discovery/tests
not-a-verb: a test helper under a tests folder, which wsc.toml [tools] exempts
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1]
ADAPTER = HERE / 'null_adapter'
os.environ['WSP_DISCOVERY_ADAPTER'] = str(ADAPTER)
for p in (CORE / 'discovery', CORE / 'proxy' / 'tools'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
