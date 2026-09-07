"""The detection loop (R2): enumerate → identify → interrogate → propose.

Plugging a machine in produces a proposal, not a form. Enumeration reports each device at
whichever level the transport can honestly claim (a USB bridge fronts an unknown MCU);
interrogation asks the registered interrogators, opening the transport at candidate parameters
and stopping at the first answer; a proposal combines the evidence with what the user's own
repo says, and asks — never guesses — when more than one repo config fits.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from solus_api.fingerprint.contract import ModalityMatch
from solus_api.hardware.config import TransportBinding, TransportKind, part_ref

from livebench.hardware.channel import TransportUnavailableError
from livebench.hardware.interrogator import Interrogation, interrogate
from livebench.hardware.registries import Registries
from livebench.hardware.repo_config import RepoConfigMatch

logger = logging.getLogger(__name__)

Level = Literal["transport", "board", "protocol", "platform"]

#: Serial rates worth a ping, common-first. A rate is a transport parameter, not a protocol.
DEFAULT_CANDIDATE_PARAMS: Final[tuple[Mapping[str, Any], ...]] = (
    {"baud": 1_000_000},
    {"baud": 115200},
    {"baud": 57600},
    {"baud": 9600},
)
DEFAULT_BUDGET_S: Final = 0.5
_PROBE_TIMEOUT_S: Final = 0.2


@dataclass(frozen=True)
class DetectedDevice:
    """One enumerated device at its honest level."""

    transport: TransportKind
    device_ref: str | None  # None when the device carries no binding identity (ambiguous)
    identity: TransportBinding | None
    level: Level
    board: str | None
    board_class: str | None
    mcu_known: bool
    confidence: float
    evidence: list[ModalityMatch]
    ambiguous: bool
    last_seen_path: str | None
    vid: int | None = None
    pid: int | None = None


def enumerate_devices(
    *, list_devices: Callable[[], Sequence[Any]] | None = None
) -> list[DetectedDevice]:
    """USB-serial devices on this machine (other transports announce themselves and arrive
    through their interrogators). Enumeration opens no port."""
    if list_devices is None:
        from livebench.local import list_devices as local_list_devices

        list_devices = local_list_devices
    devices: list[DetectedDevice] = []
    for local in list_devices():
        identity = local.identity
        path = local.by_id_path or identity.device
        binding = (
            TransportBinding(
                kind=TransportKind.USB_SERIAL,
                binding=identity.serial,
                vid=identity.vid,
                pid=identity.pid,
                last_seen_path=path,
            )
            if identity.serial
            else None
        )
        board = identity.board
        devices.append(
            DetectedDevice(
                transport=TransportKind.USB_SERIAL,
                device_ref=binding.device_ref if binding else None,
                identity=binding,
                level="board" if identity.mcu_known else "transport",
                board=board.name if board is not None else None,
                board_class=board.kind.value if board is not None else None,
                mcu_known=identity.mcu_known,
                confidence=identity.evidence.confidence,
                evidence=[identity.evidence],
                ambiguous=local.ambiguous,
                last_seen_path=path,
                vid=identity.vid,
                pid=identity.pid,
            )
        )
    return devices


def interrogate_device(
    identity: TransportBinding,
    *,
    registries: Registries,
    candidate_params: Sequence[Mapping[str, Any]] = DEFAULT_CANDIDATE_PARAMS,
    budget_s: float = DEFAULT_BUDGET_S,
) -> list[Interrogation]:
    """Open the transport at each candidate parameter set and ask the registry; stop at the
    first set that gets an answer. A busy or absent port is silence, never an error."""
    for params in candidate_params:
        try:
            channel = registries.transports.open(
                identity, {**params, "timeout_s": min(budget_s, _PROBE_TIMEOUT_S)}
            )
        except TransportUnavailableError as exc:
            logger.info("interrogation skipped %s: %s", identity.device_ref, exc)
            return []
        try:
            results = interrogate(channel, registries.interrogators, budget_s=budget_s)
        finally:
            channel.close()
        if results:
            opened = dict(getattr(channel, "params", {})) or dict(params)
            return [dataclasses.replace(r, params={**opened, **r.params}) for r in results]
    return []


@dataclass(frozen=True)
class ProposalRow:
    id: str  # `<device ref>/<address>` — stable across replug, the part's future external_ref
    subject: str
    address: str
    model: str | None
    proposed_function: str | None
    confidence: float | None
    evidence: list[ModalityMatch]
    provenance: Literal["bus", "repo"]


@dataclass(frozen=True)
class Disambiguation:
    question: str
    options: list[str]  # repo config ids; the user picks once (favoured first)
    #: Configs whose declared calibration equals what the parts themselves carry (an
    #: interrogator's `calibration_signature`). Evidence for the question, never an answer.
    favoured: list[str] = field(default_factory=list)


def _favoured(
    signature: Mapping[str, Mapping[str, Any]], matches: Sequence[RepoConfigMatch]
) -> list[str]:
    """Config ids whose per-part calibration agrees with the wire on every compared field."""
    favoured: list[str] = []
    for match in matches:
        compared = agreed = 0
        for part in match.parts:
            burned = signature.get(part.address)
            if not burned or not part.calibration:
                continue
            for key, value in burned.items():
                if key in part.calibration:
                    compared += 1
                    agreed += int(part.calibration[key]) == int(value)
        if compared and compared == agreed:
            favoured.append(match.config_id)
    return favoured


@dataclass(frozen=True)
class Proposal:
    device_ref: str
    identity: TransportBinding | None
    level: Level
    summary: str
    driver_id: str | None
    params: dict[str, Any]
    rows: list[ProposalRow]
    repo_matches: list[RepoConfigMatch]
    disambiguation: Disambiguation | None
    confidence: float
    evidence: list[ModalityMatch] = field(default_factory=list)
    calibration_source: str | None = None


def _agreed_names(address: str, matches: Sequence[RepoConfigMatch]) -> str | None:
    """A function name only when every matching config that declares this address agrees."""
    names = {p.name for m in matches for p in m.parts if p.address == address}
    return names.pop() if len(names) == 1 else None


def _repo_sentence(matches: Sequence[RepoConfigMatch], rows: Sequence[ProposalRow]) -> str:
    if len(matches) == 1:
        named = [f"{r.address} is {r.proposed_function}" for r in rows if r.proposed_function]
        text = "; your repo says " + ", ".join(named[:3]) if named else ""
        if len(named) > 3:
            text += " …"
        source = matches[0].calibration_source
        return text + (f"; calibration found at {source}" if source else "")
    if len(matches) > 1:
        return f"; {len(matches)} configs in your repo match"
    return ""


def propose(
    device: DetectedDevice,
    interrogations: Sequence[Interrogation],
    *,
    repo_matches: Sequence[RepoConfigMatch],
) -> Proposal:
    """Combine wire evidence with repo knowledge into a proposal. Nothing is accepted here."""
    if device.device_ref is None:
        raise ValueError("this device has no binding identity — pick it explicitly first")
    if not interrogations:
        title = device.board or "unknown device"
        return Proposal(
            device_ref=device.device_ref,
            identity=device.identity,
            level=device.level,
            summary=f"{title} ({device.device_ref}): no protocol recognised — name the channels?",
            driver_id=None,
            params={},
            rows=[],
            repo_matches=[],
            disambiguation=None,
            confidence=device.confidence,
            evidence=list(device.evidence),
        )
    best = max(interrogations, key=lambda i: i.confidence)
    rows: list[ProposalRow] = []
    for entry in best.bus_map:
        name = _agreed_names(entry.address, repo_matches)
        address_evidence = [
            m
            for m in best.evidence
            if (m.source_ref.external_ref or "").endswith(f"/{entry.address}")
        ]
        rows.append(
            ProposalRow(
                id=part_ref(device.device_ref, entry.address),
                subject=f"{entry.model or 'device'} at address {entry.address}",
                address=entry.address,
                model=entry.model,
                proposed_function=name,
                confidence=max((m.confidence for m in address_evidence), default=best.confidence),
                evidence=address_evidence,
                provenance="repo" if name else "bus",
            )
        )
    disambiguation: Disambiguation | None = None
    if len(repo_matches) > 1:
        signature = best.details.get("calibration_signature") or {}
        favoured = _favoured(signature, repo_matches)
        labels = {m.config_id: m.label for m in repo_matches}
        question = (
            f"{'Two' if len(repo_matches) == 2 else len(repo_matches)} configs in your repo "
            "match this device — which is it?"
        )
        if favoured:
            named = ", ".join(labels[c] for c in favoured)
            question += f" The parts' burned calibration matches {named}."
        disambiguation = Disambiguation(
            question=question,
            options=[
                *favoured,
                *(m.config_id for m in repo_matches if m.config_id not in favoured),
            ],
            favoured=favoured,
        )
    calibration = repo_matches[0].calibration_source if len(repo_matches) == 1 else None
    return Proposal(
        device_ref=device.device_ref,
        identity=device.identity,
        level="protocol",
        summary=best.summary + _repo_sentence(repo_matches, rows),
        driver_id=best.driver_id,
        params=dict(best.params),
        rows=rows,
        repo_matches=list(repo_matches),
        disambiguation=disambiguation,
        confidence=best.confidence,
        evidence=list(best.evidence),
        calibration_source=calibration,
    )
