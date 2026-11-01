"""The window a `front` drive step is bound to (sol-drive.md §2.2, ADR-041 2026-10-31).

`FrontAppBinding` is the turn's `front_app` (docs/api/API-implementation.md,
streaming turn): the app the user summoned SOL over, from desktop main's summon
snapshot. `WindowBinding` is what Solus code copies from it into a parked
`drive.step`'s stored arguments — never from model arguments — so the card's
rows, the decide-time staleness re-check and the executor's bind all read the
same five values. Titles and names are untrusted data from the machine.
"""

import unicodedata
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BUNDLE_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$"
PID_MAX: Final = 2**31 - 1
WINDOW_ID_MAX: Final = 2**32 - 1
NAME_MAX: Final = 64
TITLE_MAX: Final = 256
#: The API's "visible text only" rule for names and titles.
_HIDDEN: Final = frozenset({"Cc", "Cf", "Co", "Cn", "Cs", "Zl", "Zp"})
#: Solus itself as the helper denies it (sol-drive.md §2.2 "Solus itself"):
#: while one of these is in front the pill still has focus, so a bind waits.
_SOLUS_FAMILIES: Final = ("com.solusforge.solus", "com.github.Electron")


def is_solus(bundle_id: str) -> bool:
    return any(bundle_id == f or bundle_id.startswith(f"{f}.") for f in _SOLUS_FAMILIES)


def _visible(text: str | None) -> str | None:
    if text is not None and any(unicodedata.category(ch) in _HIDDEN for ch in text):
        raise ValueError("visible text only")
    return text


class WindowBinding(BaseModel):
    """The stored `window` of a parked `drive.step {app: "front"}`."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    bundle_id: str = Field(pattern=BUNDLE_ID_PATTERN)
    name: str = Field(min_length=1, max_length=NAME_MAX)
    title: str | None = Field(max_length=TITLE_MAX)
    pid: int = Field(ge=1, le=PID_MAX)
    window_id: int = Field(ge=1, le=WINDOW_ID_MAX)

    _visible_text = field_validator("name", "title")(_visible)


class FrontAppBinding(BaseModel):
    """The turn's `front_app`, with the API doc's shape and consistency rules —
    usable directly as the request-body field type."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    bundle_id: str = Field(pattern=BUNDLE_ID_PATTERN)
    name: str = Field(min_length=1, max_length=NAME_MAX)
    title: str | None = Field(max_length=TITLE_MAX)
    pid: int | None = Field(ge=1, le=PID_MAX)
    window_id: int | None = Field(ge=1, le=WINDOW_ID_MAX)
    drivable: bool
    binding: Literal["project", "window"] | None

    _visible_text = field_validator("name", "title")(_visible)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not self.drivable:
            if (self.title, self.pid, self.window_id) != (None, None, None):
                raise ValueError("a non-drivable app carries no title, pid or window id")
            if self.binding == "window":
                raise ValueError("a non-drivable app is never window-bound")
            return self
        if self.binding is None:
            raise ValueError("a drivable app has a binding")
        if self.binding == "window" and (self.pid is None or self.window_id is None):
            raise ValueError("a window-bound app has a pid and a window id")
        return self

    def window(self) -> WindowBinding | None:
        """The window `drive.step {app: "front"}` binds to, or None when the
        front app is not drivable and window-bound (then `front` is not offered)."""
        if not (self.drivable and self.binding == "window"):
            return None
        assert self.pid is not None and self.window_id is not None
        return WindowBinding(
            bundle_id=self.bundle_id,
            name=self.name,
            title=self.title,
            pid=self.pid,
            window_id=self.window_id,
        )
