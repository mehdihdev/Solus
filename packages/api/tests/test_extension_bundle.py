"""SOLUSDEV-235 (ADR-035) — the pure bundle validator over zip bytes."""

from __future__ import annotations

import hashlib
import os
import secrets
import zipfile
import zlib

import pytest
from fixtures.extensions import (
    FULL_MANIFEST_TOML,
    PNG_MAGIC,
    RawEntry,
    build_zip,
    deflate_raw,
    full_files,
    minimal_files,
    png_bytes,
    raw_entry,
    raw_zip,
    symlink_entry,
    with_manifest,
    without,
)
from solus_api.extensions import bundle as bundle_module
from solus_api.extensions.bundle import (
    INFLATE_BUDGET_BYTES,
    MAX_COMPRESSION_RATIO,
    MAX_ENTRIES,
    MAX_MANIFEST_BYTES,
    MAX_TEXT_MEMBER_BYTES,
    RATIO_FLOOR_BYTES,
    BundleAsset,
    BundleError,
    BundleReport,
    inspect_bundle,
    inspect_bundle_structure,
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
    assert report.manifest is not None and report.manifest.extension.id == "bom-lite"
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


def test_ratio_guard_has_no_16_kib_exemption_a_5000_to_1_small_entry_is_rejected() -> None:
    """Phase 4 H1(3): the guard used to skip entries under 16 KiB uncompressed.
    Header sizes are what the guard sees, so the archive is hand-rolled with a
    15 KiB entry whose declared compress_size is 3 bytes — 5000:1."""
    zeros = b"\0" * (15 * 1024)
    bomb = RawEntry(
        "pad.js",
        deflate_raw(zeros),
        file_size=len(zeros),
        crc=zlib.crc32(zeros) & 0xFFFFFFFF,
        compress_size=3,
    )
    entries = [raw_entry(k, v) for k, v in minimal_files().items()] + [bomb]
    report = inspect_bundle(raw_zip(entries))
    assert not report.ok
    assert any("pad.js" in p and "compression ratio" in p for p in report.problems), report.problems


def test_entries_at_or_under_the_ratio_floor_are_exempt() -> None:
    """Deflate overhead dominates tiny members: a 1 KiB run of zeros deflates
    past 100:1 and must still be accepted (the total cap bounds it anyway)."""
    files = {**minimal_files(), "tiny.json": b"0" * RATIO_FLOOR_BYTES}
    report = inspect_bundle(build_zip(files))
    assert report.ok, report.problems
    assert RATIO_FLOOR_BYTES == 1024


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


# --- inflation bounds (Phase 4 H1) ------------------------------------------------


class _Inflation:
    """Wraps `_read_bounded` to record what the inspection actually inflated:
    the budget object is threaded through every call, so its depletion is the
    ground truth even when a read aborts mid-member."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.names: list[str] = []
        self.budgets: set[int] = set()
        self._budget_objects: list[object] = []
        original = bundle_module._read_bounded

        def spy(zf: object, name: str, max_bytes: int, budget: object) -> bytes:
            self.names.append(name)
            if id(budget) not in self.budgets:
                self.budgets.add(id(budget))
                self._budget_objects.append(budget)
            return original(zf, name, max_bytes, budget)  # type: ignore[arg-type]

        monkeypatch.setattr(bundle_module, "_read_bounded", spy)

    def inflated_bytes(self, limit: int) -> int:
        return sum(limit - b.remaining for b in self._budget_objects)  # type: ignore[attr-defined]


def test_text_members_are_capped_at_512_kib() -> None:
    files = {**minimal_files(), "app.js": os.urandom(MAX_TEXT_MEMBER_BYTES + 1)}
    problems = inspect_bundle(build_zip(files)).problems
    assert any("app.js" in p and "exceeds" in p for p in problems), problems
    assert MAX_TEXT_MEMBER_BYTES == 512 * 1024


def test_manifest_is_capped_at_64_kib() -> None:
    comment = b"# " + secrets.token_hex(MAX_MANIFEST_BYTES // 2).encode()
    padded = minimal_files()["extension.toml"] + b"\n" + comment
    problems = inspect_bundle(build_zip({**minimal_files(), "extension.toml": padded})).problems
    assert any("extension.toml" in p and "exceeds" in p for p in problems), problems
    assert MAX_MANIFEST_BYTES == 64 * 1024


def test_cumulative_inflation_budget_aborts_the_whole_inspection_with_one_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every `_read_bounded` call draws on ONE budget for the whole inspection;
    exhausting it ends the inspection with a single problem, not one per member."""
    budget = 8 * 1024
    monkeypatch.setattr(bundle_module, "INFLATE_BUDGET_BYTES", budget)
    spy = _Inflation(monkeypatch)
    files = {**minimal_files(), **{f"m/{i}.js": os.urandom(3000) for i in range(20)}}

    report = inspect_bundle(build_zip(files))

    assert not report.ok
    assert len(report.problems) == 1, report.problems
    assert "inspection aborted" in report.problems[0] and str(budget) in report.problems[0]
    assert spy.inflated_bytes(budget) <= budget + 3000
    assert len(spy.names) < 20  # it stopped reading


def test_thousand_entry_bomb_with_understated_headers_never_inflates_past_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4 H1(1): 1,000 members whose headers claim 24 KiB each (24 MiB in
    total — under every header-level guard) but whose DEFLATE streams inflate to
    8 MiB each. The inspection must reject it having inflated at most the
    budget, never the 8 GiB the streams hold."""
    spy = _Inflation(monkeypatch)
    real = b"\0" * (8 * 1024 * 1024)
    stream = deflate_raw(real)
    crc = zlib.crc32(real) & 0xFFFFFFFF
    claimed = 24 * 1024
    entries = [raw_entry(k, v) for k, v in minimal_files().items()] + [
        RawEntry(f"b/{i}.js", stream, file_size=claimed, crc=crc) for i in range(1_000)
    ]
    data = raw_zip(entries)
    assert len(data) < LIMITS.bundle_bytes

    report = inspect_bundle(data)

    assert not report.ok
    assert len(report.problems) == 1, report.problems[:3]
    assert spy.inflated_bytes(INFLATE_BUDGET_BYTES) <= INFLATE_BUDGET_BYTES
    assert INFLATE_BUDGET_BYTES == LIMITS.bundle_bytes


# --- inspect_bundle_structure (the request-path inspector) -----------------------


def test_structure_inspector_reads_only_the_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 4 H1(4): the publish route may inflate exactly one member — the
    root `extension.toml` — and still learns manifest, presence and header-size
    problems from the central directory alone."""
    spy = _Inflation(monkeypatch)
    files = {
        **full_files(),
        "widget.html": b"<html></html>" + os.urandom(MAX_TEXT_MEMBER_BYTES + 1),
        "shots/table.png": PNG_MAGIC + os.urandom(LIMITS.screenshot_bytes + 1),
    }
    files.pop("docs/HOW.md")

    report = inspect_bundle_structure(build_zip(files))

    assert spy.names == ["extension.toml"]
    assert not report.ok and report.manifest is not None
    assert report.manifest.extension.id == "bom-lite"
    assert any(
        p.startswith("store.sections.0.body:") and "docs/HOW.md" in p for p in report.problems
    )
    assert any("shots/table.png" in p and "exceeds" in p for p in report.problems)
    assert any("widget.html" in p and "exceeds" in p for p in report.problems)
    assert report.assets == []


def test_structure_inspector_accepts_what_only_content_checks_would_reject() -> None:
    """Content sniffing (icon reduction, PNG magic, static checks) is the review
    job's work: the structure pass is a superset-accepting, header-only gate."""
    bad_icon = {
        **full_files(),
        "icon.svg": b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>',
    }
    remote_script = {**minimal_files(), "app.js": b"fetch('https://x.example')\n"}
    for files in (bad_icon, remote_script):
        structure = inspect_bundle_structure(build_zip(files))
        assert structure.ok, structure.problems
        assert not inspect_bundle(build_zip(files)).ok
    good = inspect_bundle_structure(build_zip(full_files()))
    assert good.ok and good.content_hash == hashlib.sha256(build_zip(full_files())).hexdigest()


def test_structure_inspector_shares_the_zip_guards() -> None:
    for data, needle in (
        (b"not a zip", "zip"),
        (build_zip(without(minimal_files(), "extension.toml")), "missing"),
        (build_zip(minimal_files(), extra=[symlink_entry("l.js", "/etc/passwd")]), "symlink"),
    ):
        report = inspect_bundle_structure(data)
        assert not report.ok and any(needle in p for p in report.problems), report.problems


# --- manifest presence ----------------------------------------------------------


def test_missing_manifest_is_rejected() -> None:
    problems = _problems(without(minimal_files(), "extension.toml"))
    assert problems == ["extension.toml: missing from the bundle root"]


def test_single_folder_wrapper_is_rejected_with_a_hint() -> None:
    wrapped = {f"bom/{k}": v for k, v in minimal_files().items()}
    problems = _problems(wrapped)
    assert len(problems) == 1 and "bom/" in problems[0] and "root" in problems[0], problems


def test_invalid_manifest_problems_come_through_and_stop_the_inspection() -> None:
    files = with_manifest(
        minimal_files(), FULL_MANIFEST_TOML.replace('id = "bom-lite"', 'id = "B"')
    )
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
