"""The ignition adapter (Citadel 3, Edifice 5, Fortress 6): the gz shapes under ``ign``,
``ignition.msgs.*`` types and the ``gazebo`` subcommand. ``--timeout`` is mandatory for
``ign service --req`` (RECON §2) and the base class always sends it."""

from __future__ import annotations

from typing import ClassVar

from .gz import GzAdapter


class IgnitionAdapter(GzAdapter):
    MSGS: ClassVar[str] = "ignition.msgs"
    SUB: ClassVar[str] = "gazebo"
