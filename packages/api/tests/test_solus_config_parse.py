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
    tables, problems = parse_project_toml_ext(
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
    assert problems == []
    assert tables == {
        "fixture-bundle": {"max_notes": 3, "prefix": "fx", "flag": True, "ratio": 0.5}
    }


def test_a_file_without_ext_is_empty_and_clean() -> None:
    assert parse_project_toml_ext('[project]\nname = "x"\n') == ({}, [])
    assert parse_project_toml_ext("") == ({}, [])


def test_invalid_toml_is_one_problem() -> None:
    tables, problems = parse_project_toml_ext("[ext.x\n")
    assert tables == {}
    assert len(problems) == 1 and "invalid TOML" in problems[0]


def test_bad_slugs_keys_and_values_are_dropped_and_named() -> None:
    tables, problems = parse_project_toml_ext(
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
    assert tables == {"good-bundle": {"ok": "yes"}}
    assert any("Bad_Slug" in p for p in problems)
    assert any("Bad Key" in p for p in problems)
    assert any("nested" in p for p in problems)
    assert any("list" in p for p in problems)


def test_caps_hold() -> None:
    too_big = "x" * (MAX_PROJECT_TOML_BYTES + 1)
    tables, problems = parse_project_toml_ext(too_big)
    assert tables == {} and "exceeds" in problems[0]

    many = "\n".join(f"[ext.b{i}]\nk = 1" for i in range(MAX_EXT_TABLES + 1))
    tables, problems = parse_project_toml_ext(many)
    assert tables == {} and "more than" in problems[0]

    keys = "[ext.bb]\n" + "\n".join(f"k{i} = 1" for i in range(MAX_KEYS_PER_TABLE + 1))
    tables, problems = parse_project_toml_ext(keys)
    assert tables == {} and any("more than" in p for p in problems)

    long_string = '[ext.bb]\ns = "' + "y" * 5000 + '"\n'
    tables, problems = parse_project_toml_ext(long_string)
    assert tables == {"bb": {}}
    assert any("bounded scalar" in p for p in problems)
