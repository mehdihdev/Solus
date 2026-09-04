"""POST /api/v1/extensions/publish + DELETE …/versions/{version}
(SOLUSDEV-235 EXT-07; docs/api/extensions.md §5.1, §5.3, §12, §13, §14).

Upload hygiene (411/413/422), the required `Idempotency-Key` (replay vs
conflict), the slug claim (`slug_taken`, `version_exists`), the bundle_invalid
path, the verified-email gate, the per-user publish budget, the rows and bytes a
publish creates, and the §5.3 `latest_approved_version_id` recompute.
"""

import hashlib
import io
import uuid
from collections.abc import AsyncIterator

import pytest
from conftest import me
from fastapi import FastAPI
from fixtures.extensions import (
    MINIMAL_MANIFEST_TOML,
    build_zip,
    minimal_files,
    with_manifest,
    without,
)
from httpx import AsyncClient, Response
from solus_api.models import (
    DataEvent,
    Extension,
    ExtensionPublisher,
    ExtensionReviewStatus,
    ExtensionVersion,
    User,
)
from solus_api.routers.extensions import bundle, publish
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

PUBLISH = "/api/v1/extensions/publish"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    # EXT-07 owns only its sub-routers; the aggregator include
    # (routers/extensions/__init__.py) is wired by the orchestrator at
    # integration, so this suite mounts them on the app directly.
    app.include_router(publish.router)
    app.include_router(bundle.router)
    return app


# ------------------------------------------------------------------ helpers
def _bundle(version: str = "1.0.0", slug: str = "bom") -> bytes:
    toml = MINIMAL_MANIFEST_TOML.replace('version = "1.0.0"', f'version = "{version}"').replace(
        'id = "bom"', f'id = "{slug}"'
    )
    return build_zip(with_manifest(minimal_files(), toml))


async def _publish(
    client: AsyncClient,
    headers: dict[str, str],
    data: bytes,
    *,
    key: str | None = "key-1",
    extra_form: dict[str, str] | None = None,
) -> Response:
    sent = dict(headers)
    if key is not None:
        sent["Idempotency-Key"] = key
    return await client.post(
        PUBLISH,
        files={"bundle": ("bundle.zip", io.BytesIO(data), "application/zip")},
        data=extra_form or {},
        headers=sent,
    )


async def _consenting(client: AsyncClient, db: AsyncSession, headers: dict[str, str]) -> str:
    user = await me(client, headers)
    await db.execute(
        update(User).where(User.id == uuid.UUID(user["id"])).values(data_collection_consent=True)
    )
    await db.commit()
    user_id: str = user["id"]
    return user_id


async def _approve(db: AsyncSession, slug: str, version: str, *, latest: bool) -> None:
    ext = await db.scalar(select(Extension).where(Extension.slug == slug))
    assert ext is not None
    row = await db.scalar(
        select(ExtensionVersion).where(
            ExtensionVersion.extension_id == ext.id, ExtensionVersion.version == version
        )
    )
    assert row is not None
    row.review_status = ExtensionReviewStatus.APPROVED
    if latest:
        ext.latest_approved_version_id = row.id
    await db.commit()


async def _latest(db: AsyncSession, slug: str) -> str | None:
    db.expire_all()
    ext = await db.scalar(select(Extension).where(Extension.slug == slug))
    assert ext is not None
    if ext.latest_approved_version_id is None:
        return None
    row = await db.get(ExtensionVersion, ext.latest_approved_version_id)
    assert row is not None
    return row.version


