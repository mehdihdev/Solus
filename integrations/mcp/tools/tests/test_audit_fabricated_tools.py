"""The fabricated-data audit detects both shapes, and does not cry wolf.

The fixtures are the two idioms found in real fork targets, reduced to the
smallest code that exhibits them. They are hand-written, not copied — the point
is the SHAPE, and a fixture lifted from a repository would carry that
repository's licence into this tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit_fabricated_tools import audit  # noqa: E402

HONEST = '''
@mcp.tool()
async def list_features(input_data):
    """Reads the model."""
    result = await adapter.list_features()
    if result.is_success:
        return {"status": "success", "features": result.data}
    return {"status": "error", "message": result.error}
'''

NEVER_TOUCHES_CAD = '''
@mcp.tool()
async def get_material_properties():
    """Get the active material."""
    return {"status": "success", "material": {"name": "Steel, Plain Carbon", "density": 7850}}
'''

PROBE_FALLBACK = '''
@mcp.tool()
async def check_interference(input_data):
    """Check for interference."""
    if hasattr(adapter, "check_interference"):
        result = await adapter.check_interference(input_data)
        if result.is_success:
            return {"status": "success", "data": result.data}
        return {"status": "error", "message": result.error}
    return {"status": "success", "interference_found": False, "interferences": []}
'''

SECOND_ATTEMPT = '''
@mcp.tool()
async def export_step(input_data):
    """Export, via whichever adapter method exists."""
    if hasattr(adapter, "export_step"):
        result = await adapter.export_step(input_data)
    else:
        result = await adapter.export_file(input_data, "step")
    return {"status": "success", "data": result.data, "time": result.execution_time}
'''

DELEGATING = '''
@mcp.tool()
async def get_mass_properties(input_data=None):
    """Alias."""
    return await calculate_mass_properties(input_data)
'''


def write(tmp_path: Path, **modules: str) -> Path:
    for name, source in modules.items():
        (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    return tmp_path


def test_an_honest_tool_is_not_flagged(tmp_path: Path) -> None:
    report = audit(write(tmp_path, honest=HONEST))

    assert report.total == 1
    assert report.findings == []


def test_a_tool_that_never_touches_cad_is_flagged(tmp_path: Path) -> None:
    """Hardcoded steel returned as "the material" is the canonical case: the
    graph cannot tell it from a real reading, and neither can SOL."""
    report = audit(write(tmp_path, fake=NEVER_TOUCHES_CAD))

    assert [f.kind for f in report.findings] == ["never-touches-cad"]
    assert "Steel, Plain Carbon" in report.findings[0].evidence


def test_a_capability_probe_fallback_is_flagged(tmp_path: Path) -> None:
    """The worst one for Solus: when the adapter lacks the capability the caller
    is told the interference check PASSED."""
    report = audit(write(tmp_path, probe=PROBE_FALLBACK))

    assert [f.kind for f in report.findings] == ["probe-fallback"]
    assert "interference_found" in report.findings[0].evidence


def test_a_genuine_second_attempt_is_not_a_fallback_lie(tmp_path: Path) -> None:
    """`if hasattr … else: result = await adapter.other(...)` really did call the
    adapter. Flagging it would drown the real findings."""
    report = audit(write(tmp_path, second=SECOND_ATTEMPT))

    assert report.findings == []


def test_a_delegating_wrapper_is_classified_not_accused(tmp_path: Path) -> None:
    """It is judged by what it calls, which the audit reports separately."""
    report = audit(write(tmp_path, delegate=DELEGATING))

    assert report.delegating == ["get_mass_properties"]
    assert report.findings == []


def test_a_target_whose_handle_is_missing_would_report_a_vacuous_zero(tmp_path: Path) -> None:
    """The limitation, pinned so nobody reads a zero as a clean bill of health:
    CAD_HANDLES is per-target and must be checked against the tree first."""
    unknown_seam = NEVER_TOUCHES_CAD.replace(
        'return {"status": "success", "material"',
        "result = await some_unlisted_seam.get_material()\n"
        '    return {"status": "success", "material"',
    )

    report = audit(write(tmp_path, unknown=unknown_seam))

    # Still flagged here only because the return itself is a literal; a target
    # returning the seam's own payload would pass unexamined.
    assert report.total == 1


def test_the_tests_directory_of_the_target_is_ignored(tmp_path: Path) -> None:
    """Upstream test doubles fabricate on purpose; auditing them is noise."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_thing.py").write_text(NEVER_TOUCHES_CAD, encoding="utf-8")

    report = audit(tmp_path)

    assert report.total == 0
