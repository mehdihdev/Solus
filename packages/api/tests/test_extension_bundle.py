"""SOLUSDEV-235 (ADR-035) — the pure bundle validator over zip bytes."""

from __future__ import annotations

import hashlib
import zipfile

import pytest
from fixtures.extensions import (
    FULL_MANIFEST_TOML,
    PNG_MAGIC,
    build_zip,
    full_files,
    minimal_files,
    png_bytes,
    symlink_entry,
    with_manifest,
    without,
)
from solus_api.extensions.bundle import (
    MAX_COMPRESSION_RATIO,
    MAX_ENTRIES,
    BundleAsset,
    BundleError,
    BundleReport,
    inspect_bundle,
    read_member,
)
from solus_contracts.extension_manifest import LIMITS


def _problems(files: dict[str, bytes], **kw: object) -> list[str]:
    report = inspect_bundle(build_zip(files, **kw))  # type: ignore[arg-type]
    assert not report.ok
    return report.problems


# --- happy paths ---------------------------------------------------------------


def test_minimal_bundle_is_ok() -> None:
    data = build_zip(minimal_files())
    report = inspect_bundle(data)
    assert isinstance(report, BundleReport)
    assert report.ok and report.problems == []
    assert report.manifest is not None and report.manifest.extension.id == "bom"
    assert report.size_bytes == len(data)
    assert [a.path for a in report.assets] == ["OVERVIEW.md"]


def test_full_bundle_reports_every_store_facing_asset() -> None:
    report = inspect_bundle(build_zip(full_files()))
    assert report.ok, report.problems
    assets = {a.path: a for a in report.assets}
    assert set(assets) == {
        "icon.svg",
        "OVERVIEW.md",
        "PRIVACY.md",
        "docs/HOW.md",
        "shots/table.png",
        "shots/finding.webp",
    }
    assert assets["icon.svg"].media_type == "image/svg+xml"
    assert assets["OVERVIEW.md"].media_type == "text/markdown"
    assert assets["shots/table.png"].media_type == "image/png"
    assert assets["shots/finding.webp"].media_type == "image/webp"
    assert assets["OVERVIEW.md"].size_bytes == len(full_files()["OVERVIEW.md"])
    assert isinstance(report.assets[0], BundleAsset)


def test_content_hash_is_sha256_of_the_original_bytes_and_stable() -> None:
    data = build_zip(minimal_files())
    a, b = inspect_bundle(data), inspect_bundle(data)
    assert a.content_hash == b.content_hash == hashlib.sha256(data).hexdigest()
    assert inspect_bundle(build_zip(full_files())).content_hash != a.content_hash
    # Rejected bundles still get hashed — the review job stores the hash it refused.
    bad = inspect_bundle(b"PK\x03\x04junk")
    assert bad.content_hash == hashlib.sha256(b"PK\x03\x04junk").hexdigest()


def test_stored_and_directory_entries_are_tolerated() -> None:
    files = {**minimal_files(), "assets/": b""}
    report = inspect_bundle(build_zip(files, compression=zipfile.ZIP_STORED))
    assert report.ok, report.problems


def test_report_is_frozen() -> None:
    report = inspect_bundle(build_zip(minimal_files()))
    with pytest.raises(AttributeError):
        report.ok = False  # type: ignore[misc]


# --- not a zip / structure ------------------------------------------------------


@pytest.mark.parametrize(
    "data", [b"", b"not a zip at all", b"PK\x03\x04 but truncated", b"%PDF-1.4"]
)
def test_non_zip_bytes_are_a_problem_not_a_crash(data: bytes) -> None:
    report = inspect_bundle(data)
    assert not report.ok and report.manifest is None
    assert any("zip" in p for p in report.problems), report.problems


def test_bundle_over_the_byte_cap_is_refused_without_parsing() -> None:
    report = inspect_bundle(b"PK\x03\x04" + b"\0" * LIMITS.bundle_bytes)
    assert not report.ok
    assert any("exceeds" in p for p in report.problems)


