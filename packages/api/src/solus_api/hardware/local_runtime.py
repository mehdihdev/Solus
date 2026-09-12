"""Prepare private, ephemeral driver input after authenticated graph resolution."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from solus_api.core.errors import APIError
from solus_api.hardware.config import (
    EntityHardwareConfig,
    HardwareConfig,
    TransportKind,
    is_private_source,
)
from solus_api.hardware.local_sources import LocalHardwareSources, LocalSourceError
from solus_api.livebench.sessions import AmbiguousDeviceError, DeviceNotFoundError

logger = logging.getLogger(__name__)


async def open_local_hardware(runner: Any, document: dict[str, Any], project_id: uuid.UUID) -> Any:
    """Never let a driver echo private input into API errors or traceback logs."""
    try:
        return await runner.open_robot(document, project_id=project_id)
    except AmbiguousDeviceError:
        raise APIError(
            409, "device_ambiguous", "More than one device matches; select it again."
        ) from None
    except DeviceNotFoundError:
        raise APIError(404, "device_not_found", "The configured device is not connected.") from None
    except ValueError:
        raise APIError(
            422, "validation_error", "The hardware configuration could not open this device."
        ) from None
    except Exception as exc:
        logger.warning("hardware open failed: project=%s error=%s", project_id, type(exc).__name__)
        raise APIError(
            503, "source_unavailable", "The hardware session could not be started."
        ) from None


def prepare_local_hardware(
    runner: object | None,
    config: HardwareConfig,
    project_id: uuid.UUID,
    account_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    owner_config: EntityHardwareConfig | None = None,
) -> dict[str, Any]:
    """Verify file evidence without replacing stored values or authorizing a port.

    Run off-loop. Only the local driver receives the returned document; callers
    must construct response/session metadata from the original portable config.
    A last-seen hint is never a confirmed_device_path or reconnect permission.
    """
    try:
        reader = LocalHardwareSources.for_local_runner(runner)
        references: set[str] = set()
        components = list(config.parts.values())
        if owner_config is not None and owner_config.component is not None:
            components.append(owner_config.component)
        for part in components:
            source = part.calibration.source if part.calibration is not None else None
            if source is not None and is_private_source(source):
                raise LocalSourceError("relink_required")
            if source is not None and source.startswith("source:"):
                references.add(source)
        for reference in references:
            reader.read_source(project_id, account_id, reference)
        hint = reader.binding_hint(project_id, account_id, entry_id)
    except LocalSourceError as exc:
        if exc.code == "source_unavailable":
            raise APIError(503, exc.code, "The local hardware runner is unavailable.") from None
        if exc.code == "source_changed":
            raise APIError(
                409,
                exc.code,
                "A calibration source changed. Review and relink it before connecting.",
            ) from None
        raise APIError(
            422,
            "relink_required",
            "Relink the calibration source in this account before connecting.",
        ) from None
    document = config.model_dump(mode="json")
    if document["identity"] is not None:
        document["identity"]["last_seen_path"] = (
            hint
            if config.identity is not None and config.identity.kind is TransportKind.USB_SERIAL
            else None
        )
    return document
