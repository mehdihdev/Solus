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
SWEEP_GLOBS: Final = ("hardware/*.py", "livebench/*.py")  # not hardware/definitions/ (the seed)
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
