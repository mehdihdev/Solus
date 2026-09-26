"""The production registry exposes presence only with an authenticated local service."""

from unittest.mock import MagicMock
from uuid import uuid4

from solus_api.agent.runtime import build_sol_registry


def test_presence_is_registered_in_real_registry():
    service = MagicMock()
    registry = build_sol_registry(MagicMock(), uuid4(), presence_service=service)
    descriptor = next(t for t in registry.list() if t.name == "hardware.flash_presence")
    assert descriptor.requires_confirmation


def test_presence_absent_without_local_service():
    registry = build_sol_registry(MagicMock(), uuid4())
    assert "hardware.flash_presence" not in {t.name for t in registry.list()}
