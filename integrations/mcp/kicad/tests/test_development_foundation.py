"""Safety contracts for schematic construction, without customer designs."""

import os
from pathlib import Path
from typing import Any

import pytest

from test_overlay_support import SOLUS  # noqa: F401  # isort: skip
from solus.development.commit import commit_plan
from solus.development.geometry import project_pin
from solus.development.library import LibraryResolver
from solus.development.models import DevelopmentError, Point, fingerprint, schematic_path
from solus.development.plan import MutationPlan
from solus.development.structural import insert_nodes

EMPTY = b'(kicad_sch (version 20250114) (uuid "root") (lib_symbols))\n'
LIBRARY = b"""(kicad_symbol_lib (version 20250114) (generator "test")
(symbol "R" (property "Reference" "R") (property "Value" "R")
(symbol "R_1_1" (pin passive line (at 0 3.81 270) (name "A") (number "1"))
(pin passive line (at 0 -3.81 90) (name "B") (number "2")))))"""


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -1, 1001, 1.23456])
def test_coordinates_are_bounded_finite_numbers(value: object) -> None:
    with pytest.raises(DevelopmentError):
        Point.from_dict({"x_mm": value, "y_mm": 1})


@pytest.mark.parametrize(
    "path", ["../a.kicad_sch", "/a.kicad_sch", "a//b.kicad_sch", "a/./b.kicad_sch", "a.txt"]
)
def test_relative_path_is_canonical(path: str) -> None:
    with pytest.raises(DevelopmentError):
        schematic_path(path)


def test_structural_insertion_preserves_every_other_byte() -> None:
    addition = b'(wire (pts (xy 0 0) (xy 1 0)) (uuid "new-wire"))'
    result = insert_nodes(EMPTY, root_nodes=[addition])
    assert result.replace(b"\n" + addition, b"") == EMPTY
    assert result.count(addition) == 1


@pytest.mark.parametrize("addition", [b") (evil)", b'(wire (uuid "root"))', b'(uuid "replace")'])
def test_structural_insertion_refuses_malformed_or_duplicate_nodes(addition: bytes) -> None:
    with pytest.raises(DevelopmentError):
        insert_nodes(EMPTY, root_nodes=[addition])


def test_plan_is_deterministic_and_hash_is_not_shortened() -> None:
    plan = MutationPlan.build("a.kicad_sch", EMPTY, EMPTY, {"operation": "noop"}, [])
    assert plan.before_fingerprint == fingerprint(EMPTY)
    assert len(plan.before_fingerprint.replace(":", "")) == 64
    assert plan.entity_uuid("symbol") == plan.entity_uuid("symbol")


def test_atomic_create_collision_and_stale_update_leave_original(tmp_path: Path) -> None:
    original = tmp_path / "a.kicad_sch"
    original.write_bytes(EMPTY)
    create = MutationPlan.build("a.kicad_sch", None, EMPTY, {}, [])
    with pytest.raises(DevelopmentError, match="already_exists"):
        commit_plan(tmp_path, create)
    update = MutationPlan.build(
        "a.kicad_sch",
        EMPTY,
        insert_nodes(EMPTY, root_nodes=[b'(label "N" (at 1 1 0) (uuid "n"))']),
        {},
        [],
    )
    original.write_bytes(EMPTY + b" ")
    with pytest.raises(DevelopmentError, match="stale_plan"):
        commit_plan(tmp_path, update)
    assert original.read_bytes() == EMPTY + b" "


def test_confined_atomic_creation_and_readback(tmp_path: Path) -> None:
    plan = MutationPlan.build("new.kicad_sch", None, EMPTY, {}, [])
    assert commit_plan(tmp_path, plan) == fingerprint(EMPTY)
    assert (tmp_path / "new.kicad_sch").read_bytes() == EMPTY


