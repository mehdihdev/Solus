"""Pure normalization of supplied parser results; no acquisition, identity binding or writes."""

import json
import math
from collections.abc import Sequence
from typing import get_args

from pydantic import ValidationError
from solus_api.hardware.topology_evidence import (
    MAX_ROWS,
    SourceKind,
    TopologyEvidence,
    TopologyExtraction,
    TopologyProvenance,
)

from livebench.hardware.repo_config import RepoConfigMatch, RepoPartDecl
from livebench.recognition.firmware import FindingKind, FirmwareFinding

_CODE_INTENT = "Code/configuration intent only; not verified physical hardware."


def _text(value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ValueError("invalid or oversized observation text")


def _firmware_metadata(finding: FirmwareFinding) -> None:
    for value in (finding.name, finding.file, finding.kind, finding.language):
        _text(value)
    _text(finding.pin_ref, optional=True)
    if finding.kind not in get_args(FindingKind) or finding.language not in ("cpp", "python"):
        raise ValueError("unknown firmware observation kind or language")
    if type(finding.line) is not int or not 1 <= finding.line <= 2**31:
        raise ValueError("invalid source line")
    _text(f"{finding.file}:{finding.line}")
    if finding.pin is not None and (type(finding.pin) is not int or finding.pin.bit_length() > 32):
        raise ValueError("invalid pin number")
    number: object = finding.value
    if number is not None:
        if type(number) is int and number.bit_length() <= 1024:
            return
        if type(number) is not float or not math.isfinite(number):
            raise ValueError("invalid numeric observation")


def _context(source_namespace: str, source_ref: str) -> dict[str, str]:
    # Validate even empty results: an empty scan must not launder invalid caller scope.
    TopologyEvidence(source_namespace=source_namespace, source_ref=source_ref)
    return {"source_namespace": source_namespace, "source_ref": source_ref}


def _invalid(kind: SourceKind) -> TopologyExtraction:
    return TopologyExtraction(
        source_kind=kind, status="invalid", notes=("Invalid or over-budget supplied observations.",)
    )


def _firmware_row(finding: FirmwareFinding, context: dict[str, str]) -> TopologyEvidence:
    _firmware_metadata(finding)
    pin_ref = finding.pin_ref or (str(finding.pin) if finding.pin is not None else None)
    return TopologyEvidence(
        **context,
        bus=finding.name if finding.kind == "bus_begin" else None,
        protocol={"bus_begin": "i2c", "analog_read": "analog"}.get(finding.kind),
        address=str(finding.pin) if finding.pin is not None else None,
        part_candidate=finding.name if finding.kind == "attach_call" else None,
        provenance=(
            TopologyProvenance(
                source_ref=f"{finding.file}:{finding.line}",
                entity_ref=finding.name,
                pin_ref=pin_ref,
                detail=json.dumps(
                    {"kind": finding.kind, "language": finding.language, "value": finding.value},
                    allow_nan=False,
                    sort_keys=True,
                ),
            ),
        ),
        confidence=0.55,
    )


def firmware_topology(
    findings: Sequence[FirmwareFinding] | None, *, source_namespace: str, source_ref: str
) -> TopologyExtraction:
    """Caller supplies findings; None means unavailable, [] a successful empty extraction."""
    try:
        context = _context(source_namespace, source_ref)
        if findings is None:
            return TopologyExtraction(source_kind="firmware", status="unavailable")
        if (
            not isinstance(findings, (list, tuple))
            or len(findings) > MAX_ROWS
            or any(not isinstance(item, FirmwareFinding) for item in findings)
        ):
            return _invalid("firmware")
        return TopologyExtraction(
            source_kind="firmware",
            status="success",
            rows=tuple(_firmware_row(item, context) for item in findings),
            notes=(_CODE_INTENT,),
        )
    except (ValidationError, ValueError, TypeError):
        return _invalid("firmware")


def _config_rows(match: RepoConfigMatch, context: dict[str, str]) -> list[TopologyEvidence]:
    for value in (match.config_id, match.parser_id, match.source):
        _text(value)
    _text(match.protocol_hint, optional=True)
    _text(match.port_hint, optional=True)
    rows: list[TopologyEvidence] = []
    for part in match.parts:
        if not isinstance(part, RepoPartDecl):
            raise ValueError("invalid supplied part declaration")
        _text(part.name)
        _text(part.address)
        _text(part.model, optional=True)
        rows.append(
            TopologyEvidence(
                **context,
                bus=match.config_id,
                protocol=match.protocol_hint,
                address=part.address,
                device=part.model,
                part_candidate=part.name,
                provenance=(
                    TopologyProvenance(
                        source_ref=match.source,
                        entity_ref=part.name,
                        detail=json.dumps(
                            {
                                "parser": match.parser_id,
                                "config": match.config_id,
                                "model_candidate": part.model,
                                "port_hint": match.port_hint,
                            },
                            sort_keys=True,
                        ),
                    ),
                ),
                confidence=0.55,
            )
        )
    return rows


def repo_config_topology(
    matches: Sequence[RepoConfigMatch] | None, *, source_namespace: str, source_ref: str
) -> TopologyExtraction:
    """Declared model/port are candidate evidence; port_hint never establishes USB identity."""
    try:
        context = _context(source_namespace, source_ref)
        if matches is None:
            return TopologyExtraction(source_kind="host_config", status="unavailable")
        if (
            not isinstance(matches, (list, tuple))
            or len(matches) > MAX_ROWS
            or any(not isinstance(item, RepoConfigMatch) for item in matches)
        ):
            return _invalid("host_config")
        if any(not isinstance(item.parts, (list, tuple)) for item in matches):
            return _invalid("host_config")
        if sum(len(item.parts) for item in matches) > MAX_ROWS:
            return _invalid("host_config")
        return TopologyExtraction(
            source_kind="host_config",
            status="success",
            rows=tuple(row for match in matches for row in _config_rows(match, context)),
            notes=(_CODE_INTENT,),
        )
    except (ValidationError, ValueError, TypeError):
        return _invalid("host_config")