def test_zip_bomb_high_ratio_entry_is_rejected() -> None:
    files = {**minimal_files(), "big.json": b"0" * (8 * 1024 * 1024)}
    problems = _problems(files)
    assert any("big.json" in p and "compression ratio" in p for p in problems), problems
    assert MAX_COMPRESSION_RATIO == 100


def test_total_uncompressed_over_the_cap_is_rejected() -> None:
    # Numbered lines deflate at a modest ~4:1 — every entry passes the per-entry
    # ratio and size guards and the zip itself is well under the cap, yet the
    # aggregate would inflate past 25 MiB on disk.
    lines = b"".join(b"%08d line of text\n" % i for i in range(220_000))  # ~4 MiB
    files = {**minimal_files(), **{f"d/{i}.json": lines for i in range(7)}}
    problems = _problems(files)
    assert any("total uncompressed" in p for p in problems), problems
    assert not any("compression ratio" in p for p in problems), problems


def test_too_many_entries_is_rejected() -> None:
    files = {**minimal_files(), **{f"a/{i}.json": b"{}" for i in range(MAX_ENTRIES)}}
    problems = _problems(files, compression=zipfile.ZIP_STORED)
    assert any("entries" in p for p in problems), problems


@pytest.mark.parametrize(
    ("name", "needle"),
    [
        ("../x.js", "traversal"),
        ("a/../../x.js", "traversal"),
        ("/x.js", "absolute"),
        ("a\\b.js", "backslash"),
        ("./x.js", "traversal"),
        ("a//b.js", "traversal"),
    ],
)
def test_unsafe_entry_names_are_rejected(name: str, needle: str) -> None:
    info = zipfile.ZipInfo(name)
    problems = _problems(minimal_files(), extra=[(info, b"x")])
    assert any(name in p and needle in p for p in problems), problems


def test_symlink_entries_are_rejected() -> None:
    problems = _problems(minimal_files(), extra=[symlink_entry("link.js", "../../etc/passwd")])
    assert any("link.js" in p and "symlink" in p for p in problems), problems


def test_duplicate_entries_are_rejected_case_insensitively() -> None:
    info = zipfile.ZipInfo("APP.JS")
    problems = _problems(minimal_files(), extra=[(info, b"x")])
    assert any("APP.JS" in p and "duplicate" in p for p in problems), problems


@pytest.mark.parametrize("name", ["run.exe", "setup.sh", "lib.wasm", "x.py", "noext", "a.HTML.bak"])
def test_entries_outside_the_suffix_allowlist_are_rejected(name: str) -> None:
    problems = _problems({**minimal_files(), name: b"x"})
    assert any(name in p and "not an allowed file type" in p for p in problems), problems


def test_upper_case_allowed_suffixes_are_fine() -> None:
    report = inspect_bundle(build_zip({**minimal_files(), "README.MD": b"# hi\n"}))
    assert report.ok, report.problems


# --- manifest presence ----------------------------------------------------------


def test_missing_manifest_is_rejected() -> None:
    problems = _problems(without(minimal_files(), "extension.toml"))
    assert problems == ["extension.toml: missing from the bundle root"]


def test_single_folder_wrapper_is_rejected_with_a_hint() -> None:
    wrapped = {f"bom/{k}": v for k, v in minimal_files().items()}
    problems = _problems(wrapped)
    assert len(problems) == 1 and "bom/" in problems[0] and "root" in problems[0], problems


def test_invalid_manifest_problems_come_through_and_stop_the_inspection() -> None:
    files = with_manifest(minimal_files(), FULL_MANIFEST_TOML.replace('id = "bom"', 'id = "B"'))
    report = inspect_bundle(build_zip(files))
    assert not report.ok and report.manifest is None
    assert any(p.startswith("extension.id:") for p in report.problems), report.problems


def test_non_utf8_manifest_is_a_problem() -> None:
    problems = _problems({**minimal_files(), "extension.toml": b"\xff\xfe\x00"})
    assert any("UTF-8" in p for p in problems), problems


# --- referenced files -----------------------------------------------------------


