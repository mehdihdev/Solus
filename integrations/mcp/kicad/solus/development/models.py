"""Validated primitives shared by the owned schematic development tools."""

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

MAX_SCHEMATIC_BYTES = 8 * 1024 * 1024


class DevelopmentError(Exception):
    """A safe stable reason, without paths or design contents."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def fingerprint(data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return ":".join(digest[index : index + 16] for index in range(0, 64, 16))


def validate_fingerprint(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{16}(?::[a-f0-9]{16}){3}", value):
        raise DevelopmentError("stale_plan")
    return value


def schematic_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 for c in value)
        or any(part in ("", ".", "..") for part in value.split("/"))
        or not value.endswith(".kicad_sch")
    ):
        raise DevelopmentError("path_escapes_workspace")
    return value


@dataclass(frozen=True)
class Point:
    x_mm: float
    y_mm: float

    @classmethod
    def from_dict(cls, value: Any) -> "Point":
        result = cls.from_saved(value)
        if any(abs(number - round(number, 4)) > 1e-9 for number in (result.x_mm, result.y_mm)):
            raise DevelopmentError("invalid_geometry")
        return result

    @classmethod
    def from_saved(cls, value: Any) -> "Point":
        if not isinstance(value, dict) or set(value) != {"x_mm", "y_mm"}:
            raise DevelopmentError("invalid_geometry")
        for number in value.values():
            if (
                isinstance(number, bool)
                or not isinstance(number, int | float)
                or not math.isfinite(number)
                or not 0 <= number <= 1000
            ):
                raise DevelopmentError("invalid_geometry")
        return cls(float(value["x_mm"]), float(value["y_mm"]))
