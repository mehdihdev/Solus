"""Fixed-argv Flatpak adapter; neither executable nor app ID is caller input."""

from pathlib import Path

from solus.development.models import DevelopmentError

_PREFIX = ["/usr/bin/flatpak", "run", "--command=kicad-cli", "org.kicad.KiCad"]
_ERC = [
    "sch",
    "erc",
    "--format",
    "json",
    "--units",
    "mm",
    "--severity-all",
    "--exit-code-violations",
    "--output",
]
_EXPORT = ["sch", "export", "netlist", "--format", "kicadxml", "--output"]


def flatpak_argv(args: list[str]) -> list[str]:
    if args == ["version"]:
        return _PREFIX + args
    prefix = next((p for p in (_ERC, _EXPORT) if args[:-2] == p), None)
    if prefix is None:
        raise DevelopmentError("unsupported_value")
    if args[-2:] != ["-", "-"]:
        raise DevelopmentError("unsupported_value")
    # No host input/output pathname crosses the sandbox boundary. The fixed
    # helper validates the bounded byte closure received on stdin.
    helper = Path(__file__).with_name("flatpak_export.py")
    return [
        "/usr/bin/flatpak",
        "run",
        "--command=/usr/bin/python3",
        "org.kicad.KiCad",
        str(helper),
        "erc" if prefix == _ERC else "netlist",
    ]
