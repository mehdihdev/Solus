"""Immutable repository reads: bounds and path validation precede network IO."""

import httpx
import pytest
from solus_api.connectors.code_content import CodeContentError, CodeContentReader, safe_code_path
from solus_api.connectors.contracts import Credentials
from solus_api.connectors.github import GitHubConnector
from solus_api.connectors.gitlab import GitLabConnector


@pytest.mark.parametrize(
    "path",
    [
        "../a.py",
        "/a.py",
        "a/../b.py",
        "a\\b.py",
        ".env",
        "a/.env.local",
        ".git/config",
        ".ssh/config",
        "keys/key.pem",
        "a//b.py",
        "a\x00b",
    ],
)
def test_unsafe_paths_refused(path: str) -> None:
    with pytest.raises(CodeContentError):
        safe_code_path(path)


@pytest.mark.parametrize("provider", ["github", "gitlab"])
async def test_reads_exact_commit_and_encoded_path(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = (
        GitHubConnector()
        if provider == "github"
        else GitLabConnector(base_url="https://git.example")
    )
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["ref"] == "a" * 40
        return httpx.Response(200, content=b"first\nsecond\n")

    monkeypatch.setattr(
        connector, "_http", lambda creds: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    text = await CodeContentReader(connector).read(
        Credentials(token="test-token"), repo="org/repo", path="src/a b.py", commit="a" * 40
    )
    assert text == "first\nsecond\n"
    assert len(requests) == 1
    assert requests[0].url.host == ("api.github.com" if provider == "github" else "git.example")


@pytest.mark.parametrize(
    "status, body",
    [
        (200, b"binary\x00"),
        (200, b"\xff"),
        (200, b"x" * 262145),
        (302, b""),
        (401, b"private provider detail"),
        (429, b"private provider detail"),
    ],
    ids=["binary", "nonutf8", "oversized", "redirect", "unauthorized", "rate_limit"],
)
async def test_invalid_provider_content_is_safe_error(
    status: int, body: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = GitHubConnector()
    monkeypatch.setattr(
        connector,
        "_http",
        lambda creds: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, content=body))
        ),
    )
    with pytest.raises(CodeContentError) as error:
        await CodeContentReader(connector).read(
            Credentials(token="test-token"), repo="org/repo", path="main.py", commit="a" * 40
        )
    assert "private provider detail" not in str(error.value)


async def test_branch_name_is_not_an_immutable_revision() -> None:
    with pytest.raises(CodeContentError):
        await CodeContentReader(GitHubConnector()).read(
            Credentials(token="test-token"), repo="org/repo", path="main.py", commit="main"
        )


async def test_unannounced_stream_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections.abc import AsyncIterator

    class LargeStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"a" * 200_000
            yield b"b" * 100_000

    connector = GitHubConnector()
    monkeypatch.setattr(
        connector,
        "_http",
        lambda creds: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=LargeStream()))
        ),
    )
    with pytest.raises(CodeContentError, match="byte limit"):
        await CodeContentReader(connector).read(
            Credentials(token="test-token"), repo="org/repo", path="main.py", commit="a" * 40
        )


@pytest.mark.parametrize("repo", ["../repo", "org/../repo", "https://evil/repo", "org/repo/third"])
async def test_invalid_repository_never_opens_client(
    repo: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import Mock

    connector = GitHubConnector()
    client = Mock()
    monkeypatch.setattr(connector, "_http", client)
    with pytest.raises(CodeContentError):
        await CodeContentReader(connector).read(
            Credentials(token="test-token"), repo=repo, path="main.py", commit="a" * 40
        )
    client.assert_not_called()


async def test_github_blob_does_not_dereference_symlink(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = GitHubConnector()

    def response(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/org/repo/git/blobs/" + "c" * 40
        assert "ref" not in request.url.params
        return httpx.Response(200, content=b".env")

    monkeypatch.setattr(
        connector, "_http", lambda creds: httpx.AsyncClient(transport=httpx.MockTransport(response))
    )
    text = await CodeContentReader(connector).read(
        Credentials(token="test-token"),
        repo="org/repo",
        path="alias.py",
        commit="a" * 40,
        blob_sha="c" * 40,
    )
    assert text == ".env"
