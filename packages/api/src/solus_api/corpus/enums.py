"""Closed vocabularies of the engineering corpus (docs/schemas/corpus-chunk.md §4).

Every categorical field on a chunk is one of these enums. Adding a value is a
C-series ticket that edits the schema document and the fixtures together — the
contract suite asserts the two halves match member for member.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from typing import Final


class CorpusDomain(enum.StrEnum):
    """The five engineering domains (SCOPE.md §4). Distinct from the graph's
    `models.Domain`: the corpus is knowledge, the graph is a robot."""

    MECHANICAL = "mechanical"
    ELECTRICAL = "electrical"
    SOFTWARE = "software"
    SYSTEMS = "systems"
    ROBOTICS = "robotics"


class Topic(enum.StrEnum):
    """The 41 topics of SCOPE.md §4.1–4.5, each bound to one domain (TOPIC_DOMAIN)."""

    # mechanical
    GDT = "gdt"
    FITS_TOLERANCES = "fits_tolerances"
    FASTENERS = "fasteners"
    MATERIAL_SELECTION = "material_selection"
    MACHINING_CONSTRAINTS = "machining_constraints"
    BEARINGS_SHAFTS = "bearings_shafts"
    MECHANISMS = "mechanisms"
    # electrical
    TRACE_WIDTH_CURRENT = "trace_width_current"
    CLEARANCE_CREEPAGE = "clearance_creepage"
    DECOUPLING = "decoupling"
    GROUNDING = "grounding"
    EMI_BASICS = "emi_basics"
    POWER_DESIGN = "power_design"
    WIRE_GAUGE = "wire_gauge"
    CONNECTOR_SELECTION = "connector_selection"
    SIGNAL_INTEGRITY = "signal_integrity"
    BUS_ADDRESSING = "bus_addressing"
    ANALOG_FRONTEND = "analog_frontend"
    MOTOR_DRIVE_ELECTRICAL = "motor_drive_electrical"
    PCB_LAYOUT_BASICS = "pcb_layout_basics"
    # software
    EMBEDDED_PATTERNS = "embedded_patterns"
    REAL_TIME_CONSTRAINTS = "real_time_constraints"
    EMBEDDED_TESTING = "embedded_testing"
    ROS_CONVENTIONS = "ros_conventions"
    BUILD_AND_TOOLCHAIN = "build_and_toolchain"
    SERIAL_PROTOCOLS = "serial_protocols"
    FIRMWARE_DEPLOYMENT = "firmware_deployment"
    # systems
    POWER_BUDGET = "power_budget"
    THERMAL_BUDGET = "thermal_budget"
    SAFETY_INTERLOCKS = "safety_interlocks"
    ENCLOSURE_INGRESS = "enclosure_ingress"
    CABLING_HARNESS = "cabling_harness"
    SYSTEM_INTEGRATION = "system_integration"
    # robotics
    ACTUATOR_SELECTION = "actuator_selection"
    KINEMATICS_BASICS = "kinematics_basics"
    DYNAMICS_BASICS = "dynamics_basics"
    SENSOR_FUSION_BASICS = "sensor_fusion_basics"
    CONTROL_TUNING = "control_tuning"
    PERCEPTION_BASICS = "perception_basics"
    SIMULATION_FIDELITY = "simulation_fidelity"
    LOCOMOTION_BASICS = "locomotion_basics"


def _bind(domain: CorpusDomain, *topics: Topic) -> dict[Topic, CorpusDomain]:
    return dict.fromkeys(topics, domain)


TOPIC_DOMAIN: Final[Mapping[Topic, CorpusDomain]] = {
    **_bind(
        CorpusDomain.MECHANICAL,
        Topic.GDT,
        Topic.FITS_TOLERANCES,
        Topic.FASTENERS,
        Topic.MATERIAL_SELECTION,
        Topic.MACHINING_CONSTRAINTS,
        Topic.BEARINGS_SHAFTS,
        Topic.MECHANISMS,
    ),
    **_bind(
        CorpusDomain.ELECTRICAL,
        Topic.TRACE_WIDTH_CURRENT,
        Topic.CLEARANCE_CREEPAGE,
        Topic.DECOUPLING,
        Topic.GROUNDING,
        Topic.EMI_BASICS,
        Topic.POWER_DESIGN,
        Topic.WIRE_GAUGE,
        Topic.CONNECTOR_SELECTION,
        Topic.SIGNAL_INTEGRITY,
        Topic.BUS_ADDRESSING,
        Topic.ANALOG_FRONTEND,
        Topic.MOTOR_DRIVE_ELECTRICAL,
        Topic.PCB_LAYOUT_BASICS,
    ),
    **_bind(
        CorpusDomain.SOFTWARE,
        Topic.EMBEDDED_PATTERNS,
        Topic.REAL_TIME_CONSTRAINTS,
        Topic.EMBEDDED_TESTING,
        Topic.ROS_CONVENTIONS,
        Topic.BUILD_AND_TOOLCHAIN,
        Topic.SERIAL_PROTOCOLS,
        Topic.FIRMWARE_DEPLOYMENT,
    ),
    **_bind(
        CorpusDomain.SYSTEMS,
        Topic.POWER_BUDGET,
        Topic.THERMAL_BUDGET,
        Topic.SAFETY_INTERLOCKS,
        Topic.ENCLOSURE_INGRESS,
        Topic.CABLING_HARNESS,
        Topic.SYSTEM_INTEGRATION,
    ),
    **_bind(
        CorpusDomain.ROBOTICS,
        Topic.ACTUATOR_SELECTION,
        Topic.KINEMATICS_BASICS,
        Topic.DYNAMICS_BASICS,
        Topic.SENSOR_FUSION_BASICS,
        Topic.CONTROL_TUNING,
        Topic.PERCEPTION_BASICS,
        Topic.SIMULATION_FIDELITY,
        Topic.LOCOMOTION_BASICS,
    ),
}


class Kind(enum.StrEnum):
    PRINCIPLE = "principle"
    PROCEDURE = "procedure"
    RULE_OF_THUMB = "rule_of_thumb"
    REFERENCE_VALUE = "reference_value"
    PITFALL = "pitfall"
    GLOSSARY = "glossary"


class Audience(enum.StrEnum):
    """Depth level; SOL mode ranks between them (SCOPE.md §3, ADR-016)."""

    FUNDAMENTALS = "fundamentals"
    REFERENCE = "reference"


class ApplicabilityKey(enum.StrEnum):
    """SCOPE.md §6 — the closed keys a project's `.solus` may declare."""

    VOLTAGE_CLASS = "voltage_class"
    FABRICATION_CLASS = "fabrication_class"
    PROCESS = "process"
    MCU_FAMILY = "mcu_family"
    ROS_DISTRO = "ros_distro"
    BUS = "bus"
    ENVIRONMENT = "environment"
    UNIT_SYSTEM = "unit_system"


