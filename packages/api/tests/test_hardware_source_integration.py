"""Private source authority cannot be supplied as a path in an API request."""

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from conftest import me
from fastapi import FastAPI
from httpx import AsyncClient
from solus_api.core.errors import APIError
from solus_api.hardware.config import HardwareConfig
from solus_api.hardware.detect import validated_repo_root


def test_existing_remote_directory_is_not_file_read_permission(tmp_path: Path) -> None:
    with pytest.raises(APIError) as failure:
        validated_repo_root(str(tmp_path))
    assert failure.value.status_code == 422
    assert str(tmp_path) not in str(failure.value)


def test_no_remote_directory_preserves_device_only_proposal() -> None:
    assert validated_repo_root(None) is None


@pytest.mark.parametrize("fault", [None, "account", "changed", "runner"])
def test_local_session_verifies_scoped_calibration_without_mutating_shared_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    from solus_api.hardware.local_runtime import prepare_local_hardware

    project, account, entry, subject, part, reference = (uuid.uuid4() for _ in range(6))
    source = tmp_path / "calibration.json"
    source.write_text('{"fixture": true}')
    directory = tmp_path / ".solus" / "projects" / str(project)
    directory.mkdir(parents=True)
    (directory / "hardware.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "accounts": {
                    str(account): {
                        "sources": {
                            str(reference): {
                                "path": str(source),
                                "contentSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                            }
                        },
                        "bindings": {str(entry): {"lastSeenPath": "/dev/private-hint"}},
                    }
                },
            }
        )
    )
    config = HardwareConfig.model_validate(
        {
            "robot_entity_id": str(subject),
            "identity": {"kind": "usb_serial", "binding": "fixture-stable-serial"},
            "parts": {str(part): {"calibration": {"source": f"source:{reference}"}}},
            "provenance": {"identity": {"by": "user"}, "parts": {"by": "repo"}},
        }
    )
    before = config.model_dump_json()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if fault == "changed":
        source.write_text('{"fixture": false}')
    if fault is not None:
        with pytest.raises(APIError) as failure:
            prepare_local_hardware(
                None if fault == "runner" else object(),
                config,
                project,
                uuid.uuid4() if fault == "account" else account,
                entry,
            )
        assert (
            failure.value.code
            == {
                "account": "relink_required",
                "changed": "source_changed",
                "runner": "source_unavailable",
            }[fault]
        )
        assert str(tmp_path) not in failure.value.message
    else:
        document = prepare_local_hardware(object(), config, project, account, entry)
        assert document["identity"]["last_seen_path"] == "/dev/private-hint"
        assert document["parts"] == config.model_dump(mode="json")["parts"]
    assert config.model_dump_json() == before


@pytest.mark.parametrize(
    ("changed", "opener_error"),
    [(False, None), (True, None), (False, ValueError), (False, RuntimeError)],
)
async def test_session_checks_owner_source_and_keeps_private_hint_out_of_response(
    client: AsyncClient,
    app: FastAPI,
    alice_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    changed: bool,
    opener_error: type[Exception] | None,
) -> None:
    from test_bench_robot_provider import _robot_project, _RobotLocal

    project, robot = await _robot_project(client, alice_headers)
    user = await me(client, alice_headers)
    local = _RobotLocal()
    app.state.bench_local = local
    reference = uuid.uuid4()
    config = {
        "schema_version": 2,
        "entity_id": robot,
        "identity": {"kind": "usb_serial", "binding": "fixture-serial"},
        "protocol": {"driver_id": "fixture-driver", "params": {}},
        "component": {"calibration": {"source": f"source:{reference}"}},
        "provenance": {key: {"by": "user"} for key in ("identity", "protocol", "component")},
    }
    saved = await client.put(
        f"/api/v1/projects/{project}/hardware/entities/{robot}/config",
        headers={**alice_headers, "If-Match": "0"},
        json={"config": config},
    )
    assert saved.status_code == 200, saved.text
    entry = saved.json()["data"]["entry_id"]
    source = tmp_path / "source.json"
    source.write_text('{"fixture": true}')
    directory = tmp_path / ".solus" / "projects" / project
    directory.mkdir(parents=True)
    (directory / "hardware.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "accounts": {
                    user["id"]: {
                        "sources": {
                            str(reference): {
                                "path": str(source),
                                "contentSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                            }
                        },
                        "bindings": {entry: {"lastSeenPath": "/dev/private-hint"}},
                    }
                },
            }
        )
    )
    if changed:
        source.write_text('{"fixture": false}')
    if opener_error is not None:
        local.robot_error = opener_error("Driver input includes /dev/private-hint")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    response = await client.post(
        f"/api/v1/projects/{project}/bench/sessions",
        headers=alice_headers,
        json={"mode": "real", "config": {"provider": "hardware", "entity_id": robot}},
    )
    if changed:
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "source_changed"
        assert local.opened == []
    elif opener_error is not None:
        assert response.status_code == (422 if opener_error is ValueError else 503)
    else:
        assert response.status_code == 201, response.text
        assert local.opened[0]["config"]["identity"]["last_seen_path"] == "/dev/private-hint"
    assert "/dev/private-hint" not in response.text
    assert str(tmp_path) not in response.text
    assert "/dev/private-hint" not in caplog.text


def test_private_hint_never_selects_a_can_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.hardware.local_runtime import prepare_local_hardware
    from solus_api.hardware.local_sources import LocalHardwareSources

    project, account, entry, subject = (uuid.uuid4() for _ in range(4))
    monkeypatch.setattr(LocalHardwareSources, "binding_hint", lambda *args: "private-can-channel")
    config = HardwareConfig.model_validate(
        {
            "robot_entity_id": str(subject),
            "identity": {"kind": "usb_can", "binding": "stable-can-binding"},
            "provenance": {"identity": {"by": "user"}},
        }
    )
    document = prepare_local_hardware(object(), config, project, account, entry)
    assert document["identity"]["last_seen_path"] is None
