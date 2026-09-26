"""lerobot repo-config parser (SOLUSDEV-248 R2). A lerobot `Robot`/`Teleoperator` class builds a
`<Vendor>MotorsBus(motors={name: Motor(id, model, norm_mode)})`; its calibration lives outside
the repo at `<HF_LEROBOT_CALIBRATION>/<robots|teleoperators>/<class.name>/<id>.json`. Each
(class, calibration file) pair is one proposal input, provenance `repo`.

Repo code is untrusted (CLAUDE.md §7): everything here is `ast` — nothing is imported or executed,
and names resolve no further than literals and same-method assignments.
"""

from __future__ import annotations

import ast
import dataclasses
import itertools
import json
import logging
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Final

from solus_api.hardware.config import CalibrationMode

from livebench.hardware.repo_config import RepoConfigMatch, RepoPartDecl
from livebench.recognition.firmware import decode_extraction_source

logger = logging.getLogger(__name__)

_PARSER_ID: Final = "lerobot"
_MAX_PY_BYTES: Final = 512 * 1024
_MAX_JSON_BYTES: Final = 256 * 1024
_MAX_MOTORS: Final = 256
_MAX_CALIBRATION_FILES: Final = 64
_MAX_CLASSES: Final = 200
_MAX_NAME_HOPS: Final = 4
_SKIP_DIRS: Final = frozenset({"examples", "tests", "docs", "benchmarks"})
_KIND_DIRS: Final = {"Robot": ("robots",), "Teleoperator": ("teleoperators",)}
_ALL_KINDS: Final = ("robots", "teleoperators")
_NORM_MODES: Final = {
    "DEGREES": CalibrationMode.DEGREES,
    "RANGE_0_100": CalibrationMode.RANGE_0_100,
    "RANGE_M100_100": CalibrationMode.RANGE_M100_100,
}
_PROTOCOL_HINTS: Final = {"Feetech": "feetech-sts", "Dynamixel": "dynamixel-2"}
_CALIBRATION_KEYS: Final = ("drive_mode", "homing_offset", "range_min", "range_max")
_TOGGLE_NOTE: Final = "Normalization depends on a runtime condition; mode is unresolved."
_SAFE_NAME: Final = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*")  # one path segment, never `..`


# ── AST helpers ───────────────────────────────────────────────────────────────


