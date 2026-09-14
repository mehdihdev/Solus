#!/usr/bin/env python3
"""Seed the tool-knowledge entries SOL's write tools act on (SOLUSDEV-251 / I4).

Tool knowledge is a GLOBAL, tenant-free table (ADR-033). The entries below are
vendor-documentation facts about the UI control each MCP write tool operates —
KiCad and Onshape controls, Git and Arduino commands, and Isaac standalone use —
admitted through the guard's docs path (which publishes directly because the
source is the vendor's own documentation). Idempotent: an existing live entry is
returned unchanged. Run once per database:

    uv run python scripts/seed-toolkb-mcp-controls.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "api" / "src"))

# Onshape retains the existing >=1.0 <2.0 lookup identity. It is a repository
# compatibility convention, not a verified SaaS release. SOL currently requests
# these notes without a version filter; do not infer release coverage from it.
# Execution notes use exact documented release windows, not guessed major-version
# coverage. Git and Arduino have distinct identities even though both use CODE.
# Isaac startup is mapped to the owned, graph-bound external simulator adapter.
ENTRIES = [
    (
        {
            "tool": "code",
            "version_range": ">=2.43.0 <2.43.1",
            "surface": "terminal",
            "control_id": "code.git.commit",
            "label": "git commit",
            "effect": "execute",
            "description": (
                "Records the staged index contents as a new commit with a log message."
            ),
            "provenance": "vendor_docs",
        },
        "https://git-scm.com/docs/git-commit/2.43.0",
    ),
    (
        {
            "tool": "code",
            "version_range": ">=2.43.0 <2.43.1",
            "surface": "terminal",
            "control_id": "code.git.push",
            "label": "git push",
            "effect": "execute",
            "description": (
                "Updates remote references and sends the repository objects needed "
                "to complete those updates."
            ),
            "provenance": "vendor_docs",
        },
        "https://git-scm.com/docs/git-push/2.43.0",
    ),
    (
        {
            "tool": "code",
            "version_range": ">=1.5.1 <1.5.2",
            "surface": "terminal",
            "control_id": "code.arduino.core_install",
            "label": "Arduino CLI core install",
            "effect": "execute",
            "description": (
                "Installs a board platform and its required tools. A version can be "
                "specified instead of installing the latest platform release."
            ),
            "provenance": "vendor_docs",
        },
        "https://docs.arduino.cc/arduino-cli/commands-reference/arduino-cli_core_install/",
    ),
    (
        {
            "tool": "code",
            "version_range": ">=1.5.1 <1.5.2",
            "surface": "terminal",
            "control_id": "code.arduino.compile",
            "label": "Arduino CLI compile",
            "effect": "execute",
            "description": (
                "Builds an Arduino sketch for the selected board. Compilation produces "
                "build artifacts; upload is a separate option."
            ),
            "provenance": "vendor_docs",
        },
        "https://docs.arduino.cc/arduino-cli/commands-reference/arduino-cli_compile/",
    ),
    (
        {
            "tool": "isaac",
            "version_range": ">=6.0.0 <6.0.1",
            "surface": "terminal",
            "control_id": "isaac.standalone.application",
            "label": "Standalone Python application",
            "effect": "execute",
            "description": (
                "Runs Isaac Sim from a standalone Python application. SimulationApp "
                "initializes the application, updates advance it, and close shuts it down."
            ),
            "provenance": "vendor_docs",
        },
        "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/"
        "core_api_tutorials/tutorial_core_hello_world.html",
    ),
    (
        {
            "tool": "kicad",
            "version_range": ">=8.0 <10.0",
            "surface": "dialog",
            "control_id": "kicad.eeschema.edit_symbol_properties",
            "label": "Symbol Properties",
            "effect": "modify_feature",
            "description": (
                "Edits one placed symbol's fields — Reference, Value, Footprint and custom "
                "properties — in the schematic editor; the change is saved with the schematic."
            ),
            "provenance": "vendor_docs",
        },
        "https://docs.kicad.org/9.0/en/eeschema/eeschema.html",
    ),
    (
        {
            "tool": "kicad",
            "version_range": ">=10.0 <11.0",
            "surface": "dialog",
            "control_id": "kicad.eeschema.edit_symbol_properties",
            "label": "Symbol Properties",
            "effect": "modify_feature",
            "description": (
                "Edits one placed symbol's fields — Reference, Value, Footprint and custom "
                "properties — in the schematic editor; the change is saved with the schematic."
            ),
            "provenance": "vendor_docs",
        },
        "https://docs.kicad.org/10.0/en/eeschema/eeschema.html",
    ),
    (
        {
            "tool": "onshape",
            "version_range": ">=1.0 <2.0",
            "surface": "panel",
            "control_id": "onshape.partstudio.variable_table",
            "label": "Variable Table",
            "effect": "modify_feature",
            "description": (
                "Creates, views, and edits variables in the current Part Studio. "
                "Variables referenced from another document are read-only in the inserted table."
            ),
            "provenance": "vendor_docs",
        },
        "https://cad.onshape.com/help/Content/PartStudio/variable_table.htm",
    ),
    (
        {
            "tool": "onshape",
            "version_range": ">=1.0 <2.0",
            "surface": "panel",
            "control_id": "onshape.partstudio.feature_list",
            "label": "Feature list",
            "effect": "create_feature",
            "description": (
                "Lists the ordered features in a Part Studio and provides access "
                "to edit and reorder them."
            ),
            "provenance": "vendor_docs",
        },
        "https://cad.onshape.com/help/Content/PartStudio/features_and_parts_lists.htm",
    ),
]


# Bounded vendor references for the supported Guide workflows. These do not
# grant execution capabilities. Release windows identify the cited manuals;
# no compatibility claim is made for untested releases or prerelease builds.
_REFERENCE_CONTROLS = [
    (
        "code",
        "code.git.status",
        "git status",
        "measure",
        "Shows staged changes relative to HEAD, unstaged changes relative to the index, "
        "and untracked files. Short output separates index and working-tree status; "
        "ignored files are normally omitted.",
        "https://git-scm.com/docs/git-status/2.43.0",
    ),
    (
        "code",
        "code.git.diff",
        "git diff",
        "measure",
        "Compares changes between the working tree, index, commits or other endpoints. "
        "Plain diff shows unstaged changes; --cached shows staged changes against HEAD. A "
        "diff compares endpoints rather than describing a range of commits.",
        "https://git-scm.com/docs/git-diff/2.43.0",
    ),
    (
        "code",
        "code.git.log",
        "git log",
        "navigate",
        "Displays commit history reachable from selected revisions. Revision limits and "
        "path filters narrow the results; patch and statistics options explain what each "
        "commit changed. Inspecting history does not create a commit.",
        "https://git-scm.com/docs/git-log/2.43.0",
    ),
    (
        "code",
        "code.git.show",
        "git show",
        "navigate",
        "Displays one or more Git objects. For a commit it shows the log message and "
        "textual change; trees list entries and blobs show contents. A selected revision "
        "identifies recorded content independently of current working-tree edits.",
        "https://git-scm.com/docs/git-show/2.43.0",
    ),
    (
        "code",
        "code.git.branch",
        "git branch",
        "select",
        "Lists branches when no creation or deletion action is requested. A branch name "
        "creates a pointer but does not switch the working tree. Remote-tracking branches "
        "describe locally recorded remote state, which can be stale.",
        "https://git-scm.com/docs/git-branch/2.43.0",
    ),
    (
        "code",
        "code.git.remote",
        "git remote",
        "settings",
        "Lists configured remotes without a subcommand. Verbose output includes "
        "addresses, and get-url inspects configured fetch or push addresses. Adding, "
        "removing or changing a remote changes configuration; update can fetch from the "
        "network.",
        "https://git-scm.com/docs/git-remote/2.37.0",
    ),
    (
        "kicad",
        "kicad.eeschema.wire",
        "Wire",
        "create_feature",
        "Connects symbol pins and wires into an electrical net. A crossing is not always "
        "a junction: connections depend on endpoints and junction placement. Use "
        "electrical connectivity inspection rather than visual proximity to determine the "
        "resulting net.",
        "https://docs.kicad.org/10.0/en/eeschema/eeschema.html",
    ),
    (
        "kicad",
        "kicad.eeschema.net_label",
        "Net Label",
        "create_feature",
        "Names the net at the label attachment point. Matching local labels connect "
        "within a schematic sheet; global labels span the hierarchy. The attachment point "
        "must touch a wire or pin. Text placed nearby does not establish an electrical "
        "connection.",
        "https://docs.kicad.org/10.0/en/eeschema/eeschema.html",
    ),
    (
        "kicad",
        "kicad.eeschema.erc",
        "Electrical Rules Checker",
        "execute",
        "Checks schematic electrical rules such as conflicting pin types, unconnected "
        "pins and undriven power inputs. Severity settings and exclusions affect reported "
        "issues. A clean ERC report does not establish current capacity, component "
        "ratings or physical correctness.",
        "https://docs.kicad.org/10.0/en/eeschema/eeschema.html",
    ),
    (
        "kicad",
        "kicad.eeschema.symbol_chooser",
        "Choose Symbol",
        "select",
        "Searches configured symbol libraries and previews the selected symbol before "
        "placement. Library identity selects the symbol definition; a placed reference "
        "identifies an instance. Symbol selection and footprint assignment are separate "
        "decisions.",
        "https://docs.kicad.org/10.0/en/eeschema/eeschema.html",
    ),
    (
        "isaac",
        "isaac.urdf.import",
        "URDF Importer",
        "import",
        "Converts a robot description into a USD articulation. Import options control "
        "base fixation, joint merging, drive configuration and collision approximation. "
        "Visual meshes alone do not establish physically accurate collision geometry or "
        "stable joint control.",
        "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/importer_exporter/ext_isaacsim_asset_importer_urdf.html",
    ),
    (
        "isaac",
        "isaac.articulation.position_drive",
        "Position Drive",
        "modify_feature",
        "Uses joint targets with stiffness and damping to drive an articulation through "
        "physics. Setting a target differs from directly assigning a joint position. "
        "Actual positions can differ under load, so inspect tracking and tune the drives "
        "instead of assuming command completion means arrival.",
        "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/py/source/extensions/isaacsim.core.experimental.prims/docs/index.html",
    ),
    (
        "isaac",
        "isaac.articulation.joint_limits",
        "Joint Limits",
        "settings",
        "Defines lower and upper limits for articulation degrees of freedom. Revolute "
        "joint values use radians in the Python articulation API. Limits constrain the "
        "modeled joint; they do not certify mechanical safety or replace inspection of "
        "actual joint positions.",
        "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/py/source/extensions/isaacsim.core.experimental.prims/docs/index.html",
    ),
    (
        "isaac",
        "isaac.sensor.contact",
        "Contact Sensor",
        "measure",
        "Reports contact readings from physics and can expose raw body identities and "
        "impulses. Sensor validity, force and contact geometry must be interpreted "
        "together. Contact with an unrelated surface or a momentary collision does not "
        "demonstrate that an object remains grasped.",
        "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/py/source/extensions/isaacsim.sensors.experimental.physics/docs/index.html",
    ),
    (
        "isaac",
        "isaac.transform.local_pose",
        "Local Pose",
        "modify_feature",
        "Sets translation and orientation relative to the parent transform. Local "
        "coordinates differ from world coordinates when the parent moves or rotates. The "
        "Python prim API represents quaternion orientation in scalar-first order; read "
        "back the pose in the intended frame.",
        "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/py/source/extensions/isaacsim.core.experimental.prims/docs/index.html",
    ),
    (
        "isaac",
        "isaac.physics.stepping",
        "Physics Step",
        "execute",
        "Advances physics using the configured simulation time step. Rendering and "
        "physics clocks are distinct; changing render rate alone does not create "
        "additional physics substeps. Articulated joint targets evolve through physics "
        "rather than through teleported transforms.",
        "https://docs.isaacsim.omniverse.nvidia.com/6.0.0/robot_simulation/robot_simulation_tips.html",
    ),
]

for family, control_id, label, effect, description, url in _REFERENCE_CONTROLS:
    ENTRIES.append(
        (
            {
                "tool": family,
                "version_range": {
                    "code": ">=2.43.0 <2.43.1",
                    "kicad": ">=10.0 <11.0",
                    "isaac": ">=6.0.0 <6.0.1",
                }[family],
                "surface": "terminal" if family in {"code", "isaac"} else "dialog",
                "control_id": control_id,
                "label": label,
                "effect": effect,
                "description": description,
                "provenance": "vendor_docs",
            },
            url,
        )
    )


def select_entries(families: list[str] | None) -> list[tuple[dict[str, str], str]]:
    allowed = {entry["tool"] for entry, _ in ENTRIES}
    if families is not None and not set(families) <= allowed:
        raise ValueError("Unknown tool family")
    return [(entry, url) for entry, url in ENTRIES if families is None or entry["tool"] in families]


async def seed(families: list[str] | None = None) -> int:
    from dotenv import load_dotenv
    from solus_api.core.config import Settings
    from solus_api.core.db import build_engine, build_sessionmaker
    from solus_api.toolkb.guard import IngestContext, IngestRejectedError, ingest
    from solus_api.toolkb.schema import AcquisitionMethod

    load_dotenv(REPO_ROOT / ".env")
    settings = Settings(_env_file=REPO_ROOT / ".env")  # type: ignore[call-arg]
    engine = build_engine(settings.database_url)
    sessionmaker = build_sessionmaker(engine)
    seeded = 0
    entries = select_entries(families)
    async with sessionmaker() as session:
        for entry, doc_url in entries:
            try:
                row = await ingest(
                    session,
                    entry=entry,
                    ctx=IngestContext(acquired_via=AcquisitionMethod.DOCS, doc_url=doc_url),
                )
            except IngestRejectedError as exc:
                print(f"REFUSED {entry['control_id']}: {exc}")
                continue
            print(f"{row.status.value:9} {entry['tool']:8} {entry['control_id']}")
            seeded += 1
        await session.commit()
    await engine.dispose()
    return 0 if seeded == len(entries) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--family", action="append", choices=sorted({e["tool"] for e, _ in ENTRIES})
    )
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(seed(arguments.family)))
