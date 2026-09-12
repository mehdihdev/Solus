"""Shared opaque source identity requires explicit private-file relinking."""

import uuid

from solus_api.hardware.migration import split_legacy_document


def test_one_project_file_reference_is_shared_across_parts_and_owners() -> None:
    project = uuid.uuid4()
    refs = []
    for _ in range(2):
        owner, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        documents = split_legacy_document(
            {
                "robot_entity_id": str(owner),
                "parts": {
                    str(part): {"calibration": {"source": "/private/calibration.json"}}
                    for part in (first, second)
                },
                "provenance": {"parts": {"by": "repo", "source": "/private/calibration.json"}},
            },
            source_namespace=project,
        )
        for part in (first, second):
            component = documents[part].component
            assert component is not None and component.calibration is not None
            refs.append(component.calibration.source)
            assert "/private/" not in documents[part].model_dump_json()
    assert len(set(refs)) == 1
    assert refs[0] == f"source:{uuid.uuid5(project, '/private/calibration.json')}"


def test_source_references_do_not_cross_project_scope() -> None:
    owner, part = uuid.uuid4(), uuid.uuid4()
    legacy = {
        "robot_entity_id": str(owner),
        "parts": {str(part): {"calibration": {"source": "/private/calibration.json"}}},
        "provenance": {"parts": {"by": "repo"}},
    }
    refs = []
    for project in (uuid.uuid4(), uuid.uuid4()):
        config = split_legacy_document(legacy, source_namespace=project)[part]
        assert config.component is not None and config.component.calibration is not None
        refs.append(config.component.calibration.source)
    assert refs[0] != refs[1]
