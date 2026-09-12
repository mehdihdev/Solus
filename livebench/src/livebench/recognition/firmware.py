"""Firmware-source idiom extraction (RBT-02) — the richest signal, no hardware needed.

Parses hobby-MCU C++ firmware (the sketch/PlatformIO shape) and MicroPython with
tree-sitter and extracts, with exact file:line provenance:

* **attach calls** — `servo_elbow.attach(9)`, `wrist = PWM(Pin(12))`: the idiom that
  binds a name to a PWM channel. A symbolic argument (`s.attach(WRIST_PIN)`) records
  the attachment WITHOUT a pin — resolving symbols across a build is inference this
  layer refuses to fake.
* **pin constants** — `#define WRIST_PIN 5`, `const int basePin = 3`, `ELBOW_PIN = 7`.
* **motor constants** — `const float MOTOR_KV = 920.0`.

Every finding is CTR-08 `firmware_symbol` evidence at 0.55 / LOW_CONFIDENCE — code
intent only; the firmware may be stale or wrong relative to the physical build
(RBT-03 asks the user, never assumes). A repo with no recognizable firmware yields
`[]`; per-file parse failures are skipped, never fatal.

Tenancy boundary (the finest line on the board): everything this module emits is
INSTANCE data — this user's pins in this user's repo — and stays in this tenant's
flow. The library IDIOMS it recognizes are tool knowledge worth compounding, but
CTR-05's `ToolKnowledge` cannot express a firmware family today, so the emission
half is deferred to a LANE 0 contract amendment. Deliberately, this module imports
nothing from the knowledge-store boundary — there is no code path an instance fact
could leak through (proven by `lb_firmware_test.py::TestTenancyBoundary`).
"""

import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import tree_sitter_cpp
import tree_sitter_python
from solus_api.fingerprint.contract import MatchState, Modality, ModalityMatch, SourceRef
from tree_sitter import Language, Node, Parser

logger = logging.getLogger(__name__)

MAX_FILE_BYTES: Final = 1024 * 1024
MAX_FILES: Final = 2000
_SKIP_DIRS: Final = {".git", ".pio", "node_modules", ".venv", "venv", "__pycache__"}

_CPP_SUFFIXES: Final = {".ino", ".cpp", ".cc", ".c", ".h", ".hpp"}
_PIN_NAME: Final = re.compile(r"pin", re.IGNORECASE)
_MOTOR_NAME: Final = re.compile(r"motor|servo|gear|torque|rpm|\bkv\b|_kv|kv_", re.IGNORECASE)
_ATTACH_METHODS: Final = {"attach"}
_PY_ACTUATOR_CALLS: Final = {"PWM", "Servo"}

_NOTE: Final = (
    "committed firmware states code intent only — it may be stale or wrong relative "
    "to the physical build; the user confirms (RBT-03), never this layer"
)

FindingKind = Literal["attach_call", "pin_constant", "motor_constant"]

_CPP_LANGUAGE: Final = Language(tree_sitter_cpp.language())
_PY_LANGUAGE: Final = Language(tree_sitter_python.language())
#: Public names for the repo-config parsers that share this module's tree-sitter setup.
CPP_LANGUAGE: Final = _CPP_LANGUAGE
PY_LANGUAGE: Final = _PY_LANGUAGE

__all__ = [
    "CPP_LANGUAGE",
    "MAX_FILE_BYTES",
    "MAX_FILES",
    "PY_LANGUAGE",
    "FirmwareFinding",
    "extract_firmware_findings",
    "node_text",
]


@dataclass(frozen=True)
class FirmwareFinding:
    """One extracted idiom instance, provenance-exact."""

    name: str
    kind: FindingKind
    file: str  # repo-relative posix path
    line: int  # 1-based
    language: Literal["cpp", "python"]
    pin: int | None = None
    value: float | None = None
    name_hint: str | None = None

    @property
    def evidence(self) -> ModalityMatch:
        return ModalityMatch(
            modality=Modality.FIRMWARE_SYMBOL,
            source_ref=SourceRef(source_connector="repo", external_ref=self.file),
            confidence=0.55,
            state=MatchState.LOW_CONFIDENCE,
            evidence={
                "matched_on": "firmware_symbol",
                "value": self.name,
                "line": self.line,
                "note": _NOTE,
            },
        )


def _name_hint(name: str) -> str | None:
    """`servo_elbow` → `elbow`: the CONVENTION that a name encodes the joint. A hint,
    never an identification."""
    lowered = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()  # basePin → base_pin
    for prefix in ("servo_", "motor_", "pin_"):
        lowered = lowered.removeprefix(prefix)
    for suffix in ("_pin", "_servo", "_motor"):
        lowered = lowered.removesuffix(suffix)
    lowered = lowered.strip("_")
    return lowered or None


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None and node.text else ""


node_text = _text


