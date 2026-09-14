"""Official XML topology replaces incomplete regex reads without clipping evidence."""

import json

import pytest
import test_overlay_support  # noqa: F401

XML = b"""<export>
<components>
<comp ref="A1">
<value>Arduino_UNO_R3</value>
</comp>
<comp ref="RFSR1">
<value>FSR402 (generic resistive model)</value>
</comp>
<comp ref="R1">
<value>10000</value>
</comp>
<comp ref="FLG1">
<value>PWR_FLAG</value>
</comp>
</components>
<nets>
<net code="1" name="/+5V">
<node ref="A1" pin="5"/>
<node ref="RFSR1" pin="1"/>
</net>
<net code="2" name="/SENSE_A0">
<node ref="A1" pin="9"/>
<node ref="RFSR1" pin="2"/>
<node ref="R1" pin="1"/>
</net>
<net code="3" name="/GND">
<node ref="A1" pin="6"/>
<node ref="A1" pin="7"/>
<node ref="A1" pin="29"/>
<node ref="R1" pin="2"/>
<node ref="FLG1" pin="1"/>
</net>
<net code="4" name="unconnected-A1">
<node ref="A1" pin="4"/>
</net>
</nets>
</export>"""


def test_full_memberships_and_components_are_retained():
    from solus.netlist_reads import topology

    result = topology(XML)
    assert result["complete"] is True and result["component_count"] == 4
    assert set(result["components"]) == {"A1", "RFSR1", "R1", "FLG1"}
    assert {(n["component"], n["pin"]) for n in result["nets"]["/SENSE_A0"]} == {
        ("A1", "9"),
        ("RFSR1", "2"),
        ("R1", "1"),
    }
    assert result["net_count"] == 4 and "unconnected-A1" in result["nets"]
    assert len(json.dumps({"ok": True, "value": result})) <= 4000


@pytest.mark.parametrize(
    "bad",
    [
        b'<!DOCTYPE export [<!ENTITY x "boom">]><export/>',
        b'<export><components/><nets><net name="x">'
        b'<node ref="missing" pin="1"/></net></nets></export>',
        XML.replace(b"<value>10000</value>", b"<value>10000</value>").replace(
            b'comp ref="FLG1"', b'comp ref="R1"'
        ),
        XML.replace(b'pin="4"', b'pin="5"'),
        XML.replace(b'name="unconnected-A1"', b'name="/+5V"'),
        b"<export><untrusted><components/><nets/></untrusted></export>",
        b"<invalid/>",
        b"<export>",
    ],
)
def test_invalid_or_ambiguous_topology_refuses(bad):
    from solus.netlist_reads import topology

    with pytest.raises(ValueError):
        topology(bad)


def test_complete_encoded_result_refuses_before_prompt_clipping():
    from solus.netlist_reads import topology

    oversized = XML.replace(b"Arduino_UNO_R3", ("界" * 150).encode())
    # Repeat safe, independently named small components to exceed full envelope.
    components = b"".join(
        f'<comp ref="X{i}"><value>{"value" * 20}</value></comp>'.encode() for i in range(40)
    )
    oversized = oversized.replace(b"</components>", components + b"</components>")
    with pytest.raises(ValueError, match="topology_too_large"):
        topology(oversized)


def test_native_cli_unavailable_never_calls_legacy_parser(tmp_path, monkeypatch):
    from solus import netlist_reads

    monkeypatch.setattr(netlist_reads, "detect_kicad_cli", lambda: None)
    with pytest.raises(ValueError, match="authoritative_topology_unavailable"):
        netlist_reads.read_topology(tmp_path / "empty.kicad_sch")


def test_empty_value_is_valid_component_metadata():
    from solus.netlist_reads import topology

    result = topology(XML.replace(b"<value>10000</value>", b"<value/>"))
    assert result["components"]["R1"]["value"] == "" and result["complete"] is True


@pytest.mark.parametrize(
    "replacement",
    [
        b'<comp ref="A1"/><comp ref="A1"/>',
        b"<comp><value>x</value></comp>",
        b'<comp ref="A1"><value>a</value><value>b</value></comp>',
    ],
)
def test_invalid_component_definitions_refuse(replacement):
    from solus.netlist_reads import topology

    with pytest.raises(ValueError, match="invalid_native_topology"):
        topology(b"<export><components>" + replacement + b"</components><nets/></export>")


def test_size_and_membership_budgets_fail_closed():
    from solus.netlist_reads import topology

    cases = [
        b"x" * (32 * 1024 * 1024 + 1),
        b"<export><components>" + b'<comp ref="A1"/>' * 257 + b"</components><nets/></export>",
        b"<export><components/><nets>" + b'<net name="x"/>' * 513 + b"</nets></export>",
        b'<export><components><comp ref="A1"/></components><nets><net name="x">'
        + b"".join(f'<node ref="A1" pin="{i}"/>'.encode() for i in range(4097))
        + b"</net></nets></export>",
    ]
    for data in cases:
        with pytest.raises(ValueError, match="topology_too_large"):
            topology(data)


@pytest.mark.parametrize(
    "data",
    [
        b"\xff",
        b"<export>\x00</export>",
        b'<export><components/><nets><net name="empty"/></nets></export>',
    ],
)
def test_unusable_xml_and_empty_net_refuse(data):
    from solus.netlist_reads import topology

    with pytest.raises(ValueError, match="invalid_native_topology"):
        topology(data)


async def test_registered_read_handlers_use_same_confined_official_snapshot(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from solus import netlist_reads
    from solus.registration import register_allowlisted_tools
    from test_overlay_support import FakeMCP

    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(tmp_path))
    project = tmp_path / "sample.kicad_pro"
    project.write_text("{}")
    schematic = project.with_suffix(".kicad_sch")
    schematic.write_text("(kicad_sch)")
    captured = []

    @contextmanager
    def snapshot(path):
        captured.append(path)
        yield path

    monkeypatch.setattr(netlist_reads, "_schematic_snapshot", snapshot)
    monkeypatch.setattr(netlist_reads, "detect_kicad_cli", lambda: "/fixed/cli")
    monkeypatch.setattr(netlist_reads, "_cli_export", lambda cli, path, name: XML)
    server = FakeMCP()
    register_allowlisted_tools(server)
    first = await server.tools["extract_project_netlist"](project_path=str(project))
    second = await server.tools["analyze_schematic_connections"](schematic_path=str(schematic))
    assert first == second and first["complete"] is True
    assert captured == [schematic, schematic]
    monkeypatch.setattr(netlist_reads, "_cli_export", lambda *args: None)
    with pytest.raises(ValueError, match="authoritative_topology_unavailable"):
        await server.tools["analyze_schematic_connections"](schematic_path=str(schematic))
    with pytest.raises(ValueError, match="expected_project_path"):
        await server.tools["extract_project_netlist"](project_path=str(schematic))
    with pytest.raises(ValueError, match="expected_schematic_path"):
        await server.tools["analyze_schematic_connections"](schematic_path=str(project))
