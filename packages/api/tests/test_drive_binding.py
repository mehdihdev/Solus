"""The turn's `front_app` and the stored window binding (sol-drive.md §2.2,
docs/api/API-implementation.md streaming turn `front_app`): strict shape,
visible text only, and the drivable/binding consistency rules."""

from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.agent.drive.binding import FrontAppBinding, WindowBinding, is_solus

WINDOW_BOUND: dict[str, Any] = {
    "bundle_id": "com.prusa3d.slic3r",
    "name": "PrusaSlicer",
    "title": "benchy.3mf",
    "pid": 4321,
    "window_id": 88,
    "drivable": True,
    "binding": "window",
}
DENIED: dict[str, Any] = {
    "bundle_id": "com.apple.Terminal",
    "name": "Terminal",
    "title": None,
    "pid": None,
    "window_id": None,
    "drivable": False,
    "binding": None,
}


def test_a_window_bound_front_app_yields_its_window() -> None:
    window = FrontAppBinding(**WINDOW_BOUND).window()
    assert window == WindowBinding(
        bundle_id="com.prusa3d.slic3r", name="PrusaSlicer", title="benchy.3mf", pid=4321,
        window_id=88,
    )  # fmt: skip


@pytest.mark.parametrize(
    "front",
    [
        DENIED,
        {**DENIED, "bundle_id": "org.kicad.kicad", "name": "KiCad", "binding": "project"},
        {**WINDOW_BOUND, "bundle_id": "org.kicad.kicad", "binding": "project"},
    ],
)
def test_only_a_drivable_window_bound_app_has_a_window(front: dict[str, Any]) -> None:
    assert FrontAppBinding(**front).window() is None


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "x"},  # a denied app's title is never accepted
        {"pid": 5},
        {"window_id": 6},
        {"binding": "window"},
    ],
)
def test_a_non_drivable_app_carries_nothing_but_its_identity(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FrontAppBinding(**{**DENIED, **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"binding": None},
        {"pid": None},
        {"pid": 0},
        {"pid": 2**31},
        {"window_id": 2**32},
        {"pid": True},
        {"pid": "4321"},
        {"bundle_id": "has space"},
        {"bundle_id": ".leading"},
        {"bundle_id": "a" * 129},
        {"name": ""},
        {"name": "x" * 65},
        {"title": "x" * 257},
        {"title": "line\nbreak"},
        {"title": "rtl‮override"},
        {"name": "zero​width"},
        {"extra": 1},
    ],
)
def test_malformed_front_apps_are_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FrontAppBinding(**{**WINDOW_BOUND, **changes})


def test_the_stored_window_is_strict_and_closed() -> None:
    window = FrontAppBinding(**WINDOW_BOUND).window()
    assert window is not None
    with pytest.raises(ValidationError):
        WindowBinding(**{**window.model_dump(), "extra": 1})
    with pytest.raises(ValidationError):
        WindowBinding(**{**window.model_dump(), "pid": None})


@pytest.mark.parametrize(
    ("bundle", "solus"),
    [
        ("com.solusforge.solus", True),
        ("com.solusforge.solus.helper.Renderer", True),
        ("com.github.Electron", True),
        ("com.solusforge.solusx", False),
        ("com.prusa3d.slic3r", False),
    ],
)
def test_solus_itself_is_recognised_by_family(bundle: str, solus: bool) -> None:
    assert is_solus(bundle) is solus


def test_a_missing_window_id_key_is_still_refused() -> None:
    # Normalisation covers an explicit null (no window in front), never an absent key.
    front = {k: v for k, v in WINDOW_BOUND.items() if k != "window_id"}
    with pytest.raises(ValidationError):
        FrontAppBinding.model_validate(front)


@pytest.mark.parametrize("window_id", [None, 0])
def test_a_windowless_window_bound_app_is_not_drivable(window_id: int | None) -> None:
    binding = FrontAppBinding.model_validate({**WINDOW_BOUND, "window_id": window_id})
    assert (binding.drivable, binding.binding) == (False, None)
    assert (binding.title, binding.pid, binding.window_id) == (None, None, None)
    assert binding.window() is None
