"""The vocabulary of `graph_entity.kind` (SOLUSDEV-320, ADR-027 amendment).

`kind` is a free string column; this module is the one list of the values the API writes.
Modules that predate it keep their local constant for now and are held equal to these by
`tests/test_kinds.py`. New modules import from here.
"""

from __future__ import annotations

from typing import Final

# electrical / code / mechanical (connectors)
PART: Final[str] = "part"
COMPONENT: Final[str] = "component"
NET: Final[str] = "net"
CODE_FILE: Final[str] = "code_file"
CODE_MODULE: Final[str] = "code_module"
CODE_REPO: Final[str] = "code_repo"
LOCAL_CLONE: Final[str] = "local_clone"
LOCAL_FOLDER: Final[str] = "local_folder"
ARDUINO_SKETCH: Final[str] = "arduino_sketch"
PYTHON_REQUIREMENT: Final[str] = "python_requirement"
PACKAGE_REQUIREMENT: Final[str] = "package_requirement"
CAD_DOCUMENT: Final[str] = "cad_document"
DESIGN_EXPORT: Final[str] = "design_export"
CANONICAL_PART: Final[str] = "canonical_part"

# hardware
PHYSICAL_ROBOT: Final[str] = "physical_robot"
ROBOT_CATEGORY: Final[str] = "robot_category"
HARDWARE_CONFIG: Final[str] = "hardware_config"
HARDWARE_BRAIN: Final[str] = "hardware_brain"
HARDWARE_BUS: Final[str] = "hardware_bus"
HARDWARE_EVIDENCE: Final[str] = "hardware_evidence"
HARDWARE_PRESENCE_PLAN: Final[str] = "hardware_presence_plan"
HARDWARE_WIRING_PROPOSAL: Final[str] = "hardware_wiring_proposal"
#: Legacy camel case; stored in dev DBs, so renaming it is a data migration.
COMPANION_DEPLOYMENT_PLAN: Final[str] = "companionDeploymentPlan"

# .solus tree
SOLUS_CONFIG: Final[str] = "solus_config"
SOLUS_SECTION: Final[str] = "solus_section"
SOLUS_SUBSECTION: Final[str] = "solus_subsection"
SOLUS_NOTE: Final[str] = "solus_note"
SOLUS_ERROR: Final[str] = "solus_error"
SOLUS_GOAL: Final[str] = "solus_goal"
SOLUS_CONSTRAINT: Final[str] = "solus_constraint"
SOLUS_PROJECT_TOML: Final[str] = "solus_project_toml"
DOCUMENT: Final[str] = "document"

# live bench / simulation
BENCH_RUN: Final[str] = "bench_run"
BENCH_SCENE_MODEL: Final[str] = "bench_scene_model"
BENCH_SCENE_CAD_IMPORT: Final[str] = "bench_scene_cad_import"
SIMULATION_MODEL: Final[str] = "simulation_model"
#: What one simulation run found about one subject (SOLUSDEV-321 P4-T1, `simulation/sim_facts.py`).
SIM_RESULT: Final[str] = "sim_result"

# software (SOLUSDEV-321 P6, `software/ros_reader.py`): a ROS workspace's launched nodes and the
# topics their modules declare; `graph/inference/ros_edges.py` joins them.
ROS_NODE: Final[str] = "ros_node"
ROS_TOPIC: Final[str] = "ros_topic"

# workspace layer
WORKSPACE: Final[str] = "solus:workspace"
LIVE_BENCH: Final[str] = "solus:live_bench"
WIDGET: Final[str] = "solus:widget"
SOURCING_RULES: Final[str] = "sourcing_rules"

# SOLUSDEV-320
FINDING: Final[str] = "finding"
MACHINE: Final[str] = "machine"
MEMBER: Final[str] = "member"

#: Nodes that describe another entity and carry its name (`Hardware config — servo 3`, a sim
#: result's `stress_mpa — bracket`). They are context for that entity, never a second candidate
#: for its name (SOLUSDEV-321).
DESCRIPTOR_KINDS: Final[frozenset[str]] = frozenset(
    {
        HARDWARE_CONFIG,
        HARDWARE_EVIDENCE,
        HARDWARE_PRESENCE_PLAN,
        HARDWARE_WIRING_PROPOSAL,
        SIM_RESULT,
    }
)

ALL_KINDS: Final[frozenset[str]] = frozenset(
    value
    for name, value in dict(globals()).items()
    if name.isupper() and isinstance(value, str) and name != "ALL_KINDS"
)
