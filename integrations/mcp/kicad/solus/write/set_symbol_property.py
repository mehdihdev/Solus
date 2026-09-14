"""State-bound, byte-stable property edits through the confined schematic publisher."""

from typing import Any

from solus.development.common import finish, original_for
from solus.development.models import DevelopmentError
from solus.development.plan import MutationPlan
from solus.trimming import SupportsToolDecorator
from solus.write.errors import REASON_GUARD_FAILED, REASON_UNSUPPORTED_VALUE, RefusalError
from solus.write.escaping import encode_kicad_string
from solus.write.guard import verify_byte_stable_splice
from solus.write.locator import locate_property_value

RESULT_KEYS = frozenset(
    {"changed", "reference", "property", "old_value", "new_value", "bytes_before", "bytes_after"}
)


def _result(
    *,
    changed: bool | None,
    reference: str,
    property_name: str,
    old_value: str | None,
    new_value: str | None,
    bytes_before: int | None,
    bytes_after: int | None,
) -> dict[str, Any]:
    return {
        "changed": changed,
        "reference": reference,
        "property": property_name,
        "old_value": old_value,
        "new_value": new_value,
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
    }


def set_symbol_property_impl(
    schematic_path: str,
    reference: str,
    property_name: str,
    value: str,
    expected_fingerprint: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Plan a bounded byte splice; publish only against the observed file digest."""
    if not isinstance(expected_fingerprint, str):
        raise DevelopmentError("stale_plan")
    original = original_for(schematic_path, expected_fingerprint)
    located = locate_property_value(original, reference, property_name)
    old_value = located.old_value
    try:
        new_literal = encode_kicad_string(value)
    except ValueError as exc:
        raise RefusalError(REASON_UNSUPPORTED_VALUE) from exc
    spliced = original[: located.start] + new_literal + original[located.end :]
    if old_value == value:
        spliced = original
    else:
        verify_byte_stable_splice(original, spliced, located.start, located.end, old_value, value)
    plan = MutationPlan.build(
        schematic_path,
        original,
        spliced,
        {"reference": reference, "property": property_name, "value": value},
        [{"label": f"{reference} · {property_name}", "before": old_value, "after": value}],
    )
    result = finish(plan, dry_run, [])
    return {
        **result,
        **_result(
            changed=original != spliced,
            reference=reference,
            property_name=property_name,
            old_value=old_value,
            new_value=value,
            bytes_before=len(original),
            bytes_after=len(spliced),
        ),
        "verified": not dry_run,
    }


def register_write_tools(mcp: SupportsToolDecorator) -> None:
    """Register the confirmation-gated `set_symbol_property` write tool
    through the same `TrimmingRegistrar` surface every other tool uses."""

    async def set_symbol_property(
        schematic_path: str,
        reference: str,
        property: str,
        value: str,
        expected_fingerprint: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Preview or apply one existing property using a fresh schematic fingerprint.

        Obtain expected_fingerprint from get_schematic_geometry. Dry runs show
        the complete bounded old/new value without writing. Execution rechecks
        file state and verifies byte readback. Missing/stale state refuses;
        mutation_unverified means a publication may already have happened.
        """
        try:
            return set_symbol_property_impl(
                schematic_path, reference, property, value, expected_fingerprint, dry_run
            )
        except (RefusalError, DevelopmentError) as exc:
            reason = exc.reason
        except (RecursionError, OSError):
            # M5: neither is one of the seven stable reasons; the closest
            # honest bucket is that we could not safely verify/complete the
            # operation — the same bucket a splice-guard failure gets.
            reason = REASON_GUARD_FAILED
        raise ValueError(reason)

    strict: Any = set_symbol_property
    strict._solus_strict_refusals = True
    mcp.tool()(set_symbol_property)
