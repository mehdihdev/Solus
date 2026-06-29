"""Cursor pagination helpers (§1.4)."""

import uuid
from datetime import UTC, datetime

import pytest
from solus_api.core.errors import APIError
from solus_api.core.pagination import decode_cursor, encode_cursor


def test_cursor_roundtrip() -> None:
    created = datetime(2026, 6, 12, 10, 30, tzinfo=UTC)
    item_id = uuid.uuid4()
    cursor = encode_cursor(created, item_id)
    decoded_at, decoded_id = decode_cursor(cursor)
    assert decoded_at == created
    assert decoded_id == item_id


def test_cursor_is_opaque_urlsafe() -> None:
    cursor = encode_cursor(datetime.now(UTC), uuid.uuid4())
    assert "+" not in cursor and "/" not in cursor


def test_invalid_cursor_raises_400() -> None:
    with pytest.raises(APIError) as exc:
        decode_cursor("definitely-not-a-cursor")
    assert exc.value.status_code == 400
    assert exc.value.code == "invalid_cursor"