def test_symlink_parent_never_modified(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    plan = MutationPlan.build("link/new.kicad_sch", None, EMPTY, {}, [])
    with pytest.raises(DevelopmentError):
        commit_plan(root, plan)
    assert not list(outside.iterdir())


def test_real_library_pin_coordinates_are_projected_without_guessing(tmp_path: Path) -> None:
    (tmp_path / "Device.kicad_sym").write_bytes(LIBRARY)
    definition = LibraryResolver(tmp_path).resolve("Device:R")
    assert [(p.number, p.x_mm, p.y_mm) for p in definition.pins] == [
        ("1", 0, 3.81),
        ("2", 0, -3.81),
    ]
    assert project_pin(definition.pins[0], Point(10, 10), 0) == Point(10, 6.19)
    assert project_pin(definition.pins[0], Point(10, 10), 90) == Point(6.19, 10)


@pytest.mark.parametrize("identity", ["../Device:R", "Device:../R", "Device:R:other"])
def test_library_identifier_cannot_escape_root(tmp_path: Path, identity: str) -> None:
    with pytest.raises(DevelopmentError):
        LibraryResolver(tmp_path).resolve(identity)


def test_duplicate_embedded_library_identity_is_refused() -> None:
    original = b'(kicad_sch (lib_symbols (symbol "Device:R")))'
    with pytest.raises(DevelopmentError, match="ambiguous_target"):
        insert_nodes(original, library_nodes=[b'(symbol "Device:R")'])


def test_selected_symbol_cannot_exceed_its_token_budget(tmp_path: Path) -> None:
    blob = b'(kicad_symbol_lib (symbol "Huge" ' + b"(x 1) " * 6000 + b"))"
    (tmp_path / "Device.kicad_sym").write_bytes(blob)
    with pytest.raises(DevelopmentError, match="file_too_large"):
        LibraryResolver(tmp_path).resolve("Device:Huge")


def test_projection_refuses_out_of_sheet_pin() -> None:
    from solus.development.library import LibraryPin

    pin = LibraryPin("1", "x", "passive", 0, 3.81, 270, 1)
    with pytest.raises(DevelopmentError, match="invalid_geometry"):
        project_pin(pin, Point(0, 0), 0)


def test_atomic_failure_preserves_original_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    target = tmp_path / "a.kicad_sch"
    target.write_bytes(EMPTY)
    proposed = insert_nodes(EMPTY, root_nodes=[b'(no_connect (at 1 1) (uuid "x"))'])
    plan = MutationPlan.build("a.kicad_sch", EMPTY, proposed, {}, [])

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("simulated filesystem error")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(DevelopmentError, match="mutation_unverified"):
        commit_plan(tmp_path, plan)
    assert target.read_bytes() == EMPTY
    assert not list(tmp_path.glob("*.tmp"))


def test_replaced_parent_is_refused_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    root = tmp_path / "root"
    root.mkdir()
    parent = root / "sub"
    parent.mkdir()
    elsewhere = tmp_path / "moved"
    plan = MutationPlan.build("sub/a.kicad_sch", None, EMPTY, {}, [])
    real_fsync = os.fsync
    swapped = False

    def swap_after_temp_write(fd: int) -> None:
        nonlocal swapped
        real_fsync(fd)
        if not swapped:
            swapped = True
            parent.rename(elsewhere)
            parent.mkdir()

    monkeypatch.setattr(os, "fsync", swap_after_temp_write)
    with pytest.raises(DevelopmentError, match="path_escapes_workspace"):
        commit_plan(root, plan)
    assert not (elsewhere / "a.kicad_sch").exists()
    assert not (parent / "a.kicad_sch").exists()


def test_library_open_is_nonblocking_and_checks_regular_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    real_open = os.open
    flags_seen: list[int] = []

    def nonregular(path: object, flags: int) -> int:
        flags_seen.append(flags)
        return real_open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)

    monkeypatch.setattr(os, "open", nonregular)
    with pytest.raises(DevelopmentError):
        LibraryResolver(tmp_path).resolve("Device:R")
    assert flags_seen[0] & os.O_NONBLOCK


def test_generated_path_preview_cannot_be_truncated() -> None:
    path = "/".join(["a" * 100] * 4) + "/b.kicad_sch"
    with pytest.raises(DevelopmentError, match="file_too_large"):
        MutationPlan.build(path, None, EMPTY, {}, [])