def _ident(node: ast.expr | None) -> str | None:
    """The last identifier of a `Name`/`Attribute` — the only name resolution done here."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _str_const(node: ast.expr | None) -> str | None:
    value = node.value if isinstance(node, ast.Constant) else None
    return value if isinstance(value, str) else None


def _int_const(node: ast.expr | None) -> int | None:
    value = node.value if isinstance(node, ast.Constant) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _resolve_norm(
    node: ast.expr | None, assigns: Mapping[str, ast.expr], hops: int = 0
) -> tuple[CalibrationMode | None, bool]:
    """(mode, toggled). Conditional modes require runtime evidence and stay unresolved."""
    if node is None or hops > _MAX_NAME_HOPS:
        return None, False
    if isinstance(node, ast.Attribute) and _ident(node.value) == "MotorNormMode":
        return _NORM_MODES.get(node.attr), False
    if isinstance(node, ast.Name):
        return _resolve_norm(assigns.get(node.id), assigns, hops + 1)
    if isinstance(node, ast.IfExp):
        return None, True
    return None, False


def _motor_args(call: ast.Call) -> tuple[ast.expr | None, ast.expr | None, ast.expr | None]:
    positional: list[ast.expr | None] = [*call.args, None, None, None]
    keyed = {kw.arg: kw.value for kw in call.keywords if kw.arg}
    return (
        keyed.get("id", positional[0]),
        keyed.get("model", positional[1]),
        keyed.get("norm_mode", positional[2]),
    )


def _lerobot_parts(
    motors: ast.Dict, assigns: Mapping[str, ast.expr]
) -> tuple[list[RepoPartDecl], bool]:
    parts: list[RepoPartDecl] = []
    toggled = False
    for key, value in zip(motors.keys, motors.values, strict=True):
        name = _str_const(key)
        if name is None or not isinstance(value, ast.Call) or _ident(value.func) != "Motor":
            continue
        motor_id, model, norm = _motor_args(value)
        address = _int_const(motor_id)
        if address is None:
            continue
        mode, by_toggle = _resolve_norm(norm, assigns)
        toggled = toggled or by_toggle
        parts.append(
            RepoPartDecl(
                name=name, address=str(address), model=_str_const(model), calibration_mode=mode
            )
        )
        if len(parts) >= _MAX_MOTORS:
            break
    return parts, toggled


def _lerobot_bus_call(
    cls: ast.ClassDef,
) -> tuple[ast.Call, ast.Dict, dict[str, ast.expr]] | None:
    """The first `*MotorsBus(motors={...})` call in any method, plus that method's assignments."""
    for method in cls.body:
        if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        assigns = {
            target.id: stmt.value
            for stmt in ast.walk(method)
            if isinstance(stmt, ast.Assign)
            for target in stmt.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(method):
            if not isinstance(node, ast.Call) or not (_ident(node.func) or "").endswith(
                "MotorsBus"
            ):
                continue
            motors = next((kw.value for kw in node.keywords if kw.arg == "motors"), None)
            if isinstance(motors, ast.Dict):
                return node, motors, assigns
    return None


def _lerobot_name(cls: ast.ClassDef) -> str | None:
    """The class-level `name = "so_follower"` lerobot keys its calibration directory by."""
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and [_ident(t) for t in stmt.targets] == ["name"]:
            return _str_const(stmt.value)
    return None


def _lerobot_kinds(cls: ast.ClassDef) -> tuple[str, ...]:
    for base in cls.bases:
        kinds = _KIND_DIRS.get(_ident(base) or "")
        if kinds:
            return kinds
    return _ALL_KINDS


@dataclass(frozen=True)
class _LerobotClass:
    class_name: str
    source: Path
    kinds: tuple[str, ...]
    calibration_name: str | None
    protocol_hint: str | None
    port_hint: str | None
    parts: list[RepoPartDecl]
    params: dict[str, Any]


def _lerobot_class(cls: ast.ClassDef, source: Path) -> _LerobotClass | None:
    found = _lerobot_bus_call(cls)
    if found is None:
        return None
    call, motors, assigns = found
    parts, toggled = _lerobot_parts(motors, assigns)
    if not parts:
        return None
    callee = _ident(call.func) or ""
    name = _lerobot_name(cls)
    params: dict[str, Any] = {"lerobot_name": name} if name else {}
    if toggled:
        params["note"] = _TOGGLE_NOTE
    return _LerobotClass(
        class_name=cls.name,
        source=source,
        kinds=_lerobot_kinds(cls),
        calibration_name=name if name and _SAFE_NAME.fullmatch(name) else None,
        protocol_hint=next((h for v, h in _PROTOCOL_HINTS.items() if callee.startswith(v)), None),
        port_hint=_str_const(next((kw.value for kw in call.keywords if kw.arg == "port"), None)),
        parts=parts,
        params=params,
    )


def _lerobot_classes_in(path: Path, root: Path) -> Iterator[ast.ClassDef]:
    if path.suffix != ".py":
        return
    try:
        if _SKIP_DIRS.intersection(path.relative_to(root).parts[:-1]):
            return
        if path.stat().st_size > _MAX_PY_BYTES:
            return
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, SyntaxError, RecursionError):  # ValueError: null bytes
        logger.info("lerobot parser skipped %s", path)
        return
    yield from (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))


# ── calibration files ─────────────────────────────────────────────────────────


def _lerobot_calibration_root() -> Path:
    return Path(
        os.environ.get("HF_LEROBOT_CALIBRATION", "~/.cache/huggingface/lerobot/calibration")
    ).expanduser()


def _lerobot_calibration_files(calibration_root: Path, klass: _LerobotClass) -> list[Path]:
    if klass.calibration_name is None:
        return []
    files = [
        path
        for kind in klass.kinds
        for path in sorted((calibration_root / kind / klass.calibration_name).glob("*.json"))
    ]
    return files[:_MAX_CALIBRATION_FILES]


