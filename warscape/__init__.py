"""warscape-core: the shared registry framework, CLI (`wsc`) and gates for the Total War remasters.

Library package. The CLI entry point is `wsc.py` at the core root; verbs live in `warscape/verbs/`.
Standard library only (Python 3.12+), so CI needs no installs.
"""
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parent.parent


def core_version():
    try:
        return (CORE_ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    except OSError:
        return 'unknown'
