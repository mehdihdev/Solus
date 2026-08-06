"""SOLUSDEV-216 — emit Pydantic's field names so TypeScript can be checked against them.

WHY. The drift guard claimed "a field added on either side breaks one of the two
suites". Code review disproved it: `satisfies` does excess-property checking only
on FRESH OBJECT LITERALS, and a fixture imported from `.json` is a variable, so a
value carrying EXTRA keys still satisfies the type. Verified — adding an
undeclared field to a fixture left `tsc` silent while renaming a required one
errored. Adding a field is the change six lanes will make most often.

Python already knows every field name. This test writes them to a committed
manifest and fails if the manifest is stale; the TypeScript suite asserts its own
exported `*_FIELDS` lists match it, and `CompleteKeysOf` proves those lists cover
the TS interfaces. The loop closes:

    Pydantic gains a field  -> manifest changes -> TS list mismatches   -> TS fails
    TS interface gains one  -> CompleteKeysOf forces it into the list   -> mismatch
    A fixture gains one     -> extra="forbid"                           -> Python fails
"""

import json
from pathlib import Path

from pydantic import BaseModel
from solus_api.contracts import action_gate, impact, tool_knowledge

FIXTURES = Path(__file__).resolve().parents[3] / "shared-types" / "fixtures"

CONTRACTS: dict[str, list[type[BaseModel]]] = {
    "action-gate": [action_gate.ToolConfirmationEvent, action_gate.DiffRow],
    "impact": [
        impact.ImpactResult,
        impact.ImpactNode,
        impact.ImpactFocus,
        impact.ImpactEntity,
        impact.ImpactPathStep,
        impact.Consequence,
        impact.ConsequenceEvidence,
        impact.SolAction,
    ],
    "tool-knowledge": [
        tool_knowledge.ToolKnowledge,
        tool_knowledge.Invocation,
        tool_knowledge.ScreenLocator,
    ],
}


def _manifest(models: list[type[BaseModel]]) -> dict[str, list[str]]:
    return {m.__name__: sorted(m.model_fields) for m in models}


def test_the_field_manifests_are_current() -> None:
    stale = []
    for contract, models in CONTRACTS.items():
        path = FIXTURES / contract / "_fields.json"
        expected = _manifest(models)
        committed = json.loads(path.read_text()) if path.is_file() else None
        if committed != expected:
            path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
            stale.append(str(path))
    assert not stale, (
        f"field manifests were stale and have been regenerated: {stale}. "
        "Commit them — the TypeScript suite checks its types against these."
    )
