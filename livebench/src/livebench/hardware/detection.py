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

from livebench.definitions.usb_boards import (
    BOARD_TABLE,
    BRIDGE_STREAM_HEADLINE,
    UNKNOWN_HEADLINE,
    VENDOR_FAMILY_TABLE,
    BoardClass,
)
from livebench.hardware.channel import TransportUnavailableError
from livebench.hardware.interrogator import Interrogation, interrogate
from livebench.hardware.registries import Registries
from livebench.hardware.repo_config import RepoConfigMatch
from livebench.recognition.passive import binding_of

logger = logging.getLogger(__name__)

Level = Literal["transport", "board", "protocol", "platform"]
IdentityBasis = Literal["serial", "port_position", "none"]
Tone = Literal["looks_like", "probably", "something"]

#: Serial rates worth a ping, servo bus first. A rate is a transport parameter, not a protocol.
DEFAULT_CANDIDATE_PARAMS: Final[tuple[Mapping[str, Any], ...]] = (
    {"baud": 1_000_000},
    {"baud": 115_200},
    {"baud": 250_000},
    {"baud": 57_600},
    {"baud": 9_600},
)
DEFAULT_BUDGET_S: Final = 0.5
_PROBE_TIMEOUT_S: Final = 0.2
_LOOKS_LIKE_CONFIDENCE: Final = 0.85
_PROBABLY_CONFIDENCE: Final = 0.5
_RATE_AGREEMENT: Final = 0.2  # a declared rate within 20% of the measured one is "its rate"
#: Wire bounds the API re-validates (solus_api.hardware.detect): a wider stream is shown
#: clamped with its true count in the summary; repo-derived text is clipped, never trusted.
MAX_STREAM_CHANNELS: Final = 64
MAX_SUMMARY_CHARS: Final = 1024
_CLIP_CHARS: Final = 64
_SUMMARY_NAMES: Final = 8  # ponytail: 8 clipped names keeps any summary under the wire bound


def _clip(text: str) -> str:
    return text if len(text) <= _CLIP_CHARS else text[: _CLIP_CHARS - 1] + "…"


@dataclass(frozen=True)
class StreamInfo:
    """What a line stream looked like, plus what the repo says the columns are."""

    framing: str
    channel_count: int
    update_hz: float
    channel_names: list[str] | None
    declared_hz: float | None


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
    headline: str = ""
    identity_basis: IdentityBasis = "none"


def headline_for(device: DetectedDevice, best: Interrogation | None) -> str:
    """Plain words for what the USB identity (plus a stream, if one answered) can claim."""
    board = BOARD_TABLE.get((device.vid or -1, device.pid or -1))
    if board is not None and board.kind is BoardClass.MCU_BOARD:
        return board.headline or board.name
    family = VENDOR_FAMILY_TABLE.get(device.vid or -1)
    if family:
        return family
    # Only a LINE stream (a framing the shape interrogator recognised) suggests a hobby
    # board behind the bridge; a self-describing bus answering a ping says nothing about
    # what fronts it, so its plugin summary — not a board guess — is the claim.
    if best is not None and best.details.get("framing"):
        return BRIDGE_STREAM_HEADLINE
    if best is None and board is not None and board.headline:
        return board.headline
    return UNKNOWN_HEADLINE


def tone_for(best: Interrogation | None, repo_matches: Sequence[RepoConfigMatch]) -> Tone:
    """Confidence shown as tone, never as a number the user must interpret."""
    if best is None:
        return "something"
    if best.confidence >= _LOOKS_LIKE_CONFIDENCE:
        return "looks_like"
    if repo_matches or best.confidence >= _PROBABLY_CONFIDENCE:
        return "probably"
    return "something"


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
        key, basis = binding_of(identity)
        binding = (
            TransportBinding(
                kind=TransportKind.USB_SERIAL,
                binding=key,
                vid=identity.vid,
                pid=identity.pid,
                last_seen_path=path,
            )
            if key
            else None
        )
        board = identity.board
        device = DetectedDevice(
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
            identity_basis=basis,
        )
        devices.append(dataclasses.replace(device, headline=headline_for(device, None)))
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
    headline: str = ""
    tone: Tone = "something"
    stream: StreamInfo | None = None
    identity_basis: IdentityBasis = "none"


def _agreed_names(address: str, matches: Sequence[RepoConfigMatch]) -> str | None:
    """A function name only when every matching config that declares this address agrees."""
    names = {p.name for m in matches for p in m.parts if p.address == address}
    return names.pop() if len(names) == 1 else None


def _names_in_order(match: RepoConfigMatch, best: Interrogation) -> list[str]:
    by_address = {p.address: p.name for p in match.parts}
    return [by_address.get(e.address, e.address) for e in best.bus_map[:MAX_STREAM_CHANNELS]]


