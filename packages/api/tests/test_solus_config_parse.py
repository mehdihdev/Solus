"""SOLUSDEV-246 — `parse_project_toml_ext`: the bounded, never-raising reader of
the repo-committed `.solus/project.toml` `[ext.<id>]` tables (CLAUDE.md §7:
committed files are untrusted input)."""

from __future__ import annotations

from solus_api.widgets.solus_config import (
    MAX_EXT_TABLES,
    MAX_KEYS_PER_TABLE,
    MAX_PROJECT_TOML_BYTES,
    parse_project_toml_ext,
)


def test_reads_only_ext_tables_with_scalar_values() -> None:
    parsed = parse_project_toml_ext(
        """
[project]
name = "ignored for now"

[ext.fixture-bundle]
max_notes = 3
prefix = "fx"
flag = true
ratio = 0.5
"""
    )
    assert parsed.problems == []
    assert parsed.tables == {
        "fixture-bundle": {"max_notes": 3, "prefix": "fx", "flag": True, "ratio": 0.5}
    }


def test_a_file_without_ext_is_empty_and_clean() -> None:
    assert parse_project_toml_ext('[project]\nname = "x"\n') == ({}, [], False)
    assert parse_project_toml_ext("") == ({}, [], False)


def test_invalid_toml_is_one_problem() -> None:
    parsed = parse_project_toml_ext("[ext.x\n")
    assert parsed.tables == {} and parsed.fatal
    assert len(parsed.problems) == 1 and "invalid TOML" in parsed.problems[0]


def test_bad_slugs_keys_and_values_are_dropped_and_named() -> None:
    parsed = parse_project_toml_ext(
        """
[ext.Bad_Slug]
a = 1

[ext.good-bundle]
"Bad Key" = 1
nested = { a = 1 }
list = [1, 2]
ok = "yes"
"""
    )
    assert parsed.tables == {"good-bundle": {"ok": "yes"}}
    assert not parsed.fatal  # dropped tables/keys are not a file-level failure
    assert any("Bad_Slug" in p for p in parsed.problems)
    assert any("Bad Key" in p for p in parsed.problems)
    assert any("nested" in p for p in parsed.problems)
    assert any("list" in p for p in parsed.problems)


def test_caps_hold() -> None:
    too_big = "x" * (MAX_PROJECT_TOML_BYTES + 1)
    parsed = parse_project_toml_ext(too_big)
    assert parsed.tables == {} and parsed.fatal and "exceeds" in parsed.problems[0]

    many = "\n".join(f"[ext.b{i}]\nk = 1" for i in range(MAX_EXT_TABLES + 1))
    parsed = parse_project_toml_ext(many)
    assert parsed.tables == {} and parsed.fatal and "more than" in parsed.problems[0]

    keys = "[ext.bb]\n" + "\n".join(f"k{i} = 1" for i in range(MAX_KEYS_PER_TABLE + 1))
    parsed = parse_project_toml_ext(keys)
    assert (
        parsed.tables == {} and not parsed.fatal and any("more than" in p for p in parsed.problems)
    )

    long_string = '[ext.bb]\ns = "' + "y" * 5000 + '"\n'
    parsed = parse_project_toml_ext(long_string)
    assert parsed.tables == {"bb": {}}
    assert any("bounded scalar" in p for p in parsed.problems)
