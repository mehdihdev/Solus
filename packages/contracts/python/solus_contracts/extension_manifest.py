"""SOLUSDEV-235 (ADR-035) — the ``extension.toml`` manifest contract.

An extension bundle declares itself in ONE fixed-name file at its root. This
module is the Python half of that shape; the TypeScript twin is
``packages/shared-types/src/extension-manifest.ts`` and both validate the shared
fixtures in ``packages/shared-types/fixtures/extension-manifest/`` so the
publish validator (API), the desktop developer mode, and the Store can never
disagree about what a valid manifest is.

Posture (CLAUDE.md §7, ADR-034/035): everything here is UNTRUSTED developer
input. Unknown fields reject everywhere; every free-text field is length-capped;
file references are relative, traversal-free, and extension-checked; nothing in
the manifest can name a command or trigger execution. Byte caps on the
referenced files (``LIMITS``) are enforced by the bundle validator, which reads
this module for the numbers.

The module takes the DECODED TOML object (``tomllib.loads`` output) rather than
TOML text so the same models validate JSON fixtures and API bodies unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

EXTENSION_MANIFEST_FILENAME = "extension.toml"
#: The LATEST schema this Solus writes and validates. SOLUSDEV-246 (STORE ST1)
#: added version 2 — the first-party ``[backend]`` / ``[graph]`` / ``[tools]``
#: tables — and every version 1 manifest published before it parses unchanged.
EXTENSION_MANIFEST_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2)
#: The tables only a first-party bundle may declare (SOLUSDEV-246). Unknown at
#: schema_version 1; at 2 the publish validator additionally requires a staff
#: publisher and an in-repo capability package — the manifest CLAIMS, Solus
#: code decides (CLAUDE.md §7).
FIRST_PARTY_TABLES = ("backend", "graph", "tools")

#: The id doubles as the bundle folder name on every OS the desktop ships on
#: (case-insensitive file systems included), so it is a lowercase slug and
#: nothing else. 2–64 characters.
EXTENSION_ID_PATTERN = r"^[a-z][a-z0-9-]{1,63}$"
#: Admitted by the regex but colliding with object internals on the TS side.
RESERVED_EXTENSION_IDS = frozenset({"__proto__", "constructor", "prototype"})

SEMVER_PATTERN = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$"
#: An https ORIGIN — scheme + host (+ optional port), no path, no query.
NETWORK_ORIGIN_PATTERN = (
    r"^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+(:\d{1,5})?$"
)
HTTPS_URL_PATTERN = r"^https://\S+$"
SETTING_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
#: Graph-kind and SOL-tool names inside a first-party bundle: snake_case, ≤ 32,
#: so ``<id>.<name>`` (≤ 64 + 1 + 32) stays under the provider's 128-char cap.
CAPABILITY_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"

SOURCE_KINDS = ("code", "eda", "cad", "canbus", "runtime")
SLOT_SIZES = ("compact", "standard", "wide", "full")
SETTING_TYPES = ("boolean", "number", "string", "select")
#: The CLOSED set of bridge scopes (ADR-035 §2). Adding one is a contract change.
PERMISSION_SCOPES = (
    "graph.read",
    "telemetry.read",
    "sources.read",
    "findings.write",
    "sol.ask",
    "storage.own",
    "focus.read",
    "focus.write",
)

#: The graph's Domain vocabulary (ADR-027) — a declared kind names one of these.
GRAPH_DOMAINS = ("code", "electrical", "mechanical", "simulation", "runtime")

SourceKind = Literal["code", "eda", "cad", "canbus", "runtime"]
GraphDomain = Literal["code", "electrical", "mechanical", "simulation", "runtime"]
SlotSize = Literal["compact", "standard", "wide", "full"]
SettingType = Literal["boolean", "number", "string", "select"]
PermissionScope = Literal[
    "graph.read",
    "telemetry.read",
    "sources.read",
    "findings.write",
    "sol.ask",
    "storage.own",
    "focus.read",
    "focus.write",
]


@dataclass(frozen=True)
class ManifestLimits:
    """Every cap in one place; the TS twin exports the same numbers."""

    name: int = 60
    publisher: int = 60
    summary: int = 160
    page_label: int = 24
    window_title: int = 60
    window_min_px: int = 320
    window_max_px: int = 4096
    requires_groups: int = 4
    scopes: int = 8
    network: int = 8
    setting_fields: int = 16
    setting_label: int = 40
    setting_options: int = 12
    setting_option_len: int = 40
    section_title: int = 40
    sections: int = 4
    screenshots: int = 6
    graph_kinds: int = 8
    tool_names: int = 16
    path_len: int = 200
    icon_bytes: int = 16 * 1024
    overview_bytes: int = 32 * 1024
    section_bytes: int = 16 * 1024
    screenshot_bytes: int = 1024 * 1024
    bundle_bytes: int = 25 * 1024 * 1024


LIMITS = ManifestLimits()

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def is_safe_extension_id(value: str) -> bool:
    return bool(re.match(EXTENSION_ID_PATTERN, value)) and value not in RESERVED_EXTENSION_IDS


def is_safe_bundle_path(value: str, extensions: tuple[str, ...]) -> bool:
    """A relative, traversal-free path inside the bundle with an allowed suffix.

    The same rule on both sides, because the desktop serves these paths from
    the installed bundle directory and a path that escapes it is a file read.
    """
    if not value or len(value) > LIMITS.path_len:
        return False
    if value.startswith("/") or "\\" in value:
        return False
    segments = value.split("/")
    if any(seg in ("", ".", "..") or not _SEGMENT_RE.match(seg) for seg in segments):
        return False
    lowered = value.lower()
    return any(lowered.endswith(ext) for ext in extensions)


def _path_field(*extensions: str):  # type: ignore[no-untyped-def]
    def validate(value: str) -> str:
        if not is_safe_bundle_path(value, extensions):
            raise ValueError(
                f"must be a relative path inside the bundle ending in {'/'.join(extensions)}"
            )
        return value

    return validate


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExtensionMeta(_Strict):
    id: Annotated[str, StringConstraints(pattern=EXTENSION_ID_PATTERN)]
    name: Annotated[str, StringConstraints(min_length=1, max_length=LIMITS.name)]
    version: Annotated[str, StringConstraints(pattern=SEMVER_PATTERN)]
    publisher: Annotated[str, StringConstraints(min_length=1, max_length=LIMITS.publisher)]
    summary: Annotated[str, StringConstraints(min_length=1, max_length=LIMITS.summary)]
    #: AND of ORs over source kinds: every group must be satisfied by one connected kind.
    requires: list[list[SourceKind]] = Field(
        default_factory=list, max_length=LIMITS.requires_groups
    )
    min_solus: Annotated[str, StringConstraints(pattern=SEMVER_PATTERN)] | None = None

    @field_validator("id")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value in RESERVED_EXTENSION_IDS:
            raise ValueError("reserved id")
        return value

    @field_validator("requires")
    @classmethod
    def _groups_non_empty(cls, groups: list[list[str]]) -> list[list[str]]:
        for group in groups:
            if not group or len(set(group)) != len(group):
                raise ValueError("each requires group must be a non-empty list of distinct kinds")
        return groups


class WidgetView(_Strict):
    entry: str
    preferred: SlotSize
    minimum: SlotSize | None = None

    _entry = field_validator("entry")(_path_field(".html"))


class PageView(_Strict):
    entry: str
    icon: str
    label: Annotated[str, StringConstraints(min_length=1, max_length=LIMITS.page_label)]

    _entry = field_validator("entry")(_path_field(".html"))
    _icon = field_validator("icon")(_path_field(".svg"))


class WindowView(_Strict):
    entry: str
    title: Annotated[str, StringConstraints(min_length=1, max_length=LIMITS.window_title)]
    width: int | None = Field(default=None, ge=LIMITS.window_min_px, le=LIMITS.window_max_px)
    height: int | None = Field(default=None, ge=LIMITS.window_min_px, le=LIMITS.window_max_px)

    _entry = field_validator("entry")(_path_field(".html"))


class Views(_Strict):
    widget: WidgetView | None = None
    page: PageView | None = None
    window: WindowView | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> Views:
        if self.widget is None and self.page is None and self.window is None:
            raise ValueError("views must declare at least one of widget, page, window")
        return self


class Permissions(_Strict):
    scopes: list[PermissionScope] = Field(default_factory=list, max_length=LIMITS.scopes)
    network: list[Annotated[str, StringConstraints(pattern=NETWORK_ORIGIN_PATTERN)]] = Field(
        default_factory=list, max_length=LIMITS.network
    )

    @field_validator("scopes", "network")
    @classmethod
    def _distinct(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("entries must be distinct")
        return values


class SettingField(_Strict):
    key: Annotated[str, StringConstraints(pattern=SETTING_KEY_PATTERN)]
    type: SettingType
    label: Annotated[str, StringConstraints(min_length=1, max_length=LIMITS.setting_label)]
    options: (
        list[Annotated[str, StringConstraints(min_length=1, max_length=LIMITS.setting_option_len)]]
        | None
    ) = Field(default=None, min_length=1, max_length=LIMITS.setting_options)
    default: bool | int | float | str | None = None
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _typed(self) -> SettingField:
        if self.type == "select":
            if not self.options:
                raise ValueError("select fields must list options")
            if self.default is not None and self.default not in self.options:
                raise ValueError("default must be one of options")
        elif self.options is not None:
            raise ValueError("only select fields take options")
        if self.type != "number" and (self.min is not None or self.max is not None):
            raise ValueError("only number fields take min/max")
        if self.default is not None:
            ok = {
                "boolean": isinstance(self.default, bool),
                "number": isinstance(self.default, (int, float))
                and not isinstance(self.default, bool),
                "string": isinstance(self.default, str),
                "select": isinstance(self.default, str),
            }[self.type]
            if not ok:
                raise ValueError(f"default must be a {self.type}")
        return self


class Settings(_Strict):
    fields: list[SettingField] = Field(default_factory=list, max_length=LIMITS.setting_fields)

    @field_validator("fields")
    @classmethod
    def _unique_keys(cls, fields: list[SettingField]) -> list[SettingField]:
        keys = [f.key for f in fields]
        if len(set(keys)) != len(keys):
            raise ValueError("setting keys must be unique")
        return fields


HttpsUrl = Annotated[str, StringConstraints(pattern=HTTPS_URL_PATTERN, max_length=2048)]


class StoreLinks(_Strict):
    documentation: HttpsUrl | None = None
    issues: HttpsUrl | None = None
    terms: HttpsUrl | None = None


class StoreSection(_Strict):
    title: Annotated[str, StringConstraints(min_length=1, max_length=LIMITS.section_title)]
    body: str

    _body = field_validator("body")(_path_field(".md"))


class Store(_Strict):
    overview: str
    privacy_policy: str | None = None
    links: StoreLinks = Field(default_factory=StoreLinks)
    screenshots: list[str] = Field(default_factory=list, max_length=LIMITS.screenshots)
    sections: list[StoreSection] = Field(default_factory=list, max_length=LIMITS.sections)

    _overview = field_validator("overview")(_path_field(".md"))

    @field_validator("privacy_policy")
    @classmethod
    def _privacy_path(cls, value: str | None) -> str | None:
        return None if value is None else _path_field(".md")(value)

    @field_validator("screenshots")
    @classmethod
    def _shots(cls, values: list[str]) -> list[str]:
        for v in values:
            _path_field(".png", ".webp")(v)
        return values


CapabilityName = Annotated[str, StringConstraints(pattern=CAPABILITY_NAME_PATTERN)]


class Backend(_Strict):
    """``[backend]`` — the in-repo capability package this bundle is backed by
    (SOLUSDEV-246). ``capability`` must equal ``extension.id``; the zip never
    carries server code, it only names the package Solus ships and reviewed."""

    capability: Annotated[str, StringConstraints(pattern=EXTENSION_ID_PATTERN)]
    routes: bool = False


class GraphKind(_Strict):
    """One declared node type; lands as ``ext:<id>:<name>`` (see :func:`graph_kind_name`)."""

    name: CapabilityName
    domain: GraphDomain


class Graph(_Strict):
    kinds: list[GraphKind] = Field(default_factory=list, max_length=LIMITS.graph_kinds)

    @field_validator("kinds")
    @classmethod
    def _distinct_names(cls, kinds: list[GraphKind]) -> list[GraphKind]:
        names = [k.name for k in kinds]
        if len(set(names)) != len(names):
            raise ValueError("kind names must be distinct")
        return kinds


class Tools(_Strict):
    """SOL tools the capability package registers, as ``<id>.<name>``."""

    names: list[CapabilityName] = Field(default_factory=list, max_length=LIMITS.tool_names)

    @field_validator("names")
    @classmethod
    def _distinct(cls, names: list[str]) -> list[str]:
        if len(set(names)) != len(names):
            raise ValueError("entries must be distinct")
        return names


class ExtensionManifest(_Strict):
    """The whole of ``extension.toml`` (decoded), with the optional blocks defaulted."""

    schema_version: Literal[1, 2]
    extension: ExtensionMeta
    views: Views
    permissions: Permissions = Field(default_factory=Permissions)
    settings: Settings = Field(default_factory=Settings)
    store: Store
    # SOLUSDEV-246 — schema_version 2 only; unknown fields at 1.
    backend: Backend | None = None
    graph: Graph = Field(default_factory=Graph)
    tools: Tools = Field(default_factory=Tools)

    @model_validator(mode="before")
    @classmethod
    def _first_party_tables_need_v2(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("schema_version") == 1:
            for key in FIRST_PARTY_TABLES:
                if key in data:
                    raise ValueError(f"{key}: unknown field (requires schema_version 2)")
        return data

    @model_validator(mode="after")
    def _privacy_when_permissioned(self) -> ExtensionManifest:
        if (self.permissions.scopes or self.permissions.network) and not self.store.privacy_policy:
            raise ValueError(
                "store.privacy_policy is required when permissions.scopes or "
                "permissions.network is non-empty"
            )
        return self

    @model_validator(mode="after")
    def _backend_names_this_bundle(self) -> ExtensionManifest:
        if self.backend is not None and self.backend.capability != self.extension.id:
            raise ValueError("backend.capability: must equal extension.id")
        return self


def declares_first_party(manifest: ExtensionManifest) -> bool:
    """True when the manifest uses any first-party table — the publish validator
    then demands a staff publisher and a matching in-repo capability."""
    return manifest.backend is not None or bool(manifest.graph.kinds) or bool(manifest.tools.names)


def graph_kind_name(extension_id: str, name: str) -> str:
    """The ``graph_entity.kind`` a declared kind lands as."""
    return f"ext:{extension_id}:{name}"


def composed_tool_name(extension_id: str, name: str) -> str:
    """The ``ToolDescriptor.name`` a declared tool registers as (dotted, like
    ``solus.*`` and ``{server}.{tool}``; the prompt layer translates it)."""
    return f"{extension_id}.{name}"


def parse_extension_manifest(data: Any) -> ExtensionManifest:
    """Strict parse of a decoded manifest; raises ``ValidationError`` naming the field."""
    return ExtensionManifest.model_validate(data)


def manifest_problems(data: Any) -> list[str]:
    """``"<dotted.path>: <message>"`` per problem, empty when valid. What the publish
    validator stores on the version row and the developer mode shows inline."""
    try:
        ExtensionManifest.model_validate(data)
    except ValidationError as exc:
        problems: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"])
            msg = str(err["msg"]).removeprefix("Value error, ")
            problems.append(f"{loc}: {msg}" if loc else msg)
        return problems
    return []
