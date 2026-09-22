"""Bounded fixed-argv ERC; incomplete checks never become a passing verdict."""

import json
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from solus.cli_detect import detect_kicad_cli
from solus.development.commit import read_schematic
from solus.development.common import text, workspace
from solus.development.flatpak_export import capture_erc, encode_snapshot
from solus.development.models import DevelopmentError, fingerprint
from solus.development.structural import children, document
from solus.export_files import publish_artifact

_MAX_REPORT = 8 * 1024 * 1024


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise DevelopmentError("invalid_erc_report")
    return value


def _item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict) or not isinstance(item.get("pos"), dict):
        raise DevelopmentError("invalid_erc_report")
    position = item["pos"]
    for axis in ("x", "y"):
        value = position.get(axis)
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise DevelopmentError("invalid_erc_report")
    return {
        "description": text(item.get("description"), 400),
        "x_mm": position["x"],
        "y_mm": position["y"],
    }


def _report(body: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(body, dict) or body.get("coordinate_units") != "mm":
        raise DevelopmentError("invalid_erc_report")
    severities = _list(body.get("included_severities"))
    if any(not isinstance(severity, str) for severity in severities) or not {
        "error",
        "warning",
    } <= set(severities):
        raise DevelopmentError("invalid_erc_report")
    sheets = _list(body.get("sheets"))
    if not sheets:
        raise DevelopmentError("invalid_erc_report")
    violations = []
    for sheet in sheets:
        if not isinstance(sheet, dict):
            raise DevelopmentError("invalid_erc_report")
        for violation in _list(sheet.get("violations")):
            if not isinstance(violation, dict) or violation.get("severity") not in (
                "error",
                "warning",
                "exclusion",
            ):
                raise DevelopmentError("invalid_erc_report")
            violations.append(
                {
                    "severity": violation["severity"],
                    "description": text(violation.get("description"), 400),
                    "items": [_item(item) for item in _list(violation.get("items"))],
                }
            )
    ignored = []
    for check in _list(body.get("ignored_checks", [])):
        if not isinstance(check, dict):
            raise DevelopmentError("invalid_erc_report")
        ignored.append(
            {"key": text(check.get("key"), 120), "description": text(check.get("description"), 400)}
        )
    return violations, ignored


def _unchecked(digest: str, reason: str) -> dict[str, Any]:
    return {
        "checked": False,
        "passed": None,
        "fingerprint": digest,
        "errors": None,
        "warnings": None,
        "violations": [],
        "degraded": True,
        "reason": reason,
    }


def _capture_report(
    cli: str, root: Path, schematic_path: str, original: bytes
) -> tuple[int, bytes]:
    adapter = Path(__file__).resolve().parents[2] / "bin/kicad-cli-flatpak"
    if Path(cli).resolve() == adapter:
        from solus.development.flatpak_export import ERC

        completed = subprocess.run(  # noqa: S603 — pinned adapter, fixed operation
            [cli, *ERC, "--output", "-", "-"],
            input=encode_snapshot("root.kicad_sch", {"root.kicad_sch": original}),
            capture_output=True,
            timeout=35,
            check=False,
        )
        code, raw = completed.returncode, completed.stdout
    else:
        with tempfile.TemporaryDirectory(prefix="solus-erc-") as directory:
            if Path(directory).is_relative_to(root):
                raise DevelopmentError("cli_failed")
            snapshot = Path(directory) / Path(schematic_path).name
            snapshot.write_bytes(original)
            captured = capture_erc(str(snapshot), cli)
            if captured is None:
                raise DevelopmentError("cli_failed")
            code, raw = captured
    return code, raw


def check_erc(schematic_path: str) -> dict[str, Any]:
    root = workspace()
    original = read_schematic(root, schematic_path)
    digest = fingerprint(original)
    if children(document(original), "sheet"):
        return _unchecked(digest, "unsupported_symbol")
    cli = detect_kicad_cli()
    if cli is None:
        return _unchecked(digest, "cli_unavailable")
    try:
        code, raw = _capture_report(cli, root, schematic_path, original)
        if code not in (0, 5):
            return _unchecked(digest, "cli_failed")
        if len(raw) > _MAX_REPORT:
            return _unchecked(digest, "file_too_large")
        violations, ignored = _report(json.loads(raw))
        if read_schematic(root, schematic_path) != original:
            return _unchecked(digest, "stale_plan")
        errors = sum(row["severity"] == "error" for row in violations)
        warnings = sum(row["severity"] == "warning" for row in violations)
        if code == 5 and not violations:
            return _unchecked(digest, "invalid_erc_report")
        result = {
            "checked": True,
            "passed": errors == 0 and warnings == 0,
            "fingerprint": digest,
            "errors": errors,
            "warnings": warnings,
            "violations": violations,
            "ignored_checks": ignored,
            "degraded": False,
            "reason": None,
            "violations_truncated": False,
            "artifact_path": None,
        }
        if len(json.dumps(result).encode()) > 512 * 1024:
            artifact = publish_artifact("erc-" + digest.split(":")[0] + ".json", raw)
            result.update(
                violations=[],
                violations_truncated=True,
                artifact_path=artifact,
            )
        return result
    except (OSError, subprocess.SubprocessError, ValueError, DevelopmentError):
        return _unchecked(digest, "cli_failed")
