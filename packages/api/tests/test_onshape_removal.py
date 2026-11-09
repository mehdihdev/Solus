"""SOLUSDEV-319 — Onshape suppress, rename, delete feature, delete instance.

docs/api/onshape-development.md §"Removal, rename, move and part metadata".
Invariants under test:

- every write is approval-gated, previewed, bound to the observation the person
  approved, and verified by a fresh readback (`mutation_unverified` on doubt);
- suppress/rename go through the guarded feature POST (`sourceMicroversion` +
  `rejectMicroversionSkew`); DELETE has no vendor guard, so a changed model
  between preview and execution refuses WITHOUT dispatching the DELETE;
- downstream breakage is reported (`downstream_errors`), never auto-reverted.

Everything is respx-mocked; no network, no live tenant.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
import pytest
import respx
from solus_api.connectors.contracts import ConnectorError, Credentials
from solus_api.connectors.onshape import ONSHAPE_API_BASE, OnshapeConnector
from solus_api.connectors.onshape_confirmation import PreviewBinding
from solus_api.connectors.onshape_ops import operation_by_name

DID, WID, EID = "d1", "w1", "e1"
PS = f"{ONSHAPE_API_BASE}/api/v6/partstudios/d/{DID}/w/{WID}/e/{EID}"
ASM = f"{ONSHAPE_API_BASE}/api/v6/assemblies/d/{DID}/w/{WID}/e/{EID}"
ARGS = {"document_id": DID, "workspace_id": WID, "element_id": EID}

_SKETCH = {
    "btType": "BTMSketch-151",
    "featureId": "Fsk1",
    "name": "Sketch 1",
    "featureType": "newSketch",
    "suppressed": False,
    "parameters": [],
}
_EXTRUDE = {
    "btType": "BTMFeature-134",
    "featureId": "Fex1",
    "name": "Extrude 1",
    "featureType": "extrude",
    "suppressed": False,
    "parameters": [
        {
            "btType": "BTMParameterQueryList-148",
            "parameterId": "entities",
            "queries": [
                {
                    "btType": "BTMIndividualSketchRegionQuery-140",
                    "featureId": "Fsk1",
                }
            ],
        }
    ],
}


def _tree() -> dict[str, Any]:
    return {
        "features": [deepcopy(_SKETCH), deepcopy(_EXTRUDE)],
        "featureStates": {
            "Fsk1": {"featureStatus": "OK"},
            "Fex1": {"featureStatus": "OK"},
        },
        "sourceMicroversion": "mv1",
        "serializationVersion": "1.2.3",
        "libraryVersion": 2000,
    }


class FakeStudio:
    """A Part Studio (or assembly feature list) whose state follows the writes."""

    def __init__(self, router: respx.MockRouter, base: str = PS) -> None:
        self.tree = _tree()
        self.base = base
        self.posts: list[dict[str, Any]] = []
        self.deletes: list[str] = []
        #: Applied on the NEXT write, to model what Onshape does to dependents.
        self.break_on_write: str | None = None
        self.ignore_writes = False
        router.get(f"{base}/features").mock(side_effect=self._get)
        router.post(url__regex=rf"{base}/features/featureid/[^/]+$").mock(side_effect=self._post)
        router.delete(url__regex=rf"{base}/features/featureid/[^/]+$").mock(
            side_effect=self._delete
        )

    def _get(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=deepcopy(self.tree))

    def _written(self) -> None:
        self.tree["sourceMicroversion"] = f"mv{len(self.posts) + len(self.deletes) + 1}"
        if self.break_on_write:
            self.tree["featureStates"][self.break_on_write] = {"featureStatus": "ERROR"}

    def _post(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.posts.append(body)
        if not self.ignore_writes:
            feature = body["feature"]
            self.tree["features"] = [
                feature if f["featureId"] == feature["featureId"] else f
                for f in self.tree["features"]
            ]
        self._written()
        return httpx.Response(200, json={"feature": body["feature"]})

    def _delete(self, request: httpx.Request) -> httpx.Response:
        fid = str(request.url).rsplit("/", 1)[-1]
        self.deletes.append(fid)
        if not self.ignore_writes:
            self.tree["features"] = [f for f in self.tree["features"] if f["featureId"] != fid]
            self.tree["featureStates"].pop(fid, None)
        self._written()
        return httpx.Response(200, json={"btType": "BTFeatureApiBase-1430"})


def _conn() -> OnshapeConnector:
    return OnshapeConnector(client_id="cid", client_secret="csecret")


async def _preview(name: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    operation = operation_by_name(name)
    assert operation is not None and operation.preview is not None
    connector = _conn()
    async with connector.http(Credentials(token="t")) as client:
        return await operation.preview(connector, client, args)


async def _approve_and_run(name: str, args: dict[str, Any], *, between: Any = None) -> Any:
    """Preview, (optionally mutate the world), then run under the approval."""
    operation = operation_by_name(name)
    assert operation is not None and operation.preview is not None
    connector = _conn()
    async with connector.http(Credentials(token="t")) as client:
        binding = PreviewBinding()
        binding.remember(args, await operation.preview(connector, client, args))
        if between is not None:
            between()
        with binding.execution(args):
            return await operation.run(connector, client, args)


def _labels(rows: list[dict[str, Any]]) -> list[str]:
    return [row["label"] for row in rows]


# ----------------------------------------------------------------- registry


@pytest.mark.parametrize(
    "name",
    [
        "onshape.suppress_feature",
        "onshape.rename_feature",
        "onshape.delete_feature",
        "onshape.delete_instance",
    ],
)
def test_every_removal_operation_is_a_previewed_confirmed_write(name: str) -> None:
    operation = operation_by_name(name)
    assert operation is not None
    assert operation.requires_confirmation is True
    assert operation.preview is not None
    assert "write" in operation.tags
    assert operation.params["additionalProperties"] is False


def test_descriptions_steer_removal_to_suppress_and_delete_to_explicit_requests() -> None:
    suppress = operation_by_name("onshape.suppress_feature")
    delete = operation_by_name("onshape.delete_feature")
    assert suppress is not None and delete is not None
    assert "remove" in suppress.description.lower()
    assert "explicitly" in delete.description.lower()


# ----------------------------------------------------------------- suppress


@respx.mock
async def test_suppress_preview_shows_the_change_and_likely_dependents() -> None:
    FakeStudio(respx.mock)
    rows = await _preview(
        "onshape.suppress_feature",
        {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1", "suppressed": True},
    )
    labels = _labels(rows)
    assert "Source microversion" in labels
    assert "Feature state fingerprint" in labels
    change = next(r for r in rows if r["label"].startswith("Sketch 1"))
    assert (change["before"], change["after"]) == ("False", "True")
    dependent = next(r for r in rows if r["label"] == "May depend on it")
    assert "Extrude 1" in dependent["after"]


@respx.mock
async def test_suppress_posts_the_complete_feature_guarded_and_reports_breakage() -> None:
    studio = FakeStudio(respx.mock)
    studio.break_on_write = "Fex1"
    result = await _approve_and_run(
        "onshape.suppress_feature",
        {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1", "suppressed": True},
    )
    (body,) = studio.posts
    assert body["sourceMicroversion"] == "mv1"
    assert body["rejectMicroversionSkew"] is True
    assert body["feature"] == {**_SKETCH, "suppressed": True}
    assert result["verified"] is True
    assert result["suppressed"] is True
    assert result["downstream_errors"] == [
        {"feature_id": "Fex1", "name": "Extrude 1", "status": "ERROR"}
    ]


@respx.mock
async def test_unsuppress_round_trips() -> None:
    studio = FakeStudio(respx.mock)
    studio.tree["features"][0]["suppressed"] = True
    result = await _approve_and_run(
        "onshape.suppress_feature",
        {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1", "suppressed": False},
    )
    assert studio.posts[0]["feature"]["suppressed"] is False
    assert result["suppressed"] is False
    assert result["downstream_errors"] == []


@respx.mock
async def test_suppress_refuses_a_feature_already_in_that_state() -> None:
    studio = FakeStudio(respx.mock)
    with pytest.raises(ConnectorError) as exc:
        await _preview(
            "onshape.suppress_feature",
            {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1", "suppressed": False},
        )
    assert exc.value.code == "config_invalid"
    assert studio.posts == []


@respx.mock
async def test_suppress_refuses_configured_suppression() -> None:
    studio = FakeStudio(respx.mock)
    studio.tree["features"][0]["suppressionConfigured"] = True
    with pytest.raises(ConnectorError) as exc:
        await _preview(
            "onshape.suppress_feature",
            {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1", "suppressed": True},
        )
    assert exc.value.code == "config_invalid"
    assert "configur" in exc.value.message.lower()


@respx.mock
async def test_suppress_readback_mismatch_is_unverified_and_not_replayed() -> None:
    studio = FakeStudio(respx.mock)
    studio.ignore_writes = True
    with pytest.raises(ConnectorError) as exc:
        await _approve_and_run(
            "onshape.suppress_feature",
            {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1", "suppressed": True},
        )
    assert exc.value.code == "mutation_unverified"
    assert len(studio.posts) == 1


@respx.mock
async def test_a_model_changed_after_approval_refuses_without_writing() -> None:
    studio = FakeStudio(respx.mock)

    def someone_else_edits() -> None:
        studio.tree["sourceMicroversion"] = "mvother"

    with pytest.raises(ConnectorError) as exc:
        await _approve_and_run(
            "onshape.suppress_feature",
            {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1", "suppressed": True},
            between=someone_else_edits,
        )
    assert exc.value.code == "stale_state"
    assert studio.posts == []


@respx.mock
async def test_assembly_features_use_the_assembly_collection() -> None:
    studio = FakeStudio(respx.mock, base=ASM)
    await _approve_and_run(
        "onshape.suppress_feature",
        {**ARGS, "element_type": "assembly", "feature_id": "Fex1", "suppressed": True},
    )
    assert studio.posts[0]["feature"]["featureId"] == "Fex1"


@pytest.mark.parametrize(
    "bad",
    [
        {"element_type": "drawing"},
        {"feature_id": "../../documents"},
        {"feature_id": ""},
        {"suppressed": "yes"},
    ],
)
@respx.mock
async def test_suppress_rejects_malformed_arguments(bad: dict[str, Any]) -> None:
    FakeStudio(respx.mock)
    args = {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1", "suppressed": True}
    with pytest.raises(ConnectorError) as exc:
        await _preview("onshape.suppress_feature", {**args, **bad})
    assert exc.value.code == "config_invalid"


@respx.mock
async def test_unknown_feature_is_not_found() -> None:
    FakeStudio(respx.mock)
    with pytest.raises(ConnectorError) as exc:
        await _preview(
            "onshape.suppress_feature",
            {**ARGS, "element_type": "partstudio", "feature_id": "Fnope", "suppressed": True},
        )
    assert exc.value.code == "not_found"


# ------------------------------------------------------------------- rename


@respx.mock
async def test_rename_changes_only_the_name_and_verifies_it() -> None:
    studio = FakeStudio(respx.mock)
    result = await _approve_and_run(
        "onshape.rename_feature",
        {**ARGS, "element_type": "partstudio", "feature_id": "Fex1", "name": "Motor boss"},
    )
    assert studio.posts[0]["feature"] == {**_EXTRUDE, "name": "Motor boss"}
    assert studio.posts[0]["rejectMicroversionSkew"] is True
    assert result == {
        "feature_id": "Fex1",
        "name": "Motor boss",
        "previous_name": "Extrude 1",
        "verified": True,
        "downstream_errors": [],
    }


@pytest.mark.parametrize(
    "name",
    [
        "",
        " leading",
        "trailing ",
        "x" * 65,
        "zero​width",
        "bidi‮flip",
        "new\nline",
        "tab\there",
        "Extrude 1",  # unchanged
    ],
)
@respx.mock
async def test_rename_refuses_invisible_unsafe_or_unchanged_names(name: str) -> None:
    studio = FakeStudio(respx.mock)
    with pytest.raises(ConnectorError) as exc:
        await _preview(
            "onshape.rename_feature",
            {**ARGS, "element_type": "partstudio", "feature_id": "Fex1", "name": name},
        )
    assert exc.value.code == "config_invalid"
    assert studio.posts == []


# ----------------------------------------------------------- delete feature


@respx.mock
async def test_delete_preview_says_it_cannot_be_undone_from_solus() -> None:
    FakeStudio(respx.mock)
    rows = await _preview(
        "onshape.delete_feature", {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1"}
    )
    action = next(r for r in rows if r["label"] == "Action")
    assert "cannot be undone from Solus" in action["after"]
    assert any(r["label"] == "May depend on it" for r in rows)


@respx.mock
async def test_delete_feature_deletes_verifies_absence_and_reports_breakage() -> None:
    studio = FakeStudio(respx.mock)
    studio.break_on_write = "Fex1"
    result = await _approve_and_run(
        "onshape.delete_feature", {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1"}
    )
    assert studio.deletes == ["Fsk1"]
    assert result["deleted"] is True
    assert result["verified"] is True
    assert result["downstream_errors"] == [
        {"feature_id": "Fex1", "name": "Extrude 1", "status": "ERROR"}
    ]


@respx.mock
async def test_delete_feature_refuses_a_changed_model_without_deleting() -> None:
    studio = FakeStudio(respx.mock)

    def someone_else_edits() -> None:
        studio.tree["features"][1]["name"] = "Renamed elsewhere"

    with pytest.raises(ConnectorError) as exc:
        await _approve_and_run(
            "onshape.delete_feature",
            {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1"},
            between=someone_else_edits,
        )
    assert exc.value.code == "stale_state"
    assert studio.deletes == []


@respx.mock
async def test_delete_feature_still_present_after_delete_is_unverified() -> None:
    studio = FakeStudio(respx.mock)
    studio.ignore_writes = True
    with pytest.raises(ConnectorError) as exc:
        await _approve_and_run(
            "onshape.delete_feature", {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1"}
        )
    assert exc.value.code == "mutation_unverified"
    assert studio.deletes == ["Fsk1"]


@respx.mock
async def test_delete_transport_failure_is_unverified() -> None:
    studio = FakeStudio(respx.mock)
    respx.mock.delete(url__regex=rf"{PS}/features/featureid/[^/]+$").mock(
        side_effect=httpx.ConnectError("boom")
    )
    with pytest.raises(ConnectorError) as exc:
        await _approve_and_run(
            "onshape.delete_feature", {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1"}
        )
    assert exc.value.code == "mutation_unverified"
    assert studio.tree["features"][0]["featureId"] == "Fsk1"


# ---------------------------------------------------------- delete instance


class FakeAssembly(FakeStudio):
    """An assembly: a definition with instances plus a mate feature list."""

    def __init__(self, router: respx.MockRouter) -> None:
        super().__init__(router, base=ASM)
        self.tree = {
            "features": [
                {
                    "btType": "BTMMate-64",
                    "featureId": "Mfast",
                    "name": "Fastened 1",
                    "featureType": "mate",
                    "suppressed": False,
                    "parameters": [
                        {
                            "btType": "BTMParameterQueryWithOccurrenceList-67",
                            "parameterId": "mateConnectorsQuery",
                            "queries": [{"path": ["Ibase", "Ipeg"]}],
                        }
                    ],
                }
            ],
            "featureStates": {"Mfast": {"featureStatus": "OK"}},
            "sourceMicroversion": "mv1",
            "serializationVersion": "1.2.3",
            "libraryVersion": 2000,
        }
        self.instances = [
            {"id": "Ibase", "name": "BasePlate <1>", "type": "Part", "partId": "JHD"},
            {"id": "Ipeg", "name": "Peg <1>", "type": "Part", "partId": "JID"},
        ]
        router.get(ASM).mock(side_effect=self._definition)
        router.delete(url__regex=rf"{ASM}/instance/nodeid/[^/]+$").mock(
            side_effect=self._delete_instance
        )

    def _definition(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"rootAssembly": {"instances": deepcopy(self.instances)}, "subAssemblies": []},
        )

    def _delete_instance(self, request: httpx.Request) -> httpx.Response:
        nid = str(request.url).rsplit("/", 1)[-1]
        self.deletes.append(nid)
        if not self.ignore_writes:
            self.instances = [i for i in self.instances if i["id"] != nid]
        self._written()
        return httpx.Response(200, json={})


@respx.mock
async def test_delete_instance_preview_names_the_instance_and_its_mates() -> None:
    FakeAssembly(respx.mock)
    rows = await _preview("onshape.delete_instance", {**ARGS, "instance_id": "Ipeg"})
    instance = next(r for r in rows if r["label"] == "Instance")
    assert "Peg <1>" in instance["after"]
    dependent = next(r for r in rows if r["label"] == "May depend on it")
    assert "Fastened 1" in dependent["after"]
    assert "cannot be undone from Solus" in next(r for r in rows if r["label"] == "Action")["after"]


@respx.mock
async def test_delete_instance_deletes_and_reports_the_broken_mate() -> None:
    assembly = FakeAssembly(respx.mock)
    assembly.break_on_write = "Mfast"
    result = await _approve_and_run("onshape.delete_instance", {**ARGS, "instance_id": "Ipeg"})
    assert assembly.deletes == ["Ipeg"]
    assert result == {
        "instance_id": "Ipeg",
        "name": "Peg <1>",
        "deleted": True,
        "verified": True,
        "downstream_errors": [{"feature_id": "Mfast", "name": "Fastened 1", "status": "ERROR"}],
    }


@respx.mock
async def test_delete_instance_still_present_is_unverified() -> None:
    assembly = FakeAssembly(respx.mock)
    assembly.ignore_writes = True
    with pytest.raises(ConnectorError) as exc:
        await _approve_and_run("onshape.delete_instance", {**ARGS, "instance_id": "Ipeg"})
    assert exc.value.code == "mutation_unverified"


@respx.mock
async def test_delete_instance_refuses_a_changed_assembly_without_deleting() -> None:
    assembly = FakeAssembly(respx.mock)

    def someone_adds_an_instance() -> None:
        assembly.instances.append({"id": "Inew", "name": "Bolt <1>", "type": "Part"})

    with pytest.raises(ConnectorError) as exc:
        await _approve_and_run(
            "onshape.delete_instance",
            {**ARGS, "instance_id": "Ipeg"},
            between=someone_adds_an_instance,
        )
    assert exc.value.code == "stale_state"
    assert assembly.deletes == []


@respx.mock
async def test_delete_unknown_instance_is_not_found() -> None:
    FakeAssembly(respx.mock)
    with pytest.raises(ConnectorError) as exc:
        await _preview("onshape.delete_instance", {**ARGS, "instance_id": "Inope"})
    assert exc.value.code == "not_found"


@respx.mock
async def test_dependent_names_are_capped_in_the_preview() -> None:
    studio = FakeStudio(respx.mock)
    studio.tree["features"][1]["name"] = "E" * 500
    rows = await _preview(
        "onshape.delete_feature", {**ARGS, "element_type": "partstudio", "feature_id": "Fsk1"}
    )
    assert all(len(str(v)) <= 400 for r in rows for v in r.values())
