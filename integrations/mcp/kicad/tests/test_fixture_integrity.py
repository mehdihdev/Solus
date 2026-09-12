"""Integrity tests for the committed `solus_sample` KiCad project fixture (SOLUSDEV-100 T3).

The fixture is the whole-surface sample for the KiCad connector family: a real
KiCad 9 schematic (`.kicad_sch` S-expression, version header 20250114), its
project file, and its hand-authored `kicad-cli sch export netlist --format
kicadxml` output — committed so every test exercising SOLUSDEV-100 runs
without KiCad installed.

These tests pin the invariants that make the fixture trustworthy:

* the schematic is a balanced KiCad 9 S-expression with a `lib_symbols` section;
* the netlist parses through the REAL parser
  (`solus_api.connectors.kicad_netlist.parse_kicad_netlist`) with ZERO warnings
  and maps through `build_graph` with zero errors;
* schematic and netlist agree exactly on the refdes→MPN roster (the
  metadata-extraction §5.2 `modality_hints.part_number` channel), and every
  component carries the §5.2 identity channels;
* the I2C bus is real: SDA/SCL nets carry the MCU, the IMU, and the pull-ups;
* both path resolvers (`integrations/.../tests/paths.py` and
  `packages/api/tests/fixtures/kicad_project.py`) return identical absolute
  paths — one copy of the fixture on disk;
* the large ArtifactRef-path variant is byte-identical to its committed
  deterministic generator's output (drift is impossible) and sits in the
  512 KiB – 1 MiB window.

The S-expression check uses the ~20-line pure-python tokenizer below — no new
dependencies (CLAUDE.md §4/§7).
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import paths
import pytest
from solus_api.connectors.eda import build_graph
from solus_api.connectors.kicad_netlist import parse_kicad_netlist

# ------------------------------------------------------------- expected roster

#: The spec-derived truth: reference designator → manufacturer part number.
#: Both the schematic (`MPN` property) and the netlist (`<property name="MPN">`)
#: must carry exactly this set.
EXPECTED_MPN: dict[str, str] = {
    "U1": "STM32F030F4P6",  # MCU, TSSOP-20
    "U2": "MPU-6050",  # I2C IMU, QFN-24
    "R1": "RC0603FR-074K7L",  # SDA pull-up 4.7k
    "R2": "RC0603FR-074K7L",  # SCL pull-up 4.7k
    "R3": "RC0603FR-0710KL",  # NRST pull-up 10k
    "C1": "CL10B104KB8NNNC",  # MCU decoupling 100nF
    "C2": "CL10B104KB8NNNC",  # IMU decoupling 100nF
    "C3": "CL10B222KB8NNNC",  # IMU CPOUT 2.2nF
    "C4": "CL10B104KB8NNNC",  # IMU REGOUT 100nF
}

#: (designator, pin) membership of the I2C bus nets.
EXPECTED_SDA_NODES = {("U1", "18"), ("U2", "24"), ("R1", "2")}
EXPECTED_SCL_NODES = {("U1", "17"), ("U2", "23"), ("R2", "2")}

KICAD9_SCH_VERSION = "20250114"

LARGE_MIN_BYTES = 512 * 1024
LARGE_MAX_BYTES = 1024 * 1024


# --------------------------------------------------------- tiny S-expr reader


def _tokens(text: str) -> Iterator[str]:
    """Tokenize an S-expression: parens, quoted strings (with escapes), atoms."""
    i, size = 0, len(text)
    while i < size:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
        elif ch in "()":
            yield ch
            i += 1
        elif ch == '"':
            j = i + 1
            while j < size and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j >= size:
                raise ValueError("unterminated string literal")
            yield text[i : j + 1]
            i = j + 1
        else:
            j = i
            while j < size and text[j] not in ' \t\r\n()"':
                j += 1
            yield text[i:j]
            i = j


SexprNode = str | list["SexprNode"]


def parse_sexpr(text: str) -> list[SexprNode]:
    """Parse S-expression text into nested lists; raises ValueError on imbalance."""
    stack: list[list[SexprNode]] = [[]]
    for token in _tokens(text):
        if token == "(":
            stack.append([])
        elif token == ")":
            if len(stack) == 1:
                raise ValueError("unbalanced ')'")
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(token[1:-1] if token.startswith('"') else token)
    if len(stack) != 1:
        raise ValueError(f"{len(stack) - 1} unclosed '('")
    return stack[0]


def _named_children(node: list[SexprNode], name: str) -> list[list[SexprNode]]:
    return [child for child in node if isinstance(child, list) and child[:1] == [name]]


def _symbol_properties(symbol: list[SexprNode]) -> dict[str, str]:
    return {
        str(prop[1]): str(prop[2]) for prop in _named_children(symbol, "property") if len(prop) >= 3
    }


def _schematic_refdes_to_mpn(sch_root: list[SexprNode]) -> dict[str, str]:
    """refdes → MPN for every placed real component (power symbols excluded)."""
    roster: dict[str, str] = {}
    for symbol in _named_children(sch_root, "symbol"):
        props = _symbol_properties(symbol)
        reference = props.get("Reference", "")
        if not reference or reference.startswith("#"):
            continue  # power symbols / unannotated
        roster[reference] = props.get("MPN", "<missing MPN>")
    return roster


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ schematic


def test_schematic_is_balanced_kicad9_sexpr(solus_sample_schematic_text: str) -> None:
    root_nodes = parse_sexpr(solus_sample_schematic_text)

    assert len(root_nodes) == 1, "schematic must be one top-level S-expression"
    root = root_nodes[0]
    assert isinstance(root, list) and root[0] == "kicad_sch"
    versions = _named_children(root, "version")
    assert versions and versions[0][1] == KICAD9_SCH_VERSION
    assert _named_children(root, "uuid"), "schematic must carry a root uuid"
    assert _named_children(root, "lib_symbols"), "schematic must embed lib_symbols"
    assert _named_children(root, "wire"), "I2C wiring must be drawn, not implied"
    labels = {str(label[1]) for label in _named_children(root, "label")}
    assert {"SDA", "SCL"} <= labels, "I2C net labels must exist on wires"


def test_project_file_is_valid_and_named_for_the_schematic(
    solus_sample_project_path: Path,
) -> None:
    project = json.loads(solus_sample_project_path.read_text(encoding="utf-8"))

    assert project["meta"]["filename"] == "solus_sample.kicad_pro"
    assert solus_sample_project_path.with_suffix(".kicad_sch").is_file()


# -------------------------------------------------------------------- netlist


def test_netlist_parses_through_real_parser_with_zero_warnings(
    solus_sample_netlist_text: str,
) -> None:
    netlist = parse_kicad_netlist(solus_sample_netlist_text)

    assert netlist.warnings == ()
    assert {c.designator for c in netlist.components} == set(EXPECTED_MPN)


def test_netlist_maps_to_graph_without_errors(solus_sample_netlist_text: str) -> None:
    netlist = parse_kicad_netlist(solus_sample_netlist_text)

    entities, relations, errors = build_graph(netlist)

    assert errors == []
    assert {e.source_key for e in entities if e.type == "component"} == set(EXPECTED_MPN)
    assert relations, "net connectivity must produce connected_to edges"


def test_every_component_carries_the_section_5_2_identity_channels(
    solus_sample_netlist_text: str,
) -> None:
    netlist = parse_kicad_netlist(solus_sample_netlist_text)

    for component in netlist.components:
        assert component.part_number == EXPECTED_MPN[component.designator]
        assert component.schematic_symbol_name, f"{component.designator} lacks libsource part"
    by_ref = {c.designator: c for c in netlist.components}
    assert by_ref["U1"].datasheet_ref and by_ref["U1"].datasheet_ref.startswith("http")
    assert by_ref["U2"].datasheet_ref and by_ref["U2"].datasheet_ref.startswith("http")


def test_schematic_and_netlist_agree_on_refdes_and_mpn(
    solus_sample_schematic_text: str, solus_sample_netlist_text: str
) -> None:
    root_nodes = parse_sexpr(solus_sample_schematic_text)
    root = root_nodes[0]
    assert isinstance(root, list)
    schematic_roster = _schematic_refdes_to_mpn(root)

    netlist = parse_kicad_netlist(solus_sample_netlist_text)
    netlist_roster = {c.designator: c.part_number for c in netlist.components}

    assert schematic_roster == EXPECTED_MPN
    assert netlist_roster == EXPECTED_MPN


def test_i2c_bus_nets_carry_mcu_imu_and_pullups(solus_sample_netlist_text: str) -> None:
    netlist = parse_kicad_netlist(solus_sample_netlist_text)
    nets = {net.name: net for net in netlist.nets}

    sda = {(node.designator, node.pin) for node in nets["SDA"].nodes}
    scl = {(node.designator, node.pin) for node in nets["SCL"].nodes}

    assert sda == EXPECTED_SDA_NODES
    assert scl == EXPECTED_SCL_NODES


def test_power_nets_reach_both_ics_and_decoupling(solus_sample_netlist_text: str) -> None:
    netlist = parse_kicad_netlist(solus_sample_netlist_text)
    nets = {net.name: {(n.designator, n.pin) for n in net.nodes} for net in netlist.nets}

    assert {("U1", "16"), ("U2", "13"), ("C1", "1"), ("C2", "1")} <= nets["+3V3"]
    assert {("U1", "15"), ("U2", "18"), ("C1", "2"), ("C2", "2")} <= nets["GND"]
    # AD0 strapped to GND — the IMU answers at I2C address 0x68.
    assert ("U2", "9") in nets["GND"]


# ------------------------------------------------------------------ resolvers


def test_both_resolvers_return_identical_absolute_existing_paths() -> None:
    api_module = _load_module(
        paths.REPO_ROOT / "packages" / "api" / "tests" / "fixtures" / "kicad_project.py",
        "kicad_project_under_test",
    )

    for name in (
        "REPO_ROOT",
        "SOLUS_SAMPLE_DIR",
        "SOLUS_SAMPLE_PRO",
        "SOLUS_SAMPLE_SCH",
        "SOLUS_SAMPLE_NETLIST",
        "SOLUS_SAMPLE_LARGE_NETLIST",
    ):
        ours, theirs = getattr(paths, name), getattr(api_module, name)
        assert ours == theirs, f"{name} diverges between the two resolvers"
        assert Path(ours).is_absolute()
        assert Path(ours).exists(), f"{name} -> {ours} does not exist"


# -------------------------------------------------------------- large variant


@pytest.fixture(scope="module")
def large_generator() -> ModuleType:
    return _load_module(paths.FIXTURES_DIR / "gen_large_fixture.py", "gen_large_fixture_under_test")


def test_large_netlist_is_byte_identical_to_its_generator(
    large_generator: ModuleType, solus_sample_large_netlist_path: Path
) -> None:
    committed = solus_sample_large_netlist_path.read_bytes()

    regenerated = large_generator.build_text().encode("utf-8")

    assert committed == regenerated, "committed large fixture drifted from its generator"


def test_large_netlist_sits_in_the_artifactref_size_window(
    solus_sample_large_netlist_path: Path,
) -> None:
    size = solus_sample_large_netlist_path.stat().st_size

    assert LARGE_MIN_BYTES < size < LARGE_MAX_BYTES, f"{size} bytes outside (512KiB, 1MiB)"


def test_large_netlist_parses_with_zero_warnings(
    solus_sample_large_netlist_text: str,
) -> None:
    netlist = parse_kicad_netlist(solus_sample_large_netlist_text)

    assert netlist.warnings == ()
    assert len(netlist.components) > 100
    assert all(c.part_number for c in netlist.components)


# --- fixtures (moved from the deleted tests/conftest.py: a bare-named
# 'conftest' module here collides in sys.modules with packages/api/tests'
# conftest under a whole-repo pytest run — SOLUSDEV-100 integration fix) ---


@pytest.fixture(scope="session")
def solus_sample_dir() -> Path:
    return paths.SOLUS_SAMPLE_DIR


@pytest.fixture(scope="session")
def solus_sample_project_path() -> Path:
    return paths.SOLUS_SAMPLE_PRO


@pytest.fixture(scope="session")
def solus_sample_schematic_path() -> Path:
    return paths.SOLUS_SAMPLE_SCH


@pytest.fixture(scope="session")
def solus_sample_netlist_path() -> Path:
    return paths.SOLUS_SAMPLE_NETLIST


@pytest.fixture(scope="session")
def solus_sample_large_netlist_path() -> Path:
    return paths.SOLUS_SAMPLE_LARGE_NETLIST


@pytest.fixture(scope="session")
def solus_sample_schematic_text() -> str:
    return paths.SOLUS_SAMPLE_SCH.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def solus_sample_netlist_text() -> str:
    return paths.SOLUS_SAMPLE_NETLIST.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def solus_sample_large_netlist_text() -> str:
    return paths.SOLUS_SAMPLE_LARGE_NETLIST.read_text(encoding="utf-8")
