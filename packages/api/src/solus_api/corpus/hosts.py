"""Rights-holder host allowlist (docs/schemas/corpus-chunk.md rules 7 and 14).

A `source_url` must sit on a host the chunk's source class is allowed to cite —
the corpus equivalent of the tool-knowledge ingestion guard's vendor-domain
list. Mirrors, aggregators, and community hosts are absent on purpose: a URL
that is not the rights-holder's is a citation to a copy, and LICENSING.md §5
forbids exactly that. Citations in `further_reading`/`checked_against` may use
any host from any class (the union) — they are pointers, not provenance.

Entries starting with "." match any subdomain; others match exactly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from solus_api.corpus.enums import SourceClass

_GOVERNMENT: Final = frozenset(
    {
        "ntrs.nasa.gov",
        "nasa.gov",
        ".nasa.gov",
        "nist.gov",
        ".nist.gov",
        "assist.dla.mil",
        "quicksearch.dla.mil",
        "faa.gov",
        ".faa.gov",
        "osti.gov",
        ".osti.gov",
        "usgs.gov",
        ".usgs.gov",
        ".energy.gov",
        ".mil",
    }
)
_OPEN_TEXTBOOKS: Final = frozenset(
    {
        "openstax.org",
        ".openstax.org",
        "libretexts.org",
        ".libretexts.org",
        "open.umn.edu",
        "ocw.mit.edu",
        "github.com",
        "raw.githubusercontent.com",
        "gitlab.com",
        ".readthedocs.io",
        "creativecommons.org",
    }
)
_VENDORS: Final = frozenset(
    {
        "ti.com",
        ".ti.com",
        "analog.com",
        ".analog.com",
        "microchip.com",
        ".microchip.com",
        "st.com",
        ".st.com",
        "nxp.com",
        ".nxp.com",
        "nordicsemi.com",
        ".nordicsemi.com",
        "espressif.com",
        ".espressif.com",
        "bosch-sensortec.com",
        ".bosch-sensortec.com",
        "invensense.tdk.com",
        ".tdk.com",
        "infineon.com",
        ".infineon.com",
        "onsemi.com",
        ".onsemi.com",
        "renesas.com",
        ".renesas.com",
        "we-online.com",
        ".we-online.com",
        "molex.com",
        ".molex.com",
        "jst-mfg.com",
        ".jst-mfg.com",
        "jst.com",
        ".jst.com",
        "te.com",
        ".te.com",
        "nvidia.com",
        ".nvidia.com",
        "raspberrypi.com",
        ".raspberrypi.com",
        "arduino.cc",
        ".arduino.cc",
        "murata.com",
        ".murata.com",
        "vishay.com",
        ".vishay.com",
        "kemet.com",
        ".kemet.com",
        "maxlinear.com",
        "cypress.com",
        ".cypress.com",
        "semtech.com",
        ".semtech.com",
        "u-blox.com",
        ".u-blox.com",
        "amphenol.com",
        ".amphenol.com",
        "hirose.com",
        ".hirose.com",
        "wago.com",
        ".wago.com",
        "phoenixcontact.com",
        ".phoenixcontact.com",
        "maxonmotor.com",
        ".maxongroup.com",
        "maxongroup.com",
        "robotis.com",
        ".robotis.com",
        "dynamixel.com",
        "odriverobotics.com",
        ".odriverobotics.com",
        "pololu.com",
        ".pololu.com",
        "skf.com",
        ".skf.com",
        "misumi.com",
        ".misumi.com",
        "mcmaster.com",
        ".mcmaster.com",
        "igus.com",
        ".igus.com",
        "harmonicdrive.net",
        ".harmonicdrive.net",
    }
)
_STANDARDS: Final = frozenset(
    {
        "ipc.org",
        ".ipc.org",
        "iso.org",
        ".iso.org",
        "iec.ch",
        ".iec.ch",
        "asme.org",
        ".asme.org",
        "astm.org",
        ".astm.org",
        "sae.org",
        ".sae.org",
        "ul.com",
        ".ul.com",
        "standards.ieee.org",
        "ieeexplore.ieee.org",
        "jedec.org",
        ".jedec.org",
        "usb.org",
        ".usb.org",
        "nema.org",
        ".nema.org",
        "din.de",
        ".din.de",
        "bsigroup.com",
        ".bsigroup.com",
        "jisc.go.jp",
        ".jisc.go.jp",
        "ros.org",
        ".ros.org",
        "iso20022.org",
    }
)
_PROJECT_DOCS: Final = frozenset(
    {
        "ros.org",
        ".ros.org",
        "design.ros2.org",
        "mujoco.readthedocs.io",
        "mujoco.org",
        "github.com",
        "raw.githubusercontent.com",
        "gitlab.com",
        "kicad.org",
        ".kicad.org",
        "zephyrproject.org",
        ".zephyrproject.org",
        "freertos.org",
        ".freertos.org",
        "arduino.cc",
        ".arduino.cc",
        "platformio.org",
        ".platformio.org",
        "micro.ros.org",
        "foxglove.dev",
        ".foxglove.dev",
        ".readthedocs.io",
        "docs.python.org",
        "python.org",
        ".python.org",
        "cmake.org",
        ".cmake.org",
        "gcc.gnu.org",
        "llvm.org",
        ".llvm.org",
        "rust-lang.org",
        ".rust-lang.org",
        "developer.nvidia.com",
        "docs.nvidia.com",
        "raspberrypi.com",
        ".raspberrypi.com",
        "espressif.com",
        ".espressif.com",
        "onshape.com",
        ".onshape.com",
        "cad.onshape.com",
        "kernel.org",
        ".kernel.org",
        "opencv.org",
        ".opencv.org",
        "gazebosim.org",
        ".gazebosim.org",
        "wiki.ros.org",
        "docs.ros.org",
        "moveit.picknik.ai",
        "moveit.ai",
        ".moveit.ai",
        "navigation.ros.org",
        "control.ros.org",
        "urdf.org",
    }
)
_ACADEMIC: Final = frozenset(
    {
        "arxiv.org",
        ".arxiv.org",
        "doi.org",
        "dx.doi.org",
        "ieeexplore.ieee.org",
        "link.springer.com",
        "sciencedirect.com",
        ".sciencedirect.com",
        "journals.plos.org",
        "mdpi.com",
        ".mdpi.com",
        "frontiersin.org",
        ".frontiersin.org",
        "dl.acm.org",
        "nature.com",
        ".nature.com",
        "openreview.net",
        "proceedings.mlr.press",
        "journals.sagepub.com",
        "roboticsproceedings.org",
        ".roboticsproceedings.org",
    }
)

HOSTS_BY_CLASS: Final[Mapping[SourceClass, frozenset[str]]] = {
    SourceClass.SOLUS_AUTHORED: frozenset(),  # source_url is null by rule 5
    SourceClass.US_GOVERNMENT_WORK: _GOVERNMENT,
    SourceClass.OPEN_LICENSE_PERMISSIVE: _OPEN_TEXTBOOKS | _PROJECT_DOCS,
    SourceClass.OPEN_LICENSE_RESTRICTED: _OPEN_TEXTBOOKS | _PROJECT_DOCS,
    SourceClass.VENDOR_DOCUMENTATION: _VENDORS,
    SourceClass.DATASHEET: _VENDORS,
    SourceClass.STANDARDS_BODY: _STANDARDS,
    SourceClass.OPEN_SOURCE_PROJECT_DOCS: _PROJECT_DOCS,
    SourceClass.ACADEMIC_PAPER: _ACADEMIC,
}

ALL_HOSTS: Final[frozenset[str]] = frozenset().union(*HOSTS_BY_CLASS.values())


def _matches(host: str, entry: str) -> bool:
    if entry.startswith("."):
        return host.endswith(entry) and host != entry.lstrip(".")
    return host == entry


def is_allowed_host(host: str, source_class: SourceClass | None = None) -> bool:
    """True when `host` (lowercase, no port) is on the allowlist for
    `source_class`, or on any class's list when `source_class` is None."""
    allowed = ALL_HOSTS if source_class is None else HOSTS_BY_CLASS[source_class]
    return any(_matches(host, entry) for entry in allowed)
