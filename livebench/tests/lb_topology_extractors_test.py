"""Pure adapters normalize supplied parser observations, never acquire or accept hardware."""

from dataclasses import replace
from pathlib import Path

import pytest
from livebench.hardware.repo_config import RepoConfigMatch, RepoPartDecl
from livebench.hardware.topology_extractors import firmware_topology, repo_config_topology
from livebench.recognition.firmware import FirmwareFinding, extract_firmware_findings
from solus_api.hardware.topology_evidence import MAX_ROWS

CONTEXT = {"source_namespace": "project:a:source:repo", "source_ref": "source:approved"}


def test_firmware_adapter_keeps_dependencies_bus_intent_and_unknown_sensor() -> None:
    findings = extract_firmware_findings(Path(__file__).parent / "fixtures" / "topology_firmware")
    batch = firmware_topology(findings, **CONTEXT)
    assert batch.status == "success" and batch.source_kind == "firmware"
    assert len(batch.rows) == 6
    bus = next(row for row in batch.rows if row.bus == "Wire")
    assert bus.protocol == "i2c" and bus.device is None and bus.part_candidate is None
    analog = next(row for row in batch.rows if any(p.pin_ref == "A0" for p in row.provenance))
    assert analog.protocol == "analog" and analog.part_candidate is None and analog.device is None
    attachment = next(row for row in batch.rows if row.part_candidate == "elbow")
    assert attachment.address is None
    assert attachment.provenance[0].pin_ref == "ELBOW_PIN"
    includes = [
        row
        for row in batch.rows
        if any(p.detail and "library_include" in p.detail for p in row.provenance)
    ]
    assert len(includes) == 2 and all(row.device is None and row.bus is None for row in includes)
    assert all(
        row.source_namespace == CONTEXT["source_namespace"]
        and row.source_ref == CONTEXT["source_ref"]
        for row in batch.rows
    )


def _config(config_id: str = "arm-a", model: str = "STS3215") -> RepoConfigMatch:
    return RepoConfigMatch(
        config_id=config_id,
        parser_id="json",
        label="arm",
        source="config.json",
        protocol_hint="feetech-sts",
        port_hint="/dev/ttyACM0",
        parts=[RepoPartDecl(name="elbow", address="06", model=model)],
    )


def test_config_adapter_retains_conflicts_separate_buses_and_informational_port() -> None:
    batch = repo_config_topology(
        [_config(), _config("arm-b"), _config(model="other-model")], **CONTEXT
    )
    assert batch.status == "success" and batch.source_kind == "host_config"
    assert len(batch.rows) == 3
    assert {row.bus for row in batch.rows} == {"arm-a", "arm-b"}
    assert {row.address for row in batch.rows} == {"06"}
    assert {row.device for row in batch.rows} == {"STS3215", "other-model"}
    assert all(
        row.part_candidate == "elbow" and row.protocol == "feetech-sts" for row in batch.rows
    )
    assert all("/dev/ttyACM0" in (row.provenance[0].detail or "") for row in batch.rows)
    assert all(row.source_ref == CONTEXT["source_ref"] for row in batch.rows)


@pytest.mark.parametrize("adapter", [firmware_topology, repo_config_topology])
def test_empty_unavailable_and_invalid_source_are_distinct(adapter: object) -> None:
    assert callable(adapter)
    assert adapter([], **CONTEXT).status == "success"
    assert adapter(None, **CONTEXT).status == "unavailable"
    assert adapter([], source_namespace="", source_ref="source").status == "invalid"


def test_adapters_deduplicate_exactly_without_losing_conflicting_evidence() -> None:
    first = FirmwareFinding("elbow", "attach_call", "a.ino", 1, "cpp", pin=3)
    second = FirmwareFinding("elbow", "attach_call", "b.ino", 1, "cpp", pin=4)
    assert firmware_topology([first, second, first], **CONTEXT) == firmware_topology(
        [second, first], **CONTEXT
    )
    assert len(firmware_topology([first, second], **CONTEXT).rows) == 2
    assert repo_config_topology([_config(), _config()], **CONTEXT) == repo_config_topology(
        [_config()], **CONTEXT
    )


def test_raw_input_limits_do_not_disappear_through_deduplication() -> None:
    finding = FirmwareFinding("elbow", "attach_call", "a.ino", 1, "cpp", pin=3)
    assert firmware_topology([finding] * (MAX_ROWS + 1), **CONTEXT).status == "invalid"
    assert repo_config_topology([_config()] * (MAX_ROWS + 1), **CONTEXT).status == "invalid"
    oversized = _config()
    oversized.parts.extend(oversized.parts * MAX_ROWS)
    assert repo_config_topology([oversized], **CONTEXT).status == "invalid"


def test_adapters_cannot_acquire_paths_or_execute_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("adapter attempted I/O")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr("subprocess.run", refuse)
    assert repo_config_topology([_config()], **CONTEXT).status == "success"
    assert (
        firmware_topology(
            [FirmwareFinding("pin", "pin_constant", "not-read.ino", 1, "cpp", pin=3)], **CONTEXT
        ).status
        == "success"
    )


def test_malformed_supplied_records_and_nonfinite_constants_are_invalid() -> None:
    assert firmware_topology([object()], **CONTEXT).status == "invalid"
    assert repo_config_topology([object()], **CONTEXT).status == "invalid"
    malformed = RepoConfigMatch("id", "parser", "label", "config.json", parts=[object()])
    assert repo_config_topology([malformed], **CONTEXT).status == "invalid"
    nonfinite = FirmwareFinding("MOTOR_KV", "motor_constant", "a.ino", 1, "cpp", value=float("nan"))
    assert firmware_topology([nonfinite], **CONTEXT).status == "invalid"


@pytest.mark.parametrize("field", ["port_hint", "parser_id", "source", "config_id"])
def test_config_metadata_is_bounded_before_json(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise RuntimeError("oversized config reached serializer")

    monkeypatch.setattr("livebench.hardware.topology_extractors.json.dumps", forbidden)
    assert (
        repo_config_topology([replace(_config(), **{field: "x" * 10000})], **CONTEXT).status
        == "invalid"
    )


@pytest.mark.parametrize("field", ["name", "file", "language", "pin_ref"])
def test_firmware_metadata_is_bounded_before_json(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise RuntimeError("oversized firmware reached serializer")

    monkeypatch.setattr("livebench.hardware.topology_extractors.json.dumps", forbidden)
    finding = FirmwareFinding("pin", "pin_constant", "a.ino", 1, "cpp", pin=3)
    assert (
        firmware_topology([replace(finding, **{field: "x" * 10000})], **CONTEXT).status == "invalid"
    )


def test_adapters_refuse_nonconcrete_sequences_without_touching_them() -> None:
    class UntrustedSequence:
        def __len__(self) -> int:
            raise RuntimeError("unbounded input was inspected")

    assert firmware_topology(UntrustedSequence(), **CONTEXT).status == "invalid"
    assert repo_config_topology(UntrustedSequence(), **CONTEXT).status == "invalid"
