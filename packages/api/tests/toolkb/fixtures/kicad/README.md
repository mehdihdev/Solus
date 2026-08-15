# KiCad TOOL_ACTION source fixtures (SOLUS-TU-02)

`sch_actions_9.0.cpp` is the verbatim KiCad 9.0 eeschema tool-action source
(`eeschema/tools/sch_actions.cpp`), fetched from
<https://gitlab.com/kicad/code/kicad/-/raw/9.0/eeschema/tools/sch_actions.cpp>,
its GPLv3 header intact.

It is a **test fixture parsed at test time**, not linked into or shipped with
any Solus product. It is the reproducible corpus behind the TU-02 KiCad
documentation-ingestion path (`solus_api.toolkb.ingest.kicad`): the `TOOL_ACTION`
definitions are the authoritative, machine-precise, vendor-pure catalog of
KiCad commands (name, friendly label, tooltip, default hotkey), keyed to
version 9.0.

⚠ **Human sign-off flagged (completion report):** vendoring GPLv3 source as a
committed test fixture in this repo — confirm the licensing posture is
acceptable, or switch the ingestion path to fetch the source at deploy time
instead of committing it.
