"""ADR-041 §5 + 2026-10-26 amendment: the computer-use toolset is translated onto
the closed drive vocabulary by Solus code. Members outside §5 are disabled in the
request; a proposal that cannot be expressed is answered as an error (the model
may try again within the budget); a proposal outside the screenshot ends the
step (a §5 bounds check, not a retry)."""

from typing import Literal

import pytest
from solus_api.agent.drive.actions import (
    DISABLED_MEMBERS,
    ENABLED_MEMBERS,
    TOOLSET,
    ActRequest,
    Capture,
    Frame,
    OutOfBounds,
    Unsupported,
    error_result,
    image_result,
    map_action,
    ok_result,
    skipped_result,
)

# A 1280x800 capture of a 640x400-point window (a 2x Retina window, downscaled 1:1
# to points would be 640 wide; here the image is twice the points).
FRAME = Frame(image_width=1280, image_height=800, points_width=640, points_height=400)


def test_the_toolset_disables_every_member_outside_the_vocabulary() -> None:
    assert TOOLSET["type"] == "computer_toolset_20260801"
    assert "name" not in TOOLSET
    assert set(TOOLSET["configs"]) == DISABLED_MEMBERS
    assert all(entry == {"enabled": False} for entry in TOOLSET["configs"].values())
    assert len(ENABLED_MEMBERS | DISABLED_MEMBERS) == 17
    assert ENABLED_MEMBERS.isdisjoint(DISABLED_MEMBERS)
    assert {"zoom", "hold_key", "left_mouse_down", "cursor_position"} <= DISABLED_MEMBERS


def test_screenshot_is_a_capture() -> None:
    assert map_action("screenshot", {}, FRAME) == Capture()


@pytest.mark.parametrize(
    ("member", "button", "count"),
    [("left_click", "left", 1), ("double_click", "left", 2), ("right_click", "right", 1)],
)
def test_clicks_scale_image_pixels_to_window_points(
    member: str, button: Literal["left", "right"], count: int
) -> None:
    act = map_action(member, {"coordinate": [200, 101]}, FRAME)
    assert act == ActRequest(verb="click", x=100, y=50, button=button, count=count)


def test_move_drag_and_scroll() -> None:
    assert map_action("mouse_move", {"coordinate": [10, 10]}, FRAME) == ActRequest(
        verb="move", x=5, y=5
    )
    drag = map_action(
        "left_click_drag", {"start_coordinate": [0, 0], "coordinate": [400, 200]}, FRAME
    )
    assert drag == ActRequest(verb="drag", x=0, y=0, to_x=200, to_y=100)
    up = map_action(
        "scroll", {"coordinate": [20, 20], "scroll_direction": "up", "scroll_amount": 3}, FRAME
    )
    assert up == ActRequest(verb="scroll", x=10, y=10, dx=0, dy=3)
    left = map_action(
        "scroll", {"coordinate": [20, 20], "scroll_direction": "left", "scroll_amount": 2}, FRAME
    )
    assert left == ActRequest(verb="scroll", x=10, y=10, dx=2, dy=0)


@pytest.mark.parametrize(
    ("text", "chord"),
    [
        ("Return", "return"),
        ("KP_Enter", "return"),
        ("Escape", "escape"),
        ("BackSpace", "delete"),
        ("Delete", "forwarddelete"),
        ("Page_Down", "pagedown"),
        ("super+z", "cmd+z"),
        ("cmd+shift+z", "cmd+shift+z"),
        ("ctrl+s", "ctrl+s"),
        ("alt+Tab", "option+tab"),
        ("a", "a"),
        ("Up", "up"),
    ],
)
def test_key_names_become_helper_chords(text: str, chord: str) -> None:
    assert map_action("key", {"text": text}, FRAME) == ActRequest(verb="key", chord=chord)


def test_typing_and_waiting() -> None:
    assert map_action("type", {"text": "10k"}, FRAME) == ActRequest(verb="type", text="10k")
    assert map_action("wait", {"duration": 1.5}, FRAME) == ActRequest(verb="wait", ms=1500)


@pytest.mark.parametrize(
    ("member", "args"),
    [
        ("left_click", {}),  # at the cursor: no point to check
        ("left_click", {"coordinate": [1, 1], "text": "shift"}),  # modifier clicks
        ("double_click", {"coordinate": [1, 1], "text": "cmd"}),
        ("left_click_drag", {"start_coordinate": [1, 1], "coordinate": [2, 2], "text": "alt"}),
        ("scroll", {"coordinate": [1, 1], "scroll_direction": "sideways", "scroll_amount": 1}),
        ("scroll", {"coordinate": [1, 1], "scroll_direction": "up", "scroll_amount": 51}),
        ("scroll", {"coordinate": [1, 1], "scroll_direction": "up", "scroll_amount": 0}),
        ("key", {"text": "Return", "repeat": 3}),
        ("key", {"text": "Hyper_L"}),
        ("key", {"text": "ctrl+ctrl+a"}),
        ("key", {"text": "cmd+"}),
        ("wait", {"duration": 5}),
        ("type", {"text": ""}),
        ("type", {"text": 7}),
        ("left_click", {"coordinate": [1.5, 2]}),
        ("left_click", {"coordinate": [1, 2, 3]}),
        ("left_click", {"coordinate": "1,2"}),
        ("zoom", {"region": [0, 0, 10, 10]}),
        ("hold_key", {"text": "shift", "duration": 1}),
        ("bash", {"command": "ls"}),
    ],
)
def test_proposals_the_vocabulary_cannot_express_are_unsupported(
    member: str, args: dict[str, object]
) -> None:
    assert isinstance(map_action(member, args, FRAME), Unsupported)


@pytest.mark.parametrize(
    ("member", "args"),
    [
        ("left_click", {"coordinate": [1280, 10]}),
        ("left_click", {"coordinate": [-1, 10]}),
        ("mouse_move", {"coordinate": [10, 800]}),
        ("left_click_drag", {"start_coordinate": [0, 0], "coordinate": [5000, 5]}),
        ("scroll", {"coordinate": [10, 9000], "scroll_direction": "down", "scroll_amount": 1}),
    ],
)
def test_a_point_outside_the_screenshot_ends_the_step(member: str, args: dict[str, object]) -> None:
    assert isinstance(map_action(member, args, FRAME), OutOfBounds)


def test_act_request_argument_order_is_fixed_and_omits_none() -> None:
    act = ActRequest(verb="click", x=1, y=2, button="left", count=1)
    assert act.args() == {"verb": "click", "x": 1, "y": 2, "button": "left", "count": 1}


def test_results_echo_the_toolset_name() -> None:
    image = image_result("t1", b"\x89PNG")
    assert image["toolset_name"] == "computer"
    assert image["tool_use_id"] == "t1"
    assert image["content"][0]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": "iVBORw==",
    }
    ok = ok_result("t2")
    assert ok == {
        "type": "tool_result",
        "tool_use_id": "t2",
        "toolset_name": "computer",
        "content": [{"type": "text", "text": "OK"}],
    }
    err = error_result("t3", "no")
    assert err["is_error"] is True and err["toolset_name"] == "computer"
    skipped = skipped_result("t4")
    assert skipped["content"] == "Not executed: an earlier computer action in this turn failed."
    assert skipped["is_error"] is True
