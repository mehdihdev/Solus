"""Artifact upload: path paranoia, allowlist gate, status mapping, ArtifactRef.

Hermetic — HTTP rides an injected fake `post`; no network, no real API. Token
values follow the suite convention ("tok-1"), placeholders only.
"""

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from solus_companion.artifacts import (
    REASON_BAD_REF,
    REASON_CONNECTION,
    REASON_FAILED,
    REASON_FILE_MISSING,
    REASON_FILE_TOO_LARGE,
    REASON_HOST_NOT_ALLOWLISTED,
    REASON_PATH_ESCAPES,
    REASON_PAYLOAD_TOO_LARGE,
    REASON_RATE_LIMITED,
    REASON_TIMEOUT,
    REASON_UNAUTHORIZED,
    REASON_WORKSPACE_UNKNOWN,
    ArtifactUploader,
    ArtifactUploadError,
    server_workspace,
)
from solus_companion.config import (
    CompanionConfig,
    ServerLaunch,
    TokenBox,
    api_endpoint_from_ws_url,
)

ARTIFACT_ID = "019f9a01-2c44-7d1e-9b0a-3f52c1e0aa10"


def _ok_envelope(size_bytes: int = 5) -> bytes:
    return json.dumps(
        {
            "data": {
                "artifact_id": ARTIFACT_ID,
                "uri": f"/api/v1/projects/p1/artifacts/{ARTIFACT_ID}/content",
                "media_type": "application/octet-stream",
                "storage": "local",
                "size_bytes": size_bytes,
                "summary": None,
            }
        }
    ).encode()


