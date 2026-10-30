"""SOLUSDEV-320: typed `.solus` entry payloads."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from solus_api.core.errors import APIError
from solus_api.services.solus_payloads import PAYLOAD_MODELS, ErrorMeta, validate_entry_payload

_META = {
    "entity_id": str(uuid.uuid4()),
    "machine_id": None,
    "dedupe_key": "a" * 40,
    "count": 2,
    "status": "resolved",
    "fix_ref": None,
    "first_seen": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
    "last_seen": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
}


def test_error_meta_round_trips_and_rejects_bad_values() -> None:
    meta = ErrorMeta.model_validate(_META)
    assert meta.first_seen == datetime(2026, 1, 1, tzinfo=UTC) and meta.count == 2
    assert ErrorMeta.model_validate(meta.model_dump(mode="json")) == meta
    for bad in ({"count": 0}, {"status": "nope"}, {"dedupe_key": "xyz"}, {"extra": 1}):
        with pytest.raises(ValueError):
            ErrorMeta.model_validate({**_META, **bad})


def test_validate_entry_payload_dispatches_by_section() -> None:
    assert PAYLOAD_MODELS[("errors", None)] is ErrorMeta
    assert isinstance(validate_entry_payload("errors", None, "text", _META), ErrorMeta)
    assert isinstance(validate_entry_payload("errors", "any", "sol", _META), ErrorMeta)
    with pytest.raises(APIError) as err:
        validate_entry_payload("errors", None, "text", {**_META, "count": 0})
    assert err.value.status_code == 422
    with pytest.raises(APIError) as err:
        validate_entry_payload("docs", None, "text", {})
    assert err.value.status_code == 422