APPLICABILITY_VALUES: Final[Mapping[ApplicabilityKey, frozenset[str]]] = {
    ApplicabilityKey.VOLTAGE_CLASS: frozenset({"elv_lt_50v", "lv_50_1000v"}),
    ApplicabilityKey.FABRICATION_CLASS: frozenset({"hobby", "prototype", "production"}),
    ApplicabilityKey.PROCESS: frozenset(
        {"fdm", "sla", "cnc_mill", "cnc_lathe", "sheet_metal", "pcb_2l", "pcb_4l"}
    ),
    ApplicabilityKey.MCU_FAMILY: frozenset(
        {"avr", "stm32", "esp32", "rp2040", "nrf52", "jetson", "raspberry_pi"}
    ),
    ApplicabilityKey.ROS_DISTRO: frozenset({"humble", "jazzy", "rolling"}),
    ApplicabilityKey.BUS: frozenset({"i2c", "spi", "uart", "can", "rs485", "usb", "ethernet"}),
    ApplicabilityKey.ENVIRONMENT: frozenset({"indoor", "outdoor", "wet", "dusty", "vibration"}),
    ApplicabilityKey.UNIT_SYSTEM: frozenset({"si", "imperial"}),
}


class Derivation(enum.StrEnum):
    VERBATIM = "verbatim"
    SUMMARY = "summary"
    FACTS_EXTRACTED = "facts_extracted"
    SOLUS_ORIGINAL = "solus_original"


