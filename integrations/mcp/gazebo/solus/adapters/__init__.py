"""One adapter per Gazebo family; :func:`adapter_for` picks it from a detected `Family`."""

from __future__ import annotations

from typing import Any

from ..family_detect import Family
from .adapter_base import Adapter
from .classic import ClassicAdapter
from .gz import GzAdapter
from .ignition import IgnitionAdapter

_ADAPTERS: dict[str, type[GzAdapter] | type[ClassicAdapter]] = {
    "gz": GzAdapter,
    "ignition": IgnitionAdapter,
    "classic": ClassicAdapter,
}


def adapter_for(family: Family, **kwargs: Any) -> Adapter:
    return _ADAPTERS[family.name](family, **kwargs)


__all__ = ["Adapter", "ClassicAdapter", "GzAdapter", "IgnitionAdapter", "adapter_for"]
