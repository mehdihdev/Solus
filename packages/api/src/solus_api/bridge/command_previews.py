"""Approval-card rows for the `code` server's executing tools (SOLUSDEV-317).

docs/api/code-command-execution.md §2.2 and §5.2. Every row is read back from
the server's own `code.plan` answer — the resolved absolute program, the exact
argv, cwd, environment, profile digest and sandbox — never re-assembled
cloud-side. A plan that is refused, malformed, unsandboxed, denied or too large
for the card raises `PreviewRefusal`: nothing is parked and nothing runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from solus_api.agent.command_policy import Risk, classify
from solus_api.agent.preview_refusal import PreviewRefusal
from solus_api.agent.tools.untrusted import redact_text

#: The fixed Solus capture script (§2.4); the setup file is `$1`, never interpolated.
CAPTURE_SCRIPT: Final = 'source "$1" >/dev/null 2>&1 </dev/null || exit 97; exec /usr/bin/env -0'
_CAPTURE_PREFIX: Final = (
    "/bin/bash",
    "--noprofile",
    "--norc",
    "-c",
    CAPTURE_SCRIPT,
    "solus-profile",
)
#: `sandbox-exec`, `landlock` or `landlock-abi<N>` (the server names the ABI).
SANDBOX_KIND: Final = re.compile(r"^(?:sandbox-exec|landlock(?:-abi[0-9]{1,2})?)$")
_LIMITS_CAP: Final = 300
_SANDBOX_NOTE: Final = "writes limited to the workspace, temp and tool caches"
_CHUNK: Final = 400
#: 40 chunks + at most 9 other rows stays inside the gate's 50-row bound.
_JSON_COMMAND_CAP: Final = 16000
#: The legacy shlex rendering keeps its SOLUSDEV-250 bound (45 chunks + 3 rows).
_SHELL_COMMAND_CAP: Final = 18000
_CWD_CAP: Final = 500
_REASON_CAP: Final = 200
_DEFAULT_MAX_RUNTIME: Final = 3600
_DIGEST: Final = re.compile(r"^[0-9a-f]{64}$")
_PROFILE_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_WHITESPACE: Final = re.compile(r"\s+")
_NOTHING: Final = "Nothing was parked or run."


@dataclass(frozen=True)
class CommandPlan:
    """A validated `code.plan` answer."""

    argv: tuple[str, ...]
    cwd: str
    environment: str | None
    profile_name: str | None
    profile_digest: str | None
    sandbox_kind: str
    sandbox_limits: tuple[str, ...] = ()
    writable: tuple[str, ...] = ()


def _refuse(detail: str) -> PreviewRefusal:
    return PreviewRefusal(f"{detail} {_NOTHING}")


def _reason(value: object) -> str:
    """The server's refusal reason as one bounded, redacted, printable line."""
    text = _WHITESPACE.sub(" ", str(value or "unknown reason"))
    printable = "".join(ch for ch in text if ch.isprintable())
    return redact_text(printable.strip())[:_REASON_CAP]


def _printable(value: str) -> bool:
    return all(ch.isprintable() for ch in value)


def _profile(value: object) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, Mapping):
        raise _refuse("The code server returned an invalid command plan.")
    name, digest = value.get("name"), value.get("digest")
    if not (isinstance(name, str) and _PROFILE_NAME.fullmatch(name)):
        raise _refuse("The code server returned an invalid command plan.")
    if not (isinstance(digest, str) and _DIGEST.fullmatch(digest)):
        raise _refuse("The code server returned an invalid command plan.")
    return name, digest


def parse_plan(plan: object) -> CommandPlan:
    """Validate a `code.plan` answer or raise `PreviewRefusal` with the reason."""
    if not isinstance(plan, Mapping):
        raise _refuse("The code server could not produce an executable plan.")
    if plan.get("ok") is not True:
        raise _refuse(
            f"The code server refused to plan this command: {_reason(plan.get('reason'))}."
        )
    argv, cwd, environment = plan.get("argv"), plan.get("cwd"), plan.get("environment")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(arg, str) and arg and _printable(arg) for arg in argv)
        or not isinstance(cwd, str)
        or len(cwd) > _CWD_CAP
        or not _printable(cwd)
        or not (environment is None or (isinstance(environment, str) and _printable(environment)))
    ):
        raise _refuse("The code server returned an invalid command plan.")
    sandbox = plan.get("sandbox")
    kind = sandbox.get("kind") if isinstance(sandbox, Mapping) else None
    if not isinstance(kind, str) or not SANDBOX_KIND.fullmatch(kind):
        raise _refuse("The command plan has no usable OS sandbox (sandbox unavailable).")
    assert isinstance(sandbox, Mapping)
    name, digest = _profile(plan.get("profile"))
    return CommandPlan(
        tuple(argv),
        cwd,
        environment,
        name,
        digest,
        kind,
        _strings(sandbox.get("limitations")),
        _strings(sandbox.get("writable")),
    )


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value[:32] if isinstance(item, str))


