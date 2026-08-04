"""`kicad.set_symbol_property` orchestration + MCP tool registration (T2b).

Pipeline, each stage refusing (never partially writing) on failure:

    resolve_confined_schematic_path  -> path_escapes_workspace, file_too_large
    locate_property_value            -> reference_not_found, property_not_found,
                                         ambiguous_target, file_too_large (M5:
                                         a sexpr resource guard tripped)
    encode_kicad_string              -> unsupported_value
    verify_byte_stable_splice        -> guard_failed
    atomic_write                     -> (only reached once every guard above passes)

Registered since commit 0785fa8 through `solus/registration.py`
(`register_write_tools`, `solus/roster.py::WRITE_ROSTER`) — see
`SECURITY_REVIEW.md`'s "2026-08-03 — Reconciliation" section.

M5: the tool wrapper also maps `RecursionError` and `OSError` (from
stat/read/atomic-write races, permissions, disk full, ...) to a clean
refusal — defense in depth so NO exception type other than `RefusalError`
ever escapes this tool, even though the pipeline above (an iterative sexpr
parser with explicit token-count/nesting-depth guards) should no longer
raise either on its own.
"""

from typing import Any

from solus.trimming import SupportsToolDecorator
from solus.write.atomic_write import atomic_write
from solus.write.errors import REASON_GUARD_FAILED, REASON_UNSUPPORTED_VALUE, RefusalError
from solus.write.escaping import encode_kicad_string
from solus.write.guard import verify_byte_stable_splice
from solus.write.locator import locate_property_value
from solus.write.paths import resolve_confined_schematic_path

RESULT_KEYS = frozenset(
    {"changed", "reference", "property", "old_value", "new_value", "bytes_before", "bytes_after"}
)


def _result(
    *,
    changed: bool,
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
    schematic_path: str, reference: str, property_name: str, value: str
) -> dict[str, Any]:
    """Splice one symbol property's value in a `.kicad_sch` file.

    Returns the plan-locked result shape on success (`changed` reflects
    whether a write actually happened — a no-op request leaves the file
    untouched and returns `changed: false`). Raises `RefusalError` — never
    any other exception type — on every rejection path.
    """
    path = resolve_confined_schematic_path(schematic_path)
    original = path.read_bytes()
    located = locate_property_value(original, reference, property_name)
    old_value = located.old_value

    if value == old_value:
        return _result(
            changed=False,
            reference=reference,
            property_name=property_name,
            old_value=old_value,
            new_value=old_value,
            bytes_before=len(original),
            bytes_after=len(original),
        )

    try:
        new_literal = encode_kicad_string(value)
    except ValueError as exc:
        raise RefusalError(REASON_UNSUPPORTED_VALUE) from exc

    spliced = original[: located.start] + new_literal + original[located.end :]
    verify_byte_stable_splice(original, spliced, located.start, located.end, old_value, value)
    atomic_write(path, spliced)

    return _result(
        changed=True,
        reference=reference,
        property_name=property_name,
        old_value=old_value,
        new_value=value,
        bytes_before=len(original),
        bytes_after=len(spliced),
    )


def register_write_tools(mcp: SupportsToolDecorator) -> None:
    """Register the confirmation-gated `set_symbol_property` write tool
    through the same `TrimmingRegistrar` surface every other tool uses."""

    @mcp.tool()
    async def set_symbol_property(
        schematic_path: str, reference: str, property: str, value: str
    ) -> dict[str, Any]:
        """Splice one symbol property's value in a KiCad schematic file.

        Confirmation-gated (allowlist.yaml: requires_confirmation true): a
        targeted byte splice on the raw file, never a library load/save, so
        every other byte in the file is guaranteed untouched. On refusal
        (never a partial write) the result carries `changed: false` and a
        stable `reason`: reference_not_found, property_not_found,
        ambiguous_target, path_escapes_workspace, file_too_large,
        unsupported_value, or guard_failed.
        """
        try:
            return set_symbol_property_impl(schematic_path, reference, property, value)
        except RefusalError as exc:
            reason = exc.reason
        except (RecursionError, OSError):
            # M5: neither is one of the seven stable reasons; the closest
            # honest bucket is that we could not safely verify/complete the
            # operation — the same bucket a splice-guard failure gets.
            reason = REASON_GUARD_FAILED
        return {
            **_result(
                changed=False,
                reference=reference,
                property_name=property,
                old_value=None,
                new_value=None,
                bytes_before=None,
                bytes_after=None,
            ),
            "reason": reason,
        }
