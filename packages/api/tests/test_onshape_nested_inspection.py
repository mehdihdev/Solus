"""SOL can inspect coaxial geometry through verified nested occurrences."""

import copy

import pytest
from solus_api.connectors.contracts import ConnectorError
from test_onshape_assembly_geometry import MATRIX, inspect, root, setup


def nested_root():
    payload = root()
    main = payload["rootAssembly"]
    child = main["instances"].pop()
    assembly = {
        "id": "sub",
        "type": "Assembly",
        "suppressed": False,
        "configuration": "default",
        "documentId": "doc",
        "elementId": "nested",
        "documentMicroversion": "nestedRev",
    }
    main["instances"].append(assembly)
    shifted = list(MATRIX)
    shifted[11] += 0.01
    main["occurrences"][1] = {"path": ["sub", child["id"]], "transform": shifted}
    main["occurrences"].append({"path": ["sub"], "transform": MATRIX})
    payload["subAssemblies"] = [
        {
            "documentId": "doc",
            "elementId": "nested",
            "documentMicroversion": "nestedRev",
            "configuration": "default",
            "instances": [child],
        }
    ]
    return payload


async def test_nested_coaxial_pairs_use_observed_global_transform_without_double_composition():
    result = await inspect(setup(nested_root()), include_nested=True, view="coaxial_circles")
    assert result["total"] == 1
    pair = result["items"][0]
    members = {tuple(m["occurrence_path"]): m for m in pair["members"]}
    assert members[("sub", "instance/2")]["center"] == pytest.approx([0.01, 0.02, 0.04])
    assert pair["axial_separation_m"] == pytest.approx(0.01)
    assert "mate_type" not in pair
    assert result["coverage"]["inspected_instances"] == 2


async def test_existing_default_keeps_nested_exclusion_explicit():
    result = await inspect(setup(nested_root()))
    assert result["coverage"]["excluded"]["nested"] == 1
    assert result["coverage"]["inspected_instances"] == 1


@pytest.mark.parametrize("fault", ["revision", "untracked", "duplicate", "path", "configured"])
async def test_unverified_nested_identity_refuses_before_donor_fetch(fault):
    payload = nested_root()
    if fault == "revision":
        payload["subAssemblies"][0]["documentMicroversion"] = "wrong"
    elif fault == "untracked":
        payload["rootAssembly"]["instances"][1]["documentId"] = "foreign"
        payload["subAssemblies"][0]["documentId"] = "foreign"
    elif fault == "duplicate":
        payload["subAssemblies"].append(copy.deepcopy(payload["subAssemblies"][0]))
    elif fault == "path":
        payload["rootAssembly"]["occurrences"][1]["path"] = ["sub", "absent"]
    else:
        payload["subAssemblies"][0]["instances"][0]["configuration"] = "custom"
    subject = setup(payload)
    with pytest.raises(ConnectorError):
        await inspect(subject, include_nested=True, view="coaxial_circles")
    assert subject.get_json.call_count == 1


async def test_parallel_offset_axes_are_not_coaxial():
    payload = nested_root()
    payload["rootAssembly"]["occurrences"][1]["transform"][3] += 0.001
    result = await inspect(setup(payload), include_nested=True, view="coaxial_circles")
    assert result["total"] == 0


async def test_nested_pose_change_invalidates_continuation():
    payload = nested_root()
    first = await inspect(setup(payload), include_nested=True, view="coaxial_circles")
    payload["rootAssembly"]["occurrences"][1]["transform"][11] += 0.001
    with pytest.raises(ConnectorError, match="changed"):
        await inspect(
            setup(payload),
            include_nested=True,
            view="coaxial_circles",
            expected_snapshot=first["snapshot"],
        )


@pytest.mark.parametrize("fault", ["depth", "occurrences", "unknown", "donors", "leaves"])
async def test_nested_resource_and_path_bounds_refuse_before_donor_reads(fault):
    payload = nested_root()
    main = payload["rootAssembly"]
    if fault == "depth":
        assembly = copy.deepcopy(main["instances"][1])
        main["instances"] = [assembly]
        payload["subAssemblies"][0]["instances"] = [copy.deepcopy(assembly)]
        main["occurrences"] = [
            {"path": ["sub"] * length, "transform": MATRIX} for length in range(1, 10)
        ]
    elif fault == "occurrences":
        main["occurrences"] = [{"path": [f"part{i}"], "transform": MATRIX} for i in range(257)]
    elif fault == "unknown":
        main["occurrences"].append({"path": ["sub", "ghost"], "transform": MATRIX})
    else:
        count = 5 if fault == "donors" else 65
        part = main["instances"][0]
        main["instances"] = [
            {
                **part,
                "id": f"part{i}",
                "documentMicroversion": f"rev{i}" if fault == "donors" else "pinned",
            }
            for i in range(count)
        ]
        main["occurrences"] = [
            {"path": [row["id"]], "transform": MATRIX} for row in main["instances"]
        ]
    subject = setup(payload)
    with pytest.raises(ConnectorError):
        await inspect(subject, include_nested=True)
    assert subject.get_json.call_count == 1