def _fingerprint(plan: CommandPlan) -> str:
    canonical = json.dumps(
        {
            "argv": list(plan.argv),
            "cwd": plan.cwd,
            "environment": plan.environment,
            "profile_digest": plan.profile_digest,
            "sandbox_kind": plan.sandbox_kind,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return ":".join(digest[start : start + 16] for start in range(0, 64, 16))


def plan_fingerprint(plan: object) -> str:
    """sha256 of canonical `{argv, cwd, environment, profile_digest, sandbox_kind}`."""
    return _fingerprint(parse_plan(plan))


def _row(label: str, after: str) -> dict[str, Any]:
    return {"label": label, "before": None, "after": after}


def _chunked(label: str, text: str, cap: int) -> list[dict[str, Any]]:
    if len(text) > cap:
        raise _refuse("The command plan cannot fit the approval card; split the action.")
    chunks = [text[start : start + _CHUNK] for start in range(0, len(text), _CHUNK)]
    if len(chunks) == 1:
        return [_row(label, chunks[0])]
    return [_row(f"{label} {i + 1}/{len(chunks)}", chunk) for i, chunk in enumerate(chunks)]


def _sandbox_row(plan: CommandPlan) -> dict[str, Any]:
    text = f"{plan.sandbox_kind} — {_SANDBOX_NOTE}"
    limits = "; ".join(filter(None, (_reason(item) for item in plan.sandbox_limits)))
    if limits:
        text += f"; limits: {limits[:_LIMITS_CAP]}"
    return _row("sandbox", text)


def _inside_writable(plan: CommandPlan) -> bool:
    """The resolved program lives where the project or a command could write it."""
    program = plan.argv[0]
    return any(
        root.startswith("/") and program.startswith(root.rstrip("/") + "/")
        for root in plan.writable
    )


def _profile_text(plan: CommandPlan) -> str:
    if plan.profile_name is None or plan.profile_digest is None:
        return "none"
    return f"{plan.profile_name} · {plan.profile_digest[:12]}"


def _max_runtime(args: Mapping[str, Any]) -> str:
    value = args.get("max_runtime_seconds", _DEFAULT_MAX_RUNTIME)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _refuse("The process arguments are invalid.")
    return f"{value} s"


def command_rows(
    raw: object, args: Mapping[str, Any], *, process: bool = False
) -> list[dict[str, Any]]:
    """Rows for `code.exec` (and `code.process_start` when `process`)."""
    plan = parse_plan(raw)
    command = _chunked("command", json.dumps(list(plan.argv)), _JSON_COMMAND_CAP)
    requested = classify(args.get("argv"))
    for verdict in (requested, classify(plan.argv)):
        if verdict.denied:
            raise _refuse(
                f"The command is denied: {verdict.reason}. Propose a direct argv instead "
                "(no shell, no &&, no pipes)."
            )
    found = set(requested.risks) | ({Risk.PROJECT_SCRIPTS} if _inside_writable(plan) else set())
    risks = ", ".join(risk.value for risk in Risk if risk in found) or "none flagged"
    return [
        _row("program", plan.argv[0]),
        *command,
        _row("cwd", plan.cwd),
        _row("environment", plan.environment or "none"),
        _row("profile", _profile_text(plan)),
        _sandbox_row(plan),
        _row("risk", risks),
        *([_row("max runtime", _max_runtime(args))] if process else []),
        _row("plan fingerprint", _fingerprint(plan)),
    ]


def capture_rows(raw: object, args: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rows for `code.profile_capture`: only the fixed Solus capture argv passes."""
    plan = parse_plan(raw)
    if len(plan.argv) != len(_CAPTURE_PREFIX) + 1 or plan.argv[:-1] != _CAPTURE_PREFIX:
        raise _refuse("The profile capture plan is not the fixed Solus capture script.")
    extends = args.get("extends")
    return [
        _row("setup file", plan.argv[-1]),
        _row("extends", extends if isinstance(extends, str) and extends else "none"),
        *_chunked("command", json.dumps(list(plan.argv)), _JSON_COMMAND_CAP),
        _sandbox_row(plan),
        _row("plan fingerprint", _fingerprint(plan)),
    ]


def legacy_rows(raw: object) -> list[dict[str, Any]]:
    """`create_environment`/`install`/`run`/`test`: the SOLUSDEV-250 rows plus
    the sandbox and the §5.2 fingerprint."""
    plan = parse_plan(raw)
    return [
        *_chunked("command", shlex.join(plan.argv), _SHELL_COMMAND_CAP),
        _row("cwd", plan.cwd),
        _sandbox_row(plan),
        _row("plan fingerprint", _fingerprint(plan)),
    ]