def test_two_processes_cannot_overwrite_the_same_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import multiprocessing

    # Aggregate collection adds other standalone forks named `solus`. Spawn
    # imports afresh, so explicitly select this writer's package in child paths.
    monkeypatch.syspath_prepend(str(SOLUS.parent))
    context = multiprocessing.get_context("spawn")
    first_ready, second_inside = context.Event(), context.Event()
    results = context.Queue()
    (tmp_path / "a.kicad_sch").write_bytes(EMPTY)

    processes = [
        context.Process(
            target=_concurrent_writer, args=(tmp_path, first, first_ready, second_inside, results)
        )
        for first in (True, False)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(5)
            assert not process.is_alive(), "writer did not terminate"
            assert process.exitcode == 0
        assert sorted([results.get(timeout=1), results.get(timeout=1)]) == ["stale_plan", "success"]
        expected = insert_nodes(EMPTY, root_nodes=[b'(no_connect (at 1 1) (uuid "first"))'])
        assert (tmp_path / "a.kicad_sch").read_bytes() == expected
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        results.close()
        results.join_thread()


def _concurrent_writer(
    tmp_path: Path, first: bool, first_ready: Any, second_inside: Any, results: Any
) -> None:
    real_fsync = os.fsync
    intercepted = False

    def sync(fd: int) -> None:
        nonlocal intercepted
        real_fsync(fd)
        if not intercepted:
            intercepted = True
            if first:
                first_ready.set()
                second_inside.wait(1)
            else:
                second_inside.set()

    patch = pytest.MonkeyPatch()
    patch.setattr(os, "fsync", sync)
    if not first:
        first_ready.wait(3)
    node = (
        b'(no_connect (at 1 1) (uuid "first"))'
        if first
        else b'(no_connect (at 2 2) (uuid "second"))'
    )
    plan = MutationPlan.build("a.kicad_sch", EMPTY, insert_nodes(EMPTY, root_nodes=[node]), {}, [])
    try:
        commit_plan(tmp_path, plan)
        results.put("success")
    except DevelopmentError as exc:
        results.put(exc.reason)


def test_fifo_library_is_refused_without_waiting(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "Device.kicad_sym")
    with pytest.raises(DevelopmentError, match="library_unavailable"):
        LibraryResolver(tmp_path).resolve("Device:R")


def test_native_library_root_precedes_flatpak_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus.development import library

    monkeypatch.setattr(library, "_native_library_roots", lambda: [tmp_path], raising=False)
    assert library.installed_library_root() == tmp_path


def test_publication_then_oserror_reports_uncertain(tmp_path, monkeypatch):
    target = tmp_path / "a.kicad_sch"
    target.write_bytes(EMPTY)
    proposed = EMPTY + b" "
    plan = MutationPlan.build(target.name, EMPTY, proposed, {}, [])
    real_replace = os.replace

    def replace_then_raise(*args, **kwargs):
        real_replace(*args, **kwargs)
        raise OSError("reported after publication")

    monkeypatch.setattr(os, "replace", replace_then_raise)
    with pytest.raises(DevelopmentError, match="mutation_unverified"):
        commit_plan(tmp_path, plan)
    assert target.read_bytes() == proposed


def test_final_directory_swap_never_reports_verified(tmp_path, monkeypatch):
    directory = tmp_path / "nested"
    directory.mkdir()
    target = directory / "a.kicad_sch"
    target.write_bytes(EMPTY)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / target.name
    sentinel.write_bytes(EMPTY)
    plan = MutationPlan.build("nested/a.kicad_sch", EMPTY, EMPTY + b" ", {}, [])
    real_fsync = os.fsync
    swapped = False

    def swap_after_directory_sync(fd):
        nonlocal swapped
        import stat

        real_fsync(fd)
        if stat.S_ISDIR(os.fstat(fd).st_mode) and not swapped:
            swapped = True
            directory.rename(tmp_path / "moved")
            directory.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(os, "fsync", swap_after_directory_sync)
    with pytest.raises(DevelopmentError, match="mutation_unverified"):
        commit_plan(tmp_path, plan)
    assert sentinel.read_bytes() == EMPTY