def _walk(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _int_or_none(text: str) -> int | None:
    try:
        return int(text.strip(), 0)
    except ValueError:
        return None


def _float_or_none(text: str) -> float | None:
    try:
        return float(text.strip().rstrip("fF"))
    except ValueError:
        return None


def _constant_finding(
    name: str, value_text: str, file: str, line: int, language: Literal["cpp", "python"]
) -> FirmwareFinding | None:
    if _PIN_NAME.search(name):
        pin = _int_or_none(value_text)
        if pin is None:
            return None
        return FirmwareFinding(
            name=name,
            kind="pin_constant",
            file=file,
            line=line,
            language=language,
            pin=pin,
            name_hint=_name_hint(name),
        )
    if _MOTOR_NAME.search(name):
        value = _float_or_none(value_text)
        if value is None:
            return None
        return FirmwareFinding(
            name=name,
            kind="motor_constant",
            file=file,
            line=line,
            language=language,
            value=value,
            name_hint=_name_hint(name),
        )
    return None


def _first_argument(call: Node) -> Node | None:
    args = call.child_by_field_name("arguments")
    if args is None:
        return None
    for child in args.children:
        if child.type not in ("(", ")", ","):
            return child
    return None


def _cpp_constant(node: Node, file: str, line: int) -> FirmwareFinding | None:
    if node.type == "preproc_def":
        name = _text(node.child_by_field_name("name"))
        value = _text(node.child_by_field_name("value"))
        if name and value:
            return _constant_finding(name, value, file, line, "cpp")
        return None
    name = _text(node.child_by_field_name("declarator"))
    value_node = node.child_by_field_name("value")
    if name and value_node is not None and value_node.type == "number_literal":
        return _constant_finding(name, _text(value_node), file, line, "cpp")
    return None


def _cpp_findings(root: Node, file: str) -> Iterator[FirmwareFinding]:
    for node in _walk(root):
        line = node.start_point[0] + 1
        if node.type == "call_expression":
            function = node.child_by_field_name("function")
            if function is None or function.type != "field_expression":
                continue
            if _text(function.child_by_field_name("field")) not in _ATTACH_METHODS:
                continue
            target = _text(function.child_by_field_name("argument"))
            if not target:
                continue
            arg = _first_argument(node)
            pin = (
                _int_or_none(_text(arg))
                if arg is not None and arg.type == "number_literal"
                else None
            )
            yield FirmwareFinding(
                name=target,
                kind="attach_call",
                file=file,
                line=line,
                language="cpp",
                pin=pin,
                name_hint=_name_hint(target),
            )
        elif node.type in ("preproc_def", "init_declarator"):
            finding = _cpp_constant(node, file, line)
            if finding:
                yield finding


def _py_call_name(call: Node) -> str:
    function = call.child_by_field_name("function")
    if function is None:
        return ""
    if function.type == "attribute":
        return _text(function.child_by_field_name("attribute"))
    return _text(function)


def _py_pin_from_call(call: Node) -> int | None:
    """`PWM(Pin(12))` or `Servo(4)` → 12 / 4; symbolic args stay None."""
    arg = _first_argument(call)
    if arg is None:
        return None
    if arg.type == "integer":
        return _int_or_none(_text(arg))
    if arg.type == "call" and _py_call_name(arg) == "Pin":
        inner = _first_argument(arg)
        if inner is not None and inner.type == "integer":
            return _int_or_none(_text(inner))
    return None


def _py_findings(root: Node, file: str) -> Iterator[FirmwareFinding]:
    for node in _walk(root):
        if node.type != "assignment":
            continue
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or left.type != "identifier":
            continue
        name = _text(left)
        line = node.start_point[0] + 1
        if right.type == "call" and _py_call_name(right) in _PY_ACTUATOR_CALLS:
            yield FirmwareFinding(
                name=name,
                kind="attach_call",
                file=file,
                line=line,
                language="python",
                pin=_py_pin_from_call(right),
                name_hint=_name_hint(name),
            )
        elif right.type in ("integer", "float"):
            finding = _constant_finding(name, _text(right), file, line, "python")
            if finding:
                yield finding


def _language_of(suffix: str) -> Literal["cpp", "python"] | None:
    if suffix in _CPP_SUFFIXES:
        return "cpp"
    if suffix == ".py":
        return "python"
    return None


def _iter_source_files(root: Path) -> Iterator[tuple[Path, Literal["cpp", "python"]]]:
    """Yield in-tree firmware source files. Trust boundary (§7): the checkout is
    connector-supplied and untrusted, so symlinks are NOT followed (a
    `firmware.cpp -> /etc/passwd` must never be read), the traversal budget is
    charged on EVERY directory entry (a million junk files can't exhaust memory
    before the cap bites), and only paths that resolve inside `root` are read."""
    root = root.resolve()
    budget = MAX_FILES * 8  # entries walked before we stop (files + dirs + noise)
    yielded = 0
    walked = 0
    # followlinks=False: symlinked directories are not recursed into.
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for filename in sorted(filenames):
            walked += 1
            if walked > budget or yielded >= MAX_FILES:
                logger.warning("firmware scan capped (walked %d, yielded %d)", walked, yielded)
                return
            path = Path(dirpath) / filename
            language = _language_of(path.suffix)
            if language is None or path.is_symlink():
                continue  # symlinked file: never follow it off the checkout
            if not path.resolve().is_relative_to(root):
                continue  # defensive: a hardlink/mount trick that escapes root
            yielded += 1
            yield path, language


def extract_firmware_findings(root: Path) -> list[FirmwareFinding]:
    """Scan a repo checkout for firmware idioms. `[]` when nothing recognizable."""
    findings: list[FirmwareFinding] = []
    for path, language in _iter_source_files(root):
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                logger.debug("skipping oversized source %s", path.name)
                continue
            source = path.read_bytes()
            parser = Parser(_CPP_LANGUAGE if language == "cpp" else _PY_LANGUAGE)
            tree = parser.parse(source)
        except Exception:
            logger.debug("skipping unparseable source %s", path.name)
            continue
        rel = path.relative_to(root).as_posix()
        extractor = _cpp_findings if language == "cpp" else _py_findings
        findings.extend(extractor(tree.root_node, rel))
    return findings
