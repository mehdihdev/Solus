"""Sketch observations stay bound to scanned source files, not invented hardware."""

import pytest
from pydantic import ValidationError
from solus_api.connectors.local_folder import FolderScan, build_local_graph


def scan(**updates):
    return FolderScan.model_validate(
        {
            "root_name": "fixture",
            "digest": "abcd",
            "files": [{"parts": ["main.ino"], "size": 20, "hash": None, "tool": "arduino"}],
            "arduino": [
                {
                    "parts": ["main.ino"],
                    "pins": [{"operation": "analogRead", "pin": "A0", "line": 1}],
                    "buses": ["i2c"],
                    "libraries": ["Wire.h"],
                    "incomplete": False,
                }
            ],
            **updates,
        }
    )


def test_observations_are_attached_to_existing_sketch_node():
    entities, edges = build_local_graph(scan(), machine_name="fixture", gitlab_host=None)
    node = next(e for e in entities if e.type == "arduino_sketch")
    assert node.properties["observations"][0]["pins"][0]["pin"] == "A0"
    assert node.properties["observations"][0]["source_file"] == "main.ino"
    assert len(entities) == 2  # no fabricated physical pin/component nodes
    assert len(edges) == 1


def test_unlisted_source_cannot_smuggle_observations():
    entities, _ = build_local_graph(scan(files=[]), machine_name="fixture", gitlab_host=None)
    assert len(entities) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"parts": ["..", "private.ino"]},
        {"buses": ["exec"]},
        {"pins": [{"operation": "eval", "pin": "A0", "line": 1}]},
        {"pins": [{"operation": "analogRead", "pin": "guessed", "line": 1}]},
    ],
)
def test_strict_observation_boundary(bad):
    with pytest.raises(ValidationError):
        scan(
            arduino=[
                {
                    "parts": ["main.ino"],
                    "pins": [],
                    "buses": [],
                    "libraries": [],
                    "incomplete": False,
                    **bad,
                }
            ]
        )


def test_any_partial_file_marks_sketch_observations_incomplete():
    context = scan()
    data = context.model_dump()
    data["arduino"][0]["incomplete"] = True
    entities, _ = build_local_graph(
        FolderScan.model_validate(data), machine_name="fixture", gitlab_host=None
    )
    node = next(e for e in entities if e.type == "arduino_sketch")
    assert node.properties["observations_incomplete"]
