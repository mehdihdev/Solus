"""Account-scoped, content-bound repo inputs for a local device proposal."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import AfterValidator, Field, StringConstraints

from solus_api.core.errors import APIError
from solus_api.hardware.local_sources import LocalHardwareSources, LocalSourceError


def _unique(refs: list[str]) -> list[str]:
    if len(set(refs)) != len(refs):
        raise ValueError("Source references must be unique")
    return refs


SourceRefs = Annotated[
    list[
        Annotated[
            str,
            StringConstraints(
                min_length=43,
                max_length=43,
                pattern=r"^source:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$",
            ),
        ]
    ],
    Field(max_length=32),
    AfterValidator(_unique),
]


@dataclass(frozen=True)
class RepoEvidence:
    digest: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def key(
        self, project: uuid.UUID, account: uuid.UUID, device: str
    ) -> tuple[uuid.UUID, uuid.UUID, str, str]:
        return project, account, device, self.digest


def _read(local: object, project: uuid.UUID, account: uuid.UUID, refs: list[str]) -> RepoEvidence:
    try:
        reader = LocalHardwareSources.for_local_runner(local)
        sources = [reader.read_source(project, account, ref) for ref in sorted(refs)]
    except LocalSourceError as exc:
        status = 404 if exc.code == "not_found" else 409 if exc.code == "source_changed" else 422
        raise APIError(
            status, exc.code, "Relink and review the source in this account and project."
        ) from None
    snapshot = [
        (source.source_ref, source.suffix, hashlib.sha256(source.content).hexdigest())
        for source in sources
    ]
    return RepoEvidence(
        hashlib.sha256(json.dumps(snapshot).encode()).hexdigest(),
        [
            {"source_ref": source.source_ref, "suffix": source.suffix, "content": source.content}
            for source in sources
        ],
    )


async def read_repo_evidence(
    local: object, project: uuid.UUID, account: uuid.UUID, refs: list[str]
) -> RepoEvidence:
    if not refs:
        return RepoEvidence()
    return await asyncio.to_thread(_read, local, project, account, refs)
