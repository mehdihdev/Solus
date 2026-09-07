"""lerobot repo-config parser plugin (SOLUSDEV-248 R2): `Robot`/`Teleoperator` classes and the
HF-cache calibration JSON lerobot keeps for them become repo-config proposals. Vendor names live
here; the seam this plugs into (`livebench.hardware.repo_config`) never names them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from livebench.plugins.lerobot.lerobot_parser import LerobotConfigParser

if TYPE_CHECKING:
    from livebench.hardware.registries import Registries


def register(registries: Registries) -> None:
    registries.repo_parsers.register(LerobotConfigParser)
