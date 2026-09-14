"""Bounded lexical Arduino observations; never execution or inferred board wiring."""

import os
import re
import stat
from pathlib import Path
from typing import Any

MAX_BYTES = 64 * 1024
MAX_FILES = 128
MAX_PINS = 128
_LITERAL = r"(?:A[0-9]{1,3}|[0-9]{1,3})"
_IDENT = r"[A-Za-z_][A-Za-z_0-9]{0,63}"
_NOISE = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
_CALL = re.compile(
    r"(?<![\w.>:])(pinMode|digitalRead|digitalWrite|analogRead|analogWrite)\s*\(\s*([^,)]*)"
)
_DEFINE = re.compile(rf"^\s*#\s*define\s+({_IDENT})\s+({_LITERAL})\s*$", re.M)
_CONST = re.compile(
    rf"\b(?:const|constexpr)\s+(?:unsigned\s+)?(?:int|uint8_t|byte)\s+({_IDENT})\s*=\s*({_LITERAL})\s*;"
)
_INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([A-Za-z0-9_./-]{1,64})[>"]', re.M)
_BUSES = {
    "Wire": "i2c",
    "SPI": "spi",
    "Serial": "uart",
    "Serial1": "uart",
    "Serial2": "uart",
    "Serial3": "uart",
}


def _blank(match: re.Match[str]) -> str:
    return "".join("\n" if char == "\n" else " " for char in match.group())


def _aliases(clean: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    definitions = [*list(_DEFINE.finditer(clean)), *list(_CONST.finditer(clean))]
    for match in definitions:
        name, value = match.groups()
        assigned = re.findall(rf"\b{re.escape(name)}\s*=", clean)
        declarations = re.findall(rf"\b\w+\s+[*&]?\s*{re.escape(name)}\b", clean)
        occurrences = sum(item.group(1) == name for item in definitions)
        if occurrences == 1 and len(assigned) <= 1 and len(declarations) <= 1:
            aliases[name] = value
    return aliases


def _libraries(text: str, clean: str) -> list[str]:
    names = set()
    for match in _INCLUDE.finditer(text):
        prefix = clean[match.start() : match.start() + match.group().find("include")]
        name = match.group(1)
        if prefix.strip() == "#" and ".." not in name.split("/"):
            names.add(name)
    return sorted(names)


def _unqualified(text: str, start: int) -> bool:
    return not text[:start].rstrip().endswith((".", ">", ":"))


def parse_sketch(text: str) -> dict[str, Any]:
    """Observe explicit calls, keeping unresolved expressions visible as unknown."""
    result: dict[str, Any] = {"pins": [], "buses": [], "libraries": [], "incomplete": False}
    if len(text.encode("utf-8")) > MAX_BYTES or "\x00" in text or 'R"' in text or "\\\n" in text:
        return {**result, "incomplete": True}
    clean = _NOISE.sub(_blank, text)
    if "/*" in clean or '"' in clean or "'" in clean:
        return {**result, "incomplete": True}
    conditional = bool(re.search(r"^\s*#\s*(?:if|ifdef|ifndef|elif|else)\b", clean, re.M))
    libraries = _libraries(text, clean)
    result["incomplete"] = conditional or len(libraries) > 64
    result["libraries"] = libraries[:64]
    aliases = {} if conditional else _aliases(clean)
    for match in _CALL.finditer(clean):
        if not _unqualified(clean, match.start()):
            continue
        name = match.group(1)
        if re.search(rf"(?:#\s*define\s+|\b(?:int|void|float|auto)\s+){name}\s*\(", clean):
            result["incomplete"] = True
            continue
        if len(result["pins"]) == MAX_PINS:
            result["incomplete"] = True
            break
        expression = match.group(2).strip()
        pin = expression if re.fullmatch(_LITERAL, expression) else aliases.get(expression)
        if pin is None:
            result["incomplete"] = True
        result["pins"].append(
            {
                "operation": match.group(1),
                "pin": pin,
                "line": clean.count("\n", 0, match.start()) + 1,
            }
        )
    result["buses"] = sorted(
        {
            bus
            for name, bus in _BUSES.items()
            for match in re.finditer(rf"\b{name}\s*\.\s*begin\s*\(", clean)
            if _unqualified(clean, match.start())
        }
    )
    return result


def _open_root(root: Path) -> int:
    absolute = root.absolute()
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read(root: Path, parts: list[str]) -> str:
    if os.name != "posix":
        raise OSError("descriptor-confined reads unavailable")
    if not parts or any(not p or p in {".", ".."} or "/" in p or "\\" in p for p in parts):
        raise ValueError("invalid path")
    descriptor = _open_root(root)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(leaf, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("not regular")
            payload = handle.read(MAX_BYTES + 1)
            if len(payload) > MAX_BYTES:
                raise ValueError("oversized")
            return payload.decode("utf-8")
    finally:
        os.close(descriptor)


def collect_sketches(root: Path, paths: list[list[str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    remaining = 512
    for parts in paths[:MAX_FILES]:
        try:
            value = parse_sketch(_read(root, parts))
        except (OSError, ValueError, UnicodeError):
            value = {"pins": [], "buses": [], "libraries": [], "incomplete": True}
        if len(value["pins"]) > remaining:
            value["pins"] = value["pins"][:remaining]
            value["incomplete"] = True
        remaining -= len(value["pins"])
        rows.append({"parts": parts, **value})
    return rows