class SourceClass(enum.StrEnum):
    """LICENSING.md §4 classes. There is deliberately NO customer, community,
    model, or other value — EXCLUDE-class sources have no way to be recorded."""

    SOLUS_AUTHORED = "solus_authored"
    US_GOVERNMENT_WORK = "us_government_work"
    OPEN_LICENSE_PERMISSIVE = "open_license_permissive"
    OPEN_LICENSE_RESTRICTED = "open_license_restricted"
    VENDOR_DOCUMENTATION = "vendor_documentation"
    DATASHEET = "datasheet"
    STANDARDS_BODY = "standards_body"
    OPEN_SOURCE_PROJECT_DOCS = "open_source_project_docs"
    ACADEMIC_PAPER = "academic_paper"


class SourceLicense(enum.StrEnum):
    """SPDX identifiers plus the corpus vocabulary values (LICENSING.md §5)."""

    CC0_1_0 = "CC0-1.0"
    CC_BY_2_5 = "CC-BY-2.5"
    CC_BY_3_0 = "CC-BY-3.0"
    CC_BY_4_0 = "CC-BY-4.0"
    MIT = "MIT"
    BSD_2_CLAUSE = "BSD-2-Clause"
    BSD_3_CLAUSE = "BSD-3-Clause"
    APACHE_2_0 = "Apache-2.0"
    ISC = "ISC"
    CC_BY_SA_3_0 = "CC-BY-SA-3.0"
    CC_BY_SA_4_0 = "CC-BY-SA-4.0"
    CC_BY_NC_4_0 = "CC-BY-NC-4.0"
    CC_BY_NC_SA_4_0 = "CC-BY-NC-SA-4.0"
    CC_BY_NC_ND_4_0 = "CC-BY-NC-ND-4.0"
    CC_BY_ND_4_0 = "CC-BY-ND-4.0"
    GFDL_1_3_ONLY = "GFDL-1.3-only"
    GPL_2_0_ONLY = "GPL-2.0-only"
    GPL_3_0_ONLY = "GPL-3.0-only"
    PUBLIC_DOMAIN_US_GOV = "public-domain-us-gov"
    VENDOR_TERMS = "vendor-terms"
    DATASHEET_TERMS = "datasheet-terms"
    STANDARD_SUMMARY = "standard-summary"
    ARXIV_NONEXCLUSIVE = "arxiv-nonexclusive"
    SOLUS_PROPRIETARY = "solus-proprietary"
    UNKNOWN = "unknown"


#: Licences whose text may ship verbatim (schema §4 "SHIP licences").
SHIP_LICENSES: Final[frozenset[SourceLicense]] = frozenset(
    {
        SourceLicense.CC0_1_0,
        SourceLicense.CC_BY_2_5,
        SourceLicense.CC_BY_3_0,
        SourceLicense.CC_BY_4_0,
        SourceLicense.MIT,
        SourceLicense.BSD_2_CLAUSE,
        SourceLicense.BSD_3_CLAUSE,
        SourceLicense.APACHE_2_0,
        SourceLicense.ISC,
        SourceLicense.PUBLIC_DOMAIN_US_GOV,
        SourceLicense.SOLUS_PROPRIETARY,
    }
)

_CC_BY: Final = frozenset(
    {
        SourceLicense.CC_BY_2_5,
        SourceLicense.CC_BY_3_0,
        SourceLicense.CC_BY_4_0,
    }
)
_PERMISSIVE_SOFTWARE: Final = frozenset(
    {
        SourceLicense.MIT,
        SourceLicense.BSD_2_CLAUSE,
        SourceLicense.BSD_3_CLAUSE,
        SourceLicense.APACHE_2_0,
        SourceLicense.ISC,
    }
)
#: Licences whose verbatim excerpts must carry a rendered attribution (rule 6).
ATTRIBUTION_REQUIRED: Final[frozenset[SourceLicense]] = _CC_BY | _PERMISSIVE_SOFTWARE
_RESTRICTED_OPEN: Final = frozenset(
    {
        SourceLicense.CC_BY_SA_3_0,
        SourceLicense.CC_BY_SA_4_0,
        SourceLicense.CC_BY_NC_4_0,
        SourceLicense.CC_BY_NC_SA_4_0,
        SourceLicense.CC_BY_NC_ND_4_0,
        SourceLicense.CC_BY_ND_4_0,
        SourceLicense.GFDL_1_3_ONLY,
    }
)
_CC_BY_NC: Final = frozenset(
    {
        SourceLicense.CC_BY_NC_4_0,
        SourceLicense.CC_BY_NC_SA_4_0,
        SourceLicense.CC_BY_NC_ND_4_0,
    }
)
#: Real SPDX identifiers — everything that is not corpus vocabulary.
SPDX_LICENSES: Final[frozenset[SourceLicense]] = frozenset(SourceLicense) - frozenset(
    {
        SourceLicense.PUBLIC_DOMAIN_US_GOV,
        SourceLicense.VENDOR_TERMS,
        SourceLicense.DATASHEET_TERMS,
        SourceLicense.STANDARD_SUMMARY,
        SourceLicense.ARXIV_NONEXCLUSIVE,
        SourceLicense.SOLUS_PROPRIETARY,
        SourceLicense.UNKNOWN,
    }
)

