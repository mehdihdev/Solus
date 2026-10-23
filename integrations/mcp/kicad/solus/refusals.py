"""The error text a strict tool refusal carries: `<stable code>: <fixed explanation>`.

FastMCP turns the raised ValueError into `isError`, the companion forwards the
text, and SOL reads it — a bare code left the model guessing at the cause. The
explanations are fixed strings: never paths or design contents.
"""

REFUSAL_EXPLANATIONS = {
    "already_exists": "the target already exists; nothing was written",
    "ambiguous_target": "the reference or pin is not unique in the schematic or library",
    "cli_failed": "the installed kicad-cli failed to run the check",
    "file_too_large": "the file exceeds the size limit this tool will read",
    "guard_failed": "the file could not be read or written safely; nothing was changed",
    "invalid_arguments": "the arguments do not match the tool's schema",
    "invalid_erc_report": "kicad-cli produced an ERC report this tool cannot read",
    "invalid_geometry": "the coordinates or wire route are not valid for placement",
    "library_unavailable": "that symbol was not found in the installed KiCad libraries",
    "mutation_unverified": "the written file did not match the planned change; it was rolled back",
    "not_found": "the referenced symbol, pin, or wire was not found in the schematic",
    "path_escapes_workspace": "the path is outside the linked project workspace",
    "property_not_found": "the symbol has no property with that name",
    "reference_not_found": "no symbol with that reference exists in the schematic",
    "stale_plan": "the schematic or library changed since it was read; read it again and retry",
    "unsupported_symbol": "the symbol or schematic uses a construct this tool cannot edit "
    "safely (multi-unit symbol, or an embedded definition that differs from the installed library)",
    "unsupported_value": "an argument has an unsupported value or format",
}


def refusal_message(reason: str) -> str:
    explanation = REFUSAL_EXPLANATIONS.get(reason)
    return f"{reason}: {explanation}" if explanation else reason
