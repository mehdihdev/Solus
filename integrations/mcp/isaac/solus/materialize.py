"""Install-time SO-101 cache materializer; never called by runtime tools.

Usage: python -m solus.materialize /path/to/pinned/Simulation/SO101
The source closure must match the committed manifest byte-for-byte. No network,
package installation, source execution, or replacement of unknown cache contents.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .assets import copy_verified_assets, verify_assets


def materialize(source: Path) -> str:
    fork = Path(__file__).resolve().parents[1]
    manifest = json.loads(Path(__file__).with_name("so101_manifest.json").read_text())
    expected = verify_assets(source, manifest)
    parent = fork / ".venv/assets"
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = parent / "so101"
    if destination.exists():
        if verify_assets(destination, manifest) != expected:
            raise ValueError("existing cache differs")
        return expected
    return copy_verified_assets(source, manifest, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    materialize(args.source)


if __name__ == "__main__":
    main()
