"""The interpreter health probe — mcp-fork-runtime.md §3 step 1.

`<python> -I -c PROBE_SCRIPT` prints one JSON object. Only CPython 3.12/3.13 is
accepted, and never a virtual environment's interpreter as a base (`venv
--copies` from a venv is fragile); everything else is refused with the
protocol's reason code."""

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from solus_companion.runtime.errors import ErrorCode
from solus_companion.runtime.proc import Runner

logger = logging.getLogger("solus.companion.runtime")

PROBE_SCRIPT = (
    "import json,platform,sys;"
    "print(json.dumps({'implementation':sys.implementation.name,"
    "'version':platform.python_version(),'executable':sys.executable,"
    "'venv':sys.prefix!=sys.base_prefix}))"
)
PROBE_TIMEOUT_SECONDS = 15.0
SUPPORTED_VERSION_RE = re.compile(r"^3\.1[23]\.\d+$")
_REPORTABLE_VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.+-]{0,31}$")
_MAX_PROBE_OUTPUT = 8192

Implementation = Literal["cpython", "pypy", "unknown"]


class ProbeReport(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    implementation: str = Field(max_length=32)
    version: str = Field(max_length=32)
    executable: str = Field(max_length=4096)
    #: Absent from an older or odd probe → treated as not a venv.
    venv: bool = False


@dataclass(frozen=True)
class Verdict:
    supported: bool
    reason: ErrorCode | None
    version: str | None
    implementation: Implementation


def run_probe(python: str, runner: Runner, env: Mapping[str, str]) -> ProbeReport | None:
    result = runner([python, "-I", "-c", PROBE_SCRIPT], timeout=PROBE_TIMEOUT_SECONDS, env=env)
    if not result.ok or len(result.stdout) > _MAX_PROBE_OUTPUT:
        return None
    try:
        return ProbeReport.model_validate(json.loads(result.stdout.strip()))
    except (ValueError, ValidationError):
        logger.info("interpreter probe produced unreadable output")
        return None


def _implementation(name: str) -> Implementation:
    return name if name in ("cpython", "pypy") else "unknown"  # type: ignore[return-value]


def judge(report: ProbeReport | None, *, allow_venv: bool = False) -> Verdict:
    """`allow_venv` is only for the fork env's own copied interpreter (§3 health
    check); a base interpreter that is itself a venv is refused."""
    if report is None:
        return Verdict(False, "python_probe_failed", None, "unknown")
    implementation = _implementation(report.implementation)
    version = report.version if _REPORTABLE_VERSION_RE.fullmatch(report.version) else None
    if implementation != "cpython":
        return Verdict(False, "python_not_cpython", version, implementation)
    if SUPPORTED_VERSION_RE.fullmatch(report.version) is None:
        return Verdict(False, "python_unsupported_version", version, implementation)
    if report.venv and not allow_venv:
        return Verdict(False, "python_is_venv", version, implementation)
    return Verdict(True, None, version, implementation)


def is_store_alias(path: str) -> bool:
    """The Microsoft Store app-execution alias: `…\\WindowsApps\\python*.exe`."""
    parts = path.replace("\\", "/").lower().split("/")
    return (
        len(parts) >= 2
        and parts[-2] == "windowsapps"
        and parts[-1].startswith("python")
        and parts[-1].endswith(".exe")
    )
