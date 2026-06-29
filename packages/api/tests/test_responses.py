"""Success envelope helper per §1.4."""

from solus_api.core.responses import envelope


def test_envelope_data_only() -> None:
    assert envelope({"a": 1}) == {"data": {"a": 1}}


def test_envelope_with_meta_and_links() -> None:
    body = envelope([1], meta={"has_next": False}, links={"self": "/api/v1/teams"})
    assert body == {
        "data": [1],
        "meta": {"has_next": False},
        "links": {"self": "/api/v1/teams"},
    }
