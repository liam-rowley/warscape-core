"""A stand-in for a game's usage reader (W31): what `[jobs] usage_cmd` runs in tests/test_usage.py and in the report's proof.

Usage: fake_usage_cmd.py <mode> <job id>; the modes are the answers `wsc jobs usage` must take or refuse. The core never reads a transcript: this
script is the whole seam, and it prints numbers it was told to print.
"""
import json
import os
import sys
import time

mode, jid = sys.argv[1], sys.argv[2]
good = {'calls': 42, 'models': ['opus'], 'sessions': 2, 'note': f'fake reader for {jid} in {os.path.basename(os.getcwd())}'}
if mode == 'ok':
    print(json.dumps(good))
elif mode == 'fail':
    print('no transcripts here', file=sys.stderr)
    sys.exit(3)
elif mode == 'badjson':
    print('{"calls": 42,')
elif mode == 'missing':
    print(json.dumps({k: v for k, v in good.items() if k != 'sessions'}))
elif mode == 'sleep':
    time.sleep(30)