@pytest.mark.parametrize(
    ("missing", "field"),
    [
        ("widget.html", "views.widget.entry"),
        ("page.html", "views.page.entry"),
        ("window.html", "views.window.entry"),
        ("icon.svg", "views.page.icon"),
        ("OVERVIEW.md", "store.overview"),
        ("PRIVACY.md", "store.privacy_policy"),
        ("docs/HOW.md", "store.sections.0.body"),
        ("shots/finding.webp", "store.screenshots.1"),
    ],
)
def test_referenced_file_missing_names_the_field(missing: str, field: str) -> None:
    report = inspect_bundle(build_zip(without(full_files(), missing)))
    assert not report.ok and report.manifest is not None
    assert any(p.startswith(f"{field}:") and missing in p for p in report.problems), report.problems


def test_references_are_case_sensitive() -> None:
    files = without(full_files(), "OVERVIEW.md")
    files["overview.md"] = b"# x\n"
    problems = inspect_bundle(build_zip(files)).problems
    assert any(p.startswith("store.overview:") for p in problems), problems


def test_oversized_icon_is_rejected() -> None:
    files = {**full_files(), "icon.svg": full_files()["icon.svg"] + b" " * LIMITS.icon_bytes}
    problems = inspect_bundle(build_zip(files)).problems
    assert any("icon.svg" in p and "exceeds" in p for p in problems), problems


def test_oversized_overview_section_and_screenshot_are_rejected() -> None:
    files = {
        **full_files(),
        "OVERVIEW.md": b"#" * (LIMITS.overview_bytes + 1),
        "docs/HOW.md": b"#" * (LIMITS.section_bytes + 1),
        "shots/table.png": png_bytes(LIMITS.screenshot_bytes + 1),
    }
    problems = inspect_bundle(build_zip(files)).problems
    for path in ("OVERVIEW.md", "docs/HOW.md", "shots/table.png"):
        assert any(path in p and "exceeds" in p for p in problems), (path, problems)


def test_screenshot_magic_must_match_its_suffix() -> None:
    files = {**full_files(), "shots/table.png": b"GIF89a" + b"\0" * 32}
    problems = inspect_bundle(build_zip(files)).problems
    assert any("shots/table.png" in p and "PNG" in p for p in problems), problems
    files = {**full_files(), "shots/finding.webp": PNG_MAGIC + b"\0" * 32}
    problems = inspect_bundle(build_zip(files)).problems
    assert any("shots/finding.webp" in p and "WebP" in p for p in problems), problems


def test_bad_icon_svg_problems_are_prefixed_with_the_path() -> None:
    files = {**full_files(), "icon.svg": b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>'}
    problems = inspect_bundle(build_zip(files)).problems
    assert any(p.startswith("icon.svg: ") and "onload" in p for p in problems), problems


def test_static_check_problems_surface_in_the_report() -> None:
    files = {**minimal_files(), "app.js": b"fetch('https://x.example')\n"}
    report = inspect_bundle(build_zip(files))
    assert not report.ok and report.manifest is not None
    assert any(p.startswith("app.js:1:") for p in report.problems), report.problems


def test_read_member_enforces_its_cap_by_streaming_not_by_trusting_the_header() -> None:
    data = build_zip({**full_files(), "OVERVIEW.md": b"#" * (LIMITS.overview_bytes + 64)})
    with pytest.raises(BundleError, match="exceeds"):
        read_member(data, "OVERVIEW.md", max_bytes=LIMITS.overview_bytes)


# --- read_member ------------------------------------------------------------------


def test_read_member_returns_the_bytes() -> None:
    data = build_zip(full_files())
    assert read_member(data, "shots/table.png") == full_files()["shots/table.png"]
    assert read_member(data, "docs/HOW.md", max_bytes=LIMITS.section_bytes) == b"# How it works\n"


@pytest.mark.parametrize("path", ["nope.md", "../OVERVIEW.md", "/OVERVIEW.md", "run.exe", ""])
def test_read_member_refuses_missing_or_unsafe_paths(path: str) -> None:
    with pytest.raises(BundleError):
        read_member(build_zip(full_files()), path)


def test_read_member_on_non_zip_raises_bundle_error() -> None:
    with pytest.raises(BundleError):
        read_member(b"nope", "OVERVIEW.md")
