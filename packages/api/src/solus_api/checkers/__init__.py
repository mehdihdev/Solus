"""Compatibility checkers (SOLUS-CHK-01, SOLUSDEV-115).

The cross-domain catch logic: pure-function rules over the linked graph (LNK) + canonical
parts (FP) that flag integration bugs spanning domains — a wrong op-amp, a sensor-frequency
clash across circuit and code, a supply that cannot meet its load. See
``docs/contracts/checker-interface.md``.
"""

from solus_api.checkers.interface import (
    Checker,
    Severity,
    Warning,
    run_checkers,
    severity_rank,
)

__all__ = [
    "Checker",
    "Severity",
    "Warning",
    "run_checkers",
    "severity_rank",
]