def _lerobot_load_calibration(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError) as exc:
        logger.info("lerobot calibration %s skipped: %s", path, type(exc).__name__)
        return None
    if not isinstance(data, dict):
        logger.info("lerobot calibration %s skipped: not a JSON object", path)
        return None
    return data


def _lerobot_calibrated(part: RepoPartDecl, data: Mapping[str, Any], source: str) -> RepoPartDecl:
    """The part with the file's values attached — only when the file names it at the same id."""
    entry = data.get(part.name)
    if not isinstance(entry, Mapping) or str(entry.get("id")) != part.address:
        return part
    values: dict[str, float | int] = {
        key: entry[key]
        for key in _CALIBRATION_KEYS
        if isinstance(entry.get(key), int | float) and not isinstance(entry.get(key), bool)
    }
    if not values:
        return part
    return dataclasses.replace(part, calibration=values, calibration_source=source)


def _lerobot_matches(klass: _LerobotClass, calibration_files: list[Path]) -> list[RepoConfigMatch]:
    bare = RepoConfigMatch(
        config_id=f"lerobot:{klass.class_name}",
        parser_id=_PARSER_ID,
        label=klass.class_name,
        source=str(klass.source),
        protocol_hint=klass.protocol_hint,
        parts=list(klass.parts),
        port_hint=klass.port_hint,
        params=dict(klass.params),
    )
    matches: list[RepoConfigMatch] = []
    for path in calibration_files:
        data = _lerobot_load_calibration(path)
        if data is None:
            continue
        stem = path.stem
        matches.append(
            dataclasses.replace(
                bare,
                config_id=f"{bare.config_id}:{stem}",
                label=f"{klass.class_name} · {'(no id)' if stem == 'None' else stem}",
                parts=[_lerobot_calibrated(part, data, str(path)) for part in klass.parts],
                calibration_source=str(path),
            )
        )
    return matches or [bare]


class LerobotConfigParser:
    """`Robot`/`Teleoperator` classes building a `*MotorsBus(motors={...})`: one match per
    calibration file lerobot keeps for the class, or one bare match when it keeps none."""

    parser_id: ClassVar[str] = _PARSER_ID

    def __init__(self, calibration_root: Path | None = None) -> None:
        self._calibration_root = (
            _lerobot_calibration_root() if calibration_root is None else calibration_root
        )

    def extract_bytes(
        self, source: bytes, *, suffix: str, source_ref: str
    ) -> list[RepoConfigMatch]:
        """Read one authorized file by AST; no adjacent files or calibration cache."""
        if suffix != ".py":
            return []
        text = decode_extraction_source(source, source_ref)
        try:
            tree = ast.parse(text)
        except (ValueError, SyntaxError, RecursionError) as exc:
            raise ValueError("Invalid Python source for configuration review") from exc
        nodes = list(itertools.islice(ast.walk(tree), 20001))
        classes = [node for node in nodes if isinstance(node, ast.ClassDef)]
        if len(nodes) > 20000 or len(classes) > _MAX_CLASSES:
            raise ValueError("Python source exceeds configuration review budget")
        matches: list[RepoConfigMatch] = []
        for node in classes:
            klass = _lerobot_class(node, Path(source_ref))
            if klass is not None:
                matches.extend(
                    dataclasses.replace(match, source=source_ref, port_hint=None)
                    for match in _lerobot_matches(klass, [])
                )
        return matches

    def scan(self, root: Path, files: list[Path]) -> list[RepoConfigMatch]:
        classes = (
            klass
            for path in files
            for node in _lerobot_classes_in(path, root)
            if (klass := _lerobot_class(node, path)) is not None
        )
        matches: list[RepoConfigMatch] = []
        for klass in itertools.islice(classes, _MAX_CLASSES):
            files_for = _lerobot_calibration_files(self._calibration_root, klass)
            matches.extend(_lerobot_matches(klass, files_for))
        return matches
