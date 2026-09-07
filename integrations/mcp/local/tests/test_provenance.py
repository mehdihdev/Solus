"""SOLUSDEV-249 — PROVENANCE.md / SECURITY_REVIEW.md / README.md for a
Solus-authored server with NO upstream: every template section present, the
no-upstream posture stated, sign-offs present but BLANK (human-only), the
security review explicitly a DRAFT awaiting human sign-off."""

from .local_paths import (  # isort: skip
    FORK_DIR,
    FORK_README,
    PROVENANCE,
    PROVENANCE_TEMPLATE,
    SECURITY_REVIEW,
)


def _provenance() -> str:
    return PROVENANCE.read_text(encoding="utf-8")


def test_provenance_contains_every_template_section() -> None:
    headings = [
        line
        for line in PROVENANCE_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    assert headings
    text = _provenance()
    for heading in headings:
        assert heading in text, f"PROVENANCE.md is missing template section {heading!r}"


def test_provenance_states_solus_authored_with_no_upstream() -> None:
    text = _provenance()
    assert "Solus-authored" in text
    assert "no upstream" in text.lower()
    assert "MIT" in text
    assert not (FORK_DIR / "upstream").exists(), "nothing is vendored for a Solus-authored server"
    assert not (FORK_DIR / "vendor").exists()


def test_provenance_sign_offs_are_present_but_blank() -> None:
    text = _provenance()
    for reviewer in ("Reviewer 1", "Reviewer 2"):
        line = next((c for c in text.splitlines() if f"**{reviewer}:**" in c), None)
        assert line is not None, f"missing the {reviewer} sign-off line"
        assert "`<name>`" in line, f"{reviewer} sign-off must stay BLANK"


def test_provenance_names_the_three_tools_and_the_destructive_one() -> None:
    text = _provenance()
    for name in ("scan_folder", "folder_digest", "open_in_tool"):
        assert name in text
    section = text.split("## Exposed tools", 1)[1].split("## ", 1)[0]
    assert "open_in_tool" in section.split("Destructive tools", 1)[1]


def test_security_review_is_a_dated_draft_awaiting_human_sign_off() -> None:
    text = SECURITY_REVIEW.read_text(encoding="utf-8")
    assert "DRAFT" in text
    assert "awaiting human sign-off" in text
    for section in (
        "## 1. Supply chain",
        "## 2. Least privilege",
        "## 3. Sandbox posture",
        "## 4. Secret hygiene",
        "## 5. Untrusted I/O",
        "## 6. Destructive actions",
        "## 7. Code-review depth",
        "## 8. Update path",
        "## Declared sandbox posture",
    ):
        assert section in text, f"SECURITY_REVIEW.md is missing {section!r}"


def test_fork_readme_exists_and_describes_the_layout() -> None:
    assert FORK_README.is_file()
    text = FORK_README.read_text(encoding="utf-8")
    assert "bin/launch" in text
    assert "allowlist.yaml" in text
    assert "docs/api/local-folder.md" in text
