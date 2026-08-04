"""Deterministic generator for `solus_sample/solus_sample_large.net.xml` (SOLUSDEV-100 T3).

The large variant is the ArtifactRef-path fixture (T5): the same `solus_sample`
project shape — one STM32F030 MCU plus MPU-6050 IMU clusters, each with its I2C
pull-ups and decoupling — padded with enough valid clusters that the KiCad XML
netlist exceeds 512 KiB while staying under 1 MiB. Every component keeps a real
MPN `<property>` and every net keeps named nodes, so the file parses through
`solus_api.connectors.kicad_netlist.parse_kicad_netlist` with zero warnings.

BOTH this script and its output are committed. `test_fixture_integrity.py`
regenerates the text and asserts byte-equality against the committed file, so
the two cannot drift: change this script → rerun it (`python
gen_large_fixture.py`) and commit the regenerated output in the same commit.

Determinism: no randomness, no timestamps beyond the fixed design date, uuid5
over a fixed namespace.
"""

from __future__ import annotations

import uuid
from pathlib import Path

#: Cluster count tuned so the output lands mid-window between 512 KiB and 1 MiB.
CLUSTER_COUNT = 250

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://solus.dev/fixtures/solus_sample_large")
_ROOT_UUID = str(uuid.uuid5(_NS, "root-sheet"))

_MCU = (
    "U1",
    "STM32F030F4Px",
    "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    "https://www.st.com/resource/en/datasheet/stm32f030f4.pdf",
    "STM32F030F4P6",
    "MCU_ST_STM32F0",
    "STM32F030F4Px",
)
_IMU_DATASHEET = "https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Datasheet1.pdf"


def _uid(name: str) -> str:
    return str(uuid.uuid5(_NS, name))


def _comp(
    ref: str, value: str, footprint: str, datasheet: str, mpn: str, lib: str, part: str
) -> list[str]:
    return [
        f'    <comp ref="{ref}">',
        f"      <value>{value}</value>",
        f"      <footprint>{footprint}</footprint>",
        f"      <datasheet>{datasheet}</datasheet>",
        f'      <libsource lib="{lib}" part="{part}" description=""/>',
        f'      <property name="MPN" value="{mpn}"/>',
        '      <property name="Sheetname" value="Root"/>',
        '      <property name="Sheetfile" value="solus_sample.kicad_sch"/>',
        f'      <sheetpath names="/" tstamps="/{_ROOT_UUID}/"/>',
        f"      <tstamps>{_uid(f'sym-{ref}')}</tstamps>",
        "    </comp>",
    ]


def _cluster_refs(index: int) -> tuple[str, str, str, str]:
    """(imu, sda pull-up, scl pull-up, decoupling cap) refs for cluster *index*."""
    return (
        f"U{100 + index}",
        f"R{100 + 2 * index}",
        f"R{101 + 2 * index}",
        f"C{100 + index}",
    )


def _components(clusters: int) -> list[str]:
    lines = ["  <components>"]
    lines += _comp(*_MCU)
    for i in range(clusters):
        imu, r_sda, r_scl, cap = _cluster_refs(i)
        lines += _comp(
            imu,
            "MPU-6050",
            "Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm",
            _IMU_DATASHEET,
            "MPU-6050",
            "Sensor_Motion",
            "MPU-6050",
        )
        for res in (r_sda, r_scl):
            lines += _comp(
                res,
                "4.7k",
                "Resistor_SMD:R_0603_1608Metric",
                "~",
                "RC0603FR-074K7L",
                "Device",
                "R",
            )
        lines += _comp(
            cap,
            "100nF",
            "Capacitor_SMD:C_0603_1608Metric",
            "~",
            "CL10B104KB8NNNC",
            "Device",
            "C",
        )
    lines.append("  </components>")
    return lines


def _nets(clusters: int) -> list[str]:
    lines = ["  <nets>"]
    power_nodes = ['      <node ref="U1" pin="16" pinfunction="VDD" pintype="power_in"/>']
    ground_nodes = ['      <node ref="U1" pin="15" pinfunction="VSS" pintype="power_in"/>']
    code = 1
    for i in range(clusters):
        imu, r_sda, r_scl, cap = _cluster_refs(i)
        lines += [
            f'    <net code="{code}" name="SDA{i}" class="Default">',
            f'      <node ref="{imu}" pin="24" pinfunction="SDA" pintype="bidirectional"/>',
            f'      <node ref="{r_sda}" pin="2" pintype="passive"/>',
            "    </net>",
            f'    <net code="{code + 1}" name="SCL{i}" class="Default">',
            f'      <node ref="{imu}" pin="23" pinfunction="SCL" pintype="input"/>',
            f'      <node ref="{r_scl}" pin="2" pintype="passive"/>',
            "    </net>",
        ]
        code += 2
        power_nodes += [
            f'      <node ref="{imu}" pin="13" pinfunction="VDD" pintype="power_in"/>',
            f'      <node ref="{imu}" pin="8" pinfunction="VLOGIC" pintype="power_in"/>',
            f'      <node ref="{r_sda}" pin="1" pintype="passive"/>',
            f'      <node ref="{r_scl}" pin="1" pintype="passive"/>',
            f'      <node ref="{cap}" pin="1" pintype="passive"/>',
        ]
        ground_nodes += [
            f'      <node ref="{imu}" pin="18" pinfunction="GND" pintype="power_in"/>',
            f'      <node ref="{imu}" pin="9" pinfunction="AD0" pintype="input"/>',
            f'      <node ref="{cap}" pin="2" pintype="passive"/>',
        ]
    lines += [f'    <net code="{code}" name="+3V3" class="Default">', *power_nodes, "    </net>"]
    lines += [
        f'    <net code="{code + 1}" name="GND" class="Default">',
        *ground_nodes,
        "    </net>",
    ]
    lines.append("  </nets>")
    return lines


def build_text(clusters: int = CLUSTER_COUNT) -> str:
    """The full netlist text — deterministic for a given *clusters* count."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<export version="E">',
        "  <design>",
        "    <source>/work/robot/solus_sample/solus_sample.kicad_sch</source>",
        "    <date>2026-08-03T10:15:00+0000</date>",
        "    <tool>Eeschema 9.0.4</tool>",
        f'    <sheet number="1" name="/" tstamps="/{_ROOT_UUID}/">',
        "      <title_block>",
        "        <title>Solus sample - padded IMU array (ArtifactRef-path fixture)</title>",
        "        <company>Solus committed test fixture (SOLUSDEV-100 T3)</company>",
        "        <rev>A</rev>",
        "        <date>2026-08-03</date>",
        "        <source>solus_sample.kicad_sch</source>",
        "      </title_block>",
        "    </sheet>",
        "  </design>",
        *_components(clusters),
        *_nets(clusters),
        "</export>",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    out_path = Path(__file__).resolve().parent / "solus_sample" / "solus_sample_large.net.xml"
    text = build_text()
    out_path.write_text(text, encoding="utf-8")
    size = out_path.stat().st_size
    if not 512 * 1024 < size < 1024 * 1024:
        raise SystemExit(f"{out_path.name}: {size} bytes is outside the (512KiB, 1MiB) window")


if __name__ == "__main__":
    main()