class FakePost:
    """Records every HTTP call; returns a programmed status/body or raises."""

    def __init__(
        self, status: int = 201, body: bytes | None = None, exc: Exception | None = None
    ) -> None:
        self.status = status
        self.body = body if body is not None else _ok_envelope()
        self.exc = exc
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> tuple[int, bytes]:
        self.calls.append({"url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return self.status, self.body


class CountingToken:
    def __init__(self, token: str = "tok-1") -> None:
        self.token = token
        self.reads = 0

    def __call__(self) -> str:
        self.reads += 1
        return self.token


def _uploader(
    workspace: Path,
    post: FakePost,
    *,
    origin: str = "https://localhost:8000",
    hosts: tuple[str, ...] = ("localhost",),
    token_source: CountingToken | None = None,
    max_bytes: int = 8 * 1024 * 1024,
) -> ArtifactUploader:
    return ArtifactUploader(
        origin=origin,
        project_id="p1",
        token_source=token_source if token_source is not None else CountingToken(),
        allowed_hosts=frozenset(hosts),
        workspaces={"kicad": workspace},
        post=post,
        max_bytes=max_bytes,
    )


def _workspace_with_artifact(tmp_path: Path, payload: bytes = b"BYTES") -> Path:
    workspace = tmp_path / "ws"
    (workspace / "out").mkdir(parents=True)
    (workspace / "out" / "netlist.kicadxml").write_bytes(payload)
    return workspace


async def _expect_refusal(
    uploader: ArtifactUploader, artifact_path: str, reason: str, post: FakePost
) -> None:
    with pytest.raises(ArtifactUploadError) as excinfo:
        await uploader.upload(
            server="kicad",
            artifact_path=artifact_path,
            source_tool="kicad.export_netlist",
            call_id="c1",
        )
    assert excinfo.value.reason == reason
    assert post.calls == []  # refused BEFORE any HTTP


# --- path validation: refuse escapes / missing / oversize with zero HTTP -----


async def test_dotdot_escape_is_refused_with_zero_http_calls(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_bytes(b"outside")
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost()
    await _expect_refusal(_uploader(workspace, post), "../secret.txt", REASON_PATH_ESCAPES, post)


async def test_symlink_escape_is_refused_with_zero_http_calls(tmp_path: Path) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    workspace = _workspace_with_artifact(tmp_path)
    (workspace / "link.bin").symlink_to(outside)  # resolves OUTSIDE the workspace
    post = FakePost()
    await _expect_refusal(_uploader(workspace, post), "link.bin", REASON_PATH_ESCAPES, post)


async def test_absolute_artifact_path_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "abs.bin"
    outside.write_bytes(b"outside")
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost()
    await _expect_refusal(_uploader(workspace, post), str(outside), REASON_PATH_ESCAPES, post)


async def test_missing_file_is_refused(tmp_path: Path) -> None:
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost()
    await _expect_refusal(_uploader(workspace, post), "out/nope.bin", REASON_FILE_MISSING, post)


async def test_oversize_file_is_refused_by_stat(tmp_path: Path) -> None:
    workspace = _workspace_with_artifact(tmp_path, payload=b"123456789")
    post = FakePost()
    uploader = _uploader(workspace, post, max_bytes=8)
    await _expect_refusal(uploader, "out/netlist.kicadxml", REASON_FILE_TOO_LARGE, post)


async def test_unknown_server_workspace_is_refused(tmp_path: Path) -> None:
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost()
    uploader = _uploader(workspace, post)
    with pytest.raises(ArtifactUploadError) as excinfo:
        await uploader.upload(
            server="ghost", artifact_path="x", source_tool="ghost.t", call_id="c1"
        )
    assert excinfo.value.reason == REASON_WORKSPACE_UNKNOWN
    assert post.calls == []


# --- allowlist gate: the token never rides to a non-allowlisted host ---------


async def test_non_allowlisted_host_refused_and_token_never_read(tmp_path: Path) -> None:
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost()
    token = CountingToken()
    uploader = _uploader(
        workspace, post, origin="https://evil.example.com", hosts=("localhost",), token_source=token
    )
    await _expect_refusal(uploader, "out/netlist.kicadxml", REASON_HOST_NOT_ALLOWLISTED, post)
    assert token.reads == 0  # the token is not even read, let alone attached


async def test_non_http_origin_is_refused(tmp_path: Path) -> None:
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost()
    uploader = _uploader(workspace, post, origin="file://localhost/etc", hosts=("localhost",))
    await _expect_refusal(uploader, "out/netlist.kicadxml", REASON_HOST_NOT_ALLOWLISTED, post)


async def test_empty_token_is_refused_without_http(tmp_path: Path) -> None:
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost()
    uploader = _uploader(workspace, post, token_source=CountingToken(token=""))
    await _expect_refusal(uploader, "out/netlist.kicadxml", REASON_UNAUTHORIZED, post)


# --- HTTP failure mapping: stable reasons, all retryable at the frame layer --


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (401, REASON_UNAUTHORIZED),
        (413, REASON_PAYLOAD_TOO_LARGE),
        (429, REASON_RATE_LIMITED),
        (500, REASON_FAILED),
        (403, REASON_FAILED),
    ],
)
async def test_http_status_maps_to_stable_reason(tmp_path: Path, status: int, reason: str) -> None:
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost(status=status, body=b"{}")
    uploader = _uploader(workspace, post)
    with pytest.raises(ArtifactUploadError) as excinfo:
        await uploader.upload(
            server="kicad",
            artifact_path="out/netlist.kicadxml",
            source_tool="kicad.export_netlist",
            call_id="c1",
        )
    assert excinfo.value.reason == reason
    assert len(post.calls) == 1


@pytest.mark.parametrize(
    ("exc", "reason"),
    [(TimeoutError("slow"), REASON_TIMEOUT), (OSError("no route"), REASON_CONNECTION)],
)
async def test_transport_errors_map_to_stable_reasons(
    tmp_path: Path, exc: Exception, reason: str
) -> None:
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost(exc=exc)
    uploader = _uploader(workspace, post)
    with pytest.raises(ArtifactUploadError) as excinfo:
        await uploader.upload(
            server="kicad",
            artifact_path="out/netlist.kicadxml",
            source_tool="kicad.export_netlist",
            call_id="c1",
        )
    assert excinfo.value.reason == reason


async def test_malformed_201_envelope_is_bad_ref(tmp_path: Path) -> None:
    workspace = _workspace_with_artifact(tmp_path)
    post = FakePost(status=201, body=b'{"data": {"nope": true}}')
    uploader = _uploader(workspace, post)
    with pytest.raises(ArtifactUploadError) as excinfo:
        await uploader.upload(
            server="kicad",
            artifact_path="out/netlist.kicadxml",
            source_tool="kicad.export_netlist",
            call_id="c1",
        )
    assert excinfo.value.reason == REASON_BAD_REF


# --- happy path: 201 → schema-valid ArtifactRef ------------------------------


async def test_201_returns_artifact_ref_and_sends_contract_multipart(tmp_path: Path) -> None:
    workspace = _workspace_with_artifact(tmp_path, payload=b"NETLISTBYTES")
    post = FakePost()
    uploader = _uploader(workspace, post)
    ref = await uploader.upload(
        server="kicad",
        artifact_path="out/netlist.kicadxml",
        source_tool="kicad.export_netlist",
        call_id="call-42",
    )
    assert ref["artifact_id"] == ARTIFACT_ID
    assert ref["storage"] == "local"
    assert ref["media_type"] == "application/octet-stream"
    assert ref["uri"].endswith("/content")
    assert ref["size_bytes"] == 5
    [request] = post.calls
    assert request["url"] == "https://localhost:8000/api/v1/projects/p1/artifacts"
    assert request["headers"]["Authorization"] == "Bearer tok-1"
    assert request["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    body = request["body"]
    assert b'name="media_type"' in body
    assert b"application/octet-stream" in body  # .kicadxml has no registered type
    assert b'name="source_tool"' in body
    assert b"kicad.export_netlist" in body
    assert b'name="call_id"' in body
    assert b"call-42" in body
    assert b'filename="netlist.kicadxml"' in body
    assert b"NETLISTBYTES" in body


# --- secret hygiene: the token never appears in logs -------------------------


async def test_token_never_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    workspace = _workspace_with_artifact(tmp_path)
    uploader = _uploader(workspace, FakePost())  # happy path
    await uploader.upload(
        server="kicad",
        artifact_path="out/netlist.kicadxml",
        source_tool="kicad.export_netlist",
        call_id="c1",
    )
    failing = _uploader(workspace, FakePost(status=401, body=b"{}"))
    with pytest.raises(ArtifactUploadError):
        await failing.upload(
            server="kicad",
            artifact_path="out/netlist.kicadxml",
            source_tool="kicad.export_netlist",
            call_id="c2",
        )
    assert "tok-1" not in caplog.text


# --- workspace + endpoint derivation -----------------------------------------


def test_server_workspace_prefers_declared_env() -> None:
    launch = ServerLaunch(
        name="kicad",
        command=Path("/root/kicad/bin/launch"),
        env={"SOLUS_MCP_WORKSPACE": "/projects/robot"},
    )
    assert server_workspace(launch) == Path("/projects/robot")


def test_server_workspace_falls_back_to_fork_dir() -> None:
    launch = ServerLaunch(name="kicad", command=Path("/root/kicad/bin/launch"))
    assert server_workspace(launch) == Path("/root/kicad")  # bin/launch's own fallback


def test_api_endpoint_from_wss_bridge_url() -> None:
    endpoint = api_endpoint_from_ws_url("wss://api.solus.dev/api/v1/projects/p42/bridge")
    assert endpoint is not None
    assert endpoint.origin == "https://api.solus.dev"
    assert endpoint.project_id == "p42"


def test_api_endpoint_maps_ws_to_http_for_local_dev() -> None:
    endpoint = api_endpoint_from_ws_url("ws://localhost:8000/api/v1/projects/p42/bridge")
    assert endpoint is not None
    assert endpoint.origin == "http://localhost:8000"
    assert endpoint.project_id == "p42"


def test_api_endpoint_rejects_non_bridge_paths() -> None:
    assert api_endpoint_from_ws_url("wss://api.solus.dev/other/path") is None
    assert api_endpoint_from_ws_url("wss://api.solus.dev/api/v1/projects//bridge") is None


def test_from_config_builds_uploader_with_server_workspaces(tmp_path: Path) -> None:
    config = CompanionConfig(
        url="wss://localhost/api/v1/projects/p7/bridge",
        token_source=TokenBox("tok-1"),
        integrations_root=tmp_path,
        instance_id="i1",
        servers=(ServerLaunch(name="kicad", command=tmp_path / "kicad" / "bin" / "launch"),),
        allowed_hosts=frozenset({"localhost"}),
    )
    uploader = ArtifactUploader.from_config(config)
    assert uploader is not None
    assert uploader.upload_url == "https://localhost/api/v1/projects/p7/artifacts"


def test_from_config_returns_none_for_non_bridge_url(tmp_path: Path) -> None:
    config = CompanionConfig(
        url="wss://localhost/not/a/bridge",
        token_source=TokenBox("tok-1"),
        integrations_root=tmp_path,
        instance_id="i1",
    )
    assert ArtifactUploader.from_config(config) is None