#: Rule 1, licence half: the licences each source class may record.
CLASS_LICENSES: Final[Mapping[SourceClass, frozenset[SourceLicense]]] = {
    SourceClass.SOLUS_AUTHORED: frozenset({SourceLicense.SOLUS_PROPRIETARY}),
    SourceClass.US_GOVERNMENT_WORK: frozenset({SourceLicense.PUBLIC_DOMAIN_US_GOV}),
    SourceClass.OPEN_LICENSE_PERMISSIVE: frozenset({SourceLicense.CC0_1_0})
    | _CC_BY
    | _PERMISSIVE_SOFTWARE,
    SourceClass.OPEN_LICENSE_RESTRICTED: _RESTRICTED_OPEN,
    SourceClass.VENDOR_DOCUMENTATION: frozenset({SourceLicense.VENDOR_TERMS}),
    SourceClass.DATASHEET: frozenset({SourceLicense.DATASHEET_TERMS}),
    SourceClass.STANDARDS_BODY: frozenset({SourceLicense.STANDARD_SUMMARY}),
    SourceClass.OPEN_SOURCE_PROJECT_DOCS: SPDX_LICENSES,
    SourceClass.ACADEMIC_PAPER: _CC_BY | _CC_BY_NC | frozenset({SourceLicense.ARXIV_NONEXCLUSIVE}),
}

_NON_VERBATIM: Final = frozenset({Derivation.SUMMARY, Derivation.FACTS_EXTRACTED})
_ANY_SOURCED: Final = _NON_VERBATIM | frozenset({Derivation.VERBATIM})

#: Rule 1, derivation half. Verbatim additionally requires a SHIP licence (rule 2),
#: which is what makes "verbatim only if the licence is a SHIP licence" hold for the
#: project-docs and academic rows without a special case here.
CLASS_DERIVATIONS: Final[Mapping[SourceClass, frozenset[Derivation]]] = {
    SourceClass.SOLUS_AUTHORED: frozenset({Derivation.SOLUS_ORIGINAL}),
    SourceClass.US_GOVERNMENT_WORK: _ANY_SOURCED,
    SourceClass.OPEN_LICENSE_PERMISSIVE: _ANY_SOURCED,
    SourceClass.OPEN_LICENSE_RESTRICTED: _NON_VERBATIM,
    SourceClass.VENDOR_DOCUMENTATION: _NON_VERBATIM,
    SourceClass.DATASHEET: _NON_VERBATIM,
    SourceClass.STANDARDS_BODY: frozenset({Derivation.SUMMARY}),
    SourceClass.OPEN_SOURCE_PROJECT_DOCS: _ANY_SOURCED,
    SourceClass.ACADEMIC_PAPER: _ANY_SOURCED,
}


class ConfidenceBasis(enum.StrEnum):
    STANDARD_DERIVED = "standard_derived"
    VENDOR_STATED = "vendor_stated"
    GOVERNMENT_PUBLISHED = "government_published"
    PEER_REVIEWED = "peer_reviewed"
    SOLUS_MEASURED = "solus_measured"
    RULE_OF_THUMB = "rule_of_thumb"
    CONSENSUS = "consensus"


class Drafting(enum.StrEnum):
    HUMAN = "human"
    LLM_ASSISTED = "llm_assisted"


class Status(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class License(enum.StrEnum):
    """The chunk's OUTGOING licence. One value; a second is a policy change."""

    SOLUS_PROPRIETARY = "solus-proprietary"