def _channel_count(best: Interrogation) -> int:
    return int(best.details.get("channel_count", len(best.bus_map)))


def _stream_of(best: Interrogation, matches: Sequence[RepoConfigMatch]) -> StreamInfo | None:
    """A line driver's shape, with the columns named when exactly one repo config agrees.
    Clamped to the wire bound; the summary carries the true count."""
    framing = best.details.get("framing")
    if not isinstance(framing, str):
        return None
    only = matches[0] if len(matches) == 1 else None
    declared = only.params.get("declared_hz") if only else None
    return StreamInfo(
        framing=framing,
        channel_count=min(_channel_count(best), MAX_STREAM_CHANNELS),
        update_hz=float(best.details.get("update_hz", 0.0)),
        channel_names=_names_in_order(only, best) if only else None,
        declared_hz=float(declared) if isinstance(declared, int | float) else None,
    )


def _shape_clause(best: Interrogation, stream: StreamInfo) -> str:
    observed = _channel_count(best)
    shown = f" (showing {MAX_STREAM_CHANNELS})" if observed > MAX_STREAM_CHANNELS else ""
    return f"{observed} channels at {stream.update_hz:.0f} Hz{shown}"


def _repo_clause(
    matches: Sequence[RepoConfigMatch], rows: Sequence[ProposalRow], stream: StreamInfo | None
) -> str | None:
    if len(matches) > 1:
        return f"{len(matches)} configs in your repo match"
    if not matches:
        return None
    match = matches[0]
    if match.names_by_print_order and stream and stream.channel_names:
        names = [_clip(n) for n in stream.channel_names[:_SUMMARY_NAMES]]
        text = "your sketch names them " + ", ".join(names)
        text += " …" if len(stream.channel_names) > _SUMMARY_NAMES else ""
        rate = stream.declared_hz
        if rate and stream.update_hz and abs(rate - stream.update_hz) <= _RATE_AGREEMENT * rate:
            text += " at your sketch's rate"
        return text
    named = [f"{r.address} is {_clip(r.proposed_function)}" for r in rows if r.proposed_function]
    text = f"matches your {_clip(match.label)} config"
    if named:
        text += "; your repo says " + ", ".join(named[:3]) + (" …" if len(named) > 3 else "")
    source = match.calibration_source
    return text + (f"; calibration found at {_clip(source)}" if source else "")


def propose(
    device: DetectedDevice,
    interrogations: Sequence[Interrogation],
    *,
    repo_matches: Sequence[RepoConfigMatch],
) -> Proposal:
    """Combine wire evidence with repo knowledge into a proposal. Nothing is accepted here."""
    if device.device_ref is None:
        raise ValueError("this device has no binding identity yet — reconnect it to verify")
    if not interrogations:
        headline = headline_for(device, None)
        return Proposal(
            device_ref=device.device_ref,
            identity=device.identity,
            level=device.level,
            summary=(
                f"{headline} ({device.device_ref}): no protocol recognised — name the channels?"
            ),
            driver_id=None,
            params={},
            rows=[],
            repo_matches=[],
            disambiguation=None,
            confidence=device.confidence,
            evidence=list(device.evidence),
            headline=headline,
            identity_basis=device.identity_basis,
        )
    best = max(interrogations, key=lambda i: i.confidence)
    stream = _stream_of(best, repo_matches)
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
                evidence=address_evidence or list(best.evidence),  # a shape row shows the shape
                provenance="repo" if name else "bus",
            )
        )
    disambiguation: Disambiguation | None = None
    if len(repo_matches) > 1:
        signature = best.details.get("calibration_signature") or {}
        favoured = _favoured(signature, repo_matches)
        labels = {m.config_id: _clip(m.label) for m in repo_matches}
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
    headline = headline_for(device, best)
    lead = [headline, _shape_clause(best, stream)] if stream else [best.summary]
    clause = _repo_clause(repo_matches, rows, stream)
    return Proposal(
        device_ref=device.device_ref,
        identity=device.identity,
        level="protocol",
        # ponytail: the parts are bounded above; the slice is the one guarantee the wire needs
        summary=" · ".join([*lead, *([clause] if clause else [])])[:MAX_SUMMARY_CHARS],
        driver_id=best.driver_id,
        params=dict(best.params),
        rows=rows,
        repo_matches=list(repo_matches),
        disambiguation=disambiguation,
        confidence=best.confidence,
        evidence=list(best.evidence),
        calibration_source=calibration,
        headline=headline,
        tone=tone_for(best, repo_matches),
        stream=stream,
        identity_basis=device.identity_basis,
    )
