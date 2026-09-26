"""Explicit, inactive dev QA client; never import from application startup.

The caller supplies an authenticated HTTP client and a trusted local attestor that
compares the entire event with its scoped pending database row and verifies that
its tool is the registered code-owned flash implementation. There is currently no
production attestor or registered flash tool: this helper is fixture-proven only.
The attestor must never trust model-authored claims about registration or identity.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError
from solus_api.contracts.action_gate import ToolConfirmationEvent, confirmation_decision_path

# Match livebench.deploy.flash.MAX_ARTIFACT_BYTES without importing deployment code.
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024

Attestor = Callable[[str, dict[str, Any]], Awaitable[bool]]


class QAApprover:
    """A single-device policy that records intent durably before deciding once.

    ``artifact`` identifies immutable bytes whose SHA-256 and size are checked by
    the trusted attestor/flash tool, not a mutable filename accepted on faith.
    A refused or uncertain result is False; it is never permission to retry.
    Preserve the journal across sessions to retain the one-attempt guarantee.
    """

    def __init__(
        self,
        *,
        app_env: str,
        usb_serial: str,
        client: httpx.AsyncClient,
        audit_path: Path,
        verify_stored_action: Attestor,
    ) -> None:
        if app_env != "dev":
            raise ValueError("QA approval is permitted only in dev")
        if not isinstance(usb_serial, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,128}", usb_serial
        ):
            raise ValueError("Exactly one explicit USB serial is required")
        self._target = f"usb:{usb_serial}"
        self._client = client
        self.audit_path = audit_path
        self._verify = verify_stored_action

    def _allowed(self, event: dict[str, Any]) -> bool:
        try:
            ToolConfirmationEvent.model_validate(event)
            UUID(event["confirmation_id"])
        except (ValidationError, ValueError, TypeError, KeyError):
            return False
        args = event.get("args", {})
        return bool(
            event["tool"] == "flash_device"
            and set(args) == {"target", "artifact", "sha256", "size"}
            and args["target"] == self._target
            and isinstance(args["artifact"], str)
            and args["artifact"].strip()
            and isinstance(args["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", args["sha256"])
            and type(args["size"]) is int
            and 0 < args["size"] <= MAX_ARTIFACT_BYTES
        )

    def _record(self, project: str, event: dict[str, Any], status: str) -> bool:
        """Locked JSON lines in Markdown, including a durable one-attempt claim."""
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "project_id": project,
            "status": status,
            "card": event,
        }
        with self.audit_path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            if status == "approval_attempt":
                for line in stream:
                    if not line.startswith("- "):
                        continue
                    old = json.loads(line[2:])
                    if (
                        old["status"] == status
                        and old["project_id"] == project
                        and UUID(old["card"]["confirmation_id"]) == UUID(event["confirmation_id"])
                    ):
                        return False
            stream.write("- " + json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            directory = os.open(self.audit_path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return True

    async def approve(self, project_id: str, card: dict[str, Any]) -> bool:
        """Leave non-allowlisted cards pending; use only the existing decide route."""
        project = str(UUID(project_id))
        event: dict[str, Any] = json.loads(json.dumps(card))
        if not self._allowed(event):
            self._record(project, event, "left_unapproved")
            return False
        try:
            attested = await self._verify(project, event)
        except Exception:
            self._record(project, event, "attestation_failed")
            return False
        if attested is not True:
            self._record(project, event, "left_unapproved")
            return False
        if not self._record(project, event, "approval_attempt"):
            return False
        try:
            response = await self._client.post(
                confirmation_decision_path(project, event["confirmation_id"]),
                json={"decision": "approve"},
                follow_redirects=False,
            )
            response.raise_for_status()
            success = response.json()["data"]["ok"] is True
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            self._record(project, event, "uncertain_or_http_failure")
            return False
        self._record(project, event, "executed" if success else "gate_refused")
        return success
