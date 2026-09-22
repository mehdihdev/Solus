"""Reviewed Arduino archive closure; no rolling index or runtime input."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

SOURCE_URL = "https://downloads.arduino.cc/packages/package_index.json"
SOURCE_SHA256 = "8b1dc76b3cd2420680db6e9f8ecfea6386a86fe16f0a7af47a966649625df50e"
SOURCE_RETRIEVED_AT = "2026-09-12T21:04:04Z"
CLI_VERSION = "1.5.1"
CLI_SHA256 = "b878632298958d61fd1eb19e70ac5d2e803d83db8930bc72dc6915eee6e8f433"


@dataclass(frozen=True, slots=True)
class Archive:
    """One exact reviewed archive, including the selected official host identifier."""

    package: str
    name: str
    version: str
    host: str | None
    url: str
    filename: str
    size_bytes: int
    sha256: str

    @property
    def id(self) -> str:
        return f"{self.package}/{self.name}@{self.version}"


ARCHIVES: tuple[Archive, ...] = (
    Archive(
        "arduino",
        "avr",
        "1.8.8",
        None,
        "https://downloads.arduino.cc/cores/staging/avr-1.8.8.tar.bz2",
        "avr-1.8.8.tar.bz2",
        7162150,
        "a234c2a43dcd01ce54be665806f183b8e6ec4e966d2e3e0c3358b63023d6390c",
    ),
    Archive(
        "builtin",
        "ctags",
        "5.8-arduino11",
        "aarch64-linux-gnu",
        "https://downloads.arduino.cc/tools/ctags-5.8-arduino11-pm-aarch64-linux-gnu.tar.bz2",
        "ctags-5.8-arduino11-pm-aarch64-linux-gnu.tar.bz2",
        100819,
        "89b6f8adb7b7124ebe2eb30970ea77c754cd2239e0d8a6b0102ae2a36416c6ef",
    ),
    Archive(
        "builtin",
        "dfu-discovery",
        "0.1.2",
        "arm64-linux-gnueabihf",
        "https://downloads.arduino.cc/discovery/dfu-discovery/dfu-discovery_v0.1.2_Linux_ARM64.tar.gz",
        "dfu-discovery_v0.1.2_Linux_ARM64.tar.gz",
        1617881,
        "4bda54b9031d5b1fb1af70d1c38bf1b1f8cfd0eb0cd81f6c3a43253c31dea92d",
    ),
    Archive(
        "builtin",
        "mdns-discovery",
        "1.1.0",
        "arm64-linux-gnueabihf",
        "https://downloads.arduino.cc/discovery/mdns-discovery/mdns-discovery_v1.1.0_Linux_ARM64.tar.gz",
        "mdns-discovery_v1.1.0_Linux_ARM64.tar.gz",
        2990900,
        "19597d8d15aac922813b34064deb870c0e5efc08d7430d15c8501768890f7725",
    ),
    Archive(
        "builtin",
        "serial-discovery",
        "1.5.2",
        "arm64-linux-gnueabihf",
        "https://downloads.arduino.cc/discovery/serial-discovery/serial-discovery_v1.5.2_Linux_ARM64.tar.gz",
        "serial-discovery_v1.5.2_Linux_ARM64.tar.gz",
        1998925,
        "489c81d0162e28e9c6602ecbce092e5a4669e7410d95067ed6dd1944e6a3cd34",
    ),
    Archive(
        "builtin",
        "serial-monitor",
        "0.15.0",
        "arm64-linux-gnueabihf",
        "https://downloads.arduino.cc/monitor/serial-monitor/serial-monitor_v0.15.0_Linux_ARM64.tar.gz",
        "serial-monitor_v0.15.0_Linux_ARM64.tar.gz",
        2299956,
        "bb16cf208befb19cef8710f753272f9e1ddbc1bd851d57be371f6d4b77af6c5e",
    ),
    Archive(
        "arduino",
        "arduinoOTA",
        "1.3.0",
        "aarch64-linux-gnu",
        "https://downloads.arduino.cc/tools/arduinoOTA-1.3.0-linux_arm64.tar.bz2",
        "arduinoOTA-1.3.0-linux_arm64.tar.bz2",
        2472427,
        "835ed8f37cffac37e979d1b0f6041559592d3d98be52f0e8611b76c4858e4113",
    ),
    Archive(
        "arduino",
        "avr-gcc",
        "7.3.0-atmel3.6.1-arduino7",
        "aarch64-linux-gnu",
        "https://downloads.arduino.cc/tools/avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        38045723,
        "03d322b9df6da17289e9e7c6233c34a8535d9c645c19efc772ba19e56914f339",
    ),
    Archive(
        "arduino",
        "avrdude",
        "8.0.0-arduino1",
        "aarch64-linux-gnu",
        "https://downloads.arduino.cc/tools/avrdude_8.0-arduino.1_Linux_ARM64.tar.gz",
        "avrdude_8.0-arduino.1_Linux_ARM64.tar.gz",
        1565761,
        "031f212bdcb77e2ea13895f07ab4a0c254963f8f1bbd3b8797d3363a6a2e95e3",
    ),
)


def validate_archive_closure(records: tuple[Archive, ...]) -> None:
    """Reject any replacement, omission, duplicate or extra helper."""
    if records != ARCHIVES:
        raise ValueError("integrity_mismatch")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def frozen_package_index() -> bytes:
    """Return an unsigned derivative containing only the reviewed ARM64 closure."""
    platform_record = json.loads(_PLATFORM_JSON)
    packages = []
    for name in ("arduino", "builtin"):
        tools = []
        for archive in ARCHIVES[1:]:
            if archive.package != name:
                continue
            tools.append(
                {
                    "name": archive.name,
                    "version": archive.version,
                    "systems": [
                        {
                            "host": archive.host,
                            "url": archive.url,
                            "archiveFileName": archive.filename,
                            "checksum": "SHA-256:" + archive.sha256,
                            "size": str(archive.size_bytes),
                        }
                    ],
                }
            )
        packages.append(
            {
                "name": name,
                "maintainer": "Arduino",
                "websiteURL": "https://www.arduino.cc/",
                "email": "packages@arduino.cc",
                "help": {"online": "https://www.arduino.cc/"},
                "platforms": [platform_record] if name == "arduino" else [],
                "tools": tools,
            }
        )
    return canonical_bytes({"packages": packages})


def empty_library_index() -> bytes:
    return canonical_bytes({"libraries": []})


def manifest_sha256() -> str:
    """Digest of source provenance and the complete curated derivative."""
    return hashlib.sha256(
        canonical_bytes(
            {
                "source_sha256": SOURCE_SHA256,
                "derivative_sha256": hashlib.sha256(frozen_package_index()).hexdigest(),
                "cli_sha256": CLI_SHA256,
            }
        )
    ).hexdigest()


_PLATFORM_JSON = (
    '{"architecture":"avr","archiveFileName":"avr-1.8.8.tar.bz2","boards":[{"name":"Arduino Y'
    '\\u00fan"},{"name":"Arduino UNO"},{"name":"Arduino UNO Mini"},{"name":"Arduino UNO WiFi"}'
    ',{"name":"Arduino Diecimila"},{"name":"Arduino Nano"},{"name":"Arduino Mega"},{"name":"A'
    'rduino Mega ADK"},{"name":"Arduino Leonardo"},{"name":"Arduino Leonardo Ethernet"},{"nam'
    'e":"Arduino Micro"},{"name":"Arduino Esplora"},{"name":"Arduino Mini"},{"name":"Arduino '
    'Ethernet"},{"name":"Arduino Fio"},{"name":"Arduino BT"},{"name":"Arduino LilyPad USB"},{'
    '"name":"Arduino LilyPad"},{"name":"Arduino Pro"},{"name":"Arduino ATMegaNG"},{"name":"Ar'
    'duino Robot Control"},{"name":"Arduino Robot Motor"},{"name":"Arduino Gemma"},{"name":"A'
    'dafruit Circuit Playground"},{"name":"Arduino Y\\u00fan Mini"},{"name":"Arduino Industria'
    'l 101"},{"name":"Linino One"}],"category":"Arduino","checksum":"SHA-256:a234c2a43dcd01ce'
    '54be665806f183b8e6ec4e966d2e3e0c3358b63023d6390c","help":{"online":"https://www.arduino.'
    'cc/en/Reference/HomePage"},"name":"Arduino AVR Boards","size":"7162150","toolsDependenci'
    'es":[{"name":"arduinoOTA","packager":"arduino","version":"1.3.0"},{"name":"avr-gcc","pac'
    'kager":"arduino","version":"7.3.0-atmel3.6.1-arduino7"},{"name":"avrdude","packager":"ar'
    'duino","version":"8.0.0-arduino1"}],"url":"https://downloads.arduino.cc/cores/staging/av'
    'r-1.8.8.tar.bz2","version":"1.8.8"}'
)


# Exact reviewed archive member, target and kind; no general links are allowed.
REVIEWED_LINKS: tuple[tuple[str, str, str, str], ...] = (
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/bin/avr-gcc",
        "avr/bin/avr-gcc-7.3.0",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/bin/avr-g++",
        "avr/bin/avr-c++",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/bin/avr-ld",
        "avr/bin/avr-ld.bfd",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/libexec/gcc/avr/7.3.0/liblto_plugin.so.0",
        "liblto_plugin.so.0.0.0",
        "symbolic",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/libexec/gcc/avr/7.3.0/liblto_plugin.so",
        "liblto_plugin.so.0.0.0",
        "symbolic",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/ld",
        "avr/bin/avr-ld.bfd",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/strip",
        "avr/bin/avr-strip",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/ld.bfd",
        "avr/bin/avr-ld.bfd",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/as",
        "avr/bin/avr-as",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/objcopy",
        "avr/bin/avr-objcopy",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/ranlib",
        "avr/bin/avr-ranlib",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/nm",
        "avr/bin/avr-nm",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/ar",
        "avr/bin/avr-ar",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/objdump",
        "avr/bin/avr-objdump",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/avr/bin/readelf",
        "avr/bin/avr-readelf",
        "hard",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/lib/gcc/avr/7.3.0/plugin/libcp1plugin.so.0",
        "libcp1plugin.so.0.0.0",
        "symbolic",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/lib/gcc/avr/7.3.0/plugin/libcc1plugin.so",
        "libcc1plugin.so.0.0.0",
        "symbolic",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/lib/gcc/avr/7.3.0/plugin/libcc1plugin.so.0",
        "libcc1plugin.so.0.0.0",
        "symbolic",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/lib/gcc/avr/7.3.0/plugin/libcp1plugin.so",
        "libcp1plugin.so.0.0.0",
        "symbolic",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/lib/libcc1.so",
        "libcc1.so.0.0.0",
        "symbolic",
    ),
    (
        "avr-gcc-7.3.0-atmel3.6.1-arduino7-aarch64-pc-linux-gnu.tar.bz2",
        "avr/lib/libcc1.so.0",
        "libcc1.so.0.0.0",
        "symbolic",
    ),
)
