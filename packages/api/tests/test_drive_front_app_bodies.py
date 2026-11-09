"""SOLUSDEV-319 Phase 4 F3 — the desktop's turn bodies and the API agree (sol-drive.md §2.2,
API-implementation.md turn body `front_app`). The shared fixture lists helper `identify.front`
replies and the exact `front_app` body the desktop sends for each (apps/desktop
frontAppBody.test.ts pins that half); here every such body validates through `FrontAppBinding`
unchanged — none may 422 the turn — and a drivable window-bound app with no window is
normalised to not drivable rather than refused."""

import json
from pathlib import Path
from typing import Any

import pytest
from solus_api.agent.drive.binding import FrontAppBinding

FIXTURE = Path(__file__).resolve().parents[2] / "shared-types/fixtures/front-app-bodies.json"
DATA: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["name"])
def test_every_desktop_body_validates_unchanged(case: dict[str, Any]) -> None:
    binding = FrontAppBinding.model_validate(case["body"])
    assert binding.model_dump() == case["body"]


@pytest.mark.parametrize("case", DATA["api_normalises"], ids=lambda c: c["name"])
def test_a_windowless_window_bound_app_is_normalised_not_refused(case: dict[str, Any]) -> None:
    binding = FrontAppBinding.model_validate(case["input"])
    assert binding.model_dump() == case["body"]
    assert binding.window() is None
