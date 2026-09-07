"""SOLUSDEV-250 — PROVENANCE.md / SECURITY_REVIEW.md / README.md for a
Solus-authored server with NO upstream: every template section present, the
no-upstream posture stated, sign-offs present but BLANK (human-only), the
security review explicitly a DRAFT awaiting human sign-off, the four acting
tools listed as destructive."""

from code_paths import (  # isort: skip
    FORK_DIR,
    FORK_README,
    PROVENANCE,
    PROVENANCE_TEMPLATE,
    SECURITY_REVIEW,
)

TOOLS = ("probe_environment", "plan", "create_environment", "install", "run", "test")
GATED = ("create_environment", "install", "run", "test")


def _provenance() -> str:
    return PROVENANCE.read_text(encoding="utf-8")


def test_provenance_contains_every_template_section() -> None:
    headings = [
        line
        for line in PROVENANCE_TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    assert headings
    for heading in headings:
        assert heading in _provenance(), heading


def test_provenance_states_solus_authored_with_no_upstream() -> None:
    text = _provenance()
    assert "Solus-authored" in text and "no upstream" in text.lower() and "MIT" in text
    assert not (FORK_DIR / "upstream").exists() and not (FORK_DIR / "vendor").exists()


def test_provenance_sign_offs_are_present_but_blank() -> None:
    text = _provenance()
    for reviewer in ("Reviewer 1", "Reviewer 2"):
        line = next((c for c in text.splitlines() if f"**{reviewer}:**" in c), None)
        assert line is not None and "`<name>`" in line, reviewer


def test_provenance_names_every_tool_and_the_destructive_four() -> None:
    text = _provenance()
    for name in TOOLS:
        assert name in text
    section = text.split("## Exposed tools", 1)[1].split("## ", 1)[0]
    destructive = section.split("Destructive tools", 1)[1]
    for name in GATED:
        assert name in destructive, name


def test_security_review_is_a_dated_draft_awaiting_human_sign_off() -> None:
    text = SECURITY_REVIEW.read_text(encoding="utf-8")
    assert "DRAFT" in text and "awaiting human sign-off" in text
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
        assert section in text, section
    assert "SEARCH_ROOTS" in text, "the pinned-roots residual must be recorded for reviewers"


def test_fork_readme_exists_and_describes_the_layout() -> None:
    text = FORK_README.read_text(encoding="utf-8")
    assert "bin/launch" in text and "allowlist.yaml" in text
    assert "docs/api/code-environment.md" in text
    for name in TOOLS:
        assert f"`{name}" in text, name
