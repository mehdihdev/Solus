"""The user's engineering preferences at the request boundary (SOLUSDEV-244 / HOME H3).

`~/.solus/preferences.json` is machine-local and user-authored (ADR-034 as amended
2026-09-06); the server never reads that file. The desktop attaches the document
to each SOL turn as `MessageCreate.preferences`, and this schema is where it is
re-validated: the same fields and caps as the shared-types parser
(`packages/shared-types/src/engineering-preferences.ts`), strict shape, over-cap
text refused. Nothing here is persisted — the transcript keeps the message, not
the preferences.

`prompt_payload()` is the only thing the prompt builder receives: labelled,
trimmed, non-empty sections. It is still user-authored text and enters the
prompt only inside a nonce fence (`agent/prompt.py`).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field, StrictInt

#: Caps mirror `PREFERENCES_FIELD_CAP` / `PREFERENCES_FREE_TEXT_CAP` in shared-types.
#: The whole document at cap (2 400 + 5 × 800 = 6 400 chars) stays under the
#: prompt's 8 000-char block cap, so one fenced block always carries it intact.
PREFERENCE_FIELD_CAP: Final = 800
PREFERENCE_FREE_TEXT_CAP: Final = 2_400

#: Section → the label a model reads. Order is display and prompt order.
PREFERENCE_LABELS: Final[dict[str, str]] = {
    "code_style": "Code style",
    "mechanical": "Mechanical",
    "electrical": "Electrical",
    "documentation": "Documentation",
    "units_standards": "Units and standards",
}
FREE_TEXT_LABEL: Final = "Notes"


class EngineeringPreferences(BaseModel):
    """The desktop's copy of `~/.solus/preferences.json`, validated at the boundary."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: StrictInt = Field(default=1, ge=1)
    updated_at: str | None = Field(default=None, alias="updatedAt", max_length=64)
    free_text: str = Field(default="", alias="freeText", max_length=PREFERENCE_FREE_TEXT_CAP)
    code_style: str = Field(default="", alias="codeStyle", max_length=PREFERENCE_FIELD_CAP)
    mechanical: str = Field(default="", max_length=PREFERENCE_FIELD_CAP)
    electrical: str = Field(default="", max_length=PREFERENCE_FIELD_CAP)
    documentation: str = Field(default="", max_length=PREFERENCE_FIELD_CAP)
    units_standards: str = Field(
        default="", alias="unitsStandards", max_length=PREFERENCE_FIELD_CAP
    )

    def _sections(self) -> dict[str, str]:
        raw = {name: getattr(self, name).strip() for name in PREFERENCE_LABELS}
        raw["free_text"] = self.free_text.strip()
        return raw

    def is_empty(self) -> bool:
        """Nothing but whitespace anywhere — the turn carries no preferences."""
        return not any(self._sections().values())

    def prompt_payload(self) -> dict[str, str]:
        """Labelled, trimmed, non-empty sections in prompt order; free text last."""
        sections = self._sections()
        payload = {
            PREFERENCE_LABELS[name]: sections[name] for name in PREFERENCE_LABELS if sections[name]
        }
        if sections["free_text"]:
            payload[FREE_TEXT_LABEL] = sections["free_text"]
        return payload
