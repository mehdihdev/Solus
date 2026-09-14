"""Cloud-owned text-write plans; raw bridge authority never reaches the model."""

import json
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_api.agent.tools.shapes import ToolDescriptor, ToolErrorCode
from solus_api.agent.tools.tool import Tool, ToolException
from solus_api.bridge.tool import _diff_rows

_FINGERPRINT = re.compile(r"(?:[0-9a-f]{16}:){3}[0-9a-f]{16}")


class WriteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=400)
    content: str = Field(max_length=200 * 1024)
    create_dirs: bool = False


def _refuse(message: str = "A fresh complete file preview is required.") -> ToolException:
    return ToolException(message, code=ToolErrorCode.TOOL_ERROR, retryable=False)


def _parse(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return WriteArgs.model_validate(args).model_dump()
    except ValidationError:
        raise _refuse("Invalid text-write arguments.") from None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class _Ticket:
    args: str
    rows: str
    fingerprint: str
    consumed: bool = False


class MachineWriteTool:
    requires_complete_preview = True

    def __init__(self, raw: Tool) -> None:
        if raw.descriptor.name != "machine.write_file":
            raise ValueError("Expected the owned machine.write_file bridge capability")
        self._raw = raw
        self._ticket: ContextVar[_Ticket | None] = ContextVar("machine_write_preview", default=None)
        self._descriptor = ToolDescriptor(
            name="machine.write_file",
            description=(
                "Create or edit one workspace text file with a complete before/after preview "
                "and verified readback. This tool reads and validates existing content internally; "
                "A separate machine.read_file call is not needed for a fully specified write."
            ),
            params=WriteArgs.model_json_schema(),
            returns={"type": "object"},
            requires_confirmation=True,
            consent_summary="Write the reviewed text to the selected workspace file.",
            files_errors=True,
        )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._descriptor

    def _clear(self) -> None:
        ticket = self._ticket.get()
        if ticket is not None:
            ticket.consumed = True
        self._ticket.set(None)

    async def _observe(self, args: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        plan = await self._raw.invoke({**args, "dry_run": True})
        if (
            not isinstance(plan, dict)
            or plan.get("ok") is not True
            or plan.get("dry_run") is not True
        ):
            raise _refuse()
        rows = _diff_rows(plan.get("preview"))
        fingerprint = plan.get("fingerprint")
        if not rows or not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
            raise _refuse()
        if any(
            "[REDACTED]" in value
            for row in rows
            for value in row.values()
            if isinstance(value, str)
        ):
            raise _refuse(
                "The complete file preview is unavailable after sensitive-data filtering."
            )
        content_rows = [row for row in rows if row["label"].startswith("Content ")]
        if (
            rows[0] != {"label": "File", "before": None, "after": args["path"]}
            or len(rows) < 3
            or rows[1] != {"label": "File state fingerprint", "before": None, "after": fingerprint}
            or not content_rows
            or [row["label"] for row in content_rows]
            != [f"Content {i + 1}" for i in range(len(content_rows))]
            or any(not isinstance(row["after"], str) for row in content_rows)
            or "".join(row["after"] for row in content_rows) != args["content"]
        ):
            raise _refuse("The complete file preview does not match the requested text.")
        return rows, fingerprint

    async def preview(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        self._clear()
        parsed = _parse(args)
        rows, fingerprint = await self._observe(parsed)
        self._ticket.set(_Ticket(_canonical(parsed), _canonical(rows), fingerprint))
        return rows

    async def invoke(self, args: dict[str, Any]) -> dict[str, Any]:
        ticket = self._ticket.get()
        consumed = ticket is None or ticket.consumed
        self._clear()
        parsed = _parse(args)
        if ticket is None or consumed or ticket.args != _canonical(parsed):
            raise _refuse()
        rows, fingerprint = await self._observe(parsed)
        if ticket.fingerprint != fingerprint or ticket.rows != _canonical(rows):
            raise _refuse("The file changed since its preview; request a new edit.")
        try:
            result = await self._raw.invoke({**parsed, "expected_fingerprint": ticket.fingerprint})
        except ToolException as exc:
            raise _refuse(
                "The file write was not verified; inspect the file before retrying."
            ) from exc
        if (
            not isinstance(result, dict)
            or result.get("verified") is not True
            or result.get("path") != parsed["path"]
            or result.get("bytes_written") != len(parsed["content"].encode("utf-8"))
        ):
            raise _refuse("The file may have been written, but its result could not be verified.")
        return result


def build_machine_write_tool(raw: Tool) -> MachineWriteTool:
    return MachineWriteTool(raw)