# ------------------------------------------------------------------- publish
async def test_publish_creates_rows_bytes_and_event(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    user_id = await _consenting(client, db, alice_headers)
    data = _bundle()

    resp = await _publish(client, alice_headers, data)

    assert resp.status_code == 202, resp.text
    body = resp.json()["data"]
    assert body["review"] == {"status": "pending", "problems": []}
    version = body["version"]
    assert version["slug"] == "bom"
    assert version["version"] == "1.0.0"
    assert version["review_status"] == "pending"
    assert version["content_hash"] == hashlib.sha256(data).hexdigest()
    assert version["bundle_size_bytes"] == len(data)
    assert version["bundle_url"] == "/api/v1/extensions/bom/versions/1.0.0/bundle"
    assert version["review_url"] == "/api/v1/extensions/bom/versions/1.0.0/review"
    assert "job_id" not in body  # no project-scoped Job row for the global registry

    publisher = await db.scalar(select(ExtensionPublisher))
    assert publisher is not None
    assert publisher.user_id == uuid.UUID(user_id)
    assert publisher.display_name == "Solus"  # seeded from extension.publisher
    extension = await db.scalar(select(Extension))
    assert extension is not None
    assert (extension.slug, extension.name, extension.publisher_id) == (
        "bom",
        "BOM",
        publisher.id,
    )
    assert extension.latest_approved_version_id is None
    row = await db.scalar(select(ExtensionVersion))
    assert row is not None
    assert row.review_status is ExtensionReviewStatus.PENDING
    assert row.published_at is None
    assert row.manifest["extension"]["id"] == "bom"
    assert row.manifest["views"] == {"widget": {"entry": "widget.html", "preferred": "wide"}}
    assert row.bundle_storage.value == "local"
    stored = {p.name for p in app.state.artifact_store.root.iterdir()}
    assert stored == {str(row.id)}  # key = the row id, never a client filename

    event = await db.scalar(select(DataEvent).where(DataEvent.event_type == "extension.publish"))
    assert event is not None
    assert event.payload == {
        "slug": "bom",
        "version": "1.0.0",
        "bundle_size_bytes": len(data),
        "content_hash": version["content_hash"],
    }


async def test_publish_response_never_carries_a_storage_locator(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    resp = await _publish(client, alice_headers, _bundle())
    assert resp.status_code == 202
    assert str(app.state.artifact_store.root) not in resp.text
    assert "local" not in resp.json()["data"]["version"].values()


async def test_publish_unauthenticated_is_401(client: AsyncClient) -> None:
    resp = await _publish(client, {}, _bundle())
    assert resp.status_code == 401


async def test_publish_requires_verified_email(
    client: AsyncClient, unverified_headers: dict[str, str]
) -> None:
    resp = await _publish(client, unverified_headers, _bundle())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"


async def test_missing_idempotency_key_is_400_and_stores_nothing(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    resp = await _publish(client, alice_headers, _bundle(), key=None)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "idempotency_key_required"
    assert await db.scalar(select(ExtensionVersion)) is None


async def test_replay_same_key_same_bytes_returns_the_original_202(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    data = _bundle()
    first = await _publish(client, alice_headers, data, key="k")
    second = await _publish(client, alice_headers, data, key="k")
    assert (first.status_code, second.status_code) == (202, 202)
    assert first.json() == second.json()
    rows = (await db.scalars(select(ExtensionVersion))).all()
    assert len(rows) == 1


async def test_same_key_different_bytes_is_409_idempotency_conflict(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    assert (await _publish(client, alice_headers, _bundle("1.0.0"), key="k")).status_code == 202
    resp = await _publish(client, alice_headers, _bundle("1.0.1"), key="k")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "idempotency_conflict"


async def test_idempotency_keys_are_scoped_per_user(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    """Bob reusing Alice's key with different bytes is a fresh publish for him,
    not a conflict with (or a replay of) hers."""
    assert (await _publish(client, alice_headers, _bundle(), key="shared")).status_code == 202
    resp = await _publish(client, bob_headers, _bundle(slug="bob-tool"), key="shared")
    assert resp.status_code == 202


async def test_publish_without_content_length_is_411(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    boundary = "solusboundary"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="bundle"; filename="b.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode()
        + _bundle()
        + f"\r\n--{boundary}--\r\n".encode()
    )

    async def _chunks() -> AsyncIterator[bytes]:
        yield body

    headers = {
        **alice_headers,
        "Idempotency-Key": "k",
        "content-type": f"multipart/form-data; boundary={boundary}",
    }
    request = client.build_request("POST", PUBLISH, content=_chunks(), headers=headers)
    assert "content-length" not in request.headers
    resp = await client.send(request)
    assert resp.status_code == 411
    assert resp.json()["error"]["code"] == "length_required"


async def test_declared_oversized_body_is_413_before_reading(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    headers = {
        **alice_headers,
        "Idempotency-Key": "k",
        "content-type": "multipart/form-data; boundary=x",
        "content-length": str(25 * 1024 * 1024 + 8_192 + 1),
    }
    request = client.build_request("POST", PUBLISH, content=b"--x--\r\n", headers=headers)
    resp = await client.send(request)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


async def test_lying_content_length_cannot_overshoot_the_streamed_cap(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI
) -> None:
    boundary = "solusboundary"
    oversized = b"\0" * (25 * 1024 * 1024 + 1)
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="bundle"; filename="b.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode()
        + oversized
        + f"\r\n--{boundary}--\r\n".encode()
    )
    headers = {
        **alice_headers,
        "Idempotency-Key": "k",
        "content-type": f"multipart/form-data; boundary={boundary}",
        "content-length": "5",
    }
    resp = await client.send(client.build_request("POST", PUBLISH, content=body, headers=headers))
    assert resp.status_code == 413
    assert list(app.state.artifact_store.root.iterdir()) == []


async def test_unknown_form_field_is_422(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await _publish(client, alice_headers, _bundle(), extra_form={"notes": "hi"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_missing_bundle_part_is_422(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.post(
        PUBLISH, data={"bundle": "not-a-file"}, headers={**alice_headers, "Idempotency-Key": "k"}
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (b"not a zip at all", "not a zip archive"),
        (build_zip(without(minimal_files(), "extension.toml")), "extension.toml: missing"),
        (build_zip(without(minimal_files(), "OVERVIEW.md")), "store.overview"),
    ],
)
async def test_invalid_bundle_is_422_bundle_invalid_with_problems(
    client: AsyncClient,
    alice_headers: dict[str, str],
    db: AsyncSession,
    app: FastAPI,
    data: bytes,
    fragment: str,
) -> None:
    resp = await _publish(client, alice_headers, data)
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == "bundle_invalid"
    assert any(fragment in problem for problem in error["details"]), error["details"]
    assert await db.scalar(select(ExtensionVersion)) is None
    assert await db.scalar(select(ExtensionPublisher)) is None
    assert list(app.state.artifact_store.root.iterdir()) == []


async def test_slug_owned_by_another_publisher_is_409_slug_taken(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    assert (await _publish(client, alice_headers, _bundle("1.0.0"))).status_code == 202
    resp = await _publish(client, bob_headers, _bundle("1.0.1"), key="bob-key")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "slug_taken"


async def test_slug_claim_is_case_insensitive(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    """`extensions.slug` is unique on lower(slug); the claim lookup must match the
    same way, so a row seeded as `BOM` blocks Alice's `bom`."""
    other = ExtensionPublisher(user_id=None, display_name="Someone")
    db.add(other)
    await db.flush()
    db.add(Extension(slug="BOM", publisher_id=other.id, name="Other", summary="Theirs."))
    await db.commit()
    resp = await _publish(client, alice_headers, _bundle())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "slug_taken"


async def test_same_publisher_adds_a_second_version_to_the_same_extension(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    assert (await _publish(client, alice_headers, _bundle("1.0.0"), key="a")).status_code == 202
    assert (await _publish(client, alice_headers, _bundle("1.1.0"), key="b")).status_code == 202
    assert len((await db.scalars(select(Extension))).all()) == 1
    assert len((await db.scalars(select(ExtensionPublisher))).all()) == 1
    assert len((await db.scalars(select(ExtensionVersion))).all()) == 2


async def test_existing_version_is_409_version_exists_even_after_unpublish(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    assert (await _publish(client, alice_headers, _bundle("1.0.0"), key="a")).status_code == 202
    again = await _publish(client, alice_headers, _bundle("1.0.0"), key="b")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "version_exists"

    gone = await client.delete("/api/v1/extensions/bom/versions/1.0.0", headers=alice_headers)
    assert gone.status_code == 204
    burned = await _publish(client, alice_headers, _bundle("1.0.0"), key="c")
    assert burned.status_code == 409
    assert burned.json()["error"]["code"] == "version_exists"


async def test_publish_rate_limit_is_429_with_retry_after_and_event(
    client: AsyncClient, alice_headers: dict[str, str], app: FastAPI, db: AsyncSession
) -> None:
    await _consenting(client, db, alice_headers)
    app.state.settings.extension_publishes_per_hour_per_user = 1
    assert (await _publish(client, alice_headers, _bundle("1.0.0"), key="a")).status_code == 202
    resp = await _publish(client, alice_headers, _bundle("1.0.1"), key="b")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"
    assert resp.headers["Retry-After"] == "3600"
    event = await db.scalar(
        select(DataEvent).where(DataEvent.event_type == "extension.rate_limited")
    )
    assert event is not None


# ----------------------------------------------------------------- unpublish
async def test_unpublish_recomputes_latest_approved(
    client: AsyncClient, alice_headers: dict[str, str], db: AsyncSession
) -> None:
    await _consenting(client, db, alice_headers)
    for i, v in enumerate(("1.0.0", "1.1.0", "2.0.0-rc.1")):
        assert (await _publish(client, alice_headers, _bundle(v), key=str(i))).status_code == 202
    await _approve(db, "bom", "1.0.0", latest=False)
    await _approve(db, "bom", "1.1.0", latest=True)
    await _approve(
        db, "bom", "2.0.0-rc.1", latest=False
    )  # pre-release < 1.1.0? no: 2.0.0-rc.1 > 1.1.0

    gone = await client.delete("/api/v1/extensions/bom/versions/1.1.0", headers=alice_headers)
    assert gone.status_code == 204
    assert await _latest(db, "bom") == "2.0.0-rc.1"

    assert (
        await client.delete("/api/v1/extensions/bom/versions/2.0.0-rc.1", headers=alice_headers)
    ).status_code == 204
    assert await _latest(db, "bom") == "1.0.0"

    assert (
        await client.delete("/api/v1/extensions/bom/versions/1.0.0", headers=alice_headers)
    ).status_code == 204
    assert await _latest(db, "bom") is None

    db.expire_all()
    rows = (await db.scalars(select(ExtensionVersion))).all()
    assert len(rows) == 3 and all(r.deleted_at is not None for r in rows)
    events = (
        await db.scalars(select(DataEvent).where(DataEvent.event_type == "extension.unpublish"))
    ).all()
    assert {e.payload["version"] for e in events} == {"1.0.0", "1.1.0", "2.0.0-rc.1"}


async def test_unpublish_by_non_publisher_or_unknown_is_404(
    client: AsyncClient, alice_headers: dict[str, str], bob_headers: dict[str, str]
) -> None:
    assert (await _publish(client, alice_headers, _bundle())).status_code == 202
    await me(client, bob_headers)
    foreign = await client.delete("/api/v1/extensions/bom/versions/1.0.0", headers=bob_headers)
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "not_found"
    unknown = await client.delete("/api/v1/extensions/nope/versions/1.0.0", headers=alice_headers)
    assert unknown.status_code == 404
    twice = await client.delete("/api/v1/extensions/bom/versions/1.0.0", headers=alice_headers)
    assert twice.status_code == 204
    again = await client.delete("/api/v1/extensions/bom/versions/1.0.0", headers=alice_headers)
    assert again.status_code == 404


async def test_unpublish_requires_verified_email(
    client: AsyncClient, unverified_headers: dict[str, str]
) -> None:
    resp = await client.delete("/api/v1/extensions/bom/versions/1.0.0", headers=unverified_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"


@pytest.mark.parametrize(
    "path",
    [
        "/-bom/versions/1.0.0",
        "/constructor/versions/1.0.0",
        "/bom/versions/latest",
        "/bom/versions/1",
    ],
)
async def test_bad_slug_or_version_syntax_is_422_before_lookup(
    client: AsyncClient, alice_headers: dict[str, str], path: str
) -> None:
    resp = await client.delete(f"/api/v1/extensions{path}", headers=alice_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
