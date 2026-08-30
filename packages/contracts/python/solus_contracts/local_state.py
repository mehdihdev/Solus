"""SOLUSDEV-166 (ADR-034) — machine-local state files under ``~/.solus``.

The desktop main process WRITES these files; the companion (and later Python
consumers) READ them. The TypeScript twin is
``packages/shared-types/src/local-state.ts``; both validate the shared fixtures
in ``packages/shared-types/fixtures/local-state/`` so the shapes cannot drift.

Ground rules (ADR-034, docs/contracts/local-state.md):

- JSON only; every file carries ``schema_version``; writes are atomic
  (temp + rename) and ``~/.solus`` is 0700.
- NO secrets, ever — ``HOME`` survives the companion's ``env -i`` scrub, so MCP
  fork processes can read this directory.
- A reader that finds a newer ``schema_version`` (``ValidationError`` here —
  the model pins ``Literal[1]``) must leave the file untouched, never rewrite
  it: that is data a future version wrote.

Field names on disk are camelCase (``repoUrl``) exactly as ratified in ADR-034;
Python bridges via serialization aliases, so dump with ``by_alias=True``.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SOLUS_HOME_DIRNAME = ".solus"
PROJECTS_FILENAME = "projects.json"
#: ``~/.solus`` permission bits — private to the user.
SOLUS_HOME_MODE = 0o700
PROJECT_REGISTRY_SCHEMA_VERSION = 1

#: Registry keys are project ids, and a project id becomes a PATH SEGMENT
#: later (``~/.solus/projects/<id>/``) — slashes, dot-segments and escapes are
#: refused at the contract boundary.
PROJECT_ID_PATTERN = r"^[A-Za-z0-9_-]+$"

ProjectId = Annotated[str, StringConstraints(pattern=PROJECT_ID_PATTERN)]


class ProjectFolderLink(BaseModel):
    """One project's link to a working copy on THIS machine."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    #: Absolute path of the working copy. Non-empty.
    path: str = Field(min_length=1)
    #: The repo it was cloned from, when linked via clone (informational).
    repo_url: str | None = Field(default=None, alias="repoUrl")
    #: ISO-8601 instant the project was last opened here (informational).
    last_opened_at: str | None = Field(default=None, alias="lastOpenedAt")


class ProjectRegistry(BaseModel):
    """The whole of ``~/.solus/projects.json``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    projects: dict[ProjectId, ProjectFolderLink] = Field(default_factory=dict)
