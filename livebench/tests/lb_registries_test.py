"""Plugin loading: vendor knowledge registers itself from `livebench.plugins`; the shared
registries are built once, list what loaded, and never die on one plugin's import fault."""

import sys
import types

import pytest
from livebench.hardware.channel import TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.registries import Registries, default_registries
from livebench.plugins import PLUGIN_MODULES, load_all
from solus_api.hardware.config import TransportKind


def _fresh() -> Registries:
    return Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())


def test_default_registries_are_built_once_with_the_builtin_transport() -> None:
    first = default_registries()
    second = default_registries()
    assert first is second
    assert TransportKind.USB_SERIAL in first.transports.kinds()
    assert [p.parser_id for p in first.repo_parsers.all()][:1] == ["generic-structured"]


def test_registries_default_a_fresh_parser_registry_per_instance() -> None:
    first, second = _fresh(), _fresh()
    assert first.repo_parsers is not second.repo_parsers


def test_every_plugin_module_lives_under_the_plugins_package() -> None:
    assert PLUGIN_MODULES
    assert all(name.startswith("livebench.plugins.") for name in PLUGIN_MODULES)


def test_load_all_calls_register_on_each_plugin_and_skips_missing_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    good = types.ModuleType("livebench.plugins._fake_good")

    def register(registries: Registries) -> None:
        calls.append("good")

    good.register = register  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "livebench.plugins._fake_good", good)

    class _Finder:
        @staticmethod
        def find_spec(name: str, path: object = None, target: object = None) -> None:
            if name == "livebench.plugins._fake_missing":
                raise ImportError("python-can is not installed")
            return None

    monkeypatch.setattr(sys, "meta_path", [_Finder(), *sys.meta_path])
    registries = _fresh()
    loaded = load_all(
        registries,
        modules=("livebench.plugins._fake_good", "livebench.plugins._fake_missing"),
    )
    assert calls == ["good"]
    assert loaded == ["livebench.plugins._fake_good"]


def test_a_plugin_without_a_register_function_is_a_packaging_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = types.ModuleType("livebench.plugins._fake_broken")
    monkeypatch.setitem(sys.modules, "livebench.plugins._fake_broken", broken)
    with pytest.raises(AttributeError):
        load_all(_fresh(), modules=("livebench.plugins._fake_broken",))


def test_registries_module_names_no_vendor() -> None:
    import re
    from pathlib import Path

    import livebench.hardware.registries as module

    source = Path(module.__file__).read_text().lower()
    assert re.search(r"\b(feetech|dynamixel|lerobot|sts3215|px4|odrive|mavlink)\b", source) is None