def _circle(path, edge, z, *, normal=(0, 0, 1), x=0):
    return {
        "occurrence_path": path,
        "instance_id": path[-1],
        "edge_id": edge,
        "center": [x, 0, z],
        "normal": list(normal),
        "radius": 0.002,
    }


def test_coaxial_pair_selects_closest_edges_with_deterministic_ties_and_signed_axes():
    from solus_api.connectors.onshape_assembly_geometry import _coaxial_pairs

    circles = [
        _circle(["a"], "a0", 0),
        _circle(["a"], "a2", 2),
        _circle(["sub", "a"], "b1", 1, normal=(0, 0, -1)),
        _circle(["sub", "a"], "b3", 3),
    ]
    forward = _coaxial_pairs(circles)
    assert _coaxial_pairs(list(reversed(circles))) == forward
    assert len(forward) == 1
    assert [member["edge_id"] for member in forward[0]["members"]] == ["a0", "b1"]
    assert forward[0]["axial_separation_m"] == 1


@pytest.mark.parametrize(
    "other",
    [
        _circle(["b"], "edge", 1, x=0.001),
        _circle(["b"], "edge", 0, normal=(1, 0, 0)),
        _circle(["a"], "second", 1),
    ],
)
def test_coaxial_refuses_parallel_offset_crossing_axes_and_same_occurrence(other):
    from solus_api.connectors.onshape_assembly_geometry import _coaxial_pairs

    assert _coaxial_pairs([_circle(["a"], "first", 0), other]) == []


async def test_nested_child_order_does_not_change_snapshot_or_observation_order():
    payload = nested_root()
    child = copy.deepcopy(payload["subAssemblies"][0]["instances"][0])
    child["id"] = "another"
    payload["subAssemblies"][0]["instances"].append(child)
    payload["rootAssembly"]["occurrences"].append({"path": ["sub", "another"], "transform": MATRIX})
    first = await inspect(setup(payload), include_nested=True, view="circles")
    payload["subAssemblies"][0]["instances"].reverse()
    second = await inspect(setup(payload), include_nested=True, view="circles")
    assert second == first


async def test_intermediate_ancestor_revision_change_invalidates_snapshot():
    payload = nested_root()
    leaf = payload["subAssemblies"][0]["instances"][0]
    deeper = {
        **payload["rootAssembly"]["instances"][1],
        "id": "deeper",
        "elementId": "deeperElement",
        "documentMicroversion": "deepRev",
    }
    payload["subAssemblies"][0]["instances"] = [deeper]
    payload["subAssemblies"].append(
        {
            "documentId": "doc",
            "elementId": "deeperElement",
            "documentMicroversion": "deepRev",
            "configuration": "default",
            "instances": [leaf],
        }
    )
    payload["rootAssembly"]["occurrences"][1]["path"] = ["sub", "deeper", leaf["id"]]
    payload["rootAssembly"]["occurrences"].append({"path": ["sub", "deeper"], "transform": MATRIX})
    first = await inspect(setup(payload), include_nested=True)
    deeper["documentMicroversion"] = "newDeepRev"
    payload["subAssemblies"][1]["documentMicroversion"] = "newDeepRev"
    with pytest.raises(ConnectorError, match="changed"):
        await inspect(setup(payload), include_nested=True, expected_snapshot=first["snapshot"])


def test_coaxial_pair_count_remains_bounded():
    from solus_api.connectors.onshape_assembly_geometry import _coaxial_pairs

    with pytest.raises(ConnectorError, match="bound"):
        _coaxial_pairs([_circle([str(i)], "edge", i) for i in range(64)])


def test_coaxial_nonfinite_derived_displacement_refuses_typed():
    from solus_api.connectors.onshape_assembly_geometry import _coaxial_pairs

    with pytest.raises(ConnectorError):
        _coaxial_pairs([_circle(["a"], "a", -1e308), _circle(["b"], "b", 1e308)])


def test_huge_finite_parallel_offset_is_not_a_coaxial_pair():
    from solus_api.connectors.onshape_assembly_geometry import _coaxial_pairs

    assert _coaxial_pairs([_circle(["a"], "a", 0), _circle(["b"], "b", 0, x=1e308)]) == []
