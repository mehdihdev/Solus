"""Manual graph mutations use the same source-optional invalidation hint."""

import uuid
from types import SimpleNamespace

from solus_api.graph.live import graph_changed_frame


def test_manual_graph_change_has_null_provider_identifiers() -> None:
    frame = graph_changed_frame(
        project_id=uuid.uuid4(),
        source_id=None,
        sync_id=None,
        counts=SimpleNamespace(
            entities_created=8,
            entities_updated=0,
            entities_deleted=0,
            relations_created=7,
            relations_deleted=0,
        ),
        at="2026-09-06T12:00:00+00:00",
    )
    assert frame["source_id"] is None
    assert frame["sync_id"] is None
