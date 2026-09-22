"""Static sketch facts must never turn comments or unknown expressions into wiring."""

from .local_paths import overlay_module


def parse(text):
    return overlay_module("arduino").parse_sketch(text)


def test_literal_alias_pin_bus_and_library_observations():
    result = parse(
        "#include <Wire.h>\nconst int SENSOR = A0;\n"
        "void setup(){Wire.begin();pinMode(13, OUTPUT);}\nvoid loop(){analogRead(SENSOR);}"
    )
    assert result["libraries"] == ["Wire.h"]
    assert result["buses"] == ["i2c"]
    assert result["pins"] == [
        {"operation": "pinMode", "pin": "13", "line": 3},
        {"operation": "analogRead", "pin": "A0", "line": 4},
    ]
    assert not result["incomplete"]


def test_comments_strings_and_mutable_alias_are_not_facts():
    result = parse(
        '// analogRead(A9);\nchar *s="digitalWrite(4,1)";\n'
        "/* SPI.begin(); */\nint pin=8;\nvoid loop(){analogRead(pin);}"
    )
    assert result["buses"] == []
    assert result["pins"] == [{"operation": "analogRead", "pin": None, "line": 5}]
    assert result["incomplete"]


def test_conditional_alias_and_conflicting_definitions_are_unknown():
    result = parse(
        "#if BOARD\n#define SENSOR A0\n#else\n#define SENSOR A1\n#endif\nanalogRead(SENSOR);"
    )
    assert result["pins"][0]["pin"] is None
    assert result["incomplete"]


def test_oversized_and_excess_observations_mark_incomplete():
    assert parse("x" * 65537)["incomplete"]
    result = parse("analogRead(A0);\n" * 129)
    assert len(result["pins"]) == 128
    assert result["incomplete"]


def test_collector_refuses_symlinks_and_traversal(tmp_path):
    module = overlay_module("arduino")
    (tmp_path / "good.ino").write_text("analogRead(A0);")
    (tmp_path / "link.ino").symlink_to(tmp_path / "good.ino")
    rows = module.collect_sketches(tmp_path, [["good.ino"], ["link.ino"], ["..", "outside.ino"]])
    assert rows[0]["pins"][0]["pin"] == "A0"
    assert all(r["incomplete"] for r in rows[1:])


def test_shadowed_alias_is_unknown():
    result = parse("const int SENSOR=A0;\nvoid sample(int SENSOR){analogRead(SENSOR);}")
    assert result["pins"][0]["pin"] is None
    assert result["incomplete"]


def test_unterminated_comment_and_raw_string_do_not_invent_calls():
    for text in ["/* analogRead(A0);", 'auto text=R"foo(digitalRead(3);)foo";']:
        result = parse(text)
        assert result["pins"] == []
        assert result["incomplete"]


def test_scan_includes_sketch_observations(tmp_path):
    (tmp_path / "sample.ino").write_text("analogRead(A0);")
    result = overlay_module("scan").scan_folder(tmp_path, tools={})
    assert result["arduino"][0]["parts"] == ["sample.ino"]
    assert result["arduino"][0]["pins"][0]["pin"] == "A0"
    assert not result["truncated_arduino"]


def test_member_calls_and_redefined_names_are_not_core_pin_calls():
    assert parse("sensor.analogRead(3);")["pins"] == []
    result = parse("#define analogRead(x) custom(x)\nanalogRead(3);")
    assert result["pins"] == []
    assert result["incomplete"]


def test_library_overflow_is_explicit():
    result = parse("".join(f"#include <Lib{i}.h>\n" for i in range(65)))
    assert len(result["libraries"]) == 64
    assert result["incomplete"]


def test_symlink_root_is_not_followed(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "main.ino").write_text("analogRead(A0);")
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    result = overlay_module("arduino").collect_sketches(linked, [["main.ino"]])
    assert result[0]["incomplete"]
    assert not result[0]["pins"]


def test_whitespace_qualified_calls_do_not_become_board_facts():
    result = parse("sensor . analogRead(3); sensor . Wire.begin();")
    assert result["pins"] == []
    assert result["buses"] == []


def test_other_alias_shadow_types_are_unknown():
    result = parse("const int PIN=9; void f(long PIN){digitalRead(PIN);}")
    assert result["pins"][0]["pin"] is None


def test_symlink_ancestor_is_not_followed(tmp_path):
    actual = tmp_path / "actual"
    (actual / "root").mkdir(parents=True)
    (actual / "root" / "main.ino").write_text("analogRead(A0);")
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    result = overlay_module("arduino").collect_sketches(linked / "root", [["main.ino"]])
    assert result[0]["incomplete"]
    assert not result[0]["pins"]
