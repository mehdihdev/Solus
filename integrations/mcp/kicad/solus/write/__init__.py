"""`kicad.set_symbol_property` — the confirmation-gated write tool (SOLUSDEV-100 T2b).

This package is a targeted BYTE SPLICE on a `.kicad_sch` file's raw bytes,
never a library load/save: `tests/test_vendor_sch_api.py` proves the vendored
`kicad_sch_api.Schematic.load()/save_as()` round-trip is NOT byte-stable on
the Solus fixture (reformats, reorders, and re-resolves `lib_symbols` from the
local KiCad install), so a load/save write tool would silently rewrite a
customer's entire file around the one property the user asked to change.

Modules:
    sexpr       -- an owned S-expression tokenizer/parser yielding byte offsets
    escaping    -- KiCad string escaping/unescaping + round-trip provability
    locator     -- finds the exact byte span of one symbol property's value
    guard       -- re-parses before/after and confines the diff to that span
    atomic_write -- temp-file-in-same-dir + fsync + os.replace
    paths       -- workspace confinement + size cap for the target file
    errors      -- the stable refusal-reason vocabulary
    set_symbol_property -- orchestration + MCP tool registration
"""
