"""SOLUSDEV-321 P2-T2 — the live-signal rules: pure functions of one part's window
(`rule_base.WindowContext`) that return hits for the window evaluator (P2-T3) to raise as findings.
`SIGNAL_RULES` is every one of them, family by family.

Shared code: it names a quantity, a relation and a limit, never a product, a vendor or a
simulator (the hygiene ratchets sweep this package).
"""

from typing import Final

from solus_api.livebench.findings.rules.body_rules import BODY_RULES
from solus_api.livebench.findings.rules.command_rules import COMMAND_RULES
from solus_api.livebench.findings.rules.electrical_rules import ELECTRICAL_RULES
from solus_api.livebench.findings.rules.prediction_rules import PREDICTION_RULES
from solus_api.livebench.findings.rules.rule_base import SignalRule
from solus_api.livebench.findings.rules.sensor_rules import SENSOR_RULES
from solus_api.livebench.findings.rules.tracking_rules import TRACKING_RULES

SIGNAL_RULES: Final[tuple[SignalRule, ...]] = (
    *COMMAND_RULES,
    *TRACKING_RULES,
    *BODY_RULES,
    *ELECTRICAL_RULES,
    *SENSOR_RULES,
    *PREDICTION_RULES,
)
