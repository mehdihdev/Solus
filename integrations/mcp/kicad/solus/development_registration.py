"""Register only the owned schematic operations, with protocol-level refusals."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from solus.development.models import DevelopmentError
from solus.trimming import SupportsToolDecorator

DESCRIPTIONS = {
    "get_symbol_definition": "Read an installed library symbol's actual pins and fingerprint. "
    "Use its exact library_id and library_fingerprint when proposing placement.",
    "get_schematic_geometry": "Read schematic symbols, transformed pin positions, wires, labels "
    "and the current file fingerprint. Read before proposing a schematic change.",
    "check_erc": "Run the installed KiCad electrical rules checker on a saved schematic. "
    "Returns actual findings; unavailable checks never count as passing.",
    "create_schematic": "Create one new standalone schematic sheet. Requires the target to be "
    "absent and explicit approval. dry_run shows the exact proposed sheet without writing.",
    "add_symbol": "Place one real installed library symbol in a schematic. Read the library and "
    "schematic first; supply both fingerprints. Requires approval; dry_run writes nothing.",
    "add_wire": "Connect two observed pins or existing wire endpoints with an orthogonal wire. "
    'Each start/end is {"pin":{"reference":"R1","pin_number":"1"}} or '
    '{"wire_uuid":"observed UUID","endpoint":0}; endpoint is integer 0 or 1. '
    'pin_number must be a string. Optional via is [{"x_mm":100.0,"y_mm":50.0}]. '
    "Use the current schematic fingerprint. Requires approval; dry_run writes nothing.",
    "add_net_label": "Add a net label at an observed pin or wire endpoint. Use the current file "
    'fingerprint. anchor is {"pin":{"reference":"R1","pin_number":"1"}} or '
    '{"wire_uuid":"observed UUID","endpoint":0}; endpoint is integer 0 or 1 and '
    "pin_number must be a string. "
    "Requires approval; dry_run writes nothing.",
    "mark_no_connect": "Mark one intentionally unused observed pin as not connected. Refuses "
    'connected pins. pin is {"reference":"R1","pin_number":"1"}; pin_number must be '
    "a string. Requires the current file fingerprint and approval; dry_run writes nothing.",
}


def _guard(function: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    @wraps(function)
    def guarded(**kwargs: Any) -> dict[str, Any]:
        try:
            return function(**kwargs)
        except DevelopmentError as exc:
            # FastMCP turns exceptions into isError, which the companion maps to
            # a failed ToolResult. A plain refusal dict would look successful.
            raise ValueError(exc.reason) from None
        except (OSError, RecursionError):
            raise ValueError("guard_failed") from None

    guarded_metadata: Any = guarded
    guarded_metadata._solus_strict_refusals = True
    return guarded


def register_development_tools(mcp: SupportsToolDecorator) -> None:
    from solus.development.erc import check_erc
    from solus.development.schematic import (
        add_symbol,
        create_schematic,
        get_schematic_geometry,
        get_symbol_definition,
    )
    from solus.development.wiring import add_net_label, add_wire, mark_no_connect

    for function in (
        get_symbol_definition,
        get_schematic_geometry,
        check_erc,
        create_schematic,
        add_symbol,
        add_wire,
        add_net_label,
        mark_no_connect,
    ):
        mcp.tool(description=DESCRIPTIONS[function.__name__])(_guard(function))
