"""Cursor pagination helpers (§1.4)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from solus_api.core.errors import APIError
from solus_api.core.pagination import (
    READ_WINDOW,
    PageMeta,
    decode_cursor,
    encode_cursor,
    page_meta,
    since_floor,
)


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


def test_the_page_meta_model_is_the_meta_block() -> None:
    """SOLUSDEV-321 P8 (M1): one response model for the §1.4 meta block, shared by every typed
    paged route."""
    rows, meta = page_meta([], 50)
    assert rows == [] and PageMeta(**meta).model_dump() == meta == {
        "limit": 50,
        "has_next": False,
        "next_cursor": None,
    }


def test_since_floor_reads_naive_as_utc_and_never_reaches_past_the_window() -> None:
    """SOLUSDEV-321 P8: a windowed read reaches back at most `READ_WINDOW`; no `since` is the whole
    window, a naive one is UTC, and an older one reads from the window's start."""
    window_start = datetime.now(UTC) - READ_WINDOW
    assert abs(since_floor(None) - window_start) < timedelta(seconds=5)
    recent = datetime.now(UTC) - timedelta(days=1)
    assert since_floor(recent.replace(tzinfo=None)) == recent
    assert abs(since_floor(window_start - timedelta(days=300)) - window_start) < timedelta(
        seconds=5
    )
