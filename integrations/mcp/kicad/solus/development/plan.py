"""Deterministic immutable plans; dry runs never touch the filesystem."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from solus.development.models import DevelopmentError, fingerprint, schematic_path
from solus.development.structural import document


@dataclass(frozen=True)
class MutationPlan:
    path: str
    original: bytes | None
    proposed: bytes
    canonical_operation: bytes
    changes: tuple[tuple[str, str | None, str | None], ...]

    @classmethod
    def build(
        cls,
        path: str,
        original: bytes | None,
        proposed: bytes,
        operation: dict[str, Any],
        changes: list[dict[str, Any]],
    ) -> "MutationPlan":
        schematic_path(path)
        if len(path) > 400:
            raise DevelopmentError("file_too_large")
        document(proposed)
        if original is not None:
            document(original)
        try:
            encoded = json.dumps(
                operation, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        except (TypeError, ValueError) as exc:
            raise DevelopmentError("unsupported_value") from exc
        if len(encoded) > 16 * 1024 or len(changes) > 36:
            raise DevelopmentError("file_too_large")
        rows = []
        for row in changes:
            if set(row) != {"label", "before", "after"} or not isinstance(row["label"], str):
                raise DevelopmentError("guard_failed")
            if any(
                v is not None and (not isinstance(v, str) or len(v) > 400) for v in row.values()
            ):
                raise DevelopmentError("file_too_large")
            rows.append((row["label"], row["before"], row["after"]))
        return cls(path, original, proposed, encoded, tuple(rows))

    @property
    def before_fingerprint(self) -> str | None:
        return None if self.original is None else fingerprint(self.original)

    @property
    def after_fingerprint(self) -> str:
        return fingerprint(self.proposed)

    def entity_uuid(self, role: str) -> str:
        identity = json.dumps(
            [self.path, self.before_fingerprint, self.canonical_operation.decode(), role]
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "solus:kicad:" + identity))

    def preview(self) -> list[dict[str, str | None]]:
        return [
            {"label": label, "before": before, "after": after}
            for label, before, after in self.changes
        ] + [
            {
                "label": "Schematic",
                "before": self.path if self.original is not None else None,
                "after": self.path,
            },
            {
                "label": "File fingerprint",
                "before": self.before_fingerprint,
                "after": self.after_fingerprint,
            },
        ]
