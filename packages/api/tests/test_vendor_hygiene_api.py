"""Phase 6 proof (c) — vendor-hygiene ratchet over the API's shared hardware code
(docs/architecture/hardware-onboarding.md §Layout: `solus_api/hardware/` is vendor-free; the
curated seed under `hardware/definitions/` is the only place a product may be named).

Word-boundary, case-insensitive, NO allowlist: every hit is reported.
"""

import re
from pathlib import Path
from typing import Final

import solus_api

SRC_ROOT: Final = Path(solus_api.__file__).resolve().parent
SWEEP_GLOBS: Final = (  # not hardware/definitions/ (the seed)
    "hardware/*.py",
    "livebench/*.py",
    "livebench/findings/*.py",
    "livebench/findings/rules/*.py",
    "checkers/*.py",
    "checkers/cells/*.py",
    "simulation/*.py",
    "simulation/providers/*.py",
    "software/*.py",
)
VENDOR_WORDS: Final = re.compile(
    r"\b(feetech|dynamixel|lerobot|sts3215|sts3250|scs0009|so-?10[01]|px4|pixhawk|odrive"
    r"|myactuator|mavlink|unitree|ur5e?|arduino|teensy|esp32|ch343|cp210x|ft232|pl2303"
    r"|xl330|xm430|robotis)\b",
    re.IGNORECASE,
)


def _swept_files() -> list[Path]:
    files = [p for pattern in SWEEP_GLOBS for p in sorted(SRC_ROOT.glob(pattern))]
    assert files, f"nothing to sweep under {SRC_ROOT}"
    return files


def test_shared_hardware_and_livebench_modules_name_no_vendor() -> None:
    offenders: list[str] = []
    for path in _swept_files():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            match = VENDOR_WORDS.search(line)
            if match:
                offenders.append(
                    f"{path.relative_to(SRC_ROOT)}:{lineno}: [{match.group(0)}] {line.strip()}"
                )
    assert not offenders, (
        "Vendors live in hardware/definitions/ (the seed) and livebench plugins, never in "
        "shared code. Offenders:\n" + "\n".join(offenders)
    )


def test_the_findings_package_is_under_the_ratchet() -> None:
    """P2's envelope package is swept from its first file (SOLUSDEV-321 P2-T1)."""
    swept = {p.relative_to(SRC_ROOT).as_posix() for p in _swept_files()}
    assert "livebench/findings/__init__.py" in swept


def test_the_checkers_package_is_under_the_ratchet() -> None:
    """The matrix rules and the fact store are swept from P3's first commit (SOLUSDEV-321
    P3-T1), so a part or a vendor named in `checkers/` fails here, not in review."""
    swept = {p.relative_to(SRC_ROOT).as_posix() for p in _swept_files()}
    assert "checkers/interface.py" in swept
    assert {"checkers/*.py", "checkers/cells/*.py"} <= set(SWEEP_GLOBS)


def test_the_simulation_package_is_under_the_ratchet() -> None:
    """The simulation ladder and its providers are swept from P4's first commit (SOLUSDEV-321
    P4-T1), so a part or a vendor named in `simulation/` fails here, not in review."""
    swept = {p.relative_to(SRC_ROOT).as_posix() for p in _swept_files()}
    assert "simulation/__init__.py" in swept
    assert {"simulation/*.py", "simulation/providers/*.py"} <= set(SWEEP_GLOBS)


def test_the_software_package_is_under_the_ratchet() -> None:
    """P6's ROS and policy readers are swept from the package's first commit (SOLUSDEV-321 P6):
    they read a workspace by structure, so a vendor or a product named in `software/` fails here,
    not in review."""
    swept = {p.relative_to(SRC_ROOT).as_posix() for p in _swept_files()}
    assert "software/__init__.py" in swept
    assert "software/*.py" in SWEEP_GLOBS


CONNECTION_PATHS = (
    "packages/api/src/solus_api/services/isaac_connection.py",
    "packages/api/src/solus_api/routers/isaac_connection.py",
    "integrations/mcp/isaac/solus/controller.py",
    "integrations/mcp/isaac/solus/server.py",
    "apps/desktop/src/renderer/src/lib/api/resources.isaacConnection.ts",
    "apps/desktop/src/renderer/src/features/workspace/IsaacConnectionPanel.tsx",
    "apps/desktop/src/renderer/src/features/workspace/ConnectedAccountsCard.tsx",
)


def connection_offenders(paths: list[Path]) -> list[str]:
    return [
        f"{path.name}:{index}:{match.group(0)}"
        for path in paths
        for index, line in enumerate(path.read_text().splitlines(), 1)
        if (match := VENDOR_WORDS.search(line))
    ]


def test_application_connection_paths_have_no_product_names() -> None:
    root = SRC_ROOT.parents[3]
    paths = [root / relative for relative in CONNECTION_PATHS]
    assert all(path.is_file() for path in paths)
    assert not connection_offenders(paths)


def test_connection_ratchet_catches_deliberately_reintroduced_product(tmp_path: Path) -> None:
    injected = tmp_path / "connection.ts"
    injected.write_text('const connect = () => offer("SO-101")\n')
    assert connection_offenders([injected]) == ["connection.ts:1:SO-101"]
