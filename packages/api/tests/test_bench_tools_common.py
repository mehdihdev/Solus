"""Shared bench tool helpers (SOLUSDEV-319 F2a): card cells, ids, rate-limit errors."""

from __future__ import annotations

import uuid

import pytest
from solus_api.agent.tools.bench_tools_common import as_uuid, cell, number, rate_limited, row
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.bridge.service import ConnectRateLimiter


def test_cell_is_one_printable_capped_line() -> None:
    assert cell("a\nb\x00  c") == "a b c"
    capped = cell("x" * 300)
    assert len(capped) == 200 and capped.endswith("…")


def test_as_uuid_rejects_non_uuids() -> None:
    value = uuid.uuid4()
    assert as_uuid(str(value)) == value
    with pytest.raises(ToolException) as caught:
        as_uuid("nope")
    assert caught.value.code is ToolErrorCode.INVALID_ARGS


def test_row_and_number() -> None:
    assert row("A", "b") == {"label": "A", "before": None, "after": "b"}
    assert number(None, "deg") == "unknown" and number(float("nan"), "deg") == "unknown"
    assert number(12.44, "deg") == "12.4 deg"


def test_rate_limited_raises_a_retryable_error_once_the_limiter_refuses() -> None:
    limiter = ConnectRateLimiter(1)
    rate_limited(limiter, "u", "slow down")
    with pytest.raises(ToolException) as caught:
        rate_limited(limiter, "u", "slow down")
    assert caught.value.code is ToolErrorCode.UNAVAILABLE and caught.value.retryable
    assert caught.value.message == "rate_limited: slow down"
