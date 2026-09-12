"""SOLUSDEV-250 Phase 2: the sketch print-order repo-config parser. A flat print sequence in
`loop()` / `while True:` names the channels of a bare-board float stream; any print under a
branch is a refusal, never a guess."""

from pathlib import Path

import pytest
from livebench.hardware.channel import TransportRegistry
from livebench.hardware.driver import DriverRegistry
from livebench.hardware.interrogator import InterrogatorRegistry
from livebench.hardware.registries import Registries
from livebench.hardware.repo_config import RepoParserRegistry, scan_repo
from livebench.plugins import load_all
from livebench.plugins.arduino.sketch_parser import SketchConfigParser

FIXTURES = Path(__file__).with_name("fixtures")


def _scan(root: Path) -> list:  # type: ignore[type-arg]
    registry = RepoParserRegistry()
    registry.register(SketchConfigParser)
    return scan_repo(root, registry)


def test_arduino_sketch_names_channels_in_print_order() -> None:
    (match,) = _scan(FIXTURES / "sketch_arduino")
    assert match.config_id == "sketch:car.ino" and match.label == "car.ino"
    assert match.parser_id == "sketch-print-order"
    assert match.protocol_hint == "raw-lines"
    assert [(p.name, p.address) for p in match.parts] == [
        ("motorL", "0"),
        ("motorR", "1"),
        ("dist", "2"),
        ("batt", "3"),
    ]
    assert match.params == {"baud": 115200, "declared_hz": pytest.approx(50.0)}


def test_micropython_sketch_names_channels_in_print_order() -> None:
    (match,) = _scan(FIXTURES / "sketch_micropython")
    assert match.config_id == "sketch:main.py"
    assert [p.name for p in match.parts] == ["motor_l", "motor_r", "dist", "batt"]
    assert match.params["declared_hz"] == pytest.approx(50.0)


def test_a_branch_dependent_print_order_is_refused() -> None:
    assert _scan(FIXTURES / "sketch_arduino_branchy") == []


def test_a_non_identifier_print_argument_is_refused(tmp_path: Path) -> None:
    (tmp_path / "s.ino").write_text(
        "void setup() { Serial.begin(9600); }\n"
        "void loop() { Serial.print(x*2); Serial.print(','); Serial.println(y); delay(10); }\n"
    )
    assert _scan(tmp_path) == []


def test_python_f_string_fields_and_sleep_are_read(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text(
        'while True:\n    print(f"{a},{b}", c)\n    time.sleep(0.1)\n'
    )
    (match,) = _scan(tmp_path)
    assert [p.name for p in match.parts] == ["a", "b", "c"]
    assert match.params["declared_hz"] == pytest.approx(10.0)


def test_printf_identifier_args_are_channels(tmp_path: Path) -> None:
    (tmp_path / "s.cpp").write_text(
        'void loop() { Serial.printf("%d,%d\\n", left, right); delay(50); }\n'
    )
    (match,) = _scan(tmp_path)
    assert [p.name for p in match.parts] == ["left", "right"]
    assert match.params == {"declared_hz": pytest.approx(20.0)}


def test_a_loop_without_prints_is_no_match(tmp_path: Path) -> None:
    (tmp_path / "s.ino").write_text("void loop() { delay(10); }\n")
    assert _scan(tmp_path) == []


def test_the_plugin_roster_registers_the_sketch_parser() -> None:
    registries = Registries(TransportRegistry(), DriverRegistry(), InterrogatorRegistry())
    load_all(registries)
    assert registries.repo_parsers.get("sketch-print-order").parser_id == "sketch-print-order"


# ── review fixes: one hostile file skips only itself; names and ids are bounded ─

GOOD_SKETCH = (
    "void setup() { Serial.begin(9600); }\nvoid loop() { Serial.println(x); delay(10); }\n"
)


def test_a_pathologically_nested_file_is_refused_and_skips_only_itself(tmp_path: Path) -> None:
    (tmp_path / "good.ino").write_text(GOOD_SKETCH)
    # 3000 nested plain blocks: a flat, static print order on paper — past the depth cap the
    # walk refuses the file rather than chew through it, and its neighbour still matches.
    (tmp_path / "hostile.ino").write_text(
        "void loop() { " + "{" * 3000 + "Serial.println(x);" + "}" * 3000 + " }\n"
    )
    assert [m.config_id for m in _scan(tmp_path)] == ["sketch:good.ino"]


def test_a_dangling_symlink_skips_only_itself(tmp_path: Path) -> None:
    good = tmp_path / "good.ino"
    good.write_text(GOOD_SKETCH)
    gone = tmp_path / "gone.ino"
    gone.symlink_to(tmp_path / "missing.ino")
    matches = SketchConfigParser().scan(tmp_path, [gone, good])
    assert [m.config_id for m in matches] == ["sketch:good.ino"]


def test_only_a_serial_begin_sets_the_baud_and_never_unsets_it(tmp_path: Path) -> None:
    (tmp_path / "s.ino").write_text(
        "void setup() { Serial.begin(115200); Wire.begin(); }\nvoid loop() { Serial.println(x); }\n"
    )
    (match,) = _scan(tmp_path)
    assert match.params["baud"] == 115200


def test_an_absurd_identifier_refuses_the_file(tmp_path: Path) -> None:
    (tmp_path / "s.ino").write_text(f"void loop() {{ Serial.println({'a' * 5000}); }}\n")
    assert _scan(tmp_path) == []


def test_a_config_id_past_the_bound_is_refused_not_truncated(tmp_path: Path) -> None:
    deep = tmp_path / ("d" * 100) / ("e" * 100) / ("f" * 100)
    deep.mkdir(parents=True)
    (deep / "s.ino").write_text(GOOD_SKETCH)
    assert _scan(tmp_path) == []
