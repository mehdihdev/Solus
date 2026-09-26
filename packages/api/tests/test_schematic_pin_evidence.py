"""Schematic pin functions are observed data, never model-name guesses."""

import uuid

import pytest
from solus_api.connectors.eda import build_graph
from solus_api.connectors.kicad_netlist import merge_pin_functions, parse_kicad_netlist
from solus_api.core.errors import APIError
from solus_api.hardware.presence import PreparePresence
from solus_api.hardware.presence_topology import WiringRequest, WiringService
from solus_api.models import Domain, GraphEdge, GraphEntity, Project, Source, SourceType
from test_firmware_presence import fixture_service


@pytest.mark.parametrize(
    "text",
    [
        '<export><components><comp ref="U1"/><comp ref="R1"/></components>'
        '<nets><net name="sense"><node ref="U1" pin="3" pinfunction="A0"/>'
        '<node ref="R1" pin="1"/></net></nets></export>',
        "(export (components (comp (ref U1)) (comp (ref R1))) "
        "(nets (net (name sense) (node (ref U1) (pin 3) (pinfunction A0)) "
        "(node (ref R1) (pin 1)))))",
    ],
)
def test_exported_pin_functions_reach_graph(text):
    _, edges, errors = build_graph(parse_kicad_netlist(text))
    assert not errors
    board = next(edge for edge in edges if edge.from_key == "U1")
    sensor = next(edge for edge in edges if edge.from_key == "R1")
    assert board.properties["pins"] == ["3"]
    assert board.properties["pin_functions"] == {"3": "A0"}
    assert "pin_functions" not in sensor.properties


@pytest.mark.parametrize(
    "observed_pin,relation,expected",
    [("A0", "connected_to", True), ("A1", "connected_to", False), ("A0", "depends_on", False)],
)
async def test_schematic_wiring_requires_exact_connected_pin(
    client, alice_headers, db, tmp_path, observed_pin, relation, expected
):
    presence, robot, brain = await fixture_service(client, alice_headers, db, tmp_path)
    project = await db.get(Project, presence.project_id)
    source = Source(
        project_id=project.id,
        team_id=project.team_id,
        type=SourceType.KICAD,
        name="Wiring evidence",
        config={},
        status="connected",
    )
    db.add(source)
    await db.flush()
    parts = [
        GraphEntity(
            project_id=project.id,
            source_id=source.id,
            source_connector="kicad",
            external_ref=name,
            origin="connector",
            domain=Domain.ELECTRICAL,
            kind=kind,
            name=name,
            attrs={},
        )
        for name, kind in [("U1", "component"), ("R1", "component"), ("sense", "net")]
    ]
    db.add_all(parts)
    await db.flush()
    edges = [
        GraphEdge(
            project_id=project.id,
            source_id=source.id,
            src_id=parts[index].id,
            dst_id=parts[2].id,
            relation_type=relation if index == 0 else "connected_to",
            origin="connector",
            domain_pair="electrical:electrical",
            attrs={"pins": ["3"], "pin_functions": {"3": observed_pin}}
            if index == 0
            else {"pins": ["1"]},
        )
        for index in range(2)
    ]
    db.add_all(edges)
    await db.commit()
    body = WiringRequest.model_validate(
        {
            "profile_id": "uno_avr",
            "mode": "schematic",
            "source_id": source.id,
            "wiring": [
                {
                    "channel": "sense.raw",
                    "pin": "A0",
                    "kind": "analog_input",
                    "component_entity_id": parts[0].id,
                    "connected_entity_id": parts[1].id,
                }
            ],
        }
    )
    service = WiringService(presence)
    if expected:
        proposal = await service.propose(robot, brain, body)
        assert proposal["wiring"][0]["pin"] == "A0"
        await service.accept(robot, brain, uuid.UUID(proposal["proposal_id"]), proposal["digest"])
        inputs, _ = await presence._wiring(
            robot,
            brain,
            PreparePresence(
                profile_id="uno_avr",
                kind="topology",
                channel="uptime",
                wiring_proposal_id=proposal["proposal_id"],
            ),
        )
        assert inputs == [{"channel": "sense.raw", "pin": "A0", "kind": "analog_input"}]
        edges[0].attrs = {"pins": ["3"], "pin_functions": {"3": "A1"}}
        await db.flush()
        with pytest.raises(APIError):
            await service.accept(
                robot, brain, uuid.UUID(proposal["proposal_id"]), proposal["digest"]
            )
    else:
        with pytest.raises(APIError) as exc:
            await service.propose(robot, brain, body)
        assert exc.value.code == "wiring_unproven"


@pytest.mark.parametrize(
    "text",
    [
        '<export><components><comp ref="U1"/></components><nets><net name="sense">'
        '<node ref="U1" pin="3" pinfunction="A1"/>'
        '<node ref="U1" pin="3" pinfunction="A0"/></net></nets></export>',
        "(export (components (comp (ref U1))) (nets (net (name sense)"
        "(node (ref U1) (pin 3) (pinfunction A1))"
        "(node (ref U1) (pin 3) (pinfunction A0)))))",
    ],
)
def test_conflicting_pin_names_never_select_last_declaration(text):
    _, edges, _ = build_graph(parse_kicad_netlist(text))
    assert "pin_functions" not in edges[0].properties


@pytest.mark.parametrize(
    "names,expected",
    [
        (["A0", "A0"], "A0"),
        (["A0", "A1", "A0"], None),
        (["A1", "A0", "A0"], None),
        ([None, "A0"], None),
        (["A0", None], None),
    ],
)
def test_duplicate_pin_evidence_stays_ambiguous_after_conflict(names, expected):
    functions = merge_pin_functions(("U1", "3", name) for name in names)
    assert functions == {("U1", "3"): expected}
